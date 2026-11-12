import os
import json
import time
import random
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
import database
from database import get_db
import sequence_engine

# ==============================================================================
# LEAD LIST MANAGEMENT AND DYNAMIC AUDIENCES ENGINE (NexusReach Pro)
# ==============================================================================

_active_extractions = set()
_extraction_threads = {}

def is_list_extracting(list_id: str) -> bool:
    """Indica si un proceso de extracción en segundo plano se encuentra activo para la lista especificada."""
    return list_id in _active_extractions

def get_lead_lists(tenant_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Retorna todas las listas de prospectos con estadísticas agregadas, conteos y secuencias vinculadas filtradas por tenant."""
    with get_db() as conn:
        cursor = conn.cursor()
        where_filter = ""
        params = []
        if tenant_ids:
            placeholders = ", ".join(["?"] * len(tenant_ids))
            where_filter = f"WHERE l.tenant_id IN ({placeholders})"
            params.extend(tenant_ids)

        cursor.execute(f"""
            SELECT l.*,
                (SELECT COUNT(*) FROM leads_en_lista WHERE lista_id = l.id) as total_leads,
                (SELECT COUNT(*) FROM leads_en_lista ll JOIN leads ld ON ll.lead_id = ld.id WHERE ll.lista_id = l.id AND ld.estado = 'EXTRAIDO') as leads_en_cola,
                (SELECT COUNT(*) FROM leads_en_lista ll JOIN leads ld ON ll.lead_id = ld.id WHERE ll.lista_id = l.id AND ld.estado IN ('INVITACION_ENVIADA', 'INVITACION_PENDIENTE', 'CONECTADO')) as leads_contactados,
                (SELECT COUNT(*) FROM leads_en_lista ll JOIN leads ld ON ll.lead_id = ld.id WHERE ll.lista_id = l.id AND ld.estado = 'CONECTADO') as leads_conectados
            FROM listas_leads l
            {where_filter}
            ORDER BY l.created_at DESC
        """, params)
        lists = cursor.fetchall()

        list_ids = [item["id"] for item in lists]
        seqs_map = {item["id"]: [] for item in lists}
        if list_ids:
            ph = ", ".join(["?"] * len(list_ids))
            cursor.execute(f"""
                SELECT sl.lista_id, s.id, s.nombre, s.activa, s.estado, sl.auto_ingresar_nuevos
                FROM secuencia_listas sl
                JOIN secuencias s ON sl.secuencia_id = s.id
                WHERE sl.lista_id IN ({ph})
            """, list_ids)
            for row in cursor.fetchall():
                seqs_map[row["lista_id"]].append(dict(row))

        for item in lists:
            item["secuencias_conectadas"] = seqs_map.get(item["id"], [])
            item["extrayendo_activo"] = is_list_extracting(item["id"])
            if item.get("estado") == "EXTRAYENDO" and not item["extrayendo_activo"]:
                item["estado"] = "ACTIVA"

        return lists

def get_lead_list_detail(list_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene la información detallada de una lista y sus prospectos inscritos."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listas_leads WHERE id = ?", (list_id,))
        lead_list = cursor.fetchone()
        if not lead_list:
            return None

        list_tenant = lead_list.get("tenant_id") or "ten_superadmin"
        cursor.execute("""
            SELECT s.id, s.nombre, s.activa, s.estado, sl.auto_ingresar_nuevos
            FROM secuencia_listas sl
            JOIN secuencias s ON sl.secuencia_id = s.id
            WHERE sl.lista_id = ? AND s.tenant_id = ?
        """, (list_id, list_tenant))
        lead_list["secuencias_conectadas"] = cursor.fetchall()

        cursor.execute("""
            SELECT ld.*, ll.created_at as fecha_ingreso_lista
            FROM leads_en_lista ll
            JOIN leads ld ON ll.lead_id = ld.id
            WHERE ll.lista_id = ?
            ORDER BY ll.created_at DESC
        """, (list_id,))
        lead_list["leads"] = cursor.fetchall()
        lead_list["total_leads"] = len(lead_list["leads"])

        # Count how many leads have verified extracted data
        extracted_count = sum(
            1 for l in lead_list["leads"] 
            if (l.get("cargo_actual") and l.get("cargo_actual").strip() not in ("", "No determinado") and 
                l.get("institucion_actual") and l.get("institucion_actual").strip() not in ("", "Empresa u Organización"))
        )
        lead_list["leads_extraidos"] = extracted_count

        extrayendo_activo = is_list_extracting(list_id)
        # If all leads are extracted, ensure background extraction is discarded
        if extracted_count >= lead_list["total_leads"] and extrayendo_activo:
            _active_extractions.discard(list_id)
            extrayendo_activo = False

        lead_list["extrayendo_activo"] = extrayendo_activo

        # Normalize state: lists should be ACTIVA or DETENIDA, never stuck in EXTRAYENDO
        if lead_list.get("estado") == "EXTRAYENDO" and not extrayendo_activo:
            lead_list["estado"] = "ACTIVA"
            cursor.execute("UPDATE listas_leads SET estado = 'ACTIVA' WHERE id = ?", (list_id,))

        return lead_list

def create_lead_list(name: str, description: str = "", search_term: str = "", status: str = "ACTIVA", auto_connect_sequence: bool = False, tenant_id: str = "ten_superadmin", **kwargs) -> Dict[str, Any]:
    """Crea una nueva lista de prospectos vinculada a su tenant y opcionalmente a la secuencia activa."""
    now_iso = datetime.now().isoformat()
    list_id = f"lista-{int(time.time())}"
    final_status = "DETENIDA" if status == "DETENIDA" else "ACTIVA"
    
    # Compatibilidad con argumento histórico auto_conectar_secuencia
    connect_seq = auto_connect_sequence or kwargs.get("auto_conectar_secuencia", False)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listas_leads (id, nombre, descripcion, termino_busqueda, estado, tenant_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (list_id, name, description, search_term, final_status, tenant_id, now_iso, now_iso))

        if connect_seq and tenant_id:
            cursor.execute("""
                SELECT id FROM secuencias 
                WHERE tenant_id = ? AND (activa = 1 OR estado = 'PUBLICADA') 
                ORDER BY es_default DESC, created_at DESC LIMIT 1
            """, (tenant_id,))
            sec_row = cursor.fetchone()
            if sec_row:
                sec_id = sec_row["id"]
                cursor.execute("""
                    INSERT INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
                    VALUES (?, ?, ?, 1, 1, ?)
                    ON CONFLICT(secuencia_id, lista_id) DO UPDATE SET activa = 1, auto_ingresar_nuevos = 1
                """, (f"sl-{sec_id}-{list_id}", sec_id, list_id, now_iso))

    return get_lead_list_detail(list_id)

def get_or_create_radar_list(tenant_id: str = "ten_superadmin") -> str:
    """Retorna el ID de la lista especial '🎯 Radar: Descubiertos por Visita' para el tenant, creándola si no existe."""
    list_name = "🎯 Radar: Descubiertos por Visita"
    with database.tenant_context_scope(tenant_id=tenant_id, is_super_admin=True):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM listas_leads WHERE nombre = ? AND tenant_id = ? LIMIT 1", (list_name, tenant_id))
            row = cursor.fetchone()
            if row:
                return row["id"]
            
            now_iso = datetime.now().isoformat()
            list_id = f"lista-radar-{int(time.time())}"
            cursor.execute("""
                INSERT INTO listas_leads (id, nombre, descripcion, termino_busqueda, estado, tenant_id, created_at, updated_at)
                VALUES (?, ?, ?, 'RADAR_VISITAS', 'ACTIVA', ?, ?, ?)
            """, (
                list_id, 
                list_name, 
                "Prospectos afines detectados automáticamente durante visitas de inspección a perfiles de LinkedIn.",
                tenant_id, 
                now_iso, 
                now_iso
            ))
            return list_id

def update_lead_list(list_id: str, name: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None, search_term: Optional[str] = None) -> bool:
    """Actualiza los metadatos o el estado de una lista de prospectos."""
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
        if status is not None:
            norm_status = "DETENIDA" if status == "DETENIDA" else "ACTIVA"
            fields.append("estado = ?")
            values.append(norm_status)
        if search_term is not None:
            fields.append("termino_busqueda = ?")
            values.append(search_term)

        if not fields:
            return False

        fields.append("updated_at = ?")
        values.append(now_iso)
        values.append(list_id)

        cursor.execute(f"UPDATE listas_leads SET {', '.join(fields)} WHERE id = ?", values)

    return True

def delete_lead_list(list_id: str) -> bool:
    """Elimina una lista de prospectos y sus asociaciones en cascada."""
    stop_list_extraction(list_id)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads_en_lista WHERE lista_id = ?", (list_id,))
        cursor.execute("DELETE FROM secuencia_listas WHERE lista_id = ?", (list_id,))
        cursor.execute("DELETE FROM listas_leads WHERE id = ?", (list_id,))
        return True

def add_leads_to_list(list_id: str, lead_ids: List[str]) -> Dict[str, Any]:
    """Agrega prospectos a una lista e inscribe en secuencias vinculadas solo a aquellos con datos extraídos y verificados."""
    now_iso = datetime.now().isoformat()
    added = 0
    with get_db() as conn:
        cursor = conn.cursor()
        for lid in lead_ids:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
                    VALUES (?, ?, ?, ?)
                """, (f"ll-{list_id}-{lid}", list_id, lid, now_iso))
                added += 1
            except Exception:
                pass

        cursor.execute("""
            SELECT sl.secuencia_id, s.estado, s.activa 
            FROM secuencia_listas sl
            JOIN secuencias s ON sl.secuencia_id = s.id
            WHERE sl.lista_id = ? AND sl.auto_ingresar_nuevos = 1 AND (s.estado = 'PUBLICADA' OR s.activa = 1)
        """, (list_id,))
        active_sequences = cursor.fetchall()

        ready_lead_ids = []
        if lead_ids:
            placeholders = ", ".join(["?"] * len(lead_ids))
            cursor.execute(f"""
                SELECT id FROM leads 
                WHERE id IN ({placeholders}) 
                  AND cargo_actual IS NOT NULL 
                  AND cargo_actual != '' 
                  AND cargo_actual != 'No determinado'
            """, lead_ids)
            ready_lead_ids = [r["id"] for r in cursor.fetchall()]

    auto_enrolled = 0
    if ready_lead_ids:
        for sec in active_sequences:
            res = sequence_engine.assign_leads_to_sequence(sec["secuencia_id"], ready_lead_ids)
            if res.get("status") == "ok":
                auto_enrolled += res.get("asignados", 0)

    return {
        "status": "ok",
        "lista_id": list_id,
        "leads_agregados": added,
        "auto_ingresados_en_secuencias": auto_enrolled
    }

def connect_list_to_sequence(sequence_id: str, list_id: str, auto_enroll_existing: bool = True) -> Dict[str, Any]:
    """Vincula una lista a una secuencia e inscribe opcionalmente los prospectos verificados existentes."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tenant_id FROM secuencias WHERE id = ?", (sequence_id,))
        sec = cursor.fetchone()
        cursor.execute("SELECT tenant_id FROM listas_leads WHERE id = ?", (list_id,))
        lst = cursor.fetchone()
        if sec and lst and sec.get("tenant_id") and lst.get("tenant_id") and sec["tenant_id"] != lst["tenant_id"]:
            raise ValueError(f"No se puede vincular una lista ({lst['tenant_id']}) a una secuencia de otra cuenta ({sec['tenant_id']})")

        cursor.execute("""
            INSERT INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
            VALUES (?, ?, ?, 1, 1, ?)
            ON CONFLICT(secuencia_id, lista_id) DO UPDATE SET activa = 1, auto_ingresar_nuevos = 1
        """, (f"sl-{sequence_id}-{list_id}", sequence_id, list_id, now_iso))

        # Enforce that only leads with verified data are enrolled
        cursor.execute("""
            SELECT ld.id 
            FROM leads_en_lista ll
            JOIN leads ld ON ll.lead_id = ld.id
            WHERE ll.lista_id = ? 
              AND ld.cargo_actual IS NOT NULL 
              AND ld.cargo_actual != '' 
              AND ld.cargo_actual != 'No determinado'
        """, (list_id,))
        ready_leads = [r["id"] for r in cursor.fetchall()]

    enrolled = 0
    if auto_enroll_existing and ready_leads:
        res = sequence_engine.assign_leads_to_sequence(sequence_id, ready_leads)
        enrolled = res.get("asignados", 0)

    return {
        "status": "ok",
        "secuencia_id": sequence_id,
        "lista_id": list_id,
        "leads_inscritos": enrolled
    }

def disconnect_list_from_sequence(sequence_id: str, list_id: str) -> bool:
    """Desvincula una lista de prospectos de una secuencia."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM secuencia_listas 
            WHERE secuencia_id = ? AND lista_id = ?
        """, (sequence_id, list_id))
        return True

def remove_lead_from_list(list_id: str, lead_id: str) -> bool:
    """Remueve un prospecto de una lista específica."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads_en_lista WHERE lista_id = ? AND lead_id = ?", (list_id, lead_id))
        return True

# ==============================================================================
# ON-DEMAND LEAD EXTRACTION WORKER (ANTIBAN ENGINE)
# ==============================================================================

def start_list_extraction(list_id: str) -> Dict[str, Any]:
    """Inicia la extracción de prospectos para una lista en segundo plano con pausas estocásticas antiban o inscribe de inmediato si ya están enriquecidos."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ld.id, ld.nombre, ld.perfil_url, ld.cargo_actual, ld.cargo_titular, ld.institucion_actual, ld.ubicacion
            FROM leads_en_lista ll
            JOIN leads ld ON ll.lead_id = ld.id
            WHERE ll.lista_id = ?
            ORDER BY ll.created_at ASC
        """, (list_id,))
        leads = cursor.fetchall()

    leads_to_process = []
    for l in leads:
        c_act = (l.get("cargo_actual") or "").strip()
        inst = (l.get("institucion_actual") or "").strip()
        # Missing if cargo_actual or company is empty or default placeholder
        if not c_act or c_act == "No determinado" or not inst or inst == "Empresa u Organización":
            leads_to_process.append(l)

    # If all leads already have extracted data:
    if not leads_to_process:
        _active_extractions.discard(list_id)
        # Auto-enroll ready leads into connected sequences
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE listas_leads SET estado = 'ACTIVA' WHERE id = ?", (list_id,))
            cursor.execute("""
                SELECT sl.secuencia_id 
                FROM secuencia_listas sl
                JOIN secuencias s ON sl.secuencia_id = s.id
                WHERE sl.lista_id = ? AND sl.activa = 1 AND (s.estado = 'PUBLICADA' OR s.activa = 1)
            """, (list_id,))
            connected_seqs = cursor.fetchall()
            all_lead_ids = [l["id"] for l in leads]

        enrolled = 0
        for seq in connected_seqs:
            res = sequence_engine.assign_leads_to_sequence(seq["secuencia_id"], all_lead_ids)
            if res.get("status") == "ok":
                enrolled += res.get("asignados", 0)

        return {
            "status": "ok",
            "lista_id": list_id,
            "extrayendo": False,
            "completado": True,
            "total": len(leads),
            "leads_extraidos": len(leads),
            "pendientes": 0,
            "mensaje": f"Todos los {len(leads)} prospectos ya tienen sus datos extraídos y verificados."
        }

    if list_id in _active_extractions:
        return {"status": "ok", "lista_id": list_id, "extrayendo": True, "mensaje": "Extracción ya en ejecución"}

    _active_extractions.add(list_id)
    t = threading.Thread(target=_run_list_extraction_worker, args=(list_id, leads_to_process), daemon=True)
    _extraction_threads[list_id] = t
    t.start()

    return {
        "status": "ok",
        "lista_id": list_id,
        "extrayendo": True,
        "pendientes": len(leads_to_process),
        "total": len(leads),
        "mensaje": f"Iniciando extracción con pausas antiban para {len(leads_to_process)} prospectos pendientes."
    }

def stop_list_extraction(list_id: str) -> Dict[str, Any]:
    """Detiene el trabajador de extracción activo para una lista."""
    _active_extractions.discard(list_id)
    return {"status": "ok", "lista_id": list_id, "extrayendo": False, "mensaje": "Extracción detenida"}

def _run_list_extraction_worker(list_id: str, leads_to_process: List[Dict[str, Any]]):
    """Trabajador en segundo plano que enriquece cargos, instituciones y ubicaciones de prospectos pendientes aplicando pausas antiban."""
    import logger_service
    import extractor_engine
    import safety_engine

    logger_service.log_event(
        "INFO",
        "EXTRACTOR",
        f"Iniciando extracción manual de {len(leads_to_process)} leads para lista {list_id}",
        {"lista_id": list_id, "pendientes": len(leads_to_process)}
    )

    try:
        for idx, lead in enumerate(leads_to_process):
            # Check if user cancelled
            if list_id not in _active_extractions:
                logger_service.log_event(
                    "INFO",
                    "EXTRACTOR",
                    f"Extracción detenida por usuario para la lista {list_id}",
                    {"lista_id": list_id, "procesados": idx}
                )
                return

            # Safety check: Kill switch & Daily limits
            with get_db() as conn:
                safety_check = safety_engine.check_linkedin_safety(conn)
                if not safety_check.get("autorizado"):
                    logger_service.log_event(
                        "WARNING",
                        "SAFETY",
                        f"Extracción en pausa antiban: {safety_check.get('motivo')}",
                        {"lista_id": list_id, "codigo": safety_check.get("codigo")}
                    )
                    time.sleep(10)
                    continue

            profile_url = lead.get("perfil_url")
            if not profile_url:
                continue

            lead_id = lead["id"]
            logger_service.log_event(
                "INFO",
                "EXTRACTOR",
                f"Extrayendo lead ({idx + 1}/{len(leads_to_process)}): {lead.get('nombre')} - {profile_url}",
                {"lista_id": list_id, "lead_id": lead_id}
            )

            # Perform live profile enrichment
            enriched = extractor_engine.enrich_lead_from_live_profile(profile_url)
            now_iso = datetime.now().isoformat()

            if enriched.get("ok"):
                nuevo_nombre = enriched.get("nombre")
                if not nuevo_nombre or "esta página no existe" in nuevo_nombre.lower() or "404" in nuevo_nombre.lower():
                    nuevo_nombre = lead.get("nombre")
                nuevo_titular = enriched.get("cargo_titular") or lead.get("cargo_titular")
                nuevo_cargo_act = enriched.get("cargo_actual") or "Directivo"
                nueva_inst = enriched.get("institucion_actual") or "Institución Educativa"
                nueva_ubic = enriched.get("ubicacion") or "Chile"
                nuevo_grado = enriched.get("grado_red") or "2°"

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE leads
                        SET nombre = COALESCE(NULLIF(?, ''), nombre),
                            cargo_titular = COALESCE(NULLIF(?, ''), cargo_titular),
                            cargo_actual = ?,
                            institucion_actual = ?,
                            ubicacion = ?,
                            grado_red = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (nuevo_nombre, nuevo_titular, nuevo_cargo_act, nueva_inst, nueva_ubic, nuevo_grado, now_iso, lead_id))

                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                        VALUES (?, 'LEAD_ENRIQUECIDO_MANUAL', ?, ?)
                    """, (lead_id, f"Datos extraídos en lista: {nuevo_cargo_act} en {nueva_inst} ({nueva_ubic})", now_iso))

                logger_service.log_event(
                    "SUCCESS",
                    "EXTRACTOR",
                    f"Lead extraído exitosamente: {nuevo_nombre} -> {nuevo_cargo_act} @ {nueva_inst} [{nueva_ubic}]",
                    {"lista_id": list_id, "lead_id": lead_id, "cargo": nuevo_cargo_act, "institucion": nueva_inst, "ubicacion": nueva_ubic}
                )
            else:
                logger_service.log_event(
                    "WARNING",
                    "EXTRACTOR",
                    f"No se pudieron extraer datos de {lead.get('nombre')}: {enriched.get('error')}",
                    {"lista_id": list_id, "lead_id": lead_id}
                )

            # Antiban randomized human delay between profile extractions
            if idx < len(leads_to_process) - 1:
                cfg = safety_engine.get_all_safety_config()
                if cfg.get("pausas_antiban_activas", "1") == "0":
                    pause_total = 1.5
                else:
                    pause_total = random.uniform(8.0, 14.0)
                elapsed = 0.0
                while elapsed < pause_total:
                    if list_id not in _active_extractions:
                        return
                    time.sleep(0.5)
                    elapsed += 0.5

        # All pending leads finished: auto-enroll into connected sequences
        if list_id in _active_extractions:
            _active_extractions.discard(list_id)

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT sl.secuencia_id 
                    FROM secuencia_listas sl
                    JOIN secuencias s ON sl.secuencia_id = s.id
                    WHERE sl.lista_id = ? AND sl.activa = 1 AND (s.estado = 'PUBLICADA' OR s.activa = 1)
                """, (list_id,))
                connected_seqs = cursor.fetchall()

                cursor.execute("SELECT lead_id FROM leads_en_lista WHERE lista_id = ?", (list_id,))
                all_lead_ids = [r["lead_id"] for r in cursor.fetchall()]

            enrolled_total = 0
            for seq in connected_seqs:
                seq_id = seq["secuencia_id"]
                res = sequence_engine.assign_leads_to_sequence(seq_id, all_lead_ids)
                if res.get("status") == "ok":
                    enrolled_total += res.get("asignados", 0)

            logger_service.log_event(
                "SUCCESS",
                "EXTRACTOR",
                f"Extracción finalizada para lista {list_id}. {enrolled_total} prospectos ingresados a secuencias vinculadas.",
                {"lista_id": list_id, "enrolled_total": enrolled_total}
            )

    except Exception as exc:
        _active_extractions.discard(list_id)
        logger_service.log_event(
            "ERROR",
            "EXTRACTOR",
            f"Error en worker de extracción de lista {list_id}: {str(exc)}",
            {"lista_id": list_id, "error": str(exc)}
        )


