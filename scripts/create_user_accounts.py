#!/usr/bin/env python3
"""
NexusReach Pro - Provisioning de Cuentas de Acceso (Administrador y Operador)
Aprovisiona en PostgreSQL (nexusreach_prod) las cuentas requeridas por el usuario:
1. Administrador (COMPANY_ADMIN): admin@nexusreach.com
2. Operador (COMPANY_MEMBER): operador@nexusreach.com
"""

import os
import sys
import secrets
from datetime import datetime, timezone
import psycopg
from dotenv import load_dotenv

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

load_dotenv()
PG_ADMIN_URL = os.getenv("POSTGRES_ADMIN_URL")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# Credenciales solicitadas
ADMIN_EMAIL = "admin@nexusreach.com"
ADMIN_PASS = "AdminNexus2026!"
ADMIN_NAME = "Administrador NexusReach"
ADMIN_ROLE = "COMPANY_ADMIN"

OPERADOR_EMAIL = "operador@nexusreach.com"
OPERADOR_PASS = "OperadorNexus2026!"
OPERADOR_NAME = "Operador Comercial NexusReach"
OPERADOR_ROLE = "COMPANY_MEMBER"

TENANT_ID = "ten_primary"


def provision_user(cur, email, password, nombre, rol, user_id=None):
    now_iso = datetime.now(timezone.utc).isoformat()
    pwhash, salt = auth_service.hash_password(password)

    # Comprobar si ya existe
    cur.execute("SELECT id FROM usuarios WHERE email = %s;", (email,))
    row = cur.fetchone()

    if row:
        uid = row[0]
        cur.execute(
            """
            UPDATE usuarios
            SET nombre = %s,
                password_hash = %s,
                salt = %s,
                rol = %s,
                tenant_id = %s,
                puesto_activo = 1,
                estado = 'ACTIVO',
                suscripcion_estado = 'ACTIVA',
                suscripcion_plan = 'ENTERPRISE',
                suscripcion_expira = '2027-12-31',
                updated_at = %s
            WHERE id = %s;
            """,
            (nombre, pwhash, salt, rol, TENANT_ID, now_iso, uid)
        )
        print(f"[✓] Usuario actualizado: {email} (ID: {uid}, Rol: {rol})")
        return uid
    else:
        uid = user_id or f"usr_{secrets.token_hex(8)}"
        cur.execute(
            """
            INSERT INTO usuarios (
                id, tenant_id, email, nombre, password_hash, salt, rol,
                puesto_activo, estado, suscripcion_estado, suscripcion_plan,
                suscripcion_expira, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 1, 'ACTIVO', 'ACTIVA', 'ENTERPRISE', '2027-12-31', %s, %s
            );
            """,
            (uid, TENANT_ID, email, nombre, pwhash, salt, rol, now_iso, now_iso)
        )
        print(f"[✓] Usuario creado: {email} (ID: {uid}, Rol: {rol})")
        return uid


def update_env_admin_pass(new_pass):
    """Actualiza INITIAL_ADMIN_PASSWORD en .env para sincronía."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            for l in lines:
                if l.startswith("INITIAL_ADMIN_PASSWORD="):
                    f.write(f"INITIAL_ADMIN_PASSWORD={new_pass}\n")
                else:
                    f.write(l)


def main():
    print("=" * 80)
    print("APROVISIONAMIENTO DE CUENTAS DE USUARIO EN POSTGRESQL (nexusreach_prod)")
    print("=" * 80)

    with psycopg.connect(PG_ADMIN_URL) as conn:
        with conn.cursor() as cur:
            # Bypass RLS a nivel de sesión administrativa para asegurar visibilidad total
            superadmin_secret = os.getenv("SUPERADMIN_RLS_SECRET")
            cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
            cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (superadmin_secret,))

            # 1. Administrador
            admin_id = provision_user(cur, ADMIN_EMAIL, ADMIN_PASS, ADMIN_NAME, ADMIN_ROLE, "usr_c2accdbaafd0fbf4")

            # 2. Operador
            op_id = provision_user(cur, OPERADOR_EMAIL, OPERADOR_PASS, OPERADOR_NAME, OPERADOR_ROLE)

        conn.commit()

    update_env_admin_pass(ADMIN_PASS)
    print("[✓] .env actualizado con las credenciales de administración.")

    # Validar autenticación de ambas cuentas
    print("\n--- Validando login con auth_service ---")
    val_adm = auth_service.authenticate_user(ADMIN_EMAIL, ADMIN_PASS)
    if val_adm.get("exito"):
        print(f"[✓] Login Administrador exitoso: {val_adm['usuario']['email']} ({val_adm['usuario']['rol']})")
    else:
        raise RuntimeError("Fallo autenticación admin: " + str(val_adm))

    val_op = auth_service.authenticate_user(OPERADOR_EMAIL, OPERADOR_PASS)
    if val_op.get("exito"):
        print(f"[✓] Login Operador exitoso: {val_op['usuario']['email']} ({val_op['usuario']['rol']})")
    else:
        raise RuntimeError("Fallo autenticación operador: " + str(val_op))

    print("\n" + "=" * 80)
    print("CUENTAS CREADAS Y VERIFICADAS CON ÉXITO")
    print("=" * 80)


if __name__ == "__main__":
    main()
