import json
import urllib.parse
import urllib.request
import urllib.error
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
import browser_service
import logger_service
from database import get_db

MCP_URL = "http://127.0.0.1:9010/mcp"

EXTRACTION_SCRIPT_JS = """
() => {
    const seenUrls = new Set();
    const leads = [];

    // En LinkedIn los resultados de personas son tarjetas de perfiles con links '/in/'
    const allProfileLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));

    allProfileLinks.forEach(a => {
        const rawHref = a.href || '';
        const cleanUrl = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
        
        // Ignorar enlaces secundarios o enlaces sin slug
        if (!cleanUrl.includes('/in/') || cleanUrl.endsWith('/in/')) return;
        if (seenUrls.has(cleanUrl)) return;

        // Tarjeta contenedora de la persona
        const card = a.closest('li') || a.closest('.entity-result') || a.closest('[data-view-name*="result"]') || a.parentElement;
        if (!card) return;

        const cardText = card.innerText ? card.innerText.trim() : '';
        const lines = cardText.split('\\n').map(l => l.trim()).filter(Boolean);

        let nombre = '';
        let grado = '2º';
        let cargo = '';
        let ubicacion = 'Chile';

        // 1. Extraer nombre del link o de la primera línea de la tarjeta
        const linkText = a.innerText.trim();
        if (linkText && !linkText.includes('\\n') && !linkText.includes('contactos en común')) {
            nombre = linkText;
        } else if (lines.length > 0) {
            nombre = lines[0].split('•')[0].split('\\n')[0].trim();
        }

        if (!nombre || nombre.length < 2 || nombre.includes('contactos en común') || nombre.includes('LinkedIn')) {
            return;
        }

        // Limpiar sufijos decorativos
        nombre = nombre.replace(/•.*$/g, '').replace(/Verificado|Premium|\\s+/g, ' ').trim();

        // 2. Extraer grado de red (1º, 2º, 3º+)
        for (const line of lines.slice(0, 3)) {
            if (line.includes('1º') || line.includes('1er')) grado = '1º';
            else if (line.includes('2º') || line.includes('2do')) grado = '2º';
            else if (line.includes('3º') || line.includes('3er')) grado = '3º+';
        }

        // 3. Extraer titular/cargo y ubicación
        for (let i = 1; i < lines.length; i++) {
            const l = lines[i];
            if (l === grado || l.includes('•') || l.includes('Pendiente') || l.includes('Conectar') || l.includes('Mensaje') || l.includes('Seguir')) {
                continue;
            }
            if (!cargo) {
                cargo = l;
            } else if (!ubicacion || ubicacion === 'Chile') {
                if (l.includes('Chile') || l.includes('Región') || l.includes('Santiago') || l.includes('Área') || l.includes('Valparaíso') || l.includes('Concepción') || l.includes('Metropolitana')) {
                    ubicacion = l;
                    break;
                }
            }
        }

        // 4. Extraer institución escolar o empresa
        let institucion = '';
        if (cargo.toLowerCase().includes(' en ')) {
            institucion = cargo.split(/ en /i)[1].split(';')[0].split('|')[0].trim();
        } else if (cargo.toLowerCase().includes('colegio')) {
            const m = cargo.match(/colegio[^\\n;|,]+/i);
            if (m) institucion = m[0].trim();
        } else if (cargo.toLowerCase().includes('escuela')) {
            const m = cargo.match(/escuela[^\\n;|,]+/i);
            if (m) institucion = m[0].trim();
        } else if (cargo.toLowerCase().includes('liceo')) {
            const m = cargo.match(/liceo[^\\n;|,]+/i);
            if (m) institucion = m[0].trim();
        } else if (cargo.toLowerCase().includes('red ')) {
            const m = cargo.match(/red [^\\n;|,]+/i);
            if (m) institucion = m[0].trim();
        } else if (cargo.toLowerCase().includes('instituto')) {
            const m = cargo.match(/instituto[^\\n;|,]+/i);
            if (m) institucion = m[0].trim();
        }

        seenUrls.add(cleanUrl);
        leads.push({
            nombre: nombre,
            grado_red: grado,
            cargo_titular: cargo || 'Profesional / Directivo',
            institucion_actual: institucion || 'Institución Escolar',
            ubicacion: ubicacion || 'Chile',
            perfil_url: cleanUrl
        });
    });

    return {
        total: leads.length,
        leads: leads
    };
}
"""
SCRIPT_EXTRACCION_JS = EXTRACTION_SCRIPT_JS


def _call_mcp_evaluate(page_id: int, func_str: str) -> Dict[str, Any]:
    """Ejecuta una función en el contexto de la página mediante MCP."""
    try:
        # 1. Initialize
        init_body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dripify-local", "version": "1.0"}
            }
        }).encode("utf-8")
        req_init = urllib.request.Request(MCP_URL, data=init_body, headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"
        })
        with urllib.request.urlopen(req_init, timeout=2.5) as res1:
            session_id = res1.headers.get("mcp-session-id")

        if not session_id:
            return {"error": "No se obtuvo session-id de BrowserOS MCP"}

        # 2. Notificar initialized
        notify_body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        req_notify = urllib.request.Request(MCP_URL, data=notify_body, headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id
        })
        try: urllib.request.urlopen(req_notify, timeout=1.0)
        except Exception: pass

        # 3. Invocar evaluate
        eval_body = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "evaluate",
                "arguments": {
                    "agentName": "dripify",
                    "page": page_id,
                    "func": func_str
                }
            }
        }).encode("utf-8")
        req_eval = urllib.request.Request(MCP_URL, data=eval_body, headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id
        })
        with urllib.request.urlopen(req_eval, timeout=10.0) as res_eval:
            raw = res_eval.read().decode("utf-8", errors="ignore")
            # Parsear bloque SSE data: {...}
            for line in raw.split("\n"):
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                        result = payload.get("result", {})
                        for content in result.get("content", []):
                            if content.get("type") == "text":
                                txt = content["text"]
                                # Desempaquetar marcador UNTRUSTED_PAGE_CONTENT de BrowserOS
                                if "[UNTRUSTED_PAGE_CONTENT" in txt:
                                    m = re.search(r'\[UNTRUSTED_PAGE_CONTENT[^\]]*\][^\n]*\n([\s\S]*?)\[END_UNTRUSTED_PAGE_CONTENT', txt)
                                    if m:
                                        txt = m.group(1).strip()
                                try:
                                    parsed = json.loads(txt)
                                    if isinstance(parsed, dict) and "leads" in parsed:
                                        return parsed
                                except Exception:
                                    pass
                    except Exception:
                        pass
        return {"leads": [], "total": 0}
    except Exception as e:
        print(f"[ExtractorEngine] Error evaluate: {e}")
        return {"error": str(e), "leads": [], "total": 0}

def _get_or_create_search_tab(target_url: str) -> Optional[int]:
    """Busca una pestaña abierta en BrowserOS o abre una nueva para navegar."""
    try:
        # Initialize
        init_body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "dripify-local", "version": "1.0"}}
        }).encode("utf-8")
        req_init = urllib.request.Request(MCP_URL, data=init_body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req_init, timeout=2.0) as r:
            session_id = r.headers.get("mcp-session-id")

        # Llamar tabs list
        call_body = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "tabs", "arguments": {"action": "list", "agentName": "dripify"}}
        }).encode("utf-8")
        req_call = urllib.request.Request(MCP_URL, data=call_body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id})
        with urllib.request.urlopen(req_call, timeout=3.0) as r_tabs:
            raw = r_tabs.read().decode("utf-8", errors="ignore")
            # Buscar página existente de búsqueda en los textos
            # Ejemplo: [4] https://www.linkedin.com/search/...
            match = re.search(r'\[(\d+)\]\s*https://www\.linkedin\.com/search', raw)
            if match:
                page_id = int(match.group(1))
                # Navegar la página existente
                nav_body = json.dumps({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "navigate", "arguments": {"agentName": "dripify", "page": page_id, "url": target_url}}
                }).encode("utf-8")
                req_nav = urllib.request.Request(MCP_URL, data=nav_body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id})
                try:
                    urllib.request.urlopen(req_nav, timeout=8.0)
                except Exception:
                    pass
                return page_id

        # Si no había pestaña de búsqueda, abrir nueva con tabs action=new
        new_body = json.dumps({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "tabs", "arguments": {"action": "new", "url": target_url, "agentName": "dripify"}}
        }).encode("utf-8")
        req_new = urllib.request.Request(MCP_URL, data=new_body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id})
        with urllib.request.urlopen(req_new, timeout=8.0) as r_new:
            raw_new = r_new.read().decode("utf-8", errors="ignore")
            m_new = re.search(r'opened page (\d+)', raw_new, re.IGNORECASE)
            if m_new:
                return int(m_new.group(1))
        return 4 # Fallback a página 4 típica
    except Exception as e:
        print(f"[ExtractorEngine] Error navegando: {e}")
        return 4

def generate_slug_id(name: str, profile_url: str, tenant_id: Optional[str] = None) -> str:
    """Genera un ID único y legible para el lead, aislado por tenant si aplica."""
    m = re.search(r'/in/([^/]+)/?', profile_url)
    if m:
        slug = urllib.parse.unquote(m.group(1)).lower().strip('-')
        base = re.sub(r'[^a-zA-Z0-9_-]+', '-', slug)
    else:
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.lower()).strip('-')
        base = f"{slug}-{int(datetime.now().timestamp())}"

    if tenant_id and tenant_id != "ten_superadmin":
        tid_suffix = tenant_id.replace("ten_", "")[:10]
        if not base.endswith(f"_{tid_suffix}"):
            return f"{base}_{tid_suffix}"
    return base

def search_and_extract_leads(term: str, page: int = 1, auto_save: bool = True, list_id: Optional[str] = None, tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """
    Navega a LinkedIn Personas en BrowserOS con el término dado y extrae los 10 leads de la página.
    Si auto_save=True, los inserta en leads.db ignorando duplicados dentro de su tenant_id.
    Si se especifica list_id, los añade a dicha lista e ingresan a secuencias activas en tiempo real.
    """
    import logger_service

    logger_service.log_event(
        "INFO",
        "EXTRACTOR",
        f"Iniciando extracción en LinkedIn para término: '{term}' (Página {page})",
        {"termino": term, "pagina": page, "lista_id": list_id}
    )

    is_electron = browser_service.is_electron_running()
    is_active = is_electron or browser_service.is_browseros_running()

    if not is_active:
        logger_service.log_event(
            "ERROR",
            "EXTRACTOR",
            "Extracción detenida: Ni Electron ni BrowserOS están en ejecución.",
            {"termino": term}
        )
        return {
            "status": "error",
            "mensaje": "El navegador de trabajo no está en ejecución. Por favor inicia la aplicación de escritorio."
        }

    # Validar sesión de LinkedIn si es Electron
    if is_electron:
        estado_electron = browser_service.get_electron_status()
        if not estado_electron.get("sesion_linkedin_activa"):
            logger_service.log_event(
                "WARNING",
                "EXTRACTOR",
                "Extracción pausada: Sesión de LinkedIn no iniciada en el navegador embebido.",
                {"termino": term}
            )
            return {
                "status": "warning",
                "mensaje": "Sesión de LinkedIn no iniciada en el navegador embebido. Por favor inicia sesión con el botón 'Iniciar Sesión' en la cabecera.",
                "requiere_login": True
            }

    encoded_term = urllib.parse.quote(term)
    target_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_term}&origin=SWITCH_SEARCH_VERTICAL"
    if page > 1:
        target_url += f"&page={page}"

    import time

    # 1. Navegar a la página
    logger_service.log_event(
        "INFO",
        "BROWSER",
        f"Navegando a URL de búsqueda LinkedIn: keywords='{term}' (Motor: {'Electron' if is_electron else 'BrowserOS'})",
        {"url": target_url}
    )

    if is_electron:
        browser_service.open_url(target_url)
        # Scroll suave para asegurar hidratación de los componentes de LinkedIn
        browser_service._call_mcp_evaluate("""
            (() => {
                window.scrollBy({ top: 350, behavior: 'smooth' });
                return true;
            })()
        """)
        time.sleep(3.5)

        logger_service.log_event(
            "INFO",
            "EXTRACTOR",
            f"Evaluando elementos de la página en Chromium Embebido (Electron)...",
            {"url": target_url}
        )
        eval_result = browser_service._call_mcp_evaluate(EXTRACTION_SCRIPT_JS)
        if isinstance(eval_result, dict) and "result" in eval_result:
            eval_result = eval_result["result"]
    else:
        page_id = _get_or_create_search_tab(target_url)
        time.sleep(3.0)
        logger_service.log_event(
            "INFO",
            "EXTRACTOR",
            f"Evaluando elementos de la página en BrowserOS (Pestaña {page_id})...",
            {"page_id": page_id}
        )
        eval_result = _call_mcp_evaluate(page_id, EXTRACTION_SCRIPT_JS)

    extracted_leads = eval_result.get("leads", []) if isinstance(eval_result, dict) else []

    if not extracted_leads:
        logger_service.log_event(
            "WARNING",
            "EXTRACTOR",
            f"No se detectaron perfiles en la página {page} para '{term}'. Verifique la búsqueda en LinkedIn.",
            {"url": target_url}
        )
        return {
            "status": "warning",
            "mensaje": f"Se navegó a la búsqueda de '{term}' pero no se detectaron resultados en esta página.",
            "url_busqueda": target_url,
            "leads": []
        }

    logger_service.log_event(
        "INFO",
        "EXTRACTOR",
        f"Detectados {len(extracted_leads)} perfiles en el DOM de LinkedIn. Procesando registros...",
        {"total_encontrados": len(extracted_leads)}
    )

    # 3. Guardar en SQLite leads.db
    new_saved_count = 0
    skipped_duplicates_count = 0
    new_lead_ids = []
    now_iso = datetime.now().isoformat()

    if auto_save:
        with get_db() as conn:
            cursor = conn.cursor()
            for lead in extracted_leads:
                clean_url = lead["perfil_url"].split("?")[0]
                cursor.execute("SELECT id FROM leads WHERE perfil_url = ? AND tenant_id = ?", (clean_url, tenant_id))
                exists = cursor.fetchone()
                
                if exists:
                    skipped_duplicates_count += 1
                    lead["guardado"] = False
                    lead["motivo"] = "Ya existe en la base de datos"
                else:
                    lead_id = generate_slug_id(lead["nombre"], clean_url, tenant_id=tenant_id)
                    cursor.execute("""
                        INSERT INTO leads (
                            id, nombre, cargo_titular, institucion_actual, ubicacion,
                            grado_red, perfil_url, estado, tenant_id, fecha_extraccion, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXTRAIDO', ?, ?, ?, ?)
                    """, (
                        lead_id,
                        lead["nombre"],
                        lead["cargo_titular"],
                        lead["institucion_actual"],
                        lead["ubicacion"],
                        lead["grado_red"],
                        clean_url,
                        tenant_id,
                        now_iso,
                        now_iso,
                        now_iso
                    ))
                    
                    cursor.execute("""
                        INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                        VALUES (?, 'LEAD_EXTRAIDO_LINKEDIN', ?, ?)
                    """, (
                        lead_id,
                        f"Prospecto extraído desde búsqueda: '{term}' (Pág. {page})",
                        now_iso
                    ))
                    
                    new_saved_count += 1
                    new_lead_ids.append(lead_id)
                    lead["guardado"] = True
                    lead["ya_existe"] = False
                    lead["id"] = lead_id

        # 4. Vincular a la lista de leads si fue especificada
        if list_id and new_lead_ids:
            try:
                import lists_engine
                lists_engine.add_leads_to_list(list_id, new_lead_ids)
                logger_service.log_event(
                    "SUCCESS",
                    "LISTS",
                    f"{len(new_lead_ids)} prospectos nuevos vinculados automáticamente a la lista ID '{list_id}'.",
                    {"lista_id": list_id, "nuevos_ids": new_lead_ids}
                )
            except Exception as e:
                logger_service.log_event(
                    "ERROR",
                    "LISTS",
                    f"Error vinculando leads a la lista {list_id}: {e}",
                    {"lista_id": list_id, "error": str(e)}
                )
    else:
        # Modo vista previa / selección manual: verificar existencia sin insertar en la base (estrictamente por tenant_id)
        with get_db() as conn:
            cursor = conn.cursor()
            for lead in extracted_leads:
                clean_url = lead["perfil_url"].split("?")[0]
                lead["perfil_url"] = clean_url
                cursor.execute("SELECT id FROM leads WHERE perfil_url = ? AND tenant_id = ?", (clean_url, tenant_id))
                exists = cursor.fetchone()
                if exists:
                    lead["ya_existe"] = True
                    lead["id"] = exists["id"]
                    lead["guardado"] = True
                else:
                    lead["ya_existe"] = False
                    lead["id"] = generate_slug_id(lead["nombre"], clean_url, tenant_id=tenant_id)
                    lead["guardado"] = False

    logger_service.log_event(
        "SUCCESS",
        "EXTRACTOR",
        f"Búsqueda finalizada: {len(extracted_leads)} prospectos encontrados en LinkedIn.",
        {
            "termino": term,
            "pagina": page,
            "total": len(extracted_leads),
            "nuevos": new_saved_count,
            "duplicados": skipped_duplicates_count
        }
    )

    return {
        "status": "ok",
        "termino_busqueda": term,
        "pagina": page,
        "total_encontrados": len(extracted_leads),
        "nuevos_importados": new_saved_count,
        "duplicados_omitidos": skipped_duplicates_count,
        "lista_id": list_id,
        "leads": extracted_leads
    }

def import_selected_leads(leads_to_import: List[Dict[str, Any]], list_id: Optional[str] = None, tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """
    Inserta en SQLite leads.db únicamente los prospectos seleccionados por el usuario.
    Si se proporciona list_id, los asocia a dicha lista dentro de su tenant_id.
    """
    new_saved = 0
    skipped = 0
    all_target_ids = []
    now_iso = datetime.now().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()
        for lead in leads_to_import:
            clean_url = lead.get("perfil_url", "").split("?")[0]
            if not clean_url:
                continue
            cursor.execute("SELECT id FROM leads WHERE perfil_url = ? AND tenant_id = ?", (clean_url, tenant_id))
            exists = cursor.fetchone()
            if exists:
                skipped += 1
                lead_id = exists["id"]
                all_target_ids.append(lead_id)
            else:
                nombre = lead.get("nombre") or "Profesional de LinkedIn"
                cargo = lead.get("cargo_titular") or lead.get("cargo") or ""
                institucion = lead.get("institucion_actual") or lead.get("institucion") or ""
                ubicacion = lead.get("ubicacion") or "Chile"
                grado_red = lead.get("grado_red") or "2°"
                lead_id = generate_slug_id(nombre, clean_url, tenant_id=tenant_id)

                cursor.execute("""
                    INSERT INTO leads (
                        id, nombre, cargo_titular, institucion_actual, ubicacion,
                        grado_red, perfil_url, estado, tenant_id, fecha_extraccion, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXTRAIDO', ?, ?, ?, ?)
                """, (
                    lead_id, nombre, cargo, institucion, ubicacion, grado_red, clean_url,
                    tenant_id, now_iso, now_iso, now_iso
                ))

                cursor.execute("""
                    INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                    VALUES (?, 'LEAD_IMPORTADO_MANUAL', 'Prospecto añadido a la base tras selección de búsqueda', ?)
                """, (lead_id, now_iso))

                new_saved += 1
                all_target_ids.append(lead_id)

    if list_id and all_target_ids:
        try:
            import lists_engine
            lists_engine.add_leads_to_list(list_id, all_target_ids)
            logger_service.log_event(
                "SUCCESS",
                "LISTS",
                f"{len(all_target_ids)} prospectos vinculados a la lista {list_id}."
            )
        except Exception as e:
            logger_service.log_event("ERROR", "LISTS", f"Error vinculando leads a lista: {e}")

    logger_service.log_event(
        "SUCCESS",
        "EXTRACTOR",
        f"Importación completada: {new_saved} nuevos prospectos añadidos a la base ({skipped} ya existentes vinculados).",
        {"lista_id": list_id, "guardados": new_saved, "duplicados": skipped}
    )

    return {
        "status": "ok",
        "nuevos_importados": new_saved,
        "duplicados_omitidos": skipped,
        "total_procesados": len(leads_to_import),
        "lista_id": list_id
    }

def delete_lead(lead_id: str) -> bool:
    """Elimina completamente un lead y todos sus registros asociados."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads_en_lista WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM historial_actividades WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM mensajes_linkedin WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM correos_electronicos WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM interacciones_sociales WHERE lead_id = ?", (lead_id,))
        cursor.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    logger_service.log_event("INFO", "DATABASE", f"Prospecto {lead_id} eliminado de la base de datos.")
    return True

def delete_leads_batch(lead_ids: List[str]) -> int:
    """Elimina un lote de prospectos y sus dependencias."""
    if not lead_ids:
        return 0
    with get_db() as conn:
        cursor = conn.cursor()
        for lid in lead_ids:
            cursor.execute("DELETE FROM leads_en_lista WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM historial_actividades WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM mensajes_linkedin WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM correos_electronicos WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM interacciones_sociales WHERE lead_id = ?", (lid,))
            cursor.execute("DELETE FROM leads WHERE id = ?", (lid,))
    logger_service.log_event("INFO", "DATABASE", f"{len(lead_ids)} prospectos eliminados en lote de la base.")
    return len(lead_ids)

# ==========================================
# ALIASES FOR BACKWARD COMPATIBILITY
# ==========================================
_obtener_o_crear_pestana_busqueda = _get_or_create_search_tab
generar_slug_id = generate_slug_id
buscar_y_extraer_leads = search_and_extract_leads
importar_leads_seleccionados = import_selected_leads
eliminar_lead = delete_lead
eliminar_leads_lote = delete_leads_batch

