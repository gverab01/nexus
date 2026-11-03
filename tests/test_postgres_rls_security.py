import unittest
from unittest.mock import MagicMock, patch
import os
import sqlite3
import tempfile
import shutil

import database
from database import _configure_pg_context, get_db


class TestPostgresRlsSecurity(unittest.TestCase):
    """Pruebas de seguridad RLS para PostgreSQL (TASK-04).
    Verifica que no exista elevación implícita de privilegios, que el contexto por defecto
    esté estrictamente restringido y que el manejo de superadministrador sea riguroso.
    """

    def setUp(self):
        self.mock_cur = MagicMock()

    def test_scenario_a_no_tenant_id_unprivileged_remains_restricted(self):
        """Escenario A: Conexión sin tenant_id y sin autorización administrativa.
        Debe forzar is_super_admin = 'false' y current_tenant_id = '' para que RLS devuelva 0 filas.
        """
        _configure_pg_context(self.mock_cur, tenant_id=None, is_super_admin=False)

        calls = [c[0] for c in self.mock_cur.execute.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "SELECT set_config('app.is_super_admin', 'false', true);")
        self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', '', true);")
        self.assertEqual(calls[2][0], "SELECT set_config('app.current_tenant_id', '', true);")

    def test_scenario_b_valid_tenant_id_isolated_properly(self):
        """Escenario B: Conexión con tenant_id válido.
        Debe fijar is_super_admin = 'false' y app.current_tenant_id con el tenant exacto.
        """
        _configure_pg_context(self.mock_cur, tenant_id="ten_techcorp", is_super_admin=False)

        calls = [c[0] for c in self.mock_cur.execute.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "SELECT set_config('app.is_super_admin', 'false', true);")
        self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', '', true);")
        self.assertEqual(calls[2][0], "SELECT set_config('app.current_tenant_id', %s, true);")
        self.assertEqual(calls[2][1], ("ten_techcorp",))

    def test_scenario_c_empty_or_whitespace_tenant_id_remains_restricted(self):
        """Escenario C: tenant_id vacío o con solo espacios.
        Debe ser tratado como no provisto, quedando en modo restringido sin fallback.
        """
        _configure_pg_context(self.mock_cur, tenant_id="", is_super_admin=False)
        calls = [c[0] for c in self.mock_cur.execute.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "SELECT set_config('app.is_super_admin', 'false', true);")
        self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', '', true);")
        self.assertEqual(calls[2][0], "SELECT set_config('app.current_tenant_id', '', true);")

        self.mock_cur.reset_mock()
        _configure_pg_context(self.mock_cur, tenant_id="   ", is_super_admin=False)
        calls = [c[0] for c in self.mock_cur.execute.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "SELECT set_config('app.is_super_admin', 'false', true);")
        self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', '', true);")
        self.assertEqual(calls[2][0], "SELECT set_config('app.current_tenant_id', '', true);")

    def test_scenario_d_strict_boolean_check_prevents_client_spoofing(self):
        """Escenario D: Nunca confiar en parámetros no tipados o strings enviados libremente.
        Valores como 'true', '1', o ['admin'] NO deben activar privilegios de superadmin.
        """
        for spoofed_value in ["true", "True", "1", 1, ["admin"], {"admin": True}]:
            self.mock_cur.reset_mock()
            _configure_pg_context(self.mock_cur, tenant_id=None, is_super_admin=spoofed_value)

            calls = [c[0] for c in self.mock_cur.execute.call_args_list]
            self.assertEqual(
                calls[0][0],
                "SELECT set_config('app.is_super_admin', 'false', true);",
                f"Fallo de seguridad: el valor '{spoofed_value}' fue tratado como superadmin!"
            )
            self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', '', true);")
            self.assertEqual(calls[2][0], "SELECT set_config('app.current_tenant_id', '', true);")

    def test_scenario_e_explicit_super_admin_authorized(self):
        """Escenario E: Autorización explícita con booleano estricto True.
        Activa app.is_super_admin = 'true' y suministra app.super_admin_token criptográfico.
        """
        _configure_pg_context(self.mock_cur, tenant_id=None, is_super_admin=True)

        calls = [c[0] for c in self.mock_cur.execute.call_args_list]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "SELECT set_config('app.is_super_admin', 'true', true);")
        self.assertEqual(calls[1][0], "SELECT set_config('app.super_admin_token', %s, true);")
        self.assertEqual(calls[1][1], (database.SUPERADMIN_RLS_SECRET,))

    @patch("database.IS_POSTGRES", True)
    @patch("database.get_pg_pool")
    def test_scenario_f_pool_connection_lifecycle_and_reuse_isolation(self, mock_get_pg_pool):
        """Escenario F: Reutilización de conexiones en pool.
        Verifica que una conexión devuelta al pool configure su contexto de forma
        independiente y determinista en la siguiente operación.
        """
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_get_pg_pool.return_value = mock_pool

        # 1. Operación como superadmin
        with get_db(is_super_admin=True) as conn:
            pass
        self.assertTrue(mock_conn.commit.called)
        calls_op1 = [c[0] for c in mock_cur.execute.call_args_list]
        self.assertIn(("SELECT set_config('app.is_super_admin', 'true', true);",), calls_op1)
        self.assertIn(("SELECT set_config('app.super_admin_token', %s, true);", (database.SUPERADMIN_RLS_SECRET,)), calls_op1)

        # 2. Misma conexión reutilizada para una consulta sin tenant
        mock_cur.reset_mock()
        mock_conn.commit.reset_mock()

        with get_db(tenant_id=None, is_super_admin=False) as conn:
            pass
        self.assertTrue(mock_conn.commit.called)
        calls_op2 = [c[0] for c in mock_cur.execute.call_args_list]
        self.assertIn(("SELECT set_config('app.is_super_admin', 'false', true);",), calls_op2)
        self.assertIn(("SELECT set_config('app.super_admin_token', '', true);",), calls_op2)
        self.assertIn(("SELECT set_config('app.current_tenant_id', '', true);",), calls_op2)

    @patch("database.IS_POSTGRES", True)
    @patch("database.get_pg_pool")
    def test_scenario_g_exception_triggers_rollback_without_state_leak(self, mock_get_pg_pool):
        """Escenario G: Si ocurre un error, la transacción debe ser revertida (rollback)
        garantizando que SET LOCAL sea descartado por PostgreSQL y no filtre estado.
        """
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_get_pg_pool.return_value = mock_pool

        with self.assertRaises(ValueError):
            with get_db(tenant_id="ten_victim") as conn:
                raise ValueError("Simulated unexpected query failure")

        self.assertTrue(mock_conn.rollback.called)
        self.assertFalse(mock_conn.commit.called)

    def test_scenario_h_sqlite_isolation_retains_task01_behavior(self):
        """Escenario H: Confirma que el comportamiento SQLite y SQLITE_DB_PATH
        implementados en TASK-01 permanecen perfectamente funcionales.
        """
        temp_dir = tempfile.mkdtemp(prefix="nexus_task04_sqlite_")
        temp_db = os.path.join(temp_dir, "test_task04.db")
        try:
            os.environ["SQLITE_DB_PATH"] = temp_db
            with get_db() as conn:
                conn.execute("CREATE TABLE t4_test (id INTEGER PRIMARY KEY, valor TEXT)")
                conn.execute("INSERT INTO t4_test (valor) VALUES (?)", ("preservado",))

            with sqlite3.connect(temp_db) as check_conn:
                row = check_conn.execute("SELECT valor FROM t4_test").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "preservado")
        finally:
            os.environ.pop("SQLITE_DB_PATH", None)
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
