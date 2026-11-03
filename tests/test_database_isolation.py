import os
import sqlite3
import tempfile
import unittest
import shutil

import database
from database import get_db, init_db, get_sqlite_db_path, DEFAULT_SQLITE_PATH


class TestDatabaseIsolation(unittest.TestCase):
    """Pruebas unitarias de aislamiento de base de datos SQLite (TASK-01).
    Verifica que SQLITE_DB_PATH redirija adecuadamente las conexiones,
    que la ruta predeterminada sea leads.db y que no ocurra fallback silencioso.
    """

    def setUp(self):
        # Guardar valor original del entorno
        self.original_env = os.environ.get("SQLITE_DB_PATH")

    def tearDown(self):
        # Restaurar valor original del entorno
        if self.original_env is None:
            os.environ.pop("SQLITE_DB_PATH", None)
        else:
            os.environ["SQLITE_DB_PATH"] = self.original_env

    def test_default_path_when_env_unset(self):
        """Verifica que sin la variable SQLITE_DB_PATH se use leads.db por defecto."""
        os.environ.pop("SQLITE_DB_PATH", None)
        self.assertEqual(get_sqlite_db_path(), DEFAULT_SQLITE_PATH)
        self.assertTrue(get_sqlite_db_path().endswith("leads.db"))

    def test_default_path_when_env_empty_or_whitespace(self):
        """Verifica que si la variable está vacía o contiene solo espacios se use leads.db."""
        os.environ["SQLITE_DB_PATH"] = ""
        self.assertEqual(get_sqlite_db_path(), DEFAULT_SQLITE_PATH)

        os.environ["SQLITE_DB_PATH"] = "   "
        self.assertEqual(get_sqlite_db_path(), DEFAULT_SQLITE_PATH)

    def test_custom_path_redirection_and_isolation(self):
        """Verifica que al configurar SQLITE_DB_PATH las escrituras e init_db
        ocurran en la base temporal sin contaminar leads.db.
        """
        temp_dir = tempfile.mkdtemp(prefix="nexus_isolation_test_")
        temp_db_path = os.path.join(temp_dir, "test_sandbox.db")
        try:
            os.environ["SQLITE_DB_PATH"] = temp_db_path
            self.assertEqual(get_sqlite_db_path(), temp_db_path)

            # Inicializar esquema en la base temporal (redirigiendo stdout para evitar fallos de encoding cp1252 en consolas Windows por emojis de logs)
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                init_db()

            # Confirmar que el archivo temporal existe y tiene tablas
            self.assertTrue(os.path.exists(temp_db_path))
            with sqlite3.connect(temp_db_path) as direct_conn:
                tables = [row[0] for row in direct_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                self.assertIn("leads", tables)
                self.assertIn("tenants", tables)

            # Insertar un registro único de prueba a través de get_db()
            unique_test_lead_id = "lead_isolation_probe_99999"
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO leads (id, nombre, perfil_url) VALUES (?, ?, ?)",
                    (unique_test_lead_id, "Sonda de Aislamiento", "https://linkedin.com/in/sonda-test")
                )

            # Verificar que el registro está en la base temporal
            with sqlite3.connect(temp_db_path) as direct_conn:
                row = direct_conn.execute("SELECT nombre FROM leads WHERE id = ?", (unique_test_lead_id,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "Sonda de Aislamiento")

            # Verificar que el registro NO está en leads.db (base operativa)
            with sqlite3.connect(DEFAULT_SQLITE_PATH) as prod_conn:
                prod_row = prod_conn.execute("SELECT nombre FROM leads WHERE id = ?", (unique_test_lead_id,)).fetchone()
                self.assertIsNone(prod_row, "ERROR CRÍTICO: El registro de prueba se filtró a leads.db!")

        finally:
            # Asegurar cierre de conexiones antes de limpiar
            os.environ.pop("SQLITE_DB_PATH", None)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_invalid_path_raises_error_without_fallback(self):
        """Verifica que una ruta inválida levante una excepción explícita
        y NUNCA haga fallback silencioso a leads.db.
        """
        non_existent_dir = os.path.join(tempfile.gettempdir(), "nonexistent_dir_nexus_xyz123", "sub", "invalid.db")
        os.environ["SQLITE_DB_PATH"] = non_existent_dir

        # Intentar obtener conexión debe fallar con sqlite3.OperationalError
        with self.assertRaises(sqlite3.OperationalError):
            with get_db() as conn:
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
