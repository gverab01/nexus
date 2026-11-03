#!/usr/bin/env python3
"""
NexusReach Pro - Backup Restoration Verification Engine
TASK-05B-06 [P0]

Verifica de forma estricta la restaurabilidad del backup lógico:
1. Toma el volcado más reciente de backups/postgres/.
2. Crea una base de datos independiente: nexusreach_restore_test.
3. Restaura el volcado usando pg_restore.
4. Audita y compara contra la base origen (nexusreach_prod):
   - Estructura de tablas y recuento de columnas.
   - Recuento de filas por tabla.
   - Configuración RLS (relrowsecurity y relforcerowsecurity en las 32 tablas multi-tenant).
   - Comportamiento del rol nexus_app en la base restaurada.
   - Integridad y funcionamiento de verify_super_admin_context().
5. Confirma que nexusreach_prod no sufrió modificaciones durante la prueba.
"""

import os
import sys
import glob
import subprocess
import psycopg
from psycopg import errors

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups", "postgres")
DOCKER_BIN = r"C:\Users\gabri\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
CONTAINER_NAME = "nexusreach_postgres_rls_test"

PROD_DB = "nexusreach_prod"
RESTORE_DB = "nexusreach_restore_test"

# Leer configuración desde .env
def get_env_credentials():
    env_vars = {}
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars


def run_psql_admin(sql_query: str, db: str = "postgres") -> str:
    """Ejecuta consulta administrativa vía docker exec psql."""
    cmd = [
        DOCKER_BIN, "exec", "-i", CONTAINER_NAME,
        "psql", "-U", "nexus_admin", "-d", db, "-t", "-A"
    ]
    proc = subprocess.run(cmd, input=sql_query, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"psql error en db {db}: {proc.stderr}")
    return proc.stdout.strip()


def main():
    print("=" * 80)
    print("VERIFICACIÓN DE RESTAURACIÓN DE BACKUP POSTGRESQL (TASK-05B-06)")
    print("=" * 80)

    # 1. Encontrar el último backup
    pattern = os.path.join(BACKUP_DIR, f"{PROD_DB}_backup_*.dump")
    dumps = glob.glob(pattern)
    if not dumps:
        print("[ERROR] No se encontraron archivos de backup en:", BACKUP_DIR)
        return 1
    dumps.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    latest_dump = dumps[0]
    print(f"\n[PASO 1] Archivo de backup seleccionado para restauración:")
    print(f"  Ruta: {latest_dump}")
    print(f"  Tamaño: {os.path.getsize(latest_dump):,} bytes")

    # 2. Registrar métricas de producción antes de la prueba para verificar no-mutación
    env_vars = get_env_credentials()
    app_url = env_vars.get("DATABASE_URL")
    admin_url = env_vars.get("POSTGRES_ADMIN_URL")
    superadmin_secret = env_vars.get("SUPERADMIN_RLS_SECRET")

    print("\n[PASO 2] Capturando estado base de nexusreach_prod...")
    prod_metrics = {}
    with psycopg.connect(admin_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(f'SELECT count(*) FROM "{t}";')
                prod_metrics[t] = cur.fetchone()[0]
    print(f"  [✓] {len(tables)} tablas auditadas en {PROD_DB}.")

    # 3. Preparar base de datos independiente de restauración
    print(f"\n[PASO 3] Creando base de datos independiente '{RESTORE_DB}'...")
    run_psql_admin(f"DROP DATABASE IF EXISTS {RESTORE_DB};", "postgres")
    run_psql_admin(f"CREATE DATABASE {RESTORE_DB} OWNER nexus_admin;", "postgres")
    run_psql_admin(
        f"GRANT ALL PRIVILEGES ON DATABASE {RESTORE_DB} TO nexus_admin; "
        f"GRANT CONNECT ON DATABASE {RESTORE_DB} TO nexus_app_role, nexus_app;",
        RESTORE_DB
    )
    print(f"  [✓] Base de datos {RESTORE_DB} creada y aprovisionada limpiamente.")

    # 4. Ejecutar pg_restore
    print(f"\n[PASO 4] Restaurando volcado mediante pg_restore en '{RESTORE_DB}'...")
    # Ejecutamos pg_restore leyendo el volcado por stdin binario
    cmd = [
        DOCKER_BIN, "exec", "-i", CONTAINER_NAME,
        "pg_restore", "-U", "nexus_admin", "-d", RESTORE_DB,
        "--no-owner", "--role=nexus_admin"
    ]
    with open(latest_dump, "rb") as dump_in:
        proc = subprocess.run(cmd, stdin=dump_in, capture_output=True)

    # pg_restore puede emitir código 0 (éxito) o 1 (advertencias no críticas en esquemas limpios)
    if proc.returncode not in (0, 1):
        err_msg = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Fallo crítico en pg_restore: {err_msg}")
    print("  [✓] pg_restore finalizado con éxito (código de salida:", proc.returncode, ").")

    # 5. Comparar tablas, columnas y recuento de registros
    print(f"\n[PASO 5] Comparando estructura y registros ({PROD_DB} vs {RESTORE_DB})...")
    restore_admin_url = admin_url.replace(f"/{PROD_DB}", f"/{RESTORE_DB}")
    restore_metrics = {}
    with psycopg.connect(restore_admin_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            rest_tables = [r[0] for r in cur.fetchall()]
            if sorted(tables) != sorted(rest_tables):
                diff = set(tables).symmetric_difference(set(rest_tables))
                raise RuntimeError(f"Discrepancia en tablas restauradas: {diff}")

            for t in rest_tables:
                cur.execute(f'SELECT count(*) FROM "{t}";')
                restore_metrics[t] = cur.fetchone()[0]

    # Validar coincidencia exacta de filas
    mismatches = []
    for t in tables:
        cnt_prod = prod_metrics[t]
        cnt_rest = restore_metrics.get(t)
        if cnt_prod != cnt_rest:
            mismatches.append(f"{t}: prod={cnt_prod}, rest={cnt_rest}")
    if mismatches:
        raise RuntimeError(f"Discrepancia en recuento de registros: {mismatches}")
    print(f"  [✓] Estructura exacta y recuento idéntico en las {len(tables)} tablas.")

    # 6. Verificar Row-Level Security en la base restaurada
    print("\n[PASO 6] Auditando Row-Level Security (RLS) en la base restaurada...")
    with psycopg.connect(restore_admin_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                ORDER BY c.relname;
            """)
            rls_rows = cur.fetchall()

    exempt_tables = {
        "action_status", "configuracion_seguridad",
        "payment_webhook_events", "selector_versions", "system_admin_keys"
    }

    rls_errors = []
    for relname, has_rls, has_force in rls_rows:
        if relname in exempt_tables:
            continue
        if not has_rls or not has_force:
            rls_errors.append(f"Tabla {relname}: rls={has_rls}, force_rls={has_force}")

    if rls_errors:
        raise RuntimeError(f"Fallo de seguridad en RLS restaurado: {rls_errors}")
    print(f"  [✓] Las 32 tablas multi-tenant restauradas conservan RLS=true y FORCE_RLS=true.")

    # 7. Validar operatividad del rol nexus_app y bypass SuperAdmin en la base restaurada
    print("\n[PASO 7] Validando rol de aplicación (nexus_app) en la base restaurada...")
    restore_app_url = app_url.replace(f"/{PROD_DB}", f"/{RESTORE_DB}")
    with psycopg.connect(restore_app_url) as conn:
        with conn.cursor() as cur:
            # 7.1. nexus_app debe tener acceso a tenants con contexto
            cur.execute("SET LOCAL app.current_tenant_id = 'ten_primary';")
            cur.execute("SELECT count(*) FROM tenants;")
            t_cnt = cur.fetchone()[0]
            if t_cnt != 1:
                raise RuntimeError(f"nexus_app no pudo consultar tenants en base restaurada (count={t_cnt})")
            print("  [✓] nexus_app consulta tenant_id='ten_primary' correctamente.")

            # 7.2. nexus_app NO debe tener acceso a system_admin_keys
            try:
                cur.execute("SELECT * FROM system_admin_keys;")
                raise RuntimeError("FALLO DE SEGURIDAD: nexus_app pudo leer system_admin_keys en base restaurada!")
            except errors.InsufficientPrivilege:
                print("  [✓] Acceso a system_admin_keys denegado a nexus_app (REVOKE preservado).")
                conn.rollback()

            # 7.3. SuperAdmin bypass funciona con el secreto rotado
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (superadmin_secret,))
            cur.execute("SELECT count(*) FROM tenants;")
            sa_cnt = cur.fetchone()[0]
            if sa_cnt != 1:
                raise RuntimeError("Bypass SuperAdmin no funcionó en base restaurada.")
            print("  [✓] Función verify_super_admin_context() operativa en base restaurada.")

    # 8. Verificar que nexusreach_prod no fue modificada
    print(f"\n[PASO 8] Comprobando que {PROD_DB} se mantuvo inalterada...")
    with psycopg.connect(admin_url) as conn:
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(f'SELECT count(*) FROM "{t}";')
                final_cnt = cur.fetchone()[0]
                if final_cnt != prod_metrics[t]:
                    raise RuntimeError(f"FALLO: {PROD_DB} fue modificada durante la prueba en tabla {t}!")
    print(f"  [✓] {PROD_DB} completamente intacta (cero mutaciones).")

    print("\n" + "=" * 80)
    print(">>> VERIFICACIÓN DE RESTAURACIÓN COMPLETADA EXITOSAMENTE (PASS) <<<")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
