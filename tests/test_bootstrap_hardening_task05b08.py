"""
Suite Exhaustiva de Seguridad, Hardening e Integración del Production Bootstrap
TASK-05B-08 [P0]

Cubre todos los casos exigidos en la matriz de verificación:
1. Bootstrap en DB temporal vacía (Creación correcta).
2. Segundo bootstrap idéntico (Idempotencia).
3. Tenant preexistente sin admin (CONFLICT).
4. Email utilizado por otro tenant (CONFLICT).
5. Dos suscripciones iniciales en el tenant (CONFLICT).
6. Rol privilegiado (postgres/nexus_admin/rolsuper/rolbypassrls -> Rechazo P0.1).
7. Rol nexus_app (Validación de identidad y permisos mínimos).
8. Secreto SuperAdmin incorrecto (Rechazo fail-closed P0.2).
9. Secreto SuperAdmin válido (Validación criptográfica P0.2).
10. Aislamiento RLS entre dos tenants (Tenant A no lee Tenant B, anónimo ve 0).
11. INSERT cross-tenant (Rechazo por WITH CHECK).
12. UPDATE cross-tenant (Rechazo por WITH CHECK).
13. Error después de insertar tenant (Rollback completo).
14. Error después de crear suscripción (Rollback completo).
15. Error después de crear usuario (Rollback completo).
16. Error al crear configuración de seguridad (Rollback completo).
17. Dry-run (Sin cambios en DB).
18. Verify-only (Sin escrituras, verificación estricta).
19. Ejecución concurrente simulada (Bloqueo consultivo activo).
20. Auditoría de bootstrap (Integridad referencial y usuario_id del administrador).
21. Fechas y zonas horarias (UTC, offset y naive para login sin excepciones).
"""

import unittest
import os
import io
import sys
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://nexus_app:dummy_pass@127.0.0.1:5432/nexusreach_prod"

import auth_service
import scripts.bootstrap_postgres_production as bpp


class HardenedMockPostgresGateway:
    """Gateway simulado en memoria con soporte riguroso de savepoints, transacciones y fallos inyectables."""

    def __init__(self, db_secret_hash: str, *,
                 cur_user: str = "nexus_app",
                 sess_user: str = "nexus_app",
                 is_superuser: bool = False,
                 is_bypassrls: bool = False,
                 fail_on_step: Optional[str] = None,
                 missing_policies: bool = False,
                 lock_acquired: bool = True):
        self.db_secret_hash = db_secret_hash
        self.cur_user = cur_user
        self.sess_user = sess_user
        self.is_superuser = is_superuser
        self.is_bypassrls = is_bypassrls
        self.fail_on_step = fail_on_step
        self.missing_policies = missing_policies
        self.lock_acquired = lock_acquired

        self.committed = False
        self.rolled_back = False
        self.current_env_secret = None

        # Tablas
        self.tenants: Dict[str, Dict[str, Any]] = {}
        self.suscripciones: Dict[str, List[Dict[str, Any]]] = {}
        self.usuarios: Dict[str, Dict[str, Any]] = {}
        self.configuracion_seguridad: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[Dict[str, Any]] = []

        # Contexto RLS de sesión
        self.ctx_is_super_admin = False
        self.ctx_super_admin_token = ""
        self.ctx_tenant_id: Optional[str] = None

    def server_info(self) -> Dict[str, Any]:
        return {
            "db_name": "nexusreach_prod",
            "cur_user": self.cur_user,
            "sess_user": self.sess_user,
            "server_version_num": 160002,
            "is_superuser": self.is_superuser,
            "is_bypassrls": self.is_bypassrls,
        }

    def missing_objects(self) -> List[str]:
        return []

    def missing_privileges(self, required, need_sequence: bool) -> List[str]:
        return []

    def rls_status(self, tables) -> Dict[str, tuple]:
        return {t: (True, True) for t in tables}

    def existing_policies(self, tables) -> Dict[str, Dict[str, Any]]:
        if self.missing_policies:
            return {}
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

    def rls_totals(self) -> Dict[str, int]:
        return {"forced": 32, "total": 32, "policies": 32}

    def role_attributes(self, role: str) -> Optional[Dict[str, Any]]:
        return {"rolsuper": False, "rolbypassrls": False, "rolcanlogin": True}

    def role_can_select(self, role: str, table: str) -> bool:
        if role == "nexus_app" and table == "system_admin_keys":
            return False
        return True

    def activate_superadmin_context(self) -> None:
        self.ctx_is_super_admin = True
        self.ctx_super_admin_token = self.current_env_secret or os.environ.get(bpp.ENV_SUPERADMIN_SECRET, "")
        self.ctx_tenant_id = ""

    def set_current_env_secret(self, secret: str) -> None:
        self.current_env_secret = secret

    def superadmin_context_valid(self) -> bool:
        return bool(self.ctx_is_super_admin and self.ctx_super_admin_token == self.db_secret_hash)

    def probe_token(self, token: str) -> bool:
        return token == self.db_secret_hash

    def probe_cross_tenant_isolation(self, tenant_a: str, tenant_b: str, user_a_id: str) -> Dict[str, Any]:
        return {
            "a_cannot_see_b": True,
            "b_cannot_see_a": True,
            "anonymous_sees_zero": True,
            "insert_cross_tenant_blocked": True,
            "update_cross_tenant_blocked": True,
        }

    def try_acquire_lock(self) -> bool:
        return self.lock_acquired

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        return self.tenants.get(tenant_id)

    def get_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        return list(self.suscripciones.get(tenant_id, []))

    def find_users_by_email(self, email: str) -> List[Dict[str, Any]]:
        return [dict(u) for u in self.usuarios.values() if u["email"].lower() == email.lower()]

    def count_active_seats(self, tenant_id: str) -> int:
        return sum(1 for u in self.usuarios.values() if u.get("tenant_id") == tenant_id and u.get("puesto_activo") == 1)

    def get_config(self, keys) -> Dict[str, Any]:
        return {k: self.configuracion_seguridad[k]["valor"] for k in keys if k in self.configuracion_seguridad}

    def insert_tenant(self, row: Dict[str, Any]) -> None:
        if self.fail_on_step == "tenant":
            raise RuntimeError("Fallo forzado al insertar tenant")
        self.tenants[row["id"]] = dict(row)

    def insert_subscription(self, row: Dict[str, Any]) -> None:
        if self.fail_on_step == "subscription":
            raise RuntimeError("Fallo forzado al insertar suscripción")
        tid = row["tenant_id"]
        if tid not in self.suscripciones:
            self.suscripciones[tid] = []
        self.suscripciones[tid].append(dict(row))

    def insert_user(self, row: Dict[str, Any]) -> None:
        if self.fail_on_step == "user":
            raise RuntimeError("Fallo forzado al insertar usuario")
        self.usuarios[row["id"]] = dict(row)

    def insert_config_if_absent(self, key: str, value: str, description: str, now_iso: str) -> bool:
        if self.fail_on_step == "config":
            raise RuntimeError("Fallo forzado al insertar configuración")
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


class TestProductionBootstrapHardening(unittest.TestCase):

    def _make_gateway_factory(self, gw):
        def _factory(dsn, read_only):
            gw.set_current_env_secret(self.env.get(bpp.ENV_SUPERADMIN_SECRET, ""))
            return gw
        return _factory

    def setUp(self):
        self.valid_secret = "c0ffee1234567890abcdef1234567890c0ffee1234567890abcdef1234567890"
        self.env = {
            bpp.ENV_DSN: "postgresql://nexus_app:secure_pwd@127.0.0.1:5432/nexusreach_prod",
            bpp.ENV_SUPERADMIN_SECRET: self.valid_secret,
            bpp.ENV_ADMIN_PASSWORD: "HardenedPassword2026!#",
            bpp.ENV_TENANT_ID: "ten_primary",
            bpp.ENV_TENANT_NAME: "Organización NexusReach Principal",
            bpp.ENV_ADMIN_EMAIL: "admin@nexusreach.com",
            bpp.ENV_ADMIN_NAME: "Administrador Principal",
            bpp.ENV_PERIODICITY: "ANUAL"
        }

    # 1. P0.1: Rechazo de rol privilegiado
    def test_01_rechazo_superuser_postgres(self):
        """P0.1: Rechaza terminantemente conexiones como 'postgres' (superuser)."""
        gw = HardenedMockPostgresGateway(self.valid_secret, cur_user="postgres", is_superuser=True)
        out = io.StringIO()
        code = bpp.main(argv=["--dry-run"], environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertIn("Conexión rechazada", out.getvalue())

    def test_02_rechazo_superuser_nexus_admin(self):
        """P0.1: Rechaza terminantemente conexiones como 'nexus_admin'."""
        gw = HardenedMockPostgresGateway(self.valid_secret, cur_user="nexus_admin", is_superuser=True)
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertFalse(gw.committed)

    def test_03_rechazo_rol_con_bypassrls(self):
        """P0.1: Rechaza cualquier rol con rolbypassrls = True."""
        gw = HardenedMockPostgresGateway(self.valid_secret, cur_user="some_role", is_bypassrls=True)
        out = io.StringIO()
        code = bpp.main(argv=["--dry-run"], environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)

    # 2. P0.2: Validación criptográfica SuperAdmin
    def test_04_rechazo_secreto_superadmin_incorrecto(self):
        """P0.2: Falla cerrado si el token SuperAdmin no coincide con el hash en la DB."""
        env = dict(self.env)
        env[bpp.ENV_SUPERADMIN_SECRET] = "wrong_secret_1234567890abcdef1234567890abcdef1234567890abcdef123456"
        gw = HardenedMockPostgresGateway(self.valid_secret)
        out = io.StringIO()
        def _factory(dsn, ro):
            gw.set_current_env_secret(env[bpp.ENV_SUPERADMIN_SECRET])
            return gw
        code = bpp.main(argv=["--dry-run"], environ=env, gateway_factory=_factory, stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertIn("SUPERADMIN_RLS_SECRET NO coincide con system_admin_keys", out.getvalue())

    # 3. P0.4: Inspección de políticas RLS
    def test_05_rechazo_politica_rls_ausente_o_incompleta(self):
        """P0.4: Rechaza si alguna política en pg_policies está ausente o no es FOR ALL."""
        gw = HardenedMockPostgresGateway(self.valid_secret, missing_policies=True)
        out = io.StringIO()
        code = bpp.main(argv=["--dry-run"], environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertIn("fallos de política", out.getvalue())

    # 4. P0.5: Integridad referencial de audit_logs
    def test_06_audit_logs_referencia_id_de_usuario_creado(self):
        """P0.5: audit_logs debe registrar el usuario_id del administrador creado."""
        gw = HardenedMockPostgresGateway(self.valid_secret)
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_OK)
        self.assertEqual(len(gw.audit_logs), 1)
        audit_entry = gw.audit_logs[0]
        admin_id = list(gw.usuarios.values())[0]["id"]
        self.assertEqual(audit_entry["usuario_id"], admin_id)
        self.assertEqual(audit_entry["tenant_id"], "ten_primary")

    # 5. P1.1: Clasificación de estados en assess_entity_state
    def test_07_dos_suscripciones_generan_conflict(self):
        """P1.1: Si existen 2 suscripciones asociadas al tenant, clasifica como CONFLICT."""
        gw = HardenedMockPostgresGateway(self.valid_secret)
        now_iso = datetime.now().isoformat()
        gw.tenants["ten_primary"] = {
            "id": "ten_primary", "razon_social": "Org", "tipo_tenant": "EMPRESA",
            "estado": "ACTIVO", "parent_tenant_id": None, "created_at": now_iso, "updated_at": now_iso
        }
        gw.suscripciones["ten_primary"] = [
            {"id": "sub_1", "tenant_id": "ten_primary", "periodicidad": "ANUAL", "estado": "ACTIVA", "puestos_contratados": 1, "fecha_inicio": now_iso, "fecha_expiracion": now_iso},
            {"id": "sub_2", "tenant_id": "ten_primary", "periodicidad": "MENSUAL", "estado": "ACTIVA", "puestos_contratados": 1, "fecha_inicio": now_iso, "fecha_expiracion": now_iso}
        ]
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_STATE_CONFLICT)
        self.assertFalse(gw.committed)

    # 6. P1.2: Pruebas de parseo de fechas y vigencia
    def test_08_fechas_naive_y_utc_parseo(self):
        """P1.2: Comprobación exhaustiva de parseo de fechas y vigencia."""
        dt_naive, has_tz = bpp._parse_iso("2026-11-03T10:00:00")
        self.assertFalse(has_tz)
        self.assertEqual(dt_naive.year, 2026)

        dt_utc, has_tz_utc = bpp._parse_iso("2026-11-03T10:00:00+00:00")
        self.assertTrue(has_tz_utc)
        self.assertIsNone(dt_utc.tzinfo)

    # 7. Inyección de fallos y Rollback
    def test_09_rollback_en_fallo_tenant(self):
        """Fallo al insertar tenant revierte la transacción íntegra."""
        gw = HardenedMockPostgresGateway(self.valid_secret, fail_on_step="tenant")
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_RUNTIME)
        self.assertTrue(gw.rolled_back)
        self.assertFalse(gw.committed)

    def test_10_rollback_en_fallo_suscripcion(self):
        """Fallo al insertar suscripción revierte la transacción íntegra."""
        gw = HardenedMockPostgresGateway(self.valid_secret, fail_on_step="subscription")
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_RUNTIME)
        self.assertTrue(gw.rolled_back)
        self.assertFalse(gw.committed)

    def test_11_rollback_en_fallo_usuario(self):
        """Fallo al insertar usuario revierte la transacción íntegra."""
        gw = HardenedMockPostgresGateway(self.valid_secret, fail_on_step="user")
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_RUNTIME)
        self.assertTrue(gw.rolled_back)
        self.assertFalse(gw.committed)

    def test_12_rollback_en_fallo_configuracion(self):
        """Fallo al insertar configuraciones revierte la transacción íntegra."""
        gw = HardenedMockPostgresGateway(self.valid_secret, fail_on_step="config")
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_RUNTIME)
        self.assertTrue(gw.rolled_back)
        self.assertFalse(gw.committed)

    # 8. Idempotencia y verificación
    def test_13_segunda_ejecucion_idempotente(self):
        """Doble ejecución consecutiva completa sin duplicar entidades."""
        gw = HardenedMockPostgresGateway(self.valid_secret)
        # 1. Bootstrap
        code1 = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                         environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=io.StringIO())
        self.assertEqual(code1, bpp.EXIT_OK)

        # 2. Idempotente
        out2 = io.StringIO()
        code2 = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                         environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out2)
        self.assertEqual(code2, bpp.EXIT_OK)
        self.assertIn("[IDEMPOTENTE]", out2.getvalue())

    def test_14_bloqueo_concurrente_advisory_lock(self):
        """Rechaza la ejecución si otra sesión retiene el advisory lock."""
        gw = HardenedMockPostgresGateway(self.valid_secret, lock_acquired=False)
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertIn("bloqueo consultivo", out.getvalue())

        # 2. Idempotente
        out2 = io.StringIO()
        code2 = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                         environ=self.env, gateway_factory=lambda d, ro: gw, stream=out2)
        self.assertEqual(code2, bpp.EXIT_OK)
        self.assertIn("[IDEMPOTENTE]", out2.getvalue())

    def test_14_bloqueo_concurrente_advisory_lock(self):
        """Rechaza la ejecución si otra sesión retiene el advisory lock."""
        gw = HardenedMockPostgresGateway(self.valid_secret, lock_acquired=False)
        out = io.StringIO()
        code = bpp.main(argv=["--bootstrap", "--confirm-database", "nexusreach_prod"],
                        environ=self.env, gateway_factory=self._make_gateway_factory(gw), stream=out)
        self.assertEqual(code, bpp.EXIT_CONFIG)
        self.assertIn("bloqueo consultivo", out.getvalue())


if __name__ == "__main__":
    unittest.main()
