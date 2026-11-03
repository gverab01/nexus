"""
Servicio de Resiliencia ante Cambios de Interfaz y Selectores como Datos (Workstream 5.8)
NexusReach Pro - Directrices v1.3

Principios:
1. Capa de abstracción de selectores: acción -> localización con múltiples estrategias de respaldo.
2. Los selectores son DATOS, no código. Catálogo versionado y firmado criptográficamente (Ed25519).
   NUNCA enviar código ejecutable ni JavaScript arbitrario.
3. Degradación segura: si una acción falla repetidamente (>= 3 fallos consecutivos), se pausa
   la acción para evitar bucles o bloqueos (ACTION_PAUSED_INTERFACE_CHANGE).
4. Telemetría de fallos sin datos personales (PII).
5. Publicación y actualización remota de selectores firmados que reactiva acciones sin compilar binarios.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List

from database import get_db
import command_signing_service

# Versión mínima de cliente soportada
DEFAULT_MIN_CLIENT_VERSION = "1.0.0"

# Catálogo base por defecto (versión 1.0.0)
DEFAULT_SELECTOR_CATALOG: Dict[str, Dict[str, Any]] = {
    "LI_CONNECT_BUTTON": {
        "description": "Botón para conectar o enviar invitación en perfil de LinkedIn",
        "strategies": [
            {
                "type": "css_attribute",
                "selector": "button[data-control-name='connect']",
                "priority": 1
            },
            {
                "type": "aria_label",
                "selector": "button[aria-label*='Conectar'], button[aria-label*='Connect']",
                "priority": 2
            },
            {
                "type": "text_content",
                "selector": "button:has(span)",
                "text_match": ["Conectar", "Connect"],
                "priority": 3
            },
            {
                "type": "structural",
                "selector": "div.pvs-profile-actions button",
                "priority": 4
            }
        ]
    },
    "LI_ADD_NOTE_BUTTON": {
        "description": "Botón para añadir nota personalizada a la invitación de LinkedIn",
        "strategies": [
            {
                "type": "aria_label",
                "selector": "button[aria-label*='nota'], button[aria-label*='note']",
                "priority": 1
            },
            {
                "type": "text_content",
                "selector": "button:has(span)",
                "text_match": ["Añadir nota", "Add a note", "Agregar nota"],
                "priority": 2
            },
            {
                "type": "css_class",
                "selector": "button.artdeco-button--secondary",
                "priority": 3
            }
        ]
    },
    "LI_MESSAGE_TEXTAREA": {
        "description": "Área de texto para el mensaje de invitación o seguimiento en LinkedIn",
        "strategies": [
            {
                "type": "css_id_or_name",
                "selector": "textarea[name='message'], #custom-message",
                "priority": 1
            },
            {
                "type": "aria_label",
                "selector": "div[role='textbox'][aria-label*='mensaje'], div[role='textbox'][aria-label*='message']",
                "priority": 2
            },
            {
                "type": "structural",
                "selector": "textarea",
                "priority": 3
            }
        ]
    },
    "LI_SEND_BUTTON": {
        "description": "Botón de confirmación y envío final en LinkedIn",
        "strategies": [
            {
                "type": "aria_label",
                "selector": "button[aria-label*='Enviar ahora'], button[aria-label*='Send now'], button[aria-label*='Enviar invitación'], button[aria-label*='Send invitation']",
                "priority": 1
            },
            {
                "type": "text_content",
                "selector": "button.artdeco-button--primary:has(span)",
                "text_match": ["Enviar", "Send", "Enviar ahora", "Send now"],
                "priority": 2
            },
            {
                "type": "structural",
                "selector": "div.artdeco-modal__actionbar button.artdeco-button--primary",
                "priority": 3
            }
        ]
    },
    "WA_CHAT_INPUT": {
        "description": "Área de entrada de texto editable en WhatsApp Web",
        "strategies": [
            {
                "type": "css_attribute",
                "selector": "footer div[contenteditable='true'][data-tab='10']",
                "priority": 1
            },
            {
                "type": "structural",
                "selector": "footer div[contenteditable='true']",
                "priority": 2
            },
            {
                "type": "aria_label",
                "selector": "div[role='textbox'][contenteditable='true']",
                "priority": 3
            }
        ]
    },
    "WA_SEND_BUTTON": {
        "description": "Botón de enviar mensaje en WhatsApp Web",
        "strategies": [
            {
                "type": "css_attribute",
                "selector": "button[data-tab='11'], span[data-icon='send']",
                "priority": 1
            },
            {
                "type": "aria_label",
                "selector": "button[aria-label*='Enviar'], button[aria-label*='Send']",
                "priority": 2
            }
        ]
    },
    "ZOHO_CREATE_LEAD_BTN": {
        "description": "Botón para crear un nuevo contacto/lead en Zoho CRM",
        "strategies": [
            {
                "type": "css_attribute",
                "selector": "button[data-action='create-lead'], button#createLeadBtn",
                "priority": 1
            },
            {
                "type": "aria_label",
                "selector": "button[aria-label*='Crear'], button[aria-label*='Create Lead']",
                "priority": 2
            },
            {
                "type": "structural",
                "selector": "div.crm-actions button.primary",
                "priority": 3
            }
        ]
    }
}


def sanitize_context_without_pii(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitiza el contexto de un fallo para diagnóstico sin almacenar PII (Directriz 5.8.6 y 6.8).
    Elimina nombres, emails, tokens, teléfonos y query params de URLs.
    """
    sanitized = {}
    forbidden_keys = {"email", "telefono", "phone", "nombre", "name", "token", "password", "clave", "auth"}
    
    for k, v in context.items():
        if k.lower() in forbidden_keys:
            continue
        if k in ("url", "perfil_url") and isinstance(v, str):
            # Eliminar query strings y fragmentos
            base_url = v.split("?")[0].split("#")[0]
            sanitized[k] = base_url
        else:
            sanitized[k] = v
    return sanitized


def sign_selector_catalog(
    catalog: Dict[str, Any],
    version: str = "1.0.0",
    min_client_version: str = DEFAULT_MIN_CLIENT_VERSION
) -> Dict[str, Any]:
    """
    Genera el paquete firmado del catálogo de selectores mediante Ed25519.
    """
    payload_to_sign = {
        "version": version,
        "min_client_version": min_client_version,
        "catalog": catalog
    }
    signature = command_signing_service.sign_command_payload(payload_to_sign)
    return {
        "version": version,
        "min_client_version": min_client_version,
        "catalog": catalog,
        "signature": signature
    }


def verify_selector_catalog_package(package: Dict[str, Any]) -> bool:
    """
    Verifica criptográficamente que el paquete de selectores provenga del backend oficial
    y no haya sido alterado en tránsito.
    """
    signature = package.get("signature")
    if not signature:
        return False

    payload_to_verify = {
        "version": package.get("version"),
        "min_client_version": package.get("min_client_version", DEFAULT_MIN_CLIENT_VERSION),
        "catalog": package.get("catalog", {})
    }
    return command_signing_service.verify_server_command_signature(payload_to_verify, signature)


def publish_selector_catalog(
    catalog_package: Dict[str, Any],
    conn=None
) -> Dict[str, Any]:
    """
    Publica una nueva versión de catálogo firmado en la base de datos.
    Verifica la firma antes de almacenar y activa la versión.
    Si una acción estaba pausada y el nuevo catálogo contiene selectores para ella, la reactiva.
    """
    if not verify_selector_catalog_package(catalog_package):
        raise ValueError("Firma criptográfica inválida del catálogo de selectores. Publicación rechazada.")

    version = catalog_package["version"]
    min_client_ver = catalog_package.get("min_client_version", DEFAULT_MIN_CLIENT_VERSION)
    catalog_json = json.dumps(catalog_package["catalog"])
    signature = catalog_package["signature"]
    now_iso = datetime.now(timezone.utc).isoformat()

    def _persist(c):
        cursor = c.cursor()
        # Desactivar versiones previas
        cursor.execute("UPDATE selector_versions SET is_active = 0")
        # Insertar o actualizar la versión publicada
        cursor.execute("""
            INSERT OR REPLACE INTO selector_versions 
            (version, catalog_json, signature, min_client_version, is_active, published_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (version, catalog_json, signature, min_client_ver, now_iso))

        # Reactivar acciones pausadas si el nuevo catálogo cubre la acción
        catalog = catalog_package["catalog"]
        for action_name in catalog.keys():
            cursor.execute("""
                UPDATE action_status 
                SET status = 'ACTIVE', pause_reason = NULL, consecutive_failures = 0, updated_at = ?
                WHERE action = ? AND status = 'PAUSED'
            """, (now_iso, action_name))

    if conn is not None:
        _persist(conn)
    else:
        with get_db() as c:
            _persist(c)

    return {
        "ok": True,
        "version": version,
        "min_client_version": min_client_ver,
        "published_at": now_iso
    }


def get_active_selector_catalog(conn=None) -> Dict[str, Any]:
    """
    Obtiene la versión activa de los selectores firmados. Si no hay en base de datos,
    publica y retorna el DEFAULT_SELECTOR_CATALOG firmado.
    """
    def _query(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT version, catalog_json, signature, min_client_version, published_at
            FROM selector_versions
            WHERE is_active = 1
            ORDER BY published_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None
        row_dict = dict(row)
        return {
            "version": row_dict["version"],
            "catalog": json.loads(row_dict["catalog_json"]),
            "signature": row_dict["signature"],
            "min_client_version": row_dict["min_client_version"],
            "published_at": row_dict["published_at"]
        }

    active_pkg = None
    if conn is not None:
        active_pkg = _query(conn)
    else:
        with get_db() as c:
            active_pkg = _query(c)

    if not active_pkg:
        # Inicializar con el default firmado
        default_pkg = sign_selector_catalog(DEFAULT_SELECTOR_CATALOG, "1.0.0", DEFAULT_MIN_CLIENT_VERSION)
        publish_selector_catalog(default_pkg, conn=conn)
        return default_pkg

    return active_pkg


def get_selectors_for_action(action: str, conn=None) -> List[Dict[str, Any]]:
    """
    Retorna la lista ordenada de estrategias de localización para una acción específica.
    """
    active_pkg = get_active_selector_catalog(conn=conn)
    catalog = active_pkg.get("catalog", {})
    action_info = catalog.get(action, {})
    strategies = action_info.get("strategies", [])
    # Ordenar por prioridad ascendente (1 es mayor prioridad)
    return sorted(strategies, key=lambda s: s.get("priority", 99))


# ==============================================================================
# DEGRADACIÓN SEGURA Y CONTROL DE ESTADO DE ACCIONES
# ==============================================================================

MAX_CONSECUTIVE_FAILURES_THRESHOLD = 3


def record_selector_failure(
    action: str,
    tenant_id: Optional[str] = None,
    command_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Registra un fallo de selector en la bitácora sanitizada.
    Incrementa el contador de fallos consecutivos de la acción.
    Si alcanza el umbral (>= 3), pausa inmediatamente la acción para proteger las cuentas.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_ctx = sanitize_context_without_pii(context or {})
    clean_ctx_json = json.dumps(clean_ctx)
    log_id = str(uuid.uuid4())

    def _update(c):
        cursor = c.cursor()
        # 1. Registrar fallo sanitizado
        cursor.execute("""
            INSERT INTO selector_failure_logs (id, action, tenant_id, command_id, context_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (log_id, action, tenant_id, command_id, clean_ctx_json, now_iso))

        # 2. Consultar o inicializar estado de la acción
        cursor.execute("SELECT status, consecutive_failures FROM action_status WHERE action = ?", (action,))
        row = cursor.fetchone()

        if row:
            curr_fails = (dict(row).get("consecutive_failures") or 0) + 1
        else:
            curr_fails = 1

        new_status = "ACTIVE"
        pause_reason = None
        action_paused = False

        if curr_fails >= MAX_CONSECUTIVE_FAILURES_THRESHOLD:
            new_status = "PAUSED"
            pause_reason = f"Degradación segura activada: {curr_fails} fallos consecutivos de selector detectados."
            action_paused = True

        cursor.execute("""
            INSERT OR REPLACE INTO action_status (action, status, pause_reason, consecutive_failures, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (action, new_status, pause_reason, curr_fails, now_iso))

        return {
            "action": action,
            "consecutive_failures": curr_fails,
            "status": new_status,
            "action_paused": action_paused,
            "pause_reason": pause_reason
        }

    if conn is not None:
        return _update(conn)
    else:
        with get_db() as c:
            return _update(c)


def is_action_paused(action: str, conn=None) -> Tuple[bool, str]:
    """
    Verifica si una acción está pausada por degradación segura ante cambios de interfaz.
    """
    def _check(c):
        cursor = c.cursor()
        cursor.execute("SELECT status, pause_reason FROM action_status WHERE action = ?", (action,))
        row = cursor.fetchone()
        if not row:
            return False, ""
        r = dict(row)
        if r.get("status") == "PAUSED":
            return True, r.get("pause_reason") or "Acción pausada preventivamente por degradación de interfaz."
        return False, ""

    if conn is not None:
        return _check(conn)
    else:
        with get_db() as c:
            return _check(c)


def resume_action(action: str, reason: str = "Recuperada manualmente o por canario", conn=None) -> None:
    """
    Restaura el estado de una acción a ACTIVE y resetea los fallos consecutivos.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    def _res(c):
        cursor = c.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO action_status (action, status, pause_reason, consecutive_failures, updated_at)
            VALUES (?, 'ACTIVE', NULL, 0, ?)
        """, (action, now_iso))

    if conn is not None:
        _res(conn)
    else:
        with get_db() as c:
            _res(c)


def get_all_actions_status(conn=None) -> List[Dict[str, Any]]:
    """Retorna la lista de acciones y su estado de salud actual."""
    def _list(c):
        cursor = c.cursor()
        cursor.execute("SELECT * FROM action_status ORDER BY action ASC")
        return [dict(r) for r in cursor.fetchall()]

    if conn is not None:
        return _list(conn)
    else:
        with get_db() as c:
            return _list(c)
