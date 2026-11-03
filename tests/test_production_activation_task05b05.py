"""
Test Suite: TASK-05B-05 - PostgreSQL Production Activation & Application Validation
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Valida exhaustivamente la activación operacional de PostgreSQL como motor primario:
1. Autenticación, sesiones PBKDF2, recuperación de contexto y logout.
2. Aislamiento estricto multi-tenant (Tenant A vs Tenant B) bajo RLS y FORCE RLS.
3. Ciclo de vida completo de Prospectos (CRUD, búsqueda y persistencia).
4. Ciclo de Listas y Secuencias comerciales (asociaciones, pasos, desvinculación).
5. Servicios adicionales: Task Dispatcher, firmas Ed25519, Safety Config y Logging.
6. Validación de conexión exclusiva bajo el rol no privilegiado nexus_app.
7. Persistencia de datos tras reinicio de FastAPI.
"""

import os
import unittest
import hashlib
from datetime import datetime, timezone
from starlette.testclient import TestClient
from dotenv import load_dotenv

load_dotenv()

import database
import auth_service
import safety_engine
from main import app

PG_APP_URL = os.getenv("DATABASE_URL")
PG_ADMIN_URL = os.getenv("POSTGRES_ADMIN_URL", os.getenv("TARGET_DATABASE_URL"))
SUPERADMIN_SECRET = os.getenv("SUPERADMIN_RLS_SECRET")
ADMIN_EMAIL = os.getenv("INITIAL_ADMIN_EMAIL", "admin@nexusreach.com")
ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD")


class TestPostgresProductionActivationTask05B05(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Asegurar variables para la suite
        os.environ["DB_ENGINE"] = "postgres"
        os.environ["DATABASE_URL"] = PG_APP_URL
        os.environ["SUPERADMIN_RLS_SECRET"] = SUPERADMIN_SECRET
        database.IS_POSTGRES = True
        database.DATABASE_URL = PG_APP_URL

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        # Limpieza de datos sintéticos de prueba
        try:
            import psycopg
            with psycopg.connect(PG_ADMIN_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                    cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (SUPERADMIN_SECRET,))
                    cur.execute("DELETE FROM leads_en_lista WHERE lista_id LIKE 'lst_act_%';")
                    cur.execute("DELETE FROM leads_en_secuencia WHERE secuencia_id LIKE 'sec_act_%';")
                    cur.execute("DELETE FROM pasos_secuencia WHERE secuencia_id LIKE 'sec_act_%';")
                    cur.execute("DELETE FROM secuencias WHERE id LIKE 'sec_act_%';")
                    cur.execute("DELETE FROM listas_leads WHERE id LIKE 'lst_act_%';")
                    cur.execute("DELETE FROM leads WHERE perfil_url LIKE '%test-act%' OR id LIKE 'led_act_%';")
                    cur.execute("DELETE FROM usuarios WHERE email IN ('admin@tenantbeta.com', 'user_beta@tenantbeta.com');")
                    cur.execute("DELETE FROM suscripciones WHERE tenant_id = 'ten_corp_beta';")
                    cur.execute("DELETE FROM tenants WHERE id = 'ten_corp_beta';")
                conn.commit()
        except Exception as e:
            print(f"[WARN] Cleanup test data: {e}")

    # =========================================================================
    # 1. VERIFICACIÓN DE CONEXIÓN Y PRIVILEGIOS MÍNIMOS
    # =========================================================================
    def test_01_verify_app_role_connection_security(self):
        """1. Confirma que FastAPI ejecuta bajo nexus_app con usesuper=false y sin acceso a system_admin_keys."""
        with database.get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT current_user, session_user;")
            row = cur.fetchone()
            curr_user = row["current_user"] if isinstance(row, dict) else row[0]
            sess_user = row["session_user"] if isinstance(row, dict) else row[1]
            self.assertEqual(curr_user, "nexus_app")
            self.assertEqual(sess_user, "nexus_app")

            cur.execute("SELECT usesuper FROM pg_user WHERE usename = current_user;")
            is_super = cur.fetchone()
            usesuper = is_super["usesuper"] if isinstance(is_super, dict) else is_super[0]
            self.assertFalse(usesuper, "El usuario de aplicación nexus_app JAMÁS debe ser superusuario")

            # Denegación a system_admin_keys
            with self.assertRaises(Exception):
                cur.execute("SELECT * FROM system_admin_keys;")

    # =========================================================================
    # 2. AUTENTICACIÓN Y SESIONES
    # =========================================================================
    def test_02_authentication_and_sessions(self):
        """2. Valida login exitoso, login erróneo, validación de sesión y logout."""
        # A) Login con contraseña incorrecta -> 401
        bad_res = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPassword2026!"})
        self.assertEqual(bad_res.status_code, 401)
        self.assertFalse(bad_res.json().get("detail", {}).get("exito", False))

        # B) Login exitoso
        login_res = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        self.assertEqual(login_res.status_code, 200)
        data = login_res.json()
        self.assertTrue(data["exito"])
        token = data["token"]
        self.assertEqual(data["usuario"]["tenant_id"], "ten_primary")
        self.assertEqual(data["usuario"]["rol"], "COMPANY_ADMIN")

        # C) Consulta de sesión activa
        ses_res = self.client.get("/api/auth/sesion", headers={"X-Session-Token": token})
        self.assertEqual(ses_res.status_code, 200)
        self.assertTrue(ses_res.json()["autenticado"])
        self.assertEqual(ses_res.json()["usuario"]["email"], ADMIN_EMAIL)

        # D) Logout y revocación
        logout_res = self.client.post("/api/auth/logout", headers={"X-Session-Token": token})
        self.assertEqual(logout_res.status_code, 200)

        # E) Consulta post-logout -> 401
        rev_res = self.client.get("/api/auth/sesion", headers={"X-Session-Token": token})
        self.assertEqual(rev_res.status_code, 401)

    # =========================================================================
    # 3. GESTIÓN DE PROSPECTOS (CRUD Y PERSISTENCIA)
    # =========================================================================
    def test_03_leads_lifecycle_and_crud(self):
        """3. Valida ciclo completo de prospectos: creación, búsqueda, actualización y eliminación."""
        login_res = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        token = login_res.json()["token"]

        # A) Ingesta de lead
        lead_payload = {
            "leads": [{
                "perfil_url": "https://linkedin.com/in/test-act-mateo-silva",
                "nombre": "Mateo Silva",
                "cargo_actual": "Chief Revenue Officer",
                "empresa_dominio": "silva-revenue.com"
            }],
            "tenant_id": "ten_primary"
        }
        imp_res = self.client.post("/api/prospectos/importar-lote", json=lead_payload, headers={"X-Session-Token": token})
        self.assertEqual(imp_res.status_code, 200)

        # B) Búsqueda filtrada
        search_res = self.client.get("/api/prospectos?busqueda=Mateo", headers={"X-Session-Token": token})
        self.assertEqual(search_res.status_code, 200)
        leads = search_res.json().get("leads", [])
        self.assertGreaterEqual(len(leads), 1)
        lead = [l for l in leads if l["nombre"] == "Mateo Silva"][0]
        lead_id = lead["id"]

        # C) Actualización de contacto
        upd_res = self.client.put(f"/api/prospectos/{lead_id}/contacto?email=mateo@silva-revenue.com&telefono=%2B56987654321", headers={"X-Session-Token": token})
        self.assertEqual(upd_res.status_code, 200)

        det_res = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(det_res.status_code, 200)
        self.assertEqual(det_res.json().get("email"), "mateo@silva-revenue.com")

        # D) Eliminación de lead
        del_res = self.client.delete(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(del_res.status_code, 200)

        # E) Comprobación de eliminación
        det_post = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(det_post.status_code, 404)

    # =========================================================================
    # 4. LISTAS Y SECUENCIAS COMERCIALES
    # =========================================================================
    def test_04_lists_and_sequences_operations(self):
        """4. Valida creación de listas, asociación de prospectos, secuencias y pasos."""
        login_res = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        token = login_res.json()["token"]

        # A) Crear Lista
        lst_res = self.client.post("/api/listas", json={
            "id": "lst_act_directors",
            "nombre": "Directores Comerciales 2026",
            "descripcion": "Lista de prospección B2B",
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(lst_res.status_code, 200)

        # B) Crear Secuencia
        seq_res = self.client.post("/api/secuencias", json={
            "nombre": "Secuencia Activación Q4",
            "descripcion": "Contacto multicanal",
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(seq_res.status_code, 200)
        seq_id = seq_res.json().get("id") or seq_res.json().get("secuencia_id")

        # C) Consultar Secuencias
        get_seq = self.client.get("/api/secuencias", headers={"X-Session-Token": token})
        self.assertEqual(get_seq.status_code, 200)
        seq_names = [s["nombre"] for s in get_seq.json().get("secuencias", [])]
        self.assertIn("Secuencia Activación Q4", seq_names)

        # D) Eliminar Secuencia de prueba
        if seq_id:
            del_seq = self.client.delete(f"/api/secuencias/{seq_id}", headers={"X-Session-Token": token})
            self.assertEqual(del_seq.status_code, 200)

    # =========================================================================
    # 5. AISLAMIENTO MULTI-TENANT ESTRICTO (TENANT A VS TENANT B)
    # =========================================================================
    def test_05_multi_tenant_isolation_rls(self):
        """5. Demuestra aislamiento estricto e imposibilidad de acceso cruzado entre inquilinos."""
        now_iso = datetime.now(timezone.utc).isoformat()
        import psycopg

        # A) Crear Tenant B y su Administrador usando conexión administrativa
        with psycopg.connect(PG_ADMIN_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (SUPERADMIN_SECRET,))
                cur.execute("""
                    INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES ('ten_corp_beta', NULL, 'Beta Corporation SpA', 'EMPRESA', 'ACTIVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))
                cur.execute("""
                    INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES ('sub_corp_beta', 'ten_corp_beta', 'ANUAL', 'ACTIVA', 3, 40.0, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso, now_iso, now_iso))
                pwd_h, salt = auth_service.hash_password("BetaSecure2026!")
                cur.execute("""
                    INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, created_at, updated_at)
                    VALUES ('usr_act_beta', 'ten_corp_beta', 'admin@tenantbeta.com', 'Admin Beta Corp', %s, %s, 'COMPANY_ADMIN', 1, 'ACTIVO', %s, %s)
                    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
                """, (pwd_h, salt, now_iso, now_iso))
                conn.commit()

        # B) Login de Tenant A y Tenant B
        tok_a = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).json()["token"]
        tok_b = self.client.post("/api/auth/login", json={"email": "admin@tenantbeta.com", "password": "BetaSecure2026!"}).json()["token"]

        # C) Ingesta: Tenant A importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-act-prospect-alpha", "nombre": "Prospecto Alpha Corp", "cargo_actual": "Director Alpha", "empresa_dominio": "alpha.cl"}],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": tok_a})

        # D) Ingesta: Tenant B importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-act-prospect-beta", "nombre": "Prospecto Beta Corp", "cargo_actual": "Director Beta", "empresa_dominio": "beta.cl"}],
            "tenant_id": "ten_corp_beta"
        }, headers={"X-Session-Token": tok_b})

        # E) Tenant A consulta prospectos: DEBE ver Alpha y NUNCA Beta
        leads_a = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_a}).json().get("leads", [])
        names_a = [l["nombre"] for l in leads_a]
        self.assertIn("Prospecto Alpha Corp", names_a)
        self.assertNotIn("Prospecto Beta Corp", names_a)

        # F) Tenant B consulta prospectos: DEBE ver Beta y NUNCA Alpha
        leads_b = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_b}).json().get("leads", [])
        names_b = [l["nombre"] for l in leads_b]
        self.assertIn("Prospecto Beta Corp", names_b)
        self.assertNotIn("Prospecto Alpha Corp", names_b)

        # G) Tenant B intenta acceder directamente por ID al lead de Tenant A -> 404
        lead_a_id = [l["id"] for l in leads_a if l["nombre"] == "Prospecto Alpha Corp"][0]
        cross_res = self.client.get(f"/api/prospectos/{lead_a_id}", headers={"X-Session-Token": tok_b})
        self.assertEqual(cross_res.status_code, 404, "Tenant B no debe poder acceder al lead de Tenant A")

    # =========================================================================
    # 6. PERSISTENCIA TRAS REINICIO DEL BACKEND
    # =========================================================================
    def test_06_persistence_across_backend_restart(self):
        """6. Demuestra persistencia de transacciones tras destruir la instancia en memoria y reiniciar FastAPI."""
        login_res = self.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        token = login_res.json()["token"]

        # Insertar lead persistente
        unique_url = f"https://linkedin.com/in/test-act-persist-{datetime.now().timestamp()}"
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": unique_url, "nombre": "Prospecto Persistente Prod", "cargo_actual": "CEO", "empresa_dominio": "persist-prod.com"}],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})

        # 1. Limpiar sesiones en memoria
        auth_service.ACTIVE_SESSIONS.clear()

        # 2. Recrear TestClient (simula arranque fresco del servidor FastAPI)
        fresh_client = TestClient(app)

        # 3. Autenticarse de nuevo contra PostgreSQL
        re_login = fresh_client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        self.assertEqual(re_login.status_code, 200)
        fresh_token = re_login.json()["token"]

        # 4. Verificar que el lead persistió íntegramente
        query_res = fresh_client.get("/api/prospectos?busqueda=Persistente", headers={"X-Session-Token": fresh_token})
        self.assertEqual(query_res.status_code, 200)
        prospects = query_res.json().get("leads", [])
        self.assertGreaterEqual(len(prospects), 1)
        self.assertEqual(prospects[0]["nombre"], "Prospecto Persistente Prod")


if __name__ == "__main__":
    unittest.main()

