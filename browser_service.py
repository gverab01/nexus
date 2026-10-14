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
URL_ZOHO_CRM = "https://crm.zoho.com/crm/org902879914/tab/Leads"

def get_electron_status() -> dict:
    """Queries detailed Electron status (LinkedIn session, cookies, visibility)."""
    try:
        req = urllib.request.Request(f"{ELECTRON_BASE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as res:
            if res.status == 200:
                return json.loads(res.read().decode("utf-8"))
    except Exception:
        pass
    return {"ok": False, "running": False, "sesion_linkedin_activa": False}

def is_electron_running() -> bool:
    """Verifies whether the Electron desktop container (Isolated Chromium) is running."""
    status = get_electron_status()
    return bool(status.get("ok"))

def verify_linkedin_session() -> bool:
    """Verifies whether LinkedIn is authenticated in Electron."""
    if is_electron_running():
        status = get_electron_status()
        return bool(status.get("sesion_linkedin_activa"))
    return False

def is_browseros_running() -> bool:
    """Verifies whether embedded Chromium (Electron) or BrowserOS are running."""
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
    """Calls BrowserOS MCP API to open a background tab."""
    try:
        # 1. Initialize MCP session
        init_payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dripify-local", "version": "1.0"}
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

def open_url(url: str) -> dict:
    """
    Opens URL in the active work browser.
    If Electron is active (embedded Chromium), navigates internally.
    If BrowserOS is active, sends navigation request via MCP.
    """
    if is_electron_running():
        try:
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/navigate",
                data=json.dumps({"url": url}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12.0) as res:
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
    Initiates or activates BrowserOS by opening work tabs for LinkedIn and Zoho CRM.
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
    """Initializes an MCP session and returns session-id."""
    init_payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "dripify-local", "version": "1.0"}}
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
    """Invokes an MCP tool and returns concatenated response text."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": {"agentName": "dripify", **arguments}}
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
    """Removes [UNTRUSTED_PAGE_CONTENT ...] wrapper added by BrowserOS."""
    m = re.search(r'\[UNTRUSTED_PAGE_CONTENT[^\]]*\][^\n]*\n([\s\S]*?)\[END_UNTRUSTED_PAGE_CONTENT', txt)
    return m.group(1).strip() if m else txt.strip()

def open_profile_in_browseros(profile_url: str, name: str = "") -> dict:
    """
    Navigates work tab to the specified profile.
    If Electron is active, navigates in its isolated embedded Chromium.
    If BrowserOS is active, navigates via MCP.
    """
    global _work_page_id
    if not profile_url:
        return {"status": "error", "detail": "URL de perfil vacía"}

    # 1. Primary: Electron Embedded Chromium
    if is_electron_running():
        try:
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/navigate",
                data=json.dumps({"url": profile_url}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15.0) as res:
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

def _call_mcp_evaluate(script: str, page_id: Optional[int] = None) -> dict:
    """
    Executes JavaScript in the work browser and returns parsed result.
    If Electron is active, executes directly in embedded Chromium.
    If BrowserOS is active, executes via MCP.
    """
    if is_electron_running():
        try:
            req = urllib.request.Request(
                f"{ELECTRON_BASE_URL}/evaluate",
                data=json.dumps({"script": script}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15.0) as res:
                data = json.loads(res.read().decode("utf-8"))
                if data.get("ok"):
                    res_val = data.get("result")
                    return res_val if isinstance(res_val, dict) else {"ok": True, "value": res_val}
                return {"ok": False, "error": data.get("error", "Error desconocido en Electron")}
        except Exception as e:
            return {"ok": False, "error": f"Fallo evaluando en Electron: {e}"}

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

def show_work_browser(url: Optional[str] = None) -> dict:
    """Shows the embedded Chromium window in Electron for login or visual monitoring."""
    if is_electron_running():
        try:
            payload = json.dumps({"url": url} if url else {}).encode("utf-8")
            req = urllib.request.Request(f"{ELECTRON_BASE_URL}/show", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Electron no está activo"}

def hide_work_browser() -> dict:
    """Hides the embedded Chromium window in Electron."""
    if is_electron_running():
        try:
            req = urllib.request.Request(f"{ELECTRON_BASE_URL}/hide", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Electron no está activo"}

# ==========================================
# BACKWARD COMPATIBILITY ALIASES
# ==========================================
obtener_estado_electron = get_electron_status
verificar_sesion_linkedin = verify_linkedin_session
abrir_perfil_en_browseros = open_profile_in_browseros
abrir_url = open_url
iniciar_sesiones_trabajo = start_work_sessions
mostrar_navegador_trabajo = show_work_browser
ocultar_navegador_trabajo = hide_work_browser
call_mcp_evaluate = _call_mcp_evaluate
