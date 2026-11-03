#!/usr/bin/env python3
"""
NexusReach Pro - Script de Inicialización Limpia de PostgreSQL (Operational Bootstrap)
TASK-05B-02A [P0]

Inicializa una base de datos PostgreSQL vacía con los datos mínimos estrictamente necesarios
para operar desde cero (un tenant inicial, un usuario administrador, esquema completo con RLS y
mecanismo SuperAdmin criptográfico), SIN importar datos operacionales históricos de SQLite.

Uso:
  # Dry-run de verificación previa
  python scripts/bootstrap_postgres_clean.py --dry-run

  # Inicialización completa con parámetros por entorno
  $env:TARGET_DATABASE_URL = "postgresql://nexus_admin:******@127.0.0.1:5432/nexusreach_test"
  $env:SUPERADMIN_RLS_SECRET = "<secreto_criptografico_64_chars>"
  $env:INITIAL_ADMIN_PASSWORD = "<password_segura>"
  python scripts/bootstrap_postgres_clean.py --bootstrap

  # Solo verificación de estado inicial
  python scripts/bootstrap_postgres_clean.py --verify-only
"""

import os
import sys
import argparse
import secrets
import hashlib
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

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
    import auth_service
except ImportError as e:
    print(f"[ERROR] Dependencias internas no encontradas: {e}")
    sys.exit(1)

SCHEMA_FILE = os.path.join(PROJECT_ROOT, "schema_postgres.sql")
ROLES_FILE = os.path.join(PROJECT_ROOT, "scripts", "init_postgres_test_roles.sql")

DEFAULT_TENANT_ID = "ten_primary"
DEFAULT_TENANT_NAME = "Organización Principal NexusReach"
DEFAULT_ADMIN_EMAIL = "admin@nexusreach.com"
DEFAULT_ADMIN_NAME = "Administrador Principal"

# Claves esenciales de configuración inicial en configuracion_seguridad
DEFAULT_SAFETY_CONFIG = {
    "kill_switch_activado": "0",
    "kill_switch_motivo": "",
    "horario_inicio": "09:00",
    "horario_fin": "18:00",
    "horario_laboral_activo": "1",
    "limite_linkedin_diario": "15",
    "limite_email_workspace_diario": "15",
    "whatsapp_cuota_diaria": "15",
    "pausas_antiban_activas": "1",
    "pausa_linkedin_min_seg": "180",
    "pausa_linkedin_max_seg": "360",
    "pausa_email_min_seg": "480",
    "pausa_email_max_seg": "900",
    "pausa_whatsapp_min_seg": "360",
    "pausa_whatsapp_max_seg": "900",
    "enriquecimiento_cascada_activo": "1",
    "zoho_sync_activo": "0"
}


def mask_db_url(url: str) -> str:
    """Enmascara contraseñas en URLs de conexión."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:******@", url)


def resolve_pg_url(cli_url: Optional[str] = None) -> str:
    """Resuelve la URL de PostgreSQL priorizando variables de entorno."""
    if cli_url and cli_url.strip():
        if "@" in cli_url and ":" in cli_url.split("@")[0]:
            print("[ADVERTENCIA DE SEGURIDAD] Ha suministrado credenciales en la línea de comandos.")
            print("  Se recomienda exportar TARGET_DATABASE_URL o DATABASE_URL para evitar registro en historial.")
        return cli_url.strip()

    for var_name in ("TARGET_DATABASE_URL", "DATABASE_URL"):
        val = os.getenv(var_name, "").strip()
        if val:
            return val

    pghost = os.getenv("PGHOST", "").strip()
    pgport = os.getenv("PGPORT", "5432").strip()
    pguser = os.getenv("PGUSER", "").strip()
    pgpassword = os.getenv("PGPASSWORD", "").strip()
    pgdatabase = os.getenv("PGDATABASE", "").strip()

    if pghost and pguser and pgdatabase:
        auth = f"{pguser}:{pgpassword}@" if pgpassword else f"{pguser}@"
        return f"postgresql://{auth}{pghost}:{pgport}/{pgdatabase}"

    return ""


def check_postgres_version(conn) -> str:
    """Verifica que la versión de PostgreSQL sea 16 o superior."""
    with conn.cursor() as cur:
        cur.execute("SHOW server_version;")
        row = cur.fetchone()
        version_str = row[0] if row else ""
        match = re.match(r"^(\d+)", version_str)
        if match:
            major = int(match.group(1))
            if major < 16:
                raise RuntimeError(f"PostgreSQL versión {version_str} no soportada. Se requiere PostgreSQL 16+.")
        return version_str


def check_database_clean_state(conn) -> Dict[str, Any]:
    """Comprueba si la base de datos está limpia o si contiene datos operacionales."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
        """)
        table_count = cur.fetchone()[0]

        operational_data = {}
        if table_count > 0:
            for check_table in ("leads", "usuarios", "audit_logs", "historial_actividades", "linkedin_accounts"):
                try:
                    cur.execute(f"SELECT count(*) FROM {check_table};")
                    cnt = cur.fetchone()[0]
                    if cnt > 0:
                        operational_data[check_table] = cnt
                except Exception:
                    conn.rollback()

        return {
            "table_count": table_count,
            "has_operational_data": bool(operational_data),
            "operational_data": operational_data
        }


def apply_schema(conn, dry_run: bool = False) -> None:
    """Aplica schema_postgres.sql si la base está vacía."""
    if not os.path.exists(SCHEMA_FILE):
        raise FileNotFoundError(f"No se encontró el archivo de esquema en: {SCHEMA_FILE}")

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print(f"  [ESQUEMA] Aplicando DDL desde {os.path.basename(SCHEMA_FILE)}...")
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    print("  [OK] Esquema completo de PostgreSQL verificado/aplicado.")


def apply_roles(conn, dry_run: bool = False) -> None:
    """Aplica y asegura la configuración de roles y privilegios mínimos."""
    if os.path.exists(ROLES_FILE):
        with open(ROLES_FILE, "r", encoding="utf-8") as f:
            roles_sql = f.read()
        print(f"  [ROLES] Aplicando configuración de roles desde {os.path.basename(ROLES_FILE)}...")
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute(roles_sql)
            conn.commit()
        print("  [OK] Roles de privilegios mínimos verificados/aplicados.")


def configure_superadmin_secret(conn, secret: Optional[str] = None, dry_run: bool = False) -> str:
    """Configura el hash criptográfico del secreto SuperAdmin en system_admin_keys."""
    effective_secret = secret.strip() if secret and secret.strip() else os.getenv("SUPERADMIN_RLS_SECRET", "").strip()
    generated = False
    if not effective_secret:
        effective_secret = secrets.token_hex(32)  # 64 caracteres hex
        generated = True

    secret_hash = hashlib.sha256(effective_secret.encode("utf-8")).hexdigest()

    print(f"  [SUPERADMIN] Configurando hash criptográfico en system_admin_keys...")
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_admin_keys (key_name, key_hash, created_at)
                VALUES ('super_admin_bypass', %s, NOW())
                ON CONFLICT (key_name) DO UPDATE SET
                    key_hash = EXCLUDED.key_hash,
                    created_at = NOW();
            """, (secret_hash,))
        conn.commit()

    if generated:
        print("  [AVISO] Se generó un nuevo token SUPERADMIN_RLS_SECRET aleatorio.")
        print(f"  --> Token generado (guardar de forma segura en gestor de secretos): {effective_secret}")
    else:
        print("  [OK] Hash de SUPERADMIN_RLS_SECRET configurado exitosamente.")

    return effective_secret


def create_initial_tenant(conn, tenant_id: str, tenant_name: str, dry_run: bool = False) -> None:
    """Crea el tenant inicial y su suscripción asociada si no existen."""
    now_iso = datetime.now().isoformat()
    exp_iso = (datetime.now() + timedelta(days=365)).isoformat()
    sub_id = f"sub_{tenant_id}"

    print(f"  [TENANT] Creando tenant inicial '{tenant_id}' ({tenant_name})...")
    if not dry_run:
        with conn.cursor() as cur:
            # Bypass RLS para la sesión administrativa
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            cur.execute("""
                INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (%s, NULL, %s, 'EMPRESA', 'ACTIVO', %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """, (tenant_id, tenant_name, now_iso, now_iso))

            cur.execute("""
                INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                VALUES (%s, %s, 'ANUAL', 'ACTIVA', 5, 0.0, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """, (sub_id, tenant_id, now_iso, exp_iso, now_iso, now_iso))
        conn.commit()
    print("  [OK] Tenant y suscripción inicial creados/verificados.")


def create_initial_admin_user(conn, tenant_id: str, email: str, name: str, password: Optional[str] = None, dry_run: bool = False) -> str:
    """Crea el usuario administrador inicial asociado al tenant."""
    effective_pass = password.strip() if password and password.strip() else os.getenv("INITIAL_ADMIN_PASSWORD", "").strip()
    generated = False
    if not effective_pass:
        effective_pass = secrets.token_urlsafe(16)
        generated = True

    pwd_hash, salt = auth_service.hash_password(effective_pass)
    now_iso = datetime.now().isoformat()
    exp_iso = (datetime.now() + timedelta(days=365)).isoformat()
    user_id = f"usr_{secrets.token_hex(8)}"

    print(f"  [USUARIO] Creando usuario administrador inicial '{email}'...")
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            cur.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'COMPANY_ADMIN', 1, 'ACTIVO', %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    nombre = EXCLUDED.nombre,
                    password_hash = EXCLUDED.password_hash,
                    salt = EXCLUDED.salt,
                    rol = EXCLUDED.rol,
                    estado = EXCLUDED.estado,
                    updated_at = EXCLUDED.updated_at;
            """, (user_id, tenant_id, email, name, pwd_hash, salt, exp_iso, now_iso, now_iso))
        conn.commit()

    if generated:
        print("  [AVISO] Se generó una contraseña inicial temporal aleatoria.")
        print(f"  --> Contraseña inicial de '{email}': {effective_pass}")
        print("  --> Cambiar inmediatamente tras el primer inicio de sesión.")
    else:
        print(f"  [OK] Usuario '{email}' configurado exitosamente.")

    return effective_pass


def seed_safety_config(conn, dry_run: bool = False) -> None:
    """Siembra las configuraciones iniciales del sistema en configuracion_seguridad."""
    now_iso = datetime.now().isoformat()
    print("  [CONFIG] Sembrando configuraciones básicas de seguridad en configuracion_seguridad...")
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            for k, v in DEFAULT_SAFETY_CONFIG.items():
                cur.execute("""
                    INSERT INTO configuracion_seguridad (clave, valor, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (clave) DO UPDATE SET updated_at = EXCLUDED.updated_at;
                """, (k, v, now_iso))
        conn.commit()
    print("  [OK] Parámetros de seguridad del sistema sembrados.")


def verify_clean_bootstrap_state(conn, expected_tenant_id: str, expected_admin_email: str) -> bool:
    """Verifica de forma exhaustiva que la base de datos cumpla los criterios del bootstrap limpio."""
    print("\n[VERIFICACIÓN] Comprobando integridad del bootstrap limpio...")
    passed = True
    with conn.cursor() as cur:
        # Bypass temporal para auditoría de verificación
        cur.execute("SET LOCAL app.is_super_admin = 'true';")

        # 1. Tenant inicial
        cur.execute("SELECT count(*) FROM tenants WHERE id = %s;", (expected_tenant_id,))
        if cur.fetchone()[0] == 1:
            print(f"  ✓ Tenant inicial '{expected_tenant_id}' presente.")
        else:
            print(f"  ✕ Falla: Tenant inicial '{expected_tenant_id}' no encontrado.")
            passed = False

        # 2. Total tenants debe ser exactamente 1
        cur.execute("SELECT count(*) FROM tenants;")
        t_count = cur.fetchone()[0]
        if t_count == 1:
            print("  ✓ Total de tenants en la base: exactamente 1.")
        else:
            print(f"  ✕ Falla: Se esperaba exactamente 1 tenant, encontrados: {t_count}.")
            passed = False

        # 3. Usuario administrador
        cur.execute("SELECT count(*) FROM usuarios WHERE email = %s;", (expected_admin_email,))
        if cur.fetchone()[0] == 1:
            print(f"  ✓ Usuario administrador '{expected_admin_email}' presente.")
        else:
            print(f"  ✕ Falla: Usuario '{expected_admin_email}' no encontrado.")
            passed = False

        # 4. Total usuarios debe ser exactamente 1
        cur.execute("SELECT count(*) FROM usuarios;")
        u_count = cur.fetchone()[0]
        if u_count == 1:
            print("  ✓ Total de usuarios en la base: exactamente 1.")
        else:
            print(f"  ✕ Falla: Se esperaba exactamente 1 usuario, encontrados: {u_count}.")
            passed = False

        # 5. system_admin_keys configurado
        cur.execute("SELECT count(*) FROM system_admin_keys WHERE key_name = 'super_admin_bypass';")
        if cur.fetchone()[0] == 1:
            print("  ✓ Mecanismo criptográfico SuperAdmin activo en system_admin_keys.")
        else:
            print("  ✕ Falla: system_admin_keys no configurado correctamente.")
            passed = False

        # 6. Cero datos operacionales históricos
        for table in ("leads", "historial_actividades", "audit_logs", "linkedin_accounts", "mensajes_linkedin"):
            cur.execute(f"SELECT count(*) FROM {table};")
            cnt = cur.fetchone()[0]
            if cnt == 0:
                print(f"  ✓ Tabla operacional '{table}': 0 filas (limpia).")
            else:
                print(f"  ✕ Falla: Tabla operacional '{table}' contiene {cnt} filas no deseadas.")
                passed = False

    return passed


def main():
    parser = argparse.ArgumentParser(description="NexusReach Pro - Inicialización Limpia de PostgreSQL (Operational Bootstrap)")
    parser.add_argument("--target-url", default=None, help="Cadena de conexión PostgreSQL (preferir TARGET_DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="Simula la inicialización sin persistir cambios")
    parser.add_argument("--bootstrap", action="store_true", help="Ejecuta la inicialización limpia completa")
    parser.add_argument("--verify-only", action="store_true", help="Audita si la base cumple con los criterios de bootstrap limpio")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID, help=f"ID del tenant inicial (def: {DEFAULT_TENANT_ID})")
    parser.add_argument("--tenant-name", default=DEFAULT_TENANT_NAME, help=f"Razón social del tenant inicial")
    parser.add_argument("--admin-email", default=DEFAULT_ADMIN_EMAIL, help=f"Email del admin inicial (def: {DEFAULT_ADMIN_EMAIL})")
    parser.add_argument("--admin-name", default=DEFAULT_ADMIN_NAME, help=f"Nombre del admin inicial")
    parser.add_argument("--admin-password", default=None, help="Contraseña del admin (preferir INITIAL_ADMIN_PASSWORD en entorno)")
    parser.add_argument("--superadmin-secret", default=None, help="Token secreto SuperAdmin (preferir SUPERADMIN_RLS_SECRET en entorno)")
    parser.add_argument("--force-init", action="store_true", help="Permite inicializar aun cuando la base contenga datos previos")

    args = parser.parse_args()

    pg_url = resolve_pg_url(args.target_url)
    if not pg_url:
        print("[ERROR CRÍTICO] No se especificó --target-url ni existe TARGET_DATABASE_URL / DATABASE_URL.")
        sys.exit(1)

    try:
        import psycopg
    except ImportError:
        print("[ERROR CRÍTICO] Se requiere psycopg para conectar a PostgreSQL. Instalar con: pip install psycopg[binary]")
        sys.exit(1)

    print("\n" + "=" * 75)
    print("NEXUSREACH PRO - INICIALIZACIÓN LIMPIA DE POSTGRESQL (BOOTSTRAP)")
    print("=" * 75)
    print(f"Destino PostgreSQL: {mask_db_url(pg_url)}")
    print(f"Modo Dry-Run: {args.dry_run}")

    with psycopg.connect(pg_url) as conn:
        version = check_postgres_version(conn)
        print(f"Versión PostgreSQL: {version}")

        state = check_database_clean_state(conn)
        print(f"Tablas existentes: {state['table_count']}")

        if state["has_operational_data"] and not args.force_init and not args.verify_only:
            print("\n[BLOQUEO DE SEGURIDAD] La base de datos contiene datos operacionales previos:")
            for t, cnt in state["operational_data"].items():
                print(f"  - {t}: {cnt} filas")
            print("  Para inicializar sobre una base con datos use el flag explícito: --force-init")
            sys.exit(1)

        if args.verify_only:
            success = verify_clean_bootstrap_state(conn, args.tenant_id, args.admin_email)
            sys.exit(0 if success else 1)

        if args.bootstrap or args.dry_run:
            print("\n--- PASO 1: APLICACIÓN DE ESQUEMA ---")
            apply_schema(conn, dry_run=args.dry_run)

            print("\n--- PASO 2: CONFIGURACIÓN DE ROLES Y PRIVILEGIOS MÍNIMOS ---")
            apply_roles(conn, dry_run=args.dry_run)

            print("\n--- PASO 3: CONFIGURACIÓN CRIPTOGRÁFICA SUPERADMIN ---")
            configure_superadmin_secret(conn, secret=args.superadmin_secret, dry_run=args.dry_run)

            print("\n--- PASO 4: CREACIÓN DE TENANT INICIAL ---")
            create_initial_tenant(conn, args.tenant_id, args.tenant_name, dry_run=args.dry_run)

            print("\n--- PASO 5: CREACIÓN DE USUARIO ADMINISTRADOR INICIAL ---")
            create_initial_admin_user(conn, args.tenant_id, args.admin_email, args.admin_name, password=args.admin_password, dry_run=args.dry_run)

            print("\n--- PASO 6: CONFIGURACIÓN DE SEGURIDAD Y PARÁMETROS DEL SISTEMA ---")
            seed_safety_config(conn, dry_run=args.dry_run)

            if not args.dry_run:
                print("\n--- PASO 7: AUDITORÍA Y VERIFICACIÓN POST-BOOTSTRAP ---")
                success = verify_clean_bootstrap_state(conn, args.tenant_id, args.admin_email)
                if success:
                    print("\n[OK] BOOTSTRAP LIMPIO DE POSTGRESQL COMPLETADO EXITOSAMENTE.")
                else:
                    print("\n[ADVERTENCIA] Algunas comprobaciones post-bootstrap no pasaron.")
                    sys.exit(1)
            else:
                print("\n[DRY RUN COMPLETO] Simulación finalizada sin persistir cambios.")
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
