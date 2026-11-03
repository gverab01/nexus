"""
Suite de Pruebas Unitarias y de Integración para el Hito 4:
Multichannel Anti-Ban Suite & Zoho CRM Browser-Session Intelligence (NexusReach Pro)

Pruebas cubiertas:
1. Curva de calentamiento (Warm-up) y límites dinámicos de LinkedIn.
2. Medidor y alertas de límite comercial de búsquedas mensuales en LinkedIn.
3. Detección y retiro de invitaciones pendientes envejecidas en LinkedIn.
4. Normalización E.164, bloqueo de enlaces y detección de opt-out en WhatsApp Web.
5. Generación de mecanografía biométrica humana con pausas y respiración.
6. Sanitización COQL y algoritmo de normalización para Zoho CRM.
7. Sincronización y persistencia de campos zoho_* en la base de datos de leads.
8. Verificación de endpoints FastAPI expuestos en main.py.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Asegurar path al directorio raíz del proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import get_db, init_db
import safety_engine
import whatsapp_safety_engine
import zoho_browser_service
from main import (
    get_zoho_session_status,
    get_whatsapp_safety_status,
    get_linkedin_warmup_status_endpoint,
    get_safety_status,
    get_browser_status
)


class TestHito4MultichannelSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    # =========================================================================
    # 1. LINKEDIN WARM-UP & COMMERCIAL SEARCH TRACKER
    # =========================================================================
    def test_linkedin_warmup_calculation(self):
        """Verifica que la curva de calentamiento calcule límites progresivos según el día actual."""
        config_day_1 = {
            "warmup_dia_actual": "1",
            "warmup_limite_inicial": "3",
            "warmup_incremento_diario": "1",
            "warmup_limite_maximo": "20"
        }
        res_d1 = safety_engine.get_linkedin_warmup_status(config=config_day_1)
        self.assertEqual(res_d1["dia_actual"], 1)
        self.assertEqual(res_d1["limite_recomendado_hoy"], 3)
        self.assertTrue(res_d1["en_calentamiento"])

        config_day_5 = {
            "warmup_dia_actual": "5",
            "warmup_limite_inicial": "3",
            "warmup_incremento_diario": "1",
            "warmup_limite_maximo": "20"
        }
        res_d5 = safety_engine.get_linkedin_warmup_status(config=config_day_5)
        # Día 5: 3 + (5-1)*1 = 7
        self.assertEqual(res_d5["limite_recomendado_hoy"], 7)

        config_day_30 = {
            "warmup_dia_actual": "30",
            "warmup_limite_inicial": "3",
            "warmup_incremento_diario": "1",
            "warmup_limite_maximo": "15"
        }
        res_d30 = safety_engine.get_linkedin_warmup_status(config=config_day_30)
        self.assertEqual(res_d30["limite_recomendado_hoy"], 15)
        self.assertFalse(res_d30["en_calentamiento"])

    def test_linkedin_search_meter_and_warning(self):
        """Verifica que el medidor de búsquedas registre el uso y alerte al aproximarse al límite comercial."""
        with get_db() as conn:
            # Forzar valores de prueba
            safety_engine.set_safety_config_val("linkedin_busquedas_mes", "75", conn)
            status = safety_engine.get_linkedin_search_usage(conn)
            self.assertEqual(status["busquedas_mes"], 75)
            self.assertEqual(status["umbral_alerta"], 80)
            self.assertFalse(status["alerta_limite"])

            # Superar límite
            safety_engine.track_linkedin_search(increment=10, conn=conn)
            status_after = safety_engine.get_linkedin_search_usage(conn)
            self.assertEqual(status_after["busquedas_mes"], 85)
            self.assertTrue(status_after["alerta_limite"])

    def test_stale_invitations_detection_and_withdrawal(self):
        """Verifica la detección y marcado de invitaciones pendientes con más de 21 días."""
        now = datetime.now()
        antigua_iso = (now - timedelta(days=25)).isoformat()
        reciente_iso = (now - timedelta(days=5)).isoformat()

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, fecha_invitacion, created_at, updated_at)
                VALUES ('lead_antiguo_1', 'org_master', 'Lead Antiguo Test', 'https://linkedin.com/in/antiguo', 'INVITACION_ENVIADA', ?, ?, ?)
            """, (antigua_iso, antigua_iso, antigua_iso))
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, fecha_invitacion, created_at, updated_at)
                VALUES ('lead_reciente_1', 'org_master', 'Lead Reciente Test', 'https://linkedin.com/in/reciente', 'INVITACION_ENVIADA', ?, ?, ?)
            """, (reciente_iso, reciente_iso, reciente_iso))

            stale = safety_engine.get_stale_pending_invitations(conn=conn, days_threshold=21)
            stale_ids = [s["id"] for s in stale]
            self.assertIn("lead_antiguo_1", stale_ids)
            self.assertNotIn("lead_reciente_1", stale_ids)

            # Retirar invitaciones
            withdrawn = safety_engine.withdraw_stale_invitations(days_threshold=21, conn=conn)
            self.assertGreaterEqual(withdrawn["invitaciones_retiradas"], 1)

            cursor.execute("SELECT invitacion_retirada FROM leads WHERE id = 'lead_antiguo_1'")
            row = cursor.fetchone()
            val = row["invitacion_retirada"] if isinstance(row, dict) else row[0]
            self.assertEqual(val, 1)

            # Limpiar datos de prueba
            cursor.execute("DELETE FROM leads WHERE id IN ('lead_antiguo_1', 'lead_reciente_1')")

    # =========================================================================
    # 2. WHATSAPP WEB ANTI-BAN ENGINE
    # =========================================================================
    def test_whatsapp_phone_normalization(self):
        """Verifica la normalización rigurosa de números a formato E.164."""
        self.assertEqual(whatsapp_safety_engine.normalize_phone_number("912345678"), "+56912345678")
        self.assertEqual(whatsapp_safety_engine.normalize_phone_number("56912345678"), "+56912345678")
        self.assertEqual(whatsapp_safety_engine.normalize_phone_number("+56 9 1234 5678"), "+56912345678")
        self.assertEqual(whatsapp_safety_engine.normalize_phone_number("12345678"), "+56912345678")
        self.assertEqual(whatsapp_safety_engine.normalize_phone_number("+1 415 555 2671"), "+14155552671")
        self.assertIsNone(whatsapp_safety_engine.normalize_phone_number("abc"))
        self.assertIsNone(whatsapp_safety_engine.normalize_phone_number("123"))

    def test_whatsapp_link_blocking_on_first_touch(self):
        """Verifica que el envío de URLs en el primer contacto frío sea bloqueado por seguridad."""
        valid, _ = whatsapp_safety_engine.validate_message_links("Hola Gabriel, un gusto saludarte.", is_first_contact=True)
        self.assertTrue(valid)

        invalid_http, msg1 = whatsapp_safety_engine.validate_message_links("Mira nuestra demo en http://sitio.com", is_first_contact=True)
        self.assertFalse(invalid_http)
        self.assertIn("enlaces", msg1)

        invalid_www, msg2 = whatsapp_safety_engine.validate_message_links("Visita www.ejemplo.cl hoy", is_first_contact=True)
        self.assertFalse(invalid_www)

        invalid_domain, msg3 = whatsapp_safety_engine.validate_message_links("Entra en miportal.io/agenda", is_first_contact=True)
        self.assertFalse(invalid_domain)

        # Si no es primer contacto, debe permitirse
        allowed, _ = whatsapp_safety_engine.validate_message_links("Aquí está el link: https://ejemplo.com", is_first_contact=False)
        self.assertTrue(allowed)

    def test_whatsapp_opt_out_detection(self):
        """Verifica la detección automática de palabras clave de baja para evitar reportes por spam."""
        self.assertTrue(whatsapp_safety_engine.check_opt_out_keywords("No gracias, no me interesa"))
        self.assertTrue(whatsapp_safety_engine.check_opt_out_keywords("Por favor dar de baja mi número"))
        self.assertTrue(whatsapp_safety_engine.check_opt_out_keywords("STOP"))
        self.assertTrue(whatsapp_safety_engine.check_opt_out_keywords("cancelar suscripción"))
        self.assertFalse(whatsapp_safety_engine.check_opt_out_keywords("Hola, me gustaría agendar una llamada"))

    def test_whatsapp_delay_bounds(self):
        """Verifica que el generador de pausas gaussianas respete los límites estocásticos configurados."""
        cfg = {"whatsapp_pausa_min_seg": 360, "whatsapp_pausa_max_seg": 900}
        for _ in range(10):
            d = whatsapp_safety_engine.calculate_whatsapp_delay(config=cfg)
            self.assertGreaterEqual(d, 360)
            self.assertLessEqual(d, 900)

    def test_whatsapp_biometric_typing_script(self):
        """Verifica la generación del script de mecanografía biométrica humana."""
        script = whatsapp_safety_engine.get_biometric_typing_script(
            selector='footer div[contenteditable="true"]',
            message="Hola, ¿cómo estás? Quería comentarte una propuesta."
        )
        self.assertIn("insertText", script)
        self.assertIn("keystrokeDelay", script)
        self.assertIn("footer div[contenteditable=\"true\"]", script)
        self.assertIn("data-tab=\"11\"", script)

    # =========================================================================
    # 3. ZOHO CRM BROWSER-SESSION INTELLIGENCE
    # =========================================================================
    def test_zoho_text_sanitization_and_normalization(self):
        """Verifica la sanitización para COQL y la normalización de nombres educativos con prefijos."""
        clean = zoho_browser_service.clean_text_for_coql("L'Oreal & O'Connor")
        self.assertEqual(clean, "L\\'Oreal & O\\'Connor")

        norm1 = zoho_browser_service.normalize_search_term("9799 - Complejo San Agustín - Gabriel Vera")
        self.assertEqual(norm1, "Gabriel Vera")

        norm2 = zoho_browser_service.normalize_search_term("María José Valenzuela")
        self.assertEqual(norm2, "Maria Jose Valenzuela")

    @patch("zoho_browser_service.execute_zoho_coql")
    def test_zoho_sync_lead_flow(self, mock_coql):
        """Verifica el cruce completo de un lead con Zoho CRM extrayendo email, cuenta, dueño y tratos."""
        # 1. Crear lead de prueba en DB
        now_iso = datetime.now().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, institucion_actual, estado, created_at, updated_at)
                VALUES ('lead_zoho_test_1', 'org_master', 'Gabriel Director', 'https://linkedin.com/in/gdirector', 'Colegio Los Andes', 'EXTRAIDO', ?, ?)
            """, (now_iso, now_iso))

        # 2. Mockear respuestas COQL
        def fake_coql(query, org_id="902879914"):
            q_lower = query.lower()
            if "contacts" in q_lower:
                return {
                    "ok": True,
                    "data": [{
                        "id": "7052016000001234567",
                        "Full_Name": "Gabriel Director",
                        "Email": "gabriel.director@losandes.cl",
                        "Account_Name": {"id": "acc_999", "name": "Colegio Los Andes"},
                        "Owner": {"id": "usr_111", "name": "Ejecutivo Ventas A"}
                    }]
                }
            elif "accounts" in q_lower:
                return {
                    "ok": True,
                    "data": [{
                        "id": "acc_999",
                        "Account_Name": "Colegio Los Andes",
                        "Account_Type": "Cliente Activo",
                        "Owner": {"id": "usr_222", "name": "Account Manager B"}
                    }]
                }
            elif "deals" in q_lower:
                return {
                    "ok": True,
                    "data": [{
                        "id": "deal_555",
                        "Deal_Name": "Licencia Anual 2026",
                        "Stage": "Negociación",
                        "Amount": 12500000,
                        "Closing_Date": "2026-12-15",
                        "Owner": {"id": "usr_111", "name": "Ejecutivo Ventas A"}
                    }]
                }
            return {"ok": True, "data": []}

        mock_coql.side_effect = fake_coql

        # 3. Ejecutar sincronización
        res = zoho_browser_service.sync_lead_with_zoho("lead_zoho_test_1")
        self.assertTrue(res["ok"])
        self.assertTrue(res["matched"])
        self.assertEqual(res["entity_type"], "Contact")
        self.assertEqual(res["email_zoho"], "gabriel.director@losandes.cl")
        self.assertEqual(res["account_name"], "Colegio Los Andes")
        self.assertEqual(res["account_owner"], "Account Manager B")
        self.assertTrue(res["account_is_client"])
        self.assertEqual(res["deals_count"], 1)

        # 4. Verificar persistencia en base de datos
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads WHERE id = 'lead_zoho_test_1'")
            lead = cursor.fetchone()
            d = dict(lead)
            self.assertEqual(d["email_zoho"], "gabriel.director@losandes.cl")
            self.assertEqual(d["zoho_entidad_tipo"], "Contact")
            self.assertEqual(d["zoho_cuenta_es_cliente"], 1)
            self.assertEqual(d["zoho_cuenta_dueno"], "Account Manager B")
            self.assertIsNotNone(d["zoho_synced_at"])
            self.assertIsNotNone(d["zoho_email_extracted_at"])
            self.assertIn("Licencia Anual 2026", d["zoho_tratos_info"])

            # Limpieza
            cursor.execute("DELETE FROM leads WHERE id = 'lead_zoho_test_1'")

    # =========================================================================
    # 4. REST API ENDPOINTS (MAIN.PY)
    # =========================================================================
    def test_api_endpoints_hito4(self):
        """Verifica que todos los nuevos endpoints de Zoho, WhatsApp y Warm-up respondan correctamente en FastAPI."""
        # 4.1 Zoho Session Endpoint
        data_z = get_zoho_session_status()
        self.assertIn("active", data_z)
        self.assertIn("org_id", data_z)

        # 4.2 WhatsApp Safety Endpoint
        data_wa = get_whatsapp_safety_status()
        self.assertIn("seguridad", data_wa)
        self.assertIn("uso_diario", data_wa)
        self.assertIn("pausa_sugerida_segundos", data_wa)

        # 4.3 LinkedIn Warm-up Endpoint
        data_wu = get_linkedin_warmup_status_endpoint()
        self.assertIn("warmup", data_wu)
        self.assertIn("busquedas_comerciales", data_wu)

        # 4.4 Global Safety Status Endpoint
        data_s = get_safety_status()
        self.assertIn("whatsapp", data_s)
        self.assertIn("linkedin_warmup", data_s)
        self.assertIn("linkedin_busquedas", data_s)

        # 4.5 Browser Status Endpoint (con detección de sesión Zoho)
        data_b = get_browser_status()
        self.assertIn("sesion_zoho_activa", data_b)
        self.assertIn("sesion_whatsapp_activa", data_b)
        self.assertIn("sesion_linkedin_activa", data_b)


if __name__ == "__main__":
    unittest.main()
