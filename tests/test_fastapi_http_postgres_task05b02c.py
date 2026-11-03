"""
Test Suite: TASK-05B-02C - FastAPI HTTP Operational Integration on PostgreSQL
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Ejecuta pruebas HTTP reales contra FastAPI montado sobre PostgreSQL 16 local
utilizando el rol de privilegios mínimos nexus_app:
1. Arranque de FastAPI y health check (/api/health).
2. Verificación de que la conexión operacional usa nexus_app y NO nexus_admin.
3. Login (/api/auth/login) y validación de sesión (/api/auth/sesion).
4. Logout (/api/auth/logout) y revocación en memoria.
5. RBAC estricto: Miembro vs Administrador de Empresa vs SuperAdmin.
6. Creación y consulta de leads (/api/prospectos/importar-lote, /api/prospectos).
7. Actualización y eliminación de leads (/api/prospectos/{id}/contacto, DELETE).
8. Creación y consulta de listas (/api/listas).
9. Operaciones sobre secuencias (/api/secuencias).
10. Aislamiento estricto entre dos organizaciones (Tenant A vs Tenant B).
11. Acceso administrativo de SuperAdmin.
12. Manejo de errores y códigos HTTP (401, 403, 404, 422).
13. Persistencia de datos tras reinicio del backend.
"""

import os
import unittest
import psycopg
from datetime import datetime, timezone, timedelta
from starlette.testclient import TestClient

PG_APP_URL = os.getenv(
    "POSTGRES_APP_TEST_URL",
    "postgresql://nexus_app:app_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)
PG_ADMIN_URL = os.getenv(
    "POSTGRES_ADMIN_TEST_URL",
    "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test"
)
SUPERADMIN_SECRET = "nexus_superadmin_secure_key_2026"

import database
import auth_service
from main import app


class TestFastAPIHttpPostgresTask05B02C(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.old_db_url = os.environ.get("DATABASE_URL")
        cls.old_is_pg = database.IS_POSTGRES
        cls.old_engine = os.environ.get("DB_ENGINE")
        cls.old_secret = os.environ.get("SUPERADMIN_RLS_SECRET")

        os.environ["DATABASE_URL"] = PG_APP_URL
        os.environ["DB_ENGINE"] = "postgres"
        os.environ["SUPERADMIN_RLS_SECRET"] = SUPERADMIN_SECRET
        database.IS_POSTGRES = True
        database.DATABASE_URL = PG_APP_URL

        # Limpiar datos previos de pruebas
        cls._cleanup_test_data()

        # Inicializar cliente de prueba FastAPI
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_test_data()

        database.IS_POSTGRES = cls.old_is_pg
        if cls.old_db_url is not None:
            os.environ["DATABASE_URL"] = cls.old_db_url
            database.DATABASE_URL = cls.old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
            database.DATABASE_URL = ""

        if cls.old_engine is not None:
            os.environ["DB_ENGINE"] = cls.old_engine
        else:
            os.environ.pop("DB_ENGINE", None)

        if cls.old_secret is not None:
            os.environ["SUPERADMIN_RLS_SECRET"] = cls.old_secret
        else:
            os.environ.pop("SUPERADMIN_RLS_SECRET", None)

    @classmethod
    def _cleanup_test_data(cls):
        """Limpia los datos generados durante las pruebas en PostgreSQL."""
        try:
            with psycopg.connect(PG_ADMIN_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.is_super_admin', 'true', false);")
                    cur.execute("SELECT set_config('app.super_admin_token', %s, false);", (SUPERADMIN_SECRET,))
                    cur.execute("DELETE FROM audit_logs;")
                    cur.execute("DELETE FROM system_logs WHERE tenant_id = 'ten_http_b';")
                    cur.execute("DELETE FROM leads_en_lista WHERE lista_id LIKE 'lst_http_%';")
                    cur.execute("DELETE FROM leads_en_secuencia WHERE secuencia_id LIKE 'sec_http_%';")
                    cur.execute("DELETE FROM pasos_secuencia WHERE secuencia_id LIKE 'sec_http_%';")
                    cur.execute("DELETE FROM secuencias WHERE id LIKE 'sec_http_%';")
                    cur.execute("DELETE FROM leads WHERE perfil_url LIKE '%test-http%' OR id LIKE 'led_http_%' OR tenant_id = 'ten_http_b';")
                    cur.execute("DELETE FROM listas_leads WHERE id LIKE 'lst_http_%';")
                    cur.execute("DELETE FROM usuarios WHERE email IN ('member_http@nexusreach.com', 'admin@tenantb.com', 'super_http@nexusreach.com');")
                    cur.execute("DELETE FROM suscripciones WHERE tenant_id = 'ten_http_b';")
                    cur.execute("DELETE FROM tenants WHERE id = 'ten_http_b';")
                conn.commit()
        except Exception as e:
            print(f"[WARN] Cleanup HTTP test data: {e}")

    def test_01_startup_and_health_check(self):
        """1 y 2. Valida el arranque de FastAPI y el endpoint de health check."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("uptime"), "ok")

    def test_02_verify_operational_connection_uses_nexus_app_not_admin(self):
        """Verifica con evidencia SQL que la conexión operacional de FastAPI ejecuta como nexus_app y NO nexus_admin."""
        with database.get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT current_user, session_user;")
            row = cur.fetchone()
            curr_user = row["current_user"] if isinstance(row, dict) else row[0]
            sess_user = row["session_user"] if isinstance(row, dict) else row[1]
            self.assertEqual(curr_user, "nexus_app", f"La conexión debe ser nexus_app, obtenido: {curr_user}")
            self.assertEqual(sess_user, "nexus_app")

            # Verificar que no es superusuario
            cur.execute("SELECT usesuper FROM pg_user WHERE usename = current_user;")
            is_super = cur.fetchone()
            usesuper = is_super["usesuper"] if isinstance(is_super, dict) else is_super[0]
            self.assertFalse(usesuper, "El usuario de aplicación nexus_app JAMÁS debe ser superusuario")

            # Verificar que nexus_app no puede consultar system_admin_keys
            with self.assertRaises(Exception):
                cur.execute("SELECT * FROM system_admin_keys;")

    def test_03_login_and_session_validation_flow(self):
        """3 y 4. Valida login, emisión de token seguro en memoria y consulta de sesión vía HTTP."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        self.assertEqual(login_res.status_code, 200)
        data = login_res.json()
        self.assertTrue(data.get("exito"))
        self.assertIn("token", data)
        token = data["token"]

        # Validar sesión activa vía GET /api/auth/sesion
        sesion_res = self.client.get("/api/auth/sesion", headers={"X-Session-Token": token})
        self.assertEqual(sesion_res.status_code, 200)
        sdata = sesion_res.json()
        self.assertTrue(sdata.get("autenticado"))
        usuario = sdata.get("usuario", {})
        self.assertEqual(usuario.get("email"), "admin@nexusreach.com")
        self.assertEqual(usuario.get("tenant_id"), "ten_primary")
        self.assertEqual(usuario.get("rol"), "COMPANY_ADMIN")

    def test_04_logout_flow_and_session_revocation(self):
        """5. Valida logout vía HTTP y destrucción inmediata de sesión en memoria."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        token = login_res.json()["token"]

        # Logout
        logout_res = self.client.post("/api/auth/logout", headers={"X-Session-Token": token})
        self.assertEqual(logout_res.status_code, 200)

        # Intento posterior de validar sesión debe retornar 401
        sesion_after = self.client.get("/api/auth/sesion", headers={"X-Session-Token": token})
        self.assertEqual(sesion_after.status_code, 401)

    def test_05_rbac_and_privilege_boundaries(self):
        """6. Valida que un COMPANY_MEMBER no pueda acceder a endpoints administrativos (HTTP 403)."""
        # Crear miembro en ten_primary
        with database.tenant_context_scope(tenant_id="ten_primary"):
            c_res = auth_service.create_user_for_tenant(
                tenant_id="ten_primary",
                email="member_http@nexusreach.com",
                password="MemberPass2026!",
                name="Miembro Operativo",
                role="COMPANY_MEMBER"
            )
            self.assertTrue(c_res["exito"])

        # Login del miembro
        m_login = self.client.post("/api/auth/login", json={
            "email": "member_http@nexusreach.com",
            "password": "MemberPass2026!"
        })
        self.assertEqual(m_login.status_code, 200)
        m_token = m_login.json()["token"]

        # Intentar acceder a listado global de tenants -> 403
        r_tenants = self.client.get("/api/tenants", headers={"X-Session-Token": m_token})
        self.assertEqual(r_tenants.status_code, 403)

        # Intentar crear una cuenta global -> 403 (enviando payload válido con esquema CreateAccountRequest)
        valid_payload = {
            "tipo_cuenta": "EMPRESA",
            "razon_social": "Empresa No Autorizada",
            "admin_nombre": "Admin Falso",
            "admin_email": "admin@falso.com",
            "admin_password": "Password123!"
        }
        r_create = self.client.post("/api/admin/cuentas", json=valid_payload, headers={"X-Session-Token": m_token})
        self.assertEqual(r_create.status_code, 403)

    def test_06_lead_creation_and_query_http(self):
        """7 y 8. Valida creación e importación de leads por lote y consulta filtrada vía HTTP."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        token = login_res.json()["token"]

        # Importar lead vía POST /api/prospectos/importar-lote
        lead_payload = {
            "leads": [{
                "perfil_url": "https://linkedin.com/in/test-http-camila",
                "nombre": "Camila Rodríguez",
                "cargo_actual": "VP Commercial",
                "empresa_dominio": "camila-corp.cl"
            }],
            "tenant_id": "ten_primary"
        }
        imp_res = self.client.post("/api/prospectos/importar-lote", json=lead_payload, headers={"X-Session-Token": token})
        self.assertEqual(imp_res.status_code, 200)

        # Consultar leads vía GET /api/prospectos
        list_res = self.client.get("/api/prospectos?busqueda=Camila", headers={"X-Session-Token": token})
        self.assertEqual(list_res.status_code, 200)
        prospects = list_res.json().get("leads", [])
        self.assertGreaterEqual(len(prospects), 1)
        self.assertEqual(prospects[0]["nombre"], "Camila Rodríguez")
        lead_id = prospects[0]["id"]

        # Consultar por ID directo
        detail_res = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(detail_res.status_code, 200)
        self.assertEqual(detail_res.json().get("id"), lead_id)

    def test_07_lead_update_and_delete_http(self):
        """9. Valida actualización de datos de contacto y eliminación de lead vía HTTP."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        token = login_res.json()["token"]

        # Importar lead
        imp_res = self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{
                "perfil_url": "https://linkedin.com/in/test-http-diego",
                "nombre": "Diego Morales",
                "cargo_actual": "Director TI",
                "empresa_dominio": "diego-tech.com"
            }],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(imp_res.status_code, 200)

        # Obtener lead_id
        list_res = self.client.get("/api/prospectos?busqueda=Diego", headers={"X-Session-Token": token})
        lead_id = list_res.json()["leads"][0]["id"]

        # Actualizar contacto vía PUT /api/prospectos/{lead_id}/contacto (con query params)
        upd_res = self.client.put(
            f"/api/prospectos/{lead_id}/contacto?email=diego@diego-tech.com&telefono=%2B56911223344",
            headers={"X-Session-Token": token}
        )
        self.assertEqual(upd_res.status_code, 200)

        # Verificar actualización
        det_res = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(det_res.json().get("email"), "diego@diego-tech.com")

        # Eliminar lead vía DELETE /api/prospectos/{lead_id}
        del_res = self.client.delete(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(del_res.status_code, 200)

        # Consulta posterior debe retornar 404
        post_del = self.client.get(f"/api/prospectos/{lead_id}", headers={"X-Session-Token": token})
        self.assertEqual(post_del.status_code, 404)

    def test_08_lists_creation_and_query_http(self):
        """10. Valida creación y consulta de listas de prospectos vía HTTP."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        token = login_res.json()["token"]

        # Crear lista vía POST /api/listas
        create_res = self.client.post("/api/listas", json={
            "id": "lst_http_01",
            "nombre": "CEOs Santiago HTTP",
            "descripcion": "Audiencia B2B HTTP",
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(create_res.status_code, 200)

        # Consultar listas vía GET /api/listas
        lists_res = self.client.get("/api/listas", headers={"X-Session-Token": token})
        self.assertEqual(lists_res.status_code, 200)
        lists = lists_res.json().get("listas", [])
        names = [l["nombre"] for l in lists]
        self.assertIn("CEOs Santiago HTTP", names)

    def test_09_sequence_operations_http(self):
        """11. Valida creación, consulta y eliminación de secuencias comerciales vía HTTP."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@nexusreach.com",
            "password": "AdminSecure2026!"
        })
        token = login_res.json()["token"]

        # Crear secuencia vía POST /api/secuencias
        seq_res = self.client.post("/api/secuencias", json={
            "nombre": "Secuencia Prospección HTTP",
            "descripcion": "LinkedIn + Followup",
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(seq_res.status_code, 200)
        seq_data = seq_res.json()
        seq_id = seq_data.get("id") or seq_data.get("secuencia_id")

        # Consultar secuencias
        get_res = self.client.get("/api/secuencias", headers={"X-Session-Token": token})
        self.assertEqual(get_res.status_code, 200)

        # Eliminar secuencia vía DELETE /api/secuencias/{secuencia_id}
        if seq_id:
            del_seq = self.client.delete(f"/api/secuencias/{seq_id}", headers={"X-Session-Token": token})
            self.assertEqual(del_seq.status_code, 200)

    def test_10_multi_tenant_isolation_http(self):
        """12. Demuestra aislamiento estricto entre Tenant A y Tenant B vía HTTP."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Crear Tenant B mediante contexto SuperAdmin
        with database.tenant_context_scope(is_super_admin=True):
            with database.get_db() as db:
                cur = db.cursor()
                cur.execute("""
                    INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES ('ten_http_b', NULL, 'Tenant B Corp SpA', 'EMPRESA', 'ACTIVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso))
                cur.execute("""
                    INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES ('sub_http_b', 'ten_http_b', 'MENSUAL', 'ACTIVA', 5, 35.0, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (now_iso, now_iso, now_iso, now_iso))

        # Crear usuario admin para Tenant B
        with database.tenant_context_scope(tenant_id="ten_http_b"):
            auth_service.create_user_for_tenant(
                tenant_id="ten_http_b",
                email="admin@tenantb.com",
                password="PassTenantB2026!",
                name="Admin Tenant B",
                role="COMPANY_ADMIN"
            )

        # Login de Tenant A
        tok_a = self.client.post("/api/auth/login", json={"email": "admin@nexusreach.com", "password": "AdminSecure2026!"}).json()["token"]
        # Login de Tenant B
        tok_b = self.client.post("/api/auth/login", json={"email": "admin@tenantb.com", "password": "PassTenantB2026!"}).json()["token"]

        # Tenant A importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-http-tenant-a-lead", "nombre": "Prospecto Alpha A", "cargo_actual": "Gerente A", "empresa_dominio": "alpha.cl"}],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": tok_a})

        # Tenant B importa un lead
        self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": "https://linkedin.com/in/test-http-tenant-b-lead", "nombre": "Prospecto Beta B", "cargo_actual": "Gerente B", "empresa_dominio": "beta.cl"}],
            "tenant_id": "ten_http_b"
        }, headers={"X-Session-Token": tok_b})

        # Tenant A consulta prospectos: DEBE ver Alpha A y JAMÁS ver Beta B
        leads_a = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_a}).json().get("leads", [])
        names_a = [l["nombre"] for l in leads_a]
        self.assertIn("Prospecto Alpha A", names_a)
        self.assertNotIn("Prospecto Beta B", names_a)

        # Tenant B consulta prospectos: DEBE ver Beta B y JAMÁS ver Alpha A
        leads_b = self.client.get("/api/prospectos", headers={"X-Session-Token": tok_b}).json().get("leads", [])
        names_b = [l["nombre"] for l in leads_b]
        self.assertIn("Prospecto Beta B", names_b)
        self.assertNotIn("Prospecto Alpha A", names_b)

        # Obtener ID del lead de Tenant A
        lead_a_id = [l["id"] for l in leads_a if l["nombre"] == "Prospecto Alpha A"][0]

        # Tenant B intenta consultar directamente el lead de Tenant A -> debe recibir 403 o 404
        cross_res = self.client.get(f"/api/prospectos/{lead_a_id}", headers={"X-Session-Token": tok_b})
        self.assertIn(cross_res.status_code, (403, 404), "Tenant B no puede ver prospectos de Tenant A")

    def test_11_administrative_access_http(self):
        """13. Valida acceso a endpoints administrativos con rol SUPER_ADMIN."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Crear usuario SuperAdmin
        with database.tenant_context_scope(is_super_admin=True):
            pwd_h, salt = auth_service.hash_password("SuperAdmin2026!")
            with database.get_db() as db:
                cur = db.cursor()
                cur.execute("""
                    INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, created_at, updated_at)
                    VALUES ('usr_super_http', 'ten_primary', 'super_http@nexusreach.com', 'Super Administrador HTTP', %s, %s, 'SUPER_ADMIN', 1, 'ACTIVO', %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """, (pwd_h, salt, now_iso, now_iso))

        # Login de SuperAdmin
        sa_res = self.client.post("/api/auth/login", json={
            "email": "super_http@nexusreach.com",
            "password": "SuperAdmin2026!"
        })
        self.assertEqual(sa_res.status_code, 200)
        sa_token = sa_res.json()["token"]

        # SuperAdmin consulta listado global de tenants vía GET /api/tenants -> 200
        t_res = self.client.get("/api/tenants", headers={"X-Session-Token": sa_token})
        self.assertEqual(t_res.status_code, 200)
        self.assertIsInstance(t_res.json(), list)

    def test_12_error_handling_and_http_status_codes(self):
        """14. Valida manejo canónico de errores HTTP (401, 403, 404, 422)."""
        # 401: Solicitud sin token a endpoint protegido
        r401 = self.client.get("/api/prospectos")
        self.assertEqual(r401.status_code, 401)

        # 401: Token inválido
        r401_fake = self.client.get("/api/prospectos", headers={"X-Session-Token": "tok_token_invalido_12345"})
        self.assertEqual(r401_fake.status_code, 401)

        # 404: Prospecto inexistente
        login_res = self.client.post("/api/auth/login", json={"email": "admin@nexusreach.com", "password": "AdminSecure2026!"})
        tok = login_res.json()["token"]
        r404 = self.client.get("/api/prospectos/lead_inexistente_9999", headers={"X-Session-Token": tok})
        self.assertEqual(r404.status_code, 404)

        # 422: Payload con schema inválido (Pydantic validation error)
        r422 = self.client.post("/api/auth/login", json={"email_incorrecto": "test"})
        self.assertEqual(r422.status_code, 422)

    def test_13_persistence_across_backend_restart(self):
        """15. Demuestra persistencia de datos tras destruir y reiniciar la instancia de FastAPI."""
        login_res = self.client.post("/api/auth/login", json={"email": "admin@nexusreach.com", "password": "AdminSecure2026!"})
        token = login_res.json()["token"]

        # Importar lead para comprobar persistencia
        unique_url = f"https://linkedin.com/in/test-http-persistence-{datetime.now().timestamp()}"
        imp_res = self.client.post("/api/prospectos/importar-lote", json={
            "leads": [{"perfil_url": unique_url, "nombre": "Prospecto Persistente", "cargo_actual": "Director", "empresa_dominio": "persist.com"}],
            "tenant_id": "ten_primary"
        }, headers={"X-Session-Token": token})
        self.assertEqual(imp_res.status_code, 200)

        # 1. Limpiar sesiones en memoria (simula reinicio de proceso del servidor)
        auth_service.ACTIVE_SESSIONS.clear()

        # 2. Iniciar nueva instancia de TestClient (simula arranque fresco del servidor)
        fresh_client = TestClient(app)

        # 3. Autenticarse de nuevo con el hash PBKDF2 persistido en PostgreSQL
        re_login = fresh_client.post("/api/auth/login", json={"email": "admin@nexusreach.com", "password": "AdminSecure2026!"})
        self.assertEqual(re_login.status_code, 200)
        fresh_token = re_login.json()["token"]

        # 4. Consultar datos creados antes del reinicio
        query_res = fresh_client.get("/api/prospectos?busqueda=Persistente", headers={"X-Session-Token": fresh_token})
        self.assertEqual(query_res.status_code, 200)
        prospects = query_res.json().get("leads", [])
        self.assertGreaterEqual(len(prospects), 1)
        self.assertEqual(prospects[0]["nombre"], "Prospecto Persistente")


if __name__ == "__main__":
    unittest.main()
