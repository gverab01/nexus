import os
import json
import time
from datetime import datetime, date
from typing import Dict, Any, Optional
from database import get_db
import safety_engine
import sequence_engine

# ==============================================================================
# CENTRALIZED TASK DISPATCHER (Cloud Brain -> Local Runner)
# ==============================================================================

_autopilot_active = False

def get_autopilot_status() -> bool:
    """Returns whether the autopilot runner is enabled by the user."""
    global _autopilot_active
    return _autopilot_active

def set_autopilot_status(active: bool) -> bool:
    """Activates or pauses the autopilot runner."""
    global _autopilot_active
    _autopilot_active = bool(active)
    return _autopilot_active

def get_next_dispatched_task() -> Dict[str, Any]:
    """
    Evaluates active published sequences and server-side safety checks
    to yield the next atomic task for the desktop runner to execute.
    """
    global _autopilot_active
    now = datetime.now()

    # 1. Check if autopilot is turned on
    if not _autopilot_active:
        return {
            "hay_tarea": False,
            "motivo": "Piloto automático en pausa por el usuario.",
            "esperar_segundos": 10
        }

    # 1.5. Embedded Browser LinkedIn session evaluation
    import browser_service
    if browser_service.is_electron_running():
        electron_status = browser_service.get_electron_status()
        if not electron_status.get("sesion_linkedin_activa"):
            return {
                "hay_tarea": False,
                "motivo": "⚠️ Sesión de LinkedIn no iniciada en el navegador embebido. Por favor inicia sesión para comenzar a prospectar.",
                "esperar_segundos": 10,
                "requiere_login_linkedin": True
            }

    # 2. Server safety evaluation (Business hours)
    in_work_hours, hours_reason = safety_engine.check_business_hours()
    if not in_work_hours:
        return {
            "hay_tarea": False,
            "motivo": f"Seguridad: {hours_reason}",
            "esperar_segundos": 120
        }

    # 3. Server safety evaluation (Active kill-switch)
    safety_config = safety_engine.get_all_safety_config()
    if safety_config.get("kill_switch_activado") == "1":
        return {
            "hay_tarea": False,
            "motivo": f"Seguridad: Freno de emergencia (Kill-switch) activo: {safety_config.get('kill_switch_motivo', '')}",
            "esperar_segundos": 60
        }

    # 4. Find first active published sequence
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, estado 
            FROM secuencias 
            WHERE activa = 1 AND estado = 'PUBLICADA'
            LIMIT 1
        """)
        sec = cursor.fetchone()
        if not sec:
            return {
                "hay_tarea": False,
                "motivo": "No hay secuencias activas en estado PUBLICADA.",
                "esperar_segundos": 30
            }

        sequence_id = sec["id"]

        # 5. Find next eligible lead in sequence
        cursor.execute("""
            SELECT 
                ls.id as inscripcion_id,
                ls.lead_id,
                ls.paso_actual_id,
                ls.estado as estado_inscripcion,
                ls.proxima_ejecucion_at,
                l.nombre,
                l.perfil_url,
                l.institucion_actual,
                l.email,
                l.estado as lead_estado
            FROM leads_en_secuencia ls
            JOIN leads l ON l.id = ls.lead_id
            WHERE ls.secuencia_id = ? 
              AND ls.estado = 'EN_CURSO'
              AND (ls.proxima_ejecucion_at IS NULL OR ls.proxima_ejecucion_at <= ?)
            ORDER BY ls.created_at ASC
            LIMIT 1
        """, (sequence_id, now.isoformat()))
        candidate = cursor.fetchone()

        if not candidate:
            return {
                "hay_tarea": False,
                "motivo": "No hay prospectos listos para ejecutar en este momento (esperando pausas o cola vacía).",
                "esperar_segundos": 20
            }

        # 6. Identify step to execute
        step_id = candidate["paso_actual_id"]
        if not step_id:
            cursor.execute("""
                SELECT * FROM pasos_secuencia 
                WHERE secuencia_id = ? AND padre_paso_id IS NULL
                ORDER BY orden ASC LIMIT 1
            """, (sequence_id,))
            step = cursor.fetchone()
        else:
            cursor.execute("SELECT * FROM pasos_secuencia WHERE id = ?", (step_id,))
            step = cursor.fetchone()

        if not step:
            return {
                "hay_tarea": False,
                "motivo": "Paso de secuencia no encontrado en el árbol.",
                "esperar_segundos": 30
            }

        step_type = step["tipo_accion"] if "tipo_accion" in step.keys() else step.get("tipo", "")
        try:
            step_params = json.loads(step.get("parametros_json") or step.get("parametros") or "{}")
        except Exception:
            step_params = {}

        # 7. Validate daily quota according to action type
        if step_type == "ENVIAR_INVITACION":
            diag = safety_engine.check_linkedin_safety(conn)
            if not diag["autorizado"]:
                return {
                    "hay_tarea": False,
                    "motivo": f"Seguridad LinkedIn: {diag['motivo']}",
                    "esperar_segundos": 300
                }

        # 8. Resolve Spintax and variables on server-side
        resolved_note = ""
        if step_type == "ENVIAR_INVITACION":
            template = step_params.get("plantilla_nota") or step_params.get("nota") or ""
            if template:
                first_name = candidate["nombre"].split()[0] if candidate["nombre"] else "hola"
                company = candidate["institucion_actual"] or "su empresa"
                title = candidate.get("cargo_titular") or "su cargo"

                for var_name in ["{{nombre}}", "{nombre}"]:
                    template = template.replace(var_name, first_name)
                for var_company in ["{{empresa}}", "{empresa}", "{{institucion}}", "{institucion}", "{{colegio}}", "{colegio}"]:
                    template = template.replace(var_company, company)
                for var_title in ["{{cargo}}", "{cargo}"]:
                    template = template.replace(var_title, title)

                resolved_note = safety_engine.process_spintax(template)

        # 9. Calculate Gaussian stochastic delay
        pause_seconds = safety_engine.calculate_gaussian_delay(config=safety_config)

        task_id = f"task-{candidate['lead_id']}-{int(time.time())}"
        
        return {
            "hay_tarea": True,
            "tarea": {
                "id": task_id,
                "tipo": step_type,
                "lead_id": candidate["lead_id"],
                "nombre_prospecto": candidate["nombre"],
                "institucion": candidate["institucion_actual"],
                "perfil_url": candidate["perfil_url"],
                "secuencia_id": sequence_id,
                "paso_id": step["id"],
                "orden_paso": step["orden"],
                "nota": resolved_note,
                "pausa_sugerida_seg": pause_seconds,
                "fecha_despacho": now.isoformat()
            }
        }

def process_executed_task_report(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Receives task execution outcome from desktop runner, updates database,
    and advances candidate in sequence tree.
    """
    task_id = report_data.get("tarea_id")
    lead_id = report_data.get("lead_id")
    sequence_id = report_data.get("secuencia_id")
    step_id = report_data.get("paso_id")
    action_type = report_data.get("tipo")
    success = bool(report_data.get("exito"))
    error_msg = report_data.get("error", "")

    now_iso = datetime.now().isoformat()

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            if success:
                # 1. Insert activity log
                try:
                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, metadata_json, timestamp)
                        VALUES (?, ?, ?, '{}', ?)
                    """, (lead_id, f"RUNNER_{action_type}_COMPLETADO", f"Acción {action_type} ejecutada exitosamente por el runner local.", now_iso))
                except Exception as db_err:
                    print(f"[Dispatcher Warning] No se insertó historial para {lead_id}: {db_err}")

                # 2. Update lead status in main table
                if action_type == "VISITAR_PERFIL":
                    cursor.execute("""
                        UPDATE leads 
                        SET estado = 'PERFIL_VISITADO', updated_at = ?
                        WHERE id = ?
                    """, (now_iso, lead_id))
                elif action_type == "ENVIAR_INVITACION":
                    cursor.execute("""
                        UPDATE leads 
                        SET estado = 'INVITACION_ENVIADA', fecha_invitacion = ?, updated_at = ?
                        WHERE id = ?
                    """, (now_iso, now_iso, lead_id))

                # 3. Advance lead to next step
                cursor.execute("""
                    SELECT * FROM pasos_secuencia 
                    WHERE secuencia_id = ? AND padre_paso_id = ?
                    ORDER BY orden ASC LIMIT 1
                """, (sequence_id, step_id))
                next_step = cursor.fetchone()

                if next_step:
                    try:
                        p_sig = json.loads(next_step.get("parametros_json") or next_step.get("parametros") or "{}")
                        hours = float(p_sig.get("horas_espera") or p_sig.get("horas") or 24)
                    except Exception:
                        hours = 24.0

                    next_ts = datetime.fromtimestamp(time.time() + (hours * 3600)).isoformat()

                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (next_step["id"], next_ts, now_iso, lead_id, sequence_id))
                else:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET estado = 'FINALIZADA', proxima_ejecucion_at = NULL, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (now_iso, lead_id, sequence_id))

                return {
                    "status": "ok",
                    "tarea_id": task_id,
                    "mensaje": f"Paso {action_type} consolidado y prospecto actualizado.",
                    "siguiente_paso_id": next_step["id"] if next_step else None
                }
            else:
                try:
                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, metadata_json, timestamp)
                        VALUES (?, 'RUNNER_FALLO', ?, '{}', ?)
                    """, (lead_id, f"Fallo al ejecutar {action_type}: {error_msg}", now_iso))
                except Exception:
                    pass

                retry_ts = datetime.fromtimestamp(time.time() + 1800).isoformat()
                cursor.execute("""
                    UPDATE leads_en_secuencia
                    SET proxima_ejecucion_at = ?, updated_at = ?
                    WHERE lead_id = ? AND secuencia_id = ?
                """, (retry_ts, now_iso, lead_id, sequence_id))

                return {
                    "status": "error",
                    "tarea_id": task_id,
                    "mensaje": f"Fallo reportado: {error_msg}. Reintento programado en 30 minutos."
                }
    except Exception as general_err:
        print(f"[Dispatcher Error]: {general_err}")
        return {
            "status": "error",
            "tarea_id": task_id,
            "error": str(general_err)
        }

# ==========================================
# BACKWARD COMPATIBILITY ALIASES
# ==========================================
get_piloto_automatico_estado = get_autopilot_status
set_piloto_automatico_estado = set_autopilot_status
obtener_proxima_tarea_despachada = get_next_dispatched_task
procesar_reporte_tarea_ejecutada = process_executed_task_report
