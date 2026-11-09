import os
import re
import json
import random
import time
import subprocess
import socket
import hashlib
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, Tuple, List
from database import get_db

# ==============================================================================
# CENTRALIZED SAFETY & ANTI-BAN PROTECTION ENGINE (NexusReach Pro)
# ==============================================================================

def get_all_safety_config(conn=None) -> Dict[str, str]:
    """Obtiene todos los parámetros de seguridad configurados en SQLite."""
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
    """Actualiza o inserta un valor de configuración de seguridad (upsert)."""
    now_iso = datetime.now().isoformat()
    close_conn = False
    if conn is None:
        ctx = get_db()
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO configuracion_seguridad (clave, valor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, updated_at = excluded.updated_at
        """, (key, str(value), now_iso))
        if close_conn:
            conn.commit()
        return True
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)

# ==============================================================================
# 1. BUSINESS HOURS CONTROL (Configurable Working Days & Window)
# ==============================================================================

DIAS_SEMANA_MAP = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo"
}

def check_business_hours(config: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
    """
    Verifica si el momento actual está dentro del horario comercial y días permitidos por el usuario.
    Retorna (es_horario_valido, motivo).
    """
    cfg = config or get_all_safety_config()
    
    # 0. Si la restricción de horario laboral está desactivada, opera 24/7 sin bloqueos
    if cfg.get("horario_laboral_activo", "1") == "0":
        return True, "Restricción de horario desactivada por configuración (operación 24/7 habilitada)."

    now = datetime.now()
    weekday = now.weekday()  # 0=Lunes, 6=Domingo
    day_name = DIAS_SEMANA_MAP.get(weekday, f"Día {weekday}")

    # 1. Validación de Días Habilitados (por defecto Lun-Vie: 0,1,2,3,4)
    dias_raw = cfg.get("dias_laborales", "0,1,2,3,4")
    try:
        dias_permitidos = [int(d.strip()) for d in str(dias_raw).split(",") if d.strip().isdigit()]
    except Exception:
        dias_permitidos = [0, 1, 2, 3, 4]

    if not dias_permitidos:
        dias_permitidos = [0, 1, 2, 3, 4]

    if weekday not in dias_permitidos:
        nombres_dias_activos = ", ".join([DIAS_SEMANA_MAP.get(d, str(d))[:3] for d in sorted(dias_permitidos)])
        return False, f"Hoy es {day_name} (día no habilitado). Días activos configurados: {nombres_dias_activos}."

    # 2. Validación de Horas de Operación
    start_str = cfg.get("horario_inicio", "09:00").strip()
    end_str = cfg.get("horario_fin", "18:00").strip()
    
    try:
        t_start = datetime.strptime(start_str, "%H:%M").time()
        t_end = datetime.strptime(end_str, "%H:%M").time()
    except Exception:
        t_start = datetime.strptime("09:00", "%H:%M").time()
        t_end = datetime.strptime("18:00", "%H:%M").time()
        start_str = "09:00"
        end_str = "18:00"

    current_t = now.time()

    # Ventana estándar diurna (ej. 08:00 a 22:00)
    if t_start <= t_end:
        if current_t < t_start or current_t > t_end:
            return False, f"Fuera de horario laboral ({now.strftime('%H:%M')}). Ventana permitida: {start_str} a {end_str} ({day_name})."
    else:
        # Ventana que cruza la medianoche (ej. 20:00 a 02:00)
        if not (current_t >= t_start or current_t <= t_end):
            return False, f"Fuera de horario laboral nocturno ({now.strftime('%H:%M')}). Ventana permitida: {start_str} a {end_str} ({day_name})."

    return True, f"En horario laboral permitido ({now.strftime('%H:%M')}). Ventana: {start_str} a {end_str} ({day_name})."

# ==============================================================================
# 2. GAUSSIAN STOCHASTIC JITTER (Human Pauses)
# ==============================================================================

def calculate_gaussian_delay(min_sec: Optional[float] = None, max_sec: Optional[float] = None, config: Optional[Dict[str, str]] = None) -> float:
    """
    Calcula una pausa estocástica con distribución gaussiana (normal) truncada.
    Evita intervalos fijos o uniformes que delaten automatizaciones.
    Si pausas_antiban_activas == '0', retorna una pausa mínima de 10s para pruebas.
    """
    cfg = config or get_all_safety_config()
    if cfg.get("pausas_antiban_activas", "1") == "0":
        return 10.0
    min_s = float(min_sec or cfg.get("pausa_linkedin_min_seg", "180"))
    max_s = float(max_sec or cfg.get("pausa_linkedin_max_seg", "360"))
    
    mu = (min_s + max_s) / 2.0
    sigma = (max_s - min_s) / 6.0
    
    delay = random.gauss(mu, sigma)
    final_delay = max(min_s, min(max_s, delay))
    return round(final_delay, 2)

def calculate_email_delay(config: Optional[Dict[str, str]] = None) -> float:
    """Calcula una pausa estocástica extendida para correos de Google Workspace (8 a 15 minutos)."""
    cfg = config or get_all_safety_config()
    if cfg.get("pausas_antiban_activas", "1") == "0":
        return 15.0
    min_s = float(cfg.get("pausa_email_min_seg", "480"))
    max_s = float(cfg.get("pausa_email_max_seg", "900"))
    return calculate_gaussian_delay(min_s, max_s, cfg)

# ==============================================================================
# 2.1 CLICK COORDINATE RANDOMIZATION & MICRO-DELAYS (Anti-Centroid Bot Trap)
# ==============================================================================

def calculate_human_click_coordinates(rect: Dict[str, float], safety_margin: float = 0.20) -> Dict[str, Any]:
    """
    Calcula coordenadas 2D (x, y) aleatorizadas con distribución gaussiana dentro del bounding box del elemento,
    evitando el centroide geométrico exacto (trampa de bots) y los bordes extremos (recortes CSS/border-radius).
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
    Genera un script JavaScript listo para page.evaluate() que emula
    la secuencia biométrica completa: pointerdown -> mousedown -> pointerup -> mouseup -> click
    con coordenadas aleatorias fuera del centroide.
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
    Evalúa integralmente si es seguro proceder con una acción en LinkedIn.
    Verifica Kill-Switch, Horario Laboral, Cuota Diaria y Acumulación de Invitaciones Pendientes.
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

    # 3. Daily Invitation Limit (Con Curva de Calentamiento Warm-up)
    limites_activos = cfg.get("limites_diarios_activos", "1") == "1"
    warmup_status = get_linkedin_warmup_status(conn)
    if warmup_status.get("activo"):
        daily_limit = warmup_status["limite_sugerido"]
    else:
        daily_limit = int(cfg.get("limite_linkedin_diario", "5"))

    today_iso = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(*) as enviadas_hoy 
        FROM leads 
        WHERE fecha_invitacion LIKE ?
    """, (f"{today_iso}%",))
    sent_today = cursor.fetchone()["enviadas_hoy"]
    quota_left = max(0, daily_limit - sent_today)

    if limites_activos and sent_today >= daily_limit:
        return {
            "autorizado": False,
            "motivo": f"Límite diario de seguridad alcanzado ({sent_today}/{daily_limit} invitaciones hoy). Curva Warm-Up Semana {warmup_status.get('semana', 1)}.",
            "codigo": "CUOTA_DIARIA_COMPLETA",
            "invitaciones_hoy": sent_today,
            "limite_diario": daily_limit,
            "cupo_restante": 0,
            "warmup": warmup_status
        }

    # 4. Control de Límite de Búsqueda Comercial (Commercial Use Limit)
    search_usage = get_linkedin_search_usage(conn)
    warnings = []
    if search_usage.get("alerta_limite"):
        warnings.append(
            f"⚠️ Atención: Has alcanzado {search_usage['busquedas_mes']} búsquedas comerciales este mes en LinkedIn "
            f"(Umbral seguro: {search_usage['umbral_alerta']}). Modera las búsquedas para evitar bloqueo de uso comercial."
        )

    # 5. Pending Invitations Audit (>21 días)
    cursor.execute("""
        SELECT COUNT(*) as total_pendientes
        FROM leads
        WHERE estado = 'INVITACION_ENVIADA' AND invitacion_retirada = 0
    """)
    pending_total = cursor.fetchone()["total_pendientes"]
    stale_invites = get_stale_pending_invitations(conn, days_threshold=21)
    if len(stale_invites) > 0:
        warnings.append(
            f"Existen {len(stale_invites)} invitaciones con más de 21 días pendientes. "
            "Se recomienda retirarlas para no degradar tu ratio de aceptación."
        )
    elif pending_total >= 250:
        warnings.append(
            f"Tienes {pending_total} invitaciones pendientes sin responder. "
            "Revisa la cartera de conexiones enviadas."
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
        "invitaciones_vencidas_21d": len(stale_invites),
        "warmup": warmup_status,
        "busquedas_mes": search_usage.get("busquedas_mes", 0),
        "advertencias": warnings
    }

# ==============================================================================
# 4. GOOGLE WORKSPACE SAFETY VERIFICATION (COLD EMAIL)
# ==============================================================================

def check_email_workspace_safety(conn) -> Dict[str, Any]:
    """
    Evalúa si es seguro despachar un correo desde Google Workspace comprobando cuotas diarias y horario laboral.
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

    limites_activos = cfg.get("limites_diarios_activos", "1") == "1"
    daily_limit = int(cfg.get("limite_email_workspace_diario", "15"))
    today_iso = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(*) as enviados_hoy 
        FROM correos_electronicos 
        WHERE enviado_at LIKE ? AND estado = 'ENVIADO'
    """, (f"{today_iso}%",))
    sent_today = cursor.fetchone()["enviados_hoy"]
    quota_left = max(0, daily_limit - sent_today)

    if limites_activos and sent_today >= daily_limit:
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
    Inspecciona la URL y el fragmento HTML. Si detecta un checkpoint o captcha, activa el freno de emergencia.
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
    """Congela inmediatamente las campañas y tareas automáticas activando el freno de emergencia."""
    set_safety_config_val("kill_switch_activado", "1", conn)
    set_safety_config_val("kill_switch_motivo", reason, conn)
    try:
        print(f"\n[KILL-SWITCH ACTIVATED] {reason}\n")
    except Exception:
        pass
    return {"status": "ok", "kill_switch": True, "motivo": reason}

def deactivate_kill_switch(conn=None) -> Dict[str, Any]:
    """Desactiva el freno de emergencia tras una auditoría manual."""
    set_safety_config_val("kill_switch_activado", "0", conn)
    set_safety_config_val("kill_switch_motivo", "", conn)
    try:
        print("\n[KILL-SWITCH DEACTIVATED] Operations resumed.\n")
    except Exception:
        pass
    return {"status": "ok", "kill_switch": False}

# ==============================================================================
# 6. SPINTAX ENGINE & EMAIL VALIDATION
# ==============================================================================

def process_spintax(text: str) -> str:
    """
    Evalúa recursivamente bloques spintax produciendo variaciones únicas para evitar patrones repetitivos de spam.
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
    Valida la sintaxis RFC 5322 del correo y realiza verificación DNS MX para prevenir rebotes duros.
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

def is_working_hours() -> bool:
    """Retorna True si el momento actual está dentro del horario laboral comercial permitido."""
    is_work, _ = check_business_hours()
    return is_work

def is_campaign_active() -> bool:
    """Retorna True si el freno de emergencia (kill-switch) no está activado."""
    cfg = get_all_safety_config()
    return cfg.get("kill_switch_activado", "0") != "1"

# ==============================================================================
# 7. WARM-UP ENGINE, COMMERCIAL SEARCH METER & STALE INVITE CLEANER
# ==============================================================================

def get_linkedin_warmup_status(conn=None, config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Calcula dinámicamente la semana de calentamiento y el límite diario seguro para LinkedIn:
    - Semana 1 (días 1-7): 8 invitaciones / día
    - Semana 2 (días 8-14): 14 invitaciones / día
    - Semana 3 (días 15-21): 20 invitaciones / día
    - Semana 4+ (días 22+): 25 invitaciones / día (régimen regular de crucero)
    """
    cfg = config or get_all_safety_config(conn)
    activo = cfg.get("linkedin_warmup_activo", "1") == "1"
    
    # Soporte para día actual explícito si se configura
    if "warmup_dia_actual" in cfg:
        try:
            dias_transcurridos = max(0, int(cfg["warmup_dia_actual"]) - 1)
        except Exception:
            dias_transcurridos = 0
        inicio_str = (datetime.now() - timedelta(days=dias_transcurridos)).isoformat()
    else:
        inicio_str = cfg.get("linkedin_warmup_inicio")
        if not inicio_str:
            inicio_str = datetime.now().isoformat()
            if conn:
                set_safety_config_val("linkedin_warmup_inicio", inicio_str, conn)

        try:
            inicio_dt = datetime.fromisoformat(inicio_str)
            dias_transcurridos = max(0, (datetime.now() - inicio_dt).days)
        except Exception:
            dias_transcurridos = 0

    dia_actual = dias_transcurridos + 1

    # Límites configurables por semana o custom directo
    lim_sem1 = int(cfg.get("linkedin_warmup_limite_semana_1", cfg.get("linkedin_warmup_limite_actual", 15)))
    lim_sem2 = int(cfg.get("linkedin_warmup_limite_semana_2", 18))
    lim_sem3 = int(cfg.get("linkedin_warmup_limite_semana_3", 22))
    lim_sem4 = int(cfg.get("linkedin_warmup_limite_semana_4", 25))

    # Soporte para override custom directo si existe
    custom_warmup = cfg.get("linkedin_warmup_limite_actual") or cfg.get("linkedin_warmup_limite_custom")

    if custom_warmup and str(custom_warmup).strip().isdigit() and int(custom_warmup) > 0:
        limite = int(custom_warmup)
        lim_sem1 = limite
    elif "warmup_limite_inicial" in cfg and "warmup_incremento_diario" in cfg:
        try:
            lim_ini = int(cfg.get("warmup_limite_inicial", 3))
            inc = int(cfg.get("warmup_incremento_diario", 1))
            lim_max = int(cfg.get("warmup_limite_maximo", 20))
            limite = min(lim_max, lim_ini + dias_transcurridos * inc)
        except Exception:
            limite = lim_sem1
    elif dias_transcurridos < 7:
        limite = lim_sem1
    elif dias_transcurridos < 14:
        limite = lim_sem2
    elif dias_transcurridos < 21:
        limite = lim_sem3
    else:
        limite = lim_sem4

    semana = min(4, (dias_transcurridos // 7) + 1)
    en_calentamiento = dias_transcurridos < 21 and (limite < int(cfg.get("warmup_limite_maximo", 25)))

    curva = [
        {"semana": 1, "limite": lim_sem1, "etiqueta": "Semana 1", "activo": semana == 1, "descripcion": "Inicio seguro y acondicionamiento"},
        {"semana": 2, "limite": lim_sem2, "etiqueta": "Semana 2", "activo": semana == 2, "descripcion": "Incremento moderado de actividad"},
        {"semana": 3, "limite": lim_sem3, "etiqueta": "Semana 3", "activo": semana == 3, "descripcion": "Consolidación de red y ritmo"},
        {"semana": 4, "limite": lim_sem4, "etiqueta": "Semana 4+", "activo": semana >= 4, "descripcion": "Régimen de crucero óptimo (Free)"},
    ]

    return {
        "activo": activo,
        "semana": semana,
        "dia_actual": dia_actual,
        "dias_transcurridos": dias_transcurridos,
        "limite_sugerido": limite,
        "limite_recomendado_hoy": limite,
        "limite_diario": limite,
        "en_calentamiento": en_calentamiento,
        "fecha_inicio": inicio_str,
        "curva": curva
    }

def track_linkedin_search(increment: int = 1, conn=None) -> Dict[str, Any]:
    """
    Registra búsquedas de personas realizadas en LinkedIn y gestiona el ciclo mensual
    para proteger la cuenta del Commercial Use Limit de LinkedIn en cuentas gratuitas.
    """
    periodo_actual = datetime.now().strftime("%Y-%m")
    cfg = get_all_safety_config(conn)
    periodo_guardado = cfg.get("linkedin_busquedas_periodo", periodo_actual)
    
    if periodo_guardado != periodo_actual:
        conteo = increment
        set_safety_config_val("linkedin_busquedas_periodo", periodo_actual, conn)
        set_safety_config_val("linkedin_busquedas_mes", str(conteo), conn)
    else:
        conteo = int(cfg.get("linkedin_busquedas_mes", "0")) + increment
        set_safety_config_val("linkedin_busquedas_mes", str(conteo), conn)

    umbral_alerta = 80
    umbral_bloqueo = 100

    return {
        "busquedas_mes": conteo,
        "periodo": periodo_actual,
        "umbral_alerta": umbral_alerta,
        "umbral_bloqueo": umbral_bloqueo,
        "alerta_limite": conteo >= umbral_alerta,
        "bloqueado": conteo >= umbral_bloqueo
    }

def get_linkedin_search_usage(conn=None) -> Dict[str, Any]:
    """Consulta el uso actual del contador de búsquedas mensuales en LinkedIn."""
    periodo_actual = datetime.now().strftime("%Y-%m")
    cfg = get_all_safety_config(conn)
    periodo_guardado = cfg.get("linkedin_busquedas_periodo", periodo_actual)
    conteo = int(cfg.get("linkedin_busquedas_mes", "0")) if periodo_guardado == periodo_actual else 0

    return {
        "busquedas_mes": conteo,
        "periodo": periodo_actual,
        "umbral_alerta": 80,
        "umbral_bloqueo": 100,
        "alerta_limite": conteo >= 80,
        "bloqueado": conteo >= 100
    }

def get_stale_pending_invitations(conn=None, days_threshold: int = 21) -> List[Dict[str, Any]]:
    """
    Encuentra prospectos con invitación enviada hace más de 'days_threshold' días que aún no han conectado.
    """
    cutoff = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db()
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, perfil_url, fecha_invitacion, tenant_id
            FROM leads
            WHERE estado = 'INVITACION_ENVIADA'
              AND (invitacion_retirada IS NULL OR invitacion_retirada = 0)
              AND fecha_invitacion IS NOT NULL
              AND fecha_invitacion <= ?
            ORDER BY fecha_invitacion ASC
        """, (cutoff,))
        return cursor.fetchall()
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)

def withdraw_stale_invitations(days_threshold: int = 21, conn=None) -> Dict[str, Any]:
    """
    Marca como retiradas las invitaciones pendientes que superan el umbral seguro de días
    y registra el suceso en el historial de actividades para proteger la reputación de la cuenta.
    """
    stale_leads = get_stale_pending_invitations(conn, days_threshold=days_threshold)
    if not stale_leads:
        return {"retiradas": 0, "mensaje": "No hay invitaciones que superen el umbral de antigüedad."}

    now_iso = datetime.now().isoformat()
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db()
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        retiradas = 0
        for lead in stale_leads:
            lid = lead["id"]
            cursor.execute("""
                UPDATE leads
                SET invitacion_retirada = 1,
                    fecha_retiro_invitacion = ?,
                    estado = 'INVITACION_RETIRADA',
                    updated_at = ?
                WHERE id = ?
            """, (now_iso, now_iso, lid))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'INVITACION_RETIRADA_AUTOMATICA', ?, ?)
            """, (lid, f"Retiro automático por antigüedad (> {days_threshold} días sin respuesta).", now_iso))
            retiradas += 1

        return {
            "retiradas": retiradas,
            "invitaciones_retiradas": retiradas,
            "dias_umbral": days_threshold,
            "timestamp": now_iso,
            "mensaje": f"Se marcaron {retiradas} invitaciones como retiradas para proteger el ratio de aceptación."
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


# ==============================================================================
# 8. MOTOR DE LÍMITES POR CUENTA, HUELLA ESTOCÁSTICA Y SEÑALES DE RIESGO (WORKSTREAM 5.5 [P1])
# ==============================================================================

def get_account_safety_parameters(account_id: str) -> Dict[str, Any]:
    """
    Deriva una semilla determinista única basada en el ID de la cuenta para que
    cada cuenta posea una distribución estadística y parámetros de tiempo distintos,
    evitando una huella temporal homogénea compartida entre clientes.
    """
    seed_int = int(hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed_int)

    # Rango de pausas específico por cuenta (variación +/- 30s sobre la media base)
    base_min = 180 + rng.randint(-20, 25)
    base_max = 360 + rng.randint(-30, 40)
    if base_min >= base_max:
        base_max = base_min + 120

    # Desplazamiento orgánico (jitter) en horario comercial (ej. 09:12 en vez de 09:00 en punto)
    start_jitter_min = rng.randint(-15, 20)
    end_jitter_min = rng.randint(-20, 15)

    return {
        "account_id": account_id,
        "seed": seed_int,
        "min_delay_sec": base_min,
        "max_delay_sec": base_max,
        "mean_delay_sec": round((base_min + base_max) / 2.0, 1),
        "start_jitter_minutes": start_jitter_min,
        "end_jitter_minutes": end_jitter_min,
        "scroll_speed_factor": round(rng.uniform(0.85, 1.20), 2)
    }


def calculate_per_account_delay(account_id: str) -> float:
    """Calcula una pausa gaussiana estocástica personalizada para la cuenta."""
    params = get_account_safety_parameters(account_id)
    min_s = float(params["min_delay_sec"])
    max_s = float(params["max_delay_sec"])
    mu = (min_s + max_s) / 2.0
    sigma = (max_s - min_s) / 6.0
    delay = random.gauss(mu, sigma)
    return round(max(min_s, min(max_s, delay)), 2)


def calculate_account_health(account_id: str, tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Calcula el puntaje de salud de la cuenta (0 a 100) según:
    - Tasa de aceptación de los últimos 30 días.
    - Volumen de invitaciones pendientes acumuladas.
    - Incidentes o checkpoints en los últimos 14 días.
    Actualiza la columna health_score en linkedin_accounts.
    """
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        now_dt = datetime.now()
        thirty_days_ago = (now_dt - timedelta(days=30)).isoformat()
        fourteen_days_ago = (now_dt - timedelta(days=14)).isoformat()

        # 1. Total enviadas y aceptadas en 30 días
        cursor.execute("""
            SELECT 
                COUNT(*) as enviadas,
                SUM(CASE WHEN estado IN ('CONTACTADO', 'CONECTADO', 'MENSAJE_ENVIADO') THEN 1 ELSE 0 END) as aceptadas
            FROM leads
            WHERE tenant_id = ? AND fecha_invitacion >= ?
        """, (tenant_id, thirty_days_ago))
        row_30d = cursor.fetchone()
        enviadas_30d = row_30d["enviadas"] if isinstance(row_30d, dict) else row_30d[0]
        aceptadas_30d = (row_30d["aceptadas"] or 0) if isinstance(row_30d, dict) else (row_30d[1] or 0)

        acceptance_rate = (aceptadas_30d / enviadas_30d) if enviadas_30d > 0 else 0.50

        # 2. Pendientes acumuladas
        cursor.execute("""
            SELECT COUNT(*) as total_pendientes
            FROM leads
            WHERE tenant_id = ? AND estado = 'INVITACION_ENVIADA' AND invitacion_retirada = 0
        """, (tenant_id,))
        row_pend = cursor.fetchone()
        pendientes = row_pend["total_pendientes"] if isinstance(row_pend, dict) else row_pend[0]

        # 3. Incidentes recientes (Checkpoints / Captchas)
        cursor.execute("""
            SELECT COUNT(*) as incidentes
            FROM system_logs
            WHERE tenant_id = ? AND level = 'CRITICAL' AND timestamp >= ?
        """, (tenant_id, fourteen_days_ago))
        row_inc = cursor.fetchone()
        incidentes_14d = row_inc["incidentes"] if isinstance(row_inc, dict) else row_inc[0]

        # Cálculo de puntaje
        score = 100.0

        if enviadas_30d >= 10:
            if acceptance_rate < 0.20:
                score -= 30.0
            elif acceptance_rate < 0.30:
                score -= 15.0

        if pendientes >= 400:
            score -= 30.0
        elif pendientes >= 250:
            score -= 15.0

        score -= (incidentes_14d * 35.0)
        final_score = max(0.0, min(100.0, round(score, 1)))

        # Actualizar en la base de datos
        cursor.execute("""
            UPDATE linkedin_accounts 
            SET health_score = ?, updated_at = ? 
            WHERE id = ? AND tenant_id = ?
        """, (final_score, now_dt.isoformat(), account_id, tenant_id))

        if close_conn:
            conn.commit()

        return {
            "account_id": account_id,
            "health_score": final_score,
            "acceptance_rate": round(acceptance_rate * 100, 1),
            "enviadas_30d": enviadas_30d,
            "aceptadas_30d": aceptadas_30d,
            "pendientes": pendientes,
            "incidentes_14d": incidentes_14d,
            "saludable": final_score >= 70.0
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def calculate_adaptive_warmup_limit(account_id: str, tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Curva de calentamiento adaptativa para la cuenta de LinkedIn:
    - Base: 15 invitaciones/día (punto de partida seguro).
    - Semana 2: 18 invitaciones/día SOLO SI health_score >= 70.0.
    - Semana 3: 22 invitaciones/día SOLO SI health_score >= 75.0.
    - Semana 4+: 25 invitaciones/día SOLO SI health_score >= 80.0.
    - Si health_score < 50.0, se reduce automáticamente a 10/día para protección.
    """
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT warmup_day, status, health_score, created_at FROM linkedin_accounts WHERE id = ? AND tenant_id = ?", (account_id, tenant_id))
        row = cursor.fetchone()
        if not row:
            return {"limite_diario": 15, "semana": 1, "escalamiento_permitido": True}

        warmup_day = row["warmup_day"] if isinstance(row, dict) else row[0]
        warmup_day = max(1, warmup_day or 1)
        row_score = row["health_score"] if isinstance(row, dict) else row[2]
        if row_score is not None:
            score = float(row_score)
        else:
            health = calculate_account_health(account_id, tenant_id, conn=conn)
            score = health["health_score"]

        # Regla de escalamiento condicionado a salud
        if score < 50.0:
            limit = 10
            escalamiento = False
            motivo = f"Puntaje de salud crítico ({score}/100): Límite reducido a 10/día por seguridad."
        elif warmup_day <= 7:
            limit = 15
            escalamiento = True
            motivo = "Semana 1: Calentamiento inicial seguro (15/día)."
        elif warmup_day <= 14:
            if score >= 70.0:
                limit = 18
                escalamiento = True
                motivo = "Semana 2: Rampa progresiva a 18/día autorizada por salud óptima."
            else:
                limit = 15
                escalamiento = False
                motivo = f"Semana 2: Escalamiento retenido en 15/día por salud moderada ({score}/100)."
        elif warmup_day <= 21:
            if score >= 75.0:
                limit = 22
                escalamiento = True
                motivo = "Semana 3: Rampa progresiva a 22/día autorizada."
            else:
                limit = 18
                escalamiento = False
                motivo = f"Semana 3: Escalamiento retenido en 18/día por salud ({score}/100)."
        else:
            if score >= 80.0:
                limit = 25
                escalamiento = True
                motivo = "Semana 4+: Régimen de crucero óptimo (25/día)."
            else:
                limit = 22
                escalamiento = False
                motivo = f"Semana 4+: Régimen limitado a 22/día para preservar ratio de aceptación ({score}/100)."

        now_iso = datetime.now().isoformat()
        cursor.execute("""
            UPDATE linkedin_accounts 
            SET daily_invite_limit = ?, updated_at = ? 
            WHERE id = ? AND tenant_id = ?
        """, (limit, now_iso, account_id, tenant_id))

        if close_conn:
            conn.commit()

        semana = min(4, ((warmup_day - 1) // 7) + 1)
        return {
            "account_id": account_id,
            "warmup_day": warmup_day,
            "semana": semana,
            "limite_diario": limit,
            "health_score": score,
            "escalamiento_permitido": escalamiento,
            "motivo": motivo
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def report_risk_signal(
    account_id: str,
    tenant_id: str,
    signal_type: str,
    details: Optional[Dict[str, Any]] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Kill-switch automático por señales de riesgo:
    - Tipos: 'CHECKPOINT', 'CAPTCHA', 'EMAIL_PIN', 'RESTRICTION', 'LIMIT_REACHED'.
    - Congela de inmediato la cuenta (status = 'CHECKPOINT' / 'RESTRICTED').
    - Registra el incidente en system_logs.
    - Si se detectan >= 3 cuentas con incidentes en < 24 horas a nivel global,
      dispara el kill-switch global del sistema para proteger todas las cuentas de clientes.
    """
    valid_signals = {"CHECKPOINT", "CAPTCHA", "EMAIL_PIN", "RESTRICTION", "LIMIT_REACHED"}
    if signal_type not in valid_signals:
        signal_type = "CHECKPOINT"

    now_iso = datetime.now().isoformat()
    new_status = "RESTRICTED" if signal_type == "RESTRICTION" else "CHECKPOINT"

    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(is_super_admin=True)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()

        # 1. Congelar cuenta individual
        cursor.execute("""
            UPDATE linkedin_accounts 
            SET status = ?, health_score = MAX(0.0, health_score - 35.0), updated_at = ? 
            WHERE id = ?
        """, (new_status, now_iso, account_id))

        # 2. Registrar incidente en system_logs
        det_json = json.dumps(details or {"signal": signal_type, "account_id": account_id})
        cursor.execute("""
            INSERT INTO system_logs (timestamp, level, module, message, details_json, created_at, tenant_id)
            VALUES (?, 'CRITICAL', 'ANTIBAN_SAFETY', ?, ?, ?, ?)
        """, (now_iso, f"Señal de riesgo detectada: {signal_type} en cuenta {account_id}", det_json, now_iso, tenant_id))

        # 3. Comprobar anomalía global (Kill-switch global si >= 3 cuentas distintas sufrieron incidentes en 24h)
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
        cursor.execute("""
            SELECT COUNT(DISTINCT details_json) as incident_accounts
            FROM system_logs
            WHERE module = 'ANTIBAN_SAFETY' AND level = 'CRITICAL' AND timestamp >= ?
        """, (twenty_four_hours_ago,))
        row_global = cursor.fetchone()
        incident_accounts = row_global["incident_accounts"] if isinstance(row_global, dict) else row_global[0]

        global_triggered = False
        if incident_accounts >= 3:
            activate_kill_switch("Freno de emergencia global: Detección anómala de incidentes múltiples (>= 3 cuentas) en LinkedIn en < 24h.", conn=conn)
            global_triggered = True

        if close_conn:
            conn.commit()

        return {
            "ok": True,
            "account_id": account_id,
            "new_status": new_status,
            "signal_type": signal_type,
            "cola_congelada": True,
            "incident_accounts_24h": incident_accounts,
            "global_kill_switch_triggered": global_triggered
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def reactivate_account(account_id: str, tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Reactivación manual de una cuenta congelada tras auditoría humana.
    Reanuda el despacho reiniciando el calentamiento al piso seguro de 15/día (warmup_day = 1).
    """
    now_iso = datetime.now().isoformat()
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE linkedin_accounts 
            SET status = 'WARMUP', warmup_day = 1, daily_invite_limit = 15, updated_at = ? 
            WHERE id = ? AND tenant_id = ?
        """, (now_iso, account_id, tenant_id))

        if close_conn:
            conn.commit()

        return {
            "ok": True,
            "account_id": account_id,
            "status": "WARMUP",
            "warmup_day": 1,
            "daily_invite_limit": 15,
            "mensaje": "Cuenta reactivada exitosamente con calentamiento reiniciado a 15/día."
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def authorize_linkedin_action(
    account_id: str,
    tenant_id: str,
    action: str = "LI_SEND_INVITE",
    conn=None
) -> Dict[str, Any]:
    """
    Evaluación integral de autorización por el Safety Engine:
    1. Freno de emergencia global activo?
    2. Cuenta congelada (CHECKPOINT / RESTRICTED)?
    3. Ventana horaria laboral con jitter de la cuenta?
    4. Cuota diaria de calentamiento alcanzada?
    SEPARACIÓN ESTRICTA: El resultado depende ÚNICAMENTE de la seguridad y salud de la cuenta,
    nunca del plan ni de pagos comerciales.
    """
    cfg = get_all_safety_config(conn)

    # 1. Kill-Switch Global
    if cfg.get("kill_switch_activado", "0") == "1":
        return {
            "autorizado": False,
            "motivo": f"FRENO GLOBAL ACTIVO: {cfg.get('kill_switch_motivo', 'Pausa general de seguridad')}",
            "codigo": "GLOBAL_KILL_SWITCH_ACTIVE"
        }

    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, invites_sent_today FROM linkedin_accounts WHERE id = ? AND tenant_id = ?", (account_id, tenant_id))
        row = cursor.fetchone()
        if not row:
            return {"autorizado": False, "motivo": "Cuenta de LinkedIn no encontrada.", "codigo": "ACCOUNT_NOT_FOUND"}

        status = row["status"] if isinstance(row, dict) else row[0]
        invites_today = (row["invites_sent_today"] or 0) if isinstance(row, dict) else (row[1] or 0)

        # 2. Estado de la cuenta
        if status in ("CHECKPOINT", "RESTRICTED", "PAUSED"):
            return {
                "autorizado": False,
                "motivo": f"La cuenta se encuentra en estado '{status}'. Requiere verificación o reactivación manual.",
                "codigo": f"ACCOUNT_{status}"
            }

        # 3. Horario laboral con jitter por cuenta
        in_hours, h_reason = check_business_hours(cfg)
        if not in_hours:
            return {"autorizado": False, "motivo": h_reason, "codigo": "FUERA_DE_HORARIO"}

        # 4. Cuota diaria de calentamiento
        warmup_info = calculate_adaptive_warmup_limit(account_id, tenant_id, conn=conn)
        limit = warmup_info["limite_diario"]

        if action == "LI_SEND_INVITE" and invites_today >= limit:
            return {
                "autorizado": False,
                "motivo": f"Límite diario de seguridad alcanzado ({invites_today}/{limit} hoy). Curva adaptativa Semana {warmup_info['semana']}.",
                "codigo": "CUOTA_DIARIA_COMPLETA",
                "invitaciones_hoy": invites_today,
                "limite_diario": limit,
                "cupo_restante": 0
            }

        return {
            "autorizado": True,
            "motivo": "Autorizado por el motor de seguridad antiban.",
            "codigo": "OK",
            "daily_limit": limit,
            "invites_today": invites_today,
            "cupo_restante": max(0, limit - invites_today),
            "warmup": warmup_info
        }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def check_commercial_quota(tenant_id: str, action: str, conn=None) -> Dict[str, Any]:
    """
    Evaluación independiente de límites comerciales (Planes, suscripciones y créditos).
    Completamente separada del motor de seguridad antiban.
    """
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT estado, puestos_contratados FROM suscripciones WHERE tenant_id = ?", (tenant_id,))
        sub = cursor.fetchone()
        if not sub:
            return {"aprobado": True, "tipo": "DEFAULT_PLAN", "creditos_restantes": 999}

        estado = sub["estado"] if isinstance(sub, dict) else sub[0]
        if estado not in ("ACTIVA", "EN_PRUEBA", "TRIAL"):
            return {"aprobado": False, "motivo": f"Suscripción comercial no activa: {estado}", "codigo": "COMMERCIAL_INACTIVE"}

        return {"aprobado": True, "tipo": "COMMERCIAL_APPROVED", "estado": estado}
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)

