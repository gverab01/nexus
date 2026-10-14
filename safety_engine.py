import os
import re
import json
import random
import time
import subprocess
import socket
from datetime import datetime, date
from typing import Dict, Any, Optional, Tuple
from database import get_db

# ==============================================================================
# CENTRALIZED SAFETY & ANTI-BAN PROTECTION ENGINE (NexusReach Pro)
# ==============================================================================

def get_all_safety_config(conn=None) -> Dict[str, str]:
    """Obtains all safety parameters configured in SQLite."""
    query = "SELECT clave, valor FROM configuracion_seguridad"
    if conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        return {r["clave"]: r["valor"] for r in rows}
    else:
        with get_db() as c:
            cursor = c.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return {r["clave"]: r["valor"] for r in rows}

def set_safety_config_val(key: str, value: str, conn=None) -> bool:
    """Updates a safety configuration value."""
    now_iso = datetime.now().isoformat()
    query = """
        UPDATE configuracion_seguridad 
        SET valor = ?, updated_at = ?
        WHERE clave = ?
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (str(value), now_iso, key))
    else:
        with get_db() as c:
            cursor = c.cursor()
            cursor.execute(query, (str(value), now_iso, key))
    return True

# ==============================================================================
# 1. BUSINESS HOURS CONTROL (Monday to Friday, Safe Window)
# ==============================================================================

def check_business_hours(config: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
    """
    Verifies if current time is within safe business hours.
    Returns (is_valid_hour, reason).
    """
    cfg = config or get_all_safety_config()
    
    # If restriction is deactivated for testing
    if cfg.get("horario_laboral_activo", "1") == "0":
        return True, "Restricción de horario desactivada por configuración."

    now = datetime.now()
    weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    
    if weekday >= 5:
        day_name = "Sábado" if weekday == 5 else "Domingo"
        return False, f"Fin de semana ({day_name}): Campañas de prospección y correos B2B no deben enviarse fuera de días hábiles."

    start_str = cfg.get("horario_inicio", "09:00")
    end_str = cfg.get("horario_fin", "18:00")
    
    try:
        t_start = datetime.strptime(start_str, "%H:%M").time()
        t_end = datetime.strptime(end_str, "%H:%M").time()
    except Exception:
        t_start = datetime.strptime("09:00", "%H:%M").time()
        t_end = datetime.strptime("18:00", "%H:%M").time()

    current_t = now.time()
    if current_t < t_start or current_t > t_end:
        return False, f"Fuera de horario laboral comercial ({now.strftime('%H:%M')}). Ventana permitida: {start_str} a {end_str}."

    return True, f"En horario laboral permitido ({now.strftime('%H:%M')})."

# ==============================================================================
# 2. GAUSSIAN STOCHASTIC JITTER (Human Pauses)
# ==============================================================================

def calculate_gaussian_delay(min_sec: Optional[float] = None, max_sec: Optional[float] = None, config: Optional[Dict[str, str]] = None) -> float:
    """
    Calculates a stochastic pause with a truncated Gaussian (normal) distribution.
    Prevents fixed or uniform intervals that reveal bot automation.
    """
    cfg = config or get_all_safety_config()
    min_s = float(min_sec or cfg.get("pausa_linkedin_min_seg", "180"))
    max_s = float(max_sec or cfg.get("pausa_linkedin_max_seg", "360"))
    
    mu = (min_s + max_s) / 2.0
    sigma = (max_s - min_s) / 6.0
    
    delay = random.gauss(mu, sigma)
    final_delay = max(min_s, min(max_s, delay))
    return round(final_delay, 2)

def calculate_email_delay(config: Optional[Dict[str, str]] = None) -> float:
    """Calculates extended delay for Google Workspace emails (8 to 15 minutes)."""
    cfg = config or get_all_safety_config()
    min_s = float(cfg.get("pausa_email_min_seg", "480"))
    max_s = float(cfg.get("pausa_email_max_seg", "900"))
    return calculate_gaussian_delay(min_s, max_s, cfg)

# ==============================================================================
# 2.1 CLICK COORDINATE RANDOMIZATION & MICRO-DELAYS (Anti-Centroid Bot Trap)
# ==============================================================================

def calculate_human_click_coordinates(rect: Dict[str, float], safety_margin: float = 0.20) -> Dict[str, Any]:
    """
    Calculates 2D Gaussian randomized (x, y) coordinates inside element bounding box,
    avoiding exact centroid (bot traps) and extreme edges (CSS clipping/border-radius).
    """
    base_x = float(rect.get("x", rect.get("left", 0)))
    base_y = float(rect.get("y", rect.get("top", 0)))
    w = max(10.0, float(rect.get("width", 20)))
    h = max(10.0, float(rect.get("height", 20)))

    cx = base_x + (w / 2.0)
    cy = base_y + (h / 2.0)

    x_min = base_x + (w * safety_margin)
    x_max = base_x + (w * (1.0 - safety_margin))
    y_min = base_y + (h * safety_margin)
    y_max = base_y + (h * (1.0 - safety_margin))

    sigma_x = (x_max - x_min) / 6.0
    sigma_y = (y_max - y_min) / 6.0

    click_x = max(x_min, min(x_max, random.gauss(cx, sigma_x)))
    click_y = max(y_min, min(y_max, random.gauss(cy, sigma_y)))

    hover_ms = random.randint(110, 320)
    mousedown_ms = random.randint(65, 155)
    post_click_ms = random.randint(180, 420)

    return {
        "x": round(click_x, 2),
        "y": round(click_y, 2),
        "offset_x_pct": round(((click_x - base_x) / w) * 100, 1),
        "offset_y_pct": round(((click_y - base_y) / h) * 100, 1),
        "hover_delay_ms": hover_ms,
        "click_duration_ms": mousedown_ms,
        "post_click_delay_ms": post_click_ms
    }

def generate_organic_click_script(selector: str) -> str:
    """
    Generates a JavaScript snippet ready for page.evaluate() that emulates
    the complete biometric sequence: pointerdown -> mousedown -> pointerup -> mouseup -> click
    with randomized non-centroid coordinates.
    """
    return f"""
    (() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ ok: false, error: 'Elemento no encontrado' }};
        
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return {{ ok: false, error: 'Elemento no visible' }};
        
        const randX = 0.22 + (Math.random() * 0.28 + Math.random() * 0.28);
        const randY = 0.25 + (Math.random() * 0.25 + Math.random() * 0.25);
        
        const clientX = r.left + (r.width * randX);
        const clientY = r.top + (r.height * randY);
        
        const eventOpts = {{
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: clientX,
            clientY: clientY,
            screenX: clientX + window.screenX,
            screenY: clientY + window.screenY,
            button: 0,
            buttons: 1
        }};
        
        el.dispatchEvent(new PointerEvent('pointerdown', eventOpts));
        el.dispatchEvent(new MouseEvent('mousedown', eventOpts));
        
        setTimeout(() => {{
            el.dispatchEvent(new PointerEvent('pointerup', eventOpts));
            el.dispatchEvent(new MouseEvent('mouseup', eventOpts));
            el.dispatchEvent(new MouseEvent('click', eventOpts));
        }}, 85 + Math.floor(Math.random() * 60));
        
        return {{
            ok: true,
            clientX: Math.round(clientX),
            clientY: Math.round(clientY),
            width: Math.round(r.width),
            height: Math.round(r.height),
            offsetX_pct: Math.round(randX * 100),
            offsetY_pct: Math.round(randY * 100)
        }};
    }})()
    """

# ==============================================================================
# 3. LINKEDIN SAFETY VERIFICATION
# ==============================================================================

def check_linkedin_safety(conn) -> Dict[str, Any]:
    """
    Comprehensively evaluates whether it is safe to proceed with a LinkedIn action.
    Verifies Kill-Switch, Business Hours, Daily Quota, and Pending Connection Accumulation.
    """
    cfg = get_all_safety_config(conn)
    cursor = conn.cursor()

    # 1. Emergency Kill-Switch
    if cfg.get("kill_switch_activado", "0") == "1":
        reason = cfg.get("kill_switch_motivo", "Freno de emergencia activado.")
        return {
            "autorizado": False,
            "motivo": f"FRENO DE EMERGENCIA ACTIVO: {reason}",
            "codigo": "KILL_SWITCH_ACTIVE",
            "kill_switch": True
        }

    # 2. Business Hours
    is_work_hours, hours_detail = check_business_hours(cfg)
    if not is_work_hours:
        return {
            "autorizado": False,
            "motivo": hours_detail,
            "codigo": "FUERA_DE_HORARIO",
            "en_horario": False
        }

    # 3. Daily Invitation Limit
    daily_limit = int(cfg.get("limite_linkedin_diario", "5"))
    today_iso = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(*) as enviadas_hoy 
        FROM leads 
        WHERE fecha_invitacion LIKE ?
    """, (f"{today_iso}%",))
    sent_today = cursor.fetchone()["enviadas_hoy"]
    quota_left = max(0, daily_limit - sent_today)

    if sent_today >= daily_limit:
        return {
            "autorizado": False,
            "motivo": f"Límite diario de seguridad alcanzado ({sent_today}/{daily_limit} invitaciones hoy).",
            "codigo": "CUOTA_DIARIA_COMPLETA",
            "invitaciones_hoy": sent_today,
            "limite_diario": daily_limit,
            "cupo_restante": 0
        }

    # 4. Pending Invitations Audit
    cursor.execute("""
        SELECT COUNT(*) as total_pendientes
        FROM leads
        WHERE estado = 'INVITACION_ENVIADA' AND invitacion_retirada = 0
    """)
    pending_total = cursor.fetchone()["total_pendientes"]
    warnings = []
    if pending_total >= 250:
        warnings.append(
            f"Tienes {pending_total} invitaciones pendientes sin aceptar. "
            "Se recomienda retirar invitaciones de más de 21 días para no degradar tu score de aceptación."
        )

    return {
        "autorizado": True,
        "motivo": "Condiciones de seguridad óptimas para operar en LinkedIn.",
        "codigo": "OK",
        "invitaciones_hoy": sent_today,
        "limite_diario": daily_limit,
        "cupo_restante": quota_left,
        "en_horario": True,
        "pendientes_acumuladas": pending_total,
        "advertencias": warnings
    }

# ==============================================================================
# 4. GOOGLE WORKSPACE SAFETY VERIFICATION (COLD EMAIL)
# ==============================================================================

def check_email_workspace_safety(conn) -> Dict[str, Any]:
    """
    Evaluates whether it is safe to dispatch an email from Google Workspace.
    """
    cfg = get_all_safety_config(conn)
    cursor = conn.cursor()

    if cfg.get("kill_switch_activado", "0") == "1":
        return {
            "autorizado": False,
            "motivo": "Freno de emergencia activo.",
            "codigo": "KILL_SWITCH_ACTIVE"
        }

    is_work_hours, hours_detail = check_business_hours(cfg)
    if not is_work_hours:
        return {
            "autorizado": False,
            "motivo": hours_detail,
            "codigo": "FUERA_DE_HORARIO"
        }

    daily_limit = int(cfg.get("limite_email_workspace_diario", "15"))
    today_iso = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(*) as enviados_hoy 
        FROM correos_electronicos 
        WHERE enviado_at LIKE ? AND estado = 'ENVIADO'
    """, (f"{today_iso}%",))
    sent_today = cursor.fetchone()["enviados_hoy"]
    quota_left = max(0, daily_limit - sent_today)

    if sent_today >= daily_limit:
        return {
            "autorizado": False,
            "motivo": f"Cuota de calentamiento Google Workspace alcanzada ({sent_today}/{daily_limit} emails hoy).",
            "codigo": "CUOTA_EMAIL_COMPLETA",
            "emails_hoy": sent_today,
            "limite_diario": daily_limit,
            "cupo_restante": 0
        }

    return {
        "autorizado": True,
        "motivo": "Condiciones de envío de correo óptimas.",
        "codigo": "OK",
        "emails_hoy": sent_today,
        "limite_diario": daily_limit,
        "cupo_restante": quota_left
    }

# ==============================================================================
# 5. AUTOMATIC KILL-SWITCH FOR DETECTIONS & CHALLENGES
# ==============================================================================

CHALLENGE_PATTERNS = [
    r"/checkpoint/",
    r"/challenge/",
    r"/uas/login/submit",
    r"security-check",
    r"quick-challenge",
    r"unusual-activity"
]

def inspect_alert_or_checkpoint(current_url: str, html_snippet: str = "") -> Dict[str, Any]:
    """
    Inspects URL and HTML snippet. If checkpoint or captcha is detected, triggers kill-switch.
    """
    text_to_eval = f"{current_url} {html_snippet}".lower()
    
    for pattern in CHALLENGE_PATTERNS:
        if re.search(pattern, text_to_eval):
            reason = f"Detección de pantalla de desafío o captcha en URL: {current_url}"
            activate_kill_switch(reason)
            return {
                "amenaza_detectada": True,
                "motivo": reason,
                "accion": "KILL_SWITCH_DISPARADO"
            }
            
    return {"amenaza_detectada": False}

def activate_kill_switch(reason: str, conn=None) -> Dict[str, Any]:
    """Freezes campaigns and automated tasks immediately."""
    set_safety_config_val("kill_switch_activado", "1", conn)
    set_safety_config_val("kill_switch_motivo", reason, conn)
    print(f"\n🚨 [KILL-SWITCH ACTIVATED] {reason}\n")
    return {"status": "ok", "kill_switch": True, "motivo": reason}

def deactivate_kill_switch(conn=None) -> Dict[str, Any]:
    """Deactivates emergency kill switch after manual audit."""
    set_safety_config_val("kill_switch_activado", "0", conn)
    set_safety_config_val("kill_switch_motivo", "", conn)
    print("\n🟢 [KILL-SWITCH DEACTIVATED] Operations resumed.\n")
    return {"status": "ok", "kill_switch": False}

# ==============================================================================
# 6. SPINTAX ENGINE & EMAIL VALIDATION
# ==============================================================================

def process_spintax(text: str) -> str:
    """
    Recursively evaluates spintax blocks like:
    '{Hola|Estimado/a|Buenas tardes} {director/a|profesor/a}, ...'
    Produces unique variations to avoid spam footprints.
    """
    pattern = re.compile(r'\{([^{}]+)\}')
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split('|')
        choice = random.choice(options)
        text = text[:match.start()] + choice + text[match.end():]
    return text

def validate_email_syntax_and_mx(email: str) -> Dict[str, Any]:
    """
    Validates RFC 5322 email syntax and performs DNS MX check to prevent hard bounces.
    """
    email = email.strip()
    regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(regex, email):
        return {"valido": False, "motivo": "Formato de correo inválido"}

    domain = email.split('@')[1]
    
    # 1. Host resolution check
    try:
        socket.gethostbyname(domain)
    except Exception:
        return {"valido": False, "motivo": f"El dominio @{domain} no existe o no tiene resolución DNS."}

    # 2. MX check via native nslookup
    try:
        cmd = ["nslookup", "-type=mx", domain]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=3.0)
        out_lower = out.lower()
        if "mail exchanger" in out_lower or "mx" in out_lower:
            return {"valido": True, "dominio": domain, "mx_verificado": True}
        else:
            return {"valido": True, "dominio": domain, "mx_verificado": False, "nota": "Dominio activo (registro A)"}
    except Exception:
        return {"valido": True, "dominio": domain, "mx_verificado": False}

# ==============================================================================
# BACKWARD COMPATIBILITY ALIASES (LEGACY SPANISH SUPPORT)
# ==============================================================================
verificar_horario_laboral = check_business_hours
calcular_pausa_gaussiana = calculate_gaussian_delay
calcular_pausa_email = calculate_email_delay
calcular_coordenadas_click_humano = calculate_human_click_coordinates
generar_script_click_organico = generate_organic_click_script
verificar_seguridad_linkedin = check_linkedin_safety
verificar_seguridad_email_workspace = check_email_workspace_safety
inspeccionar_alerta_o_checkpoint = inspect_alert_or_checkpoint
activar_kill_switch = activate_kill_switch
desactivar_kill_switch = deactivate_kill_switch
procesar_spintax = process_spintax
procesar_spintax_recursivo = process_spintax
validar_email_sintaxis_y_mx = validate_email_syntax_and_mx

# English Alternative Aliases
verify_working_hours = check_business_hours
verify_linkedin_safety = check_linkedin_safety
verify_workspace_email_safety = check_email_workspace_safety
PATRONES_CHALLENGE = CHALLENGE_PATTERNS
