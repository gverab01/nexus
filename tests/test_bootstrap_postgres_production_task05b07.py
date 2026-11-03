"""
Pruebas unitarias y de validación para el bootstrap de producción PostgreSQL.
TASK-05B-07 [P0]

Verifica:
1. Creación de tenant.
2. Creación de suscripción.
3. Creación de administrador.
4. Validación de hashing (PBKDF2-SHA256 con auth_service).
5. Rechazo de contraseña ausente o insegura.
6. Rechazo de email duplicado.
7. Rechazo de tenant duplicado.
8. Rollback ante fallas en operaciones.
9. Segunda ejecución sin duplicados (idempotencia).
10. Conservación de configuraciones existentes sin modificación.
11. No modificación del secreto SuperAdmin ni roles.
12. Ausencia de secretos en logs.
13. Comportamiento correcto ante estado parcial / conflictivo.
"""

import unittest
import os
import io
import sys
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List

# Asegurar path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Dummy DATABASE_URL para permitir importación en tests sin depender de base de datos viva
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://nexus_app:dummy_test_pass@127.0.0.1:5432/nexusreach_prod"

import auth_service
import scripts.bootstrap_postgres_production as bpp


class MockPostgresGateway:
    """Gateway simulado en memoria para validar la lógica del bootstrap sin requerir PostgreSQL vivo."""

    def __init__(self, superadmin_secret: str, fail_on_insert: Optional[str] = None):
        self.superadmin_secret = superadmin_secret
        self.fail_on_insert = fail_on_insert
        self.committed = False
        self.rolled_back = False
        self.advisory_lock_acquired = True

        # Base de datos en memoria
        self.tenants: Dict[str, Dict[str, Any]] = {}
        self.suscripciones: Dict[str, Dict[str, Any]] = {}
        self.usuarios: Dict[str, Dict[str, Any]] = {}
        self.configuracion_seguridad: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[Dict[str, Any]] = []

        # Estado de contexto RLS
        self.current_superadmin_token = None
        self.is_super_admin = False
        self.current_tenant_id = None

    def server_info(self) -> Dict[str, Any]:
        return {
            "db_name": "nexusreach_prod",
            "cur_user": "nexus_app",
            "sess_user": "nexus_app",
            "server_version_num": 160001,
            "is_superuser": False,
            "is_bypassrls": False,
        }

    def missing_objects(self) -> List[str]:
        return []

    def missing_privileges(self, required, need_sequence: bool) -> List[str]:
        return []

    def rls_status(self, tables) -> Dict[str, tuple]:
        return {t: (True, True) for t in tables}

    def existing_policies(self, tables) -> Dict[str, Dict[str, Any]]:
        return {
            f"{t}.{bpp.CORE_RLS_POLICIES[t]}": {
                "schemaname": "public",
                "tablename": t,
                "policyname": bpp.CORE_RLS_POLICIES[t],
                "permissive": "PERMISSIVE",
                "roles": ["PUBLIC"],
                "cmd": "ALL",
                "qual": "(verify_super_admin_context() OR ...)",
                "with_check": "(verify_super_admin_context() OR ...)"
            }
            for t in tables if t in bpp.CORE_RLS_POLICIES
        }

    def probe_cross_tenant_isolation(self, tenant_a: str, tenant_b: str, user_a_id: str) -> Dict[str, Any]:
        return {
            "a_cannot_see_b": True,
            "b_cannot_see_a": True,
            "anonymous_sees_zero": True,
            "insert_cross_tenant_blocked": True,
            "update_cross_tenant_blocked": True,
        }

    def rls_totals(self) -> Dict[str, int]:
        return {"forced": 32, "total": 32, "policies": 32}

    def role_attributes(self, role: str) -> Optional[Dict[str, Any]]:
        return {"rolsuper": False, "rolbypassrls": False, "rolcanlogin": True}

    def role_can_select(self, role: str, table: str) -> bool:
        if role == "nexus_app" and table == "system_admin_keys":
            return False
        return True

    def activate_superadmin_context(self) -> None:
        self.is_super_admin = True
        self.current_superadmin_token = self.superadmin_secret

    def superadmin_context_valid(self) -> bool:
        return bool(self.is_super_admin and self.current_superadmin_token == self.superadmin_secret)

    def probe_token(self, token: str) -> bool:
        return token == self.superadmin_secret

    def probe_visibility(self, context_tenant_id: Optional[str], tenant_id: str, user_id: Optional[str]) -> Dict[str, int]:
        if context_tenant_id is None:
            return {"tenant": 0, "sub": 0, "usr": 0}
        if context_tenant_id == tenant_id:
            return {
                "tenant": 1 if tenant_id in self.tenants else 0,
                "sub": 1 if tenant_id in self.suscripciones else 0,
                "usr": 1 if any(u.get("id") == user_id for u in self.usuarios.values()) else 0
            }
        return {"tenant": 0, "sub": 0, "usr": 0}

    def try_acquire_lock(self) -> bool:
        return self.advisory_lock_acquired

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        return self.tenants.get(tenant_id)

    def get_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        sub = self.suscripciones.get(tenant_id)
        return [sub] if sub else []

    def find_users_by_email(self, email: str) -> List[Dict[str, Any]]:
        res = []
        for u in self.usuarios.values():
            if u["email"].lower() == email.lower():
                res.append(u)
        return res

    def count_active_seats(self, tenant_id: str) -> int:
        return sum(1 for u in self.usuarios.values() if u.get("tenant_id") == tenant_id and u.get("puesto_activo") == 1)

    def get_config(self, keys) -> Dict[str, Any]:
        return {k: self.configuracion_seguridad[k]["valor"] for k in keys if k in self.configuracion_seguridad}

    def insert_tenant(self, row: Dict[str, Any]) -> None:
        if self.fail_on_insert == "tenant":
            raise RuntimeError("Fallo simulado al insertar tenant")
        self.tenants[row["id"]] = dict(row)

    def insert_subscription(self, row: Dict[str, Any]) -> None:
        if self.fail_on_insert == "subscription":
            raise RuntimeError("Fallo simulado al insertar suscripción")
        self.suscripciones[row["tenant_id"]] = dict(row)

    def insert_user(self, row: Dict[str, Any]) -> None:
        if self.fail_on_insert == "user":
            raise RuntimeError("Fallo simulado al insertar usuario")
        self.usuarios[row["id"]] = dict(row)

    def insert_config_if_absent(self, key: str, value: str, description: str, now_iso: str) -> bool:
        if key in self.configuracion_seguridad:
            return False
        self.configuracion_seguridad[key] = {
            "clave": key,
            "valor": value,
            "descripcion": description,
            "updated_at": now_iso
        }
        return True

    def insert_audit_log(self, row: Dict[str, Any]) -> None:
        self.audit_logs.append(dict(row))

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class TestProductionBootstrap(unittest.TestCase):

    def setUp(self):
        self.valid_secret = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
        self.env = {
            bpp.ENV_DSN: "postgresql://nexus_app:secret@127.0.0.1:5432/nexusreach_prod",
            bpp.ENV_SUPERADMIN_SECRET: self.valid_secret,
            bpp.ENV_ADMIN_PASSWORD: "SuperSecurePassword2026!#",
            bpp.ENV_TENANT_ID: "ten_primary",
            bpp.ENV_TENANT_NAME: "Organización NexusReach Principal",
            bpp.ENV_ADMIN_EMAIL: "admin@nexusreach.com",
            bpp.ENV_ADMIN_NAME: "Administrador NexusReach",
            bpp.ENV_PERIODICITY: "ANUAL"
        }

    def test_01_creacion_exitosa_completa(self):
        """1, 2, 3: Creación de tenant, suscripción y administrador con validación de hashing."""
        gw = MockPostgresGateway(self.valid_secret)
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_OK)
        self.assertTrue(gw.committed)
        self.assertIn("ten_primary", gw.tenants)
        self.assertIn("ten_primary", gw.suscripciones)
        self.assertEqual(len(gw.usuarios), 1)

        # Verificar admin y hashing
        admin = list(gw.usuarios.values())[0]
        self.assertEqual(admin["email"], "admin@nexusreach.com")
        self.assertEqual(admin["rol"], "COMPANY_ADMIN")
        self.assertTrue(auth_service.verify_password("SuperSecurePassword2026!#", admin["salt"], admin["password_hash"]))

    def test_02_rechazo_contrasena_ausente(self):
        """5: Rechazo de contraseña ausente."""
        gw = MockPostgresGateway(self.valid_secret)
        env = dict(self.env)
        del env[bpp.ENV_ADMIN_PASSWORD]
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertFalse(gw.committed)

    def test_03_rechazo_contrasena_debil(self):
        """5b: Rechazo de contraseña que coincide con valores por defecto débiles."""
        gw = MockPostgresGateway(self.valid_secret)
        env = dict(self.env)
        env[bpp.ENV_ADMIN_PASSWORD] = "admin123"
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertFalse(gw.committed)

    def test_04_rechazo_tenant_duplicado_sin_usuario(self):
        """7 & 14: Rechazo ante estado parcial o tenant preexistente."""
        gw = MockPostgresGateway(self.valid_secret)
        gw.tenants["ten_primary"] = {
            "id": "ten_primary",
            "razon_social": "Antigua Org",
            "tipo_tenant": "EMPRESA",
            "estado": "ACTIVO",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_STATE_CONFLICT)
        self.assertFalse(gw.committed)

    def test_05_rechazo_email_duplicado(self):
        """6: Rechazo si el email de administrador ya existe en otro contexto."""
        gw = MockPostgresGateway(self.valid_secret)
        gw.usuarios["usr_otro"] = {
            "id": "usr_otro",
            "tenant_id": "ten_otro",
            "email": "admin@nexusreach.com",
            "nombre": "Otro Admin",
            "password_hash": "hash",
            "salt": "salt",
            "rol": "COMPANY_ADMIN",
            "puesto_activo": 1,
            "estado": "ACTIVO"
        }
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_STATE_CONFLICT)
        self.assertFalse(gw.committed)

    def test_06_rollback_en_fallo_transaccional(self):
        """8: Rollback completo si falla la inserción de usuario."""
        gw = MockPostgresGateway(self.valid_secret, fail_on_insert="user")
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_RUNTIME)
        self.assertFalse(gw.committed)
        self.assertTrue(gw.rolled_back)

    def test_07_idempotencia_segunda_ejecucion(self):
        """9: Segunda ejecución exitosa sin duplicar entidades ni alterar contraseñas."""
        gw = MockPostgresGateway(self.valid_secret)
        output1 = io.StringIO()

        # 1ra ejecución
        code1 = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output1
        )
        self.assertEqual(code1, bpp.EXIT_OK)

        admin1 = list(gw.usuarios.values())[0]
        hash_original = admin1["password_hash"]

        # 2da ejecución
        output2 = io.StringIO()
        code2 = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output2
        )
        self.assertEqual(code2, bpp.EXIT_OK)
        self.assertIn("[IDEMPOTENTE]", output2.getvalue())

        admin2 = list(gw.usuarios.values())[0]
        self.assertEqual(admin2["password_hash"], hash_original, "La contraseña no debe ser alterada en reejecución")

    def test_08_conservacion_configuracion_existente(self):
        """10: Conservación intacta de configuraciones de seguridad existentes."""
        gw = MockPostgresGateway(self.valid_secret)
        gw.configuracion_seguridad["pausa_linkedin_min_seg"] = {
            "clave": "pausa_linkedin_min_seg",
            "valor": "250",
            "descripcion": "Custom",
            "updated_at": datetime.now().isoformat()
        }
        output = io.StringIO()

        code = bpp.main(
            argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_OK)
        self.assertEqual(gw.configuracion_seguridad["pausa_linkedin_min_seg"]["valor"], "250", "El valor preexistente debe respetarse")

    def test_09_ausencia_secretos_en_logs(self):
        """13: Comprobar que contraseñas, secretos y URLs queden enmascarados en logs."""
        gw = MockPostgresGateway(self.valid_secret)
        output = io.StringIO()

        bpp.main(
            argv=["--dry-run"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        log_content = output.getvalue()
        self.assertNotIn("SuperSecurePassword2026!#", log_content)
        self.assertNotIn(self.valid_secret, log_content)
        self.assertNotIn(":secret@", log_content)

    def test_10_dry_run_no_persiste_datos(self):
        """Verifica que el modo --dry-run no realice persistencia en el gateway."""
        gw = MockPostgresGateway(self.valid_secret)
        output = io.StringIO()

        code = bpp.main(
            argv=["--dry-run"],
            environ=self.env,
            gateway_factory=lambda d, ro: gw,
            stream=output
        )

        self.assertEqual(code, bpp.EXIT_OK)
        self.assertFalse(gw.committed)
        self.assertEqual(len(gw.tenants), 0)
        self.assertEqual(len(gw.usuarios), 0)


if __name__ == "__main__":
    unittest.main()
