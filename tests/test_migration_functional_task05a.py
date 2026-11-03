"""
Test Suite: TASK-05A - Functional Validation & Multi-Tenant RLS on Migrated PostgreSQL Data
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Verifica que tras la migración desde SQLite:
1. Las políticas RLS aíslan estrictamente los datos migrados entre tenants bajo el rol nexus_app.
2. Consultas bajo un tenant_id no filtran filas de otros tenants.
3. Actualizaciones y borrados cruzados son prevenidos por RLS (afectan 0 filas).
4. Inserciones cruzadas violan la política WITH CHECK de RLS.
5. El acceso SuperAdmin autorizado tiene visibilidad completa sobre los datos consolidados.
6. Intentos no autorizados de bypass superadmin fallan y se confinan a 0 filas.
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


class TestMigratedDataFunctionalRLS(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Verify connection to PostgreSQL
        try:
            with psycopg.connect(PG_APP_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT current_user;")
                    user = cur.fetchone()[0]
                    assert user == "nexus_app", f"Expected nexus_app, got {user}"
        except Exception as e:
            raise unittest.SkipTest(f"PostgreSQL test database not available: {e}")

    def test_01_migrated_leads_rls_isolation(self):
        """Verifica que los leads migrados se aíslen estrictamente por tenant."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Tenant 1: ten_d933e9ca99 tiene 175 leads migrados
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_d933e9ca99', true);")
                cur.execute("SELECT COUNT(*) FROM leads;")
                cnt_1 = cur.fetchone()[0]
                self.assertEqual(cnt_1, 175, "ten_d933e9ca99 debe ver exactamente sus 175 leads migrados")

                # Comprobar que todos los leads devueltos pertenecen a este tenant
                cur.execute("SELECT DISTINCT tenant_id FROM leads;")
                tenants_seen = [r[0] for r in cur.fetchall()]
                self.assertEqual(tenants_seen, ['ten_d933e9ca99'])

                # Tenant 2: ten_wa_daily_limit tiene 15 leads migrados
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_wa_daily_limit', true);")
                cur.execute("SELECT COUNT(*) FROM leads;")
                cnt_2 = cur.fetchone()[0]
                self.assertEqual(cnt_2, 15, "ten_wa_daily_limit debe ver exactamente sus 15 leads migrados")

                cur.execute("SELECT DISTINCT tenant_id FROM leads;")
                tenants_seen_2 = [r[0] for r in cur.fetchall()]
                self.assertEqual(tenants_seen_2, ['ten_wa_daily_limit'])

                # Tenant sin leads o inexistente
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_nonexistent', true);")
                cur.execute("SELECT COUNT(*) FROM leads;")
                self.assertEqual(cur.fetchone()[0], 0)

                # Sin tenant context configurado (vacío)
                cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
                cur.execute("SELECT COUNT(*) FROM leads;")
                self.assertEqual(cur.fetchone()[0], 0, "Sin tenant context no debe retornar ningún registro")

    def test_02_migrated_usuarios_rls_isolation(self):
        """Verifica que los usuarios migrados se aíslen estrictamente por tenant."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # ten_techcorp tiene 4 usuarios
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_techcorp', true);")
                cur.execute("SELECT COUNT(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 4)

                cur.execute("SELECT email FROM usuarios;")
                emails = [r[0] for r in cur.fetchall()]
                self.assertEqual(len(emails), 4)

                # ten_sanagustin tiene 1 usuario
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_sanagustin', true);")
                cur.execute("SELECT COUNT(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 1)

                # ten_d933e9ca99 tiene 1 usuario
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_d933e9ca99', true);")
                cur.execute("SELECT COUNT(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 1)

                # ten_wa_daily_limit no tiene usuarios
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_wa_daily_limit', true);")
                cur.execute("SELECT COUNT(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 0)

    def test_03_cross_tenant_update_blocked_by_rls(self):
        """Verifica que un tenant no pueda actualizar registros de otro tenant."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Actuamos como ten_wa_daily_limit
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_wa_daily_limit', true);")
                
                # Intentamos actualizar un lead de ten_d933e9ca99
                cur.execute("""
                    UPDATE leads 
                    SET nombre = 'IntentoAtaque' 
                    WHERE tenant_id = 'ten_d933e9ca99';
                """)
                self.assertEqual(cur.rowcount, 0, "RLS debe invisibilizar el registro, afectando 0 filas")
            conn.rollback()

    def test_04_cross_tenant_delete_blocked_by_rls(self):
        """Verifica que un tenant no pueda borrar registros de otro tenant."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Actuamos como ten_wa_daily_limit
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_wa_daily_limit', true);")
                
                # Intentamos borrar leads de ten_d933e9ca99
                cur.execute("DELETE FROM leads WHERE tenant_id = 'ten_d933e9ca99';")
                self.assertEqual(cur.rowcount, 0, "RLS debe invisibilizar el registro, borrando 0 filas")
            conn.rollback()

    def test_05_cross_tenant_insert_violates_with_check(self):
        """Verifica que un tenant no pueda insertar registros asignados a otro tenant."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Actuamos como ten_wa_daily_limit
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_wa_daily_limit', true);")
                
                with self.assertRaises(errors.InsufficientPrivilege):
                    cur.execute("""
                        INSERT INTO leads (id, tenant_id, nombre, estado, created_at)
                        VALUES ('lead_spoof_01', 'ten_d933e9ca99', 'Spoof Lead', 'NUEVO', '2026-10-29T00:00:00Z');
                    """)
            conn.rollback()

    def test_06_superadmin_access_with_valid_token(self):
        """Verifica que SuperAdmin autorizado con token criptográfico vea la totalidad de los datos migrados."""
        secret = database.get_superadmin_rls_secret()
        self.assertIsNotNone(secret, "El secreto criptográfico RLS debe estar inicializado")

        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (secret,))

                # Total leads migrados
                cur.execute("SELECT COUNT(*) FROM leads;")
                self.assertEqual(cur.fetchone()[0], 194, "SuperAdmin debe ver los 194 leads consolidados")

                # Total tenants migrados
                cur.execute("SELECT COUNT(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 40, "SuperAdmin debe ver los 40 tenants migrados")

                # Total usuarios migrados
                cur.execute("SELECT COUNT(*) FROM usuarios;")
                self.assertEqual(cur.fetchone()[0], 18, "SuperAdmin debe ver los 18 usuarios migrados")

                # Total listas_leads migradas
                cur.execute("SELECT COUNT(*) FROM listas_leads;")
                self.assertEqual(cur.fetchone()[0], 31, "SuperAdmin debe ver las 31 listas migradas")

    def test_07_unauthorized_superadmin_attempt_fails(self):
        """Verifica que una sesión ordinaria intentando bypass sin token no tenga acceso a los datos."""
        with psycopg.connect(PG_APP_URL) as conn:
            with conn.cursor() as cur:
                # Intento de bypass malicioso: sólo SET LOCAL app.is_super_admin = 'true'
                cur.execute("SET LOCAL app.is_super_admin = 'true';")
                # Sin token o con token falso
                cur.execute("SELECT set_config('app.super_admin_token', 'token_falso_invalido', true);")

                cur.execute("SELECT COUNT(*) FROM leads;")
                self.assertEqual(cur.fetchone()[0], 0, "Bypass fraudulento debe ser denegado y retornar 0 filas")

                cur.execute("SELECT COUNT(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 0, "Bypass fraudulento en tenants debe retornar 0 filas")

    def test_08_backend_database_py_integration_with_migrated_data(self):
        """Verifica que get_db() con tenant_context_scope funcione sobre los datos migrados en PostgreSQL."""
        old_url = os.environ.get("DATABASE_URL")
        old_is_pg = database.IS_POSTGRES
        old_db_url = database.DATABASE_URL
        try:
            os.environ["DATABASE_URL"] = PG_APP_URL
            database.IS_POSTGRES = True
            database.DATABASE_URL = PG_APP_URL

            with database.tenant_context_scope(tenant_id="ten_d933e9ca99"):
                with database.get_db() as db:
                    cur = db.cursor()
                    cur.execute("SELECT COUNT(*) AS cnt FROM leads;")
                    row = cur.fetchone()
                    count = row["cnt"] if isinstance(row, dict) else row[0]
                    self.assertEqual(count, 175, "get_db() debe aislar 175 leads para ten_d933e9ca99")

            with database.tenant_context_scope(tenant_id="ten_wa_daily_limit"):
                with database.get_db() as db:
                    cur = db.cursor()
                    cur.execute("SELECT COUNT(*) AS cnt FROM leads;")
                    row = cur.fetchone()
                    count = row["cnt"] if isinstance(row, dict) else row[0]
                    self.assertEqual(count, 15, "get_db() debe aislar 15 leads para ten_wa_daily_limit")

            # Superadmin scope
            with database.tenant_context_scope(is_super_admin=True):
                with database.get_db() as db:
                    cur = db.cursor()
                    cur.execute("SELECT COUNT(*) AS cnt FROM leads;")
                    row = cur.fetchone()
                    count = row["cnt"] if isinstance(row, dict) else row[0]
                    self.assertEqual(count, 194, "SuperAdmin vía get_db() debe ver todos los 194 leads")
        finally:
            database.IS_POSTGRES = old_is_pg
            database.DATABASE_URL = old_db_url
            if old_url is not None:
                os.environ["DATABASE_URL"] = old_url
            else:
                os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    unittest.main()
