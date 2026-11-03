"""
Pruebas Automatizadas de Resiliencia ante Cambios de Interfaz y Selectores como Datos
NexusReach Pro - Workstream 5.8 [P1] - Directrices v1.3

Verifica:
1. Capa de abstracción de selectores con múltiples estrategias de respaldo (data-attr, aria-label, text).
2. Los selectores son datos firmados con Ed25519, no código ejecutable. Verificación de firma y rechazo de manipulación.
3. Detección de rotura de selectores mediante canarios.
4. Degradación segura: 3 fallos consecutivos pausan automáticamente la acción (ACTION_PAUSED_INTERFACE_CHANGE).
5. Sanitización de logs de fallos (cero datos personales / PII).
6. Corrección en caliente publicando un nuevo catálogo firmado que reactiva la acción sin liberar un nuevo binario.
"""

import unittest
import json
from datetime import datetime

from database import get_db, init_db
import selector_service
import canary_service
import command_signing_service


class TestInterfaceResilienceAndSelectors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM selector_failure_logs")
            cursor.execute("DELETE FROM action_status")
            cursor.execute("DELETE FROM selector_versions")
            conn.commit()

    def test_01_fallback_strategies_in_canary(self):
        """
        CRITERIO 5.8.1:
        Capa de abstracción con estrategias de respaldo:
        Si cambia el atributo primario (data-control-name), el selector de respaldo
        (aria-label o texto) localiza el elemento correctamente.
        """
        action = "LI_CONNECT_BUTTON"

        # HTML alterado donde se removió data-control-name, pero permanece aria-label y texto
        html_altered_primary = """
            <div class="custom-container">
                <button class="artdeco-button--primary" aria-label="Conectar con Gabriel Vera">
                    <span>Conectar</span>
                </button>
            </div>
        """
        res = canary_service.run_canary_test(action, html_altered_primary)
        self.assertTrue(res["ok"])
        self.assertTrue(res["matched"])
        # La estrategia usada debe ser de prioridad 2 (aria_label) o posterior
        self.assertIn(res["priority"], [2, 3])

    def test_02_signed_selector_catalog_and_tamper_rejection(self):
        """
        CRITERIO 5.8.2:
        Los selectores son datos firmados con Ed25519.
        Un paquete alterado o falsificado es rechazado tajantemente.
        """
        # 1. Catálogo legítimo firmado
        legit_pkg = selector_service.sign_selector_catalog(
            catalog=selector_service.DEFAULT_SELECTOR_CATALOG,
            version="1.0.1",
            min_client_version="1.0.0"
        )
        self.assertTrue(selector_service.verify_selector_catalog_package(legit_pkg))

        # 2. Publicación exitosa
        pub_res = selector_service.publish_selector_catalog(legit_pkg)
        self.assertTrue(pub_res["ok"])
        self.assertEqual(pub_res["version"], "1.0.1")

        # 3. Intentar publicar paquete con payload manipulado (ataque MITM)
        tampered_pkg = dict(legit_pkg)
        tampered_pkg["catalog"] = dict(legit_pkg["catalog"])
        # Alterar selector maliciosamente
        tampered_pkg["catalog"]["LI_CONNECT_BUTTON"] = {"strategies": [{"type": "malicious", "selector": "evil"}]}

        self.assertFalse(selector_service.verify_selector_catalog_package(tampered_pkg))
        with self.assertRaises(ValueError):
            selector_service.publish_selector_catalog(tampered_pkg)

    def test_03_safe_degradation_action_auto_paused(self):
        """
        CRITERIO 5.8.4 y 5.8.6:
        Degradación segura ante fallos repetidos:
        3 fallos consecutivos pausan la acción (ACTION_PAUSED_INTERFACE_CHANGE).
        La bitácora de fallos no contiene PII (nombres, correos, query params).
        """
        action = "LI_SEND_BUTTON"

        # HTML completamente roto donde nada coincide
        html_broken = "<div><p>El perfil no tiene botones de acción.</p></div>"

        # 1er fallo
        res1 = canary_service.run_canary_test(action, html_broken)
        self.assertFalse(res1["ok"])
        self.assertFalse(res1["action_paused"])

        # 2do fallo
        res2 = canary_service.run_canary_test(action, html_broken)
        self.assertFalse(res2["ok"])
        self.assertFalse(res2["action_paused"])

        # 3er fallo: Debe disparar la degradación segura
        res3 = canary_service.run_canary_test(action, html_broken)
        self.assertFalse(res3["ok"])
        self.assertTrue(res3["action_paused"])
        self.assertEqual(res3["consecutive_failures"], 3)

        # Comprobar que la acción está pausada
        is_paused, reason = selector_service.is_action_paused(action)
        self.assertTrue(is_paused)
        self.assertIn("3 fallos consecutivos", reason)

        # Verificar que la bitácora de fallos NO almacena PII
        context_with_pii = {
            "nombre": "Gabriel Vera",
            "email": "gabriel@empresa.com",
            "telefono": "+56912345678",
            "perfil_url": "https://linkedin.com/in/gabriel-test?trackingId=12345&auth=secret_token"
        }
        selector_service.record_selector_failure(action, tenant_id="ten_test", command_id="cmd_999", context=context_with_pii)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT context_json FROM selector_failure_logs WHERE command_id = 'cmd_999'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            ctx = json.loads(dict(row)["context_json"])
            # Cero PII
            self.assertNotIn("nombre", ctx)
            self.assertNotIn("email", ctx)
            self.assertNotIn("telefono", ctx)
            self.assertEqual(ctx.get("perfil_url"), "https://linkedin.com/in/gabriel-test")

    def test_04_hotfix_signed_catalog_resumes_paused_action(self):
        """
        CRITERIO 5.8.2 y 5.8.4:
        Un selector roto que causó la pausa de una acción se corrige
        publicando un nuevo catálogo firmado sin requerir recompilar el binario cliente.
        """
        action = "ZOHO_CREATE_LEAD_BTN"

        # 1. Simular que la acción fue pausada por 3 fallos
        for _ in range(3):
            selector_service.record_selector_failure(action, "ten_canary", "cmd_zoho", {"err": "Not found"})

        is_paused, _ = selector_service.is_action_paused(action)
        self.assertTrue(is_paused)

        # 2. Publicar nueva versión de catálogo (v1.1.0) con selectores actualizados
        updated_catalog = dict(selector_service.DEFAULT_SELECTOR_CATALOG)
        updated_catalog[action] = {
            "description": "Selector Zoho actualizado tras rediseño del CRM",
            "strategies": [
                {
                    "type": "css_attribute",
                    "selector": "button[data-new-zoho-action='add-lead']",
                    "priority": 1
                }
            ]
        }

        new_pkg = selector_service.sign_selector_catalog(
            catalog=updated_catalog,
            version="1.1.0",
            min_client_version="1.0.0"
        )
        selector_service.publish_selector_catalog(new_pkg)

        # 3. Comprobar que la acción fue restaurada a ACTIVE
        is_paused_now, _ = selector_service.is_action_paused(action)
        self.assertFalse(is_paused_now)

        # 4. Comprobar que el canario contra el nuevo diseño pasa con la nueva estrategia
        new_zoho_html = '<div class="new-ui"><button data-new-zoho-action="add-lead">Nuevo Lead</button></div>'
        canary_res = canary_service.run_canary_test(action, new_zoho_html)
        self.assertTrue(canary_res["ok"])
        self.assertEqual(canary_res["priority"], 1)

    def test_05_standard_canary_suite_all_pass(self):
        """
        CRITERIO 5.8.3:
        Pruebas de contrato periódicas: todas las acciones estándar pasan
        satisfactoriamente el 100% de los fixtures canarios.
        """
        audit = canary_service.run_full_canary_suite()
        self.assertTrue(audit["all_healthy"])
        self.assertEqual(audit["failed"], 0)
        self.assertGreaterEqual(audit["passed"], 6)


if __name__ == "__main__":
    unittest.main()
