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
from lead_parser import (
    parse_cargo_and_institucion,
    is_invalid_role,
    is_invalid_institution,
    clean_institution_name,
    refine_pie_institution
)

MCP_URL = "http://127.0.0.1:9010/mcp"

EXTRACTION_SCRIPT_JS = r"""
() => {
    try {
        const seenUrls = new Set();
        const leads = [];

        // 1. Identificar lista de resultados de búsqueda de personas
        // Compatible con LinkedIn SDUI 2026 y versiones clásicas de Chromium
        let cardElements = [];
        const lists = Array.from(document.querySelectorAll('[role="list"]'));
        const searchList = lists.find(l => l.children.length >= 3 && l.children.length <= 15);
        if (searchList) {
            cardElements = Array.from(searchList.children);
        } else {
            cardElements = Array.from(document.querySelectorAll('.reusable-search__result-container, .entity-result, [componentkey*="SearchResult"]'));
        }

        // Si se encontraron tarjetas estructuradas, procesar tarjeta a tarjeta (AISLANDO al candidato principal)
        if (cardElements.length > 0) {
            cardElements.forEach(card => {
                try {
                    const text = card.innerText ? card.innerText.trim() : '';
                    if (!text || text.length < 10) return;
                    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

                    // Extraer únicamente el enlace del CANDIDATO PRINCIPAL (excluyendo contactos en común)
                    const allLinks = Array.from(card.querySelectorAll('a[href*="/in/"]'));
                    const primaryLink = allLinks.find(a => {
                        const parent = a.closest('p') || a.parentElement;
                        const pText = parent ? parent.innerText : '';
                        return !pText.includes('contacto') && !pText.includes('común') && !pText.includes('mutual');
                    }) || allLinks[0];

                    if (!primaryLink) return;

                    const cleanUrl = primaryLink.href.split('?')[0].replace(/\/+$/, '') + '/';
                    if (!cleanUrl.includes('/in/') || cleanUrl.endsWith('/in/')) return;
                    if (seenUrls.has(cleanUrl)) return;

                    let nombre = '';
                    let grado = '2º';
                    let titular = '';
                    let ubicacion = 'Chile';
                    let snippetActual = '';

                    const isDegreeText = (t) => {
                        if (!t) return false;
                        const clean = t.trim();
                        return /^[·•\s]*(?:1er|1º|1°|2do|2º|2°|3er|3º|3°|\d+[º°]|\d+(?:er|do|to|st|nd|rd|th))\+?[·•\s]*$/i.test(clean);
                    };

                    const extractDegree = (t) => {
                        if (!t) return '2º';
                        if (/1er|1º|1°/i.test(t)) return '1º';
                        if (/2do|2º|2°/i.test(t)) return '2º';
                        if (/3er|3º|3°|\+/i.test(t)) return '3º+';
                        return '2º';
                    };

                    // Línea 0: Nombre • Grado (ej: "Alejandro Calvo • 2º")
                    if (lines.length > 0) {
                        const first = lines[0];
                        const parts = first.split(/[•·]/);
                        nombre = parts[0].replace(/Verificado|Premium|\s+/g, ' ').trim();
                        if (parts.length > 1) {
                            grado = extractDegree(parts[1]);
                        }
                    }

                    if (!nombre || nombre.includes('contacto') || nombre.includes('LinkedIn')) return;

                    // Buscar snippet explícito "Actual:"
                    const snipLine = lines.find(l => /^(Actual|Current|Experiencia actual)\s*:/i.test(l));
                    if (snipLine) snippetActual = snipLine;

                    // Extraer titular y ubicación entre las líneas
                    for (let i = 1; i < lines.length; i++) {
                        const l = lines[i];
                        if (l === '·' || l === '•') continue;
                        if (isDegreeText(l)) {
                            grado = extractDegree(l);
                            continue;
                        }
                        if (l.includes('Conectar') || l.includes('Pendiente') || l.includes('Mensaje') || l.includes('Seguir') || l.includes('contacto') || l.includes('común') || l.includes('mutual')) {
                            continue;
                        }
                        if (/^(Actual|Current|Pasado|Past|Experiencia actual)\s*:/i.test(l)) {
                            continue;
                        }
                        if (!titular) {
                            titular = l;
                        } else if (!ubicacion || ubicacion === 'Chile') {
                            const cleanLoc = l.replace(/[·•|;].*$/, '').trim();
                            if (cleanLoc.length >= 2 && cleanLoc.length < 90 && cleanLoc !== titular) {
                                ubicacion = cleanLoc;
                                break;
                            }
                        }
                    }

                    // Extraer institución si viene en el titular o snippet
                    let institucion = '';
                    const sourceText = snippetActual || titular;
                    if (sourceText.toLowerCase().includes(' en ')) {
                        institucion = sourceText.split(/ en /i)[1].split(/[;|\·•]/)[0].trim();
                    } else if (sourceText.toLowerCase().includes(' at ')) {
                        institucion = sourceText.split(/ at /i)[1].split(/[;|\·•]/)[0].trim();
                    }

                    seenUrls.add(cleanUrl);
                    leads.push({
                        nombre: nombre,
                        grado_red: grado,
                        cargo_titular: titular || 'Profesional',
                        snippet_actual: snippetActual,
                        institucion_actual: institucion,
                        ubicacion: ubicacion || 'Chile',
                        perfil_url: cleanUrl
                    });
                } catch (e) {}
            });
        }

        return {
            total: leads.length,
            leads: leads
        };
    } catch (err) {
        return { total: 0, leads: [], error: err.message };
    }
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
        logger_service.log_event(
            "INFO",
            "EXTRACTOR",
            f"Ejecutando búsqueda y extracción precompilada en Electron para '{term}' (Página {page})...",
            {"termino": term, "pagina": page, "url": target_url}
        )
        electron_res = browser_service.search_people_from_electron(term, page=page)
        if electron_res.get("success"):
            extracted_leads = electron_res.get("leads", [])
        else:
            logger_service.log_event(
                "WARNING",
                "EXTRACTOR",
                f"Aviso en búsqueda precompilada de Electron: {electron_res.get('error')}",
                {"error": electron_res.get("error")}
            )
            extracted_leads = []
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

    # Preprocesar y extraer cargo_actual e institución limpia para cada lead
    for lead in extracted_leads:
        cargo_act, inst = parse_cargo_and_institucion(
            lead.get("cargo_titular", ""),
            snippet_actual=lead.get("snippet_actual", ""),
            default_institucion=lead.get("institucion_actual", "")
        )
        lead["cargo_actual"] = cargo_act
        if inst:
            lead["institucion_actual"] = inst

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
                            id, nombre, cargo_titular, cargo_actual, institucion_actual, ubicacion,
                            grado_red, perfil_url, estado, tenant_id, fecha_extraccion, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'EXTRAIDO', ?, ?, ?, ?)
                    """, (
                        lead_id,
                        lead["nombre"],
                        lead["cargo_titular"],
                        lead["cargo_actual"],
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
        # Modo vista previa / selección manual: verificar existencia en lote sin insertar en la base (estrictamente por tenant_id)
        with get_db() as conn:
            cursor = conn.cursor()
            clean_urls = []
            for lead in extracted_leads:
                curl = lead["perfil_url"].split("?")[0]
                lead["perfil_url"] = curl
                clean_urls.append(curl)

            existing_map = {}
            if clean_urls:
                ph = ", ".join(["?"] * len(clean_urls))
                cursor.execute(f"""
                    SELECT id, perfil_url, cargo_actual, institucion_actual, ubicacion, estado 
                    FROM leads 
                    WHERE perfil_url IN ({ph}) AND tenant_id = ?
                """, (*clean_urls, tenant_id))
                existing_map = {r["perfil_url"]: r for r in cursor.fetchall()}

            lead_ids = [r["id"] for r in existing_map.values()]
            lists_by_lead = {}
            sequences_by_lead = {}

            if lead_ids:
                id_ph = ", ".join(["?"] * len(lead_ids))
                cursor.execute(f"""
                    SELECT lel.lead_id, ll.id, ll.nombre 
                    FROM leads_en_lista lel 
                    JOIN listas_leads ll ON lel.lista_id = ll.id 
                    WHERE lel.lead_id IN ({id_ph})
                """, lead_ids)
                for r in cursor.fetchall():
                    lists_by_lead.setdefault(r["lead_id"], []).append({"id": r["id"], "nombre": r["nombre"]})

                cursor.execute(f"""
                    SELECT les.lead_id, s.id, s.nombre, s.estado, les.estado as estado_lead 
                    FROM leads_en_secuencia les 
                    JOIN secuencias s ON les.secuencia_id = s.id 
                    WHERE les.lead_id IN ({id_ph})
                """, lead_ids)
                for r in cursor.fetchall():
                    sequences_by_lead.setdefault(r["lead_id"], []).append({
                        "id": r["id"], "nombre": r["nombre"], "estado": r["estado"], "estado_lead": r["estado_lead"]
                    })

            for lead in extracted_leads:
                clean_url = lead["perfil_url"]
                exists = existing_map.get(clean_url)
                if exists:
                    lead_id = exists["id"]
                    lead["ya_existe"] = True
                    lead["id"] = lead_id
                    lead["guardado"] = True
                    if exists["cargo_actual"]:
                        lead["cargo_actual"] = exists["cargo_actual"]
                    if exists["institucion_actual"]:
                        lead["institucion_actual"] = exists["institucion_actual"]
                    if exists["ubicacion"] and exists["ubicacion"] != "Chile":
                        lead["ubicacion"] = exists["ubicacion"]
                    lead["estado"] = exists["estado"]
                    lead["listas"] = lists_by_lead.get(lead_id, [])
                    lead["secuencias"] = sequences_by_lead.get(lead_id, [])
                else:
                    lead["ya_existe"] = False
                    lead["id"] = generate_slug_id(lead["nombre"], clean_url, tenant_id=tenant_id)
                    lead["guardado"] = False
                    lead["listas"] = []
                    lead["secuencias"] = []

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

def extract_network_leads(source: str = "all", limit: int = 50, tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """
    Extrae contactos y decisores desde la red personal de LinkedIn del usuario:
    - Conexiones de 1er grado (source='connections')
    - Invitaciones enviadas pendientes (source='sent_invitations')
    - Ambos canales consolidados (source='all')
    - Cantidad configurable mediante limit (default 50)

    Verifica deduplicación y pertenencia a listas en SQLite leads.db para el tenant_id activo,
    entregando los leads listos para visualización y selección con un solo clic.
    """
    import logger_service

    is_electron = browser_service.is_electron_running()
    is_active = is_electron or browser_service.is_browseros_running()

    if not is_active:
        return {
            "status": "error",
            "mensaje": "El navegador de trabajo no está en ejecución. Por favor inicia la aplicación de escritorio."
        }

    if is_electron:
        estado_electron = browser_service.get_electron_status()
        if not estado_electron.get("sesion_linkedin_activa"):
            return {
                "status": "warning",
                "mensaje": "Sesión de LinkedIn no iniciada en el navegador embebido. Por favor inicia sesión en LinkedIn antes de extraer.",
                "requiere_login": True
            }

    logger_service.log_event(
        "INFO",
        "EXTRACTOR",
        f"Iniciando extracción de red LinkedIn: source='{source}', limit={limit}",
        {"source": source, "limit": limit, "tenant_id": tenant_id}
    )

    res = browser_service.extract_network_from_electron(source=source, limit=limit)
    if not res.get("success"):
        error_msg = res.get("error") or "Error extrayendo contactos de LinkedIn"
        return {
            "status": "error",
            "mensaje": f"No se pudo extraer la red de LinkedIn: {error_msg}",
            "leads": []
        }

    raw_leads = res.get("leads", [])
    if not raw_leads:
        return {
            "status": "warning",
            "mensaje": "No se detectaron contactos en la sección de red solicitada.",
            "total": 0,
            "leads": []
        }

    # Preprocesar titulares, cargos e instituciones
    for lead in raw_leads:
        cargo_tit = lead.get("cargo_titular") or lead.get("cargo") or ""
        cargo_act, inst = parse_cargo_and_institucion(
            cargo_tit,
            default_institucion=lead.get("institucion_actual", "")
        )
        lead["cargo_actual"] = cargo_act or "Profesional de LinkedIn"
        lead["institucion_actual"] = inst or ""
        lead["ubicacion"] = lead.get("ubicacion") or "Chile"
        lead["grado_red"] = lead.get("grado_red") or ("1º" if lead.get("estado_origen") == "CONECTADO" else "2º")
        lead["estado"] = lead.get("estado_origen") or "CONECTADO"

    # Verificar existencia previa en base de datos para este tenant_id
    with get_db() as conn:
        cursor = conn.cursor()
        clean_urls = []
        for lead in raw_leads:
            curl = lead["perfil_url"].split("?")[0]
            lead["perfil_url"] = curl
            clean_urls.append(curl)

        existing_map = {}
        if clean_urls:
            ph = ", ".join(["?"] * len(clean_urls))
            cursor.execute(f"""
                SELECT id, perfil_url, estado, cargo_actual, institucion_actual 
                FROM leads 
                WHERE perfil_url IN ({ph}) AND tenant_id = ?
            """, (*clean_urls, tenant_id))
            existing_map = {r["perfil_url"]: r for r in cursor.fetchall()}

        lead_ids = [r["id"] for r in existing_map.values()]
        lists_by_lead = {}
        if lead_ids:
            id_ph = ", ".join(["?"] * len(lead_ids))
            cursor.execute(f"""
                SELECT lel.lead_id, ll.id, ll.nombre 
                FROM leads_en_lista lel 
                JOIN listas_leads ll ON lel.lista_id = ll.id 
                WHERE lel.lead_id IN ({id_ph})
            """, (*lead_ids,))
            for row in cursor.fetchall():
                lists_by_lead.setdefault(row["lead_id"], []).append({"id": row["id"], "nombre": row["nombre"]})

        for lead in raw_leads:
            ex = existing_map.get(lead["perfil_url"])
            if ex:
                lead["ya_existe"] = True
                lead["id"] = ex["id"]
                lead["estado_actual"] = ex["estado"]
                lead["listas"] = lists_by_lead.get(ex["id"], [])
            else:
                lead["ya_existe"] = False
                lead["id"] = generate_slug_id(lead["nombre"], lead["perfil_url"], tenant_id=tenant_id)
                lead["listas"] = []

    logger_service.log_event(
        "SUCCESS",
        "EXTRACTOR",
        f"Extracción de red completada: {len(raw_leads)} perfiles procesados ({sum(1 for l in raw_leads if not l['ya_existe'])} nuevos).",
        {"total": len(raw_leads), "source": source}
    )

    return {
        "status": "success",
        "total": len(raw_leads),
        "origen": source,
        "mensaje": f"Se extrajeron {len(raw_leads)} prospectos desde tu red de LinkedIn.",
        "leads": raw_leads
    }

def import_selected_leads(leads_to_import: List[Dict[str, Any]], list_id: Optional[str] = None, list_ids: Optional[List[str]] = None, tenant_id: str = "ten_superadmin") -> Dict[str, Any]:
    """
    Inserta en SQLite leads.db únicamente los prospectos seleccionados por el usuario.
    Si se proporciona list_id o list_ids, los asocia a dichas listas dentro de su tenant_id.
    Conserva el estado de origen (CONECTADO o INVITACION_ENVIADA) y el grado de red.
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
                cargo_titular = lead.get("cargo_titular") or lead.get("cargo") or ""
                cargo_actual = lead.get("cargo_actual")
                institucion = lead.get("institucion_actual") or lead.get("institucion") or ""
                if not cargo_actual:
                    cargo_actual, parsed_inst = parse_cargo_and_institucion(
                        cargo_titular,
                        snippet_actual=lead.get("snippet_actual", ""),
                        default_institucion=institucion
                    )
                    if not institucion:
                        institucion = parsed_inst

                ubicacion = lead.get("ubicacion") or "Chile"
                estado_inicial = lead.get("estado") or lead.get("estado_origen") or "EXTRAIDO"
                grado_red = lead.get("grado_red") or ("1º" if estado_inicial == "CONECTADO" else "2°")
                fecha_conexion = now_iso if estado_inicial == "CONECTADO" else None
                lead_id = generate_slug_id(nombre, clean_url, tenant_id=tenant_id)

                cursor.execute("""
                    INSERT INTO leads (
                        id, nombre, cargo_titular, cargo_actual, institucion_actual, ubicacion,
                        grado_red, perfil_url, estado, tenant_id, fecha_conexion, fecha_extraccion, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lead_id, nombre, cargo_titular, cargo_actual, institucion, ubicacion, grado_red, clean_url,
                    estado_inicial, tenant_id, fecha_conexion, now_iso, now_iso, now_iso
                ))

                if estado_inicial == "CONECTADO":
                    tipo_evento = "CONEXION_IMPORTADA_MANUAL"
                    desc_evento = "Contacto de 1er grado importado desde tu red personal de LinkedIn"
                elif estado_inicial == "INVITACION_ENVIADA":
                    tipo_evento = "INVITACION_IMPORTADA_MANUAL"
                    desc_evento = "Invitación pendiente importada desde tu red de LinkedIn"
                else:
                    tipo_evento = "LEAD_IMPORTADO_MANUAL"
                    desc_evento = "Prospecto añadido a la base tras selección de búsqueda"

                cursor.execute("""
                    INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (lead_id, tipo_evento, desc_evento, now_iso))

                new_saved += 1
                all_target_ids.append(lead_id)

    target_lists = []
    if list_ids:
        target_lists.extend(list_ids)
    if list_id and list_id not in target_lists:
        target_lists.append(list_id)

    if target_lists and all_target_ids:
        try:
            import lists_engine
            for lid in target_lists:
                lists_engine.add_leads_to_list(lid, all_target_ids)
            logger_service.log_event(
                "SUCCESS",
                "LISTS",
                f"{len(all_target_ids)} prospectos vinculados a {len(target_lists)} lista(s)."
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

EXTRACT_DETAILS_EXP_JS = r"""
(() => {
    try {
        const main = document.querySelector('main') || document.body;
        if (!main) return { ok: false, error: 'No main element' };

        const EMPLOYMENT_TYPES = [
            'jornada completa', 'jornada parcial', 'tiempo completo', 'medio tiempo',
            'profesional independiente', 'autónomo', 'autónoma', 'contrato temporal',
            'contrato de prácticas', 'contrato de formación', 'de temporada', 'en prácticas',
            'full-time', 'part-time', 'self-employed', 'freelance', 'contract', 'internship', 'seasonal'
        ];

        const isEmploymentType = (t) => {
            if (!t) return false;
            const c = t.toLowerCase().trim();
            return EMPLOYMENT_TYPES.some(type => c === type || c.startsWith(type + ' ·') || c.startsWith(type + '•') || c.startsWith(type + ' -'));
        };

        const isDateLine = (t) => {
            if (!t) return false;
            const c = t.toLowerCase();
            return (c.includes('actualidad') || c.includes('present') || c.includes('dic.') || c.includes('ene.') || c.includes('mar.') || c.includes('20')) &&
                   (c.includes('año') || c.includes('mes') || c.includes('yr') || c.includes('mo') || /\d{4}/.test(c));
        };

        let experienceEntries = [];
        const mainLis = Array.from(main.querySelectorAll('li'));
        const validLis = mainLis.filter(li => {
            const text = li.innerText || '';
            return isDateLine(text) && text.split('\n').length >= 2;
        });

        const itemsToProcess = validLis.length > 0 ? validLis : [main];

        for (const item of itemsToProcess) {
            const rawText = item.innerText || '';
            const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean);
            
            const expIdx = lines.findIndex(l => l.toLowerCase() === 'experiencia' || l.toLowerCase() === 'experience');
            const relevantLines = expIdx !== -1 ? lines.slice(expIdx + 1) : lines;

            if (relevantLines.length < 2) continue;

            const dateIdx = relevantLines.findIndex(l => isDateLine(l));
            if (dateIdx === -1) continue;

            let role = '';
            let company = '';
            let location = '';

            if (dateIdx === 1) {
                role = relevantLines[0];
            } else if (dateIdx >= 2) {
                role = relevantLines[0];
                company = relevantLines[1].replace(/[·•|;].*$/, '').trim();
                if (isEmploymentType(company)) {
                    company = '';
                }
            }

            if (dateIdx + 1 < relevantLines.length) {
                const afterDate = relevantLines[dateIdx + 1];
                const low = afterDate.toLowerCase();
                const isJob = /^(psic[oó]log|picolog|educador|coordinador|director|docente|profesor|terapeuta|inspector|jefe|asistente|encargad)/i.test(low);
                const isLoc = low.includes('chile') || low.includes('regi') || low.includes('santiago') || low.includes('presencial') || low.includes('híbrido') || low.includes('remoto');
                if (!isJob && !isEmploymentType(afterDate) && !afterDate.startsWith('Educación') && !afterDate.startsWith('Aptitudes') && isLoc && afterDate.length < 90) {
                    location = afterDate.replace(/[·•|;].*$/, '').trim();
                }
            }

            if (role || company) {
                experienceEntries.push({
                    role: role,
                    company: company,
                    date: relevantLines[dateIdx],
                    location: location
                });
                break;
            }
        }

        return {
            ok: true,
            entriesCount: experienceEntries.length,
            firstEntry: experienceEntries[0] || null
        };
    } catch (e) {
        return { ok: false, error: e.message };
    }
})()
"""

def enrich_lead_from_live_profile(profile_url: str) -> Dict[str, Any]:
    """
    Navega o inspecciona el perfil activo en el navegador de trabajo para extraer
    con máxima fidelidad el nombre, titular, cargo actual, empresa u organización y ubicación real.
    """
    import time
    import re
    if not profile_url:
        return {"ok": False, "error": "URL de perfil no especificada"}

    clean_url = re.sub(r'/+$', '', profile_url.split("?")[0].strip()) + "/"

    # 1. Modo Electron Chromium Aislado: Extracción Precompilada Segura (Regla C-01 Directrices v1.3)
    if browser_service.is_electron_running():
        res = browser_service.enrich_profile_from_electron(clean_url)
        if not res.get("ok") and not res.get("success"):
            return {"ok": False, "error": res.get("error", "Error extrayendo datos del perfil en Electron")}

        res_data = res.get("result") if isinstance(res.get("result"), dict) else res
        if not res_data.get("ok"):
            return {"ok": False, "error": res_data.get("error", "Error extrayendo datos del perfil")}

        nombre = res_data.get("nombre") or ""
        if "esta página no existe" in nombre.lower():
            return {"ok": False, "error": "Página no encontrada en LinkedIn (404)"}

        exp_role = res_data.get("expRole", "")
        exp_company = clean_institution_name(res_data.get("expCompany", ""))
        headline = res_data.get("headline", "")
        loc = res_data.get("location") or "Chile"
        grado = res_data.get("grado") or "2°"

        if exp_role and is_invalid_role(exp_role):
            exp_role = ""
        if exp_company and is_invalid_institution(exp_company):
            exp_company = ""

        # Extraer si el titular contiene una empresa explícita destacada (ej: @Vesta Software Group)
        headline_comp = ""
        m_head_at = re.search(r'@\s*([A-Za-zÁÉÍÓÚáéíóúñÑ0-9\s\.\&\-]+?)(?:\s+[|;•·\n\–\—]|$)', headline)
        if m_head_at:
            cand = clean_institution_name(m_head_at.group(1))
            if cand and not is_invalid_institution(cand) and len(cand) >= 2:
                headline_comp = cand

        details = res_data.get("details")
        if details and isinstance(details, dict):
            first_entry = details.get("firstEntry")
            if first_entry and isinstance(first_entry, dict):
                det_role = first_entry.get("role", "")
                det_company = clean_institution_name(first_entry.get("company", ""))
                det_loc = first_entry.get("location", "")
                det_date = (first_entry.get("date") or "").lower()
                is_current = "actualidad" in det_date or "present" in det_date or not det_date
                
                # Solo reemplazar si es un cargo actual en vigor o si no teníamos rol
                if det_role and not is_invalid_role(det_role) and (not exp_role or is_current):
                    exp_role = det_role
                if det_company and not is_invalid_institution(det_company) and (not exp_company or is_current):
                    exp_company = det_company
                if det_loc and (not loc or loc in ["Chile", "Área metropolitana de Santiago", "Gran Santiago", "Santiago"] or len(det_loc) > len(loc)):
                    loc = det_loc

        # Si el headline especifica claramente la empresa con @ y exp_company no es coincidente o vino de fallback, preferir la empresa del headline
        if headline_comp and (not exp_company or is_invalid_institution(exp_company)):
            exp_company = headline_comp

        if exp_role and not is_invalid_role(exp_role):
            c_act, inst = parse_cargo_and_institucion(exp_role, default_institucion=exp_company, location=loc)
        else:
            c_act, inst = parse_cargo_and_institucion(headline, default_institucion=exp_company, location=loc)

        if not inst and headline_comp:
            inst = headline_comp

        if not inst and headline:
            match_en = re.search(r'\s+(?:en|at|@)\s+([^|;•·\n\–\—]+)', headline, re.IGNORECASE)
            if match_en:
                cand_en = clean_institution_name(match_en.group(1).strip())
                if cand_en and not is_invalid_institution(cand_en):
                    inst = cand_en

        # Si aún no hay institución pero exp_company viene de LinkedIn, usarla directamente
        if not inst and exp_company and not is_invalid_institution(exp_company):
            inst = exp_company.strip()

        # Si el titular o rol menciona un colegio/escuela explícito:
        if not inst:
            m_school = re.search(r'\b(Colegio|Liceo|Escuela|Instituto|Universidad|Fundaci[oó]n|Corporaci[oó]n|DAEM|SLEP)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9\s]+?)(?:\s+(?:en|at|@|–|-|\||•|·|\.|\,|$)|$)', f"{c_act} {headline}", re.IGNORECASE)
            if m_school:
                cand_school = f"{m_school.group(1)} {m_school.group(2)}".strip()
                if len(cand_school) > 5 and not is_invalid_institution(cand_school):
                    inst = cand_school

        inst = refine_pie_institution(inst, role=c_act, headline=headline, location=loc)

        if inst:
            inst = re.sub(r'[|,;·•].*$', '', inst).strip()
            inst = re.sub(r'[\/|;,\-–—]+$', '', inst).strip()
        if c_act:
            c_act = re.sub(r'[|,;·•].*$', '', c_act).strip()
            c_act = re.sub(r'[\/|;,\-–—]+$', '', c_act).strip()

        if loc == headline or len(loc) > 90:
            loc = "Chile"

        return {
            "ok": True,
            "nombre": nombre,
            "cargo_titular": headline,
            "cargo_actual": c_act or "Profesional",
            "institucion_actual": inst or "",
            "ubicacion": loc,
            "grado_red": grado
        }

    # Si Electron está activo pero llegamos aquí, no evaluar JS para evitar error 403 (C-01)
    if not browser_service.is_browseros_running():
        return {"ok": False, "error": "Chromium embebido aislado de Electron no pudo extraer el perfil"}

    # 2. Modo Legacy / BrowserOS MCP (Fallback únicamente si BrowserOS está corriendo fuera de Electron)
    browser_service.open_url(clean_url)
    time.sleep(3.2)

    # Activar lazy loading progresivo de la sección de Experiencia (IntersectionObserver en SDUI de LinkedIn)
    scroll_stage1 = """(() => {
        const ws = document.getElementById('workspace') || document.querySelector('main');
        window.scrollTo(0, 1200);
        if (ws) ws.scrollTop = 1200;
        return true;
    })()"""
    browser_service._call_mcp_evaluate(scroll_stage1)
    time.sleep(1.0)

    scroll_stage2 = """(() => {
        const ws = document.getElementById('workspace') || document.querySelector('main');
        window.scrollTo(0, 2600);
        if (ws) ws.scrollTop = 2600;
        return true;
    })()"""
    browser_service._call_mcp_evaluate(scroll_stage2)
    time.sleep(1.0)

    scroll_stage3 = """(() => {
        const ws = document.getElementById('workspace') || document.querySelector('main');
        window.scrollTo(0, 4200);
        if (ws) ws.scrollTop = 4200;

        // Si ya está experiencia presente, centrarla directamente
        const sections = Array.from(document.querySelectorAll('section'));
        for (const s of sections) {
            const h2 = s.querySelector('h2');
            const h2Text = h2 ? (h2.innerText || '').toLowerCase() : '';
            if (h2Text.includes('experiencia') || h2Text.includes('experience')) {
                s.scrollIntoView({ behavior: 'auto', block: 'center' });
                return 'found_exp_h2';
            }
        }
        return 'scrolled_stage3';
    })()"""
    browser_service._call_mcp_evaluate(scroll_stage3)
    time.sleep(2.0)

    script = r"""
    (() => {
        try {
            const url = window.location.href;
            const pageTitle = (document.title || '').trim();

            // 0. Detección estricta de 404 o página no encontrada
            if (url.includes('/404') || 
                pageTitle.toLowerCase().includes('esta página no existe') || 
                pageTitle.toLowerCase().includes('page not found') || 
                (document.body && document.body.innerText.includes('Esta página no existe'))) {
                return {
                    ok: false,
                    is_404: true,
                    error: 'Página no encontrada en LinkedIn (404)'
                };
            }

            const sections = Array.from(document.querySelectorAll('section'));

            // 1. Tarjeta principal de presentación (Intro Card)
            const introSec = sections.find(s => {
                const text = (s.innerText || '').trim();
                return text.includes('Información de contacto') || text.includes('contact info') || text.includes('contactos') || text.includes('connections');
            }) || sections[1] || sections[0];

            let name = '';
            let headline = '';
            let location = 'Chile';
            let grado = '2º';

            const isDegreeText = (t) => {
                if (!t) return false;
                const clean = t.trim();
                return /^[·•\s]*(?:1er|1º|1°|2do|2º|2°|3er|3º|3°|\d+[º°]|\d+(?:er|do|to|st|nd|rd|th))\+?[·•\s]*$/i.test(clean);
            };

            const extractDegree = (t) => {
                if (!t) return '2º';
                if (/1er|1º|1°/i.test(t)) return '1º';
                if (/2do|2º|2°/i.test(t)) return '2º';
                if (/3er|3º|3°|\+/i.test(t)) return '3º+';
                return '2º';
            };

            const isJobTitleLike = (t) => {
                if (!t) return false;
                const clean = t.trim().toLowerCase();
                const jobStarters = [
                    'director', 'directora', 'subdirector', 'subdirectora', 'gerente', 'jefe', 'jefa',
                    'coordinador', 'coordinadora', 'representante', 'encargado', 'encargada', 'profesor',
                    'profesora', 'docente', 'consultor', 'consultora', 'asesor', 'asesora', 'fundador',
                    'fundadora', 'ceo', 'rector', 'rectora', 'abogado', 'abogada', 'ingeniero', 'ingeniera'
                ];
                return jobStarters.some(starter => clean.startsWith(starter) || clean.startsWith('ex-' + starter));
            };

            if (pageTitle.includes('|')) name = pageTitle.split('|')[0].trim();
            else if (pageTitle.includes('-')) name = pageTitle.split('-')[0].trim();

            if (introSec) {
                const h2 = introSec.querySelector('h2') || introSec.querySelector('h1');
                if (h2 && (!name || name === 'LinkedIn')) name = h2.innerText.trim();

                // 1. Extraer ubicación exacta asociada al enlace de 'Información de contacto'
                const contactLink = Array.from(introSec.querySelectorAll('a')).find(a => {
                    const t = (a.innerText || '').toLowerCase();
                    return t.includes('información de contacto') || t.includes('contact info');
                });

                if (contactLink) {
                    let locContainer = contactLink.parentElement;
                    while (locContainer && locContainer !== introSec) {
                        const text = locContainer.innerText || '';
                        if (text.includes('·') || text.includes('•') || text.includes('\n')) {
                            const parts = text.split(/[\n·•]+/).map(p => p.trim()).filter(Boolean);
                            const nonContact = parts.find(p => {
                                const pLow = p.toLowerCase();
                                return !pLow.includes('información de contacto') && 
                                       !pLow.includes('contact info') && 
                                       !pLow.includes('contacto') && 
                                       !isDegreeText(p) &&
                                       !isJobTitleLike(p) &&
                                       p !== name &&
                                       p.length >= 2 && p.length < 90;
                            });
                            if (nonContact) {
                                location = nonContact;
                                break;
                            }
                        }
                        locContainer = locContainer.parentElement;
                    }
                }

                const lines = introSec.innerText.split('\n').map(l => l.trim()).filter(Boolean);

                // Fallback de ubicación si no se encontró con contactLink
                if (!location || location === 'Chile') {
                    const contactIdx = lines.findIndex(l => {
                        const low = l.toLowerCase();
                        return low.includes('información de contacto') || low.includes('contact info');
                    });
                    if (contactIdx !== -1) {
                        for (let j = contactIdx - 1; j >= 0; j--) {
                            const cand = lines[j].trim();
                            if (cand === '·' || cand === '•' || !cand || isDegreeText(cand) || cand === name || isJobTitleLike(cand)) continue;
                            if (cand.length >= 2 && cand.length < 90) {
                                location = cand;
                                break;
                            }
                        }
                    }
                }

                // Extraer grado y headline recorriendo las líneas de la tarjeta
                for (let i = 1; i < lines.length; i++) {
                    const l = lines[i];
                    if (l === '·' || l === '•') continue;
                    if (isDegreeText(l)) {
                        grado = extractDegree(l);
                        continue;
                    }
                    if (l.toLowerCase().includes('información de contacto') || 
                        l.toLowerCase().includes('contact info') || 
                        l.toLowerCase().includes('contactos en común') || 
                        l.toLowerCase().includes('connections')) {
                        break;
                    }
                    if (l === location || l === name) continue;
                    if (!headline) {
                        headline = l;
                    }
                }
            }

            if (!name || name === 'LinkedIn' || name.toLowerCase().includes('esta página no existe')) {
                const h2 = document.querySelector('main h2') || document.querySelector('h1') || document.querySelector('h2');
                if (h2) name = h2.innerText.trim();
            }

            if (name.toLowerCase().includes('esta página no existe')) {
                return { ok: false, error: 'Página no encontrada en LinkedIn (404)' };
            }

            // 2. Extraer Cargo Actual y Empresa desde la sección de EXPERIENCIA laboral en vivo
            let expRole = '';
            let expCompany = '';

            const isEmploymentType = (t) => {
                if (!t) return false;
                const clean = t.toLowerCase().trim();
                const types = [
                    'jornada completa', 'jornada parcial', 'tiempo completo', 'medio tiempo',
                    'profesional independiente', 'autónomo', 'autónoma', 'contrato temporal',
                    'contrato de prácticas', 'contrato de formación', 'de temporada', 'en prácticas',
                    'full-time', 'part-time', 'self-employed', 'freelance', 'contract', 'internship', 'seasonal'
                ];
                return types.some(type => clean === type || clean.startsWith(type + ' ·') || clean.startsWith(type + '•') || clean.startsWith(type + ' -'));
            };

            const isDuration = (t) => {
                if (!t) return false;
                const clean = t.toLowerCase().trim();
                return (clean.includes('año') || clean.includes('mes') || clean.includes('yr') || clean.includes('mo')) && 
                       /\d/.test(clean) && 
                       !clean.includes('actualidad') && !clean.includes('present');
            };

            const cleanRole = (role) => {
                if (!role) return '';
                const parts = role.split(/\s*(?:[|;•·]|\s-\s)\s*/).map(p => p.trim()).filter(Boolean);
                if (parts.length <= 1) return role.trim();
                
                const pitchKeywords = [
                    'factura', 'ayudo', 'ayudamos', 'cliente', 'metodo', 'método', 'dolar', 'dólar', 
                    'escala', 'crece', 'impacto', 'negocio', 'asesor', 'transforma', 'helping', 'scale', 
                    'revenue', 'k/mes', 'mes con', 'usd'
                ];
                
                const cleaned = [];
                for (let i = 0; i < parts.length; i++) {
                    const p = parts[i];
                    const pLower = p.toLowerCase();
                    const isPitch = p.length > 30 || pitchKeywords.some(k => pLower.includes(k));
                    if (i === 0) {
                        cleaned.push(p);
                    } else if (!isPitch) {
                        cleaned.push(p);
                    }
                }
                return cleaned.join(' | ');
            };

            const allNodes = Array.from(document.querySelectorAll('*'));
            const dateElement = allNodes.find(el => {
                if (el.children.length !== 0) return false;
                const t = (el.innerText || '').toLowerCase().trim();
                return (t.includes('actualidad') || t.includes(' - present') || t.includes('presente')) && 
                       (t.includes('año') || t.includes('mes') || t.includes('year') || t.includes('month') || t.includes('20'));
            });

            if (dateElement) {
                let jobContainer = dateElement.parentElement;
                while (jobContainer && !jobContainer.innerText.includes('\n') && jobContainer.parentElement) {
                    jobContainer = jobContainer.parentElement;
                }
                if (jobContainer) {
                    const lines = jobContainer.innerText.split('\n').map(l => l.trim()).filter(Boolean);
                    const dateIdx = lines.findIndex(l => l.toLowerCase().includes('actualidad') || l.toLowerCase().includes('present') || l.toLowerCase().includes('presente'));
                    
                    expRole = cleanRole(lines[0]);

                    if (dateIdx >= 2 && !isEmploymentType(lines[1])) {
                        expCompany = lines[1].replace(/[·•|;].*$/, '').trim();
                    }

                    // Si expCompany no se encontró o era un tipo de jornada ("Jornada completa", "Full-time"),
                    // buscar en la jerarquía superior (estructura multi-cargo de LinkedIn)
                    if (!expCompany || isEmploymentType(expCompany)) {
                        expCompany = '';
                        let curr = jobContainer.parentElement;
                        while (curr && curr.tagName !== 'SECTION' && curr.tagName !== 'MAIN') {
                            const pLines = curr.innerText.split('\n').map(l => l.trim()).filter(Boolean);
                            if (pLines.length >= 2 && pLines[0] !== lines[0] && pLines[0] !== 'Experiencia' && !isEmploymentType(pLines[0])) {
                                if (isDuration(pLines[1]) || pLines[1] === lines[0] || isEmploymentType(pLines[1])) {
                                    expCompany = pLines[0].replace(/[·•|;].*$/, '').trim();
                                    break;
                                }
                            }
                            curr = curr.parentElement;
                        }
                    }
                }
            }

            // Fallback directo a la sección con h2 'Experiencia' si dateElement no resolvió
            if (!expRole || !expCompany) {
                const expSec = sections.find(s => {
                    const h2 = s.querySelector('h2');
                    return h2 && (h2.innerText || '').toLowerCase().includes('experiencia');
                }) || document.getElementById('experience')?.closest('section');
                
                if (expSec) {
                    const sLines = expSec.innerText.split('\n').map(l => l.trim()).filter(Boolean);
                    const expTitleIdx = sLines.findIndex(l => l.toLowerCase() === 'experiencia' || l.toLowerCase() === 'experience');
                    const relevantLines = expTitleIdx !== -1 ? sLines.slice(expTitleIdx + 1) : sLines;
                    if (relevantLines.length >= 2) {
                        if (!expRole) expRole = cleanRole(relevantLines[0]);
                        if (!expCompany && !isEmploymentType(relevantLines[1])) {
                            expCompany = relevantLines[1].replace(/[·•|;].*$/, '').trim();
                        }
                    }
                }
            }

            // 3. Fallbacks de Headline y Ubicación si no se extrajeron de la tarjeta intro
            if (!headline || !location || location === 'Chile') {
                const allElements = Array.from(document.querySelectorAll('main h1, main h2, main h3, main p, main span, main a, div[data-sdui-screen] p, div[data-sdui-screen] span'))
                    .filter(el => el.children.length === 0 && (el.innerText || '').trim().length > 0)
                    .map(el => el.innerText.trim());

                const isExcluded = (t) => {
                    if (!t) return true;
                    if (t === name) return true;
                    if (t.startsWith('·') || t.startsWith('•')) return true;
                    if (isDegreeText(t)) return true;
                    if (t.includes('contacto') || t.includes('seguidor') || t.includes('más en común')) return true;
                    if (isEmploymentType(t)) return true;
                    if (['Información de contacto', 'Enviar mensaje', 'Enviar', 'Más', 'Seguir', 'Conectar', 'Guardar', 'Recomendar'].includes(t)) return true;
                    return false;
                };

                const cleanItems = allElements.filter(t => !isExcluded(t));

                if (!headline) {
                    for (const t of cleanItems) {
                        if (t.length >= 3 && t.length <= 250 && t !== expRole && t !== expCompany && !isJobTitleLike(t)) {
                            headline = t;
                            break;
                        }
                    }
                }

                if (!location || location === 'Chile') {
                    for (const t of cleanItems) {
                        if (t === headline || t === name || t === expRole || t === expCompany) continue;
                        if (isJobTitleLike(t)) continue;
                        if ((t === 'Chile' || t.startsWith('Chile') || t.includes('Santiago') || t.includes('Región') || t.includes('Valparaíso') || t.includes('Concepción') || t.includes('Antofagasta')) && t.length < 80) {
                            location = t.replace(/[·•|;].*$/, '').trim();
                            break;
                        }
                    }
                }
            }

            return {
                ok: true,
                nombre: name,
                headline: headline,
                expRole: expRole,
                expCompany: expCompany,
                location: location,
                grado: grado,
                url: url
            };
        } catch (e) {
            return { ok: false, error: e.message };
        }
    })()
    """

    res = browser_service._call_mcp_evaluate(script)
    if isinstance(res, dict) and res.get("ok"):
        res_data = res.get("result") if "result" in res and isinstance(res.get("result"), dict) else res
        if not res_data.get("ok"):
            return {"ok": False, "error": res_data.get("error", "Error extrayendo datos del perfil")}

        nombre = res_data.get("nombre") or ""
        if "esta página no existe" in nombre.lower():
            return {"ok": False, "error": "Página no encontrada en LinkedIn (404)"}

        exp_role = res_data.get("expRole", "")
        exp_company = res_data.get("expCompany", "")
        headline = res_data.get("headline", "")
        loc = res_data.get("location") or "Chile"
        grado = res_data.get("grado") or "2°"

        # Validar si el rol o la empresa obtenidos de la página principal son inválidos (p. ej. habilidades o voluntariados)
        if exp_role and is_invalid_role(exp_role):
            exp_role = ""
        if exp_company and is_invalid_institution(exp_company):
            exp_company = ""

        # Si falta el cargo/empresa, o si la empresa es genérica tipo PIE o voluntariado, inspeccionar /details/experience/
        need_details = False
        if not exp_role or is_invalid_role(exp_role):
            need_details = True
        if not exp_company or is_invalid_institution(exp_company):
            need_details = True
        if exp_company and re.search(r'^(?:programa\s+(?:de\s+)?integraci[oó]n\s+escolar|p\.?i\.?e\.?)\b', exp_company, re.IGNORECASE):
            need_details = True

        if need_details:
            exp_url = clean_url + "details/experience/"
            browser_service.open_url(exp_url)
            time.sleep(3.2)
            det_res = browser_service._call_mcp_evaluate(EXTRACT_DETAILS_EXP_JS)
            if isinstance(det_res, dict) and det_res.get("ok"):
                det_data = det_res.get("result") if "result" in det_res and isinstance(det_res.get("result"), dict) else det_res
                first_entry = det_data.get("firstEntry")
                if first_entry:
                    det_role = first_entry.get("role", "")
                    det_company = first_entry.get("company", "")
                    det_loc = first_entry.get("location", "")
                    if det_role and not is_invalid_role(det_role):
                        exp_role = det_role
                    if det_company and not is_invalid_institution(det_company):
                        exp_company = det_company
                    if det_loc and (not loc or loc in ["Chile", "Área metropolitana de Santiago", "Gran Santiago", "Santiago"] or len(det_loc) > len(loc)):
                        loc = det_loc

        # Parsear con lead_parser usando ubicación y filtros
        if exp_role and not is_invalid_role(exp_role):
            c_act, inst = parse_cargo_and_institucion(exp_role, default_institucion=exp_company, location=loc)
        else:
            c_act, inst = parse_cargo_and_institucion(headline, default_institucion=exp_company, location=loc)

        if not inst and headline:
            match_en = re.search(r'\s+(?:en|at|@)\s+([^|;•·\n\–\—]+)', headline, re.IGNORECASE)
            if match_en and not is_invalid_institution(match_en.group(1).strip()):
                inst = match_en.group(1).strip()

        # Si aún no hay institución pero exp_company viene de LinkedIn, usarla directamente
        if not inst and exp_company and not is_invalid_institution(exp_company):
            inst = exp_company.strip()

        # Si el titular o rol menciona un colegio/escuela explícito:
        if not inst:
            m_school = re.search(r'\b(Colegio|Liceo|Escuela|Instituto|Universidad|Fundaci[oó]n|Corporaci[oó]n|DAEM|SLEP)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9\s]+?)(?:\s+(?:en|at|@|–|-|\||•|·|\.|\,|$)|$)', f"{c_act} {headline}", re.IGNORECASE)
            if m_school:
                cand_school = f"{m_school.group(1)} {m_school.group(2)}".strip()
                if len(cand_school) > 5 and not is_invalid_institution(cand_school):
                    inst = cand_school

        inst = refine_pie_institution(inst, role=c_act, headline=headline, location=loc)

        if inst:
            inst = re.sub(r'[|,;·•].*$', '', inst).strip()
            inst = re.sub(r'[\/|;,\-–—]+$', '', inst).strip()
        if c_act:
            c_act = re.sub(r'[|,;·•].*$', '', c_act).strip()
            c_act = re.sub(r'[\/|;,\-–—]+$', '', c_act).strip()

        if loc == headline or len(loc) > 90:
            loc = "Chile"

        return {
            "ok": True,
            "nombre": nombre,
            "cargo_titular": headline,
            "cargo_actual": c_act or "Profesional",
            "institucion_actual": inst or "",
            "ubicacion": loc,
            "grado_red": grado
        }
    return {"ok": False, "error": res.get("error", "No se pudo leer el DOM del perfil") if isinstance(res, dict) else str(res)}



