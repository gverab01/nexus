"""
Módulo de Seguridad y Anti-Baneo para WhatsApp Web (NexusReach Pro)

Este módulo implementa las reglas de mitigación de riesgo y comportamiento humanizado
para el canal de WhatsApp Web:
1. Normalización de números telefónicos a formato internacional E.164.
2. Control estricto de cuota diaria y horarios comerciales.
3. Protección de primer contacto: bloqueo o sanitización de enlaces/URLs para evitar
   reportes por spam y flaggeo heurístico de Meta.
4. Pausas inter-contacto gaussianas (6 a 15 minutos entre conversaciones nuevas).
5. Detección automática de palabras clave de baja/opt-out ("no me interesa", "baja", "stop").
6. Generación de scripts de mecanografía biométrica humana con micro-pausas y respiración.
"""

import re
import json
import random
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from database import get_db
from safety_engine import get_all_safety_config, check_business_hours

# Expresión regular para detectar hipervínculos y URLs en el cuerpo del mensaje
URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|[a-zA-Z0-9.\-]+\.(?:com|cl|org|net|io|me|app|ai|biz|info)(?:/[^\s]*)?)",
    re.IGNORECASE
)

# Palabras clave asociadas a intención de no contacto o cancelación
OPT_OUT_PATTERN = re.compile(
    r"\b(no\s+gracias|no\s+me\s+interesa|cancelar|dar\s+de\s+baja|baja|desuscribir(?:me)?|remover|stop|alto|no\s+contactar|no\s+m[aá]s|borrar|eliminar(?:me)?)\b",
    re.IGNORECASE
)


def normalize_phone_number(raw_phone: str, default_country_code: str = "+56") -> Optional[str]:
    """
    Normaliza un número de teléfono crudo a estándar internacional E.164.
    Maneja prefijos nacionales (ej. Chile móvil 9XXXXXXXX -> +569XXXXXXXX).
    Retorna None si el formato numérico es inválido o insuficiente.
    """
    if not raw_phone:
        return None

    cleaned = re.sub(r"[^\d+]", "", str(raw_phone).strip())
    if not cleaned:
        return None

    # Si ya inicia con +, verificar dígitos
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if 8 <= len(digits) <= 15 and digits.isdigit():
            return f"+{digits}"
        return None

    # Si no tiene +, analizar formato de dígitos
    digits = re.sub(r"[^\d]", "", cleaned)
    clean_default_code = default_country_code.lstrip("+")

    # Caso Chile móvil común (9 dígitos comenzando con 9)
    if clean_default_code == "56":
        if len(digits) == 9 and digits.startswith("9"):
            return f"+56{digits}"
        elif len(digits) == 8:
            return f"+569{digits}"
        elif len(digits) == 11 and digits.startswith("569"):
            return f"+{digits}"

    # Si ya incluye el código de país sin el '+'
    if digits.startswith(clean_default_code) and 8 <= len(digits) <= 15:
        return f"+{digits}"

    # Concatenar código de país por defecto si longitud es consistente
    if 7 <= len(digits) <= 12:
        return f"+{clean_default_code}{digits}"

    return None


def validate_message_links(text: str, is_first_contact: bool = True) -> Tuple[bool, str]:
    """
    Verifica que el mensaje no contenga enlaces si es el primer contacto con el destinatario.
    Enviar enlaces directos a números que no tienen agregado al remitente es el principal factor
    de baneo y marcado como spam en WhatsApp Web.
    """
    if not text:
        return True, ""

    has_link = bool(URL_PATTERN.search(text))
    if is_first_contact and has_link:
        return False, "El mensaje contiene enlaces o dominios web. La política de seguridad de primer contacto de WhatsApp prohíbe URLs en el primer mensaje."

    return True, text


def check_opt_out_keywords(text: str) -> bool:
    """
    Identifica si una respuesta o mensaje contiene intenciones explícitas de baja/desuscripción.
    """
    if not text:
        return False
    return bool(OPT_OUT_PATTERN.search(text))


def calculate_whatsapp_delay(config: Optional[Dict[str, Any]] = None) -> int:
    """
    Calcula una pausa gaussiana estocástica entre envíos de WhatsApp a contactos fríos.
    Por defecto oscila entre 360 y 900 segundos (6 a 15 minutos).
    """
    cfg = config or get_all_safety_config()
    min_sec = int(cfg.get("whatsapp_pausa_min_seg", cfg.get("whatsapp_pausa_min_segundos", 360)))
    max_sec = int(cfg.get("whatsapp_pausa_max_seg", cfg.get("whatsapp_pausa_max_segundos", 900)))

    if min_sec >= max_sec:
        return min_sec

    mean = (min_sec + max_sec) / 2.0
    stdev = (max_sec - min_sec) / 6.0  # 99.7% dentro del rango
    delay = random.gauss(mean, stdev)
    return int(max(min_sec, min(max_sec, delay)))


def get_whatsapp_daily_usage(conn=None) -> Dict[str, Any]:
    """
    Calcula la cantidad de mensajes de WhatsApp despachados durante la jornada de hoy.
    """
    today_prefix = datetime.now().strftime("%Y-%m-%d")

    def _query(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS total FROM mensajes_whatsapp 
            WHERE enviado_at LIKE ? AND estado = 'ENVIADO'
        """, (f"{today_prefix}%",))
        row = cursor.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return row.get("total", 0)
        return row[0]

    if conn is not None:
        count = _query(conn)
    else:
        with get_db() as c:
            count = _query(c)

    return {"hoy": today_prefix, "mensajes_enviados_hoy": count}


def is_whatsapp_enabled_for_tenant(tenant_id: str, conn=None) -> bool:
    """
    Verifica si el módulo de WhatsApp Web está activado por feature flag para el tenant.
    Por defecto está DESACTIVADO (0) por seguridad de cuenta.
    """
    cfg = get_all_safety_config(conn=conn)
    # 1. Configuración global/tenant de feature flag
    tenant_flag_key = f"whatsapp_enabled_{tenant_id}"
    if tenant_flag_key in cfg:
        return cfg[tenant_flag_key] == "1"
    # Fallback general
    return cfg.get("whatsapp_enabled", "0") == "1"


def set_whatsapp_feature_flag(tenant_id: str, enabled: bool, conn=None) -> None:
    """Activa o desactiva el feature flag de WhatsApp para un tenant."""
    from safety_engine import set_safety_config_val
    tenant_flag_key = f"whatsapp_enabled_{tenant_id}"
    set_safety_config_val(tenant_flag_key, "1" if enabled else "0", conn=conn)


def is_lead_warm(lead_data: Dict[str, Any]) -> bool:
    """
    REGLA NO NEGOCIABLE v1.3 (Sección 5.7 y Sección 6):
    Solo se permite mensajería de WhatsApp para contactos CÁLIDOS (conexión aceptada en LinkedIn).
    NUNCA enviar mensajes fríos por WhatsApp.
    """
    if not lead_data:
        return False
    grado = str(lead_data.get("grado_red", "")).strip().lower()
    estado = str(lead_data.get("lead_estado", lead_data.get("estado", ""))).strip().upper()

    if grado in ("1º", "1er", "1°", "1st", "1"):
        return True
    if estado in ("CONECTADO", "1º", "1ER", "1°", "1ST", "MENSAJE_ENVIADO", "RESPONDIÓ", "RESPONDIO"):
        return True
    if lead_data.get("is_warm") is True:
        return True
    return False


def activate_whatsapp_kill_switch(motivo: str, conn=None) -> Dict[str, Any]:
    """Activa el freno de emergencia específico para el canal de WhatsApp."""
    from safety_engine import set_safety_config_val
    set_safety_config_val("whatsapp_kill_switch_activado", "1", conn=conn)
    set_safety_config_val("whatsapp_kill_switch_motivo", motivo, conn=conn)
    return {"ok": True, "canal": "WHATSAPP", "kill_switch": True, "motivo": motivo}


def deactivate_whatsapp_kill_switch(conn=None) -> Dict[str, Any]:
    """Desactiva el freno de emergencia específico para WhatsApp."""
    from safety_engine import set_safety_config_val
    set_safety_config_val("whatsapp_kill_switch_activado", "0", conn=conn)
    set_safety_config_val("whatsapp_kill_switch_motivo", "", conn=conn)
    return {"ok": True, "canal": "WHATSAPP", "kill_switch": False}


def report_whatsapp_risk_signal(tenant_id: str, signal_type: str, details: Optional[Dict[str, Any]] = None, conn=None) -> Dict[str, Any]:
    """
    Registra señales de riesgo críticas en WhatsApp (ej. BAN_WARNING, SESSION_DISCONNECTED,
    RATE_LIMIT_WARNING) y activa automáticamente el kill-switch específico del canal.
    """
    now_iso = datetime.now().isoformat()
    motivo = f"Freno preventivo en canal WhatsApp por señal crítica: {signal_type}"
    activate_whatsapp_kill_switch(motivo, conn=conn)

    close_conn = False
    if conn is None:
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        det_json = json.dumps(details or {"signal": signal_type, "tenant_id": tenant_id})
        cursor.execute("""
            INSERT INTO system_logs (timestamp, level, module, message, details_json, created_at, tenant_id)
            VALUES (?, 'CRITICAL', 'WHATSAPP_SAFETY', ?, ?, ?, ?)
        """, (now_iso, motivo, det_json, now_iso, tenant_id))

        if close_conn:
            conn.commit()

        return {"ok": True, "signal_type": signal_type, "whatsapp_kill_switch_triggered": True, "motivo": motivo}
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)


def check_whatsapp_safety(conn=None) -> Dict[str, Any]:
    """
    Evaluación retrocompatible de seguridad global de WhatsApp:
    Retorna tanto 'safe' como 'autorizado' para consistencia con los callers.
    """
    cfg = get_all_safety_config(conn=conn)

    # 1. Kill-Switch Global o Específico de Canal
    if cfg.get("kill_switch_activado") == "1":
        return {
            "safe": False,
            "autorizado": False,
            "reason": "Kill-Switch global activo.",
            "motivo": "Kill-Switch global activo.",
            "codigo": "GLOBAL_KILL_SWITCH_ACTIVE",
            "daily_sent": 0,
            "daily_limit": 0,
            "within_hours": False
        }

    if cfg.get("whatsapp_kill_switch_activado") == "1":
        motivo = cfg.get("whatsapp_kill_switch_motivo", "Kill-Switch específico de WhatsApp activado.")
        return {
            "safe": False,
            "autorizado": False,
            "reason": motivo,
            "motivo": motivo,
            "codigo": "WHATSAPP_KILL_SWITCH_ACTIVE",
            "daily_sent": 0,
            "daily_limit": 0,
            "within_hours": False
        }

    # 2. Horario comercial
    within_hours, hours_msg = check_business_hours(config=cfg)
    limite_diario = int(cfg.get("whatsapp_cuota_diaria", cfg.get("whatsapp_limite_diario", 15)))
    if not within_hours:
        return {
            "safe": False,
            "autorizado": False,
            "reason": hours_msg,
            "motivo": hours_msg,
            "codigo": "FUERA_DE_HORARIO",
            "daily_sent": 0,
            "daily_limit": limite_diario,
            "within_hours": False
        }

    # 3. Límite diario conservador (15/día)
    usage = get_whatsapp_daily_usage(conn=conn)
    enviados_hoy = usage.get("mensajes_enviados_hoy", 0)

    if enviados_hoy >= limite_diario:
        motivo_lim = f"Límite diario de WhatsApp alcanzado ({enviados_hoy}/{limite_diario} mensajes hoy)."
        return {
            "safe": False,
            "autorizado": False,
            "reason": motivo_lim,
            "motivo": motivo_lim,
            "codigo": "WHATSAPP_DAILY_LIMIT_REACHED",
            "daily_sent": enviados_hoy,
            "daily_limit": limite_diario,
            "within_hours": True
        }

    return {
        "safe": True,
        "autorizado": True,
        "reason": "Condiciones óptimas de seguridad para despacho de WhatsApp Web.",
        "motivo": "Condiciones óptimas de seguridad para despacho de WhatsApp Web.",
        "codigo": "OK",
        "daily_sent": enviados_hoy,
        "daily_limit": limite_diario,
        "within_hours": True
    }


def check_whatsapp_safety_for_tenant(
    tenant_id: str,
    lead_data: Dict[str, Any],
    conn=None
) -> Dict[str, Any]:
    """
    Evaluación integral de seguridad para WhatsApp por Tenant (Sección 5.7):
    1. Feature flag activo para el tenant.
    2. REGLA ESTRICTA: Prospecto cálido (conexión aceptada en LinkedIn). NUNCA mensajes fríos.
    3. Lista de supresión / opt-out respetada.
    4. Kill-switch del canal inactivo.
    5. Horario comercial laboral permitido.
    6. Límite diario de ~15 mensajes/día respetado.
    """
    # 1. Feature Flag
    if not is_whatsapp_enabled_for_tenant(tenant_id, conn=conn):
        return {
            "autorizado": False,
            "safe": False,
            "motivo": "El módulo de WhatsApp Web está desactivado por defecto para este tenant. Requiere activación explícita con aceptación de términos de riesgo.",
            "codigo": "WHATSAPP_FEATURE_FLAG_DISABLED"
        }

    # 2. Warm Outreach Estricto (Prohibición 6 y Sección 5.7)
    if not is_lead_warm(lead_data):
        return {
            "autorizado": False,
            "safe": False,
            "motivo": "PROHIBICIÓN ESTRICTA: WhatsApp solo está autorizado para contactos cálidos (conexión de 1er grado aceptada en LinkedIn). Mensajería en frío rechazada.",
            "codigo": "COLD_LEAD_REJECTED"
        }

    # 3. Lista de supresión / opt-out
    import zoho_bridge_service
    phone = lead_data.get("telefono") or lead_data.get("phone") or ""
    profile_url = lead_data.get("perfil_url") or ""
    email = lead_data.get("email") or ""
    is_supp, supp_reason = zoho_bridge_service.is_suppressed(
        tenant_id=tenant_id,
        email=email,
        phone=phone,
        profile_url=profile_url
    )
    if is_supp:
        return {
            "autorizado": False,
            "safe": False,
            "motivo": f"El destinatario se encuentra en la lista de supresión (Opt-out): {supp_reason}",
            "codigo": "LEAD_IN_SUPPRESSION_LIST"
        }

    # 4, 5, 6. Kill-switch, Horario comercial y cuota diaria
    return check_whatsapp_safety(conn=conn)


def get_biometric_typing_script(selector: str, message: str) -> str:
    """
    Genera un script JavaScript asíncrono para ejecutar en WhatsApp Web que simula
    la pulsación de teclas humana con cadencia no uniforme, micro-pausas y pausas
    de puntuación antes de accionar el botón de envío.
    """
    escaped_msg = json.dumps(message)
    escaped_selector = json.dumps(selector)

    return f"""
    (async () => {{
        const selector = {escaped_selector};
        const textToType = {escaped_msg};

        const targetEl = document.querySelector(selector) || 
                         document.querySelector('footer div[contenteditable="true"]') ||
                         document.querySelector('div[contenteditable="true"][data-tab="10"]');

        if (!targetEl) {{
            return {{ ok: false, error: 'No se encontró el contenedor de texto de WhatsApp Web.' }};
        }}

        targetEl.focus();

        const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

        // Limpiar contenido previo si existiese
        document.execCommand('selectAll', false, null);
        document.execCommand('delete', false, null);

        // Escritura biométrica carácter por carácter
        for (let i = 0; i < textToType.length; i++) {{
            const char = textToType[i];

            // Emular evento de entrada
            document.execCommand('insertText', false, char);
            targetEl.dispatchEvent(new Event('input', {{ bubbles: true }}));

            // Variabilidad de velocidad mecanográfica humana: 45ms a 135ms
            let keystrokeDelay = Math.floor(Math.random() * (135 - 45 + 1)) + 45;

            // Micro-pausa de reflexión tras signos de puntuación o saltos de línea
            if ([',', ';'].includes(char)) {{
                keystrokeDelay += Math.floor(Math.random() * 250) + 150;
            }} else if (['.', '!', '?', '\\n'].includes(char)) {{
                keystrokeDelay += Math.floor(Math.random() * 450) + 300;
            }}

            await sleep(keystrokeDelay);
        }}

        // Pausa de lectura visual antes de enviar (1.2 a 2.5 segundos)
        await sleep(Math.floor(Math.random() * 1300) + 1200);

        const sendBtn = document.querySelector('button[data-tab="11"]') || 
                        document.querySelector('span[data-icon="send"]')?.closest('button') ||
                        document.querySelector('button[aria-label="Enviar"]') ||
                        document.querySelector('button[aria-label="Send"]');

        if (sendBtn) {{
            sendBtn.click();
            return {{ ok: true, accion: 'mecanografia_y_envio_completados', longitud: textToType.length }};
        }}

        return {{ ok: false, error: 'Texto ingresado biometrisado pero no se halló el botón Enviar.' }};
    }})()
    """
