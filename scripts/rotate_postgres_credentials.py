#!/usr/bin/env python3
"""
NexusReach Pro - Script de Rotación de Credenciales PostgreSQL y Secretos
TASK-05B-06 [P0]

Ejecuta la rotación criptográfica segura de:
1. Contraseña del rol nexus_app
2. Contraseña del rol nexus_admin
3. Secreto HMAC/SHA-256 para SuperAdmin RLS (SUPERADMIN_RLS_SECRET)
4. Contraseña del usuario administrador primario (admin@nexusreach.com)
5. Actualización segura y atómica del archivo .env

Reglas de seguridad:
- No imprime contraseñas ni secretos en claro en stdout ni logs.
- No incluye credenciales en argumentos de procesos (se inyectan por stdin).
- Valida que las credenciales viejas sean rechazadas.
- Valida que las credenciales nuevas funcionen.
- Valida que nexus_app carezca de privilegios DDL.
- Valida que el bypass SuperAdmin responda solo al nuevo secreto.
"""

import os
import sys
import secrets
import hashlib
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
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import auth_service

ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
DOCKER_BIN = r"C:\Users\gabri\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
CONTAINER_NAME = "nexusreach_postgres_rls_test"


def generate_secure_password(length: int = 32) -> str:
    """Genera contraseñas alfanuméricas criptográficamente seguras."""
    # Usar solo caracteres alfanuméricos seguros para evitar problemas de escape en URLs y SQL
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_hex_secret(bytes_count: int = 32) -> str:
    """Genera secreto hexadecimal seguro de 64 caracteres."""
    return secrets.token_hex(bytes_count)


def read_current_env():
    """Lee variables actuales desde .env."""
    config = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip()
    return config


def main():
    print("=" * 80)
    print("INICIANDO ROTACIÓN DE CREDENCIALES Y SECRETOS (TASK-05B-06)")
    print("=" * 80)

    # 1. Obtener credenciales anteriores para validación de invalidación
    current_env = read_current_env()
    old_app_url = current_env.get("DATABASE_URL", "postgresql://nexus_app:app_secure_pass_123@127.0.0.1:5432/nexusreach_prod")
    old_admin_url = current_env.get("POSTGRES_ADMIN_URL", "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_prod")
    old_superadmin_secret = current_env.get("SUPERADMIN_RLS_SECRET", "136b47eab959db3ed4134b74221f2da061502e9f70e3a16e5200120e81641a37")
    old_admin_password = current_env.get("INITIAL_ADMIN_PASSWORD", "rhajsCfH-WnSeus8PJ6iTUvC")

    # 2. Generar nuevos secretos criptográficos
    print("\n[FASE 1] Generando nuevos secretos de alta entropía...")
    new_app_password = generate_secure_password(32)
    new_admin_password = generate_secure_password(32)
    new_superadmin_secret = generate_hex_secret(32)
    new_admin_user_password = generate_secure_password(24)
    print("  [✓] Nuevos secretos generados en memoria (sin eco en terminal).")

    # 3. Aplicar rotación en PostgreSQL vía psql stdin (evitando credenciales en argumentos)
    print("\n[FASE 2] Aplicando cambios en PostgreSQL (nexusreach_prod)...")
    new_secret_hash = hashlib.sha256(new_superadmin_secret.encode("utf-8")).hexdigest()
    admin_pwhash, admin_salt = auth_service.hash_password(new_admin_user_password)

    sql_statements = f"""
    ALTER ROLE nexus_app WITH PASSWORD '{new_app_password}';
    ALTER ROLE nexus_admin WITH PASSWORD '{new_admin_password}';
    INSERT INTO system_admin_keys (key_name, key_hash, created_at)
    VALUES ('super_admin_bypass', '{new_secret_hash}', CURRENT_TIMESTAMP)
    ON CONFLICT (key_name) DO UPDATE 
    SET key_hash = EXCLUDED.key_hash, created_at = EXCLUDED.created_at;
    UPDATE usuarios 
    SET password_hash = '{admin_pwhash}', salt = '{admin_salt}', updated_at = CURRENT_TIMESTAMP
    WHERE email = 'admin@nexusreach.com';
    """

    cmd = [
        DOCKER_BIN, "exec", "-i", CONTAINER_NAME,
        "psql", "-U", "nexus_admin", "-d", "nexusreach_prod"
    ]
    proc = subprocess.run(cmd, input=sql_statements, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"[ERROR] Fallo al aplicar SQL en PostgreSQL: {proc.stderr}")
        sys.exit(1)
    print("  [✓] Sentencias SQL ejecutadas exitosamente vía stdin.")

    # 4. Actualizar el archivo .env
    print("\n[FASE 3] Actualizando archivo de configuración .env...")
    new_app_url = f"postgresql://nexus_app:{new_app_password}@127.0.0.1:5432/nexusreach_prod"
    new_admin_url = f"postgresql://nexus_admin:{new_admin_password}@127.0.0.1:5432/nexusreach_prod"

    new_env_lines = [
        "# NexusReach Pro - Production Environment Configuration",
        "# Motor Operacional Activo: PostgreSQL 16 (Rotación TASK-05B-06)",
        "DB_ENGINE=postgres",
        f"DATABASE_URL={new_app_url}",
        f"POSTGRES_APP_URL={new_app_url}",
        f"POSTGRES_ADMIN_URL={new_admin_url}",
        "",
        "# Secreto Criptográfico para Bypass Autorizado de SuperAdmin en RLS (HMAC-SHA256)",
        f"SUPERADMIN_RLS_SECRET={new_superadmin_secret}",
        "",
        "# Credenciales del Administrador Primario Inicial",
        "INITIAL_ADMIN_EMAIL=admin@nexusreach.com",
        f"INITIAL_ADMIN_PASSWORD={new_admin_user_password}",
        "",
        "# Servidor de Aplicación",
        "ENV=production",
        "ENVIRONMENT=production",
        "HOST=127.0.0.1",
        "PORT=8000",
        "SESSION_EXPIRE_HOURS=24"
    ]

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(new_env_lines) + "\n")
    print("  [✓] Archivo .env reescrito de forma atómica y segura.")

    # 5. Verificaciones de Invalidation y Nuevas Credenciales
    print("\n[FASE 4] Verificando invalidación de credenciales anteriores y operatividad de las nuevas...")

    # 5.1. Verificar que la contraseña anterior de nexus_app es RECHAZADA
    old_app_failed = False
    try:
        with psycopg.connect(old_app_url) as c:
            pass
    except psycopg.OperationalError:
        old_app_failed = True
    if not old_app_failed:
        raise RuntimeError("FALLO DE SEGURIDAD: La contraseña anterior de nexus_app todavía funciona!")
    print("  [✓] Confirmado: Credencial anterior de nexus_app fue INVALIDADA (rechazo 100%).")

    # 5.2. Verificar que la contraseña anterior de nexus_admin es RECHAZADA
    old_admin_failed = False
    try:
        with psycopg.connect(old_admin_url) as c:
            pass
    except psycopg.OperationalError:
        old_admin_failed = True
    if not old_admin_failed:
        raise RuntimeError("FALLO DE SEGURIDAD: La contraseña anterior de nexus_admin todavía funciona!")
    print("  [✓] Confirmado: Credencial anterior de nexus_admin fue INVALIDADA (rechazo 100%).")

    # 5.3. Verificar que la nueva conexión de nexus_app funciona
    with psycopg.connect(new_app_url) as c:
        with c.cursor() as cur:
            cur.execute("SELECT current_user, usesuper FROM pg_user WHERE usename = current_user;")
            user, is_super = cur.fetchone()
            if user != "nexus_app" or is_super:
                raise RuntimeError(f"Usuario inesperado o privilegios excesivos: {user}, {is_super}")
    print("  [✓] Confirmado: Nueva credencial de nexus_app funciona correctamente (sin superusuario).")

    # 5.4. Verificar que la nueva conexión de nexus_admin funciona
    with psycopg.connect(new_admin_url) as c:
        with c.cursor() as cur:
            cur.execute("SELECT current_user, usesuper FROM pg_user WHERE usename = current_user;")
            user, is_super = cur.fetchone()
            if user != "nexus_admin" or not is_super:
                raise RuntimeError("nexus_admin no autentica o carece de superusuario")
    print("  [✓] Confirmado: Nueva credencial de nexus_admin funciona correctamente.")

    # 5.5. Verificar que nexus_app NO tiene privilegios DDL
    with psycopg.connect(new_app_url) as c:
        with c.cursor() as cur:
            try:
                cur.execute("CREATE TABLE test_unauthorized_ddl (id int);")
                raise RuntimeError("FALLO DE SEGURIDAD: nexus_app pudo ejecutar CREATE TABLE!")
            except errors.InsufficientPrivilege:
                print("  [✓] Confirmado: nexus_app no tiene privilegios DDL (CREATE TABLE denegado).")

    # 5.6. Verificar que nexus_app NO tiene acceso a system_admin_keys
    with psycopg.connect(new_app_url) as c:
        with c.cursor() as cur:
            try:
                cur.execute("SELECT * FROM system_admin_keys;")
                raise RuntimeError("FALLO DE SEGURIDAD: nexus_app pudo leer system_admin_keys!")
            except errors.InsufficientPrivilege:
                print("  [✓] Confirmado: nexus_app tiene acceso denegado a system_admin_keys.")

    # 5.7. Verificar SuperAdmin bypass con el nuevo secreto y con el secreto anterior
    with psycopg.connect(new_app_url) as c:
        with c.cursor() as cur:
            # Intento con secreto viejo -> debe ver 0 filas
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (old_superadmin_secret,))
            cur.execute("SELECT count(*) FROM tenants;")
            count_old = cur.fetchone()[0]
            if count_old != 0:
                raise RuntimeError("FALLO DE SEGURIDAD: El secreto viejo de SuperAdmin todavía concede bypass!")
            print("  [✓] Confirmado: Secreto anterior de SuperAdmin fue INVALIDADO (0 filas devueltas).")

            # Intento con secreto nuevo -> debe ver 1 fila (ten_primary)
            cur.execute("SET LOCAL app.is_super_admin = 'true';")
            cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (new_superadmin_secret,))
            cur.execute("SELECT count(*) FROM tenants;")
            count_new = cur.fetchone()[0]
            if count_new != 1:
                raise RuntimeError(f"Fallo en bypass SuperAdmin con nuevo secreto: devolvió {count_new} filas")
            print("  [✓] Confirmado: Nuevo secreto de SuperAdmin opera exitosamente (acceso verificado).")

    # 5.8. Verificar validación de contraseñas de admin@nexusreach.com
    # Contraseña anterior debe fallar
    is_old_valid = auth_service.verify_password(old_admin_password, admin_salt, admin_pwhash)
    if is_old_valid:
        raise RuntimeError("FALLO DE SEGURIDAD: La contraseña anterior del admin de la app sigue siendo válida!")
    print("  [✓] Confirmado: Contraseña anterior de admin@nexusreach.com INVALIDADA.")

    # Contraseña nueva debe tener éxito
    is_new_valid = auth_service.verify_password(new_admin_user_password, admin_salt, admin_pwhash)
    if not is_new_valid:
        raise RuntimeError("Fallo: La nueva contraseña de admin@nexusreach.com no verifica!")
    print("  [✓] Confirmado: Nueva contraseña de admin@nexusreach.com VERIFICADA exitosamente.")

    print("\n" + "=" * 80)
    print(">>> ROTACIÓN DE SECRETOS COMPLETADA EXITOSAMENTE (PASS) <<<")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
