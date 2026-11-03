"""
Servicio de Observabilidad, Telemetría y Diagnóstico de Soporte (Workstream 5.10)
NexusReach Pro - Directrices v1.3

Funciones:
1. Métricas agregadas por cuenta y globales:
   - Acciones ejecutadas (total y por tipo).
   - Tasa de éxito por acción.
   - Tasa de aceptación de invitaciones (conexiones aceptadas vs invitaciones enviadas).
   - Latencia de comandos (tiempo de respuesta del cliente).
   - Incidentes de seguridad (checkpoints, captchas, restricciones).
2. Tablero interno con alertas:
   - Picos de incidentes.
   - Tasa de fallos anómala por acción (> 15%).
   - Alertas de canarios caídos o acciones pausadas por interfaz.
3. Paquete de diagnóstico de soporte para el usuario (Support Bundle):
   - Exportable por el usuario ante problemas técnicos.
   - ESTRICTAMENTE SANITIZADO: Cero credenciales, tokens, contraseñas ni contenido de chats.
"""

import json
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple

from database import get_db
import selector_service
import entitlements_service


CURRENT_SERVER_VERSION = "1.3.0"
MIN_CLIENT_VERSION = "1.0.0"


def check_client_version_support(client_version: Optional[str]) -> Tuple[bool, str]:
    """
    Comprueba si la versión del cliente Electron cumple con la política de versión mínima (5.11).
    Si client_version < MIN_CLIENT_VERSION, rechaza con CLIENT_VERSION_DEPRECATED.
    """
    if not client_version:
        return False, "Versión de cliente no especificada."

    try:
        def _parse(v):
            clean = re.sub(r'[^0-9\.]', '', str(v)).split('.')
            return tuple(int(x) for x in clean if x)

        c_tuple = _parse(client_version)
        min_tuple = _parse(MIN_CLIENT_VERSION)

        if c_tuple < min_tuple:
            return False, f"Versión de cliente {client_version} obsoleta. Versión mínima requerida: {MIN_CLIENT_VERSION}. Por favor descargue la última actualización."
        return True, f"Versión {client_version} soportada."
    except Exception:
        return True, "Versión aceptada por fallback."


def sanitize_diagnostics_without_pii(text_or_obj: Any) -> Any:
    """
    Sanitiza datos para diagnóstico de soporte sin filtrar información confidencial (Directriz 5.10 y 6.8).
    Elimina tokens de sesión, contraseñas, claves privadas y textos de mensajes privados.
    """
    if isinstance(text_or_obj, dict):
        sanitized = {}
        forbidden_substrings = ("password", "token", "secret", "private_key", "cookie", "auth", "contenido", "message_text")
        for k, v in text_or_obj.items():
            k_lower = k.lower()
            if any(sub in k_lower for sub in forbidden_substrings):
                sanitized[k] = "[REDACTED_CONFIDENTIAL]"
            elif k_lower in ("email", "telefono", "phone", "nombre"):
                sanitized[k] = "[REDACTED_PII]"
            else:
                sanitized[k] = sanitize_diagnostics_without_pii(v)
        return sanitized
    elif isinstance(text_or_obj, list):
        return [sanitize_diagnostics_without_pii(item) for item in text_or_obj]
    elif isinstance(text_or_obj, str):
        # Ocultar posibles tokens base64 o JWT largos
        if len(text_or_obj) > 64 and ("ey" in text_or_obj or "bearer" in text_or_obj.lower()):
            return "[REDACTED_TOKEN]"
        return text_or_obj
    return text_or_obj


def get_telemetry_metrics(
    tenant_id: Optional[str] = None,
    account_id: Optional[str] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Calcula métricas operativas por cuenta y agregadas globales:
    - Volumen de comandos por acción y tasa de éxito.
    - Tasa de aceptación de invitaciones de LinkedIn.
    - Latencia promedio de ejecución de comandos.
    - Incidentes de seguridad y salud de cuentas.
    """
    def _query(c):
        cursor = c.cursor()

        # 1. Acciones ejecutadas y tasa de éxito (desde commands y command_results)
        cmd_where = ["1=1"]
        cmd_params = []
        if tenant_id:
            cmd_where.append("c.tenant_id = ?")
            cmd_params.append(tenant_id)

        where_sql = " AND ".join(cmd_where)

        cursor.execute(f"""
            SELECT 
                c.action,
                COUNT(c.id) as total_commands,
                SUM(CASE WHEN c.status = 'COMPLETED' THEN 1 ELSE 0 END) as successful_commands,
                SUM(CASE WHEN c.status = 'FAILED' THEN 1 ELSE 0 END) as failed_commands
            FROM commands c
            WHERE {where_sql}
            GROUP BY c.action
        """, cmd_params)

        action_breakdown = {}
        total_cmds = 0
        total_success = 0
        total_failed = 0

        for row in cursor.fetchall():
            r = dict(row)
            act = r["action"]
            tot = r["total_commands"]
            succ = r["successful_commands"]
            fail = r["failed_commands"]
            rate = (succ / tot * 100.0) if tot > 0 else 0.0

            action_breakdown[act] = {
                "total": tot,
                "successful": succ,
                "failed": fail,
                "success_rate_pct": round(rate, 1)
            }
            total_cmds += tot
            total_success += succ
            total_failed += fail

        global_success_rate = (total_success / total_cmds * 100.0) if total_cmds > 0 else 100.0

        # 2. Tasa de aceptación de invitaciones de LinkedIn
        # Invitaciones enviadas vs conexiones en estado 'CONECTADO'
        inv_where = ["l.estado IN ('CONECTADO', 'INVITACION_ENVIADA', 'EN_SECUENCIA', 'MENSAJE_ENVIADO')"]
        inv_params = []
        if tenant_id:
            inv_where.append("l.tenant_id = ?")
            inv_params.append(tenant_id)

        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_outreach,
                SUM(CASE WHEN l.estado = 'CONECTADO' OR l.grado_red = '1º' THEN 1 ELSE 0 END) as total_connected,
                SUM(CASE WHEN l.estado = 'INVITACION_ENVIADA' THEN 1 ELSE 0 END) as pending_invites
            FROM leads l
            WHERE {" AND ".join(inv_where)}
        """, inv_params)

        inv_row = cursor.fetchone()
        tot_outreach = (inv_row["total_outreach"] if inv_row else 0) or 0
        tot_connected = (inv_row["total_connected"] if inv_row else 0) or 0
        acceptance_rate = (tot_connected / tot_outreach * 100.0) if tot_outreach > 0 else 0.0

        # 3. Latencia promedio de ejecución de comandos (en segundos)
        cursor.execute(f"""
            SELECT 
                c.created_at,
                r.reported_at
            FROM commands c
            JOIN command_results r ON c.id = r.command_id
            WHERE {where_sql} AND c.status = 'COMPLETED'
            ORDER BY c.created_at DESC LIMIT 100
        """, cmd_params)

        latencies = []
        for row in cursor.fetchall():
            try:
                r = dict(row)
                t_start = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                t_end = datetime.fromisoformat(r["reported_at"].replace("Z", "+00:00"))
                lat_sec = (t_end - t_start).total_seconds()
                if 0 <= lat_sec <= 300:
                    latencies.append(lat_sec)
            except Exception:
                pass

        avg_latency_sec = (sum(latencies) / len(latencies)) if latencies else 0.0

        # 4. Incidentes recientes (últimas 24 horas)
        now_utc = datetime.now(timezone.utc)
        since_24h = (now_utc - timedelta(hours=24)).isoformat()

        cursor.execute("""
            SELECT COUNT(*) as incident_count
            FROM system_logs
            WHERE level IN ('WARNING', 'ERROR', 'CRITICAL')
              AND message LIKE '%CHECKPOINT%' OR message LIKE '%CAPTCHA%' OR message LIKE '%RESTRICTED%' OR message LIKE '%KILL-SWITCH%'
              AND timestamp >= ?
        """, (since_24h,))
        inc_row = cursor.fetchone()
        recent_incidents = (inc_row["incident_count"] if inc_row else 0) or 0

        # 5. Versiones de cliente conectadas
        cursor.execute("""
            SELECT client_version, COUNT(*) as device_count
            FROM devices
            WHERE status = 'PAIRED'
            GROUP BY client_version
        """)
        client_versions = {dict(r)["client_version"] or "unknown": dict(r)["device_count"] for r in cursor.fetchall()}

        return {
            "tenant_id": tenant_id or "global",
            "account_id": account_id or "all",
            "commands": {
                "total": total_cmds,
                "successful": total_success,
                "failed": total_failed,
                "global_success_rate_pct": round(global_success_rate, 1),
                "by_action": action_breakdown
            },
            "linkedin_funnel": {
                "total_outreach": tot_outreach,
                "connections_accepted": tot_connected,
                "acceptance_rate_pct": round(acceptance_rate, 1)
            },
            "latency": {
                "average_execution_seconds": round(avg_latency_sec, 2),
                "samples_measured": len(latencies)
            },
            "incidents_last_24h": recent_incidents,
            "connected_client_versions": client_versions,
            "timestamp": now_utc.isoformat()
        }

    if conn is not None:
        return _query(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _query(c)


def get_team_internal_dashboard_alerts(conn=None) -> Dict[str, Any]:
    """
    Genera alertas proactivas para el equipo de operaciones:
    1. Cuentas con incidentes de seguridad o bajo health score (< 70).
    2. Acciones con tasa de fallo superior al 15%.
    3. Acciones pausadas preventivamente por rotura de interfaz.
    """
    def _alerts(c):
        cursor = c.cursor()
        alerts = []

        # 1. Acciones pausadas por rotura de interfaz
        actions_status = selector_service.get_all_actions_status(conn=c)
        for act in actions_status:
            if act.get("status") == "PAUSED":
                alerts.append({
                    "severity": "CRITICAL",
                    "module": "INTERFACE_SELECTOR",
                    "action": act.get("action"),
                    "title": f"Acción pausada por degradación segura: {act.get('action')}",
                    "details": act.get("pause_reason"),
                    "consecutive_failures": act.get("consecutive_failures", 0)
                })

        # 2. Cuentas con salud degradada
        cursor.execute("""
            SELECT id, tenant_id, account_name, health_score, status 
            FROM linkedin_accounts 
            WHERE health_score < 70.0 OR status IN ('CHECKPOINT', 'RESTRICTED')
        """)
        for row in cursor.fetchall():
            r = dict(row)
            alerts.append({
                "severity": "WARNING" if r.get("health_score", 100) >= 50 else "CRITICAL",
                "module": "ACCOUNT_HEALTH",
                "account_id": r.get("id"),
                "tenant_id": r.get("tenant_id"),
                "title": f"Cuenta LinkedIn en riesgo: {r.get('account_name', r.get('id'))}",
                "health_score": r.get("health_score"),
                "status": r.get("status")
            })

        # 3. Tasa de fallo anómala por acción en comandos
        telemetry = get_telemetry_metrics(conn=c)
        for act_name, data in telemetry["commands"]["by_action"].items():
            tot = data["total"]
            fail = data["failed"]
            fail_rate = (fail / tot * 100.0) if tot >= 5 else 0.0
            if fail_rate > 15.0:
                alerts.append({
                    "severity": "WARNING",
                    "module": "ACTION_FAILURE_SPIKE",
                    "action": act_name,
                    "title": f"Pico de fallos en acción {act_name} ({round(fail_rate, 1)}%)",
                    "total_attempts": tot,
                    "failures": fail
                })

        return {
            "ok": True,
            "total_alerts": len(alerts),
            "critical_count": sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
            "warning_count": sum(1 for a in alerts if a.get("severity") == "WARNING"),
            "alerts": alerts,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    if conn is not None:
        return _alerts(conn)
    else:
        with get_db() as c:
            return _alerts(c)


def generate_support_diagnostics_bundle(
    tenant_id: str,
    account_id: Optional[str] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Genera un paquete integral de diagnóstico de soporte exportable por el usuario.
    Regla estricta de privacidad: CERO datos personales, credenciales ni contenidos de mensajes.
    """
    now_utc = datetime.now(timezone.utc)

    def _bundle(c):
        cursor = c.cursor()

        # 1. Información del entorno y versiones
        cursor.execute("SELECT client_version, device_name, status, last_seen_at FROM devices WHERE tenant_id = ? ORDER BY last_seen_at DESC LIMIT 5", (tenant_id,))
        devices_info = [dict(r) for r in cursor.fetchall()]

        # 2. Resumen comercial y de ciclo
        cycle_summary = entitlements_service.get_cycle_usage_summary(tenant_id, conn=c)

        # 3. Salud de cuentas vinculadas
        cursor.execute("""
            SELECT id, tenant_id, status, warmup_day, daily_invite_limit, health_score, updated_at
            FROM linkedin_accounts
            WHERE tenant_id = ?
        """, (tenant_id,))
        accounts = [dict(r) for r in cursor.fetchall()]

        # 4. Estado de selectores y degradación
        actions_status = selector_service.get_all_actions_status(conn=c)

        # 5. Últimos 50 logs sanitizados
        cursor.execute("""
            SELECT id, timestamp, level, module, message, details_json
            FROM system_logs
            WHERE tenant_id = ? OR tenant_id IS NULL
            ORDER BY timestamp DESC LIMIT 50
        """, (tenant_id,))
        raw_logs = []
        for row in cursor.fetchall():
            r = dict(row)
            try:
                det = json.loads(r.get("details_json") or "{}")
            except Exception:
                det = {}
            raw_logs.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "level": r["level"],
                "module": r["module"],
                "message": r["message"],
                "details": det
            })

        sanitized_logs = sanitize_diagnostics_without_pii(raw_logs)

        # 6. Telemetría de comandos del tenant
        telemetry = get_telemetry_metrics(tenant_id=tenant_id, account_id=account_id, conn=c)

        bundle = {
            "bundle_id": f"diag_{uuid.uuid4().hex[:12]}",
            "generated_at": now_utc.isoformat(),
            "server_version": CURRENT_SERVER_VERSION,
            "min_client_version_required": MIN_CLIENT_VERSION,
            "tenant_id": tenant_id,
            "subscription_and_entitlements": cycle_summary,
            "linked_devices": devices_info,
            "accounts_health": accounts,
            "actions_health_status": actions_status,
            "telemetry": telemetry,
            "sanitized_system_logs": sanitized_logs
        }

        return bundle

    if conn is not None:
        return _bundle(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _bundle(c)
