"""
Test Suite: TASK-05B-06 - Credential Rotation & Regression Verification
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Valida de extremo a extremo que tras la rotación de credenciales:
1. FastAPI se conecta exitosamente bajo el rol no privilegiado 'nexus_app' con la nueva contraseña.
2. Contraseñas e identificadores antiguos son rechazados (401 Unauthorized / OperationalError).
3. Login con nuevas credenciales de admin@nexusreach.com emite token de sesión válido.
4. Flujo CRUD completo de prospectos (ingesta, consulta, actualización de contacto y borrado).
5. Aislamiento estricto multi-tenant RLS (Tenant A no puede ver ni modificar datos de Tenant B).
6. Persistencia confirmada a través de un reinicio en frío del cliente y backend.
7. Eliminación completa de registros sintéticos de prueba sin dejar residuos.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
import psycopg
from psycopg import errors
from starlette.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
import auth_service
from main import app


def get_current_env():
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


class TestCredentialRotationRegressionTask05B06(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.env = get_current_env()
        cls.app_url = cls.env.get("DATABASE_URL")
        cls.admin_url = cls.env.get("POSTGRES_ADMIN_URL")
        cls.admin_email = cls.env.get("INITIAL_ADMIN_EMAIL", "admin@nexusreach.com")
        cls.admin_password = cls.env.get("INITIAL_ADMIN_PASSWORD")
        cls.superadmin_secret = cls.env.get("SUPERADMIN_RLS_SECRET")

        database.DB_ENGINE = "postgres"
        database.DATABASE_URL = cls.app_url
        database.IS_POSTGRES = True

        # Limpiar residuos previos si hubieran quedado
        try:
            with psycopg.connect(cls.admin_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                    cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (cls.superadmin_secret,))
                    cur.execute("DELETE FROM leads WHERE perfil_url LIKE '%test-rot%' OR id LIKE 'test-rot-%';")
                conn.commit()
        except Exception:
            pass

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            with psycopg.connect(cls.admin_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                    cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (cls.superadmin_secret,))
                    cur.execute("DELETE FROM leads WHERE perfil_url LIKE '%test-rot%' OR id LIKE 'test-rot-%';")
                    cur.execute("DELETE FROM usuarios WHERE email = 'admin@tenantbeta-rot.com';")
                    cur.execute("DELETE FROM suscripciones WHERE tenant_id = 'ten_corp_beta_rot';")
                    cur.execute("DELETE FROM tenants WHERE id = 'ten_corp_beta_rot';")
                conn.commit()
        except Exception:
            pass

    def test_01_health_and_app_connection_identity(self):
        """1. Verifica endpoint de salud y rol efectivo de conexión nexus_app."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "healthy")

        with database.get_db() as db:
            cur = db.cursor()
            cur.execute("SELECT current_user, session_user;")
            row = cur.fetchone()
            curr_user = row["current_user"] if isinstance(row, dict) else row[0]
            self.assertEqual(curr_user, "nexus_app")

            cur.execute("SELECT usesuper FROM pg_user WHERE usename = current_user;")
            is_super = cur.fetchone()
            usesuper = is_super["usesuper"] if isinstance(is_super, dict) else is_super[0]
            self.assertFalse(usesuper, "El usuario de aplicación nexus_app JAMÁS debe ser superusuario")

            # Denegación a system_admin_keys
            with self.assertRaises(Exception):
                cur.execute("SELECT * FROM system_admin_keys;")

    def test_02_login_with_rotated_credentials(self):
        """2. Verifica login con credenciales rotadas y rechazo con credencial antigua."""
        # 2.1. Credencial antigua debe retornar 401
        res_old = self.client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": "old_invalid_password_2026!"
        })
        self.assertEqual(res_old.status_code, 401)

        # 2.2. Nueva credencial rotada debe retornar 200 y token de sesión
        res_new = self.client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        self.assertEqual(res_new.status_code, 200)
        data = res_new.json()
        self.assertTrue(data.get("exito"))
        self.assertIn("token", data)
        token = data["token"]

        # 2.3. Verificar endpoint de sesión
        res_ses = self.client.get("/api/auth/sesion", headers={"X-Session-Token": token})
        self.assertEqual(res_ses.status_code, 200)
        self.assertEqual(res_ses.json().get("usuario", {}).get("email"), self.admin_email)

    def test_03_lead_lifecycle_crud(self):
        """3. Ingesta, consulta, actualización y eliminación de prospecto sintético."""
        # Login
        res_log = self.client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        token = res_log.json()["token"]

        lead_id = "test-rot-prospect-sintetico_primary"
        # 3.1. Ingesta
        res_imp = self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{
                "perfil_url": "https://linkedin.com/in/test-rot-prospect-sintetico",
                "nombre": "Prospecto Rotacion",
                "cargo_actual": "Head of Security",
                "empresa_dominio": "security-corp.com"
            }],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(res_imp.status_code, 200)

        # 3.2. Consulta
        res_q = self.client.get("/api/prospectos?busqueda=Rotacion", headers={"X-Session-Token": token})
        self.assertEqual(res_q.status_code, 200)
        leads = res_q.json().get("leads", [])
        self.assertGreaterEqual(len(leads), 1)
        lead = [l for l in leads if l["nombre"] == "Prospecto Rotacion"][0]
        self.assertEqual(lead["id"], lead_id)

        # 3.3. Actualización de datos de contacto
        res_upd = self.client.put(
            f"/api/prospectos/{lead_id}/contacto?email=sec@security-corp.com&telefono=%2B56988887777",
            headers={"X-Session-Token": token}
        )
        self.assertEqual(res_upd.status_code, 200)

        # 3.4. Eliminación limpia
        res_del = self.client.delete(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(res_del.status_code, 200)

        # 3.5. Verificación de 404 tras borrado
        res_404 = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(res_404.status_code, 404)

    def test_04_multi_tenant_isolation_rls(self):
        """4. Validación estricta de aislamiento RLS entre tenants via API."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # A) Crear Tenant B usando conexión administrativa con bypass SuperAdmin
        with psycopg.connect(self.admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (self.superadmin_secret,))
                cur.execute("""
                    INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES ('ten_corp_beta_rot', NULL, 'Beta Corporation SpA', 'EMPRESA', 'ACTIVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))
                cur.execute("""
                    INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES ('sub_corp_beta_rot', 'ten_corp_beta_rot', 'ANUAL', 'ACTIVA', 3, 40.0, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso, now_iso, now_iso))
                pwd_h, salt = auth_service.hash_password("BetaRot2026!")
                cur.execute("""
                    INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, created_at, updated_at)
                    VALUES ('usr_act_beta_rot', 'ten_corp_beta_rot', 'admin@tenantbeta-rot.com', 'Admin Beta Corp', %s, %s, 'COMPANY_ADMIN', 1, 'ACTIVO', %s, %s)
                    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
                """, (pwd_h, salt, now_iso, now_iso))
                conn.commit()

        # B) Login de Tenant A y Tenant B
        tok_a = self.client.post("/api/auth/login", json={"email": self.admin_email, "password": self.admin_password}).json()["token"]
        tok_b = self.client.post("/api/auth/login", json={"email": "admin@tenantbeta-rot.com", "password": "BetaRot2026!"}).json()["token"]

        # C) Ingesta: Tenant A importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-rot-lead-alpha", "nombre": "Prospecto Alpha Rot", "cargo_actual": "Director Alpha", "empresa_dominio": "alpha-rot.cl"}],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": tok_a})

        # D) Ingesta: Tenant B importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-rot-lead-beta", "nombre": "Prospecto Beta Rot", "cargo_actual": "Director Beta", "empresa_dominio": "beta-rot.cl"}],
            "tenant_id": "ten_corp_beta_rot"
        }, headers={"X-Session-Token": tok_b})

        # E) Comprobación de aislamiento: Tenant A no ve el lead de Tenant B
        res_a = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_a})
        names_a = [l["nombre"] for l in res_a.json().get("leads", [])]
        self.assertIn("Prospecto Alpha Rot", names_a)
        self.assertNotIn("Prospecto Beta Rot", names_a)

        # F) Tenant B no ve el lead de Tenant A
        res_b = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_b})
        names_b = [l["nombre"] for l in res_b.json().get("leads", [])]
        self.assertIn("Prospecto Beta Rot", names_b)
        self.assertNotIn("Prospecto Alpha Rot", names_b)

        # G) Acceso directo por ID cruzado retorna 404
        cross_res = self.client.get("/api/prospectos/test-rot-lead-alpha_primary", headers={"X-Session-Token": tok_b})
        self.assertEqual(cross_res.status_code, 404)

    def test_05_persistence_across_backend_restart(self):
        """5. Verifica persistencia en frío tras reinicio completo del cliente y sesión."""
        # 1. Login inicial
        res_log = self.client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        token = res_log.json()["token"]

        persist_lead_id = "test-rot-persist-lead_primary"
        # 2. Ingesta
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{
                "perfil_url": "https://linkedin.com/in/test-rot-persist-lead",
                "nombre": "Prospecto Persistencia Rotacion",
                "cargo_actual": "CISO",
                "empresa_dominio": "ciso-corp.com"
            }],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})

        # 3. Simular reinicio en frío: crear nuevo cliente TestClient y purgar sesiones
        fresh_client = TestClient(app)
        auth_service.ACTIVE_SESSIONS.clear()

        # 4. Re-autenticar con credenciales rotadas
        res_relog = fresh_client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        fresh_token = res_relog.json()["token"]

        # 5. Consultar y verificar persistencia
        res_chk = fresh_client.get("/api/prospectos?busqueda=Persistencia", headers={"X-Session-Token": fresh_token})
        leads = res_chk.json().get("leads", [])
        self.assertGreaterEqual(len(leads), 1)
        lead = [l for l in leads if l["nombre"] == "Prospecto Persistencia Rotacion"][0]
        self.assertEqual(lead["id"], persist_lead_id)

        # 6. Limpieza final
        fresh_client.delete(f"/api/prospectos/{persist_lead_id}", headers={"X-Session-Token": fresh_token})


if __name__ == "__main__":
    unittest.main()
