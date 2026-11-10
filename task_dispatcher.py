import os
import json
import time
import random
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional
import database
from database import get_db
import safety_engine
import sequence_engine
import command_signing_service
import zoho_bridge_service

# ==============================================================================
# CENTRALIZED TASK DISPATCHER (Cloud Brain -> Local Runner)
# ==============================================================================

def get_autopilot_status(tenant_id: Optional[str] = None) -> bool:
    """Retorna True si existe al menos una secuencia publicada y activa en ejecución."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            if tenant_id:
                cursor.execute(
                    "SELECT COUNT(*) as total FROM secuencias WHERE activa = 1 AND estado = 'PUBLICADA' AND tenant_id = ?",
                    (tenant_id,)
                )
            else:
                cursor.execute("SELECT COUNT(*) as total FROM secuencias WHERE activa = 1 AND estado = 'PUBLICADA'")
            row = cursor.fetchone()
            return bool(row and row["total"] > 0)
    except Exception:
        return False

def set_autopilot_status(active: bool) -> bool:
    """Función auxiliar para compatibilidad."""
    return get_autopilot_status()

def get_next_dispatched_task(tenant_id: Optional[str] = None, sequence_id: Optional[str] = None, device_id: Optional[str] = None) -> Dict[str, Any]:
    """Evalúa las secuencias activas publicadas y los controles de seguridad para despachar la siguiente tarea atómica al runner de escritorio."""
    now = datetime.now()

    target_tenant = (tenant_id or "").strip()
    if not target_tenant:
        return {
            "hay_tarea": False,
            "error": "TENANT_REQUIRED",
            "motivo": "Seguridad: Se requiere un tenant_id autenticado y explícito para despachar tareas.",
            "esperar_segundos": 60
        }

    # Establecer contexto de tenant para el aislamiento y compatibilidad con PostgreSQL RLS
    database.set_current_tenant_context(tenant_id=target_tenant)

    # 0. Validación de dispositivo si se envía device_id (Workstream 5.1)
    if device_id:
        is_active, dev_reason, _ = command_signing_service.is_device_active(device_id, target_tenant)
        if not is_active:
            return {
                "hay_tarea": False,
                "error": "UNAUTHORIZED_DEVICE",
                "motivo": f"⚠️ Dispositivo no autorizado ({dev_reason}). Acceso revocado o no emparejado.",
                "esperar_segundos": 60,
                "dispositivo_revocado": True
            }

    # 0.5. Validación de pertenencia de secuencia y suscripción activa del tenant
    with get_db() as conn:
        cursor = conn.cursor()
        if sequence_id:
            cursor.execute("SELECT id, tenant_id FROM secuencias WHERE id = ?", (sequence_id,))
            seq_row = cursor.fetchone()
            if not seq_row:
                return {
                    "hay_tarea": False,
                    "error": "SEQUENCE_NOT_FOUND",
                    "motivo": "Secuencia no encontrada.",
                    "esperar_segundos": 60
                }
            if seq_row["tenant_id"] != target_tenant:
                return {
                    "hay_tarea": False,
                    "error": "FORBIDDEN_SEQUENCE_TENANT",
                    "motivo": "Seguridad: La secuencia solicitada no pertenece al tenant autorizado.",
                    "esperar_segundos": 60
                }

        import entitlements_service
        sub_active, sub_msg = entitlements_service.is_tenant_subscription_active(target_tenant, conn=conn)
        if not sub_active:
            return {
                "hay_tarea": False,
                "motivo": f"Comercial: {sub_msg}",
                "codigo": "TENANT_SUBSCRIPTION_INACTIVE",
                "esperar_segundos": 180
            }

    # 1. Check if there are published active sequences for this tenant
    if not get_autopilot_status(tenant_id=target_tenant):
        return {
            "hay_tarea": False,
            "motivo": "Sin secuencias publicadas en marcha (motor en reposo).",
            "esperar_segundos": 15
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

    # 3.5. Promover automáticamente esperas estratégicas expiradas acotadas al tenant
    try:
        sequence_engine.promote_expired_delays(sequence_id=sequence_id, tenant_id=target_tenant)
    except Exception:
        pass

    # 4. Encontrar prospectos elegibles listos a través de secuencias activas publicadas del tenant autorizado
    with get_db() as conn:
        cursor = conn.cursor()

        # Resolver dispositivo activo del tenant antes de reservar tareas
        resolved_device_id = device_id
        if not resolved_device_id:
            cursor.execute(
                "SELECT id FROM devices WHERE tenant_id = ? AND status = 'ACTIVE' ORDER BY last_seen_at DESC LIMIT 1",
                (target_tenant,)
            )
            dev_row = cursor.fetchone()
            if dev_row:
                resolved_device_id = dev_row["id"] if isinstance(dev_row, dict) else dev_row[0]
            else:
                return {
                    "hay_tarea": False,
                    "error": "NO_ACTIVE_DEVICE",
                    "motivo": "⚠️ No hay dispositivos activos registrados para este tenant.",
                    "esperar_segundos": 60,
                    "dispositivo_revocado": True
                }

        where_clauses = [
            "s.activa = 1",
            "s.estado = 'PUBLICADA'",
            "s.tenant_id = ?",
            "l.tenant_id = ?",
            "ls.estado = 'EN_CURSO'",
            "(ls.proxima_ejecucion_at IS NULL OR ls.proxima_ejecucion_at <= ?)"
        ]
        params = [target_tenant, target_tenant, now.isoformat()]

        if sequence_id:
            where_clauses.append("s.id = ?")
            params.append(sequence_id)

        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"""
            SELECT 
                ls.id as inscripcion_id,
                ls.lead_id,
                ls.secuencia_id,
                ls.paso_actual_id,
                ls.estado as estado_inscripcion,
                ls.proxima_ejecucion_at,
                s.nombre as secuencia_nombre,
                s.tenant_id,
                l.nombre,
                l.cargo_actual,
                l.cargo_titular,
                l.perfil_url,
                l.institucion_actual,
                l.email,
                l.telefono,
                l.estado as lead_estado,
                p.tipo_accion as paso_tipo_accion
            FROM leads_en_secuencia ls
            JOIN secuencias s ON s.id = ls.secuencia_id
            JOIN leads l ON l.id = ls.lead_id
            LEFT JOIN pasos_secuencia p ON ls.paso_actual_id = p.id
            WHERE {where_sql}
            ORDER BY ls.proxima_ejecucion_at ASC
            LIMIT 100
        """, params)
        raw_candidates = cursor.fetchall()

        if not raw_candidates:
            return {
                "hay_tarea": False,
                "motivo": "No hay prospectos listos para ejecutar en este momento (esperando pausas o cola vacía).",
                "esperar_segundos": 20
            }

        # 4.5. Intercalación estocástica y rotación inteligente de acciones (Visita <-> Invitación <-> Mensaje)
        cursor.execute("""
            SELECT action FROM commands 
            WHERE tenant_id = ? AND status IN ('COMPLETED', 'REPORTED', 'EXECUTED', 'DISPATCHED')
            ORDER BY created_at DESC LIMIT 1
        """, (target_tenant,))
        last_cmd_row = cursor.fetchone()
        last_action = last_cmd_row["action"] if last_cmd_row else None

        last_cat = "VISITA" if last_action in ("LI_VISIT_PROFILE", "VISITAR_PERFIL") else (
            "INVITACION" if last_action in ("LI_SEND_INVITE", "ENVIAR_INVITACION") else (
                "MENSAJE" if last_action in ("LI_SEND_MESSAGE", "ENVIAR_MENSAJE_LINKEDIN", "WA_SEND_MESSAGE", "ENVIAR_WHATSAPP_WEB") else None
            )
        )

        def get_cand_cat(c):
            t = (c.get("paso_tipo_accion") or "").upper()
            if "VISIT" in t: return "VISITA"
            if "INVIT" in t: return "INVITACION"
            if "MENSAJE" in t or "WHATSAPP" in t: return "MENSAJE"
            return "OTRO"

        if last_cat:
            alternate_cands = [c for c in raw_candidates if get_cand_cat(c) != last_cat]
            same_cands = [c for c in raw_candidates if get_cand_cat(c) == last_cat]
            candidates = (alternate_cands + same_cands) if alternate_cands else raw_candidates
        else:
            candidates = raw_candidates

        candidate = None
        step = None
        step_type = ""
        blocked_reasons = {}

        # 5. Iteración inteligente para evitar Head-of-Line Blocking si una acción específica agotó cupo
        for cand in candidates:
            c_seq_id = cand["secuencia_id"]
            c_step_id = cand["paso_actual_id"]

            if not c_step_id:
                cursor.execute("""
                    SELECT * FROM pasos_secuencia 
                    WHERE secuencia_id = ? AND padre_paso_id IS NULL
                    ORDER BY orden ASC LIMIT 1
                """, (c_seq_id,))
                c_step = cursor.fetchone()
            else:
                cursor.execute("SELECT * FROM pasos_secuencia WHERE id = ? AND secuencia_id = ?", (c_step_id, c_seq_id))
                c_step = cursor.fetchone()

            if not c_step:
                continue

            # 5.0. Deduplicación interna DB-first y lista de supresión (Workstream 5.2)
            c_tenant = target_tenant
            has_col, col_msg, _ = zoho_bridge_service.check_internal_collision(
                tenant_id=c_tenant,
                profile_url=cand.get("perfil_url") or "",
                email=cand.get("email"),
                current_lead_id=cand["lead_id"]
            )
            if has_col:
                now_iso = now.isoformat()
                cursor.execute("""
                    UPDATE leads_en_secuencia 
                    SET estado = 'SUPRIMIDO', proxima_ejecucion_at = NULL, updated_at = ?
                    WHERE lead_id = ? AND secuencia_id = ?
                """, (now_iso, cand["lead_id"], c_seq_id))
                zoho_bridge_service.log_lead_activity(
                    tenant_id=c_tenant,
                    lead_id=cand["lead_id"],
                    action_type="COLLISION_OR_SUPPRESSION_BLOCKED",
                    details={"motivo": col_msg, "secuencia_id": c_seq_id}
                )
                conn.commit()
                continue

            c_step_type = c_step["tipo_accion"] if "tipo_accion" in c_step.keys() else c_step.get("tipo", "")

            # Promoción inmediata si quedó algún retraso de espera
            if c_step_type == "ESPERAR":
                next_step_id, next_date_iso, is_sequence_end = sequence_engine._calculate_next_step(
                    sequence_id=c_seq_id,
                    current_step_id=c_step["id"],
                    bifurcation=None,
                    now=now
                )
                now_iso = now.isoformat()
                if is_sequence_end or not next_step_id:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET estado = 'COMPLETADO', proxima_ejecucion_at = NULL, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (now_iso, cand["lead_id"], c_seq_id))
                else:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (next_step_id, next_date_iso, now_iso, cand["lead_id"], c_seq_id))
                conn.commit()
                continue

            # Ejecución en segundo plano de extracción y resolución de correo
            if c_step_type in ("EXTRAER_CORREO", "RESOLVER_CORREO"):
                import email_resolver_service
                email_resolver_service.resolve_lead_email(cand["lead_id"])
                next_step_id, next_date_iso, is_sequence_end = sequence_engine._calculate_next_step(
                    sequence_id=c_seq_id,
                    current_step_id=c_step["id"],
                    bifurcation=None,
                    now=now
                )
                now_iso = now.isoformat()
                if is_sequence_end or not next_step_id:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET estado = 'COMPLETADO', proxima_ejecucion_at = NULL, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (now_iso, cand["lead_id"], c_seq_id))
                else:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (next_step_id, next_date_iso, now_iso, cand["lead_id"], c_seq_id))
                conn.commit()
                continue

            # Ejecución en segundo plano de cruce contra Zoho CRM
            if c_step_type in ("CRUZAR_ZOHO_CRM", "SINCRONIZAR_ZOHO"):
                import zoho_browser_service
                zoho_browser_service.sync_lead_with_zoho(cand["lead_id"], conn=conn)
                next_step_id, next_date_iso, is_sequence_end = sequence_engine._calculate_next_step(
                    sequence_id=c_seq_id,
                    current_step_id=c_step["id"],
                    bifurcation=None,
                    now=now
                )
                now_iso = now.isoformat()
                if is_sequence_end or not next_step_id:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET estado = 'COMPLETADO', proxima_ejecucion_at = NULL, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (now_iso, cand["lead_id"], c_seq_id))
                else:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (next_step_id, next_date_iso, now_iso, cand["lead_id"], c_seq_id))
                conn.commit()
                continue

            # 6. Validación de cuotas antiban específicas por canal
            if c_step_type in ("ENVIAR_INVITACION", "VISITAR_PERFIL", "ENVIAR_MENSAJE_LINKEDIN"):
                # Resolver cuenta de LinkedIn activa para este tenant
                cursor.execute("""
                    SELECT id, status FROM linkedin_accounts 
                    WHERE tenant_id = ? AND status IN ('ACTIVE', 'WARMUP', 'CHECKPOINT', 'RESTRICTED', 'PAUSED')
                    ORDER BY created_at ASC LIMIT 1
                """, (c_tenant,))
                acc_row = cursor.fetchone()
                if acc_row:
                    acc_id = acc_row["id"] if isinstance(acc_row, dict) else acc_row[0]
                else:
                    acc_id = f"li_acc_{c_tenant}"
                    now_iso_acc = now.isoformat()
                    try:
                        cursor.execute("""
                            INSERT OR IGNORE INTO linkedin_accounts 
                            (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, created_at, updated_at)
                            VALUES (?, ?, ?, 'WARMUP', 1, 15, ?, ?)
                        """, (acc_id, c_tenant, f"Cuenta LinkedIn ({c_tenant})", now_iso_acc, now_iso_acc))
                        conn.commit()
                    except Exception:
                        pass

                cand["resolved_account_id"] = acc_id

                # Evaluación por el Safety Engine del servidor
                action_name = "LI_SEND_INVITE" if c_step_type == "ENVIAR_INVITACION" else ("LI_VISIT_PROFILE" if c_step_type == "VISITAR_PERFIL" else "LI_SEND_MESSAGE")
                
                # Evaluación de resiliencia de interfaz (Workstream 5.8)
                import selector_service
                action_paused, pause_reason = selector_service.is_action_paused(action_name, conn=conn)
                if action_paused:
                    blocked_reasons[c_step_type] = f"Interfaz pausada preventivamente: {pause_reason}"
                    continue

                auth_res = safety_engine.authorize_linkedin_action(acc_id, c_tenant, action=action_name, conn=conn)
                if not auth_res["autorizado"]:
                    blocked_reasons[c_step_type] = f"Seguridad LinkedIn: {auth_res['motivo']}"
                    continue

                # Evaluación de cuota comercial completamente desacoplada (5.5.7)
                comm_res = safety_engine.check_commercial_quota(c_tenant, action=action_name, conn=conn)
                if not comm_res["aprobado"]:
                    blocked_reasons[c_step_type] = f"Cuota Comercial: {comm_res.get('motivo', 'Límite comercial alcanzado')}"
                    continue

            if c_step_type == "ENVIAR_WHATSAPP_WEB":
                import selector_service
                wa_paused, wa_reason = selector_service.is_action_paused("WA_SEND_BUTTON", conn=conn)
                if wa_paused:
                    blocked_reasons["ENVIAR_WHATSAPP_WEB"] = f"Interfaz pausada preventivamente: {wa_reason}"
                    continue

                import whatsapp_safety_engine
                diag_wa = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(
                    tenant_id=c_tenant,
                    lead_data=cand,
                    conn=conn
                )
                if not diag_wa["autorizado"]:
                    blocked_reasons["ENVIAR_WHATSAPP_WEB"] = f"Seguridad WhatsApp: {diag_wa['motivo']}"
                    continue

            # 7. Evaluación de activación comercial por ciclo (Workstream 5.9)
            import entitlements_service
            lead_ent = entitlements_service.check_lead_activation_entitlement(c_tenant, cand["lead_id"], conn=conn)
            if not lead_ent["aprobado"]:
                blocked_reasons[c_step_type] = f"Cuota Comercial: {lead_ent['motivo']}"
                continue

            # 7.5. Reserva atómica (lease de 120s) para evitar despacho duplicado a múltiples workers
            lease_expires_at = (datetime.now() + timedelta(seconds=120)).isoformat()
            claim_now_iso = datetime.now().isoformat()
            cursor.execute("""
                UPDATE leads_en_secuencia
                SET paso_actual_id = ?,
                    proxima_ejecucion_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND estado = 'EN_CURSO'
                  AND (proxima_ejecucion_at IS NULL OR proxima_ejecucion_at <= ?)
            """, (c_step["id"], lease_expires_at, claim_now_iso, cand["inscripcion_id"], now.isoformat()))
            if cursor.rowcount != 1:
                conn.commit()
                continue
            conn.commit()

            # ¡Candidato autorizado y reservado atómicamente!
            candidate = cand
            step = c_step
            step_type = c_step_type
            sequence_id = c_seq_id
            break

        if not candidate:
            if blocked_reasons:
                motivo = " | ".join(blocked_reasons.values())
                return {
                    "hay_tarea": False,
                    "motivo": f"Prospectos en cola en espera de cupo de seguridad: {motivo}",
                    "esperar_segundos": 180
                }
            return {
                "hay_tarea": False,
                "motivo": "No hay prospectos listos para ejecutar en este momento (esperando pausas o cola vacía).",
                "esperar_segundos": 20
            }

        try:
            step_params = json.loads(step.get("parametros_json") or step.get("parametros") or "{}")
        except Exception:
            step_params = {}

        # 8. Resolver Spintax y variables dinámicas
        resolved_note = ""
        template = (
            step_params.get("plantilla_nota") or 
            step_params.get("nota") or 
            step_params.get("mensaje") or 
            step_params.get("plantilla") or ""
        )
        if template:
            first_name = candidate["nombre"].split()[0] if candidate["nombre"] else "hola"
            company = candidate["institucion_actual"] or "su empresa"
            title = candidate.get("cargo_actual") or candidate.get("cargo_titular") or "su cargo"

            for var_name in ["{{nombre}}", "{nombre}"]:
                template = template.replace(var_name, first_name)
            for var_company in ["{{empresa}}", "{empresa}", "{{institucion}}", "{institucion}", "{{colegio}}", "{colegio}"]:
                template = template.replace(var_company, company)
            for var_title in ["{{cargo}}", "{cargo}"]:
                template = template.replace(var_title, title)

            resolved_note = safety_engine.process_spintax(template)

        # 9. Calcular pausa estocástica según canal
        if step_type == "ENVIAR_WHATSAPP_WEB":
            import whatsapp_safety_engine
            pause_seconds = whatsapp_safety_engine.calculate_whatsapp_delay(config=safety_config)
        else:
            acc_id_for_delay = candidate.get("resolved_account_id") or f"li_acc_{target_tenant}"
            pause_seconds = safety_engine.calculate_per_account_delay(account_id=acc_id_for_delay)

        # 10. Mapeo a la lista cerrada de acciones tipadas (Workstream 5.1)
        ACTION_MAP = {
            "VISITAR_PERFIL": "LI_VISIT_PROFILE",
            "ENVIAR_INVITACION": "LI_SEND_INVITE",
            "ENVIAR_MENSAJE_LINKEDIN": "LI_SEND_MESSAGE",
            "ENVIAR_WHATSAPP_WEB": "WA_SEND_MESSAGE",
            "CRUZAR_ZOHO_CRM": "ZOHO_FIND_LEAD",
            "SINCRONIZAR_ZOHO": "ZOHO_FIND_LEAD"
        }
        closed_action = ACTION_MAP.get(step_type, step_type)

        # 11. Construir comando firmado con Ed25519 vinculado a tenant, device, lead, secuencia y paso
        cmd_params = {
            "lead_id": candidate["lead_id"],
            "secuencia_id": sequence_id,
            "paso_id": step["id"],
            "profile_url": candidate["perfil_url"],
            "perfil_url": candidate["perfil_url"],
            "note": resolved_note,
            "nota": resolved_note,
            "message": resolved_note,
            "mensaje": resolved_note,
            "phone_e164": candidate.get("telefono"),
            "email": candidate.get("email"),
            "name": candidate["nombre"],
            "is_warm": candidate.get("lead_estado") in ("CONECTADO", "1º", "1er", "1°", "1st")
        }

        try:
            signed_command = command_signing_service.create_signed_command(
                tenant_id=target_tenant,
                device_id=resolved_device_id,
                action=closed_action,
                params=cmd_params,
                ttl_seconds=120
            )
            task_id = signed_command["command_id"]
        except Exception as sign_err:
            # Revertir la reserva atómica si no se pudo emitir el comando firmado
            try:
                cursor.execute(
                    "UPDATE leads_en_secuencia SET proxima_ejecucion_at = ? WHERE id = ?",
                    (now.isoformat(), candidate["inscripcion_id"])
                )
                conn.commit()
            except Exception:
                pass
            return {
                "hay_tarea": False,
                "error": "COMMAND_SIGNING_FAILED",
                "motivo": f"Seguridad: No se pudo firmar el comando de despacho ({sign_err}).",
                "esperar_segundos": 60
            }

        return {
            "hay_tarea": True,
            "comando": signed_command,
            "tarea": {
                "id": task_id,
                "command_id": task_id,
                "tenant_id": target_tenant,
                "device_id": resolved_device_id,
                "tipo": step_type,
                "action": closed_action,
                "lead_id": candidate["lead_id"],
                "nombre_prospecto": candidate["nombre"],
                "institucion": candidate["institucion_actual"],
                "perfil_url": candidate["perfil_url"],
                "telefono": candidate.get("telefono"),
                "email": candidate.get("email"),
                "secuencia_id": sequence_id,
                "paso_id": step["id"],
                "orden_paso": step["orden"],
                "nota": resolved_note,
                "mensaje": resolved_note,
                "pausa_sugerida_seg": pause_seconds,
                "fecha_despacho": now.isoformat()
            }
        }

def process_executed_task_report(
    report_data: Dict[str, Any],
    authenticated_tenant_id: Optional[str] = None,
    permitted_tenants: Optional[list] = None
) -> Dict[str, Any]:
    """Recibe el resultado de la ejecución desde el runner de escritorio, verifica la firma del dispositivo y la asignación del comando antes de aplicar cualquier mutación."""
    if not isinstance(report_data, dict):
        return {
            "ok": False,
            "status": "error",
            "http_status": 400,
            "error": "INVALID_REPORT_PAYLOAD"
        }

    task_id = (report_data.get("command_id") or report_data.get("tarea_id") or "").strip()
    lead_id = (report_data.get("lead_id") or "").strip()
    sequence_id = (report_data.get("secuencia_id") or "").strip()
    step_id = report_data.get("paso_id")
    action_type = report_data.get("action") or report_data.get("tipo")
    success = bool(report_data.get("exito") if "exito" in report_data else report_data.get("success", False))
    error_msg = report_data.get("error", "")
    device_id = (report_data.get("device_id") or "").strip()
    device_sig = (report_data.get("device_signature") or "").strip()
    reported_tenant = (report_data.get("tenant_id") or "").strip()
    result_data = report_data.get("result", {})

    if not task_id or not device_id or not device_sig:
        return {
            "ok": False,
            "status": "error",
            "http_status": 401,
            "tarea_id": task_id,
            "error": "MISSING_WORKER_CREDENTIALS_OR_SIGNATURE"
        }

    if not lead_id or not sequence_id:
        return {
            "ok": False,
            "status": "error",
            "http_status": 400,
            "tarea_id": task_id,
            "error": "MISSING_TASK_BINDING_FIELDS"
        }

    # 1. Validar que el comando exista y coincida con el tenant, dispositivo, lead, secuencia y estado antes de mutar nada
    effective_tenant = authenticated_tenant_id or reported_tenant
    if effective_tenant:
        database.set_current_tenant_context(tenant_id=effective_tenant)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, tenant_id, device_id, action, params_json, status FROM commands WHERE id = ?",
            (task_id,)
        )
        cmd_row = cursor.fetchone()
        if not cmd_row:
            return {
                "ok": False,
                "status": "error",
                "http_status": 404,
                "tarea_id": task_id,
                "error": "COMMAND_NOT_FOUND"
            }

        cmd_tenant = cmd_row["tenant_id"]
        cmd_device = cmd_row["device_id"]
        cmd_status = cmd_row["status"]
        cmd_action = cmd_row["action"]
        try:
            cmd_params = json.loads(cmd_row["params_json"] or "{}")
        except Exception:
            cmd_params = {}

        if authenticated_tenant_id and authenticated_tenant_id != cmd_tenant:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "CROSS_TENANT_COMMAND_REPORT_FORBIDDEN"
            }

        if permitted_tenants is not None and cmd_tenant not in permitted_tenants:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "CROSS_TENANT_COMMAND_REPORT_FORBIDDEN"
            }

        if reported_tenant and reported_tenant != cmd_tenant:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "REPORT_TENANT_MISMATCH"
            }

        if device_id != cmd_device:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "COMMAND_DEVICE_MISMATCH"
            }

        if cmd_status not in ("DISPATCHED", "ISSUED"):
            return {
                "ok": False,
                "status": "error",
                "http_status": 409,
                "tarea_id": task_id,
                "error": f"COMMAND_ALREADY_PROCESSED ({cmd_status})"
            }

        bound_lead_id = cmd_params.get("lead_id")
        if bound_lead_id and str(bound_lead_id) != str(lead_id):
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "COMMAND_LEAD_MISMATCH"
            }

        bound_seq_id = cmd_params.get("secuencia_id")
        if bound_seq_id and str(bound_seq_id) != str(sequence_id):
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "COMMAND_SEQUENCE_MISMATCH"
            }

        bound_step_id = cmd_params.get("paso_id")
        if bound_step_id is not None and step_id is not None and str(bound_step_id) != str(step_id):
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "COMMAND_STEP_MISMATCH"
            }

        effective_step_id = step_id if step_id is not None else bound_step_id

        # Verificar que el lead pertenezca al mismo tenant del comando
        cursor.execute("SELECT id, tenant_id FROM leads WHERE id = ?", (lead_id,))
        lead_row = cursor.fetchone()
        if not lead_row:
            return {
                "ok": False,
                "status": "error",
                "http_status": 404,
                "tarea_id": task_id,
                "error": "LEAD_NOT_FOUND"
            }
        if lead_row["tenant_id"] != cmd_tenant:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "CROSS_TENANT_LEAD_FORBIDDEN"
            }

        # Verificar que la secuencia pertenezca al mismo tenant del comando
        cursor.execute("SELECT id, tenant_id FROM secuencias WHERE id = ?", (sequence_id,))
        seq_row = cursor.fetchone()
        if not seq_row:
            return {
                "ok": False,
                "status": "error",
                "http_status": 404,
                "tarea_id": task_id,
                "error": "SEQUENCE_NOT_FOUND"
            }
        if seq_row["tenant_id"] != cmd_tenant:
            return {
                "ok": False,
                "status": "error",
                "http_status": 403,
                "tarea_id": task_id,
                "error": "CROSS_TENANT_SEQUENCE_FORBIDDEN"
            }

        # Verificar que la inscripción en secuencia exista y esté EN_CURSO
        cursor.execute(
            "SELECT id, estado, paso_actual_id FROM leads_en_secuencia WHERE lead_id = ? AND secuencia_id = ?",
            (lead_id, sequence_id)
        )
        enr_row = cursor.fetchone()
        if not enr_row:
            return {
                "ok": False,
                "status": "error",
                "http_status": 404,
                "tarea_id": task_id,
                "error": "ENROLLMENT_NOT_FOUND"
            }
        if enr_row["estado"] != "EN_CURSO":
            return {
                "ok": False,
                "status": "error",
                "http_status": 409,
                "tarea_id": task_id,
                "error": f"INCOMPATIBLE_ENROLLMENT_STATE ({enr_row['estado']})"
            }
        if effective_step_id is not None and enr_row["paso_actual_id"] is not None and str(enr_row["paso_actual_id"]) != str(effective_step_id):
            return {
                "ok": False,
                "status": "error",
                "http_status": 409,
                "tarea_id": task_id,
                "error": "ENROLLMENT_STEP_MISMATCH"
            }

    # 2. Verificar criptográficamente la firma Ed25519 del dispositivo y consolidar el comando de forma atómica
    reg_res = command_signing_service.record_command_result(
        command_id=task_id,
        device_id=device_id,
        tenant_id=cmd_tenant,
        action=action_type or cmd_action or "LI_ACTION",
        success=success,
        result_data=result_data,
        error_message=error_msg,
        device_signature=device_sig
    )
    if not reg_res.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "http_status": reg_res.get("http_status", 403),
            "tarea_id": task_id,
            "error": reg_res.get("error", "INVALID_COMMAND_RESULT")
        }

    now_iso = datetime.now().isoformat()
    rep_tenant = cmd_tenant

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            if lead_id:
                try:
                    zoho_bridge_service.log_lead_activity(
                        tenant_id=rep_tenant,
                        lead_id=lead_id,
                        action_type=f"RUNNER_{action_type}",
                        details={"command_id": task_id, "success": success, "result": result_data, "error": error_msg},
                        actor_id=device_id
                    )
                except Exception as log_err:
                    print(f"[Dispatcher Warning] Error registrando bitácora lead_activity: {log_err}")

            if success:
                # Sincronización desacoplada si vino resultado de Zoho
                if action_type in ("ZOHO_FIND_LEAD", "CRUZAR_ZOHO_CRM", "SINCRONIZAR_ZOHO") and lead_id:
                    crm_id = result_data.get("id") or result_data.get("crm_external_id")
                    owner = result_data.get("owner")
                    found = result_data.get("found", True)
                    sync_status = "SYNCED" if found else "NOT_FOUND"
                    zoho_bridge_service.sync_zoho_result_to_lead(
                        tenant_id=rep_tenant,
                        lead_id=lead_id,
                        crm_external_id=crm_id,
                        crm_sync_status=sync_status,
                        owner_name=owner
                    )

                # 1. Insert activity log retrocompatible
                try:
                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, metadata_json, timestamp)
                        VALUES (?, ?, ?, '{}', ?)
                    """, (lead_id, f"RUNNER_{action_type}_COMPLETADO", f"Acción {action_type} ejecutada exitosamente por el runner local.", now_iso))
                except Exception as db_err:
                    print(f"[Dispatcher Warning] No se insertó historial para {lead_id}: {db_err}")

                # 2. Update lead status in main table acotado al tenant del comando
                if action_type in ("VISITAR_PERFIL", "LI_VISIT_PROFILE"):
                    lead_updates = ["estado = 'PERFIL_VISITADO'", "updated_at = ?"]
                    update_params = [now_iso]

                    # Email descubierto en la visita
                    extracted_email = result_data.get("email")
                    if extracted_email and isinstance(extracted_email, str) and "@" in extracted_email:
                        lead_updates.append("email = COALESCE(NULLIF(email, ''), ?)")
                        update_params.append(extracted_email.strip())

                    # Teléfono descubierto en la visita
                    extracted_phone = result_data.get("phone") or result_data.get("telefono")
                    if extracted_phone and isinstance(extracted_phone, str) and len(extracted_phone.strip()) > 4:
                        lead_updates.append("telefono = COALESCE(NULLIF(telefono, ''), ?)")
                        update_params.append(extracted_phone.strip())

                    # Titular / Grado
                    if result_data.get("cargo_titular"):
                        lead_updates.append("cargo_titular = COALESCE(NULLIF(cargo_titular, ''), ?)")
                        update_params.append(result_data["cargo_titular"])
                    if result_data.get("grado_red"):
                        lead_updates.append("grado_red = ?")
                        update_params.append(result_data["grado_red"])
                        if result_data["grado_red"] == "1º":
                            lead_updates.append("fecha_conexion = COALESCE(fecha_conexion, ?)")
                            update_params.append(now_iso)

                    update_params.extend([lead_id, rep_tenant])
                    cursor.execute(f"""
                        UPDATE leads 
                        SET {", ".join(lead_updates)}
                        WHERE id = ? AND tenant_id = ?
                    """, update_params)

                    # Ingesta al Radar de Prospectos Afines ("Personas que también vieron")
                    similar_profiles = result_data.get("similar_profiles") or []
                    if similar_profiles and isinstance(similar_profiles, list):
                        try:
                            import extractor_engine, lists_engine
                            radar_list_id = lists_engine.get_or_create_radar_list(tenant_id=rep_tenant)
                            visited_lead_name = lead_row.get("nombre") if isinstance(lead_row, dict) else ""
                            visited_inst = lead_row.get("institucion_actual") if isinstance(lead_row, dict) else ""
                            visited_ubic = lead_row.get("ubicacion") if isinstance(lead_row, dict) else "Chile"

                            for sim in similar_profiles:
                                sim_url = sim.get("perfil_url")
                                sim_nom = sim.get("nombre")
                                sim_tit = sim.get("cargo_titular") or ""
                                if not sim_url or not sim_nom:
                                    continue
                                clean_sim_url = sim_url.split("?")[0].rstrip("/") + "/"

                                cursor.execute("SELECT id FROM leads WHERE tenant_id = ? AND (perfil_url LIKE ? OR perfil_url = ?)", (rep_tenant, f"{clean_sim_url}%", sim_url))
                                if cursor.fetchone():
                                    continue

                                sim_id = f"lead-radar-{int(time.time())}-{random.randint(1000, 9999)}"
                                sim_cargo, sim_inst = extractor_engine.parse_cargo_and_institucion(sim_tit, default_institucion=visited_inst, location=visited_ubic)

                                cursor.execute("""
                                    INSERT INTO leads (
                                        id, nombre, cargo_titular, cargo_actual, institucion_actual,
                                        ubicacion, grado_red, perfil_url, estado, tags, notas,
                                        tenant_id, created_at, updated_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, '2º', ?, 'EXTRAIDO', ?, ?, ?, ?, ?)
                                """, (
                                    sim_id, sim_nom, sim_tit, sim_cargo or "Profesional", sim_inst or visited_inst,
                                    visited_ubic or "Chile", sim_url,
                                    json.dumps(["RADAR_VISITA"]),
                                    f"Descubierto automáticamente por radar de visitas en el perfil de {visited_lead_name}." if visited_lead_name else "Descubierto automáticamente por radar de visitas.",
                                    rep_tenant, now_iso, now_iso
                                ))

                                cursor.execute("""
                                    INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
                                    VALUES (?, ?, ?, ?)
                                """, (f"ll-{radar_list_id}-{sim_id}", radar_list_id, sim_id, now_iso))
                        except Exception as radar_err:
                            print(f"[Dispatcher Radar Warning] Error procesando perfiles afines: {radar_err}")
                elif action_type in ("ENVIAR_INVITACION", "LI_SEND_INVITE"):
                    cursor.execute("""
                        UPDATE leads 
                        SET estado = 'INVITACION_ENVIADA', fecha_invitacion = ?, updated_at = ?
                        WHERE id = ? AND tenant_id = ?
                    """, (now_iso, now_iso, lead_id, rep_tenant))
                    try:
                        cursor.execute("""
                            UPDATE linkedin_accounts 
                            SET invites_sent_today = COALESCE(invites_sent_today, 0) + 1, updated_at = ?
                            WHERE tenant_id = ?
                        """, (now_iso, rep_tenant))
                    except Exception as li_err:
                        print(f"[Dispatcher Warning] Error actualizando invites_sent_today: {li_err}")

                # 3. Advance lead to next step
                next_step_id, next_date_iso, is_sequence_end = sequence_engine._calculate_next_step(
                    sequence_id=sequence_id,
                    current_step_id=effective_step_id,
                    bifurcation=None,
                    now=datetime.now()
                )

                if is_sequence_end or not next_step_id:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET estado = 'COMPLETADO', proxima_ejecucion_at = NULL, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (now_iso, lead_id, sequence_id))
                else:
                    cursor.execute("""
                        UPDATE leads_en_secuencia
                        SET paso_actual_id = ?, proxima_ejecucion_at = ?, updated_at = ?
                        WHERE lead_id = ? AND secuencia_id = ?
                    """, (next_step_id, next_date_iso, now_iso, lead_id, sequence_id))

                return {
                    "ok": True,
                    "status": "ok",
                    "tarea_id": task_id,
                    "mensaje": f"Paso {action_type} consolidado y prospecto actualizado.",
                    "siguiente_paso_id": next_step_id
                }
            else:
                try:
                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, metadata_json, timestamp)
                        VALUES (?, 'RUNNER_FALLO', ?, '{}', ?)
                    """, (lead_id, f"Fallo al ejecutar {action_type}: {error_msg}", now_iso))
                except Exception:
                    pass

                # Detección de señales de riesgo antiban (5.5)
                err_lower = (error_msg or "").lower()
                risk_keywords = ["checkpoint", "captcha", "pin", "restricted", "restricci", "suspended", "suspensión", "unusual activity", "limit reached"]
                matched_signal = None
                for kw in risk_keywords:
                    if kw in err_lower:
                        matched_signal = kw.upper()
                        break
                if matched_signal:
                    try:
                        cursor.execute("SELECT id FROM linkedin_accounts WHERE tenant_id = ? LIMIT 1", (rep_tenant,))
                        ac_r = cursor.fetchone()
                        ac_id = (ac_r["id"] if isinstance(ac_r, dict) else ac_r[0]) if ac_r else f"li_acc_{rep_tenant}"
                        safety_engine.report_risk_signal(
                            account_id=ac_id,
                            tenant_id=rep_tenant,
                            signal_type=matched_signal,
                            details={"error": error_msg, "task_id": task_id, "action": action_type},
                            conn=conn
                        )
                    except Exception as sig_err:
                        print(f"[Dispatcher Warning] Error reportando señal de riesgo: {sig_err}")

                retry_ts = datetime.fromtimestamp(time.time() + 1800).isoformat()
                cursor.execute("""
                    UPDATE leads_en_secuencia
                    SET proxima_ejecucion_at = ?, updated_at = ?
                    WHERE lead_id = ? AND secuencia_id = ?
                """, (retry_ts, now_iso, lead_id, sequence_id))

                return {
                    "ok": True,
                    "status": "error",
                    "tarea_id": task_id,
                    "mensaje": f"Fallo reportado: {error_msg}. Reintento programado en 30 minutos."
                }
    except Exception as general_err:
        print(f"[Dispatcher Error]: {general_err}")
        return {
            "ok": False,
            "status": "error",
            "http_status": 500,
            "tarea_id": task_id,
            "error": str(general_err)
        }



