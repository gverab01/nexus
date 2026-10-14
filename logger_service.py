import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from database import get_db

# Configuración básica del logger de consola estándar de Python
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s")
logger = logging.getLogger("NexusReach")

def log_event(
    level: str,
    module: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    lead_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Registra un suceso en la base de datos y lo emite en la consola estándar.
    Niveles permitidos: 'INFO', 'SUCCESS', 'WARNING', 'ERROR'
    Módulos sugeridos: 'EXTRACTOR', 'SEQUENCES', 'BROWSER', 'SAFETY', 'ENRICHMENT', 'LISTS', 'SYSTEM'
    """
    now = datetime.now()
    timestamp_iso = now.isoformat()
    details_str = json.dumps(details or {})
    level_normalized = level.upper()
    module_normalized = module.upper()

    # Emitir en logging estándar de consola
    log_msg = f"[{module_normalized}] {message}"
    if level_normalized == "ERROR":
        logger.error(log_msg)
    elif level_normalized == "WARNING":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Persistir en SQLite
    log_record = {
        "timestamp": timestamp_iso,
        "level": level_normalized,
        "module": module_normalized,
        "message": message,
        "details_json": details_str,
        "details": details or {},
        "lead_id": lead_id,
        "created_at": timestamp_iso
    }

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO system_logs (timestamp, level, module, message, details_json, lead_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timestamp_iso, level_normalized, module_normalized, message, details_str, lead_id, timestamp_iso))
            log_record["id"] = cursor.lastrowid
    except Exception as e:
        logger.error(f"Error persistiendo suceso en system_logs: {e}")

    return log_record

def get_logs(
    limit: int = 150,
    module: Optional[str] = None,
    level: Optional[str] = None,
    search: Optional[str] = None,
    since_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Recupera los logs más recientes con filtros opcionales de módulo, nivel y búsqueda.
    """
    query = "SELECT * FROM system_logs WHERE 1=1"
    params: List[Any] = []

    if module and module != "ALL":
        query += " AND module = ?"
        params.append(module.upper())

    if level and level != "ALL":
        query += " AND level = ?"
        params.append(level.upper())

    if search:
        query += " AND (message LIKE ? OR module LIKE ?)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    if since_id is not None:
        query += " AND id > ?"
        params.append(since_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    logs: List[Dict[str, Any]] = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        for r in rows:
            details_dict = {}
            try:
                details_dict = json.loads(r.get("details_json") or "{}")
            except Exception:
                pass
            r["details"] = details_dict
            logs.append(r)

    return logs

def get_log_stats() -> Dict[str, Any]:
    """
    Calcula métricas agregadas sobre los sucesos registrados y detecta actividad en tiempo real.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM system_logs")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) as errors FROM system_logs WHERE level = 'ERROR'")
        errors = cursor.fetchone()["errors"]

        cursor.execute("SELECT COUNT(*) as warnings FROM system_logs WHERE level = 'WARNING'")
        warnings = cursor.fetchone()["warnings"]

        cursor.execute("SELECT COUNT(*) as successes FROM system_logs WHERE level = 'SUCCESS'")
        successes = cursor.fetchone()["successes"]

        cursor.execute("SELECT timestamp FROM system_logs ORDER BY id DESC LIMIT 1")
        last_row = cursor.fetchone()
        last_timestamp = last_row["timestamp"] if last_row else None

        # Detectar si el extractor está operando activamente en los últimos 45 segundos
        cursor.execute("""
            SELECT timestamp, message, level 
            FROM system_logs 
            WHERE module = 'EXTRACTOR' 
            ORDER BY id DESC LIMIT 1
        """)
        last_extractor_row = cursor.fetchone()
        
        is_extracting_now = False
        last_extractor_activity = None
        if last_extractor_row:
            last_extractor_activity = last_extractor_row["timestamp"]
            try:
                # Comprobar diferencia de tiempo
                ts = datetime.fromisoformat(last_extractor_row["timestamp"])
                diff_seconds = (datetime.now() - ts).total_seconds()
                # Si el último evento fue hace menos de 45 segundos y no fue de finalización ni error
                msg_lower = last_extractor_row["message"].lower()
                is_finished = "finalizada" in msg_lower or "detenida" in msg_lower or last_extractor_row["level"] in ("ERROR", "WARNING")
                if diff_seconds < 45 and not is_finished:
                    is_extracting_now = True
            except Exception:
                pass

    return {
        "total": total,
        "total_logs": total,
        "errors": errors,
        "warnings": warnings,
        "successes": successes,
        "level_counts": {
            "SUCCESS": successes,
            "INFO": total - (errors + warnings + successes),
            "WARNING": warnings,
            "ERROR": errors,
        },
        "is_extracting_now": is_extracting_now,
        "last_extractor_activity": last_extractor_activity,
        "last_timestamp": last_timestamp
    }

def clear_logs() -> bool:
    """
    Elimina los logs del sistema para reiniciar la consola.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM system_logs")
    log_event("INFO", "SYSTEM", "Consola de logs reiniciada por el usuario.")
    return True

# ==========================================
# ALIASES FOR BACKWARD COMPATIBILITY
# ==========================================
registrar_evento = log_event
obtener_logs = get_logs
obtener_estadisticas_logs = get_log_stats
limpiar_logs = clear_logs

