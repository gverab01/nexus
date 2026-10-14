import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from database import get_db
import sequence_engine

# ==============================================================================
# LEAD LIST MANAGEMENT AND DYNAMIC AUDIENCES ENGINE (NexusReach Pro)
# ==============================================================================

def get_lead_lists(tenant_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns all lead lists with progress statistics, counts, and linked sequences.
    Filters by authorized tenant_ids.
    """
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

        for item in lists:
            cursor.execute("""
                SELECT s.id, s.nombre, s.activa, s.estado, sl.auto_ingresar_nuevos
                FROM secuencia_listas sl
                JOIN secuencias s ON sl.secuencia_id = s.id
                WHERE sl.lista_id = ?
            """, (item["id"],))
            item["secuencias_conectadas"] = cursor.fetchall()

        return lists

def get_lead_list_detail(list_id: str) -> Optional[Dict[str, Any]]:
    """Obtains detailed information for a list and its enrolled prospects."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listas_leads WHERE id = ?", (list_id,))
        lead_list = cursor.fetchone()
        if not lead_list:
            return None

        cursor.execute("""
            SELECT s.id, s.nombre, s.activa, s.estado, sl.auto_ingresar_nuevos
            FROM secuencia_listas sl
            JOIN secuencias s ON sl.secuencia_id = s.id
            WHERE sl.lista_id = ?
        """, (list_id,))
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

        return lead_list

def create_lead_list(name: str, description: str = "", search_term: str = "", status: str = "ACTIVA", auto_connect_sequence: bool = False, tenant_id: str = "ten_superadmin", **kwargs) -> Dict[str, Any]:
    """Creates a new prospect list linked to its tenant and optionally to the active sequence."""
    now_iso = datetime.now().isoformat()
    list_id = f"lista-{int(time.time())}"
    final_status = status if status in ("ACTIVA", "EXTRAYENDO", "DETENIDA") else "ACTIVA"
    
    # Backward compatibility with auto_conectar_secuencia argument
    connect_seq = auto_connect_sequence or kwargs.get("auto_conectar_secuencia", False)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listas_leads (id, nombre, descripcion, termino_busqueda, estado, tenant_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (list_id, name, description, search_term, final_status, tenant_id, now_iso, now_iso))

        if connect_seq:
            cursor.execute("SELECT id FROM secuencias WHERE activa = 1 OR estado = 'PUBLICADA' ORDER BY es_default DESC LIMIT 1")
            sec_row = cursor.fetchone()
            if sec_row:
                sec_id = sec_row["id"]
                cursor.execute("""
                    INSERT INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
                    VALUES (?, ?, ?, 1, 1, ?)
                    ON CONFLICT(secuencia_id, lista_id) DO UPDATE SET activa = 1, auto_ingresar_nuevos = 1
                """, (f"sl-{sec_id}-{list_id}", sec_id, list_id, now_iso))

    return get_lead_list_detail(list_id)

def update_lead_list(list_id: str, name: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None, search_term: Optional[str] = None) -> bool:
    """Updates lead list metadata or state."""
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
            fields.append("estado = ?")
            values.append(status)
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
    """Deletes a prospect list."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM listas_leads WHERE id = ?", (list_id,))
        return True

def add_leads_to_list(list_id: str, lead_ids: List[str]) -> Dict[str, Any]:
    """
    Adds leads to a list and, if list is connected to published sequences with auto_ingresar_nuevos = 1,
    enrolls them in the sequence root step.
    """
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

    auto_enrolled = 0
    for sec in active_sequences:
        res = sequence_engine.assign_leads_to_sequence(sec["secuencia_id"], lead_ids)
        if res.get("status") == "ok":
            auto_enrolled += res.get("asignados", 0)

    return {
        "status": "ok",
        "lista_id": list_id,
        "leads_agregados": added,
        "auto_ingresados_en_secuencias": auto_enrolled
    }

def connect_list_to_sequence(sequence_id: str, list_id: str, auto_enroll_existing: bool = True) -> Dict[str, Any]:
    """
    Links a lead list to a sequence and optionally enrolls all existing leads into the sequence.
    """
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
            VALUES (?, ?, ?, 1, 1, ?)
            ON CONFLICT(secuencia_id, lista_id) DO UPDATE SET activa = 1, auto_ingresar_nuevos = 1
        """, (f"sl-{sequence_id}-{list_id}", sequence_id, list_id, now_iso))

        cursor.execute("SELECT lead_id FROM leads_en_lista WHERE lista_id = ?", (list_id,))
        list_leads = [r["lead_id"] for r in cursor.fetchall()]

    enrolled = 0
    if auto_enroll_existing and list_leads:
        res = sequence_engine.assign_leads_to_sequence(sequence_id, list_leads)
        enrolled = res.get("asignados", 0)

    return {
        "status": "ok",
        "secuencia_id": sequence_id,
        "lista_id": list_id,
        "leads_inscritos": enrolled
    }

def disconnect_list_from_sequence(sequence_id: str, list_id: str) -> bool:
    """Unlinks a lead list from a sequence."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM secuencia_listas 
            WHERE secuencia_id = ? AND lista_id = ?
        """, (sequence_id, list_id))
        return True

# ==========================================
# BACKWARD COMPATIBILITY ALIASES
# ==========================================
obtener_listas = get_lead_lists
obtener_lista_detalle = get_lead_list_detail
crear_lista = create_lead_list
actualizar_lista = update_lead_list
eliminar_lista = delete_lead_list
agregar_leads_a_lista = add_leads_to_list
conectar_lista_a_secuencia = connect_list_to_sequence
desconectar_lista_de_secuencia = disconnect_list_from_sequence
