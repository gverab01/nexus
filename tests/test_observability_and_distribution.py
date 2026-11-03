"""
Pruebas Automatizadas de Observabilidad, Telemetría, Soporte y Distribución
NexusReach Pro - Workstream 5.10 y 5.11 [Hito M5] - Directrices v1.3

Verifica:
1. Métricas de telemetría operativa (tasa de éxito por acción, embudo de aceptación, latencia e incidentes).
2. Tablero de alertas internas del equipo (acciones con >15% de fallo, cuentas degradadas, selectores caídos).
3. Paquete de diagnóstico de soporte exportable estrictamente sanitizado (CERO PII, contraseñas o chats).
4. Política de versión mínima de cliente (versiones obsoletas rechazadas con CLIENT_VERSION_DEPRECATED).
5. Configuración de distribución multiplataforma (electron-builder.yml para Windows y macOS).
"""

import unittest
import json
import os
from datetime import datetime, timezone, timedelta

from database import get_db, init_db
import observability_service
import command_signing_service
import selector_service


class TestObservabilityAndDistribution(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    TEST_TENANTS = ('ten_obs_metrics', 'ten_support_bundle')

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?'] * len(self.TEST_TENANTS))
            cursor.execute(f"DELETE FROM commands WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM command_results WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM devices WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM system_logs WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM linkedin_accounts WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM leads WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute("DELETE FROM action_status")
            conn.commit()

    def _ensure_tenant(self, cursor, tenant_id: str):
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO tenants (id, razon_social, estado, created_at, updated_at)
            VALUES (?, ?, 'ACTIVO', ?, ?)
        """, (tenant_id, f"Tenant {tenant_id}", now_iso, now_iso))

    def test_01_telemetry_metrics_and_funnel_calculations(self):
        """
        CRITERIO 5.10:
        Cálculo de métricas de telemetría operativa:
        - Tasa de éxito por acción.
        - Tasa de aceptación del embudo de LinkedIn.
        - Latencia media de comandos en segundos.
        """
        tenant = "ten_obs_metrics"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        t_start = (now - timedelta(seconds=10)).isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            # 1. Asegurar dispositivo
            cursor.execute("""
                INSERT OR IGNORE INTO devices (id, tenant_id, device_name, public_key_ed25519, status, client_version, created_at, updated_at)
                VALUES ('dev_1', ?, 'Device 1', 'pubkey', 'ACTIVE', '1.0.0', ?, ?)
            """, (tenant, now_iso, now_iso))

            # Insertar comandos simulados (8 exitosos, 2 fallidos en LI_SEND_INVITE -> 80% éxito)
            for i in range(8):
                cmd_id = f"cmd_ok_{i}"
                cursor.execute("""
                    INSERT INTO commands (id, tenant_id, device_id, action, params_json, nonce, issued_at, expires_at, signature, status, created_at)
                    VALUES (?, ?, 'dev_1', 'LI_SEND_INVITE', '{}', ?, ?, ?, 'sig', 'COMPLETED', ?)
                """, (cmd_id, tenant, f"nonce_ok_{i}", t_start, now_iso, t_start))
                cursor.execute("""
                    INSERT INTO command_results (id, command_id, device_id, tenant_id, action, success, reported_at)
                    VALUES (?, ?, 'dev_1', ?, 'LI_SEND_INVITE', 1, ?)
                """, (f"res_ok_{i}", cmd_id, tenant, now_iso))

            for i in range(2):
                cmd_id = f"cmd_fail_{i}"
                cursor.execute("""
                    INSERT INTO commands (id, tenant_id, device_id, action, params_json, nonce, issued_at, expires_at, signature, status, created_at)
                    VALUES (?, ?, 'dev_1', 'LI_SEND_INVITE', '{}', ?, ?, ?, 'sig', 'FAILED', ?)
                """, (cmd_id, tenant, f"nonce_fail_{i}", t_start, now_iso, t_start))

            # 2. Insertar leads para embudo (10 outreach, 4 conectados -> 40% aceptación)
            for i in range(4):
                cursor.execute("""
                    INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, grado_red, created_at, updated_at)
                    VALUES (?, ?, 'Lead C', ?, 'CONECTADO', '1º', ?, ?)
                """, (f"lead_conn_{i}", tenant, f"https://li.com/test_c_{i}", now_iso, now_iso))

            for i in range(6):
                cursor.execute("""
                    INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, grado_red, created_at, updated_at)
                    VALUES (?, ?, 'Lead P', ?, 'INVITACION_ENVIADA', '2º', ?, ?)
                """, (f"lead_pend_{i}", tenant, f"https://li.com/test_p_{i}", now_iso, now_iso))

            conn.commit()

            metrics = observability_service.get_telemetry_metrics(tenant_id=tenant, conn=conn)

            # Verificaciones
            self.assertEqual(metrics["commands"]["total"], 10)
            self.assertEqual(metrics["commands"]["successful"], 8)
            self.assertEqual(metrics["commands"]["failed"], 2)
            self.assertEqual(metrics["commands"]["global_success_rate_pct"], 80.0)

            # Embudo
            self.assertEqual(metrics["linkedin_funnel"]["total_outreach"], 10)
            self.assertEqual(metrics["linkedin_funnel"]["connections_accepted"], 4)
            self.assertEqual(metrics["linkedin_funnel"]["acceptance_rate_pct"], 40.0)

            # Latencia
            self.assertGreater(metrics["latency"]["average_execution_seconds"], 0.0)

    def test_02_team_internal_dashboard_alerts(self):
        """
        CRITERIO 5.10:
        Alertas operativas internas:
        - Alerta CRÍTICA si una acción fue pausada por rotura de interfaz.
        - Alerta si una cuenta tiene salud degradada (health < 70).
        """
        with get_db() as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, "ten_alert")

            # 1. Simular acción pausada en selector_service
            selector_service.record_selector_failure("LI_CONNECT_BUTTON", "ten_alert", "cmd_fail_1", {"err": "test"}, conn=conn)
            selector_service.record_selector_failure("LI_CONNECT_BUTTON", "ten_alert", "cmd_fail_2", {"err": "test"}, conn=conn)
            selector_service.record_selector_failure("LI_CONNECT_BUTTON", "ten_alert", "cmd_fail_3", {"err": "test"}, conn=conn)

            # 2. Simular cuenta con health degradado (health_score = 45.0)
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES ('acc_degraded', 'ten_alert', 'Cuenta en Riesgo', 'CHECKPOINT', 1, 15, 45.0, ?, ?)
            """, (now_iso, now_iso))
            conn.commit()

            alerts_data = observability_service.get_team_internal_dashboard_alerts(conn=conn)
            self.assertTrue(alerts_data["ok"])
            self.assertGreaterEqual(alerts_data["total_alerts"], 2)

            modules_alerted = [a["module"] for a in alerts_data["alerts"]]
            self.assertIn("INTERFACE_SELECTOR", modules_alerted)
            self.assertIn("ACCOUNT_HEALTH", modules_alerted)

    def test_03_support_diagnostics_bundle_strict_privacy_no_pii(self):
        """
        CRITERIO 5.10 y Prohibición 8:
        El Support Diagnostics Bundle contiene diagnóstico técnico exhaustivo,
        pero CERO datos personales, credenciales, tokens o contenidos de chat.
        """
        tenant = "ten_support_bundle"
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            # Insertar log del sistema con posible información confidencial
            confidential_log_details = {
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.super_secret_session_token",
                "password": "super_secret_user_password",
                "contenido": "Hola Juan, este es un mensaje privado de prospección.",
                "email": "juan.perez@empresa.com",
                "telefono": "+56912345678",
                "error_code": "ERR_SELECTOR_TIMEOUT",
                "url_path": "/in/juan-perez"
            }
            cursor.execute("""
                INSERT INTO system_logs (timestamp, level, module, message, details_json, created_at, tenant_id)
                VALUES (?, 'ERROR', 'COMMAND_DISPATCHER', 'Error de despacho', ?, ?, ?)
            """, (now_iso, json.dumps(confidential_log_details), now_iso, tenant))
            conn.commit()

            # Generar paquete de diagnóstico
            bundle = observability_service.generate_support_diagnostics_bundle(tenant, conn=conn)

            self.assertIn("bundle_id", bundle)
            self.assertEqual(bundle["tenant_id"], tenant)
            self.assertIn("server_version", bundle)
            self.assertIn("sanitized_system_logs", bundle)

            # Convertir el bundle completo a texto para auditoría estricta de fuga de datos
            bundle_str = json.dumps(bundle)

            # Verificar que NINGUNA credencial o dato personal se filtró
            self.assertNotIn("super_secret_user_password", bundle_str)
            self.assertNotIn("super_secret_session_token", bundle_str)
            self.assertNotIn("Hola Juan, este es un mensaje privado", bundle_str)
            self.assertNotIn("juan.perez@empresa.com", bundle_str)
            self.assertNotIn("+56912345678", bundle_str)

            # Verificar que los campos sensibles fueron redactados
            self.assertIn("[REDACTED_CONFIDENTIAL]", bundle_str)
            self.assertIn("[REDACTED_PII]", bundle_str)

    def test_04_client_minimum_version_policy_enforcement(self):
        """
        CRITERIO 5.11:
        Control de versión mínima de cliente (`min_client_version`):
        Clientes con versión inferior a la mínima requerida son rechazados con CLIENT_VERSION_DEPRECATED.
        """
        # 1. Versión obsoleta (0.8.0 < 1.0.0)
        is_ok, msg = observability_service.check_client_version_support("0.8.0")
        self.assertFalse(is_ok)
        self.assertIn("obsoleta", msg)

        # 2. Intento de registro de dispositivo con versión obsoleta
        dev_id = "dev_old_version_test"
        valid_pubkey = "r0W+5L1R2PZ0N5sJ9X/8K9L7P3M2N1B4V6C8X0Z2Q4A="
        res_reg = command_signing_service.register_device(
            device_id=dev_id,
            tenant_id="ten_test",
            public_key_ed25519=valid_pubkey,
            client_version="0.8.0"
        )
        self.assertFalse(res_reg["ok"])
        self.assertEqual(res_reg["error"], "CLIENT_VERSION_DEPRECATED")

        # 3. Versión válida (1.0.0 o 1.3.0)
        is_ok_valid, _ = observability_service.check_client_version_support("1.0.0")
        self.assertTrue(is_ok_valid)

        is_ok_future, _ = observability_service.check_client_version_support("1.3.0")
        self.assertTrue(is_ok_future)

    def test_05_electron_packaging_configuration_validity(self):
        """
        CRITERIO 5.11:
        Verificación de integridad de la configuración de empaquetado y distribución:
        - electron-builder.yml existe y configura Windows (NSIS) y macOS (DMG).
        - package.json en desktop contiene dependencias y scripts de empaquetado.
        """
        builder_yml_path = os.path.join(os.path.dirname(__file__), "..", "desktop", "electron-builder.yml")
        self.assertTrue(os.path.exists(builder_yml_path), "Falta desktop/electron-builder.yml")

        with open(builder_yml_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("appId: com.nexusreach.desktop", content)
        self.assertIn("win:", content)
        self.assertIn("mac:", content)
        self.assertIn("target: nsis", content)
        self.assertIn("target: dmg", content)
        self.assertIn("hardenedRuntime: true", content)

        pkg_json_path = os.path.join(os.path.dirname(__file__), "..", "desktop", "package.json")
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)

        self.assertIn("dist:win", pkg_data["scripts"])
        self.assertIn("dist:mac", pkg_data["scripts"])
        self.assertIn("electron-builder", pkg_data["devDependencies"])


if __name__ == "__main__":
    unittest.main()
