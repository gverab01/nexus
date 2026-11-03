"""
Servicio de Canarios y Pruebas de Contrato de Selectores (Workstream 5.8)
NexusReach Pro - Directrices v1.3

Funciones:
1. Pruebas de contrato continuas contra fixtures DOM / cuentas de prueba (canarios).
2. Evaluación determinista de estrategias de localización por orden de prioridad:
   - Atributos semánticos / estables (data-control-name, data-tab, etc.)
   - Accesibilidad (aria-label)
   - Contenido de texto accesible
   - Selectores estructurales
3. Detección automática de rotura de interfaz.
4. Auto-pausa de la acción afectada (degradación segura) tras fallos repetidos.
5. Verificación de que una nueva versión de catálogo firmado reactiva la acción.
"""

import re
import html
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional, Tuple

import selector_service


# ==============================================================================
# 1. PARSER LIGERO DE ESTRATEGIAS HTML PARA CANARIOS
# ==============================================================================

class SimpleDOMElement:
    def __init__(self, tag: str, attrs: Dict[str, str]):
        self.tag = tag.lower()
        self.attrs = {k.lower(): v for k, v in attrs.items()}
        self.text_content = ""

    def get_attr(self, name: str) -> Optional[str]:
        return self.attrs.get(name.lower())

    def matches_attribute_selector(self, attr_name: str, op: str, value: str) -> bool:
        attr_val = self.get_attr(attr_name)
        if attr_val is None:
            return False
        attr_val = attr_val.lower()
        val = value.lower()
        if op == "=":
            return attr_val == val
        elif op == "*=":
            return val in attr_val
        elif op == "^=":
            return attr_val.startswith(val)
        elif op == "$=":
            return attr_val.endswith(val)
        return False


class MiniDOMParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: List[SimpleDOMElement] = []
        self._current_el: Optional[SimpleDOMElement] = None

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        el = SimpleDOMElement(tag, attr_dict)
        self.elements.append(el)
        self._current_el = el

    def handle_data(self, data):
        if self._current_el:
            self._current_el.text_content += data

    def handle_endtag(self, tag):
        self._current_el = None


def parse_html_to_elements(html_str: str) -> List[SimpleDOMElement]:
    parser = MiniDOMParser()
    parser.feed(html_str)
    return parser.elements


# ==============================================================================
# 2. EVALUADOR DE ESTRATEGIAS DE LOCALIZACIÓN
# ==============================================================================

ATTR_PATTERN = re.compile(r'\[([a-zA-Z0-9_\-]+)([\*\^\$]?=)[\'"]?([^\'"\]]+)[\'"]?\]')


def evaluate_strategy_against_elements(strategy: Dict[str, Any], elements: List[SimpleDOMElement]) -> bool:
    """
    Evalúa si la estrategia coincide con algún elemento de la lista de elementos DOM parseados.
    """
    strat_type = strategy.get("type", "")
    selector_str = strategy.get("selector", "")
    text_matches = [t.lower() for t in strategy.get("text_match", [])]

    # Estrategia por coincidencia de texto
    if strat_type == "text_content" or text_matches:
        for el in elements:
            el_text = el.text_content.strip().lower()
            for tm in text_matches:
                if tm in el_text:
                    return True

    # Estrategia por selectores CSS / atributos (data-*, aria-label, etc.)
    sub_selectors = [s.strip() for s in selector_str.split(",")]
    for sub in sub_selectors:
        # Extraer tag si existe (ej. button[data-...])
        tag_match = re.match(r'^([a-zA-Z0-9]+)', sub)
        expected_tag = tag_match.group(1).lower() if tag_match else None

        attr_matches = ATTR_PATTERN.findall(sub)
        
        # Verificar contra cada elemento
        for el in elements:
            if expected_tag and el.tag != expected_tag:
                continue

            # Si hay selectores de atributo
            if attr_matches:
                all_attrs_match = True
                for attr_name, op, val in attr_matches:
                    if not el.matches_attribute_selector(attr_name, op or "=", val):
                        all_attrs_match = False
                        break
                if all_attrs_match:
                    return True

            # Si busca por clase CSS pura (ej. .artdeco-button--secondary)
            if "." in sub and not attr_matches:
                class_names = re.findall(r'\.([a-zA-Z0-9_\-]+)', sub)
                el_class = el.get_attr("class") or ""
                if all(c in el_class for c in class_names):
                    return True

            # Selector estructural simple (ej. textarea)
            if sub.strip().lower() == el.tag and not attr_matches and "." not in sub:
                return True

    return False


# ==============================================================================
# 3. FIXTURES CANARIO ESTÁNDAR
# ==============================================================================

STANDARD_CANARY_FIXTURES: Dict[str, str] = {
    "LI_CONNECT_BUTTON": """
        <div class="pvs-profile-actions">
            <button data-control-name="connect" class="artdeco-button--primary" aria-label="Conectar con Gabriel Vera">
                <span>Conectar</span>
            </button>
        </div>
    """,
    "LI_ADD_NOTE_BUTTON": """
        <div class="artdeco-modal__actionbar">
            <button class="artdeco-button--secondary" aria-label="Añadir nota a la invitación">
                <span>Añadir nota</span>
            </button>
        </div>
    """,
    "LI_MESSAGE_TEXTAREA": """
        <div class="send-invite">
            <textarea name="message" id="custom-message" rows="5" placeholder="Escribe una nota..."></textarea>
        </div>
    """,
    "LI_SEND_BUTTON": """
        <div class="artdeco-modal__actionbar">
            <button class="artdeco-button--primary" aria-label="Enviar ahora">
                <span>Enviar ahora</span>
            </button>
        </div>
    """,
    "WA_CHAT_INPUT": """
        <footer>
            <div role="textbox" contenteditable="true" data-tab="10" class="selectable-text copyable-text">
                Hola, un gusto saludarte.
            </div>
        </footer>
    """,
    "WA_SEND_BUTTON": """
        <footer>
            <button data-tab="11" aria-label="Enviar">
                <span data-icon="send"></span>
            </button>
        </footer>
    """,
    "ZOHO_CREATE_LEAD_BTN": """
        <div class="crm-actions">
            <button data-action="create-lead" id="createLeadBtn" aria-label="Crear Posible Cliente" class="primary">
                Crear
            </button>
        </div>
    """
}


# ==============================================================================
# 4. EJECUTOR DE AUDITORÍAS CANARIO
# ==============================================================================

def run_canary_test(
    action: str,
    html_content: str,
    tenant_id: str = "canary_system",
    conn=None
) -> Dict[str, Any]:
    """
    Ejecuta la prueba de contrato canario para una acción contra el HTML provisto.
    Evalúa las estrategias registradas en orden de prioridad.
    - Si una estrategia tiene éxito: reactiva la acción si estaba en fallo.
    - Si todas las estrategias fallan: registra el fallo y puede activar la auto-pausa de la acción.
    """
    elements = parse_html_to_elements(html_content)
    strategies = selector_service.get_selectors_for_action(action, conn=conn)

    for strat in strategies:
        matched = evaluate_strategy_against_elements(strat, elements)
        if matched:
            # Éxito: la estrategia funciona
            is_paused, _ = selector_service.is_action_paused(action, conn=conn)
            if is_paused:
                selector_service.resume_action(action, reason="Canario exitoso recuperó la acción", conn=conn)

            return {
                "ok": True,
                "action": action,
                "matched": True,
                "strategy_used": strat,
                "priority": strat.get("priority", 1),
                "type": strat.get("type", "")
            }

    # Ninguna estrategia coincidió -> rotura de interfaz detectada por el canario
    fail_report = selector_service.record_selector_failure(
        action=action,
        tenant_id=tenant_id,
        command_id="canary_run",
        context={
            "error": "CANARY_FAILED_SELECTOR_BREAK",
            "action": action,
            "strategies_tested_count": len(strategies)
        },
        conn=conn
    )

    return {
        "ok": False,
        "action": action,
        "matched": False,
        "error": "CANARY_FAILED_SELECTOR_BREAK",
        "action_paused": fail_report.get("action_paused", False),
        "consecutive_failures": fail_report.get("consecutive_failures", 1),
        "pause_reason": fail_report.get("pause_reason")
    }


def run_full_canary_suite(
    custom_fixtures: Optional[Dict[str, str]] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Audita todas las acciones soportadas contra sus fixtures canario.
    """
    fixtures = custom_fixtures or STANDARD_CANARY_FIXTURES
    results = {}
    total_passed = 0
    total_failed = 0

    for action, html_snip in fixtures.items():
        res = run_canary_test(action, html_snip, tenant_id="canary_system", conn=conn)
        results[action] = res
        if res.get("ok"):
            total_passed += 1
        else:
            total_failed += 1

    return {
        "total_actions": len(fixtures),
        "passed": total_passed,
        "failed": total_failed,
        "all_healthy": total_failed == 0,
        "details": results
    }
