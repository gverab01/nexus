"""
NexusReach Pro - Servicio Centralizado de Cola de Tareas y Ritmo Antibaneo (TASK-QUEUE-02)
Gestiona la persistencia, despacho atomizado con SKIP LOCKED, cálculo de jitter gaussiano
y control de límites diarios por tenant sobre PostgreSQL 16.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import get_db

logger = logging.getLogger("nexusreach.task_queue")

POLITICAS_PREDETERMINADAS = [
    {
        "tipo_tarea": "LI_INVITE",
        "descripcion": "Enviar Invitación con/sin nota personalizada",
        "limite_diario": 50,
        "pausa_min_seg": 240,  # 4 min
        "pausa_max_seg": 480,  # 8 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_VISIT",
        "descripcion": "Visitar perfil orgánicamente en LinkedIn",
        "limite_diario": 70,
        "pausa_min_seg": 90,   # 1.5 min
        "pausa_max_seg": 180,  # 3 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_ENRICH",
        "descripcion": "Sincronizar y enriquecer perfil en vivo",
        "limite_diario": 50,
        "pausa_min_seg": 120,  # 2 min
        "pausa_max_seg": 240,  # 4 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_MESSAGE",
        "descripcion": "Mensaje directo a contacto de 1er grado",
        "limite_diario": 35,
        "pausa_min_seg": 180,  # 3 min
        "pausa_max_seg": 360,  # 6 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_ENDORSE",
        "descripcion": "Validar aptitudes clave (Skill Endorse)",
        "limite_diario": 25,
        "pausa_min_seg": 120,  # 2 min
        "pausa_max_seg": 240,  # 4 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_REACT",
        "descripcion": "Reaccionar a última publicación (Like/Celebrar)",
        "limite_diario": 40,
        "pausa_min_seg": 90,   # 1.5 min
        "pausa_max_seg": 180,  # 3 min
        "nivel_riesgo": "MEDIO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_COMMENT",
        "descripcion": "Comentario asistido en publicación relevante",
        "limite_diario": 12,
        "pausa_min_seg": 300,  # 5 min
        "pausa_max_seg": 600,  # 10 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "EMAIL_OUTREACH",
        "descripcion": "Envío de correo corporativo frío (SMTP)",
        "limite_diario": 60,
        "pausa_min_seg": 60,   # 1 min
        "pausa_max_seg": 150,  # 2.5 min
        "nivel_riesgo": "MEDIO",
        "activo": True
    },
    {
        "tipo_tarea": "ZOHO_SYNC",
        "descripcion": "Cruce y validación con Zoho CRM",
        "limite_diario": 300,
        "pausa_min_seg": 3,
        "pausa_max_seg": 8,
        "nivel_riesgo": "BAJO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_WITHDRAW_STALE",
        "descripcion": "Retiro de invitaciones vencidas (>21 días)",
        "limite_diario": 25,
        "pausa_min_seg": 60,   # 1 min
        "pausa_max_seg": 120,  # 2 min
        "nivel_riesgo": "BAJO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_SYNC_ACCEPTED",
        "descripcion": "Detección de nuevas conexiones aceptadas",
        "limite_diario": 10,
        "pausa_min_seg": 60,
        "pausa_max_seg": 120,
        "nivel_riesgo": "BAJO",
        "activo": True
    }
]

def ensure_tenant_policies(tenant_id: str) -> None:
    """Asegura que el tenant tenga sembradas las políticas de ritmo base en PostgreSQL."""
    if not tenant_id:
        return
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        for pol in POLITICAS_PREDETERMINADAS:
            cursor.execute("""
                INSERT INTO politicas_ritmo_tareas 
                (tenant_id, tipo_tarea, descripcion, limite_diario, pausa_min_seg, pausa_max_seg, nivel_riesgo, activo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, tipo_tarea) DO NOTHING;
            """, (
                tenant_id, pol["tipo_tarea"], pol["descripcion"], pol["limite_diario"],
                pol["pausa_min_seg"], pol["pausa_max_seg"], pol["nivel_riesgo"], pol["activo"]
            ))

def get_tenant_policies(tenant_id: str) -> List[Dict[str, Any]]:
    """Obtiene la lista de políticas configuradas para el tenant con sus consumos del día."""
    ensure_tenant_policies(tenant_id)
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.tipo_tarea, p.descripcion, p.limite_diario, p.pausa_min_seg, 
                   p.pausa_max_seg, p.nivel_riesgo, p.activo,
                   COALESCE(
                       (SELECT COUNT(*) FROM cola_tareas_central c 
                        WHERE c.tenant_id = p.tenant_id 
                          AND c.tipo_tarea = p.tipo_tarea 
                          AND c.estado = 'COMPLETADO' 
                          AND c.finalizado_at >= CURRENT_DATE), 0
                   ) as ejecutadas_hoy
            FROM politicas_ritmo_tareas p
            WHERE p.tenant_id = %s
            ORDER BY 
                CASE p.nivel_riesgo 
                    WHEN 'ALTO' THEN 1 
                    WHEN 'MEDIO' THEN 2 
                    ELSE 3 
                END,
                p.tipo_tarea ASC;
        """, (tenant_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def update_tenant_policy(
    tenant_id: str,
    tipo_tarea: str,
    limite_diario: Optional[int] = None,
    pausa_min_seg: Optional[int] = None,
    pausa_max_seg: Optional[int] = None,
    activo: Optional[bool] = None
) -> Dict[str, Any]:
    """Actualiza los parámetros granulares de una política de ritmo para un tenant."""
    ensure_tenant_policies(tenant_id)
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM politicas_ritmo_tareas WHERE tenant_id = %s AND tipo_tarea = %s",
            (tenant_id, tipo_tarea)
        )
        current = cursor.fetchone()
        if not current:
            raise ValueError(f"No existe política para la tarea '{tipo_tarea}' en el tenant '{tenant_id}'")

        new_limite = int(limite_diario) if limite_diario is not None else current["limite_diario"]
        new_min = int(pausa_min_seg) if pausa_min_seg is not None else current["pausa_min_seg"]
        new_max = int(pausa_max_seg) if pausa_max_seg is not None else current["pausa_max_seg"]
        new_activo = bool(activo) if activo is not None else current["activo"]

        if new_min < 1:
            new_min = 1
        if new_max < new_min:
            new_max = new_min

        now_iso = datetime.now()
        cursor.execute("""
            UPDATE politicas_ritmo_tareas
            SET limite_diario = %s, pausa_min_seg = %s, pausa_max_seg = %s, activo = %s, updated_at = %s
            WHERE tenant_id = %s AND tipo_tarea = %s
        """, (new_limite, new_min, new_max, new_activo, now_iso, tenant_id, tipo_tarea))

        cursor.execute(
            "SELECT * FROM politicas_ritmo_tareas WHERE tenant_id = %s AND tipo_tarea = %s",
            (tenant_id, tipo_tarea)
        )
        return dict(cursor.fetchone())

def reset_tenant_policies_to_recommended(tenant_id: str) -> List[Dict[str, Any]]:
    """Restaura todas las políticas del tenant a los valores seguros estándar antibaneo (50 inv/día)."""
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        now_iso = datetime.now()
        for pol in POLITICAS_PREDETERMINADAS:
            cursor.execute("""
                INSERT INTO politicas_ritmo_tareas 
                (tenant_id, tipo_tarea, descripcion, limite_diario, pausa_min_seg, pausa_max_seg, nivel_riesgo, activo, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, tipo_tarea) DO UPDATE SET
                    limite_diario = EXCLUDED.limite_diario,
                    pausa_min_seg = EXCLUDED.pausa_min_seg,
                    pausa_max_seg = EXCLUDED.pausa_max_seg,
                    activo = EXCLUDED.activo,
                    updated_at = EXCLUDED.updated_at;
            """, (
                tenant_id, pol["tipo_tarea"], pol["descripcion"], pol["limite_diario"],
                pol["pausa_min_seg"], pol["pausa_max_seg"], pol["nivel_riesgo"], pol["activo"], now_iso
            ))
    return get_tenant_policies(tenant_id)

def calculate_jitter_seconds(min_sec: int, max_sec: int) -> int:
    """Calcula una pausa estocástica con distribución normal/gaussiana truncada para simular el comportamiento humano."""
    if min_sec >= max_sec:
        return min_sec
    mean = (min_sec + max_sec) / 2.0
    sigma = (max_sec - min_sec) / 4.0
    sample = random.gauss(mean, sigma)
    clamped = max(min_sec, min(max_sec, int(round(sample))))
    return clamped

def enqueue_batch_actions(
    tenant_id: str,
    tipo_tarea: str,
    lead_ids: List[str],
    payload: Optional[Dict[str, Any]] = None,
    prioridad: int = 5
) -> Dict[str, Any]:
    """
    Encola en PostgreSQL un lote de prospectos calculando marcas temporales orgánicas con jitter.
    Garantiza que no se generen tareas duplicadas en estado PENDIENTE para el mismo lead y tipo de acción.
    """
    if not tenant_id:
        raise ValueError("tenant_id requerido para encolar acciones.")
    if not lead_ids:
        return {"enqueued": 0, "skipped": 0, "mensaje": "Lista de leads vacía."}

    ensure_tenant_policies(tenant_id)
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()

        # Obtener política para la tarea
        cursor.execute(
            "SELECT * FROM politicas_ritmo_tareas WHERE tenant_id = %s AND tipo_tarea = %s",
            (tenant_id, tipo_tarea)
        )
        policy = cursor.fetchone()
        p_min = policy["pausa_min_seg"] if policy else 120
        p_max = policy["pausa_max_seg"] if policy else 240

        # Obtener la hora programada más lejana de las tareas pendientes de este tenant para encadenar
        cursor.execute("""
            SELECT MAX(programado_para) as ultima_hora
            FROM cola_tareas_central
            WHERE tenant_id = %s AND estado = 'PENDIENTE';
        """, (tenant_id,))
        row = cursor.fetchone()
        ultima_hora = row["ultima_hora"] if row and row["ultima_hora"] else None

        now = datetime.now()
        base_time = ultima_hora if (ultima_hora and ultima_hora > now) else now

        # Verificar duplicados pendientes
        cursor.execute("""
            SELECT lead_id FROM cola_tareas_central
            WHERE tenant_id = %s AND tipo_tarea = %s AND estado IN ('PENDIENTE', 'EN_PROCESO');
        """, (tenant_id, tipo_tarea))
        already_queued = {r["lead_id"] for r in cursor.fetchall() if r["lead_id"]}

        enqueued_count = 0
        skipped_count = 0
        current_schedule = base_time
        payload_data = payload or {}

        for l_id in lead_ids:
            if not l_id:
                continue
            if l_id in already_queued:
                skipped_count += 1
                continue

            jitter_pause = calculate_jitter_seconds(p_min, p_max)
            current_schedule = current_schedule + timedelta(seconds=jitter_pause)

            cursor.execute("""
                INSERT INTO cola_tareas_central
                (tenant_id, lead_id, tipo_tarea, prioridad, estado, payload_json, programado_para)
                VALUES (%s, %s, %s, %s, 'PENDIENTE', %s, %s);
            """, (
                tenant_id, l_id, tipo_tarea, prioridad,
                json.dumps(payload_data), current_schedule
            ))
            already_queued.add(l_id)
            enqueued_count += 1

    return {
        "enqueued": enqueued_count,
        "skipped": skipped_count,
        "primera_ejecucion": base_time.isoformat(),
        "ultima_ejecucion": current_schedule.isoformat(),
        "mensaje": f"{enqueued_count} tareas encoladas con éxito en PostgreSQL ({skipped_count} omitidas por ya estar en cola)."
    }

def get_next_task_for_worker(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Entrega la siguiente tarea lista para ser ejecutada por el runner local en Electron.
    Usa 'FOR UPDATE SKIP LOCKED' para evitar colisiones atómicas y valida límites diarios del día.
    """
    if not tenant_id:
        return None

    now = datetime.now()
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()

        # Seleccionar la tarea más prioritaria cuyo tiempo programado haya llegado
        cursor.execute("""
            SELECT c.*, l.nombre as lead_nombre, l.perfil_url as lead_url
            FROM cola_tareas_central c
            LEFT JOIN leads l ON l.id = c.lead_id
            WHERE c.tenant_id = %s
              AND c.estado = 'PENDIENTE'
              AND c.programado_para <= %s
            ORDER BY c.prioridad ASC, c.programado_para ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED;
        """, (tenant_id, now))
        task = cursor.fetchone()
        if not task:
            return None

        task_dict = dict(task)
        tipo = task_dict["tipo_tarea"]

        # Validar si este tipo de tarea está activo y dentro del límite diario
        cursor.execute("""
            SELECT p.activo, p.limite_diario,
                   (SELECT COUNT(*) FROM cola_tareas_central 
                    WHERE tenant_id = %s AND tipo_tarea = %s 
                      AND estado = 'COMPLETADO' AND finalizado_at >= CURRENT_DATE) as ejecutadas_hoy
            FROM politicas_ritmo_tareas p
            WHERE p.tenant_id = %s AND p.tipo_tarea = %s;
        """, (tenant_id, tipo, tenant_id, tipo))
        pol_row = cursor.fetchone()

        if pol_row:
            if not pol_row["activo"]:
                # Política desactivada: marcar en pausa
                cursor.execute(
                    "UPDATE cola_tareas_central SET estado = 'PAUSADO', error_detalle = 'Tarea desactivada por política' WHERE id = %s",
                    (task_dict["id"],)
                )
                return None

            if pol_row["ejecutadas_hoy"] >= pol_row["limite_diario"]:
                # Cuota diaria alcanzada: reprogramar para mañana a las 09:00 AM
                manana_9am = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()) + timedelta(hours=9, minutes=random.randint(5, 30))
                cursor.execute(
                    "UPDATE cola_tareas_central SET programado_para = %s, error_detalle = 'Cuota diaria alcanzada. Pospuesta para mañana' WHERE id = %s",
                    (manana_9am, task_dict["id"])
                )
                return None

        # Marcar la tarea en proceso
        cursor.execute("""
            UPDATE cola_tareas_central
            SET estado = 'EN_PROCESO', iniciado_at = %s, intentos = intentos + 1
            WHERE id = %s;
        """, (now, task_dict["id"]))

        # Deserializar JSONs si vienen como texto
        for j_key in ["payload_json", "resultado_json"]:
            if isinstance(task_dict.get(j_key), str):
                try:
                    task_dict[j_key] = json.loads(task_dict[j_key])
                except Exception:
                    task_dict[j_key] = {}

        return task_dict

def report_task_result(
    task_id: str,
    tenant_id: str,
    success: bool,
    resultado: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> Dict[str, Any]:
    """Actualiza el resultado de la tarea en la cola central y registra eventos de auditoría."""
    now = datetime.now()
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cola_tareas_central WHERE id = %s AND tenant_id = %s", (task_id, tenant_id))
        task = cursor.fetchone()
        if not task:
            raise ValueError(f"Tarea con ID '{task_id}' no encontrada para el tenant.")

        if success:
            cursor.execute("""
                UPDATE cola_tareas_central
                SET estado = 'COMPLETADO', finalizado_at = %s, resultado_json = %s, error_detalle = NULL
                WHERE id = %s;
            """, (now, json.dumps(resultado or {}), task_id))
        else:
            intentos = task["intentos"]
            max_intentos = task["max_intentos"]
            if intentos >= max_intentos:
                nuevo_estado = "FALLIDO"
                next_time = task["programado_para"]
            else:
                nuevo_estado = "PENDIENTE"
                # Backoff exponencial: reintentar en 5 a 15 minutos
                next_time = now + timedelta(minutes=random.randint(5, 12))

            cursor.execute("""
                UPDATE cola_tareas_central
                SET estado = %s, programado_para = %s, error_detalle = %s, resultado_json = %s
                WHERE id = %s;
            """, (nuevo_estado, next_time, error or "Error desconocido durante la ejecución", json.dumps(resultado or {}), task_id))

        return {"status": "ok", "task_id": task_id, "estado": "COMPLETADO" if success else nuevo_estado}

def get_queue_summary(tenant_id: str) -> Dict[str, Any]:
    """Retorna métricas ejecutivas de la cola para los badges y cabeceras de la aplicación."""
    ensure_tenant_policies(tenant_id)
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE estado = 'PENDIENTE') as pendientes,
                COUNT(*) FILTER (WHERE estado = 'EN_PROCESO') as en_proceso,
                COUNT(*) FILTER (WHERE estado = 'COMPLETADO' AND finalizado_at >= CURRENT_DATE) as completadas_hoy,
                COUNT(*) FILTER (WHERE estado = 'FALLIDO' AND (finalizado_at >= CURRENT_DATE OR finalizado_at IS NULL)) as fallidas_hoy,
                MIN(programado_para) FILTER (WHERE estado = 'PENDIENTE') as proxima_ejecucion
            FROM cola_tareas_central
            WHERE tenant_id = %s;
        """, (tenant_id,))
        row = cursor.fetchone()

        prox = row["proxima_ejecucion"]
        return {
            "pendientes": int(row["pendientes"] or 0),
            "en_proceso": int(row["en_proceso"] or 0),
            "completadas_hoy": int(row["completadas_hoy"] or 0),
            "fallidas_hoy": int(row["fallidas_hoy"] or 0),
            "proxima_ejecucion": prox.isoformat() if prox else None
        }

def cancel_pending_tasks(tenant_id: str, task_ids: Optional[List[str]] = None) -> int:
    """Cancela tareas pendientes del tenant en PostgreSQL."""
    with get_db(tenant_id=tenant_id) as conn:
        cursor = conn.cursor()
        if task_ids:
            cursor.execute("""
                UPDATE cola_tareas_central
                SET estado = 'CANCELADO', error_detalle = 'Cancelado por el usuario'
                WHERE tenant_id = %s AND id = ANY(%s) AND estado = 'PENDIENTE';
            """, (tenant_id, task_ids))
        else:
            cursor.execute("""
                UPDATE cola_tareas_central
                SET estado = 'CANCELADO', error_detalle = 'Cancelado en bloque por el usuario'
                WHERE tenant_id = %s AND estado = 'PENDIENTE';
            """, (tenant_id,))
        return cursor.rowcount

def execute_task_action(task: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Ejecuta de forma nativa la acción asociada a una tarea de la cola central."""
    tipo = task.get("tipo_tarea")
    lead_id = task.get("lead_id")
    tenant_id = task.get("tenant_id")

    if tipo == "LI_ENRICH":
        if not lead_id:
            return False, None, "Tarea sin lead_id asignado"
        with get_db(tenant_id=tenant_id) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM leads WHERE id = %s AND tenant_id = %s", (lead_id, tenant_id))
            lead = cur.fetchone()
            if not lead:
                return False, None, f"Lead '{lead_id}' no encontrado en el tenant"
            url = lead.get("perfil_url")
            if not url:
                return False, None, "El lead no tiene URL de LinkedIn asignada"

        import extractor_engine
        enriched = extractor_engine.enrich_lead_from_live_profile(url)
        if not enriched.get("ok"):
            err_msg = enriched.get("error", "Error sincronizando con LinkedIn")
            return False, enriched, err_msg

        now_iso = datetime.now().isoformat()
        nuevo_nombre = enriched.get("nombre")
        if not nuevo_nombre or "esta página no existe" in nuevo_nombre.lower() or "404" in nuevo_nombre.lower():
            nuevo_nombre = lead.get("nombre")
        nuevo_titular = enriched.get("cargo_titular") or lead.get("cargo_titular")
        nuevo_cargo_act = enriched.get("cargo_actual") or lead.get("cargo_actual")
        nueva_inst = (enriched.get("institucion_actual") or "").strip()
        if not nueva_inst or nueva_inst.lower() in ["institución educativa", "institución escolar", "empresa u organización", "chile"]:
            prev_inst = (lead.get("institucion_actual") or "").strip()
            if prev_inst and prev_inst.lower() not in ["institución educativa", "institución escolar", "empresa u organización", "chile"]:
                nueva_inst = prev_inst
            else:
                nueva_inst = ""
        nueva_ubic = enriched.get("ubicacion") or lead.get("ubicacion")
        nuevo_grado = enriched.get("grado_red") or lead.get("grado_red")
        nuevo_estado = "CONECTADO" if nuevo_grado == "1º" else lead.get("estado")
        nueva_fecha_conn = now_iso if (nuevo_grado == "1º" and not lead.get("fecha_conexion")) else lead.get("fecha_conexion")

        with get_db(tenant_id=tenant_id) as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE leads
                SET nombre = %s, cargo_titular = %s, cargo_actual = %s, institucion_actual = %s, 
                    ubicacion = %s, grado_red = %s, estado = %s, fecha_conexion = %s, updated_at = %s
                WHERE id = %s AND tenant_id = %s;
            """, (nuevo_nombre, nuevo_titular, nuevo_cargo_act, nueva_inst, nueva_ubic, nuevo_grado, nuevo_estado, nueva_fecha_conn, now_iso, lead_id, tenant_id))

            cur.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (%s, 'LEAD_SINCRONIZADO_LINKEDIN', %s, %s);
            """, (lead_id, f"Perfil sincronizado en vivo desde LinkedIn: {nuevo_cargo_act} en {nueva_inst}", now_iso))

        return True, {"lead_id": lead_id, "cargo_actual": nuevo_cargo_act, "institucion": nueva_inst}, None

    return False, None, f"Tipo de tarea '{tipo}' delegado al despachador de secuencias o no implementado"

def process_queue_cycle() -> int:
    """Procesa una pasada de la cola central para todos los tenants activos."""
    try:
        import safety_engine
        in_work_hours, _ = safety_engine.check_business_hours()
        if not in_work_hours:
            return 0
    except Exception:
        pass

    processed = 0
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM tenants WHERE estado = 'ACTIVO';")
            tenants = [r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

        for t_id in tenants:
            task = get_next_task_for_worker(t_id)
            if task:
                success, result, err = execute_task_action(task)
                report_task_result(task["id"], t_id, success=success, resultado=result, error=err)
                processed += 1
    except Exception as e:
        logger.error(f"[QueueRunner] Error en ciclo de cola: {e}")

    return processed

_queue_runner_thread = None

def start_periodic_queue_runner():
    """Inicia el hilo permanente en segundo plano para procesar la cola central."""
    global _queue_runner_thread
    if _queue_runner_thread is not None and _queue_runner_thread.is_alive():
        return

    import threading
    import time

    def loop():
        time.sleep(5)
        while True:
            try:
                process_queue_cycle()
            except Exception as e:
                logger.error(f"[QueueRunner] Error en loop: {e}")
            time.sleep(12)

    _queue_runner_thread = threading.Thread(target=loop, daemon=True, name="NexusReach_CentralQueueRunner")
    _queue_runner_thread.start()
    logger.info("[QueueRunner] Hilo permanente de cola central en PostgreSQL activado.")
