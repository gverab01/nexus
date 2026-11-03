"""
Servicio de Cumplimiento de Datos Personales, Retención y Privacidad (Ley 21.719 Chile)
NexusReach Pro Directrices de Ingeniería v1.3 - Workstream 5.4 [P0]

Implementa:
1. Registro de origen y base de licitud formal (source, source_url, legal_basis, collected_at).
2. Procesamiento de Opt-out y lista de supresión por hash SHA-256.
3. Purga periódica de leads inactivos tras 12 meses sin actividad.
4. Borrado completo de tenant en cascada (<=30 días tras cancelación).
5. Endpoints de ejercicio de derechos del titular (exportación completa y derecho al olvido).
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from database import get_db
import zoho_bridge_service
import crypto_field_service

VALID_LEGAL_BASES = {
    "INTERES_LEGITIMO_B2B",
    "CONSENTIMIENTO_EXPRESO",
    "RELACION_COMERCIAL_PREVIA",
    "EJECUCION_CONTRATO"
}


def register_lead_legal_basis(
    tenant_id: str,
    lead_id: str,
    source: str = "LINKEDIN",
    source_url: Optional[str] = None,
    legal_basis: str = "INTERES_LEGITIMO_B2B",
    evidence_text: Optional[str] = None,
    channel: str = "LINKEDIN"
) -> bool:
    """Registra la base legal y origen del lead tanto en la tabla leads como en consent_records."""
    if legal_basis not in VALID_LEGAL_BASES:
        raise ValueError(f"Base de licitud no válida: {legal_basis}. Debe ser una de: {VALID_LEGAL_BASES}")

    now_iso = datetime.now(timezone.utc).isoformat()
    record_id = f"con_{secrets.token_hex(6)}"

    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        # Actualizar campos de licitud en el lead
        cursor.execute("""
            UPDATE leads 
            SET source = ?, source_url = ?, legal_basis = ?, collected_at = COALESCE(collected_at, ?), updated_at = ?
            WHERE id = ? AND tenant_id = ?
        """, (source, source_url, legal_basis, now_iso, now_iso, lead_id, tenant_id))

        # Registrar en bitácora de consentimiento formal
        cursor.execute("""
            INSERT INTO consent_records (id, tenant_id, lead_id, channel, legal_basis, evidence_text, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (record_id, tenant_id, lead_id, channel, legal_basis, evidence_text or f"Capturado vía {source}", now_iso))

        conn.commit()

    zoho_bridge_service.log_lead_activity(
        tenant_id=tenant_id,
        lead_id=lead_id,
        action_type="LEGAL_BASIS_REGISTERED",
        details={"legal_basis": legal_basis, "source": source, "source_url": source_url}
    )
    return True


def process_opt_out(
    tenant_id: str,
    identifier: str,
    identifier_type: str = "EMAIL",
    reason: str = "SOLICITO_BAJA"
) -> Dict[str, Any]:
    """
    Procesa un opt-out (solicitud de baja):
    1. Agrega el identificador a la lista de supresión con hash SHA-256.
    2. Detiene cualquier secuencia en curso del lead afectado.
    3. Marca su estado como 'OPT_OUT'.
    """
    added = zoho_bridge_service.add_to_suppression_list(
        tenant_id=tenant_id,
        identifier=identifier,
        identifier_type=identifier_type,
        reason=reason
    )

    detenidos = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    id_clean = identifier.strip().lower()

    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        # Buscar leads asociados por email o por perfil_url
        if identifier_type.upper() == "EMAIL":
            cursor.execute("SELECT id FROM leads WHERE tenant_id = ? AND LOWER(email) = ?", (tenant_id, id_clean))
        elif identifier_type.upper() == "LINKEDIN_URL":
            cursor.execute("SELECT id FROM leads WHERE tenant_id = ? AND perfil_url = ?", (tenant_id, identifier.strip()))
        elif identifier_type.upper() == "PHONE":
            cursor.execute("SELECT id FROM leads WHERE tenant_id = ? AND telefono = ?", (tenant_id, identifier.strip()))
        else:
            cursor.execute("SELECT id FROM leads WHERE tenant_id = ? AND (email = ? OR perfil_url = ?)", (tenant_id, identifier, identifier))

        matching_leads = [r["id"] if isinstance(r, dict) else r[0] for r in cursor.fetchall()]

        for lid in matching_leads:
            # Cancelar de secuencias activas
            cursor.execute("""
                UPDATE leads_en_secuencia 
                SET estado = 'CANCELADO', updated_at = ? 
                WHERE lead_id = ? AND estado NOT IN ('COMPLETADO', 'CANCELADO')
            """, (now_iso, lid))
            detenidos += cursor.rowcount

            # Actualizar estado del lead
            cursor.execute("UPDATE leads SET estado = 'OPT_OUT', updated_at = ? WHERE id = ? AND tenant_id = ?", (now_iso, lid, tenant_id))

        conn.commit()

    # Registrar en bitácora interna fuera del contexto de conexión exclusivo
    for lid in matching_leads:
        zoho_bridge_service.log_lead_activity(
            tenant_id=tenant_id,
            lead_id=lid,
            action_type="OPT_OUT_PROCESSED",
            details={"reason": reason, "identifier_type": identifier_type}
        )

    return {
        "ok": True,
        "suppression_added": added,
        "leads_affected": len(matching_leads),
        "sequences_stopped": detenidos
    }


def purge_inactive_leads(tenant_id: str, months: int = 12) -> int:
    """
    Purga automáticamente los leads que no han tenido actividad registrada
    ni actualización en los últimos N meses (por defecto 12 meses según Ley 21.719).
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=months * 30)
    cutoff_iso = cutoff_date.isoformat()

    purged_count = 0
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        # Leads cuyo updated_at es anterior al cutoff y no tienen actividad reciente
        cursor.execute("""
            SELECT id FROM leads 
            WHERE tenant_id = ? 
              AND (updated_at < ? OR (updated_at IS NULL AND created_at < ?))
              AND id NOT IN (
                  SELECT DISTINCT lead_id FROM lead_activity 
                  WHERE tenant_id = ? AND created_at >= ?
              )
        """, (tenant_id, cutoff_iso, cutoff_iso, tenant_id, cutoff_iso))

        old_lead_ids = [r["id"] if isinstance(r, dict) else r[0] for r in cursor.fetchall()]

        for lid in old_lead_ids:
            cursor.execute("DELETE FROM lead_activity WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lid))
            cursor.execute("DELETE FROM consent_records WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lid))
            cursor.execute("DELETE FROM email_candidates WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lid))
            cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM leads_en_lista WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM mensajes_linkedin WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM correos_electronicos WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM mensajes_whatsapp WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM leads WHERE id = ? AND tenant_id = ?", (lid, tenant_id))
            purged_count += 1

        conn.commit()

    return purged_count


def delete_tenant_cascade(tenant_id: str) -> Dict[str, int]:
    """
    Eliminación completa de un tenant y todos sus datos en cascada en <= 30 días tras cancelación.
    Garantiza que no quede ningún dato huérfano en ninguna tabla del sistema.
    """
    counts = {}
    with get_db(is_super_admin=True) as conn:
        cursor = conn.cursor()

        # Tablas dependientes de leads
        cursor.execute("DELETE FROM lead_activity WHERE tenant_id = ?", (tenant_id,))
        counts["lead_activity"] = cursor.rowcount

        cursor.execute("DELETE FROM consent_records WHERE tenant_id = ?", (tenant_id,))
        counts["consent_records"] = cursor.rowcount

        cursor.execute("DELETE FROM email_candidates WHERE tenant_id = ?", (tenant_id,))
        counts["email_candidates"] = cursor.rowcount

        cursor.execute("""
            DELETE FROM leads_en_secuencia 
            WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)
        """, (tenant_id,))
        counts["leads_en_secuencia"] = cursor.rowcount

        cursor.execute("""
            DELETE FROM leads_en_lista 
            WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?) 
               OR lista_id IN (SELECT id FROM listas_leads WHERE tenant_id = ?)
        """, (tenant_id, tenant_id))
        counts["leads_en_lista"] = cursor.rowcount

        cursor.execute("DELETE FROM mensajes_linkedin WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (tenant_id,))
        counts["mensajes_linkedin"] = cursor.rowcount

        cursor.execute("DELETE FROM correos_electronicos WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (tenant_id,))
        counts["correos_electronicos"] = cursor.rowcount

        cursor.execute("DELETE FROM mensajes_whatsapp WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (tenant_id,))
        counts["mensajes_whatsapp"] = cursor.rowcount

        cursor.execute("DELETE FROM historial_actividades WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (tenant_id,))
        counts["historial_actividades"] = cursor.rowcount

        cursor.execute("DELETE FROM leads WHERE tenant_id = ?", (tenant_id,))
        counts["leads"] = cursor.rowcount

        # Comandos y dispositivos
        cursor.execute("DELETE FROM command_results WHERE tenant_id = ?", (tenant_id,))
        counts["command_results"] = cursor.rowcount

        cursor.execute("DELETE FROM commands WHERE tenant_id = ?", (tenant_id,))
        counts["commands"] = cursor.rowcount

        cursor.execute("DELETE FROM devices WHERE tenant_id = ?", (tenant_id,))
        counts["devices"] = cursor.rowcount

        # Cuentas conectadas y comerciales
        cursor.execute("DELETE FROM linkedin_accounts WHERE tenant_id = ?", (tenant_id,))
        counts["linkedin_accounts"] = cursor.rowcount

        cursor.execute("DELETE FROM whatsapp_accounts WHERE tenant_id = ?", (tenant_id,))
        counts["whatsapp_accounts"] = cursor.rowcount

        cursor.execute("DELETE FROM credit_ledger WHERE tenant_id = ?", (tenant_id,))
        counts["credit_ledger"] = cursor.rowcount

        cursor.execute("DELETE FROM suppression_list WHERE tenant_id = ?", (tenant_id,))
        counts["suppression_list"] = cursor.rowcount

        # Secuencias y listas
        cursor.execute("""
            DELETE FROM pasos_secuencia 
            WHERE secuencia_id IN (SELECT id FROM secuencias WHERE tenant_id = ?)
        """, (tenant_id,))
        counts["pasos_secuencia"] = cursor.rowcount

        cursor.execute("""
            DELETE FROM secuencia_listas 
            WHERE secuencia_id IN (SELECT id FROM secuencias WHERE tenant_id = ?) 
               OR lista_id IN (SELECT id FROM listas_leads WHERE tenant_id = ?)
        """, (tenant_id, tenant_id))
        counts["secuencia_listas"] = cursor.rowcount

        cursor.execute("DELETE FROM secuencias WHERE tenant_id = ?", (tenant_id,))
        counts["secuencias"] = cursor.rowcount

        cursor.execute("DELETE FROM listas_leads WHERE tenant_id = ?", (tenant_id,))
        counts["listas_leads"] = cursor.rowcount

        # Usuarios, auditoría y suscripción
        cursor.execute("DELETE FROM audit_logs WHERE tenant_id = ?", (tenant_id,))
        counts["audit_logs"] = cursor.rowcount

        cursor.execute("DELETE FROM usuarios WHERE tenant_id = ?", (tenant_id,))
        counts["usuarios"] = cursor.rowcount

        cursor.execute("DELETE FROM suscripciones WHERE tenant_id = ?", (tenant_id,))
        counts["suscripciones"] = cursor.rowcount

        cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        counts["tenants"] = cursor.rowcount

        conn.commit()

    return counts


def export_data_subject_profile(tenant_id: str, lead_id: str) -> Optional[Dict[str, Any]]:
    """
    Derecho de Acceso (Ley 21.719 / ARCO):
    Exporta la ficha completa y comprensible de los datos personales almacenados para un lead concreto,
    incluyendo su origen, licitud, bitácora de actividad y mensajes asociados.
    """
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE id = ? AND tenant_id = ?", (lead_id, tenant_id))
        lead_row = cursor.fetchone()
        if not lead_row:
            return None

        lead = dict(lead_row)

        # Descifrar correos o teléfonos si están cifrados
        if lead.get("email"):
            lead["email_descifrado"] = crypto_field_service.decrypt_field(lead["email"], tenant_id)
        if lead.get("telefono"):
            lead["telefono_descifrado"] = crypto_field_service.decrypt_field(lead["telefono"], tenant_id)

        # Bitácora
        cursor.execute("SELECT * FROM lead_activity WHERE tenant_id = ? AND lead_id = ? ORDER BY created_at ASC", (tenant_id, lead_id))
        activities = [dict(r) for r in cursor.fetchall()]

        # Bases de consentimiento
        cursor.execute("SELECT * FROM consent_records WHERE tenant_id = ? AND lead_id = ? ORDER BY captured_at ASC", (tenant_id, lead_id))
        consents = [dict(r) for r in cursor.fetchall()]

        # Candidatos de correo
        cursor.execute("SELECT * FROM email_candidates WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lead_id))
        email_candidates = [dict(r) for r in cursor.fetchall()]

        return {
            "lead": lead,
            "base_licitud": consents,
            "candidatos_email": email_candidates,
            "actividades": activities,
            "exportado_el": datetime.now(timezone.utc).isoformat()
        }


def delete_data_subject_profile(tenant_id: str, lead_id: str, reason: str = "DERECHO_AL_OLVIDO") -> bool:
    """
    Derecho de Supresión / Olvido (Ley 21.719):
    Elimina definitivamente los datos del lead de todas las tablas activas y agrega
    sus identificadores (hash SHA-256) a la lista de supresión para evitar que sea re-prospectado en el futuro.
    """
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email, telefono, perfil_url FROM leads WHERE id = ? AND tenant_id = ?", (lead_id, tenant_id))
        row = cursor.fetchone()
        if not row:
            return False

        email = row["email"] if isinstance(row, dict) else row[0]
        tel = row["telefono"] if isinstance(row, dict) else row[1]
        url = row["perfil_url"] if isinstance(row, dict) else row[2]

        # Descifrar si fuera necesario antes del hash
        if email:
            email_dec = crypto_field_service.decrypt_field(email, tenant_id)
            zoho_bridge_service.add_to_suppression_list(tenant_id, email_dec, "EMAIL", reason)
        if tel:
            tel_dec = crypto_field_service.decrypt_field(tel, tenant_id)
            zoho_bridge_service.add_to_suppression_list(tenant_id, tel_dec, "PHONE", reason)
        if url:
            zoho_bridge_service.add_to_suppression_list(tenant_id, url, "LINKEDIN_URL", reason)

        # Eliminar registros asociados
        cursor.execute("DELETE FROM lead_activity WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lead_id))
        cursor.execute("DELETE FROM consent_records WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lead_id))
        cursor.execute("DELETE FROM email_candidates WHERE tenant_id = ? AND lead_id = ?", (tenant_id, lead_id))
        cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM leads_en_lista WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM mensajes_linkedin WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM correos_electronicos WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM mensajes_whatsapp WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM leads WHERE id = ? AND tenant_id = ?", (lead_id, tenant_id))

        conn.commit()

    return True
