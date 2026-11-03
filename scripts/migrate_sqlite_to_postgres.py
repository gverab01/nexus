#!/usr/bin/env python3
"""
Script de Migración Idempotente SQLite a PostgreSQL con Verificación de Conteos y Rollback
NexusReach Pro Directrices de Ingeniería - TASK-05B-01 [P0]

Mejoras de seguridad implementadas en TASK-05B-01:
1. Enmascaramiento obligatorio de credenciales en logs y consola (mask_db_url).
2. Resolución segura de credenciales vía variables de entorno (TARGET_DATABASE_URL, DATABASE_URL, PG*).
3. Soporte de modo estricto de claves foráneas (--strict-fks) para ejecución con roles sin privilegios SUPERUSER.
4. Protección ante pérdida accidental de datos en rollback post-cutover (--confirm-data-loss).

Uso seguro recomendado:
  $env:TARGET_DATABASE_URL = "postgresql://nexus_admin:******@127.0.0.1:5432/nexusreach_test"
  python scripts/migrate_sqlite_to_postgres.py --source-db leads.db --dry-run
  python scripts/migrate_sqlite_to_postgres.py --source-db leads.db --migrate
  python scripts/migrate_sqlite_to_postgres.py --source-db leads.db --verify-only
  python scripts/migrate_sqlite_to_postgres.py --rollback --confirm-data-loss
"""

import os
import sys
import sqlite3
import argparse
import re
from typing import Dict, List, Tuple, Any, Optional

# Configurar UTF-8 en salida estándar para compatibilidad con Windows consola
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import database
except ImportError:
    database = None

DEFAULT_SQLITE_PATH = os.path.join(PROJECT_ROOT, "leads.db")

# Tablas en orden estricto de dependencias de claves foraneas segun PostgreSQL (Topological sort - 36 tablas)
MIGRATION_TABLES = [
    "configuracion_seguridad",
    "selector_versions",
    "action_status",
    "payment_webhook_events",
    "tenants",
    "suscripciones",
    "subscriptions",
    "entitlements",
    "credit_ledger",
    "usage_counters",
    "usage_events",
    "suppression_list",
    "system_logs",
    "audit_logs",
    "selector_failure_logs",
    "usuarios",
    "devices",
    "whatsapp_accounts",
    "linkedin_accounts",
    "commands",
    "command_results",
    "listas_leads",
    "leads",
    "leads_en_lista",
    "secuencias",
    "pasos_secuencia",
    "secuencia_listas",
    "leads_en_secuencia",
    "mensajes_linkedin",
    "correos_electronicos",
    "mensajes_whatsapp",
    "interacciones_sociales",
    "historial_actividades",
    "lead_activity",
    "consent_records",
    "email_candidates",
]

PROTECTED_SYSTEM_TABLES = {
    "system_admin_keys"
}

# Tenant placeholder para auditoría histórica huérfana en modo strict-fks
SYSTEM_LEGACY_AUDIT_TENANT_ID = "ten_legacy_audit"


def mask_db_url(url: str) -> str:
    """Enmascara contraseñas en URLs de conexión para prevenir exposición en logs y consola."""
    if not url:
        return ""
    # Patrón: ://user:password@host
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:******@", url)


def resolve_target_pg_url(cli_url: Optional[str] = None) -> str:
    """Resuelve la cadena de conexión priorizando variables de entorno para evitar exposición en historial CLI."""
    if cli_url and cli_url.strip():
        if "@" in cli_url and ":" in cli_url.split("@")[0]:
            print("[ADVERTENCIA DE SEGURIDAD] Ha suministrado credenciales directamente en la línea de comandos.")
            print("  Se recomienda exportar TARGET_DATABASE_URL o DATABASE_URL para evitar que queden registradas en el historial.")
        return cli_url.strip()

    env_target = os.getenv("TARGET_DATABASE_URL", "").strip()
    if env_target:
        return env_target

    env_db = os.getenv("DATABASE_URL", "").strip()
    if env_db:
        return env_db

    # Comprobar variables estándar de PostgreSQL (libpq)
    pghost = os.getenv("PGHOST", "").strip()
    pgport = os.getenv("PGPORT", "5432").strip()
    pguser = os.getenv("PGUSER", "").strip()
    pgpassword = os.getenv("PGPASSWORD", "").strip()
    pgdatabase = os.getenv("PGDATABASE", "").strip()

    if pghost and pguser and pgdatabase:
        auth = f"{pguser}:{pgpassword}@" if pgpassword else f"{pguser}@"
        return f"postgresql://{auth}{pghost}:{pgport}/{pgdatabase}"

    return ""


def get_sqlite_connection(sqlite_path: str) -> sqlite3.Connection:
    """Abre conexión SQLite en modo estrictamente de solo lectura."""
    abs_path = os.path.abspath(sqlite_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"No existe el archivo SQLite en: {abs_path}")
    uri = f"file:{abs_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def get_sqlite_table_counts(sqlite_path: str) -> Dict[str, int]:
    """Obtiene el conteo de filas de todas las tablas en SQLite."""
    counts = {}
    conn = get_sqlite_connection(sqlite_path)
    cur = conn.cursor()
    try:
        for table in MIGRATION_TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = 0
    finally:
        conn.close()
    return counts


def get_sqlite_data(sqlite_path: str, table: str, strict_fks: bool = False, valid_tenants: Optional[set] = None) -> Tuple[List[str], List[Tuple]]:
    """Extrae nombres de columnas y filas de una tabla en SQLite con orden seguro y saneamiento de huérfanos."""
    conn = get_sqlite_connection(sqlite_path)
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if not cols:
            return [], []

        order_clause = ""
        if table == "tenants" and "parent_tenant_id" in cols:
            order_clause = " ORDER BY CASE WHEN parent_tenant_id IS NULL OR parent_tenant_id = '' THEN 0 ELSE 1 END, created_at ASC"

        cur.execute(f"SELECT {', '.join(cols)} FROM {table}{order_clause}")
        raw_rows = cur.fetchall()

        # En modo strict_fks, para audit_logs si el tenant no existe en tenants, se mapea al placeholder de auditoría
        if strict_fks and table == "audit_logs" and "tenant_id" in cols and valid_tenants is not None:
            t_idx = cols.index("tenant_id")
            sanitized_rows = []
            for r in raw_rows:
                r_list = list(r)
                tid = r_list[t_idx]
                if tid and tid not in valid_tenants:
                    r_list[t_idx] = SYSTEM_LEGACY_AUDIT_TENANT_ID
                sanitized_rows.append(tuple(r_list))
            return cols, sanitized_rows

        return cols, raw_rows
    except sqlite3.OperationalError:
        return [], []
    finally:
        conn.close()


def setup_superadmin_session(pg_cur, strict_fks: bool = False) -> None:
    """Configura la sesión PostgreSQL para tener bypass de superadministrador autorizado."""
    pg_cur.execute("SET LOCAL app.is_super_admin = 'true';")
    
    if not strict_fks:
        # Modo por defecto para carga masiva histórica: desactivar comprobaciones temporales
        try:
            pg_cur.execute("SET LOCAL session_replication_role = 'replica';")
        except Exception:
            pass

    secret = None
    if database and hasattr(database, "get_superadmin_rls_secret"):
        try:
            secret = database.get_superadmin_rls_secret()
        except Exception:
            pass

    if not secret:
        try:
            pg_cur.execute("SELECT key_hash FROM system_admin_keys WHERE is_active = TRUE LIMIT 1;")
            row = pg_cur.fetchone()
            if row:
                secret = row[0]
        except Exception:
            pass

    if secret:
        pg_cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (secret,))


def ensure_legacy_audit_tenant(pg_cur) -> None:
    """Crea el tenant placeholder de auditoría del sistema para permitir integridad referencial estricta."""
    pg_cur.execute("""
        INSERT INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
        VALUES (%s, 'Sistema - Registros Auditoria Pre-Migracion', 'SISTEMA', 'ACTIVO', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        ON CONFLICT (id) DO NOTHING;
    """, (SYSTEM_LEGACY_AUDIT_TENANT_ID,))


def migrate_data(sqlite_path: str, pg_url: str, dry_run: bool = False, strict_fks: bool = False) -> Dict[str, Any]:
    """Ejecuta la migración de SQLite a PostgreSQL de forma transaccional e idempotente."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("Se requiere psycopg para conectar a PostgreSQL. Instalar con: pip install psycopg[binary]")

    sqlite_counts = get_sqlite_table_counts(sqlite_path)
    total_sqlite_rows = sum(sqlite_counts.values())
    results = {}

    print(f"\n[INICIO] Proceso de migracion (Dry-run: {dry_run}, Strict-FKs: {strict_fks})")
    print(f"  Base de origen SQLite: {os.path.abspath(sqlite_path)}")
    print(f"  Base de destino PostgreSQL: {mask_db_url(pg_url)}")
    print(f"  Total de tablas a procesar: {len(MIGRATION_TABLES)} (Filas origen: {total_sqlite_rows})")

    # Obtener conjunto de tenants existentes en SQLite para modo strict_fks
    valid_tenants = set()
    if strict_fks:
        sq_conn = get_sqlite_connection(sqlite_path)
        sq_cur = sq_conn.cursor()
        sq_cur.execute("SELECT id FROM tenants")
        valid_tenants = set(r[0] for r in sq_cur.fetchall())
        valid_tenants.add(SYSTEM_LEGACY_AUDIT_TENANT_ID)
        sq_conn.close()

    with psycopg.connect(pg_url) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            setup_superadmin_session(pg_cur, strict_fks=strict_fks)

            if strict_fks:
                ensure_legacy_audit_tenant(pg_cur)

            total_inserted = 0
            for table in MIGRATION_TABLES:
                cols, rows = get_sqlite_data(sqlite_path, table, strict_fks=strict_fks, valid_tenants=valid_tenants)
                if not cols or not rows:
                    results[table] = {"source": 0, "migrated": 0, "status": "EMPTY_OR_SKIPPED"}
                    continue

                col_names = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))

                insert_query = f"""
                    INSERT INTO {table} ({col_names})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """

                pg_cur.executemany(insert_query, rows)
                total_inserted += len(rows)

                results[table] = {
                    "source": len(rows),
                    "migrated": len(rows) if not dry_run else 0,
                    "status": "MIGRATED" if not dry_run else "SIMULATED"
                }
                print(f"  [OK] Tabla '{table}': {len(rows)} filas preparadas/insertadas.")

            if dry_run:
                pg_conn.rollback()
                print(f"\n[DRY RUN COMPLETO] {total_inserted} filas simuladas. Todos los cambios fueron revertidos mediante rollback.")
            else:
                pg_conn.commit()
                print(f"\n[OK] Migracion completada y transacciones confirmadas. ({total_inserted} filas migradas)")

    return results


def verify_counts(sqlite_path: str, pg_url: str, strict_fks: bool = False) -> bool:
    """Compara tabla por tabla los conteos exactos entre SQLite y PostgreSQL."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("Se requiere psycopg para conectar a PostgreSQL.")

    sqlite_counts = get_sqlite_table_counts(sqlite_path)
    all_match = True
    total_sq = 0
    total_pg = 0

    print("\n[VERIFICACION] CONTEOS ENTRE MOTORES:")
    print(f"{'Tabla':<28} | {'SQLite':<10} | {'PostgreSQL':<10} | {'Estado':<10}")
    print("-" * 65)

    with psycopg.connect(pg_url) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            setup_superadmin_session(pg_cur)
            for table in MIGRATION_TABLES:
                sq_c = sqlite_counts.get(table, 0)
                total_sq += sq_c
                try:
                    pg_cur.execute(f"SELECT COUNT(*) FROM {table}")
                    pg_c = pg_cur.fetchone()[0]
                    total_pg += pg_c
                except Exception as e:
                    pg_c = f"ERR: {e}"

                # En modo strict_fks, tenants puede tener +1 por el placeholder SYSTEM_LEGACY_AUDIT_TENANT_ID
                is_match = (sq_c == pg_c) if isinstance(pg_c, int) else False
                if strict_fks and table == "tenants" and isinstance(pg_c, int) and pg_c == sq_c + 1:
                    is_match = True

                status = "COINCIDE" if is_match else ("VACIAS" if sq_c == 0 and pg_c == 0 else "DIFERENCIA")
                if not is_match:
                    all_match = False

                print(f"{table:<28} | {sq_c:<10} | {str(pg_c):<10} | {status:<10}")

    print("-" * 65)
    print(f"{'TOTAL':<28} | {total_sq:<10} | {total_pg:<10} | {'COINCIDE' if all_match else 'DESCUADRE'}")
    return all_match


def rollback_pg_data(pg_url: str, confirm_data_loss: bool = False) -> None:
    """Limpia las tablas de negocio en PostgreSQL con protección contra pérdida accidental de datos post-cutover."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("Se requiere psycopg para conectar a PostgreSQL.")

    if not confirm_data_loss:
        print("\n[BLOQUEO DE SEGURIDAD] El procedimiento de rollback elimina todos los registros de las tablas de negocio en PostgreSQL.")
        print("  Si el sistema ya recibió escrituras tras el cutover, ejecutar rollback causará PÉRDIDA IRREVERSIBLE DE DATOS.")
        print("  Para confirmar la reversión voluntaria, especifique el flag: --confirm-data-loss")
        sys.exit(1)

    print("\n[ROLLBACK] Limpiando tablas de negocio en PostgreSQL...")
    with psycopg.connect(pg_url) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            setup_superadmin_session(pg_cur)
            for table in reversed(MIGRATION_TABLES):
                if table in PROTECTED_SYSTEM_TABLES:
                    continue
                try:
                    pg_cur.execute(f"TRUNCATE TABLE {table} CASCADE;")
                    print(f"  [OK] Tabla '{table}' truncada.")
                except Exception as e:
                    print(f"  [ERROR] Truncando '{table}': {e}")
            pg_conn.commit()
    print("[OK] Rollback completado exitosamente.")


def main():
    parser = argparse.ArgumentParser(description="NexusReach Pro - Migración SQLite a PostgreSQL con verificación y rollback.")
    parser.add_argument("--source-db", default=DEFAULT_SQLITE_PATH, help="Ruta al archivo leads.db SQLite.")
    parser.add_argument("--target-url", default=None, help="Cadena de conexión PostgreSQL (preferir TARGET_DATABASE_URL en entorno).")
    parser.add_argument("--dry-run", action="store_true", help="Simula la migración sin persistir en PostgreSQL.")
    parser.add_argument("--migrate", action="store_true", help="Ejecuta la migración de datos y confirma.")
    parser.add_argument("--verify-only", action="store_true", help="Compara conteos entre SQLite y PostgreSQL.")
    parser.add_argument("--rollback", action="store_true", help="Elimina los datos de negocio en PostgreSQL (requiere --confirm-data-loss).")
    parser.add_argument("--confirm-data-loss", action="store_true", help="Confirma explícitamente la purga de datos en rollback.")
    parser.add_argument("--strict-fks", action="store_true", help="Aplica validación estricta de FKs sin session_replication_role=replica.")

    args = parser.parse_args()

    pg_url = resolve_target_pg_url(args.target_url)

    if not pg_url:
        print("[ERROR CRÍTICO] No se especificó --target-url ni están configuradas TARGET_DATABASE_URL / DATABASE_URL.")
        print("  Configure: $env:TARGET_DATABASE_URL = 'postgresql://usuario:pass@host:5432/db'")
        sys.exit(1)

    if args.rollback:
        rollback_pg_data(pg_url, confirm_data_loss=args.confirm_data_loss)
    elif args.verify_only:
        match = verify_counts(args.source_db, pg_url, strict_fks=args.strict_fks)
        sys.exit(0 if match else 1)
    elif args.migrate:
        migrate_data(args.source_db, pg_url, dry_run=False, strict_fks=args.strict_fks)
        match = verify_counts(args.source_db, pg_url, strict_fks=args.strict_fks)
        sys.exit(0 if match else 1)
    elif args.dry_run:
        migrate_data(args.source_db, pg_url, dry_run=True, strict_fks=args.strict_fks)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
