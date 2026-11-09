# ==============================================================================
# MOTOR DE STAGING, MATCHING Y DESCUBRIMIENTO DE PROSPECTOS (NexusReach Pro)
# ==============================================================================
# Permite ingresar prospectos de forma Manual (uno a uno), CSV/Excel o Zoho CRM
# para buscar su perfil real en LinkedIn, validar la coincidencia humana con
# scoring y promoverlos de forma limpia al Directorio oficial o a Listas.
# ==============================================================================

import os
import json
import time
import random
import re
import unicodedata
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from database import get_db
import browser_service
import extractor_engine
import safety_engine
import zoho_browser_service


def normalize_text(text: Optional[str]) -> str:
    """Elimina tildes, signos de puntuación y pasa a minúsculas para matching tolerante."""
    if not text:
        return ""
    # Remover tildes
    nfkd = unicodedata.normalize('NFKD', text)
    clean = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Limpiar puntuación extraña y dejar caracteres alfanuméricos simples
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean)
    return " ".join(clean.lower().split())


def calculate_matching_score(
    source_name: str,
    source_inst: str,
    source_role: str,
    cand_name: str,
    cand_headline: str,
    cand_snippet: str = ""
) -> int:
    """
    Calcula una puntuación de afinidad (0 - 100%) entre el prospecto de origen y
    el candidato extraído de LinkedIn.
    """
    score = 0
    norm_s_name = normalize_text(source_name)
    norm_c_name = normalize_text(cand_name)
    norm_s_inst = normalize_text(source_inst)
    norm_s_role = normalize_text(source_role)
    norm_c_head = normalize_text(cand_headline)
    norm_c_snip = normalize_text(cand_snippet)

    # 1. Coincidencia de Nombre (hasta 50 puntos)
    s_tokens = set(norm_s_name.split())
    c_tokens = set(norm_c_name.split())
    if s_tokens and c_tokens:
        inter = s_tokens.intersection(c_tokens)
        ratio = len(inter) / max(len(s_tokens), 1)
        if norm_s_name == norm_c_name:
            score += 50
        elif ratio >= 0.75:
            score += 45
        elif ratio >= 0.5:
            score += 35
        elif ratio > 0:
            score += 20

    # 2. Coincidencia de Colegio / Institución (hasta 35 puntos)
    if norm_s_inst:
        inst_tokens = [t for t in norm_s_inst.split() if len(t) > 3 and t not in ('colegio', 'escuela', 'liceo', 'instituto', 'fundacion', 'corporacion')]
        if norm_s_inst in norm_c_head or norm_s_inst in norm_c_snip:
            score += 35
        elif inst_tokens:
            matches = [t for t in inst_tokens if t in norm_c_head or t in norm_c_snip]
            if matches:
                ratio = len(matches) / len(inst_tokens)
                score += int(35 * ratio)

    # 3. Coincidencia de Cargo o Función (hasta 15 puntos)
    if norm_s_role:
        role_tokens = [t for t in norm_s_role.split() if len(t) > 3]
        if norm_s_role in norm_c_head or norm_s_role in norm_c_snip:
            score += 15
        elif role_tokens:
            matches = [t for t in role_tokens if t in norm_c_head or t in norm_c_snip]
            if matches:
                score += 10

    return min(100, score)


def create_staging_lead(data: Dict[str, Any], tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """Crea un nuevo prospecto en el buzón de staging (ej: ingreso manual uno a uno)."""
    now_iso = datetime.now().isoformat()
    staging_id = f"stg-{int(time.time())}-{random.randint(100, 999)}"
    
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre de la persona es obligatorio")
        
    institucion = (data.get("institucion") or data.get("colegio") or data.get("empresa") or "").strip()
    email = (data.get("email") or "").strip()
    cargo = (data.get("cargo_declarado") or data.get("cargo") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    origen = data.get("origen", "MANUAL").upper()
    zoho_id = (data.get("zoho_id") or "").strip() or None
    notas = (data.get("notas") or "").strip()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO staging_leads (
                id, tenant_id, nombre, institucion, email, cargo_declarado,
                telefono, origen, zoho_id, estado, notas, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?)
        """, (
            staging_id, tenant_id, nombre, institucion, email, cargo,
            telefono, origen, zoho_id, notas, now_iso, now_iso
        ))

    return get_staging_lead(staging_id)


def batch_create_staging_leads(
    leads_list: List[Dict[str, Any]], 
    tenant_id: str = "ten_superadmin", 
    origen: str = "CSV"
) -> Dict[str, Any]:
    """Inserta una lista de prospectos en lote (desde CSV, Excel o Zoho)."""
    now_iso = datetime.now().isoformat()
    created = 0
    ignored = 0

    with get_db() as conn:
        cursor = conn.cursor()
        for item in leads_list:
            nom = (item.get("nombre") or item.get("name") or "").strip()
            if not nom:
                ignored += 1
                continue
            
            inst = (item.get("institucion") or item.get("colegio") or item.get("empresa") or item.get("company") or "").strip()
            email = (item.get("email") or item.get("correo") or "").strip()
            cargo = (item.get("cargo_declarado") or item.get("cargo") or item.get("puesto") or item.get("title") or "").strip()
            tel = (item.get("telefono") or item.get("phone") or "").strip()
            z_id = (item.get("zoho_id") or "").strip() or None
            
            # Evitar duplicados idénticos en staging por nombre + institucion o email
            if email:
                cursor.execute("SELECT id FROM staging_leads WHERE email = ? AND tenant_id = ? LIMIT 1", (email, tenant_id))
                if cursor.fetchone():
                    ignored += 1
                    continue
            else:
                cursor.execute("SELECT id FROM staging_leads WHERE nombre = ? AND institucion = ? AND tenant_id = ? LIMIT 1", (nom, inst, tenant_id))
                if cursor.fetchone():
                    ignored += 1
                    continue

            stg_id = f"stg-{int(time.time())}-{random.randint(1000, 9999)}"
            cursor.execute("""
                INSERT INTO staging_leads (
                    id, tenant_id, nombre, institucion, email, cargo_declarado,
                    telefono, origen, zoho_id, estado, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)
            """, (stg_id, tenant_id, nom, inst, email, cargo, tel, origen, z_id, now_iso, now_iso))
            created += 1

    return {"ok": True, "creados": created, "ignorados_o_duplicados": ignored}


def get_staging_lead(staging_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene el detalle completo de un prospecto en staging."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM staging_leads WHERE id = ?", (staging_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["candidatos_alternativos"] = json.loads(d.get("candidatos_alternativos_json") or "[]")
        except Exception:
            d["candidatos_alternativos"] = []
        return d


def list_staging_leads(
    tenant_id: str = "ten_superadmin",
    estado: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Lista prospectos en staging con filtros por estado o búsqueda."""
    with get_db() as conn:
        cursor = conn.cursor()
        conditions = ["tenant_id = ?"]
        params: List[Any] = [tenant_id]

        if estado and estado != "TODOS":
            conditions.append("estado = ?")
            params.append(estado.upper().strip())

        if search:
            q = f"%{search.strip()}%"
            conditions.append("(nombre LIKE ? OR institucion LIKE ? OR email LIKE ? OR cargo_declarado LIKE ?)")
            params.extend([q, q, q, q])

        where_clause = " WHERE " + " AND ".join(conditions)

        # Total count
        cursor.execute(f"SELECT COUNT(*) as total FROM staging_leads {where_clause}", params)
        total_count = cursor.fetchone()["total"]

        # Paged items
        params.extend([limit, offset])
        cursor.execute(f"""
            SELECT * FROM staging_leads 
            {where_clause} 
            ORDER BY 
                CASE estado 
                    WHEN 'MATCH_ENCONTRADO' THEN 1 
                    WHEN 'PENDIENTE' THEN 2 
                    WHEN 'SIN_RESULTADOS' THEN 3 
                    WHEN 'VALIDADO' THEN 4 
                    ELSE 5 
                END,
                score_coincidencia DESC,
                created_at DESC 
            LIMIT ? OFFSET ?
        """, params)
        rows = cursor.fetchall()

        items = []
        for r in rows:
            d = dict(r)
            try:
                d["candidatos_alternativos"] = json.loads(d.get("candidatos_alternativos_json") or "[]")
            except Exception:
                d["candidatos_alternativos"] = []
            items.append(d)

        return {
            "total": total_count,
            "leads": items,
            "limit": limit,
            "offset": offset
        }


def get_staging_stats(tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """Obtiene métricas resumidas del buzón de matching."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN estado = 'PENDIENTE' THEN 1 ELSE 0 END) as pendientes,
                SUM(CASE WHEN estado = 'MATCH_ENCONTRADO' THEN 1 ELSE 0 END) as matches_listos,
                SUM(CASE WHEN estado = 'SIN_RESULTADOS' THEN 1 ELSE 0 END) as sin_resultados,
                SUM(CASE WHEN estado = 'VALIDADO' THEN 1 ELSE 0 END) as validados,
                SUM(CASE WHEN estado = 'DESCARTADO' THEN 1 ELSE 0 END) as descartados
            FROM staging_leads
            WHERE tenant_id = ?
        """, (tenant_id,))
        row = cursor.fetchone()
        return {
            "total": row["total"] or 0,
            "pendientes": row["pendientes"] or 0,
            "matches_listos": row["matches_listos"] or 0,
            "sin_resultados": row["sin_resultados"] or 0,
            "validados": row["validados"] or 0,
            "descartados": row["descartados"] or 0
        }


def search_candidate_for_staging_lead(staging_id: str) -> Dict[str, Any]:
    """
    Ejecuta la búsqueda de candidatos en LinkedIn para un lead de staging.
    Utiliza el navegador Chromium (Electron) de forma antiban segura.
    """
    stg = get_staging_lead(staging_id)
    if not stg:
        return {"ok": False, "error": "Prospecto no encontrado en staging"}

    nombre = stg.get("nombre", "").strip()
    institucion = stg.get("institucion", "").strip()
    cargo = stg.get("cargo_declarado", "").strip()

    if not nombre:
        return {"ok": False, "error": "El prospecto no tiene nombre"}

    # Construir término de búsqueda de alta precisión
    clean_inst = re.sub(r'\b(colegio|escuela|liceo|instituto|fundacion|corporacion|slep|daem)\b', '', institucion, flags=re.IGNORECASE).strip()
    primary_term = f"{nombre} {clean_inst}".strip() if clean_inst else f"{nombre} {institucion}".strip()

    # Disparar búsqueda a través de Electron
    res = browser_service.search_people_from_electron(primary_term)
    candidates = res.get("leads") or []

    # Fallback si no hay candidatos y teníamos institución con palabra compuesta
    if not candidates and institucion:
        fallback_term = f"{nombre} {cargo} Chile".strip() if cargo else f"{nombre} Chile"
        res = browser_service.search_people_from_electron(fallback_term)
        candidates = res.get("leads") or []

    now_iso = datetime.now().isoformat()

    if not candidates:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE staging_leads 
                SET estado = 'SIN_RESULTADOS', score_coincidencia = 0, updated_at = ?
                WHERE id = ?
            """, (now_iso, staging_id))
        return {
            "ok": True,
            "estado": "SIN_RESULTADOS",
            "candidatos": [],
            "mensaje": f"No se localizaron perfiles de LinkedIn para '{primary_term}'"
        }

    # Evaluar y puntuar cada candidato
    scored_candidates = []
    for cand in candidates:
        c_name = cand.get("nombre", "")
        c_head = cand.get("cargo_titular", "")
        c_snip = cand.get("snippet_actual", "")
        score = calculate_matching_score(nombre, institucion, cargo, c_name, c_head, c_snip)
        
        # Parsear cargo e institución tentativa del candidato
        c_cargo, c_inst = extractor_engine.parse_cargo_and_institucion(c_head, default_institucion=institucion)
        
        scored_candidates.append({
            "nombre": c_name,
            "perfil_url": cand.get("perfil_url"),
            "cargo_titular": c_head,
            "cargo_actual": c_cargo,
            "institucion_actual": c_inst,
            "ubicacion": cand.get("ubicacion", "Chile"),
            "grado_red": cand.get("grado_red", "2º"),
            "score": score
        })

    # Ordenar por afinidad
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    best = scored_candidates[0]
    alternatives = scored_candidates[1:4]  # Hasta 3 alternativos

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE staging_leads
            SET estado = 'MATCH_ENCONTRADO',
                candidato_nombre = ?,
                candidato_url = ?,
                candidato_titular = ?,
                candidato_cargo = ?,
                candidato_institucion = ?,
                candidato_ubicacion = ?,
                candidato_grado = ?,
                score_coincidencia = ?,
                candidatos_alternativos_json = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            best["nombre"],
            best["perfil_url"],
            best["cargo_titular"],
            best["cargo_actual"],
            best["institucion_actual"],
            best["ubicacion"],
            best["grado_red"],
            best["score"],
            json.dumps(alternatives),
            now_iso,
            staging_id
        ))

    return {
        "ok": True,
        "estado": "MATCH_ENCONTRADO",
        "candidato_principal": best,
        "alternativos": alternatives
    }


def confirm_and_promote_staging_lead(
    staging_id: str,
    target_list_id: Optional[str] = None,
    custom_url: Optional[str] = None,
    custom_nombre: Optional[str] = None,
    custom_cargo: Optional[str] = None,
    custom_institucion: Optional[str] = None,
    tenant_id: str = "ten_superadmin"
) -> Dict[str, Any]:
    """
    Confirma que el candidato de LinkedIn corresponde al prospecto,
    lo promueve formalmente a la tabla 'leads' de NexusReach y opcionalmente
    lo agrega a una lista seleccionada por el usuario.
    """
    stg = get_staging_lead(staging_id)
    if not stg:
        raise ValueError("Prospecto de staging no encontrado")

    final_url = (custom_url or stg.get("candidato_url") or "").strip()
    if not final_url:
        raise ValueError("Se requiere una URL válida de LinkedIn para validar y promover el prospecto")

    now_iso = datetime.now().isoformat()
    lead_id = f"lead-match-{int(time.time())}-{random.randint(100, 999)}"

    final_nombre = (custom_nombre or stg.get("candidato_nombre") or stg.get("nombre") or "").strip()
    final_titular = stg.get("candidato_titular") or stg.get("cargo_declarado") or ""
    final_cargo = (custom_cargo or stg.get("candidato_cargo") or stg.get("cargo_declarado") or "Profesional").strip()
    final_inst = (custom_institucion or stg.get("candidato_institucion") or stg.get("institucion") or "").strip()
    final_ubic = stg.get("candidato_ubicacion") or "Chile"
    final_grado = stg.get("candidato_grado") or "2º"
    final_email = stg.get("email") or None
    final_tel = stg.get("telefono") or None
    origen = stg.get("origen") or "MATCHING_LINKEDIN"
    zoho_id = stg.get("zoho_id")

    tags = ["MATCH_VALIDADO", f"ORIGEN_{origen}"]

    with get_db() as conn:
        cursor = conn.cursor()
        
        # Verificar si ya existe en leads por URL o por email
        existing_id = None
        if final_url:
            clean_u = final_url.split("?")[0].rstrip("/") + "/"
            cursor.execute("SELECT id FROM leads WHERE perfil_url LIKE ? OR perfil_url = ? LIMIT 1", (f"{clean_u}%", final_url))
            row_e = cursor.fetchone()
            if row_e:
                existing_id = row_e["id"]

        if not existing_id and final_email:
            cursor.execute("SELECT id FROM leads WHERE email = ? LIMIT 1", (final_email,))
            row_em = cursor.fetchone()
            if row_em:
                existing_id = row_em["id"]

        if existing_id:
            # Actualizar lead existente con los nuevos datos cruzados
            lead_id = existing_id
            cursor.execute("""
                UPDATE leads 
                SET perfil_url = COALESCE(NULLIF(perfil_url, ''), ?),
                    email = COALESCE(NULLIF(email, ''), ?),
                    telefono = COALESCE(NULLIF(telefono, ''), ?),
                    cargo_actual = COALESCE(NULLIF(?, ''), cargo_actual),
                    institucion_actual = COALESCE(NULLIF(?, ''), institucion_actual),
                    zoho_id = COALESCE(NULLIF(zoho_id, ''), ?),
                    updated_at = ?
                WHERE id = ?
            """, (final_url, final_email, final_tel, final_cargo, final_inst, zoho_id, now_iso, lead_id))
        else:
            # Crear nuevo lead oficial
            cursor.execute("""
                INSERT INTO leads (
                    id, nombre, cargo_titular, cargo_actual, institucion_actual,
                    ubicacion, grado_red, perfil_url, email, telefono,
                    estado, tags, notas, zoho_id, tenant_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EXTRAIDO', ?, ?, ?, ?, ?, ?)
            """, (
                lead_id, final_nombre, final_titular, final_cargo, final_inst,
                final_ubic, final_grado, final_url, final_email, final_tel,
                json.dumps(tags),
                f"Validado y promovido desde buzón de matching ({origen}).",
                zoho_id, tenant_id, now_iso, now_iso
            ))

        # Si se especificó una lista de destino, vincular
        if target_list_id:
            cursor.execute("""
                INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
                VALUES (?, ?, ?, ?)
            """, (f"ll-{target_list_id}-{lead_id}", target_list_id, lead_id, now_iso))

        # Actualizar staging_leads como VALIDADO
        cursor.execute("""
            UPDATE staging_leads
            SET estado = 'VALIDADO', promovido_lead_id = ?, updated_at = ?
            WHERE id = ?
        """, (lead_id, now_iso, staging_id))

        # Registrar historial de actividad
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'MATCH_VALIDADO_USUARIO', ?, ?)
        """, (lead_id, f"Prospecto validado manualmente en LinkedIn: {final_nombre} ({final_cargo} en {final_inst}).", now_iso))

    return {
        "ok": True,
        "lead_id": lead_id,
        "mensaje": f"¡Prospecto validado exitosamente! Agregado como lead oficial{' a la lista seleccionada' if target_list_id else ''}."
    }


def discard_staging_lead(staging_id: str, motivo: str = "") -> bool:
    """Marca un prospecto de staging como descartado."""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE staging_leads
            SET estado = 'DESCARTADO', notas = COALESCE(notas, '') || ?, updated_at = ?
            WHERE id = ?
        """, (f" [Descartado: {motivo}]" if motivo else "", now_iso, staging_id))
        return cursor.rowcount > 0


def delete_staging_lead(staging_id: str) -> bool:
    """Elimina definitivamente un prospecto del staging."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM staging_leads WHERE id = ?", (staging_id,))
        return cursor.rowcount > 0


def import_from_zoho_to_staging(tenant_id: str = "ten_superadmin", max_records: int = 50) -> Dict[str, Any]:
    """
    Importa contactos o leads desde Zoho CRM que tengan email e institución
    para someterlos al proceso de descubrimiento en LinkedIn.
    """
    coql = f"""
        SELECT id, First_Name, Last_Name, Full_Name, Email, Phone, Title, Account_Name
        FROM Contacts
        WHERE Email IS NOT NULL
        ORDER BY Modified_Time DESC
        LIMIT {min(max_records, 100)}
    """
    res = zoho_browser_service.execute_zoho_coql(coql)
    if not res.get("ok"):
        return {"ok": False, "error": f"Error consultando Zoho CRM: {res.get('error', 'Error COQL')}"}

    records = res.get("data") or []
    formatted = []
    for r in records:
        full_name = r.get("Full_Name") or f"{r.get('First_Name', '')} {r.get('Last_Name', '')}".strip()
        acc = r.get("Account_Name") or {}
        inst_name = acc.get("name") if isinstance(acc, dict) else str(acc or "")
        
        formatted.append({
            "nombre": full_name,
            "institucion": inst_name,
            "email": r.get("Email"),
            "cargo_declarado": r.get("Title") or "",
            "telefono": r.get("Phone") or "",
            "zoho_id": r.get("id"),
            "origen": "ZOHO_CRM"
        })

    import_res = batch_create_staging_leads(formatted, tenant_id=tenant_id, origen="ZOHO_CRM")
    return {
        "ok": True,
        "importados": import_res.get("creados", 0),
        "ignorados": import_res.get("ignorados_o_duplicados", 0),
        "total_consultados": len(records)
    }

