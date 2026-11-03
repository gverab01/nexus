import os
import re
import unittest
from typing import Optional, Dict, Any, List

import database
from database import (
    tenant_context_scope,
    set_current_tenant_context,
    clear_current_tenant_context,
    get_current_tenant_context,
    _configure_pg_context,
    verify_pg_security_posture,
    get_db
)


def _check_real_postgres_available() -> Optional[str]:
    """Retorna la URL de conexión a PostgreSQL si está disponible y accesible, o None."""
    db_url = os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not (db_url.startswith("postgres://") or db_url.startswith("postgresql://")):
        return None
    try:
        import psycopg
        conn = psycopg.connect(db_url, connect_timeout=3)
        conn.close()
        return db_url
    except Exception:
        return None


REAL_PG_URL = _check_real_postgres_available()


class TestPostgresSchemaStaticSecurity(unittest.TestCase):
    """Pruebas estáticas obligatorias del esquema PostgreSQL (TASK-04B).
    Verifican la integridad sintáctica, completitud de tablas, cobertura total de RLS
    y ausencia de defaults privilegiados en schema_postgres.sql.
    """

    @classmethod
    def setUpClass(cls):
        schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema_postgres.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            cls.schema_sql = f.read()

    def test_sql_parentheses_and_statement_balance(self):
        """Verifica que el script SQL no tenga paréntesis desbalanceados ni errores de sintaxis."""
        stack = []
        for i, char in enumerate(self.schema_sql):
            if char == '(':
                stack.append(i)
            elif char == ')':
                self.assertTrue(len(stack) > 0, f"Paréntesis de cierre ')' sin apertura en posición {i}")
                stack.pop()
        self.assertEqual(len(stack), 0, f"Paréntesis de apertura '(' sin cerrar en posiciones {stack[:5]}")

    def test_all_multi_tenant_tables_have_rls_and_force_rls(self):
        """Verifica que las 32 tablas multi-tenant tengan ENABLE ROW LEVEL SECURITY y FORCE ROW LEVEL SECURITY."""
        tables_created = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', self.schema_sql)
        rls_enabled = set(re.findall(r'ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY', self.schema_sql))
        rls_forced = set(re.findall(r'ALTER TABLE (\w+) FORCE ROW LEVEL SECURITY', self.schema_sql))
        policies = set(re.findall(r'CREATE POLICY \w+ ON (\w+)', self.schema_sql))

        # Tablas globales expresamente justificadas fuera de RLS
        global_tables = {
            'configuracion_seguridad',  # Parámetros y límites anti-baneo globales de la plataforma
            'selector_versions',        # Catálogo firmado de selectores compartido por todos los workers
            'action_status',            # Interruptores de salud y fallback global de selectores
            'payment_webhook_events',   # Registro idempotente global de webhooks de pasarelas de pago
            'system_admin_keys'         # Claves criptográficas de bypass RLS restringidas a nivel de rol de BD
        }

        tenant_tables = [t for t in tables_created if t not in global_tables]
        self.assertEqual(len(tenant_tables), 32, f"Se esperaban 32 tablas multi-tenant, se encontraron {len(tenant_tables)}")

        for table in tenant_tables:
            self.assertIn(table, rls_enabled, f"Falla de seguridad: Tabla multi-tenant '{table}' NO tiene ENABLE ROW LEVEL SECURITY")
            self.assertIn(table, rls_forced, f"Falla de seguridad: Tabla multi-tenant '{table}' NO tiene FORCE ROW LEVEL SECURITY")
            self.assertIn(table, policies, f"Falla de seguridad: Tabla multi-tenant '{table}' NO tiene política RLS definida")

    def test_no_privileged_defaults_in_schema(self):
        """Verifica que no existan valores por defecto inseguros como DEFAULT 'ten_superadmin'."""
        privileged_defaults = re.findall(r"DEFAULT\s+'ten_superadmin'", self.schema_sql, re.IGNORECASE)
        self.assertEqual(
            len(privileged_defaults),
            0,
            f"Falla de seguridad: Se detectaron {len(privileged_defaults)} fallbacks a 'ten_superadmin' en el esquema!"
        )

    def test_application_role_definition_exists_with_least_privilege(self):
        """Verifica que el rol 'nexus_app_role' esté definido con atributos NOSUPERUSER y NOBYPASSRLS."""
        self.assertIn("nexus_app_role", self.schema_sql)
        self.assertIn("NOSUPERUSER", self.schema_sql)
        self.assertIn("NOBYPASSRLS", self.schema_sql)

    def test_missing_table_mensajes_whatsapp_is_present(self):
        """Verifica que la tabla mensajes_whatsapp esté formalmente definida en el esquema."""
        self.assertIn("CREATE TABLE IF NOT EXISTS mensajes_whatsapp", self.schema_sql)
        self.assertIn("ALTER TABLE mensajes_whatsapp ENABLE ROW LEVEL SECURITY", self.schema_sql)
        self.assertIn("ALTER TABLE mensajes_whatsapp FORCE ROW LEVEL SECURITY", self.schema_sql)


class TestPostgresContextVarsAndPosture(unittest.TestCase):
    """Pruebas unitarias de gestión de contexto y verificación de postura (TASK-04B)."""

    def tearDown(self):
        clear_current_tenant_context()

    def test_context_vars_lifecycle_and_scope(self):
        """Verifica que tenant_context_scope delimite y limpie el contexto de forma transparente."""
        self.assertIsNone(get_current_tenant_context()["tenant_id"])
        self.assertFalse(get_current_tenant_context()["is_super_admin"])

        with tenant_context_scope("ten_cliente_123", is_super_admin=False):
            ctx = get_current_tenant_context()
            self.assertEqual(ctx["tenant_id"], "ten_cliente_123")
            self.assertFalse(ctx["is_super_admin"])

        # Al salir del scope debe quedar limpio
        self.assertIsNone(get_current_tenant_context()["tenant_id"])

    def test_set_and_clear_context(self):
        """Verifica que set_current_tenant_context y clear_current_tenant_context funcionen según contrato."""
        set_current_tenant_context("ten_alpha", is_super_admin=True)
        ctx = get_current_tenant_context()
        self.assertEqual(ctx["tenant_id"], "ten_alpha")
        self.assertTrue(ctx["is_super_admin"])

        clear_current_tenant_context()
        ctx_clean = get_current_tenant_context()
        self.assertIsNone(ctx_clean["tenant_id"])
        self.assertFalse(ctx_clean["is_super_admin"])

    def test_verify_pg_security_posture_detects_insecure_role(self):
        """Verifica que verify_pg_security_posture detecte y rechace roles SUPERUSER o BYPASSRLS."""
        from unittest.mock import MagicMock
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Simular rol superusuario inseguro
        mock_cur.fetchone.return_value = {
            "rolname": "postgres",
            "rolsuper": True,
            "rolbypassrls": False
        }
        mock_cur.fetchall.return_value = []

        report = verify_pg_security_posture(mock_conn, strict=False)
        self.assertFalse(report["secure"])
        self.assertTrue(report["is_superuser"])

        with self.assertRaises(RuntimeError):
            verify_pg_security_posture(mock_conn, strict=True)


@unittest.skipIf(
    REAL_PG_URL is None,
    "BLOCKED: Instancia real de PostgreSQL no disponible en el entorno local de ejecución. "
    "Para ejecutar estas pruebas en un entorno con PostgreSQL/Docker, levantar: "
    "`docker compose -f docker-compose.postgres-test.yml up -d` y exportar `TEST_DATABASE_URL`."
)
class TestPostgresRealRlsIntegration(unittest.TestCase):
    """Pruebas de integración real contra PostgreSQL con Row-Level Security (TASK-04B).
    Requiere una instancia viva de PostgreSQL accesible mediante TEST_DATABASE_URL.
    """

    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.rows import dict_row
        cls.conn = psycopg.connect(REAL_PG_URL, row_factory=dict_row)
        cls.conn.autocommit = True
        with cls.conn.cursor() as cur:
            # Asegurar tenants sintéticos para las pruebas con autorización criptográfica
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (database.SUPERADMIN_RLS_SECRET,))
            cur.execute("""
                INSERT INTO tenants (id, razon_social, created_at, updated_at)
                VALUES ('test_pg_ten_a', 'Tenant A Test', '2026-10-28', '2026-10-28')
                ON CONFLICT (id) DO NOTHING;
            """)
            cur.execute("""
                INSERT INTO tenants (id, razon_social, created_at, updated_at)
                VALUES ('test_pg_ten_b', 'Tenant B Test', '2026-10-28', '2026-10-28')
                ON CONFLICT (id) DO NOTHING;
            """)
            cur.execute("COMMIT;")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn") and cls.conn:
            cls.conn.close()

    def setUp(self):
        # Limpiar datos de prueba antes de cada test
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (database.SUPERADMIN_RLS_SECRET,))
            cur.execute("DELETE FROM leads_en_lista WHERE id LIKE 'test_pg_%';")
            cur.execute("DELETE FROM listas_leads WHERE id LIKE 'test_pg_%';")
            cur.execute("DELETE FROM leads WHERE id LIKE 'test_pg_%';")
            cur.execute("COMMIT;")

    def test_01_verify_app_role_security_posture(self):
        """Verifica que la conexión de aplicación no tenga privilegios SUPERUSER ni BYPASSRLS."""
        posture = verify_pg_security_posture(self.conn, strict=False)
        self.assertFalse(posture["is_superuser"], "Falla de postura: El rol de pruebas no debe ser SUPERUSER!")
        self.assertFalse(posture["is_bypassrls"], "Falla de postura: El rol de pruebas no debe tener BYPASSRLS!")
        self.assertEqual(posture["role"], "nexus_app")
        self.assertEqual(posture["tables_audited"], 32)
        self.assertEqual(posture["tables_with_rls"], 32)
        self.assertEqual(posture["tables_with_force_rls"], 32)
        self.assertTrue(posture["secure"], f"Postura de seguridad no aprobada: {posture['details']}")

    def test_02_tenant_a_can_insert_and_read_own_records(self):
        """Verifica que Tenant A pueda insertar y consultar sus propios prospectos."""
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                VALUES ('test_pg_lead_1', 'test_pg_ten_a', 'Lead A', 'https://linkedin.com/in/lead-a', '2026-10-28', '2026-10-28');
            """)
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_1';")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["tenant_id"], "test_pg_ten_a")
            cur.execute("COMMIT;")

    def test_03_tenant_b_cannot_read_or_modify_tenant_a_records(self):
        """Verifica que Tenant B no pueda leer, actualizar ni eliminar prospectos de Tenant A."""
        # 1. Insertar como Tenant A
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                VALUES ('test_pg_lead_iso', 'test_pg_ten_a', 'Lead A Protegido', 'https://linkedin.com/in/lead-iso', '2026-10-28', '2026-10-28');
            """)
            cur.execute("COMMIT;")

        # 2. Intentar leer como Tenant B -> Debe retornar 0 filas
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_b', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_iso';")
            self.assertIsNone(cur.fetchone(), "Violación RLS: Tenant B pudo leer el registro de Tenant A!")

            # 3. Intentar actualizar como Tenant B -> 0 filas modificadas
            cur.execute("UPDATE leads SET nombre = 'Hackeado' WHERE id = 'test_pg_lead_iso';")
            self.assertEqual(cur.rowcount, 0, "Violación RLS: Tenant B pudo modificar el registro de Tenant A!")

            # 4. Intentar eliminar como Tenant B -> 0 filas eliminadas
            cur.execute("DELETE FROM leads WHERE id = 'test_pg_lead_iso';")
            self.assertEqual(cur.rowcount, 0, "Violación RLS: Tenant B pudo eliminar el registro de Tenant A!")
            cur.execute("COMMIT;")

    def test_04_cross_tenant_insert_rejected_by_with_check(self):
        """Verifica que un intento de insertar datos con tenant_id ajeno sea bloqueado por WITH CHECK."""
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")

            # Intentar insertar un lead con tenant_id de B estando en contexto de A
            with self.assertRaises(Exception) as ctx:
                cur.execute("""
                    INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                    VALUES ('test_pg_lead_spoof', 'test_pg_ten_b', 'Lead Malicioso', 'https://linkedin.com/in/lead-spoof', '2026-10-28', '2026-10-28');
                """)
            cur.execute("ROLLBACK;")
            self.assertIn("row-level security policy", str(ctx.exception).lower())

    def test_05_unauthenticated_empty_context_returns_zero_rows(self):
        """Verifica que consultas sin contexto de tenant retornen 0 filas (fail-closed)."""
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT COUNT(*) as total FROM leads;")
            count = cur.fetchone()["total"]
            self.assertEqual(count, 0, "Violación de aislamiento: Consulta sin tenant devolvió filas protegidas!")
            cur.execute("COMMIT;")

    def test_06_bridge_tables_cross_tenant_association_blocked(self):
        """Verifica que tablas puente (leads_en_lista) impidan asociar entidades entre tenants distintos."""
        # 1. Crear lead y lista para Tenant A
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                VALUES ('test_pg_lead_a', 'test_pg_ten_a', 'Lead A', 'https://linkedin.com/in/lead-a-bridge', '2026-10-28', '2026-10-28');
            """)
            cur.execute("""
                INSERT INTO listas_leads (id, tenant_id, nombre, created_at, updated_at)
                VALUES ('test_pg_lista_a', 'test_pg_ten_a', 'Lista A', '2026-10-28', '2026-10-28');
            """)
            cur.execute("COMMIT;")

        # 2. Crear lista para Tenant B
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_b', true);")
            cur.execute("""
                INSERT INTO listas_leads (id, tenant_id, nombre, created_at, updated_at)
                VALUES ('test_pg_lista_b', 'test_pg_ten_b', 'Lista B', '2026-10-28', '2026-10-28');
            """)
            cur.execute("COMMIT;")

        # 3. Tenant A intentando asociar su lead a la lista de Tenant B debe ser rechazado
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            with self.assertRaises(Exception) as ctx:
                cur.execute("""
                    INSERT INTO leads_en_lista (id, lista_id, lead_id, created_at)
                    VALUES ('test_pg_bridge_spoof', 'test_pg_lista_b', 'test_pg_lead_a', '2026-10-28');
                """)
            cur.execute("ROLLBACK;")
            self.assertIn("row-level security policy", str(ctx.exception).lower())

    def test_07_connection_reuse_and_transaction_leak_prevention(self):
        """Verifica que una conexión reutilizada para Tenant B no conserve estado del Tenant A."""
        # Transacción 1: Tenant A
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                VALUES ('test_pg_lead_reuse', 'test_pg_ten_a', 'Lead Reuse', 'https://linkedin.com/in/lead-reuse', '2026-10-28', '2026-10-28');
            """)
            cur.execute("COMMIT;")

        # Transacción 2: Misma conexión, sin configurar tenant -> debe retornar 0
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET LOCAL app.is_super_admin = 'false';")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_reuse';")
            self.assertIsNone(cur.fetchone())
            cur.execute("COMMIT;")

    def test_08_super_admin_bypass_restricted_to_explicit_boolean(self):
        """Verifica que el bypass administrativo requiera is_super_admin='true' Y token criptográfico válido."""
        # 1. Crear un registro para Tenant A
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'false', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                VALUES ('test_pg_lead_sa', 'test_pg_ten_a', 'Lead SA', 'https://linkedin.com/in/lead-sa', '2026-10-28', '2026-10-28');
            """)
            cur.execute("COMMIT;")

        # 2. Intento de ataque: Solo establecer app.is_super_admin = 'true' SIN token -> Retorna 0 filas (BLOQUEADO)
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', '', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_sa';")
            self.assertIsNone(cur.fetchone(), "Fallo de seguridad: app.is_super_admin='true' sin token no debe dar acceso global!")
            cur.execute("COMMIT;")

        # 3. Intento de ataque: app.is_super_admin = 'true' con token falso -> Retorna 0 filas (BLOQUEADO)
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', 'token_falso_hacker', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_sa';")
            self.assertIsNone(cur.fetchone(), "Fallo de seguridad: Token falso no debe dar acceso global!")
            cur.execute("COMMIT;")

        # 4. Vía legítima de superadministrador con token criptográfico válido -> Puede leer el registro
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (database.SUPERADMIN_RLS_SECRET,))
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_sa';")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["id"], "test_pg_lead_sa")
            cur.execute("COMMIT;")

        # 5. Con app.is_super_admin = 'false' -> Retorna 0
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'false', true);")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT * FROM leads WHERE id = 'test_pg_lead_sa';")
            self.assertIsNone(cur.fetchone())
            cur.execute("COMMIT;")

    def test_09_database_get_db_integration_with_contextvars(self):
        """Verifica que el context manager get_db() funcione con PostgreSQL real respetando contextvars."""
        orig_is_postgres = database.IS_POSTGRES
        orig_database_url = database.DATABASE_URL
        try:
            database.IS_POSTGRES = True
            database.DATABASE_URL = REAL_PG_URL

            # Consulta con contexto de Tenant A
            with tenant_context_scope("test_pg_ten_a"):
                with get_db() as db_conn:
                    cur = db_conn.cursor()
                    cur.execute("""
                        INSERT INTO leads (id, tenant_id, nombre, perfil_url, created_at, updated_at)
                        VALUES ('test_pg_lead_getdb', 'test_pg_ten_a', 'Lead get_db', 'https://linkedin.com/in/lead-getdb', '2026-10-28', '2026-10-28');
                    """)
                    cur.execute("SELECT id FROM leads WHERE id = 'test_pg_lead_getdb';")
                    self.assertIsNotNone(cur.fetchone())

            # Consulta fuera de contexto -> Debe retornar 0 filas
            with get_db() as db_conn:
                cur = db_conn.cursor()
                cur.execute("SELECT id FROM leads WHERE id = 'test_pg_lead_getdb';")
                self.assertIsNone(cur.fetchone())

        finally:
            database.IS_POSTGRES = orig_is_postgres
            database.DATABASE_URL = orig_database_url

    def test_10_rollback_drops_set_local_state(self):
        """Verifica que una excepción y rollback descarten el estado de la transacción sin contaminar la sesión."""
        with self.conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.current_tenant_id', 'test_pg_ten_a', true);")
            cur.execute("ROLLBACK;")

            # Tras el rollback, la configuración local de la transacción debe ser inexistente o vacía
            cur.execute("SELECT current_setting('app.current_tenant_id', true) as val;")
            val = cur.fetchone()["val"]
            self.assertTrue(val is None or val == "")

    def test_11_attacker_cannot_read_system_admin_keys(self):
        """Verifica que el rol no privilegiado 'nexus_app' no pueda consultar la tabla system_admin_keys."""
        import psycopg
        with self.conn.cursor() as cur:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT * FROM system_admin_keys;")

    def test_12_verify_super_admin_context_function_logic(self):
        """Verifica exhaustivamente el comportamiento de la función criptográfica verify_super_admin_context()."""
        with self.conn.cursor() as cur:
            # Caso 1: Sin configurar nada -> False
            cur.execute("SELECT verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"])

            # Caso 2: Atacante fija app.is_super_admin='true' pero sin token -> False
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"])
            cur.execute("ROLLBACK;")

            # Caso 3: Atacante fija token falso o inválido -> False
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', 'wrong_token_123', true);")
            cur.execute("SELECT verify_super_admin_context() as authorized;")
            self.assertFalse(cur.fetchone()["authorized"])
            cur.execute("ROLLBACK;")

            # Caso 4: Backend legítimo con token correcto -> True
            cur.execute("BEGIN;")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (database.SUPERADMIN_RLS_SECRET,))
            cur.execute("SELECT verify_super_admin_context() as authorized;")
            self.assertTrue(cur.fetchone()["authorized"])
            cur.execute("ROLLBACK;")


if __name__ == "__main__":
    unittest.main()
