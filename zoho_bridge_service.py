"""
Servicio del Zoho Bridge Transitorio y Deduplicación Interna (Workstream 5.2 [P0])
NexusReach Pro Directrices de Ingeniería v1.3

Funcionalidades:
1. Gobernanza 100% en la Nube: lógica de decisión en el servidor; el cliente solo ejecuta comandos firmados.
2. Feature Flag por Tenant ('zoho_sync_activo') y Org ID dinámico ('zoho_org_id').
3. Deduplicación Interna DB-First: comprobación de lista de supresión y colisión de representantes antes de Zoho.
4. Bitácora Interna ('lead_activity') como fuente única de verdad.
5. Emisión de las 4 acciones de lista cerrada ('ZOHO_FIND_LEAD', 'ZOHO_UPSERT_LEAD', 'ZOHO_SET_STATUS', 'ZOHO_ADD_NOTE').
6. Exportación CSV nativa y trazable de leads con historial de actividad por tenant.
7. Control de cadencia y parada preventiva ante errores o pérdida de sesión sin bucles infinitos.
"""

import os
import csv
import io
import json
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from database import get_db
import command_signing_service

# Constantes de Cadencia y Cuotas de Seguridad para Zoho Bridge
MAX_ZOHO_OPS_PER_HOUR = 30
MAX_ZOHO_OPS_PER_DAY = 150

# Memoria de control de cadencia por (tenant_id, device_id): lista de timestamps
_zoho_rate_window: Dict[str, List[datetime]] = {}


# ==============================================================================
# 1. CONFIGURACIÓN Y FEATURE FLAGS POR TENANT
# ==============================================================================

def get_zoho_config(tenant_id: str) -> Dict[str, Any]:
    """Retorna la configuración y estado del feature flag de Zoho para el tenant."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT zoho_sync_activo, zoho_org_id FROM tenants WHERE id = ?", (tenant_id,))
        row = cursor.fetchone()
        if not row:
            return {"zoho_sync_activo": False, "zoho_org_id": None}
        activo = bool(row["zoho_sync_activo"] if isinstance(row, dict) else row[0])
        org_id = row["zoho_org_id"] if isinstance(row, dict) else row[1]
        return {
            "zoho_sync_activo": activo,
            "zoho_org_id": org_id
        }


def set_zoho_config(tenant_id: str, activo: bool, org_id: Optional[str] = None) -> bool:
    """Actualiza la activación del flag y el identificador de organización para un tenant."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tenants 
            SET zoho_sync_activo = ?, zoho_org_id = ?, updated_at = ?
            WHERE id = ?
        """, (1 if activo else 0, org_id, now_iso, tenant_id))
        conn.commit()
    return True


def is_zoho_bridge_enabled(tenant_id: str) -> bool:
    """Verifica si el módulo Zoho Bridge está habilitado para el tenant."""
    config = get_zoho_config(tenant_id)
    return config.get("zoho_sync_activo", False)


# ==============================================================================
# 2. LISTA DE SUPRESIÓN (OPT-OUT CON HASH SHA-256)
# ==============================================================================

def hash_identifier(value: str) -> str:
    """Genera hash SHA-256 normalizado para proteger datos en la lista de supresión."""
    if not value:
        return ""
    normalized = value.strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def add_to_suppression_list(
    tenant_id: str,
    identifier: str,
    identifier_type: str,
    reason: str = "OPT_OUT"
) -> bool:
    """Agrega un identificador a la lista de supresión del tenant con hash irreversible."""
    ident_hash = hash_identifier(identifier)
    if not ident_hash:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    record_id = str(uuid.uuid4())

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO suppression_list (id, tenant_id, identifier_hash, identifier_type, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (record_id, tenant_id, ident_hash, identifier_type.upper(), reason, now_iso))
        conn.commit()
    return True


def is_suppressed(
    tenant_id: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    profile_url: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """Comprueba si alguno de los identificadores del lead figura en la lista de supresión del tenant."""
    hashes_to_check = []
    if email:
        hashes_to_check.append(("EMAIL", hash_identifier(email)))
    if phone:
        hashes_to_check.append(("PHONE", hash_identifier(phone)))
    if profile_url:
        clean_url = profile_url.split("?")[0].rstrip("/")
        hashes_to_check.append(("LINKEDIN_URL", hash_identifier(clean_url)))

    if not hashes_to_check:
        return False, None

    with get_db() as conn:
        cursor = conn.cursor()
        for id_type, h in hashes_to_check:
            cursor.execute("""
                SELECT reason FROM suppression_list 
                WHERE tenant_id = ? AND identifier_hash = ?
            """, (tenant_id, h))
            row = cursor.fetchone()
            if row:
                reason = row["reason"] if isinstance(row, dict) else row[0]
                return True, f"Lead en lista de supresión ({id_type}: {reason})"

    return False, None


# ==============================================================================
# 3. DEDUPLICACIÓN INTERNA DB-FIRST (ANTI-COLISIÓN DE REPRESENTANTES)
# ==============================================================================

def check_internal_collision(
    tenant_id: str,
    profile_url: str,
    email: Optional[str] = None,
    current_lead_id: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Verifica primero en la base de datos propia si el prospecto colisiona:
    1. Si está en la lista de supresión (Opt-out).
    2. Si ya está siendo contactado activamente por otra cuenta en el mismo tenant.
    3. Si ya completó una secuencia con respuesta positiva recientemente.
    """
    # 1. Comprobar supresión
    suppressed, sup_reason = is_suppressed(tenant_id, email=email, profile_url=profile_url)
    if suppressed:
        return True, sup_reason, None

    clean_url = profile_url.split("?")[0].rstrip("/") if profile_url else ""

    with get_db() as conn:
        cursor = conn.cursor()

        # 2. Buscar coincidencias de perfil o correo en leads del mismo tenant
        query = """
            SELECT l.id, l.nombre, l.estado, l.perfil_url, l.email, 
                   les.secuencia_id, les.estado as estado_secuencia, s.nombre as secuencia_nombre
            FROM leads l
            LEFT JOIN leads_en_secuencia les ON l.id = les.lead_id
            LEFT JOIN secuencias s ON les.secuencia_id = s.id
            WHERE l.tenant_id = ? 
              AND (l.perfil_url LIKE ? OR (l.email = ? AND l.email IS NOT NULL AND l.email != ''))
        """
        params = [tenant_id, f"{clean_url}%", email or ""]
        if current_lead_id:
            query += " AND l.id != ?"
            params.append(current_lead_id)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        for r in rows:
            data = dict(r) if isinstance(r, dict) else {
                "id": r[0], "nombre": r[1], "estado": r[2], "perfil_url": r[3],
                "email": r[4], "secuencia_id": r[5], "estado_secuencia": r[6], "secuencia_nombre": r[7]
            }

            # Si está en secuencia activa
            if data.get("estado_secuencia") in ("EN_CURSO", "PAUSADO"):
                return True, f"Lead ya activo en la secuencia '{data.get('secuencia_nombre')}' (Lead ID: {data.get('id')})", data

            # Si ya fue contactado o respondió
            if data.get("estado") in ("CONTACTADO", "RESPONDIÓ", "REUNIÓN_AGENDADA", "INVITACION_ENVIADA"):
                return True, f"Lead ya contactado previamente en el tenant (Estado: {data.get('estado')})", data

    return False, None, None


# ==============================================================================
# 4. BITÁCORA INTERNA DE ACTIVIDADES (lead_activity)
# ==============================================================================

def log_lead_activity(
    tenant_id: str,
    lead_id: str,
    action_type: str,
    details: Optional[Dict[str, Any]] = None,
    actor_id: Optional[str] = None
) -> str:
    """
    Registra un evento en la bitácora interna lead_activity (fuente única de verdad).
    Sincroniza simultáneamente con historial_actividades para compatibilidad con la UI.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    activity_id = str(uuid.uuid4())
    details_json = json.dumps(details or {})

    with get_db() as conn:
        cursor = conn.cursor()
        # 1. lead_activity (esquema principal v1.3)
        cursor.execute("""
            INSERT INTO lead_activity (id, tenant_id, lead_id, action_type, details_json, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (activity_id, tenant_id, lead_id, action_type, details_json, actor_id, now_iso))

        # 2. historial_actividades (compatibilidad previa)
        try:
            desc = details.get("descripcion") or f"Acción {action_type} ejecutada" if details else f"Acción {action_type}"
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, metadata_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (lead_id, action_type, desc, details_json, now_iso))
        except Exception:
            pass

        # 3. Actualizar updated_at del lead
        cursor.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (now_iso, lead_id))
        conn.commit()

    return activity_id


def get_lead_activities(tenant_id: str, lead_id: str) -> List[Dict[str, Any]]:
    """Obtiene el historial cronológico de actividades del lead para el tenant."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, action_type, details_json, actor_id, created_at
            FROM lead_activity
            WHERE tenant_id = ? AND lead_id = ?
            ORDER BY created_at DESC
        """, (tenant_id, lead_id))
        rows = cursor.fetchall()
        activities = []
        for r in rows:
            act = dict(r) if isinstance(r, dict) else {
                "id": r[0], "action_type": r[1], "details_json": r[2], "actor_id": r[3], "created_at": r[4]
            }
            try:
                act["details"] = json.loads(act["details_json"])
            except Exception:
                act["details"] = {}
            activities.append(act)
        return activities


# ==============================================================================
# 5. CONTROL DE CADENCIA Y EMISIÓN DE COMANDOS FIRMADOS ZOHO_*
# ==============================================================================

def check_zoho_rate_limit(tenant_id: str, device_id: str) -> Tuple[bool, Optional[str]]:
    """Aplica tope horario y diario a operaciones con Zoho para evitar bloqueos."""
    key = f"{tenant_id}:{device_id}"
    now = datetime.now(timezone.utc)
    if key not in _zoho_rate_window:
        _zoho_rate_window[key] = []

    # Filtrar timestamps de las últimas 24h
    one_day_ago = now - timedelta(days=1)
    one_hour_ago = now - timedelta(hours=1)
    _zoho_rate_window[key] = [t for t in _zoho_rate_window[key] if t > one_day_ago]

    ops_last_hour = len([t for t in _zoho_rate_window[key] if t > one_hour_ago])
    ops_last_day = len(_zoho_rate_window[key])

    if ops_last_hour >= MAX_ZOHO_OPS_PER_HOUR:
        return False, f"Límite horario de Zoho alcanzado ({ops_last_hour}/{MAX_ZOHO_OPS_PER_HOUR} ops/hora)"

    if ops_last_day >= MAX_ZOHO_OPS_PER_DAY:
        return False, f"Límite diario de Zoho alcanzado ({ops_last_day}/{MAX_ZOHO_OPS_PER_DAY} ops/día)"

    return True, None


def register_zoho_operation(tenant_id: str, device_id: str):
    """Registra la marca de tiempo de una operación ejecutada en Zoho."""
    key = f"{tenant_id}:{device_id}"
    if key not in _zoho_rate_window:
        _zoho_rate_window[key] = []
    _zoho_rate_window[key].append(datetime.now(timezone.utc))


def create_zoho_find_lead_command(
    tenant_id: str,
    device_id: str,
    lead_id: str,
    name: str,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Emite el comando firmado ZOHO_FIND_LEAD para consultar si un contacto existe.
    Gobernado 100% por el servidor: rechaza si el flag está apagado.
    """
    if not is_zoho_bridge_enabled(tenant_id):
        raise PermissionError("El módulo Zoho Bridge no está activado para este tenant")

    allowed, rate_reason = check_zoho_rate_limit(tenant_id, device_id)
    if not allowed:
        raise RuntimeError(f"Freno de cadencia Zoho: {rate_reason}")

    params = {
        "lead_id": lead_id,
        "name": name,
        "email": email or ""
    }

    cmd = command_signing_service.create_signed_command(
        tenant_id=tenant_id,
        device_id=device_id,
        action="ZOHO_FIND_LEAD",
        params=params,
        ttl_seconds=120
    )
    register_zoho_operation(tenant_id, device_id)
    log_lead_activity(tenant_id, lead_id, "ZOHO_FIND_DISPATCHED", {"command_id": cmd["command_id"], "name": name})
    return cmd


def create_zoho_upsert_lead_command(
    tenant_id: str,
    device_id: str,
    lead_id: str,
    lead_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Emite el comando firmado ZOHO_UPSERT_LEAD."""
    if not is_zoho_bridge_enabled(tenant_id):
        raise PermissionError("El módulo Zoho Bridge no está activado para este tenant")

    allowed, rate_reason = check_zoho_rate_limit(tenant_id, device_id)
    if not allowed:
        raise RuntimeError(f"Freno de cadencia Zoho: {rate_reason}")

    cmd = command_signing_service.create_signed_command(
        tenant_id=tenant_id,
        device_id=device_id,
        action="ZOHO_UPSERT_LEAD",
        params={"lead_id": lead_id, "data": lead_data},
        ttl_seconds=120
    )
    register_zoho_operation(tenant_id, device_id)
    log_lead_activity(tenant_id, lead_id, "ZOHO_UPSERT_DISPATCHED", {"command_id": cmd["command_id"]})
    return cmd


def create_zoho_set_status_command(
    tenant_id: str,
    device_id: str,
    lead_id: str,
    crm_external_id: str,
    status_label: str
) -> Dict[str, Any]:
    """Emite el comando firmado ZOHO_SET_STATUS."""
    if not is_zoho_bridge_enabled(tenant_id):
        raise PermissionError("El módulo Zoho Bridge no está activado para este tenant")

    allowed, rate_reason = check_zoho_rate_limit(tenant_id, device_id)
    if not allowed:
        raise RuntimeError(f"Freno de cadencia Zoho: {rate_reason}")

    cmd = command_signing_service.create_signed_command(
        tenant_id=tenant_id,
        device_id=device_id,
        action="ZOHO_SET_STATUS",
        params={"lead_id": lead_id, "crm_external_id": crm_external_id, "status": status_label},
        ttl_seconds=120
    )
    register_zoho_operation(tenant_id, device_id)
    log_lead_activity(tenant_id, lead_id, "ZOHO_STATUS_DISPATCHED", {"crm_id": crm_external_id, "status": status_label})
    return cmd


def create_zoho_add_note_command(
    tenant_id: str,
    device_id: str,
    lead_id: str,
    crm_external_id: str,
    note_title: str,
    note_content: str
) -> Dict[str, Any]:
    """Emite el comando firmado ZOHO_ADD_NOTE."""
    if not is_zoho_bridge_enabled(tenant_id):
        raise PermissionError("El módulo Zoho Bridge no está activado para este tenant")

    allowed, rate_reason = check_zoho_rate_limit(tenant_id, device_id)
    if not allowed:
        raise RuntimeError(f"Freno de cadencia Zoho: {rate_reason}")

    cmd = command_signing_service.create_signed_command(
        tenant_id=tenant_id,
        device_id=device_id,
        action="ZOHO_ADD_NOTE",
        params={
            "lead_id": lead_id,
            "crm_external_id": crm_external_id,
            "title": note_title,
            "content": note_content
        },
        ttl_seconds=120
    )
    register_zoho_operation(tenant_id, device_id)
    log_lead_activity(tenant_id, lead_id, "ZOHO_NOTE_DISPATCHED", {"crm_id": crm_external_id, "title": note_title})
    return cmd


def sync_zoho_result_to_lead(
    tenant_id: str,
    lead_id: str,
    crm_external_id: Optional[str],
    crm_sync_status: str,
    owner_name: Optional[str] = None
) -> bool:
    """Actualiza los campos de referencia CRM desacoplados en el lead sin alterar su estado propio."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE leads 
            SET crm_external_id = COALESCE(?, crm_external_id),
                crm_sync_status = ?,
                crm_synced_at = ?,
                zoho_id = COALESCE(?, zoho_id),
                zoho_cuenta_dueno = COALESCE(?, zoho_cuenta_dueno),
                updated_at = ?
            WHERE id = ? AND tenant_id = ?
        """, (crm_external_id, crm_sync_status, now_iso, crm_external_id, owner_name, now_iso, lead_id, tenant_id))
        conn.commit()

    log_lead_activity(tenant_id, lead_id, "CRM_SYNC_COMPLETED", {
        "crm_external_id": crm_external_id,
        "crm_sync_status": crm_sync_status,
        "owner": owner_name
    })
    return True


# ==============================================================================
# 6. EXPORTACIÓN CSV NATIVA DE LEADS Y BITÁCORA
# ==============================================================================

def export_leads_with_activity_csv(tenant_id: str) -> str:
    """
    Genera un archivo CSV con formato documentado y estable que contiene los leads
    exclusivos del tenant, su estado, referencias de CRM y bitácora cronológica de actividad.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Cabecera estable
    writer.writerow([
        "lead_id",
        "nombre",
        "cargo_actual",
        "institucion_actual",
        "ubicacion",
        "email",
        "telefono",
        "perfil_url",
        "estado",
        "crm_external_id",
        "crm_sync_status",
        "crm_synced_at",
        "created_at",
        "total_actividades",
        "ultima_actividad_tipo",
        "ultima_actividad_fecha",
        "historial_resumido"
    ])

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, cargo_actual, institucion_actual, ubicacion, email, telefono,
                   perfil_url, estado, crm_external_id, crm_sync_status, crm_synced_at, created_at
            FROM leads
            WHERE tenant_id = ?
            ORDER BY created_at DESC
        """, (tenant_id,))
        leads = cursor.fetchall()

        for row in leads:
            l = dict(row) if isinstance(row, dict) else {
                "id": row[0], "nombre": row[1], "cargo_actual": row[2], "institucion_actual": row[3],
                "ubicacion": row[4], "email": row[5], "telefono": row[6], "perfil_url": row[7],
                "estado": row[8], "crm_external_id": row[9], "crm_sync_status": row[10],
                "crm_synced_at": row[11], "created_at": row[12]
            }

            # Obtener actividades del lead
            cursor.execute("""
                SELECT action_type, created_at 
                FROM lead_activity 
                WHERE lead_id = ? 
                ORDER BY created_at DESC
            """, (l["id"],))
            acts = cursor.fetchall()

            total_acts = len(acts)
            last_type = acts[0]["action_type"] if acts and isinstance(acts[0], dict) else (acts[0][0] if acts else "")
            last_date = acts[0]["created_at"] if acts and isinstance(acts[0], dict) else (acts[0][1] if acts else "")
            
            summary_list = []
            for a in acts[:5]:
                atype = a["action_type"] if isinstance(a, dict) else a[0]
                adate = (a["created_at"] if isinstance(a, dict) else a[1])[:10]
                summary_list.append(f"{adate}:{atype}")
            historial_resumen = " | ".join(summary_list)

            writer.writerow([
                l.get("id"),
                l.get("nombre"),
                l.get("cargo_actual"),
                l.get("institucion_actual"),
                l.get("ubicacion"),
                l.get("email"),
                l.get("telefono"),
                l.get("perfil_url"),
                l.get("estado"),
                l.get("crm_external_id") or "",
                l.get("crm_sync_status") or "",
                l.get("crm_synced_at") or "",
                l.get("created_at"),
                total_acts,
                last_type,
                last_date,
                historial_resumen
            ])

    return output.getvalue()
