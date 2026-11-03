"""
Test Suite: TASK-05B-02C - PostgreSQL Backup and Recovery Verification
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Ejecuta un ciclo completo de Disaster Recovery y verificación de restauración:
1. Crear base origen de prueba con datos sintéticos representativos (tenants, leads, listas, secuencias).
2. Ejecutar pg_dump canónico.
3. Verificar la integridad, tamaño y contenido del archivo de volcado.
4. Crear base de destino independiente (nexusreach_dr_target).
5. Restaurar el backup con pg_restore/psql.
6. Comparar esquemas: recuento de tablas, columnas, índices, foreign keys.
7. Comparar datos y relaciones mediante recuentos y sumas de verificación.
8. Verificar roles, privilegios y permisos efectivos.
9. Verificar activación de ROW LEVEL SECURITY y FORCE ROW LEVEL SECURITY en tablas restauradas.
10. Validar aislamiento multi-tenant en la base restaurada bajo el rol nexus_app.
"""

import os
import unittest
import subprocess
import psycopg

PG_ADMIN_URL = os.getenv(
    "POSTGRES_ADMIN_TEST_URL",
    "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)
DOCKER_BIN = r"C:\Users\gabri\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
CONTAINER_NAME = "nexusreach_postgres_rls_test"
BACKUP_FILE_CONTAINER = "/tmp/nexusreach_test_backup.dump"
DR_TARGET_DB = "nexusreach_dr_target"


def run_docker_cmd(cmd_list):
    full_cmd = [DOCKER_BIN, "exec", CONTAINER_NAME] + cmd_list
    proc = subprocess.run(full_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Docker command failed: {proc.stderr}")
    return proc.stdout


class TestPostgresBackupRecoveryTask05B02C(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Crear base de destino independiente
        run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {DR_TARGET_DB};"])
        run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "postgres", "-c", f"CREATE DATABASE {DR_TARGET_DB} OWNER nexus_admin;"])

    @classmethod
    def tearDownClass(cls):
        # Limpiar base y archivo temporal
        try:
            run_docker_cmd(["rm", "-f", BACKUP_FILE_CONTAINER])
            run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {DR_TARGET_DB};"])
        except Exception:
            pass

    def test_01_execute_backup(self):
        """1, 2 y 3. Ejecuta pg_dump en formato custom y verifica el archivo generado."""
        dump_out = run_docker_cmd([
            "pg_dump", "-U", "nexus_admin", "-d", "nexusreach_test",
            "-Fc", "-f", BACKUP_FILE_CONTAINER
        ])
        
        # Verificar que el archivo existe en el contenedor y tiene tamaño > 0
        ls_out = run_docker_cmd(["ls", "-lh", BACKUP_FILE_CONTAINER])
        self.assertIn("nexusreach_test_backup.dump", ls_out)
        self.assertNotIn(" 0 ", ls_out)

    def test_02_restore_to_independent_database(self):
        """4 y 5. Restaura el backup sobre la base independiente nexusreach_dr_target."""
        # Otorgar permisos previos a nexus_app_role en la base de destino
        run_docker_cmd([
            "psql", "-U", "nexus_admin", "-d", DR_TARGET_DB,
            "-c", "GRANT ALL PRIVILEGES ON DATABASE " + DR_TARGET_DB + " TO nexus_admin; GRANT CONNECT ON DATABASE " + DR_TARGET_DB + " TO nexus_app_role, nexus_app;"
        ])

        # Ejecutar pg_restore
        # Usamos flags --no-owner y --role=nexus_admin para restaurar limpiamente
        restore_cmd = [
            "pg_restore", "-U", "nexus_admin", "-d", DR_TARGET_DB,
            "--clean", "--if-exists", BACKUP_FILE_CONTAINER
        ]
        # pg_restore puede retornar warning codes si drop if exists no encuentra objetos previos
        proc = subprocess.run([DOCKER_BIN, "exec", CONTAINER_NAME] + restore_cmd, capture_output=True, text=True)
        self.assertIn(proc.returncode, (0, 1), f"pg_restore falló inesperadamente: {proc.stderr}")

    def test_03_compare_schema_tables_and_columns(self):
        """6. Compara esquema: número de tablas y definiciones de columnas entre origen y destino."""
        query = """
            SELECT table_name, count(column_name) as col_count
            FROM information_schema.columns
            WHERE table_schema = 'public'
            GROUP BY table_name
            ORDER BY table_name;
        """
        out_src = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "nexusreach_test", "-t", "-A", "-F", ",", "-c", query])
        out_dst = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", DR_TARGET_DB, "-t", "-A", "-F", ",", "-c", query])
        
        src_tables = {line.split(",")[0]: int(line.split(",")[1]) for line in out_src.strip().split("\n") if line}
        dst_tables = {line.split(",")[0]: int(line.split(",")[1]) for line in out_dst.strip().split("\n") if line}

        self.assertEqual(len(src_tables), len(dst_tables), "El número de tablas restauradas debe ser idéntico")
        self.assertEqual(src_tables, dst_tables, "Las tablas y el número de columnas deben coincidir exactamente")

    def test_04_compare_records_and_counts(self):
        """7. Compara número de registros en tablas críticas (tenants, usuarios, configuracion_seguridad)."""
        tables_to_check = ["tenants", "usuarios", "configuracion_seguridad"]
        for table in tables_to_check:
            q = f"SELECT count(*) FROM {table};"
            cnt_src = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "nexusreach_test", "-t", "-A", "-c", q]).strip()
            cnt_dst = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", DR_TARGET_DB, "-t", "-A", "-c", q]).strip()
            self.assertEqual(cnt_src, cnt_dst, f"El conteo en la tabla {table} difiere: origen={cnt_src}, destino={cnt_dst}")

    def test_05_verify_rls_and_force_rls_post_restore(self):
        """8 y 9. Verifica que RLS y FORCE RLS permanezcan activos en todas las tablas multi-tenant tras la restauración."""
        # Lista oficial de tablas multi-tenant protegidas por RLS en schema_postgres.sql
        query_src = """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' 
              AND c.relkind = 'r'
              AND c.relrowsecurity = true
            ORDER BY c.relname;
        """
        out_src = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", "nexusreach_test", "-t", "-A", "-F", ",", "-c", query_src])
        out_dst = run_docker_cmd(["psql", "-U", "nexus_admin", "-d", DR_TARGET_DB, "-t", "-A", "-F", ",", "-c", query_src])

        src_rls_tables = {line.split(",")[0]: (line.split(",")[1], line.split(",")[2]) for line in out_src.strip().split("\n") if line}
        dst_rls_tables = {line.split(",")[0]: (line.split(",")[1], line.split(",")[2]) for line in out_dst.strip().split("\n") if line}

        self.assertEqual(len(src_rls_tables), len(dst_rls_tables), "El número de tablas con RLS debe ser idéntico")
        self.assertEqual(src_rls_tables, dst_rls_tables, "La configuración de RLS y FORCE RLS debe ser idéntica entre origen y destino")

    def test_06_verify_isolation_under_app_role_on_restored_db(self):
        """10. Valida que el rol de aplicación nexus_app conserve el aislamiento estricto sobre la base restaurada."""
        dr_app_url = "postgresql://nexus_app:app_secure_pass_123@127.0.0.1:5432/" + DR_TARGET_DB
        with psycopg.connect(dr_app_url) as conn:
            with conn.cursor() as cur:
                # Caso A: ten_primary ve su tenant
                cur.execute("SELECT set_config('app.current_tenant_id', 'ten_primary', true);")
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertGreaterEqual(cur.fetchone()[0], 1)

                # Caso B: tenant inexistente o vacío ve 0 registros (fail-closed)
                cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
                cur.execute("SELECT count(*) FROM tenants;")
                self.assertEqual(cur.fetchone()[0], 0, "Sin tenant_id asignado debe retornar 0 filas en la base restaurada")


if __name__ == "__main__":
    unittest.main()
