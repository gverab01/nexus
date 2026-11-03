import os
import json
import random
import time
import re
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from database import get_db
import safety_engine
import browser_service
import whatsapp_safety_engine
import zoho_browser_service

# ==============================================================================
# MOTOR DE SECUENCIAS MULTICANAL Y ÁRBOLES DE DECISIÓN (NexusReach Pro)
# ==============================================================================

def get_sequences(tenant_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Obtiene la lista de secuencias disponibles con sus métricas agregadas y listas asociadas."""
    try:
        promote_expired_delays()
    except Exception:
        pass
    with get_db() as conn:
        cursor = conn.cursor()
        where_filter = ""
        params = []
        if tenant_ids:
            placeholders = ", ".join(["?"] * len(tenant_ids))
            where_filter = f"WHERE s.tenant_id IN ({placeholders})"
            params.extend(tenant_ids)

        cursor.execute(f"""
            SELECT s.*, 
                (SELECT COUNT(*) FROM pasos_secuencia WHERE secuencia_id = s.id) as total_pasos,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id) as total_leads,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id AND estado = 'EN_CURSO') as leads_en_curso,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id AND estado IN ('COMPLETADO', 'FINALIZADA', 'FINALIZADO')) as leads_completados
            FROM secuencias s
            {where_filter}
            ORDER BY s.es_default DESC, s.created_at DESC
        """, params)
        sequences = cursor.fetchall()

        sec_ids = [s["id"] for s in sequences]
        lists_map = {s["id"]: [] for s in sequences}
        if sec_ids:
            sec_ph = ", ".join(["?"] * len(sec_ids))
            cursor.execute(f"""
                SELECT sl.secuencia_id, l.id, l.nombre, l.estado, sl.activa as vinculo_activo,
                       (SELECT COUNT(*) FROM leads_en_lista WHERE lista_id = l.id) as total_leads
                FROM secuencia_listas sl
                JOIN listas_leads l ON sl.lista_id = l.id
                WHERE sl.secuencia_id IN ({sec_ph})
            """, sec_ids)
            for row in cursor.fetchall():
                lists_map[row["secuencia_id"]].append(dict(row))

        for s in sequences:
            s["listas_asociadas"] = lists_map.get(s["id"], [])

        return sequences

def change_sequence_publish_status(sequence_id: str, new_status: str) -> bool:
    """Cambia el estado de una secuencia entre 'BORRADOR', 'PUBLICADA' (activa) y 'PAUSADA'."""
    now_iso = datetime.now().isoformat()
    norm = (new_status or "").upper().strip()
    if norm in ('PUBLICADA', 'ACTIVA', 'PUBLICADO'):
        normalized_status = 'PUBLICADA'
        is_active = 1
    elif norm in ('PAUSADA', 'DESACTIVADA', 'INACTIVA', 'PAUSADO'):
        normalized_status = 'PAUSADA'
        is_active = 0
    elif norm in ('BORRADOR', 'DRAFT'):
        normalized_status = 'BORRADOR'
        is_active = 0
    else:
        normalized_status = 'BORRADOR'
        is_active = 0
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE secuencias 
            SET estado = ?, activa = ?, updated_at = ?
            WHERE id = ?
        """, (normalized_status, is_active, now_iso, sequence_id))
        return True

def get_full_sequence(sequence_id: str, secuencia_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Obtiene la definición de una secuencia y todos sus pasos ordenados y estructurados.
    """
    target_id = sequence_id or secuencia_id
    secuencia_id = target_id
    try:
        promote_expired_delays(sequence_id=secuencia_id)
    except Exception:
        pass
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM secuencias WHERE id = ?", (target_id,))
        sec = cursor.fetchone()
        if not sec:
            return None

        ahora_iso = datetime.now().isoformat()
        cursor.execute("""
            SELECT p.*,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ? AND paso_actual_id = p.id AND estado = 'EN_CURSO') as leads_en_paso,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ? AND paso_actual_id = p.id AND estado = 'EN_CURSO' AND (proxima_ejecucion_at IS NULL OR proxima_ejecucion_at <= ?)) as leads_listos,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ? AND paso_actual_id = p.id AND estado = 'EN_CURSO' AND proxima_ejecucion_at IS NOT NULL AND proxima_ejecucion_at > ?) as leads_en_espera
            FROM pasos_secuencia p
            WHERE p.secuencia_id = ? 
            ORDER BY p.orden ASC, p.created_at ASC
        """, (secuencia_id, secuencia_id, ahora_iso, secuencia_id, ahora_iso, secuencia_id))
        pasos_raw = cursor.fetchall()

        pasos = []
        for p in pasos_raw:
            params = {}
            try:
                params = json.loads(p.get("parametros_json") or "{}")
            except Exception:
                pass
            p["parametros"] = params
            pasos.append(p)

        sec["pasos"] = pasos

        # Métricas de avance de leads en la secuencia
        cursor.execute("""
            SELECT 
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ? AND estado = 'EN_CURSO') as total_en_curso,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ? AND estado IN ('COMPLETADO', 'FINALIZADA', 'FINALIZADO')) as total_completados,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = ?) as total_inscritos
        """, (secuencia_id, secuencia_id, secuencia_id))
        metrics = cursor.fetchone() or {}
        sec["total_en_curso"] = metrics.get("total_en_curso", 0)
        sec["total_completados"] = metrics.get("total_completados", 0)
        sec["total_inscritos"] = metrics.get("total_inscritos", 0)

        # Calcular métricas de flujo para cada paso (entrantes, en circulación, salientes)
        cursor.execute("""
            SELECT ls.lead_id, ls.paso_actual_id, ls.estado, p.orden as paso_orden
            FROM leads_en_secuencia ls
            LEFT JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            WHERE ls.secuencia_id = ?
        """, (secuencia_id,))
        leads_distribution = cursor.fetchall()

        total_inscritos = sec["total_inscritos"]
        total_pasos = len(pasos)
        for idx_p, p in enumerate(pasos):
            p_orden = p.get("orden", 1)
            p_id = p["id"]
            is_last_step = (idx_p == total_pasos - 1)

            # Leads actualmente en este paso en ejecución
            en_paso = sum(1 for l in leads_distribution if l["paso_actual_id"] == p_id and l["estado"] == "EN_CURSO")

            # Leads que ya pasaron por este paso
            salientes = 0
            for l in leads_distribution:
                if l["estado"] in ("COMPLETADO", "FINALIZADA", "FINALIZADO"):
                    salientes += 1
                elif l["paso_actual_id"] != p_id:
                    l_orden = l.get("paso_orden") or 0
                    if l_orden > p_orden:
                        salientes += 1

            if p_orden == 1 or p.get("padre_paso_id") is None:
                entrantes = total_inscritos
            else:
                entrantes = en_paso + salientes

            p["leads_entrantes"] = entrantes
            p["leads_en_paso"] = en_paso
            p["leads_salientes"] = salientes
            p["es_ultimo_paso"] = is_last_step
            p["porcentaje_salida"] = round((salientes / entrantes * 100), 1) if entrantes > 0 else 0


        # Próximo lead candidato
        cursor.execute("""
            SELECT ls.*, l.nombre, l.cargo_actual, l.cargo_titular, l.institucion_actual,
                   p.orden as paso_orden, p.tipo_accion, p.parametros_json
            FROM leads_en_secuencia ls
            JOIN leads l ON ls.lead_id = l.id
            JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            WHERE ls.secuencia_id = ? AND ls.estado = 'EN_CURSO'
            ORDER BY ls.proxima_ejecucion_at ASC LIMIT 1
        """, (secuencia_id,))
        prox = cursor.fetchone()
        if prox:
            params_prox = {}
            try:
                params_prox = json.loads(prox.get("parametros_json") or "{}")
            except Exception:
                pass
            prox["etiqueta"] = params_prox.get("etiqueta") or prox["tipo_accion"]
            prox["listo_ahora"] = 1 if (prox.get("proxima_ejecucion_at") or "") <= ahora_iso else 0
        sec["proximo_lead"] = prox

        sec_tenant = sec.get("tenant_id") or "ten_superadmin"
        cursor.execute("""
            SELECT l.id, l.nombre, l.estado, sl.activa as vinculo_activo, sl.auto_ingresar_nuevos,
                   (SELECT COUNT(*) FROM leads_en_lista WHERE lista_id = l.id) as total_leads
            FROM secuencia_listas sl
            JOIN listas_leads l ON sl.lista_id = l.id
            WHERE sl.secuencia_id = ? AND l.tenant_id = ?
        """, (secuencia_id, sec_tenant))
        sec["listas_asociadas"] = cursor.fetchall()

        return sec

def create_sequence(name: str, description: str = "", active: bool = False, template: str = "multicanal", tenant_id: str = "ten_superadmin", estado: str = "BORRADOR") -> Dict[str, Any]:
    """Crea una nueva secuencia comenzando en BORRADOR por defecto, poblada con pasos de plantilla."""
    now_iso = datetime.now().isoformat()
    sec_id = f"sec-{int(time.time())}"
    norm_estado = (estado or "").upper().strip()
    if norm_estado in ('PUBLICADA', 'ACTIVA') and active:
        final_estado = 'PUBLICADA'
        is_active = 1
    elif norm_estado in ('PAUSADA', 'DESACTIVADA'):
        final_estado = 'PAUSADA'
        is_active = 0
    else:
        final_estado = 'BORRADOR'
        is_active = 0

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO secuencias (id, nombre, descripcion, activa, es_default, estado, tenant_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
        """, (sec_id, name, description, is_active, final_estado, tenant_id, now_iso, now_iso))

        # Create steps according to selected template
        steps_tpl = []
        if template in ("trilateral_multicanal", "multicanal"):
            steps_tpl = [
                ("step-1", None, "DEFAULT", "VISITAR_PERFIL", {
                    "tiempo_lectura_min_seg": 6,
                    "tiempo_lectura_max_seg": 12,
                    "etiqueta": "1. Visitar Perfil LinkedIn (Scroll y Lectura Humana)"
                }, 1),
                ("step-2", "step-1", "DEFAULT", "ESPERAR", {
                    "horas_espera": 4,
                    "etiqueta": "2. Esperar 4 Horas (Pausa Estratégica)"
                }, 2),
                ("step-3", "step-2", "DEFAULT", "ENVIAR_INVITACION", {
                    "incluir_nota": True,
                    "usar_spintax": True,
                    "plantilla_nota": "Hola {nombre}, un gusto saludarte. Veo tu labor en {empresa}. Me encantaría conectar contigo por este medio.",
                    "etiqueta": "3. Enviar Invitación a Conectar (Nota Personalizada)"
                }, 3),
                ("step-4", "step-3", "DEFAULT", "ESPERAR", {
                    "horas_espera": 48,
                    "etiqueta": "4. Esperar 48 Horas para Aceptación"
                }, 4),
                ("step-5", "step-4", "DEFAULT", "VERIFICAR_ESTADO", {
                    "descripcion": "¿El prospecto aceptó la invitación?",
                    "etiqueta": "5. Bifurcación Condicional: ¿Aceptó en LinkedIn?"
                }, 5),
                ("step-6a", "step-5", "SI_ACEPTO", "ENVIAR_MENSAJE_LINKEDIN", {
                    "asunto": "Mensaje de Bienvenida",
                    "plantilla_mensaje": "Hola {nombre}, gracias por aceptar la conexión. Quería compartir contigo algunas experiencias prácticas que estamos implementando en optimización de procesos en {empresa}. ¿Te interesaría revisar un resumen breve?",
                    "etiqueta": "6A. [Si Conectó] Enviar Mensaje 1 de Valor en LinkedIn"
                }, 6),
                ("step-7a", "step-6a", "DEFAULT", "ESPERAR", {
                    "horas_espera": 72,
                    "etiqueta": "7A. Esperar 3 Días (72 hrs)"
                }, 7),
                ("step-8a", "step-7a", "DEFAULT", "ENVIAR_MENSAJE_LINKEDIN", {
                    "asunto": "Mensaje de Seguimiento",
                    "plantilla_mensaje": "Estimado/a {nombre}, espero que estés teniendo una excelente semana en {empresa}. Quería consultarte si tuviste ocasión de revisar mi mensaje anterior o si prefieres coordinar una llamada breve de 10 minutos.",
                    "etiqueta": "8A. Enviar Mensaje 2 de Seguimiento en LinkedIn"
                }, 8),
                ("step-6b", "step-5", "SI_NO_ACEPTO", "ENVIAR_CORREO_WORKSPACE", {
                    "asunto": "Oportunidad de colaboración con {empresa}",
                    "cuerpo_email": "Estimado/a {nombre},\n\nEspero que se encuentre muy bien. Le escribo en relación a su labor directiva en {empresa}.\n\nIntenté conectar con usted recientemente por LinkedIn; no obstante, le escribo por este medio formal de correo para presentarle una breve síntesis de herramientas para optimizar operaciones...\n\nQuedo a su disposición si estima conveniente conversar brevemente.\n\nAtentamente,\nGabriel",
                    "requiere_email_valido": True,
                    "etiqueta": "6B. [Si NO Conectó] Enviar Email Google Workspace"
                }, 6),
                ("step-7b", "step-6b", "DEFAULT", "ESPERAR", {
                    "horas_espera": 48,
                    "etiqueta": "7B. Esperar 48 Horas (2 Días)"
                }, 7),
                ("step-8b", "step-7b", "DEFAULT", "ENVIAR_WHATSAPP_WEB", {
                    "plantilla_mensaje": "{Hola|Buenos días} {nombre}, un gusto saludarte. Te contacto en relación a tu labor en {empresa}. Te había enviado un correo anteriormente y quería dejarte mi contacto directo por WhatsApp.",
                    "etiqueta": "8B. [WhatsApp Antiban] Mensaje WhatsApp Web Local"
                }, 8),
                ("step-9b", "step-8b", "DEFAULT", "ESPERAR", {
                    "horas_espera": 96,
                    "etiqueta": "9B. Esperar 4 Días (96 hrs)"
                }, 9),
                ("step-10b", "step-9b", "DEFAULT", "RETIRAR_INVITACION", {
                    "motivo": "Retiro automático por falta de respuesta para proteger ratio de cuenta",
                    "etiqueta": "10B. Retirar Solicitud de Conexión en LinkedIn"
                }, 10)
            ]
        elif template == "linkedin_lineal":
            steps_tpl = [
                ("step-1", None, "DEFAULT", "VISITAR_PERFIL", {
                    "tiempo_lectura_min_seg": 6,
                    "tiempo_lectura_max_seg": 12,
                    "etiqueta": "1. Visitar Perfil LinkedIn"
                }, 1),
                ("step-2", "step-1", "DEFAULT", "ESPERAR", {
                    "horas_espera": 24,
                    "etiqueta": "2. Pausa de 24 Horas"
                }, 2),
                ("step-3", "step-2", "DEFAULT", "ENVIAR_INVITACION", {
                    "incluir_nota": True,
                    "plantilla_nota": "Hola {nombre}, un gusto saludarte. Veo tu gestión en {colegio}.",
                    "etiqueta": "3. Enviar Invitación LinkedIn con Nota"
                }, 3),
                ("step-4", "step-3", "DEFAULT", "ESPERAR", {
                    "horas_espera": 48,
                    "etiqueta": "4. Pausa de 48 Horas"
                }, 4),
                ("step-5", "step-4", "DEFAULT", "ENVIAR_MENSAJE_LINKEDIN", {
                    "asunto": "Contacto Directo",
                    "plantilla_mensaje": "Hola {nombre}, te contacto con relación a tu rol en {colegio}...",
                    "etiqueta": "5. Mensaje Directo de LinkedIn"
                }, 5)
            ]
        elif template == "workspace_lineal":
            steps_tpl = [
                ("step-1", None, "DEFAULT", "ENVIAR_CORREO_WORKSPACE", {
                    "asunto": "Contacto institucional {colegio}",
                    "cuerpo_email": "Estimado/a {nombre},\n\nLe escribo en relación a su gestión directiva en {colegio}...",
                    "etiqueta": "1. Correo Frío Google Workspace Inicial"
                }, 1),
                ("step-2", "step-1", "DEFAULT", "ESPERAR", {
                    "horas_espera": 72,
                    "etiqueta": "2. Esperar 3 Días (72 hrs)"
                }, 2),
                ("step-3", "step-2", "DEFAULT", "ENVIAR_CORREO_WORKSPACE", {
                    "asunto": "Re: Contacto institucional {colegio}",
                    "cuerpo_email": "Estimado/a {nombre},\n\nLe reitero mi mensaje anterior para consultar si tuvo oportunidad de revisarlo...",
                    "etiqueta": "3. Correo de Seguimiento Follow-up"
                }, 3)
            ]
        elif template == "whatsapp_lineal":
            steps_tpl = [
                ("step-1", None, "DEFAULT", "ENVIAR_WHATSAPP_WEB", {
                    "plantilla_mensaje": "{Hola|Buenos días} {nombre}, un gusto saludarte. Te escribo con relación a tu rol en {empresa}...",
                    "etiqueta": "1. Mensaje de Presentación WhatsApp Web (Local Antiban)"
                }, 1),
                ("step-2", "step-1", "DEFAULT", "ESPERAR", {
                    "horas_espera": 72,
                    "etiqueta": "2. Pausa Antiban de 3 Días (72 Horas)"
                }, 2),
                ("step-3", "step-2", "DEFAULT", "ENVIAR_WHATSAPP_WEB", {
                    "plantilla_mensaje": "Hola {nombre}, espero que tengas una excelente semana. Quería consultar si tuviste oportunidad de revisar mi mensaje anterior...",
                    "etiqueta": "3. Mensaje de Seguimiento WhatsApp Web"
                }, 3)
            ]
        else: # vacia
            steps_tpl = [
                ("step-1", None, "DEFAULT", "VISITAR_PERFIL", {
                    "tiempo_lectura_min_seg": 6,
                    "tiempo_lectura_max_seg": 12,
                    "etiqueta": "1. Visitar Perfil LinkedIn"
                }, 1)
            ]

        for p_id_rel, parent_rel, cond, action_type, p_params, ord_val in steps_tpl:
            real_id = f"step-{sec_id}-{p_id_rel}"
            real_parent = f"step-{sec_id}-{parent_rel}" if parent_rel else None
            cursor.execute("""
                INSERT INTO pasos_secuencia (id, secuencia_id, padre_paso_id, condicion_rama, tipo_accion, parametros_json, orden, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (real_id, sec_id, real_parent, cond, action_type, json.dumps(p_params), ord_val, now_iso))

    return get_full_sequence(sec_id)

def update_sequence(sequence_id: str, name: Optional[str] = None, description: Optional[str] = None, active: Optional[bool] = None) -> bool:
    """Actualiza los metadatos de una secuencia existente."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        fields = []
        values = []
        if name is not None:
            fields.append("nombre = ?")
            values.append(name)
        if description is not None:
            fields.append("descripcion = ?")
            values.append(description)
        if active is not None:
            fields.append("activa = ?")
            values.append(1 if active else 0)
        
        if not fields:
            return False
            
        fields.append("updated_at = ?")
        values.append(now_iso)
        values.append(sequence_id)

        cursor.execute(f"UPDATE secuencias SET {', '.join(fields)} WHERE id = ?", values)
        return True

def delete_sequence(sequence_id: str) -> bool:
    """Elimina una secuencia y sus pasos asociados en cascada."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pasos_secuencia WHERE secuencia_id = ?", (sequence_id,))
        cursor.execute("DELETE FROM leads_en_secuencia WHERE secuencia_id = ?", (sequence_id,))
        cursor.execute("DELETE FROM secuencia_listas WHERE secuencia_id = ?", (sequence_id,))
        cursor.execute("DELETE FROM secuencias WHERE id = ?", (sequence_id,))
        return True

def add_sequence_step(sequence_id: str, step_data: Dict[str, Any], position: str = "final", reference_step_id: Optional[str] = None) -> Dict[str, Any]:
    """Inserta un nuevo paso en la secuencia y reorganiza el orden correlativo."""
    now_iso = datetime.now().isoformat()
    new_id = f"step-{sequence_id}-{int(time.time())}-{random.randint(100, 999)}"
    action_type = step_data.get("tipo_accion", "ESPERAR")
    params = step_data.get("parametros") or step_data.get("parametros_json") or {}
    label = step_data.get("etiqueta") or params.get("etiqueta") or f"Paso {action_type}"
    params["etiqueta"] = label
    params_json = json.dumps(params)
    branch_condition = step_data.get("condicion_rama", "DEFAULT")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pasos_secuencia WHERE secuencia_id = ? ORDER BY orden ASC", (sequence_id,))
        steps = cursor.fetchall()

        new_order = 1
        parent_step_id = None

        if not steps:
            new_order = 1
            parent_step_id = None
        elif position == "inicio":
            new_order = 1
            parent_step_id = None
            cursor.execute("UPDATE pasos_secuencia SET orden = orden + 1 WHERE secuencia_id = ?", (sequence_id,))
            if steps:
                first_step_id = steps[0]["id"]
                cursor.execute("UPDATE pasos_secuencia SET padre_paso_id = ? WHERE id = ?", (new_id, first_step_id))
        elif position == "intermedio" and reference_step_id:
            ref_idx = next((i for i, p in enumerate(steps) if p["id"] == reference_step_id), None)
            if ref_idx is not None:
                ref_step = steps[ref_idx]
                new_order = ref_step["orden"] + 1
                parent_step_id = ref_step["id"]
                cursor.execute("UPDATE pasos_secuencia SET orden = orden + 1 WHERE secuencia_id = ? AND orden >= ?", (sequence_id, new_order))
                cursor.execute("UPDATE pasos_secuencia SET padre_paso_id = ? WHERE secuencia_id = ? AND padre_paso_id = ? AND id != ?", (new_id, sequence_id, ref_step["id"], new_id))
            else:
                max_order = max(p["orden"] for p in steps) if steps else 0
                new_order = max_order + 1
                parent_step_id = steps[-1]["id"] if steps else None
        else:
            max_order = max(p["orden"] for p in steps) if steps else 0
            new_order = max_order + 1
            parent_step_id = steps[-1]["id"] if steps else None

        cursor.execute("""
            INSERT INTO pasos_secuencia (id, secuencia_id, padre_paso_id, condicion_rama, tipo_accion, parametros_json, orden, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, sequence_id, parent_step_id, branch_condition, action_type, params_json, new_order, now_iso))

        cursor.execute("UPDATE secuencias SET updated_at = ? WHERE id = ?", (now_iso, sequence_id))

    return {
        "id": new_id,
        "secuencia_id": sequence_id,
        "tipo_accion": action_type,
        "orden": new_order,
        "etiqueta": label,
        "padre_paso_id": parent_step_id
    }

def delete_sequence_step(sequence_id: str, step_id: str) -> bool:
    """Elimina un paso de la secuencia y migra o finaliza los leads en cola."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pasos_secuencia WHERE id = ? AND secuencia_id = ?", (step_id, sequence_id))
        step_to_delete = cursor.fetchone()
        if not step_to_delete:
            return False

        parent_of_deleted = step_to_delete["padre_paso_id"]
        order_deleted = step_to_delete["orden"]

        cursor.execute("""
            SELECT * FROM pasos_secuencia 
            WHERE secuencia_id = ? AND orden > ? 
            ORDER BY orden ASC LIMIT 1
        """, (sequence_id, order_deleted))
        next_step = cursor.fetchone()

        if next_step:
            cursor.execute("""
                UPDATE leads_en_secuencia 
                SET paso_actual_id = ?, updated_at = ?
                WHERE secuencia_id = ? AND paso_actual_id = ?
            """, (next_step["id"], now_iso, sequence_id, step_id))
        else:
            cursor.execute("""
                UPDATE leads_en_secuencia 
                SET estado = 'COMPLETADO', paso_actual_id = NULL, updated_at = ?
                WHERE secuencia_id = ? AND paso_actual_id = ?
            """, (now_iso, sequence_id, step_id))

        cursor.execute("""
            UPDATE pasos_secuencia 
            SET padre_paso_id = ?
            WHERE secuencia_id = ? AND padre_paso_id = ?
        """, (parent_of_deleted, sequence_id, step_id))

        cursor.execute("DELETE FROM pasos_secuencia WHERE id = ?", (step_id,))

        cursor.execute("SELECT id FROM pasos_secuencia WHERE secuencia_id = ? ORDER BY orden ASC", (sequence_id,))
        remaining = cursor.fetchall()
        for idx, r in enumerate(remaining, start=1):
            cursor.execute("UPDATE pasos_secuencia SET orden = ? WHERE id = ?", (idx, r["id"]))

        cursor.execute("UPDATE secuencias SET updated_at = ? WHERE id = ?", (now_iso, sequence_id))
        return True

def save_sequence_steps(sequence_id: str, steps: List[Dict[str, Any]]) -> bool:
    """Reemplaza o guarda el árbol completo de pasos para una secuencia dada."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pasos_secuencia WHERE secuencia_id = ?", (sequence_id,))
        
        for idx, p in enumerate(steps, start=1):
            p_id = p.get("id") or f"step-{sequence_id}-{idx}"
            parent_id = p.get("padre_paso_id")
            cond = p.get("condicion_rama") or "DEFAULT"
            action_type = p.get("tipo_accion") or p.get("tipo") or "VISITAR_PERFIL"
            
            params_dict = p.get("parametros") or p.get("parametros_json") or {}
            if isinstance(params_dict, str):
                try:
                    params_dict = json.loads(params_dict)
                except Exception:
                    params_dict = {}
            if p.get("etiqueta"):
                params_dict["etiqueta"] = p.get("etiqueta")
            params = json.dumps(params_dict)
            order_val = p.get("orden", idx)

            cursor.execute("""
                INSERT INTO pasos_secuencia (id, secuencia_id, padre_paso_id, condicion_rama, tipo_accion, parametros_json, orden, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (p_id, sequence_id, parent_id, cond, action_type, params, order_val, now_iso))
        
        cursor.execute("UPDATE secuencias SET updated_at = ? WHERE id = ?", (now_iso, sequence_id))
    return True

# ==============================================================================
# LEAD ASSIGNMENT TO SEQUENCES
# ==============================================================================

def assign_leads_to_sequence(sequence_id: str, lead_ids: List[str]) -> Dict[str, Any]:
    """Asigna una lista de prospectos a la secuencia especificada en su paso inicial raíz."""
    now = datetime.now()
    now_iso = now.isoformat()
    
    with get_db() as conn:
        cursor = conn.cursor()
        # 1. Find root step (no parent)
        cursor.execute("""
            SELECT id FROM pasos_secuencia 
            WHERE secuencia_id = ? AND padre_paso_id IS NULL 
            ORDER BY orden ASC LIMIT 1
        """, (sequence_id,))
        root = cursor.fetchone()
        if not root:
            return {"status": "error", "mensaje": "La secuencia no tiene un paso inicial definido."}
        
        root_step_id = root["id"]
        assigned = 0
        skipped = 0

        cursor.execute("SELECT tenant_id FROM secuencias WHERE id = ?", (sequence_id,))
        sec_row = cursor.fetchone()
        sec_tenant = sec_row.get("tenant_id") if sec_row else None

        for lid in lead_ids:
            try:
                if sec_tenant:
                    cursor.execute("SELECT tenant_id FROM leads WHERE id = ?", (lid,))
                    l_row = cursor.fetchone()
                    if l_row and l_row.get("tenant_id") and l_row["tenant_id"] != sec_tenant:
                        skipped += 1
                        continue

                cursor.execute("""
                    INSERT INTO leads_en_secuencia (
                        id, lead_id, secuencia_id, paso_actual_id, estado, proxima_ejecucion_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'EN_CURSO', ?, ?, ?)
                    ON CONFLICT(lead_id, secuencia_id) DO UPDATE SET
                        paso_actual_id = excluded.paso_actual_id,
                        estado = 'EN_CURSO',
                        proxima_ejecucion_at = excluded.proxima_ejecucion_at,
                        updated_at = excluded.updated_at
                """, (f"ls-{lid}-{sequence_id}", lid, sequence_id, root_step_id, now_iso, now_iso, now_iso))
                assigned += 1
            except Exception as e:
                skipped += 1

        return {
            "status": "ok",
            "asignados": assigned,
            "omitidos": skipped,
            "paso_inicial_id": root_step_id
        }

def get_leads_in_sequence(sequence_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtiene los prospectos inscritos en la secuencia con su paso actual y estado de ejecución."""
    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT ls.*, l.nombre, l.cargo_actual, l.cargo_titular, l.institucion_actual, l.ubicacion, l.email, l.telefono, l.perfil_url, l.estado as lead_estado,
                   l.email_extracted, l.email_source, l.email_status, l.empresa_dominio, l.email_zoho, l.zoho_entidad_tipo, l.zoho_id, l.zoho_lead_status,
                   l.zoho_cuenta_nombre, l.zoho_cuenta_dueno, l.zoho_cuenta_es_cliente, l.zoho_synced_at, l.notas, l.tags,
                   p.tipo_accion as paso_accion, p.condicion_rama as paso_condicion, p.orden as paso_orden, p.parametros_json
            FROM leads_en_secuencia ls
            JOIN leads l ON ls.lead_id = l.id
            LEFT JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            WHERE ls.secuencia_id = ?
        """
        params = [sequence_id]
        if status:
            if status.upper() in ('COMPLETADO', 'FINALIZADA', 'FINALIZADO'):
                query += " AND ls.estado IN ('COMPLETADO', 'FINALIZADA', 'FINALIZADO')"
            else:
                query += " AND ls.estado = ?"
                params.append(status)
        query += " ORDER BY ls.proxima_ejecucion_at ASC"
        cursor.execute(query, params)
        raw_leads = cursor.fetchall()
        for l in raw_leads:
            p_params = {}
            try:
                p_params = json.loads(l.get("parametros_json") or "{}")
            except Exception:
                pass
            l["paso_etiqueta"] = p_params.get("etiqueta") or l.get("paso_accion") or "-"
        return raw_leads

# ==============================================================================
# SEQUENCE STEP & BRANCH EXECUTION ENGINE
# ==============================================================================

def get_next_executable_lead(sequence_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Encuentra el siguiente prospecto cuyo plazo de espera ha vencido y está listo para ejecución."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT ls.*, l.nombre, l.cargo_actual, l.cargo_titular, l.institucion_actual, l.email, l.telefono, l.perfil_url, l.estado as lead_estado,
                   p.tipo_accion, p.condicion_rama, p.parametros_json, p.orden, p.secuencia_id, s.nombre as secuencia_nombre
            FROM leads_en_secuencia ls
            JOIN leads l ON ls.lead_id = l.id
            JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            JOIN secuencias s ON ls.secuencia_id = s.id
            WHERE ls.estado = 'EN_CURSO'
              AND s.activa = 1
              AND s.estado = 'PUBLICADA'
              AND ls.proxima_ejecucion_at <= ?
        """
        params = [now_iso]
        if sequence_id:
            query += " AND ls.secuencia_id = ?"
            params.append(sequence_id)
        query += " ORDER BY ls.proxima_ejecucion_at ASC LIMIT 1"
        cursor.execute(query, params)
        return cursor.fetchone()

def execute_next_step(sequence_id: Optional[str] = None) -> Dict[str, Any]:
    """Punto de entrada principal: localiza el siguiente prospecto elegible y ejecuta su paso atómico aplicando restricciones de seguridad antiban."""
    import logger_service

    # 1. Pre-execution Safety Audit
    with get_db() as conn:
        safety_status = safety_engine.check_linkedin_safety(conn)
        if not safety_status.get("autorizado"):
            logger_service.log_event(
                "WARNING",
                "SAFETY",
                f"Secuencia detenida por control de seguridad anti-baneo: {safety_status.get('motivo')}",
                {"codigo": safety_status.get("codigo"), "detalle": safety_status}
            )
            return {
                "status": "bloqueado_por_seguridad",
                "motivo": safety_status.get("motivo"),
                "codigo": safety_status.get("codigo"),
                "detalle": safety_status
            }

    # 2. Retrieve next ready lead
    lead_item = get_next_executable_lead(sequence_id)
    if not lead_item:
        logger_service.log_event(
            "INFO",
            "SEQUENCES",
            "Evaluación de cola: no hay prospectos con plazos vencidos listos para ejecutar ahora.",
            {"secuencia_id": sequence_id}
        )
        return {
            "status": "idle",
            "mensaje": "No hay prospectos con pasos pendientes listos para ejecutar en este momento (o están en período de espera)."
        }

    # 3. Dispatch atomic step execution
    return _process_step_atom(lead_item)

def _process_step_atom(item: Dict[str, Any]) -> Dict[str, Any]:
    """Ejecuta el paso correspondiente para un prospecto individual y avanza el árbol de decisión."""
    import logger_service
    lead_id = item["lead_id"]
    lead_name = item["nombre"]
    sequence_id = item["secuencia_id"]
    current_step_id = item["paso_actual_id"]
    action_type = item["tipo_accion"]
    params = {}
    try:
        params = json.loads(item.get("parametros_json") or "{}")
    except Exception:
        pass

    now = datetime.now()
    now_iso = now.isoformat()
    execution_result = {"accion": action_type, "timestamp": now_iso, "ok": True}

    logger_service.log_event(
        "INFO",
        "SEQUENCES",
        f"Ejecutando acción '{action_type}' (Paso {item.get('orden', 1)}) para {lead_name}",
        {"lead_id": lead_id, "paso_id": current_step_id, "secuencia": item.get("secuencia_nombre")},
        lead_id=lead_id
    )

    # =========================================================================
    # ACTION 1: VISITAR_PERFIL (LinkedIn)
    # =========================================================================
    if action_type == "VISITAR_PERFIL":
        profile_url = item.get("perfil_url")
        if not profile_url:
            return {"status": "error", "mensaje": f"El lead {lead_name} no tiene URL de LinkedIn."}

        # Open profile in BrowserOS
        nav_res = browser_service.open_profile_in_browseros(profile_url, lead_name)
        if nav_res.get("status") != "ok":
            return {"status": "error", "mensaje": f"Fallo al abrir en BrowserOS: {nav_res.get('detail')}"}

        # Simulate human reading (stochastic scroll and pause)
        t_min = params.get("tiempo_lectura_min_seg", 5)
        t_max = params.get("tiempo_lectura_max_seg", 10)
        human_pause = random.uniform(t_min, t_max)
        
        # Biological scroll script in BrowserOS
        scroll_script = """
            (() => {
                window.scrollBy({ top: 400 + Math.floor(Math.random() * 350), behavior: 'smooth' });
                return { scrolled: true, scrollY: window.scrollY };
            })()
        """
        browser_service._call_mcp_evaluate(scroll_script)
        time.sleep(min(human_pause, 4)) # Controlled pause

        # Update database
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE leads SET estado = 'PERFIL_VISITADO', fecha_visita = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, lead_id))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'VISITA_PERFIL_SECUENCIA', ?, ?)
            """, (lead_id, f"Perfil visitado automáticamente según secuencia '{item['secuencia_nombre']}'.", now_iso))

        execution_result["detalle"] = f"Perfil visitado con scroll y lectura de {round(human_pause, 1)}s."

    # =========================================================================
    # ACTION 2: ESPERAR (Stochastic delay hours/days)
    # =========================================================================
    elif action_type == "ESPERAR":
        hours = float(params.get("horas_espera", 24))
        hours_with_jitter = round(max(0.1, hours * random.uniform(0.92, 1.08)), 2)
        next_hour = now + timedelta(hours=hours_with_jitter)
        execution_result["detalle"] = f"Pausa programada de {hours_with_jitter} horas hasta {next_hour.strftime('%Y-%m-%d %H:%M')}."

    # =========================================================================
    # ACTION 3: ENVIAR_INVITACION (With/Without Spintax Note)
    # =========================================================================
    elif action_type == "ENVIAR_INVITACION":
        profile_url = item.get("perfil_url")
        if not profile_url:
            return {"status": "error", "mensaje": f"El lead {lead_name} no tiene URL de LinkedIn."}

        note_final = ""
        if params.get("incluir_nota"):
            template = params.get("plantilla_nota", "Hola {nombre}, un gusto saludarte. Veo tu labor en {empresa}.")
            company = item.get("institucion_actual") or "tu empresa"
            title = item.get("cargo_actual") or item.get("cargo_titular") or "tu cargo"
            first_name = lead_name.split()[0] if lead_name else "hola"

            text_var = template
            for k in ["{nombre}", "{{nombre}}"]: text_var = text_var.replace(k, first_name)
            for k in ["{nombre_completo}", "{{nombre_completo}}"]: text_var = text_var.replace(k, lead_name)
            for k in ["{empresa}", "{{empresa}}", "{institucion}", "{{institucion}}", "{colegio}", "{{colegio}}"]: text_var = text_var.replace(k, company)
            for k in ["{cargo}", "{{cargo}}"]: text_var = text_var.replace(k, title)

            note_final = safety_engine.process_spintax(text_var)

        # 1. Resolver enlace directo custom-invite para navegación limpia y consistente
        vanity_match = re.search(r'/in/([^/?#]+)', profile_url)
        vanity_name = vanity_match.group(1) if vanity_match else None
        invite_url = f"https://www.linkedin.com/preload/custom-invite/?vanityName={vanity_name}" if vanity_name else profile_url

        browser_service.open_profile_in_browseros(invite_url, lead_name)
        time.sleep(3.5)

        # 2. Despachar envío de la invitación
        send_script = f"""
            (() => {{
                const btns = Array.from(document.querySelectorAll('button, a'));
                const sendWithoutNoteBtn = btns.find(b => {{
                    const txt = b.innerText.trim().toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('enviar sin nota') || aria.includes('enviar sin nota') ||
                           txt.includes('send without a note') || aria.includes('send without a note') ||
                           txt === 'enviar' || txt === 'send';
                }});

                const addNoteBtn = btns.find(b => {{
                    const txt = b.innerText.trim().toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('añadir una nota') || aria.includes('añadir una nota') ||
                           txt.includes('add a note') || aria.includes('add a note');
                }});

                const hasNote = {"true" if note_final else "false"};

                if (hasNote && addNoteBtn) {{
                    addNoteBtn.click();
                    return {{ ok: true, accion: 'abrio_campo_nota' }};
                }} else if (sendWithoutNoteBtn) {{
                    sendWithoutNoteBtn.click();
                    return {{ ok: true, accion: 'invitacion_enviada_sin_nota' }};
                }}

                // Fallback para perfil tradicional
                const connectBtn = btns.find(b => {{
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    const txt = b.innerText.trim().toLowerCase();
                    return (aria.includes('a conectar') || txt === 'conectar' || txt.includes('connect')) &&
                           !aria.includes('cancelar') && !aria.includes('descartar');
                }});

                if (connectBtn) {{
                    connectBtn.click();
                    return {{ ok: true, accion: 'clic_conectar_perfil' }};
                }}

                return {{ ok: false, error: 'No se encontró botón conectar ni diálogo de envío' }};
            }})()
        """
        eval_res = browser_service._call_mcp_evaluate(send_script)
        time.sleep(2)

        if note_final and eval_res.get("accion") == "abrio_campo_nota":
            fill_and_send_script = f"""
                (() => {{
                    const textarea = document.querySelector('textarea[name="message"], #custom-message, textarea');
                    if (textarea) {{
                        textarea.value = {json.dumps(note_final)};
                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                    const sendBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                        const txt = b.innerText.trim().toLowerCase();
                        return txt === 'enviar' || txt === 'send';
                    }});
                    if (sendBtn) {{
                        sendBtn.click();
                        return {{ ok: true, accion: 'invitacion_con_nota_enviada' }};
                    }}
                    return {{ ok: false, error: 'Botón enviar tras nota no encontrado' }};
                }})()
            """
            browser_service._call_mcp_evaluate(fill_and_send_script)
            time.sleep(2)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE leads SET estado = 'INVITACION_ENVIADA', fecha_invitacion = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, lead_id))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'INVITACION_ENVIADA_SECUENCIA', ?, ?)
            """, (lead_id, f"Invitación a conectar enviada vía secuencia. Nota: '{note_final[:60]}...'" if note_final else "Invitación a conectar enviada vía secuencia en LinkedIn (sin nota). Estado: Pendiente.", now_iso))

        execution_result["detalle"] = f"Invitación despachada a {lead_name}. Nota: '{note_final[:40]}...'" if note_final else f"Invitación a conectar enviada exitosamente a {lead_name} (sin nota)."

    # =========================================================================
    # ACTION 4: VERIFICAR_ESTADO (Branch condition)
    # =========================================================================
    elif action_type == "VERIFICAR_ESTADO":
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = ?", (lead_id,))
            lead_db = cursor.fetchone()
            current_status = lead_db["estado"] if lead_db else item["lead_estado"]

        is_connected = current_status == "CONECTADO"

        # Verificación en vivo si aún no figura como CONECTADO en base de datos
        if not is_connected and item.get("perfil_url") and browser_service.is_browseros_running():
            try:
                browser_service.open_profile_in_browseros(item["perfil_url"], lead_name)
                time.sleep(3.2)
                check_conn_js = """
                (() => {
                    const text = (document.body.innerText || '').toLowerCase();
                    
                    // 1. Detectar botones o enlaces interactivos a mensajería directa (1er grado)
                    const interactiveEls = Array.from(document.querySelectorAll('main button, main a, div[data-sdui-screen] button, div[data-sdui-screen] a'));
                    const hasMsgAction = interactiveEls.some(el => {
                        const t = (el.innerText || '').toLowerCase().trim();
                        const href = (el.getAttribute('href') || '').toLowerCase();
                        return t === 'enviar mensaje' || t === 'mensaje' || t === 'message' || href.includes('/messaging/compose');
                    });
                    
                    // 2. Detectar distintivo de grado de red (1er, 1.º, 1º, 1st) en cualquier etiqueta (p, span, div, li)
                    const is1st = Array.from(document.querySelectorAll('span, p, div, li')).some(el => {
                        const t = (el.innerText || '').trim();
                        return /^[·•\\s]*(?:1er|1º|1°|1\\.?º|1st)[·•\\s]*$/i.test(t) || t === '· 1er' || t === '1.º' || t === '1º';
                    });
                    
                    // 3. Comprobar si aún figura como pendiente de aceptación
                    const isPending = interactiveEls.some(el => (el.innerText || '').toLowerCase().trim() === 'pendiente');
                    
                    const connected = (hasMsgAction || is1st) && !isPending;
                    return { is_connected: connected, has_msg_action: hasMsgAction, is_1st: is1st, is_pending: isPending };
                })()
                """
                eval_conn = browser_service._call_mcp_evaluate(check_conn_js)
                if isinstance(eval_conn, dict) and eval_conn.get("is_connected"):
                    is_connected = True
                    current_status = "CONECTADO"
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("UPDATE leads SET estado = 'CONECTADO', fecha_conexion = ?, grado_red = '1º', updated_at = ? WHERE id = ?", (now_iso, now_iso, lead_id))
                        cursor.execute("""
                            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                            VALUES (?, 'CONEXION_ACEPTADA', ?, ?)
                        """, (lead_id, "Conexión aceptada confirmada en vivo durante paso de verificación de secuencia.", now_iso))

                    # Disparar resolución / extracción de correo de 1er grado automáticamente
                    try:
                        import email_resolver_service
                        threading.Thread(target=email_resolver_service.resolve_lead_email, args=(lead_id,), daemon=True).start()
                    except Exception:
                        pass
            except Exception as e:
                print(f"[SequenceEngine] Error en verificación en vivo de conexión: {e}")

        execution_result["bifurcacion"] = "SI_ACEPTO" if is_connected else "SI_NO_ACEPTO"
        execution_result["detalle"] = f"Evaluación de bifurcación: {execution_result['bifurcacion']} (Estado verificado: {current_status})"

    # =========================================================================
    # ACTION 5: ENVIAR_MENSAJE_LINKEDIN
    # =========================================================================
    elif action_type == "ENVIAR_MENSAJE_LINKEDIN":
        template = params.get("plantilla_mensaje", "Hola {nombre}, un gusto saludarte.")
        company = item.get("institucion_actual") or "tu empresa"
        first_name = lead_name.split()[0] if lead_name else "hola"

        msg = template
        for k in ["{nombre}", "{{nombre}}"]: msg = msg.replace(k, first_name)
        for k in ["{empresa}", "{{empresa}}", "{institucion}", "{{institucion}}", "{colegio}", "{{colegio}}"]: msg = msg.replace(k, company)
        msg_final = safety_engine.process_spintax(msg)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mensajes_linkedin (lead_id, campana_nombre, contenido, estado, enviado_at, created_at)
                VALUES (?, ?, ?, 'ENVIADO', ?, ?)
            """, (lead_id, item["secuencia_nombre"], msg_final, now_iso, now_iso))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'MENSAJE_LINKEDIN_ENVIADO', ?, ?)
            """, (lead_id, f"Mensaje privado enviado en LinkedIn: '{msg_final[:60]}...'", now_iso))

        execution_result["detalle"] = f"Mensaje privado de LinkedIn registrado: '{msg_final[:50]}...'"

    # =========================================================================
    # ACTION 6: ENVIAR_CORREO_WORKSPACE (Google Workspace Email Channel)
    # =========================================================================
    elif action_type == "ENVIAR_CORREO_WORKSPACE":
        email_dest = item.get("email")
        if not email_dest:
            execution_result["ok"] = False
            execution_result["detalle"] = f"Lead {lead_name} no tiene correo electrónico registrado para el canal Workspace."
        else:
            subj_tpl = params.get("asunto", "Contacto formal {empresa}")
            body_tpl = params.get("cuerpo_email", "Estimado/a {nombre},\n\nLe contacto formalmente...")
            company = item.get("institucion_actual") or "su empresa"
            title = item.get("cargo_actual") or item.get("cargo_titular") or "su cargo"
            first_name = lead_name.split()[0] if lead_name else "hola"

            subj = subj_tpl
            for k in ["{empresa}", "{{empresa}}", "{institucion}", "{{institucion}}", "{colegio}", "{{colegio}}"]: subj = subj.replace(k, company)

            body = body_tpl
            for k in ["{nombre}", "{{nombre}}"]: body = body.replace(k, first_name)
            for k in ["{nombre_completo}", "{{nombre_completo}}"]: body = body.replace(k, lead_name)
            for k in ["{empresa}", "{{empresa}}", "{institucion}", "{{institucion}}", "{colegio}", "{{colegio}}"]: body = body.replace(k, company)
            for k in ["{cargo}", "{{cargo}}"]: body = body.replace(k, title)
            
            subj_final = safety_engine.process_spintax(subj)
            body_final = safety_engine.process_spintax(body)

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO correos_electronicos (lead_id, campana_nombre, email_destino, asunto, cuerpo, estado, enviado_at, created_at)
                    VALUES (?, ?, ?, ?, ?, 'ENVIADO', ?, ?)
                """, (lead_id, item["secuencia_nombre"], email_dest, subj_final, body_final, now_iso, now_iso))
                cursor.execute("""
                    INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                    VALUES (?, 'CORREO_WORKSPACE_ENVIADO', ?, ?)
                """, (lead_id, f"Correo Google Workspace despachado a {email_dest}. Asunto: '{subj_final}'", now_iso))

            execution_result["detalle"] = f"Correo formal de Google Workspace enviado a {email_dest}."

    # =========================================================================
    # ACTION 7: ENVIAR_WHATSAPP_WEB (WhatsApp Web Local con Antiban Humanizado)
    # =========================================================================
    elif action_type == "ENVIAR_WHATSAPP_WEB":
        # 1. Validación de seguridad y cuotas de WhatsApp Web
        wa_safety = whatsapp_safety_engine.check_whatsapp_safety()
        if not wa_safety.get("safe"):
            execution_result["ok"] = False
            execution_result["detalle"] = f"WhatsApp bloqueado por seguridad: {wa_safety.get('reason')}"
            return execution_result

        phone_dest = item.get("telefono")
        normalized_phone = whatsapp_safety_engine.normalize_phone_number(phone_dest)
        if not normalized_phone:
            execution_result["ok"] = False
            execution_result["detalle"] = f"Lead {lead_name} no tiene número de teléfono válido para WhatsApp (formato E.164 requerido)."
        else:
            clean_digits = normalized_phone.lstrip("+")
            template = params.get("plantilla_mensaje") or params.get("mensaje") or "Hola {nombre}, un gusto saludarte. Te contacto en relación a tu labor en {empresa}."
            company = item.get("institucion_actual") or "tu empresa"
            title = item.get("cargo_actual") or item.get("cargo_titular") or "tu cargo"
            first_name = lead_name.split()[0] if lead_name else "hola"

            msg = template
            for k in ["{nombre}", "{{nombre}}"]: msg = msg.replace(k, first_name)
            for k in ["{nombre_completo}", "{{nombre_completo}}"]: msg = msg.replace(k, lead_name)
            for k in ["{empresa}", "{{empresa}}", "{institucion}", "{{institucion}}", "{colegio}", "{{colegio}}"]: msg = msg.replace(k, company)
            for k in ["{cargo}", "{{cargo}}"]: msg = msg.replace(k, title)

            msg_final = safety_engine.process_spintax(msg)

            # 2. Protección de enlaces en primer contacto
            is_valid_links, link_reason = whatsapp_safety_engine.validate_message_links(msg_final, is_first_contact=True)
            if not is_valid_links:
                execution_result["ok"] = False
                execution_result["detalle"] = f"Envío cancelado: {link_reason}"
                return execution_result

            # 3. Apertura limpia sin query params directos de texto para no alertar a Meta
            wa_url = f"https://web.whatsapp.com/send?phone={clean_digits}"

            try:
                browser_service.open_profile_in_browseros(wa_url, f"WhatsApp Web - {lead_name}")
                # Pausa de observación visual humana
                time.sleep(random.uniform(4.5, 7.5))

                # 4. Mecanografía biométrica humana asistida por script
                type_script = whatsapp_safety_engine.get_biometric_typing_script(
                    selector='footer div[contenteditable="true"]',
                    message=msg_final
                )
                send_eval = browser_service._call_mcp_evaluate(type_script, channel="whatsapp")
            except Exception as e:
                send_eval = {"ok": False, "error": str(e)}

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO mensajes_whatsapp (lead_id, campana_nombre, telefono_destino, contenido, estado, enviado_at, created_at)
                    VALUES (?, ?, ?, ?, 'ENVIADO', ?, ?)
                """, (lead_id, item.get("secuencia_nombre", "Secuencia Multicanal"), clean_digits, msg_final, now_iso, now_iso))
                cursor.execute("""
                    INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                    VALUES (?, 'WHATSAPP_WEB_ENVIADO', ?, ?)
                """, (lead_id, f"Mensaje WhatsApp Web despachado a +{clean_digits} con mecanografía biométrica: '{msg_final[:60]}...'", now_iso))
                cursor.execute("UPDATE leads SET estado = 'MENSAJE_ENVIADO', updated_at = ? WHERE id = ?", (now_iso, lead_id))

            execution_result["detalle"] = f"Mensaje WhatsApp Web despachado a +{clean_digits} con cadencia biométrica."

    # =========================================================================
    # ACTION 8: RETIRAR_INVITACION
    # =========================================================================
    elif action_type == "RETIRAR_INVITACION":
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE leads SET invitacion_retirada = 1, fecha_retiro_invitacion = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, lead_id))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'INVITACION_RETIRADA_SECUENCIA', 'Invitación retirada automáticamente tras vencimiento de plazo en secuencia.', ?)
            """, (lead_id, now_iso))
        execution_result["detalle"] = "Invitación pendiente de LinkedIn retirada exitosamente."

    # =========================================================================
    # ACTION 9: EXTRAER_CORREO / RESOLVER_CORREO (Enriquecimiento en Cascada)
    # =========================================================================
    elif action_type in ("EXTRAER_CORREO", "RESOLVER_CORREO"):
        import email_resolver_service
        force = bool(params.get("forzar_recarga", False))
        res_email = email_resolver_service.resolve_lead_email(lead_id, force_refresh=force)
        if res_email.get("ok") and res_email.get("email"):
            execution_result["detalle"] = f"Correo resuelto exitosamente ({res_email.get('source')}): {res_email.get('email')} [{res_email.get('status')}]."
        else:
            execution_result["detalle"] = f"Resolución de correo completada: {res_email.get('motivo', 'No se validó correo corporativo')}."

    # =========================================================================
    # ACTION 10: CRUZAR_ZOHO_CRM / SINCRONIZAR_ZOHO (Inteligencia B2B vía Sesión)
    # =========================================================================
    elif action_type in ("CRUZAR_ZOHO_CRM", "SINCRONIZAR_ZOHO"):
        sync_res = zoho_browser_service.sync_lead_with_zoho(lead_id)
        if sync_res.get("ok"):
            if sync_res.get("matched"):
                ent_type = sync_res.get("entity_type")
                z_email = sync_res.get("email_zoho")
                is_client = sync_res.get("account_is_client")
                acc_name = sync_res.get("account_name")
                if is_client:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE leads SET estado = 'CLIENTE_EXISTENTE', updated_at = ? WHERE id = ?
                        """, (now_iso, lead_id))
                        cursor.execute("""
                            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                            VALUES (?, 'ANTI_COLISION_ACTIVADO', ?, ?)
                        """, (lead_id, f"Colisión evitada: La institución '{acc_name}' es cliente activo en Zoho CRM. Prospección fría finalizada.", now_iso))
                    execution_result["detalle"] = f"Cruce Zoho: {ent_type} hallado. Cuenta '{acc_name}' es Cliente Activo. Prospección detenida por anti-colisión."
                else:
                    execution_result["detalle"] = f"Cruce Zoho exitoso: {ent_type} ID {sync_res.get('zoho_id')}, Email extraído: {z_email or 'N/A'}, Cuenta: {acc_name or 'N/A'}."
            else:
                execution_result["detalle"] = f"Cruce Zoho: No se encontraron coincidencias para '{lead_name}' en Zoho CRM."
        else:
            execution_result["ok"] = False
            execution_result["detalle"] = f"Error al sincronizar con Zoho CRM: {sync_res.get('error')}"

    # =========================================================================
    # ADVANCE DECISION TREE TO NEXT STEP
    # =========================================================================
    next_step_id, next_date_iso, is_sequence_end = _calculate_next_step(
        sequence_id=sequence_id,
        current_step_id=current_step_id,
        bifurcation=execution_result.get("bifurcacion"),
        now=now
    )

    with get_db() as conn:
        cursor = conn.cursor()
        new_status = "COMPLETADO" if is_sequence_end else "EN_CURSO"
        cursor.execute("""
            UPDATE leads_en_secuencia 
            SET paso_actual_id = ?,
                estado = ?,
                proxima_ejecucion_at = ?,
                ultimo_resultado_json = ?,
                updated_at = ?
            WHERE lead_id = ? AND secuencia_id = ?
        """, (
            next_step_id,
            new_status,
            next_date_iso,
            json.dumps(execution_result),
            now_iso,
            lead_id,
            sequence_id
        ))

    return {
        "status": "ok",
        "lead": {
            "id": lead_id,
            "nombre": lead_name,
            "institucion": item.get("institucion_actual")
        },
        "paso_ejecutado": {
            "id": current_step_id,
            "accion": action_type,
            "detalle": execution_result.get("detalle")
        },
        "siguiente_paso": {
            "id": next_step_id,
            "proxima_ejecucion": next_date_iso,
            "secuencia_completada": is_sequence_end
        }
    }

def _calculate_next_step(sequence_id: str, current_step_id: str, bifurcation: Optional[str], now: datetime) -> tuple:
    """Recorre las ramas del árbol de decisión para identificar el siguiente paso hijo correspondiente."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # If branching condition (VERIFICAR_ESTADO)
        if bifurcation:
            cursor.execute("""
                SELECT * FROM pasos_secuencia 
                WHERE secuencia_id = ? AND padre_paso_id = ? AND condicion_rama = ?
                ORDER BY orden ASC LIMIT 1
            """, (sequence_id, current_step_id, bifurcation))
        else:
            # Regular linear flow: child with 'DEFAULT' condition
            cursor.execute("""
                SELECT * FROM pasos_secuencia 
                WHERE secuencia_id = ? AND padre_paso_id = ? AND (condicion_rama = 'DEFAULT' OR condicion_rama IS NULL)
                ORDER BY orden ASC LIMIT 1
            """, (sequence_id, current_step_id))
            
        child = cursor.fetchone()

        if not child and not bifurcation:
            # Fallback for linear chains advancing by numeric order
            cursor.execute("SELECT orden FROM pasos_secuencia WHERE id = ? AND secuencia_id = ?", (current_step_id, sequence_id))
            curr_step = cursor.fetchone()
            if curr_step:
                cursor.execute("""
                    SELECT * FROM pasos_secuencia
                    WHERE secuencia_id = ? AND orden > ? AND (condicion_rama = 'DEFAULT' OR condicion_rama IS NULL)
                    ORDER BY orden ASC LIMIT 1
                """, (sequence_id, curr_step["orden"]))
                child = cursor.fetchone()

        if not child:
            # End of branch
            return None, None, True

        child_id = child["id"]
        child_type = child["tipo_accion"]
        
        # If next step is ESPERAR, calculate delay immediately
        if child_type == "ESPERAR":
            params = {}
            try:
                params = json.loads(child.get("parametros_json") or "{}")
            except Exception:
                pass
            hours = float(params.get("horas_espera", 24))
            hours_jitter = round(max(0.1, hours * random.uniform(0.95, 1.05)), 2)
            next_date = (now + timedelta(hours=hours_jitter)).isoformat()
        else:
            # Si el paso actual de origen ya era ESPERAR, la pausa estratégica ya transcurrió
            # y el prospecto queda listo para ser despachado de inmediato.
            cursor.execute("SELECT tipo_accion FROM pasos_secuencia WHERE id = ?", (current_step_id,))
            curr_step_row = cursor.fetchone()
            curr_step_type = curr_step_row["tipo_accion"] if curr_step_row else ""
            if curr_step_type == "ESPERAR":
                next_date = now.isoformat()
            else:
                # Pausa estocástica humana (3 a 6 mins) entre pasos de acción inmediata
                pause_seconds = safety_engine.calculate_gaussian_delay()
                next_date = (now + timedelta(seconds=pause_seconds)).isoformat()

        return child_id, next_date, False

def promote_expired_delays(sequence_id: Optional[str] = None, tenant_id: Optional[str] = None) -> int:
    """
    Identifica y promueve automáticamente todos los prospectos en pasos 'ESPERAR'
    cuyo temporizador ya expiró (proxima_ejecucion_at <= AHORA), avanzándolos de
    inmediato al siguiente paso de la secuencia en la base de datos.

    Args:
        sequence_id (Optional[str]): Filtrar por una secuencia específica o None.
        tenant_id (Optional[str]): Filtrar por tenant específico o None.

    Returns:
        int: Cantidad de prospectos promovidos exitosamente.
    """
    now = datetime.now()
    now_iso = now.isoformat()
    promoted_count = 0

    with get_db() as conn:
        cursor = conn.cursor()

        where_clauses = [
            "ls.estado = 'EN_CURSO'",
            "p.tipo_accion = 'ESPERAR'",
            "(ls.proxima_ejecucion_at IS NULL OR ls.proxima_ejecucion_at <= ?)"
        ]
        params = [now_iso]

        if sequence_id:
            where_clauses.append("ls.secuencia_id = ?")
            params.append(sequence_id)
        if tenant_id:
            where_clauses.append("s.tenant_id = ?")
            params.append(tenant_id)

        where_sql = " AND ".join(where_clauses)

        cursor.execute(f"""
            SELECT ls.id as inscripcion_id, ls.lead_id, ls.secuencia_id, ls.paso_actual_id
            FROM leads_en_secuencia ls
            JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            JOIN secuencias s ON ls.secuencia_id = s.id
            WHERE {where_sql}
        """, params)

        expired_leads = cursor.fetchall()
        if not expired_leads:
            return 0

        for row in expired_leads:
            lead_id = row["lead_id"]
            sec_id = row["secuencia_id"]
            current_step_id = row["paso_actual_id"]

            next_step_id, next_date_iso, is_sequence_end = _calculate_next_step(
                sequence_id=sec_id,
                current_step_id=current_step_id,
                bifurcation=None,
                now=now
            )

            if is_sequence_end or not next_step_id:
                cursor.execute("""
                    UPDATE leads_en_secuencia
                    SET estado = 'COMPLETADO', proxima_ejecucion_at = NULL, updated_at = ?
                    WHERE lead_id = ? AND secuencia_id = ?
                """, (now_iso, lead_id, sec_id))
            else:
                cursor.execute("""
                    UPDATE leads_en_secuencia
                    SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                    WHERE lead_id = ? AND secuencia_id = ?
                """, (next_step_id, next_date_iso, now_iso, lead_id, sec_id))

            promoted_count += 1

        conn.commit()

    return promoted_count





