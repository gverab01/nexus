"""
Test Suite: TASK-05B-02B - Full Application PostgreSQL Operational Readiness
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Demuestra que la aplicación NexusReach Pro completa opera de forma nativa e impecable
sobre PostgreSQL como motor de persistencia, sin depender de SQLite:
1. Flujo completo de Autenticación, Sesiones, PBKDF2 y RBAC.
2. Gestión de Tenants y separación estricta de organizaciones.
3. Ciclo de vida comercial: Leads, Listas, Secuencias, Pasos e Inscripciones.
4. Validación de traducción de dialectos (INSERT OR IGNORE / ON CONFLICT).
5. Motor de seguridad antiban y configuraciones clave-valor.
6. Task Dispatcher y Worker Runner con firma Ed25519 y confirmación de comandos.
7. Aislamiento Row-Level Security (RLS) bajo rol de aplicación nexus_app.
"""

import os
import unittest
import base64
import json
import psycopg
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives.asymmetric import ed25519

# URLs de prueba
PG_APP_URL = os.getenv(
    "POSTGRES_APP_TEST_URL",
    "postgresql://nexus_app:app_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)
PG_ADMIN_URL = os.getenv(
    "POSTGRES_ADMIN_TEST_URL",
    "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)

import database
import auth_service
import safety_engine
import task_dispatcher
import command_signing_service


class TestFullApplicationPostgresReadiness(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Fijar entorno a PostgreSQL durante toda la ejecución de la suite
        cls.old_db_url = os.environ.get("DATABASE_URL")
        cls.old_is_pg = database.IS_POSTGRES
        cls.old_engine = os.environ.get("DB_ENGINE")

        os.environ["DATABASE_URL"] = PG_APP_URL
        os.environ["DB_ENGINE"] = "postgres"
        database.IS_POSTGRES = True
        database.DATABASE_URL = PG_APP_URL

        # Limpieza previa de artefactos de prueba previos usando conexión administrativa
        cls._cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_test_data()

        database.IS_POSTGRES = cls.old_is_pg
        if cls.old_db_url is not None:
            os.environ["DATABASE_URL"] = cls.old_db_url
            database.DATABASE_URL = cls.old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
            database.DATABASE_URL = ""

        if cls.old_engine is not None:
            os.environ["DB_ENGINE"] = cls.old_engine
        else:
            os.environ.pop("DB_ENGINE", None)

    @classmethod
    def _cleanup_test_data(cls):
        """Elimina datos generados durante las pruebas para garantizar idempotencia."""
        try:
            with psycopg.connect(PG_ADMIN_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit_logs;")
                    cur.execute("DELETE FROM command_results WHERE tenant_id IN ('ten_primary', 'ten_secondary_org');")
                    cur.execute("DELETE FROM commands WHERE tenant_id IN ('ten_primary', 'ten_secondary_org');")
                    cur.execute("DELETE FROM devices WHERE tenant_id IN ('ten_primary', 'ten_secondary_org');")
                    cur.execute("DELETE FROM linkedin_accounts WHERE tenant_id IN ('ten_primary', 'ten_secondary_org');")
                    cur.execute("DELETE FROM leads_en_secuencia WHERE id = 'enr_001';")
                    cur.execute("DELETE FROM pasos_secuencia WHERE id = 'paso_01';")
                    cur.execute("DELETE FROM secuencias WHERE id = 'sec_b2b_outreach';")
                    cur.execute("DELETE FROM leads_en_lista WHERE id = 'rel_001';")
                    cur.execute("DELETE FROM leads WHERE id = 'led_ops_001';")
                    cur.execute("DELETE FROM listas_leads WHERE id = 'lst_primaria_01';")
                    cur.execute("DELETE FROM usuarios WHERE email IN ('vendedor@nexusreach.com', 'admin@segunda.com');")
                    cur.execute("DELETE FROM suscripciones WHERE tenant_id = 'ten_secondary_org';")
                    cur.execute("DELETE FROM tenants WHERE id = 'ten_secondary_org';")
                conn.commit()
        except Exception as e:
            print(f"[WARN] Cleanup test data: {e}")

    def test_01_auth_login_and_session_lifecycle(self):
        """Valida login, hash PBKDF2, sesión en memoria y logout sobre PostgreSQL."""
        # Login del administrador inicial creado en bootstrap
        login_res = auth_service.authenticate_user("admin@nexusreach.com", "AdminSecure2026!")
        self.assertTrue(login_res["exito"], f"Login falló: {login_res.get('mensaje')}")
        self.assertIn("token", login_res)
        session_token = login_res["token"]

        # Validar sesión activa en memoria
        session = auth_service.verify_token(session_token)
        self.assertIsNotNone(session)
        self.assertEqual(session["email"], "admin@nexusreach.com")
        self.assertEqual(session["tenant_id"], "ten_primary")
        self.assertEqual(session["rol"], "COMPANY_ADMIN")

        # Crear un usuario miembro dentro del tenant inicial
        with database.tenant_context_scope(tenant_id="ten_primary"):
            user_res = auth_service.create_user_for_tenant(
                tenant_id="ten_primary",
                email="vendedor@nexusreach.com",
                password="VendedorPass2026!",
                name="Vendedor Uno",
                role="COMPANY_MEMBER"
            )
            self.assertTrue(user_res["exito"], f"Error creando usuario: {user_res.get('mensaje')}")

            # Listar miembros del tenant
            members = auth_service.list_tenant_users("ten_primary")
            emails = [m["email"] for m in members]
            self.assertIn("admin@nexusreach.com", emails)
            self.assertIn("vendedor@nexusreach.com", emails)

        # Login del nuevo vendedor
        vend_login = auth_service.authenticate_user("vendedor@nexusreach.com", "VendedorPass2026!")
        self.assertTrue(vend_login["exito"])
        self.assertEqual(vend_login["usuario"]["rol"], "COMPANY_MEMBER")

        # Logout
        logout_ok = auth_service.logout_user(session_token)
        self.assertTrue(logout_ok)
        self.assertIsNone(auth_service.verify_token(session_token))

    def test_02_tenant_creation_and_strict_isolation(self):
        """Valida creación de un segundo tenant y separación de datos en PostgreSQL."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Crear segundo tenant usando contexto SuperAdmin
        with database.tenant_context_scope(is_super_admin=True):
            with database.get_db() as db:
                cur = db.cursor()
                cur.execute("""
                    INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES ('ten_secondary_org', NULL, 'Segunda Organización SpA', 'EMPRESA', 'ACTIVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))

                cur.execute("""
                    INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES ('sub_secondary', 'ten_secondary_org', 'MENSUAL', 'ACTIVA', 3, 35.0, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso, now_iso, now_iso))

        # Crear usuario para el segundo tenant
        with database.tenant_context_scope(tenant_id="ten_secondary_org"):
            res = auth_service.create_user_for_tenant(
                tenant_id="ten_secondary_org",
                email="admin@segunda.com",
                password="SegundaPass2026!",
                name="Admin Segunda",
                role="COMPANY_ADMIN"
            )
            self.assertTrue(res["exito"], f"Error creando admin@segunda.com: {res.get('mensaje')}")

        # Verificar aislamiento: ten_primary NO debe ver a admin@segunda.com
        with database.tenant_context_scope(tenant_id="ten_primary"):
            members_primary = auth_service.list_tenant_users("ten_primary")
            emails_p = [m["email"] for m in members_primary]
            self.assertNotIn("admin@segunda.com", emails_p)

        # ten_secondary_org NO debe ver a admin@nexusreach.com
        with database.tenant_context_scope(tenant_id="ten_secondary_org"):
            members_sec = auth_service.list_tenant_users("ten_secondary_org")
            emails_s = [m["email"] for m in members_sec]
            self.assertIn("admin@segunda.com", emails_s)
            self.assertNotIn("admin@nexusreach.com", emails_s)

    def test_03_commercial_lifecycle_leads_lists_sequences(self):
        """Valida creación y consulta de leads, listas, secuencias e inserción ON CONFLICT en PostgreSQL."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with database.tenant_context_scope(tenant_id="ten_primary"):
            with database.get_db() as db:
                cur = db.cursor()

                # 1. Crear Lista
                cur.execute("""
                    INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, created_at, updated_at)
                    VALUES ('lst_primaria_01', 'ten_primary', 'CEOs Santiago', 'Lista comercial B2B', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))

                # 2. Crear Lead
                cur.execute("""
                    INSERT INTO leads (id, tenant_id, perfil_url, nombre, cargo_actual, empresa_dominio, estado, created_at, updated_at)
                    VALUES ('led_ops_001', 'ten_primary', 'https://linkedin.com/in/andres-bello', 'Andrés Bello', 'Director General', 'empresa.cl', 'NUEVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))

                # 3. Asociar Lead a Lista usando sintaxis SQLite INSERT OR IGNORE (traducida transparentemente a ON CONFLICT)
                cur.execute("""
                    INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
                    VALUES ('rel_001', 'lst_primaria_01', 'led_ops_001', %s);
                """, (now_iso,))

                # 4. Crear Secuencia de Prospección
                cur.execute("""
                    INSERT INTO secuencias (id, tenant_id, nombre, descripcion, activa, created_at, updated_at)
                    VALUES ('sec_b2b_outreach', 'ten_primary', 'Secuencia B2B Q4', 'Conexión + Seguimiento', 1, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))

                # 5. Crear Paso de Secuencia
                cur.execute("""
                    INSERT INTO pasos_secuencia (id, secuencia_id, orden, tipo_accion, parametros_json, created_at)
                    VALUES ('paso_01', 'sec_b2b_outreach', 1, 'ENVIAR_INVITACION', '{"nota": "Hola Andrés"}', %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso,))

                # 6. Inscribir Lead en Secuencia con INSERT OR IGNORE
                cur.execute("""
                    INSERT OR IGNORE INTO leads_en_secuencia (id, lead_id, secuencia_id, paso_actual_id, estado, proxima_ejecucion_at, created_at, updated_at)
                    VALUES ('enr_001', 'led_ops_001', 'sec_b2b_outreach', 'paso_01', 'PENDIENTE', %s, %s, %s);
                """, (now_iso, now_iso, now_iso))

                # 7. Consultar y verificar relaciones con alias únicos
                cur.execute("""
                    SELECT l.nombre AS lead_nombre, lst.nombre AS lista_nombre, s.nombre AS secuencia_nombre, les.estado
                    FROM leads l
                    JOIN leads_en_lista lel ON lel.lead_id = l.id
                    JOIN listas_leads lst ON lst.id = lel.lista_id
                    JOIN leads_en_secuencia les ON les.lead_id = l.id
                    JOIN secuencias s ON s.id = les.secuencia_id
                    WHERE l.id = 'led_ops_001';
                """)
                row = cur.fetchone()
                self.assertIsNotNone(row)
                nombre_lead = row["lead_nombre"] if isinstance(row, dict) else row[0]
                self.assertEqual(nombre_lead, "Andrés Bello")

    def test_04_safety_engine_and_key_value_config_upsert(self):
        """Valida que safety_engine opere con PostgreSQL sin errores de sintaxis (ON CONFLICT clave)."""
        # Actualizar parámetros antiban en configuracion_seguridad
        ok1 = safety_engine.set_safety_config_val("pausa_linkedin_min_seg", "200")
        self.assertTrue(ok1)
        ok2 = safety_engine.set_safety_config_val("pausa_linkedin_max_seg", "400")
        self.assertTrue(ok2)

        # Leer configuraciones consolidadas
        cfg = safety_engine.get_all_safety_config()
        self.assertEqual(cfg.get("pausa_linkedin_min_seg"), "200")
        self.assertEqual(cfg.get("pausa_linkedin_max_seg"), "400")

        # Comprobar horario comercial
        is_safe, msg = safety_engine.check_business_hours(cfg)
        self.assertIsInstance(is_safe, bool)
        self.assertIsInstance(msg, str)

    def test_05_task_dispatcher_and_command_signing(self):
        """Valida despacho de tareas, encolamiento y verificación de firmas Ed25519 en PostgreSQL."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with database.tenant_context_scope(tenant_id="ten_primary"):
            with database.get_db() as db:
                cur = db.cursor()

                # 1. Registrar cuenta de LinkedIn
                cur.execute("""
                    INSERT INTO linkedin_accounts (id, tenant_id, account_name, profile_url, status, created_at, updated_at)
                    VALUES ('acc_li_primary_01', 'ten_primary', 'SDR Ejecutivo', 'https://linkedin.com/in/sdr', 'CONNECTED', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))

            # 2. Generar par de claves Ed25519 para dispositivo cliente
            dev_priv = ed25519.Ed25519PrivateKey.generate()
            dev_pub = dev_priv.public_key()
            dev_pub_b64 = base64.b64encode(dev_pub.public_bytes_raw()).decode("utf-8")

            # 3. Registrar dispositivo en el sistema
            reg_res = command_signing_service.register_device(
                device_id="dev_primary_001",
                tenant_id="ten_primary",
                public_key_ed25519=dev_pub_b64,
                device_name="Dispositivo Primario 001"
            )
            self.assertTrue(reg_res.get("ok", True))

            # 4. Crear comando firmado por el servidor (Ed25519)
            cmd = command_signing_service.create_signed_command(
                tenant_id="ten_primary",
                device_id="dev_primary_001",
                action="LI_SEND_INVITE",
                params={"perfil_url": "https://linkedin.com/in/andres-bello"}
            )
            self.assertIsNotNone(cmd)
            cmd_id = cmd["command_id"]
            self.assertEqual(cmd["action"], "LI_SEND_INVITE")
            self.assertTrue(bool(cmd["signature"]))

            # 5. Verificar firma Ed25519 del servidor
            valid_sig = command_signing_service.verify_server_command_signature(cmd, cmd["signature"])
            self.assertTrue(valid_sig, "La firma Ed25519 del servidor sobre el comando debe ser válida")

            # 6. El dispositivo procesa el comando y firma el resultado
            report_payload = {
                "command_id": cmd_id,
                "device_id": "dev_primary_001",
                "success": True,
                "result": {"perfil_url": "https://linkedin.com/in/andres-bello", "invitado": True},
                "error": ""
            }
            canonical_report = command_signing_service.canonicalize_json(report_payload)
            dev_signature_b64 = base64.b64encode(dev_priv.sign(canonical_report)).decode("utf-8")

            # 7. Registrar resultado de ejecución con verificación criptográfica
            res_report = command_signing_service.record_command_result(
                command_id=cmd_id,
                device_id="dev_primary_001",
                tenant_id="ten_primary",
                action="LI_SEND_INVITE",
                success=True,
                result_data={"perfil_url": "https://linkedin.com/in/andres-bello", "invitado": True},
                device_signature=dev_signature_b64
            )
            self.assertTrue(res_report.get("ok"), f"Error en record_command_result: {res_report.get('error')}")
            self.assertEqual(res_report.get("status"), "EXECUTED")

    def test_06_cross_tenant_isolation_under_app_role(self):
        """Verifica que el rol nexus_app confine todas las entidades creadas exclusivamente al tenant autorizado."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Caso A: ten_primary ve sus entidades creadas
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_primary', true);")
                cur.execute("SELECT count(*) FROM leads WHERE id = 'led_ops_001';")
                self.assertEqual(cur.fetchone()[0], 1)

                cur.execute("SELECT count(*) FROM listas_leads WHERE id = 'lst_primaria_01';")
                self.assertEqual(cur.fetchone()[0], 1)

                cur.execute("SELECT count(*) FROM secuencias WHERE id = 'sec_b2b_outreach';")
                self.assertEqual(cur.fetchone()[0], 1)

                cur.execute("SELECT count(*) FROM commands;")
                self.assertGreaterEqual(cur.fetchone()[0], 1)

                # Caso B: ten_secondary_org ve 0 entidades de ten_primary
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_secondary_org', true);")
                cur.execute("SELECT count(*) FROM leads WHERE id = 'led_ops_001';")
                self.assertEqual(cur.fetchone()[0], 0, "No debe ver leads ajenos")

                cur.execute("SELECT count(*) FROM listas_leads WHERE id = 'lst_primaria_01';")
                self.assertEqual(cur.fetchone()[0], 0, "No debe ver listas ajenas")

                cur.execute("SELECT count(*) FROM secuencias WHERE id = 'sec_b2b_outreach';")
                self.assertEqual(cur.fetchone()[0], 0, "No debe ver secuencias ajenas")

                cur.execute("SELECT count(*) FROM commands WHERE device_id = 'dev_primary_001';")
                self.assertEqual(cur.fetchone()[0], 0, "No debe ver comandos ajenos")

                # Caso C: Sin tenant context -> 0 filas
                cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
                cur.execute("SELECT count(*) FROM leads;")
                self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
