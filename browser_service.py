import os
import re
import json
import subprocess
import threading
import urllib.request
import urllib.error
from typing import List, Optional

BROWSERCLAW_EXE = r"C:\Users\gabri\AppData\Local\BrowserClaw\Application\chrome.exe"
BROWSERCLAW_SHORTCUT = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\BrowserOS neo.lnk")
MCP_URL = "http://127.0.0.1:9010/mcp"
ELECTRON_BASE_URL = "http://127.0.0.1:9099"

URL_LINKEDIN = "https://www.linkedin.com/feed/"
URL_ZOHO_CRM = "https://crm.zoho.com/crm/org902879914/tab/Home"

def get_electron_status() -> dict:
    """Consulta el estado detallado de Electron (sesión de LinkedIn, sesión de WhatsApp, cookies, visibilidad)."""
    try:
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as res:
            if res.status == 200:
                return json.loads(res.read().decode("utf-8"))
    except Exception:
        pass
    return {"ok": False, "running": False, "sesion_linkedin_activa": False, "sesion_whatsapp_activa": False}

def is_electron_running() -> bool:
    """Verifica si el contenedor de escritorio Electron (Chromium aislado) está en ejecución."""
    status = get_electron_status()
    return bool(status.get("ok"))

def verify_linkedin_session() -> bool:
    """Verifica si la sesión de LinkedIn está autenticada en Electron."""
    if is_electron_running():
        status = get_electron_status()
        return bool(status.get("sesion_linkedin_activa"))
    return False

def verify_whatsapp_session() -> bool:
    """Verifica si la sesión de WhatsApp Web está autenticada en Electron."""
    if is_electron_running():
        status = get_electron_status()
        return bool(status.get("sesion_whatsapp_activa"))
    return False

def verify_zoho_session() -> bool:
    """Verifica si la sesión de Zoho CRM está autenticada en Electron."""
    if is_electron_running():
        status = get_electron_status()
        return bool(status.get("sesion_zoho_activa"))
    return False

def start_electron_worker(session_token: Optional[str] = None, tenant_id: Optional[str] = None) -> dict:
    """Instruye al runner de fondo en Electron para que inicie su ciclo autónomo con la sesión autenticada."""
    try:
        payload = {}
        if session_token:
            payload["session_token"] = session_token
        if tenant_id:
            payload["tenant_id"] = tenant_id
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/start", data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=2.0) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def stop_electron_worker() -> dict:
    """Instruye al runner de fondo en Electron para que pause su ciclo autónomo."""
    try:
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/stop", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=2.0) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def sync_electron_worker_session(session_token: Optional[str] = None, tenant_id: Optional[str] = None) -> dict:
    """Sincroniza el contexto de sesión autenticada con el runner de Electron sin alterar su estado de pausa."""
    try:
        payload = {
            "session_token": session_token,
            "tenant_id": tenant_id
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/session", data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=1.5) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def clear_electron_worker_session() -> dict:
    """Invalida la sesión activa en el runner de Electron y detiene el polling inmediatamente."""
    try:
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/logout", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=1.5) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def force_electron_worker_next(session_token: Optional[str] = None, tenant_id: Optional[str] = None) -> dict:
    """Fuerza al bucle del runner en Electron a omitir la espera y ejecutar de inmediato el próximo ciclo."""
    try:
        payload = {}
        if session_token:
            payload["session_token"] = session_token
        if tenant_id:
            payload["tenant_id"] = tenant_id
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/forzar-siguiente", data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        try:
            stop_res = stop_electron_worker()
            start_res = start_electron_worker(session_token=session_token, tenant_id=tenant_id)
            return {"ok": True, "method": "restart_fallback", "stop": stop_res, "start": start_res}
        except Exception as e2:
            return {"ok": False, "error": f"Fallo principal ({e}) y fallback ({e2})"}

def get_electron_worker_status() -> dict:
    """Consulta el estado actual del bucle del runner autónomo de Electron."""
    try:
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/worker/status", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e), "status": {"activo": False, "estado_actual": "En reposo"}}

def is_browseros_running() -> bool:
    """Verifica si Chromium embebido (Electron) o BrowserOS están en ejecución."""
    if is_electron_running():
        return True

    try:
        # Check HTTP port 9010 (BrowserOS Fallback)
        req = urllib.request.Request(MCP_URL, method="GET")
        try:
            urllib.request.urlopen(req, timeout=0.8)
        except urllib.error.HTTPError as e:
            if e.code in (400, 406):
                return True
        except Exception:
            pass
        
        # Windows process check fallback
        output = subprocess.check_output(
            ["tasklist", "/fi", "imagename eq browseros-claw-server.exe"],
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        return "browseros-claw-server.exe" in output
    except Exception:
        return False

def _call_mcp_tabs_new(url: str):
    """Invoca la API MCP de BrowserOS para abrir una pestaña en segundo plano."""
    try:
        # 1. Initialize MCP session
        init_payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nexusreach-local", "version": "1.0"}
            }
        }).encode("utf-8")

        req_init = urllib.request.Request(
            MCP_URL,
            data=init_payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )
        with urllib.request.urlopen(req_init, timeout=2.5) as res_init:
            session_id = res_init.headers.get("mcp-session-id")

        if not session_id:
            return False

        # 2. Notify initialized
        notify_payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }).encode("utf-8")
        req_notify = urllib.request.Request(
            MCP_URL,
            data=notify_payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id
            }
        )
        try:
            urllib.request.urlopen(req_notify, timeout=1.5)
        except Exception:
            pass

        # 3. Invoke tabs action='new'
        call_payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "tabs",
                "arguments": {
                    "action": "new",
                    "url": url,
                    "agentName": "dripify"
                }
            }
        }).encode("utf-8")
        req_call = urllib.request.Request(
            MCP_URL,
            data=call_payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id
            }
        )
        try:
            urllib.request.urlopen(req_call, timeout=3.0)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[BrowserService] Error invocando MCP tabs: {e}")
        return False

def open_url(url: str, force: bool = False) -> dict:
    """
    Abre una URL en el navegador de trabajo activo.
    Si Electron está activo (Chromium embebido), navega internamente.
    Si BrowserOS está activo, envía la petición de navegación vía MCP.
    """
    if is_electron_running():
        try:
            if not force:
                status = get_electron_status()
                current_raw = (status.get("url") or "").rstrip("/")
                target_raw = (url or "").rstrip("/")

                # Solo para perfiles individuales (/in/) ignoramos parámetros de tracking como ?miniProfileUrn=...
                # Para búsquedas (/search/) o cualquier otra URL, los parámetros query (keywords, etc.) son esenciales
                is_already_there = False
                if "/in/" in target_raw.lower() and "/search/" not in target_raw.lower():
                    current_base = current_raw.split("?")[0].rstrip("/")
                    target_base = target_raw.split("?")[0].rstrip("/")
                    is_already_there = bool(current_base and target_base and current_base == target_base)
                else:
                    is_already_there = bool(current_raw and target_raw and current_raw == target_raw)

                if is_already_there:
                    return {
                        "status": "ok",
                        "metodo": "electron_isolated_current",
                        "mensaje": f"Pestaña ya posicionada en: {url}",
                        "url": url
                    }

            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/navigate",
                data=json.dumps({"url": url}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=18.0) as res:
                return {
                    "status": "ok",
                    "metodo": "electron_isolated",
                    "mensaje": f"Pestaña navegada en Chromium Embebido: {url}",
                    "url": url
                }
        except Exception as e:
            print(f"[BrowserService] Error navegando en Electron: {e}")

    if is_browseros_running():
        threading.Thread(target=_call_mcp_tabs_new, args=(url,), daemon=True).start()
        return {
            "status": "ok",
            "metodo": "mcp",
            "mensaje": f"Pestaña abierta en BrowserOS: {url}",
            "url": url
        }
    else:
        # Fallback to launch BrowserOS
        if os.path.exists(BROWSERCLAW_EXE):
            subprocess.Popen([BROWSERCLAW_EXE, url])
            return {
                "status": "ok",
                "metodo": "launch",
                "mensaje": f"Iniciando BrowserOS con {url}",
                "url": url
            }
        elif os.path.exists(BROWSERCLAW_SHORTCUT):
            os.startfile(BROWSERCLAW_SHORTCUT)
            return {
                "status": "ok",
                "metodo": "shortcut",
                "mensaje": "Iniciando BrowserOS mediante acceso directo",
                "url": url
            }
        else:
            return {
                "status": "error",
                "mensaje": "No se encontró el ejecutable de BrowserOS",
                "url": url
            }

def start_work_sessions(urls: Optional[List[str]] = None) -> dict:
    """
    Inicia o activa el navegador de trabajo abriendo pestañas para LinkedIn y Zoho CRM.
    """
    targets = urls or [URL_LINKEDIN, URL_ZOHO_CRM]
    
    if is_browseros_running():
        for u in targets:
            threading.Thread(target=_call_mcp_tabs_new, args=(u,), daemon=True).start()
        return {
            "status": "ok",
            "activo_previo": True,
            "mensaje": "BrowserOS ya estaba activo. Se abrieron pestañas de LinkedIn y Zoho CRM.",
            "urls": targets
        }
    else:
        if os.path.exists(BROWSERCLAW_EXE):
            cmd = [BROWSERCLAW_EXE] + targets
            subprocess.Popen(cmd)
            return {
                "status": "ok",
                "activo_previo": False,
                "mensaje": "BrowserOS iniciado exitosamente con sesiones de LinkedIn y Zoho CRM.",
                "urls": targets
            }
        elif os.path.exists(BROWSERCLAW_SHORTCUT):
            os.startfile(BROWSERCLAW_SHORTCUT)
            return {
                "status": "ok",
                "activo_previo": False,
                "mensaje": "BrowserOS iniciado mediante acceso directo del sistema.",
                "urls": targets
            }
        else:
            return {
                "status": "error",
                "mensaje": "No se localizó el ejecutable de BrowserOS en AppData."
            }

# ==========================================
# SYNCHRONOUS MCP CLIENT (NAVIGATION AND EVALUATE FOR SEQUENCES)
# ==========================================
_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_work_page_id: Optional[int] = None

def _mcp_open_session() -> Optional[str]:
    """Inicializa una sesión MCP y retorna el identificador de sesión."""
    init_payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "nexusreach-local", "version": "1.0"}}
    }).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=init_payload, headers=_MCP_HEADERS)
    with urllib.request.urlopen(req, timeout=2.5) as res:
        session_id = res.headers.get("mcp-session-id")
    if not session_id:
        return None
    notify = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
    try:
        urllib.request.urlopen(urllib.request.Request(
            MCP_URL, data=notify, headers={**_MCP_HEADERS, "mcp-session-id": session_id}), timeout=1.5)
    except Exception:
        pass
    return session_id

def _mcp_tool_text(session_id: str, tool: str, arguments: dict, timeout: float = 10.0) -> str:
    """Invoca una herramienta MCP y retorna la respuesta de texto concatenada."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": {"agentName": "nexusreach", **arguments}}
    }).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=payload, headers={**_MCP_HEADERS, "mcp-session-id": session_id})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode("utf-8", errors="ignore")

    text_list = []
    blocks = [l[6:] for l in raw.split("\n") if l.startswith("data: ")] or [raw]
    for block in blocks:
        try:
            data = json.loads(block)
        except Exception:
            continue
        if data.get("error"):
            text_list.append(f"ERROR: {data['error'].get('message', data['error'])}")
        for content in (data.get("result") or {}).get("content", []):
            if content.get("type") == "text":
                text_list.append(content.get("text", ""))
    return "\n".join(text_list)

def _unwrap_untrusted(txt: str) -> str:
    """Remueve la envoltura [UNTRUSTED_PAGE_CONTENT ...] añadida por BrowserOS."""
    m = re.search(r'\[UNTRUSTED_PAGE_CONTENT[^\]]*\][^\n]*\n([\s\S]*?)\[END_UNTRUSTED_PAGE_CONTENT', txt)
    return m.group(1).strip() if m else txt.strip()

def open_profile_in_browseros(profile_url: str, name: str = "") -> dict:
    """
    Navega la pestaña de trabajo al perfil indicado.
    Si Electron está activo, navega en su Chromium embebido aislado.
    Si BrowserOS está activo, navega vía MCP.
    """
    global _work_page_id
    if not profile_url:
        return {"status": "error", "detail": "URL de perfil vacía"}

    # 1. Primary: Electron Embedded Chromium
    if is_electron_running():
        try:
            status = get_electron_status()
            current_url = status.get("url", "").split("?")[0].rstrip("/")
            target_clean = profile_url.split("?")[0].rstrip("/")
            if current_url and current_url == target_clean:
                return {"status": "ok", "tipo": "electron_isolated_current", "url": profile_url}

            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/navigate",
                data=json.dumps({"url": profile_url}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=18.0) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("ok"):
                    return {"status": "ok", "tipo": "electron_isolated", "url": profile_url}
        except Exception as e:
            return {"status": "error", "detail": f"Fallo navegando en Electron: {e}"}

    # 2. Fallback: BrowserOS MCP
    if not is_browseros_running():
        return {"status": "error", "detail": "Ni Electron ni BrowserOS están en ejecución."}

    try:
        session_id = _mcp_open_session()
        if not session_id:
            return {"status": "error", "detail": "No se obtuvo session-id de BrowserOS MCP"}

        if _work_page_id is not None:
            txt = _mcp_tool_text(session_id, "navigate", {"page": _work_page_id, "url": profile_url}, timeout=15.0)
            if not txt.startswith("ERROR") and "error" not in txt.lower()[:80]:
                return {"status": "ok", "page_id": _work_page_id, "metodo": "navigate"}
            _work_page_id = None

        txt = _mcp_tool_text(session_id, "tabs", {"action": "new", "url": profile_url}, timeout=15.0)
        m = re.search(r'(?:opened page|page)\s*(\d+)', txt, re.IGNORECASE)
        if not m:
            return {"status": "error", "detail": f"No se pudo abrir la pestaña: {txt[:200]}"}
        _work_page_id = int(m.group(1))
        return {"status": "ok", "page_id": _work_page_id, "metodo": "tabs_new"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

def _call_mcp_evaluate(script: str, page_id: Optional[int] = None, channel: Optional[str] = None) -> dict:
    """
    Ejecuta JavaScript únicamente en entornos BrowserOS locales de desarrollo legacy vía MCP.
    En Electron (Chromium aislado), la evaluación arbitraria de JavaScript está bloqueada por directriz C-01.
    """
    if is_electron_running():
        # Regla C-01 / Directrices v1.3: La evaluación remota arbitraria en Electron está revocada
        return {
            "ok": False,
            "error": "ACCESO_DENEGADO (C-01): La evaluación remota arbitraria de JavaScript en Electron está revocada. Use funciones precompiladas locales o comandos firmados Ed25519."
        }

    target = page_id if page_id is not None else _work_page_id
    if target is None:
        return {"ok": False, "error": "No hay pestaña de trabajo activa en BrowserOS"}

    code = script.strip()
    if not re.match(r'^(async\s*)?(\([^)]*\)|\w+)\s*=>|^(async\s+)?function\b', code):
        code = f"() => ({code})"
    try:
        session_id = _mcp_open_session()
        if not session_id:
            return {"ok": False, "error": "No se obtuvo session-id de BrowserOS MCP"}
        txt = _unwrap_untrusted(_mcp_tool_text(session_id, "evaluate", {"page": target, "func": code}, timeout=15.0))
        if txt.startswith("ERROR"):
            return {"ok": False, "error": txt}
        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, dict) else {"ok": True, "value": parsed}
        except Exception:
            return {"ok": True, "raw": txt}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def show_work_browser(url: Optional[str] = None, channel: Optional[str] = None) -> dict:
    """Muestra la ventana de Chromium embebido en Electron para login o monitoreo visual."""
    if is_electron_running():
        try:
            body = {}
            if url:
                body["url"] = url
            if channel:
                body["channel"] = channel
            elif url and "whatsapp" in url.lower():
                body["channel"] = "whatsapp"
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(f"{ELECTRON_BASE_URL}/show", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Electron no está activo"}

def extract_network_from_electron(source: str = "all", limit: int = 50) -> dict:
    """
    Invoca la extracción precompilada segura de red en Chromium (Electron).
    source: 'all', 'connections', o 'sent_invitations'.
    limit: Cantidad objetivo de contactos a extraer de la cola (default 50).
    """
    if is_electron_running():
        try:
            body = json.dumps({"source": source, "limit": limit}).encode("utf-8")
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/extract/network",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e), "leads": []}
    return {"success": False, "error": "Electron no está activo", "leads": []}

def enrich_profile_from_electron(profile_url: str) -> dict:
    """
    Invoca la extracción y enriquecimiento precompilado seguro de perfil en vivo en Chromium (Electron).
    profile_url: URL pública o directa del perfil de LinkedIn.
    """
    if is_electron_running():
        try:
            body = json.dumps({"profile_url": profile_url}).encode("utf-8")
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/extract/profile",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=45.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "success": False, "error": str(e)}
    return {"ok": False, "success": False, "error": "Electron no está activo"}

def extract_contact_info_from_electron(profile_url: str) -> dict:
    """
    Invoca la extracción precompilada segura de información de contacto de 1er grado (overlay) en Electron.
    profile_url: URL del perfil de LinkedIn.
    """
    if is_electron_running():
        try:
            body = json.dumps({"profile_url": profile_url}).encode("utf-8")
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/extract/contact-info",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Electron no está activo"}

def search_people_from_electron(term: str, page: int = 1) -> dict:
    """
    Invoca la búsqueda y extracción precompilada segura de personas en LinkedIn en Chromium (Electron).
    term: Término de búsqueda (ej. 'Director', 'CEO').
    page: Número de página (1 a 20).
    """
    if is_electron_running():
        try:
            body = json.dumps({"term": term, "page": page}).encode("utf-8")
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/extract/search",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e), "leads": []}
    return {"success": False, "error": "Electron no está activo", "leads": []}

def hide_work_browser(channel: Optional[str] = None) -> dict:
    """Oculta la ventana de Chromium embebido en Electron."""
    if is_electron_running():
        try:
            body = {"channel": channel} if channel else {}
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(f"{ELECTRON_BASE_URL}/hide", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Electron no está activo"}

def logout_zoho() -> dict:
    """Cierra la sesión de Zoho CRM, purga cookies/almacenamiento y regresa al formulario de acceso."""
    if is_electron_running():
        try:
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/zoho/logout",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception:
            # Fallback inmediato si el proceso de Electron es previo al hot-update del endpoint
            try:
                clear_js = """
                (() => {
                    try {
                        document.cookie.split(';').forEach(c => {
                            const eq = c.indexOf('=');
                            const name = eq > -1 ? c.substring(0, eq).trim() : c.trim();
                            document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.zoho.com';
                            document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=crm.zoho.com';
                            document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=accounts.zoho.com';
                            document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;';
                        });
                        localStorage.clear();
                        sessionStorage.clear();
                    } catch(e) {}
                    window.location.href = 'https://accounts.zoho.com/signin?servicename=ZohoCRM';
                    return { ok: true };
                })()
                """
                _call_mcp_evaluate(clear_js, channel="zoho")
                
                # 2. Navegar a logout de Zoho Accounts para matar la sesión SSO del servidor
                try:
                    nav_logout = json.dumps({"channel": "zoho", "url": "https://accounts.zoho.com/logout"}).encode("utf-8")
                    req1 = urllib.request.Request(f"{ELECTRON_BASE_URL}/navigate", data=nav_logout, headers={"Content-Type": "application/json"}, method="POST")
                    urllib.request.urlopen(req1, timeout=8.0)
                except Exception:
                    pass

                # 3. Navegar a la pantalla oficial de signin
                try:
                    nav_signin = json.dumps({"channel": "zoho", "url": "https://accounts.zoho.com/signin?servicename=ZohoCRM"}).encode("utf-8")
                    req2 = urllib.request.Request(f"{ELECTRON_BASE_URL}/navigate", data=nav_signin, headers={"Content-Type": "application/json"}, method="POST")
                    urllib.request.urlopen(req2, timeout=8.0)
                except Exception:
                    pass

                try:
                    show_body = json.dumps({"channel": "zoho"}).encode("utf-8")
                    req_show = urllib.request.Request(f"{ELECTRON_BASE_URL}/show", data=show_body, headers={"Content-Type": "application/json"}, method="POST")
                    urllib.request.urlopen(req_show, timeout=3.0)
                except Exception:
                    pass

                return {"ok": True, "fallback": True, "mensaje": "Sesión de Zoho reiniciada exitosamente"}
            except Exception as eval_err:
                return {"ok": False, "error": str(eval_err)}
    return {"ok": False, "error": "Electron no está activo"}

