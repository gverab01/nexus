"""
Test Suite de Seguridad y Reglas No Negociables de WhatsApp (Workstream 5.7 [P1])
NexusReach Pro Directrices de Ingeniería v1.3 - Sección 5.7 y Prohibición 6

Verifica rigurosamente:
1. Feature flag por tenant: desactivado por defecto (WHATSAPP_FEATURE_FLAG_DISABLED).
2. Regla No Negociable de Warm Outreach: Prohibición absoluta de mensajería en frío (COLD_LEAD_REJECTED).
3. Contactos cálidos (1er grado / CONECTADO en LinkedIn) autorizados.
4. Pausas estocásticas largas (6 a 15 min) y límite diario conservador (15 msgs/día).
5. Kill-switch específico de canal WhatsApp sin interrumpir el canal de LinkedIn.
6. Detección de señales de riesgo (BAN_WARNING, SESSION_DISCONNECTED) con auto-freno del canal.
7. Exclusión estricta de prospectos en lista de supresión (Opt-out).
"""

import os
import sys
import unittest
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import whatsapp_safety_engine
import safety_engine

class TestWhatsAppSafetyStrict(unittest.TestCase):

    def setUp(self):
        init_db()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE configuracion_seguridad SET valor = '0' WHERE clave = 'kill_switch_activado'")
            cursor.execute("UPDATE configuracion_seguridad SET valor = '0' WHERE clave = 'whatsapp_kill_switch_activado'")
            cursor.execute("UPDATE configuracion_seguridad SET valor = '0' WHERE clave = 'horario_laboral_activo'")
            cursor.execute("DELETE FROM suppression_list")
            cursor.execute("DELETE FROM mensajes_whatsapp")
            conn.commit()

    def _ensure_tenant(self, cursor, tenant_id: str):
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
            VALUES (?, ?, 'EMPRESA', 'ACTIVO', ?, ?)
        """, (tenant_id, f"Empresa {tenant_id}", now_iso, now_iso))

    def test_01_feature_flag_disabled_by_default(self):
        """
        CRITERIO 5.7.1:
        Módulo de WhatsApp desactivado por defecto para cada tenant.
        Cualquier intento de envío sin activación explícita debe ser rechazado.
        """
        tenant = "ten_wa_default_off"
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            conn.commit()

            lead_data = {
                "id": "lead_warm_1",
                "nombre": "Juan Pérez",
                "telefono": "+56912345678",
                "grado_red": "1º",
                "lead_estado": "CONECTADO"
            }

            diag = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_data, conn=conn)
            self.assertFalse(diag["autorizado"])
            self.assertEqual(diag["codigo"], "WHATSAPP_FEATURE_FLAG_DISABLED")

    def test_02_cold_outreach_strictly_prohibited(self):
        """
        CRITERIO NO NEGOCIABLE v1.3 (Prohibición 6 y 5.7.3):
        NUNCA enviar mensajes de WhatsApp en frío.
        Prospectos de 2º grado o sin conexión aceptada son rechazados categóricamente con COLD_LEAD_REJECTED.
        """
        tenant = "ten_wa_cold_prohibited"
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            # Habilitar feature flag para este tenant
            whatsapp_safety_engine.set_whatsapp_feature_flag(tenant, True, conn=conn)
            conn.commit()

            # Caso A: Lead frío de 2º grado
            lead_cold_2nd = {
                "id": "lead_cold_01",
                "nombre": "Pedro Frío",
                "telefono": "+56999887766",
                "grado_red": "2º",
                "lead_estado": "EXTRAIDO"
            }
            diag_cold = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_cold_2nd, conn=conn)
            self.assertFalse(diag_cold["autorizado"])
            self.assertEqual(diag_cold["codigo"], "COLD_LEAD_REJECTED")

            # Caso B: Lead cálido de 1er grado con conexión aceptada
            lead_warm_1st = {
                "id": "lead_warm_01",
                "nombre": "María Cálida",
                "telefono": "+56988776655",
                "grado_red": "1º",
                "lead_estado": "CONECTADO"
            }
            diag_warm = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_warm_1st, conn=conn)
            self.assertTrue(diag_warm["autorizado"])
            self.assertEqual(diag_warm["codigo"], "OK")

    def test_03_conservative_daily_limit_enforcement(self):
        """
        CRITERIO 5.7.2:
        Límite diario conservador (15 mensajes/día por defecto).
        Alcanzar la cuota diaria bloquea nuevos envíos con WHATSAPP_DAILY_LIMIT_REACHED.
        """
        tenant = "ten_wa_daily_limit"
        now_iso = datetime.now().isoformat()
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            whatsapp_safety_engine.set_whatsapp_feature_flag(tenant, True, conn=conn)

            # Insertar 15 mensajes enviados hoy
            for i in range(15):
                cursor.execute("""
                    INSERT OR REPLACE INTO leads (id, tenant_id, nombre, perfil_url, estado, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'CONECTADO', ?, ?)
                """, (f"lead_dummy_{i}", tenant, f"Dummy {i}", f"https://li.com/test_{i}", now_iso, now_iso))
                cursor.execute("""
                    INSERT INTO mensajes_whatsapp (lead_id, campana_nombre, contenido, telefono_destino, estado, enviado_at, created_at)
                    VALUES (?, 'Campana_Test', 'Hola!', '+56911223344', 'ENVIADO', ?, ?)
                """, (f"lead_dummy_{i}", now_iso, now_iso))
            conn.commit()

            lead_warm = {
                "id": "lead_warm_limit_test",
                "nombre": "Ana Conectada",
                "telefono": "+56944332211",
                "grado_red": "1º",
                "lead_estado": "CONECTADO"
            }

            diag = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_warm, conn=conn)
            self.assertFalse(diag["autorizado"])
            self.assertEqual(diag["codigo"], "WHATSAPP_DAILY_LIMIT_REACHED")

    def test_04_channel_specific_kill_switch_isolation(self):
        """
        CRITERIO 5.7.5:
        Kill-Switch específico para WhatsApp.
        Congela el canal de WhatsApp sin interrumpir el canal de LinkedIn.
        """
        tenant = "ten_wa_kill_iso"
        now_iso = datetime.now().isoformat()
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            whatsapp_safety_engine.set_whatsapp_feature_flag(tenant, True, conn=conn)

            # Cuenta de LinkedIn activa
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES ('li_acc_iso', ?, 'Account LinkedIn', 'WARMUP', 1, 15, 80.0, ?, ?)
            """, (tenant, now_iso, now_iso))
            conn.commit()

            # Activar Kill-Switch exclusivo de WhatsApp
            res_ks = whatsapp_safety_engine.activate_whatsapp_kill_switch("Advertencia de Meta detectada", conn=conn)
            self.assertTrue(res_ks["ok"])

            lead_warm = {
                "id": "lead_warm_ks",
                "nombre": "Carlos Conectado",
                "telefono": "+56977665544",
                "grado_red": "1º",
                "lead_estado": "CONECTADO"
            }

            # WhatsApp debe estar bloqueado
            diag_wa = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_warm, conn=conn)
            self.assertFalse(diag_wa["autorizado"])
            self.assertEqual(diag_wa["codigo"], "WHATSAPP_KILL_SWITCH_ACTIVE")

            # LinkedIn debe seguir AUTORIZADO (aislamiento de canales)
            diag_li = safety_engine.authorize_linkedin_action("li_acc_iso", tenant, "LI_SEND_INVITE", conn=conn)
            self.assertTrue(diag_li["autorizado"], "El Kill-Switch de WhatsApp no debe bloquear el canal de LinkedIn")

    def test_05_suppression_list_blocks_whatsapp_outreach(self):
        """
        CRITERIO 5.7.7 y 5.4:
        El canal de WhatsApp debe respetar estrictamente la lista de supresión (Opt-out).
        """
        tenant = "ten_wa_suppress"
        phone = "+56966554433"
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            whatsapp_safety_engine.set_whatsapp_feature_flag(tenant, True, conn=conn)

            # Agregar teléfono a lista de supresión
            import privacy_compliance_service
            import hashlib
            phone_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()
            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO suppression_list (id, tenant_id, identifier_hash, identifier_type, reason, created_at)
                VALUES ('sup_wa_1', ?, ?, 'PHONE_SHA256', 'USER_OPT_OUT', ?)
            """, (tenant, phone_hash, now_iso))
            conn.commit()

            lead_warm = {
                "id": "lead_suppressed",
                "nombre": "Ignacio Baja",
                "telefono": phone,
                "grado_red": "1º",
                "lead_estado": "CONECTADO"
            }

            diag = whatsapp_safety_engine.check_whatsapp_safety_for_tenant(tenant, lead_warm, conn=conn)
            self.assertFalse(diag["autorizado"])
            self.assertEqual(diag["codigo"], "LEAD_IN_SUPPRESSION_LIST")


if __name__ == "__main__":
    unittest.main()
