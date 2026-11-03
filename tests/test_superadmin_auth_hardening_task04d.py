# ==============================================================================
# NEXUSREACH PRO - SUITE DE AUDITORÍA Y HARDENING DE AUTORIZACIÓN SUPERADMIN (TASK-04D)
# ==============================================================================
import unittest
import os
import psycopg
from psycopg.rows import dict_row
from unittest.mock import patch

import database
from database import _configure_pg_context, get_db, tenant_context_scope, get_superadmin_rls_secret

REAL_PG_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://nexus_app:app_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)
ADMIN_PG_URL = "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test"


class TestSuperAdminAuthHardeningTask04D(unittest.TestCase):
    """Pruebas rigurosas de seguridad para la función verify_super_admin_context(),
    el secreto criptográfico, el aislamiento contra objetos temporales y el flujo del backend.
    """

    @classmethod
    def setUpClass(cls):
        # 0. Habilitar modo PostgreSQL en el módulo database para pruebas de backend
        cls.orig_is_postgres = database.IS_POSTGRES
        cls.orig_database_url = database.DATABASE_URL
        database.IS_POSTGRES = True
        database.DATABASE_URL = REAL_PG_URL

        # 1. Preparar datos de prueba conectando como administrador
        with psycopg.connect(ADMIN_PG_URL, row_factory=dict_row) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("BEGIN;")
                cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
                cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (get_superadmin_rls_secret(),))
                cur.execute("""
                    INSERT INTO tenants (id, razon_social, created_at, updated_at)
                    VALUES ('ten_audit_alpha', 'Tenant Alpha Audit', '2026-10-29', '2026-10-29')
                    ON CONFLICT (id) DO NOTHING;
                """)
                cur.execute("""
                    INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                    VALUES ('lead_audit_secret_1', 'ten_audit_alpha', 'Lead Alpha Confidencial', 'https://linkedin.com/in/secret-alpha', '2026-10-29', '2026-10-29')
                    ON CONFLICT (id) DO NOTHING;
                """)
                cur.execute("COMMIT;")

        # 2. Conexión estándar de aplicación no privilegiada
        cls.app_conn = psycopg.connect(REAL_PG_URL, row_factory=dict_row)
        cls.app_conn.autocommit = True

    @classmethod
    def tearDownClass(cls):
        database.IS_POSTGRES = cls.orig_is_postgres
        database.DATABASE_URL = cls.orig_database_url

        if hasattr(cls, "app_conn") and cls.app_conn:
            cls.app_conn.close()

        with psycopg.connect(ADMIN_PG_URL) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("BEGIN;")
                cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
                cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (get_superadmin_rls_secret(),))
                cur.execute("DELETE FROM leads WHERE id LIKE 'lead_audit_%';")
                cur.execute("DELETE FROM tenants WHERE id LIKE 'ten_audit_%';")
                cur.execute("COMMIT;")

    def test_01_normal_user_without_token_denied_access(self):
        """1. Usuario normal fija app.is_super_admin='true' sin token: acceso global denegado."""
        with self.app_conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', '', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            
            # Consultar función de verificación y consulta a tabla
            cur.execute("SELECT public.verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"])

            cur.execute("SELECT * FROM leads WHERE id = 'lead_audit_secret_1';")
            self.assertIsNone(cur.fetchone(), "Violación RLS: Atacante sin token pudo leer registro de otro tenant!")
            cur.execute("COMMIT;")

    def test_02_normal_user_with_fake_token_denied_access(self):
        """2. Usuario normal fija token falso: acceso global denegado."""
        with self.app_conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', 'forged_token_attack_xyz', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")

            cur.execute("SELECT public.verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"])

            cur.execute("SELECT * FROM leads WHERE id = 'lead_audit_secret_1';")
            self.assertIsNone(cur.fetchone(), "Violación RLS: Atacante con token falso pudo leer registro!")
            cur.execute("COMMIT;")

    def test_03_normal_user_cannot_read_or_modify_system_admin_keys(self):
        """3. Usuario no privilegiado 'nexus_app' no puede consultar ni modificar la tabla system_admin_keys."""
        with self.app_conn.cursor() as cur:
            # Lectura denegada
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT * FROM public.system_admin_keys;")

            # Inserción denegada
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO public.system_admin_keys VALUES ('fake_key', 'fake_hash');")

            # Modificación denegada
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cur.execute("UPDATE public.system_admin_keys SET key_hash = 'fake_hash';")

            # Eliminación denegada
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM public.system_admin_keys;")

    def test_04_temp_table_shadowing_attack_prevented(self):
        """4. Manipulación de pg_temp para interceptar system_admin_keys es neutralizada por search_path fijo."""
        with self.app_conn.cursor() as cur:
            # Atacante crea tabla temporal con el mismo nombre y su propio hash
            cur.execute("""
                CREATE TEMP TABLE system_admin_keys (
                    key_name VARCHAR(64) PRIMARY KEY,
                    key_hash VARCHAR(128) NOT NULL
                );
                INSERT INTO system_admin_keys VALUES ('super_admin_bypass', encode(digest('hacked_token', 'sha256'), 'hex'));
            """)
            
            # Intenta activar bypass con su token forjado
            cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
            cur.execute("SELECT set_config('app.super_admin_token', 'hacked_token', false);")
            
            # verify_super_admin_context() DEBE consultar public.system_admin_keys gracias a search_path=pg_catalog, public
            cur.execute("SELECT public.verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"], "Vulnerabilidad CVE: Ataque de shadowing en pg_temp tuvo éxito!")

            cur.execute("SELECT * FROM leads WHERE id = 'lead_audit_secret_1';")
            self.assertIsNone(cur.fetchone(), "Vulnerabilidad CVE: Shadowing de pg_temp permitió leer datos cross-tenant!")

    def test_05_public_role_has_no_execute_on_verify_function(self):
        """5. Verifica que el rol PUBLIC no tenga permisos EXECUTE sobre verify_super_admin_context."""
        with psycopg.connect(ADMIN_PG_URL, row_factory=dict_row) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("""
                    SELECT grantee, privilege_type
                    FROM information_schema.routine_privileges
                    WHERE routine_name = 'verify_super_admin_context'
                      AND grantee = 'PUBLIC';
                """)
                rows = cur.fetchall()
                self.assertEqual(len(rows), 0, "Fallo de privilegio: PUBLIC conserva EXECUTE sobre verify_super_admin_context!")

    def test_06_backend_authorization_e2e_rbac_boundary(self):
        """6. Flujo real de backend FastAPI: Usuario ordinario recibe 403 en ruta admin; superadmin accede con 200."""
        from fastapi.testclient import TestClient
        from main import app
        import auth_service

        client = TestClient(app)

        import secrets
        import time

        # A. Crear sesión legítima para usuario común (COMPANY_MEMBER en ten_audit_alpha)
        token_member = "test_member_token_" + secrets.token_hex(16)
        auth_service.ACTIVE_SESSIONS[token_member] = {
            "id": "usr_audit_member",
            "tenant_id": "ten_audit_alpha",
            "rol": "COMPANY_MEMBER",
            "email": "member@alpha.com",
            "expires_at": time.time() + 3600,
            "last_db_check": time.time(),
            "suscripcion": {"estado": "ACTIVA", "dias_restantes": 30}
        }

        # B. Intento de llamar ruta administrativa de superadmin -> 403
        resp = client.delete(
            "/api/logs",
            headers={"Authorization": f"Bearer {token_member}"}
        )
        self.assertEqual(resp.status_code, 403, f"Fallo de autorización: Usuario ordinario obtuvo {resp.status_code}")

        # C. Llamar ruta con superadmin legítimo (SUPER_ADMIN) -> 200
        token_sa = "test_sa_token_" + secrets.token_hex(16)
        auth_service.ACTIVE_SESSIONS[token_sa] = {
            "id": "usr_audit_sa",
            "tenant_id": "ten_superadmin",
            "rol": "SUPER_ADMIN",
            "email": "superadmin@nexusreach.com",
            "expires_at": time.time() + 3600,
            "last_db_check": time.time(),
            "suscripcion": {"estado": "ACTIVA", "dias_restantes": 30}
        }
        resp_sa = client.delete(
            "/api/logs",
            headers={"Authorization": f"Bearer {token_sa}"}
        )
        self.assertEqual(resp_sa.status_code, 200, f"Superadmin legítimo bloqueado: {resp_sa.status_code}")

    def test_07_backend_fail_closed_on_missing_or_corrupted_secret(self):
        """7. Ausencia o corrupción del secreto en entorno de producción fuerza fail-closed."""
        mock_cur = unittest.mock.MagicMock()

        # Simular entorno de producción sin SUPERADMIN_RLS_SECRET configurado
        with patch.dict(os.environ, {"ENV": "production", "SUPERADMIN_RLS_SECRET": ""}):
            _configure_pg_context(mock_cur, tenant_id=None, is_super_admin=True)

            calls = [c[0] for c in mock_cur.execute.call_args_list]
            # Debe haber configurado app.is_super_admin = 'false' y app.super_admin_token = ''
            self.assertIn(("SELECT set_config('app.is_super_admin', 'false', true);",), calls)
            self.assertIn(("SELECT set_config('app.super_admin_token', '', true);",), calls)

    def test_08_connection_reuse_and_transaction_cleanup(self):
        """8. Reutilización de conexión: Consulta legítima como superadmin limpia el contexto y no deja fugas."""
        # Transacción 1: Consulta legítima de superadmin vía get_db()
        with get_db(is_super_admin=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE id = 'lead_audit_secret_1';")
            self.assertIsNotNone(cur.fetchone())

        # Transacción 2: Misma conexión en contexto sin privilegios
        with get_db(tenant_id=None, is_super_admin=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE id = 'lead_audit_secret_1';")
            self.assertIsNone(cur.fetchone(), "Fuga de contexto: Transacción no privilegiada heredó superadmin!")

    def test_09_native_dba_bypass_logic(self):
        """9. Conexión de administrador nativo (nexus_admin) evalúa correctamente sin recursión infinita."""
        with psycopg.connect(ADMIN_PG_URL, row_factory=dict_row) as admin_conn:
            admin_conn.autocommit = True
            with admin_conn.cursor() as cur:
                # Con is_super_admin = 'true'
                cur.execute("BEGIN;")
                cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
                cur.execute("SELECT public.verify_super_admin_context() as authorized;")
                self.assertTrue(cur.fetchone()["authorized"])
                cur.execute("COMMIT;")

                # Con is_super_admin = 'false'
                cur.execute("BEGIN;")
                cur.execute("SELECT set_config('app.is_super_admin', 'false', true);")
                cur.execute("SELECT public.verify_super_admin_context() as authorized;")
                self.assertFalse(cur.fetchone()["authorized"])
                cur.execute("COMMIT;")


if __name__ == "__main__":
    unittest.main()
