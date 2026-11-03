"""
Test Suite: TASK-05B-02A - Clean PostgreSQL Initialization & Operational Bootstrap Validation
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Verifica de extremo a extremo:
1. Estado inicial limpio de la base de datos (exactamente 1 tenant, 1 admin, 0 leads, 0 datos históricos).
2. Autenticación y hash seguro PBKDF2 del usuario administrador inicial.
3. Aislamiento Row-Level Security (RLS) en el tenant inicial frente a tenants no autorizados.
4. Operaciones CRUD (creación, lectura, actualización, eliminación de leads) bajo rol de aplicación.
5. Políticas WITH CHECK impiden inyección cruzada entre tenants.
6. Bypass SuperAdmin autorizado vs no autorizado (fail-closed).
7. Integración de database.get_db() con tenant_context_scope() sobre PostgreSQL limpio.
"""

import os
import unittest
import psycopg
from psycopg import errors

# Connection configuration
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


class TestCleanPostgresBootstrapFunctional(unittest.TestCase):

    def test_01_clean_initial_state_metrics(self):
        """Verifica que la base solo contenga los datos mínimos iniciales y ningún registro histórico."""
        secret = database.get_superadmin_rls_secret()
        with psycopg.connect(PG_ADMIN_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                if secret:
                    cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (secret,))

                # Exactamente 1 tenant
                cur.execute("SELECT count(*), min(id) FROM tenants;")
                t_count, t_id = cur.fetchone()
                self.assertEqual(t_count, 1, "Debe existir exactamente 1 tenant inicial")
                self.assertEqual(t_id, "ten_primary")

                # Exactamente 1 usuario
                cur.execute("SELECT count(*), min(email), min(rol) FROM usuarios;")
                u_count, u_email, u_role = cur.fetchone()
                self.assertEqual(u_count, 1, "Debe existir exactamente 1 usuario administrador inicial")
                self.assertEqual(u_email, "admin@nexusreach.com")
                self.assertEqual(u_role, "COMPANY_ADMIN")

                # Exactamente 1 suscripción
                cur.execute("SELECT count(*) FROM suscripciones;")
                self.assertEqual(cur.fetchone()[0], 1)

                # Tablas operacionales deben estar completamente vacías (0 leads, 0 auditorías, 0 mensajes)
                for table in ("leads", "historial_actividades", "audit_logs", "linkedin_accounts", "mensajes_linkedin", "commands"):
                    cur.execute(f"SELECT count(*) FROM {table};")
                    self.assertEqual(cur.fetchone()[0], 0, f"La tabla operacional '{table}' debe tener 0 filas")

    def test_02_admin_authentication_and_password_verification(self):
        """Verifica que la contraseña del administrador inicial coincida con su hash PBKDF2."""
        with psycopg.connect(PG_ADMIN_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                cur.execute("SELECT password_hash, salt FROM usuarios WHERE email = 'admin@nexusreach.com';")
                row = cur.fetchone()
                self.assertIsNotNone(row, "Usuario admin@nexusreach.com debe existir")
                pwd_hash, salt = row

                # Validar con la contraseña configurada en el bootstrap
                is_valid = auth_service.verify_password("AdminSecure2026!", salt, pwd_hash)
                self.assertTrue(is_valid, "La contraseña del administrador inicial debe verificar exitosamente")

                # Contraseña incorrecta debe ser rechazada
                is_invalid = auth_service.verify_password("WrongPassword123!", salt, pwd_hash)
                self.assertFalse(is_invalid, "Una contraseña inválida debe ser rechazada")

    def test_03_tenant_isolation_and_crud_under_app_role(self):
        """Verifica que el rol nexus_app bajo ten_primary pueda ejecutar CRUD y esté aislado de otros tenants."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # 1. Configurar contexto del tenant inicial
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_primary', true);")

                # Consulta de tenant propio
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 1)

                # 2. INSERT de un nuevo lead en el tenant inicial
                cur.execute("""
                    INSERT INTO leads (id, tenant_id, perfil_url, nombre, cargo_actual, estado, created_at, updated_at)
                    VALUES ('lead_clean_001', 'ten_primary', 'https://linkedin.com/in/carlos-perez', 'Carlos Pérez', 'CTO', 'NUEVO', '2026-10-29T10:00:00Z', '2026-10-29T10:00:00Z');
                """)

                # 3. SELECT del lead creado
                cur.execute("SELECT nombre, estado FROM leads WHERE id = 'lead_clean_001';")
                lead = cur.fetchone()
                self.assertEqual(lead[0], "Carlos Pérez")

                # 4. UPDATE del lead
                cur.execute("UPDATE leads SET estado = 'CONTACTADO' WHERE id = 'lead_clean_001';")
                self.assertEqual(cur.rowcount, 1)

                cur.execute("SELECT estado FROM leads WHERE id = 'lead_clean_001';")
                self.assertEqual(cur.fetchone()[0], "CONTACTADO")

                # 5. Cambio de contexto a un tenant ajeno (ten_secondary)
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_secondary', true);")

                # No debe ver el lead creado por ten_primary
                cur.execute("SELECT count(*) FROM leads WHERE id = 'lead_clean_001';")
                self.assertEqual(cur.fetchone()[0], 0, "Tenant secundario no debe ver leads de ten_primary")

                # No puede actualizar el lead de ten_primary
                cur.execute("UPDATE leads SET estado = 'HACKED' WHERE id = 'lead_clean_001';")
                self.assertEqual(cur.rowcount, 0, "Update cruzado debe afectar 0 filas")

                # No puede borrar el lead de ten_primary
                cur.execute("DELETE FROM leads WHERE id = 'lead_clean_001';")
                self.assertEqual(cur.rowcount, 0, "Delete cruzado debe afectar 0 filas")

                # 6. Intento de INSERT cruzado con tenant ajeno debe fallar por WITH CHECK
                with self.assertRaises(errors.InsufficientPrivilege):
                    cur.execute("""
                        INSERT INTO leads (id, tenant_id, perfil_url, nombre, estado, created_at, updated_at)
                        VALUES ('lead_spoof_002', 'ten_primary', 'https://linkedin.com/in/spoof', 'Spoof Lead', 'NUEVO', '2026-10-29T10:00:00Z', '2026-10-29T10:00:00Z');
                    """)

            # Revertir la transacción de prueba para dejar la base limpia
            conn.rollback()

    def test_04_unauthenticated_fail_closed_under_app_role(self):
        """Verifica que una sesión sin app.current_tenant_id no retorne ningún registro (fail-closed)."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Sin tenant context configurado
                cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 0, "Sin contexto no debe retornar tenants")

                cur.execute("SELECT count(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 0, "Sin contexto no debe retornar usuarios")

    def test_05_superadmin_crypto_bypass_validation(self):
        """Verifica que el bypass de superadmin funcione con el token correcto y falle con tokens falsos."""
        secret = database.get_superadmin_rls_secret()
        self.assertTrue(bool(secret), "Debe existir un secreto para pruebas locales")

        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Caso A: Intento de bypass malicioso con token falso
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                cur.execute("SELECT set_config('app.super_admin_token', 'token_falso_invalido', true);")
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 0, "Token falso debe retornar 0 filas")

                # Caso B: Bypass legítimo con token criptográfico verificado
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (secret,))
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 1, "SuperAdmin legítimo debe ver los tenants del sistema")

    def test_06_backend_get_db_integration_with_clean_postgres(self):
        """Verifica que database.get_db() opere transparentemente con tenant_context_scope sobre PostgreSQL limpio."""
        old_url = os.environ.get("DATABASE_URL")
        old_is_pg = database.IS_POSTGRES
        old_db_url = database.DATABASE_URL
        try:
            os.environ["DATABASE_URL"] = PG_APP_URL
            database.IS_POSTGRES = True
            database.DATABASE_URL = PG_APP_URL

            # Consulta usando tenant_context_scope
            with database.tenant_context_scope(tenant_id="ten_primary"):
                with database.get_db() as db:
                    cur = db.cursor()
                    cur.execute("SELECT COUNT(*) AS cnt FROM tenants;")
                    row = cur.fetchone()
                    cnt = row["cnt"] if isinstance(row, dict) else row[0]
                    self.assertEqual(cnt, 1, "get_db() debe permitir consultar el tenant propio")

            # Consulta sin contexto
            with database.tenant_context_scope(tenant_id=""):
                with database.get_db() as db:
                    cur = db.cursor()
                    cur.execute("SELECT COUNT(*) AS cnt FROM tenants;")
                    row = cur.fetchone()
                    cnt = row["cnt"] if isinstance(row, dict) else row[0]
                    self.assertEqual(cnt, 0, "Sin contexto get_db() debe retornar 0 filas")
        finally:
            database.IS_POSTGRES = old_is_pg
            database.DATABASE_URL = old_db_url
            if old_url is not None:
                os.environ["DATABASE_URL"] = old_url
            else:
                os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    unittest.main()
