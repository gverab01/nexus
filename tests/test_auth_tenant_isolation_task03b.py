"""
Test Suite Obligatoria TASK-03B: Blindaje de Autenticación y Aislamiento Multi-Tenant en main.py

Verifica rigurosamente los 9 escenarios requeridos (A-I):
A. Solicitud sin token a cada endpoint privado afectado: rechazada (HTTP 401).
B. Solicitud con token inválido o expirado: rechazada (HTTP 401).
C. Usuario autenticado consultando su propio tenant: funciona (HTTP 200).
D. Usuario del tenant A intentando consultar datos del tenant B: rechazado (HTTP 403).
E. Usuario del tenant A intentando exportar datos del tenant B: rechazado (HTTP 403).
F. Usuario autenticado solicitando un tenant_id manipulado en la URL: rechazado sin acceso adicional (HTTP 403).
G. Usuario con permisos administrativos legítimos: conserva únicamente los privilegios correspondientes.
H. Consultas de métricas, listas y secuencias: no filtran datos de otros tenants indirectamente.
I. Ausencia de caller, identidad incompleta o contexto de permisos inválido: falla de forma segura (Fail-Closed).

IMPORTANTE: Ejecutado de forma 100% aislada sobre una base de datos temporal SQLite mediante SQLITE_DB_PATH.
leads.db jamás es tocada.
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import io
from contextlib import redirect_stdout, redirect_stderr, AsyncExitStack
import tempfile
import time
import json
import unittest
from datetime import datetime, timezone
from fastapi import HTTPException
from starlette.responses import Response

# ------------------------------------------------------------------------------
# 1. AISLAMIENTO ESTRICTO DE BASE DE DATOS (TASK-01 / PREVENCIÓN DE CONTAMINACIÓN)
# ------------------------------------------------------------------------------
TEMP_TEST_DIR = tempfile.mkdtemp(prefix="nexus_task03b_isolated_")
TEMP_DB_PATH = os.path.join(TEMP_TEST_DIR, "test_sandbox_task03b.db")
os.environ["SQLITE_DB_PATH"] = TEMP_DB_PATH

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import urllib.parse
import database
from database import get_db, init_db, get_sqlite_db_path, DEFAULT_SQLITE_PATH
import auth_service
from main import app, _resolve_permitted_tenants
import fastapi.routing
import fastapi.dependencies.utils
import starlette.routing
import starlette.concurrency


async def _inline_run_in_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)


fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
starlette.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool


class _ASGIResponse:
    def __init__(self, status_code: int, headers: dict, body: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


from starlette.middleware.exceptions import ExceptionMiddleware


class SandboxSafeTestClient:
    """Cliente ASGI síncrono en memoria que ejecuta el stack completo de FastAPI
    (ruteo, validación Pydantic, dependencias y HTTPException) sin
    invocar socket.socketpair() de asyncio en entornos Windows aislados.
    """
    def __init__(self, asgi_app):
        self.app = ExceptionMiddleware(asgi_app.router, handlers=asgi_app.exception_handlers)

    def request(self, method: str, url: str, headers: dict = None, json_body=None) -> _ASGIResponse:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        query_string = (parsed.query or "").encode("utf-8")

        raw_body = b""
        req_headers = []
        if headers:
            for k, v in headers.items():
                req_headers.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))
        if json_body is not None:
            raw_body = json.dumps(json_body).encode("utf-8")
            req_headers.append((b"content-type", b"application/json"))
            req_headers.append((b"content-length", str(len(raw_body)).encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query_string,
            "root_path": "",
            "headers": req_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
            "fastapi_middleware_astack": AsyncExitStack(),
        }

        body_sent = False
        response_status = 500
        response_headers = {}
        response_body = bytearray()

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message["status"]
                for k, v in message.get("headers", []):
                    response_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        coro = self.app(scope, receive, send)
        try:
            while True:
                coro.send(None)
        except StopIteration:
            pass

        return _ASGIResponse(response_status, response_headers, bytes(response_body))

    def get(self, url: str, headers: dict = None) -> _ASGIResponse:
        return self.request("GET", url, headers=headers)

    def post(self, url: str, json: dict = None, headers: dict = None) -> _ASGIResponse:
        return self.request("POST", url, headers=headers, json_body=json)

    def put(self, url: str, json: dict = None, headers: dict = None) -> _ASGIResponse:
        return self.request("PUT", url, headers=headers, json_body=json)

    def patch(self, url: str, json: dict = None, headers: dict = None) -> _ASGIResponse:
        return self.request("PATCH", url, headers=headers, json_body=json)

    def delete(self, url: str, headers: dict = None) -> _ASGIResponse:
        return self.request("DELETE", url, headers=headers)


class TestAuthAndTenantIsolationTask03B(unittest.TestCase):
    """Suite automatizada para verificar el blindaje contra el bypass de autenticación
    y la garantía de aislamiento mono-tenant estricto en main.py (TASK-03B).
    """

    @classmethod
    def setUpClass(cls):
        os.environ["SQLITE_DB_PATH"] = TEMP_DB_PATH
        # Asegurar que estamos usando la base aislada
        assert get_sqlite_db_path() == TEMP_DB_PATH, "La base de pruebas DEBE ser la temporal aislada."
        assert TEMP_DB_PATH != DEFAULT_SQLITE_PATH, "leads.db no debe usarse para pruebas."

        # Inicializar esquema limpio en la base temporal silenciando emojis en Windows
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            init_db()
        cls.client = SandboxSafeTestClient(app)

        # Sembrar datos sintéticos multi-tenant controlados
        cls.now_iso = datetime.now(timezone.utc).isoformat()
        cls.future_iso = "2030-01-01T00:00:00"

        cls.tenant_alpha = "ten_corp_alpha"
        cls.tenant_beta = "ten_corp_beta"
        cls.tenant_agency = "ten_agency_gamma"
        cls.tenant_subordinate = "ten_sub_gamma"
        cls.tenant_super = "ten_superadmin"

        with get_db() as conn:
            cursor = conn.cursor()

            # 1. Tenants
            cursor.execute("""
                INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, NULL, 'Corporación Alpha', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (cls.tenant_alpha, cls.now_iso, cls.now_iso))

            cursor.execute("""
                INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, NULL, 'Corporación Beta', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))

            cursor.execute("""
                INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, NULL, 'Agencia Gamma Media', 'AGENCIA', 'ACTIVO', ?, ?)
            """, (cls.tenant_agency, cls.now_iso, cls.now_iso))

            cursor.execute("""
                INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, ?, 'Cliente Subordinado Gamma', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (cls.tenant_subordinate, cls.tenant_agency, cls.now_iso, cls.now_iso))

            # 2. Suscripciones Activas
            for t_id in [cls.tenant_alpha, cls.tenant_beta, cls.tenant_agency, cls.tenant_subordinate]:
                cursor.execute("""
                    INSERT OR REPLACE INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES (?, ?, 'MENSUAL', 'ACTIVA', 5, 35.0, ?, ?, ?, ?)
                """, (f"sub_{t_id}", t_id, cls.now_iso, cls.future_iso, cls.now_iso, cls.now_iso))

            # 3. Usuarios
            # Usuario Alpha (COMPANY_ADMIN)
            h_alpha, s_alpha = auth_service.hash_password("PassAlpha123!")
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES ('usr_alpha', ?, 'admin@alpha.com', 'Admin Alpha', ?, ?, 'COMPANY_ADMIN', 1, 'ACTIVO', ?, ?, ?)
            """, (cls.tenant_alpha, h_alpha, s_alpha, cls.future_iso, cls.now_iso, cls.now_iso))

            # Usuario Alpha Miembro (COMPANY_MEMBER)
            h_alpha_m, s_alpha_m = auth_service.hash_password("MemberAlpha123!")
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES ('usr_alpha_m', ?, 'member@alpha.com', 'Miembro Alpha', ?, ?, 'COMPANY_MEMBER', 1, 'ACTIVO', ?, ?, ?)
            """, (cls.tenant_alpha, h_alpha_m, s_alpha_m, cls.future_iso, cls.now_iso, cls.now_iso))

            # Usuario Beta (COMPANY_ADMIN)
            h_beta, s_beta = auth_service.hash_password("PassBeta123!")
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES ('usr_beta', ?, 'admin@beta.com', 'Admin Beta', ?, ?, 'COMPANY_ADMIN', 1, 'ACTIVO', ?, ?, ?)
            """, (cls.tenant_beta, h_beta, s_beta, cls.future_iso, cls.now_iso, cls.now_iso))

            # Usuario Agencia Gamma (AGENCY_ADMIN)
            h_gamma, s_gamma = auth_service.hash_password("PassGamma123!")
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES ('usr_gamma', ?, 'admin@gamma.com', 'Admin Gamma', ?, ?, 'AGENCY_ADMIN', 1, 'ACTIVO', ?, ?, ?)
            """, (cls.tenant_agency, h_gamma, s_gamma, cls.future_iso, cls.now_iso, cls.now_iso))

            # 4. Leads Sintéticos
            # 2 leads en Alpha
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_alpha_1', ?, 'Directora Alpha 1', 'Directora General', 'https://linkedin.com/in/alpha1', 'd1@alpha.com', 'EXTRAIDO', ?, ?)
            """, (cls.tenant_alpha, cls.now_iso, cls.now_iso))
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_alpha_2', ?, 'Gerente Alpha 2', 'Gerente Comercial', 'https://linkedin.com/in/alpha2', 'g2@alpha.com', 'CONECTADO', ?, ?)
            """, (cls.tenant_alpha, cls.now_iso, cls.now_iso))

            # 3 leads en Beta
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_beta_1', ?, 'CEO Beta 1', 'CEO', 'https://linkedin.com/in/beta1', 'ceo@beta.com', 'EXTRAIDO', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_beta_2', ?, 'CTO Beta 2', 'CTO', 'https://linkedin.com/in/beta2', 'cto@beta.com', 'INVITACION_ENVIADA', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_beta_3', ?, 'COO Beta 3', 'COO', 'https://linkedin.com/in/beta3', 'coo@beta.com', 'CONECTADO', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))

            # 1 lead en Subordinado de Gamma
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES ('lead_sub_1', ?, 'Rector Subordinado', 'Rector', 'https://linkedin.com/in/sub1', 'rector@sub.com', 'EXTRAIDO', ?, ?)
            """, (cls.tenant_subordinate, cls.now_iso, cls.now_iso))

            # 5. Secuencias Sintéticas
            cursor.execute("""
                INSERT INTO secuencias (id, tenant_id, nombre, descripcion, activa, estado, created_at, updated_at)
                VALUES ('sec_alpha_1', ?, 'Secuencia Alpha Exclusiva', 'Campaña Colegios Alpha', 1, 'PUBLICADA', ?, ?)
            """, (cls.tenant_alpha, cls.now_iso, cls.now_iso))
            cursor.execute("""
                INSERT INTO secuencias (id, tenant_id, nombre, descripcion, activa, estado, created_at, updated_at)
                VALUES ('sec_beta_1', ?, 'Secuencia Beta Confidencial', 'Campaña Privada Beta', 1, 'PUBLICADA', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))

            # 6. Listas Sintéticas
            cursor.execute("""
                INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, termino_busqueda, estado, created_at, updated_at)
                VALUES ('list_alpha_1', ?, 'Audiencia Alpha Q4', 'Directores', 'director', 'ACTIVA', ?, ?)
            """, (cls.tenant_alpha, cls.now_iso, cls.now_iso))
            cursor.execute("""
                INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, termino_busqueda, estado, created_at, updated_at)
                VALUES ('list_beta_1', ?, 'Audiencia Beta Q4', 'CEOs', 'ceo', 'ACTIVA', ?, ?)
            """, (cls.tenant_beta, cls.now_iso, cls.now_iso))

            # 7. Actividades de Leads
            cursor.execute("""
                INSERT INTO lead_activity (id, tenant_id, lead_id, action_type, details_json, created_at)
                VALUES ('act_alpha_1', ?, 'lead_alpha_1', 'NOTE_ADDED', '{"nota": "Nota privada de Alpha"}', ?)
            """, (cls.tenant_alpha, cls.now_iso))
            cursor.execute("""
                INSERT INTO lead_activity (id, tenant_id, lead_id, action_type, details_json, created_at)
                VALUES ('act_beta_1', ?, 'lead_beta_1', 'NOTE_ADDED', '{"nota": "Nota privada de Beta"}', ?)
            """, (cls.tenant_beta, cls.now_iso))

            conn.commit()

        # Logins para tokens
        res_a = auth_service.authenticate_user("admin@alpha.com", "PassAlpha123!")
        assert res_a["exito"], f"Fallo login Alpha: {res_a}"
        cls.token_alpha = res_a["token"]

        res_a_m = auth_service.authenticate_user("member@alpha.com", "MemberAlpha123!")
        assert res_a_m["exito"], f"Fallo login Member Alpha: {res_a_m}"
        cls.token_alpha_member = res_a_m["token"]

        res_b = auth_service.authenticate_user("admin@beta.com", "PassBeta123!")
        assert res_b["exito"], f"Fallo login Beta: {res_b}"
        cls.token_beta = res_b["token"]

        res_g = auth_service.authenticate_user("admin@gamma.com", "PassGamma123!")
        assert res_g["exito"], f"Fallo login Gamma: {res_g}"
        cls.token_gamma = res_g["token"]

        res_super = auth_service.authenticate_user("admin@nexusreach.com", "admin123")
        assert res_super["exito"], f"Fallo login SuperAdmin: {res_super}"
        cls.token_super = res_super["token"]

    def setUp(self):
        os.environ["SQLITE_DB_PATH"] = TEMP_DB_PATH

    @classmethod
    def tearDownClass(cls):
        # Limpieza del directorio temporal aislado
        import shutil
        if os.path.exists(TEMP_TEST_DIR):
            try:
                shutil.rmtree(TEMP_TEST_DIR, ignore_errors=True)
            except Exception:
                pass

    # ==========================================================================
    # ESCENARIO A: SOLICITUD SIN TOKEN RECHAZADA CON 401 EN TODOS LOS ENDPOINTS AFECTADOS
    # ==========================================================================

    def test_scenario_a_unauthenticated_request_rejected_with_401(self):
        """A. Verifica que toda petición anónima (sin token) a los endpoints privados
        sea rechazada con HTTP 401, inclusive si intenta consultar un tenant_id en la URL.
        """
        endpoints_to_test = [
            ("GET", "/api/metricas"),
            ("GET", f"/api/metricas?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/prospectos"),
            ("GET", f"/api/prospectos?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/secuencias"),
            ("GET", f"/api/secuencias?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/listas"),
            ("GET", f"/api/listas?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/dashboard/metricas"),
            ("GET", f"/api/dashboard/metricas?tenant_id={self.tenant_alpha}"),
            ("GET", f"/api/tenants/{self.tenant_alpha}/export-csv"),
            ("GET", f"/api/tenants/{self.tenant_alpha}/zoho-config"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/zoho-config"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/suppression"),
            ("GET", "/api/leads/lead_alpha_1/activities"),
            ("GET", f"/api/leads/lead_alpha_1/activities?tenant_id={self.tenant_alpha}"),
            ("GET", f"/api/tenants/{self.tenant_alpha}/leads/lead_alpha_1/export-subject-data"),
            ("DELETE", f"/api/tenants/{self.tenant_alpha}/leads/lead_alpha_1/data-subject-deletion"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/purge-inactive-leads"),
            ("DELETE", f"/api/tenants/{self.tenant_alpha}/cascade-deletion"),
            ("GET", "/api/tenants"),
            ("POST", "/api/admin/cuentas"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/revocar"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/reactivar"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/puestos"),
            ("GET", f"/api/agencia/{self.tenant_agency}/clientes"),
            ("POST", f"/api/agencia/{self.tenant_agency}/clientes"),
            ("GET", f"/api/tenants/{self.tenant_alpha}/miembros"),
            ("POST", f"/api/tenants/{self.tenant_alpha}/usuarios"),
            ("PATCH", "/api/usuarios/usr_alpha_m/puesto"),
            ("GET", f"/api/agencia/{self.tenant_agency}/finanzas"),
            ("GET", "/api/auth/usuarios"),
            ("PATCH", "/api/auth/usuarios/usr_alpha/suscripcion"),
            ("POST", "/api/prospectos/importar-lote"),
            ("POST", "/api/devices/register"),
            ("POST", "/api/devices/revoke"),
            ("GET", "/api/devices/list"),
            ("GET", f"/api/devices/list?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/accounts/acc_alpha/health"),
            ("GET", f"/api/accounts/acc_alpha/health?tenant_id={self.tenant_alpha}"),
            ("POST", f"/api/accounts/acc_alpha/risk-signal?tenant_id={self.tenant_alpha}"),
            ("POST", f"/api/accounts/acc_alpha/reactivate?tenant_id={self.tenant_alpha}"),
            ("POST", "/api/selectors/publish"),
            ("GET", "/api/billing/subscription"),
            ("GET", f"/api/billing/subscription?tenant_id={self.tenant_alpha}"),
            ("POST", f"/api/billing/checkout/subscription?tenant_id={self.tenant_alpha}"),
            ("POST", f"/api/billing/checkout/pack?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/observability/metrics"),
            ("GET", f"/api/observability/metrics?tenant_id={self.tenant_alpha}"),
            ("GET", "/api/observability/team-alerts"),
            ("GET", "/api/support/diagnostics-bundle"),
            ("GET", f"/api/support/diagnostics-bundle?tenant_id={self.tenant_alpha}"),
            # Endpoints blindados en TASK-03B-C
            ("POST", "/api/extraccion/buscar"),
            ("POST", f"/api/extraccion/buscar?tenant_id={self.tenant_alpha}"),
            ("POST", "/api/extraccion/red-linkedin"),
            ("POST", f"/api/extraccion/red-linkedin?tenant_id={self.tenant_alpha}"),
            ("POST", "/api/leads/sincronizar-conexiones"),
            ("POST", f"/api/leads/sincronizar-conexiones?tenant_id={self.tenant_alpha}"),
            ("POST", "/api/secuencias/barrer-esperas"),
            ("POST", f"/api/secuencias/barrer-esperas?tenant_id={self.tenant_alpha}"),
            ("POST", "/api/leads/lead_alpha_1/reunion"),
            ("GET", "/api/prospectos/lead_alpha_1"),
            ("POST", "/api/prospectos/lead_alpha_1/seguir"),
            ("POST", "/api/prospectos/lead_alpha_1/retirar-invitacion"),
            ("POST", "/api/prospectos/lead_alpha_1/sincronizar-linkedin"),
            ("PUT", "/api/prospectos/lead_alpha_1/contacto"),
            ("POST", "/api/prospectos/lead_alpha_1/resolver-correo"),
            ("POST", "/api/leads/lead_alpha_1/resolver-correo"),
            ("POST", "/api/prospectos/lote/resolver-correo"),
            ("POST", "/api/leads/lote/resolver-correo"),
            ("POST", "/api/enrichment/test-diagnostico"),
            ("DELETE", "/api/prospectos/lead_alpha_1"),
            ("POST", "/api/prospectos/eliminar-lote"),
            ("POST", "/api/prospectos/lead_alpha_1/abrir-en-browseros"),
            ("GET", "/api/secuencias/sec_alpha_1"),
            ("PUT", "/api/secuencias/sec_alpha_1"),
            ("DELETE", "/api/secuencias/sec_alpha_1"),
            ("POST", "/api/secuencias/sec_alpha_1/pasos"),
            ("POST", "/api/secuencias/sec_alpha_1/pasos/agregar"),
            ("DELETE", "/api/secuencias/sec_alpha_1/pasos/paso_1"),
            ("POST", "/api/secuencias/sec_alpha_1/asignar-leads"),
            ("GET", "/api/secuencias/sec_alpha_1/leads"),
            ("POST", "/api/secuencias/ejecutar-siguiente"),
            ("POST", "/api/secuencias/sec_alpha_1/estado"),
            ("GET", "/api/listas/list_alpha_1"),
            ("PUT", "/api/listas/list_alpha_1"),
            ("DELETE", "/api/listas/list_alpha_1"),
            ("POST", "/api/listas/list_alpha_1/leads"),
            ("DELETE", "/api/listas/list_alpha_1/leads/lead_alpha_1"),
            ("POST", "/api/listas/list_alpha_1/conectar-secuencia"),
            ("POST", "/api/listas/list_alpha_1/desconectar-secuencia"),
            ("POST", "/api/listas/list_alpha_1/iniciar-extraccion"),
            ("POST", "/api/listas/list_alpha_1/detener-extraccion"),
            ("GET", "/api/logs"),
            ("GET", "/api/logs/stats"),
            ("DELETE", "/api/logs"),
            ("POST", "/api/seguridad/kill-switch/activar"),
            ("POST", "/api/seguridad/kill-switch/desactivar"),
            ("POST", "/api/seguridad/configuracion"),
            ("POST", "/api/linkedin/invitaciones-vencidas/retirar"),
            ("POST", "/api/selectors/canary-run"),
        ]

        dummy_json = {
            "nombre": "Test",
            "email": "test@alpha.com",
            "password": "Pass123!",
            "rol": "COMPANY_MEMBER",
            "puesto_activo": 1,
            "estado": "ACTIVO",
            "tipo_cuenta": "EMPRESA",
            "razon_social": "Test Corp",
            "admin_nombre": "Test",
            "admin_email": "t@t.com",
            "admin_password": "p",
            "delta": 1,
            "zoho_sync_activo": False,
            "identifier": "test@test.com",
            "identifier_type": "EMAIL",
            "device_id": "dev_test_1",
            "public_key_ed25519": "AAAA",
            "signal_type": "CAPTCHA",
            "version": "1.0.0",
            "catalog": {},
            "signature": "sig",
            "pack_type": "LEADS_500",
            "leads": [{"nombre": "Lead Test", "perfil_url": "https://linkedin.com/in/test"}],
            "lead_ids": ["lead_alpha_1"],
            "secuencia_id": "sec_alpha_1",
            "clave": "limite_linkedin_diario",
            "valor": "10",
        }

        for method, url in endpoints_to_test:
            with self.subTest(method=method, url=url):
                if method == "GET":
                    res = self.client.get(url)
                elif method == "POST":
                    res = self.client.post(url, json=dummy_json)
                elif method == "PUT":
                    res = self.client.put(url, json=dummy_json)
                elif method == "PATCH":
                    res = self.client.patch(url, json=dummy_json)
                elif method == "DELETE":
                    res = self.client.delete(url)
                
                self.assertEqual(
                    res.status_code, 401,
                    f"Fallo de seguridad: {method} {url} sin credenciales respondió {res.status_code} (esperaba 401)."
                )

    # ==========================================================================
    # ESCENARIO B: TOKEN INVÁLIDO O EXPIRADO RECHAZADO CON 401
    # ==========================================================================

    def test_scenario_b_invalid_or_expired_token_rejected_with_401(self):
        """B. Verifica que tokens corruptos, falsos o expirados sean rechazados con HTTP 401."""
        bad_headers = [
            {"Authorization": "Bearer token_falso_inexistente_12345"},
            {"Authorization": "Bearer "},
            {"X-Session-Token": "sesion_expirada_inventada"},
            {"Authorization": "Bearer malformed.jwt.token"},
        ]

        for h in bad_headers:
            with self.subTest(headers=h):
                res_leads = self.client.get("/api/prospectos", headers=h)
                self.assertEqual(res_leads.status_code, 401)

                res_csv = self.client.get(f"/api/tenants/{self.tenant_alpha}/export-csv", headers=h)
                self.assertEqual(res_csv.status_code, 401)

        # Probar token expirado deliberadamente en memoria
        expired_token = "tok_expired_" + os.urandom(8).hex()
        auth_service.ACTIVE_SESSIONS[expired_token] = {
            "id": "usr_exp",
            "email": "exp@alpha.com",
            "nombre": "Expirado",
            "rol": "COMPANY_ADMIN",
            "tenant_id": self.tenant_alpha,
            "expires_at": time.time() - 3600,  # Vencido hace 1 hora
            "last_db_check": time.time() - 3600
        }

        exp_headers = {"Authorization": f"Bearer {expired_token}"}
        res_exp = self.client.get("/api/prospectos", headers=exp_headers)
        self.assertEqual(res_exp.status_code, 401, "Token expirado debe ser rechazado con 401.")

    # ==========================================================================
    # ESCENARIO C: USUARIO AUTENTICADO CONSULTANDO SU PROPIO TENANT
    # ==========================================================================

    def test_scenario_c_authenticated_user_accesses_own_tenant(self):
        """C. Usuario autenticado legítimo consulta su propio tenant exitosamente."""
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # 1. Prospectos propios (debe ver exactamente los 2 de Alpha)
        res_leads = self.client.get("/api/prospectos", headers=h_alpha)
        self.assertEqual(res_leads.status_code, 200)
        data_leads = res_leads.json()
        self.assertEqual(data_leads["total"], 2)
        self.assertTrue(all(l["tenant_id"] == self.tenant_alpha for l in data_leads["leads"]))

        # 2. Métricas propias
        res_metrics = self.client.get("/api/metricas", headers=h_alpha)
        self.assertEqual(res_metrics.status_code, 200)
        data_metrics = res_metrics.json()
        self.assertEqual(data_metrics["total_leads"], 2)

        # 3. Secuencias propias
        res_sec = self.client.get("/api/secuencias", headers=h_alpha)
        self.assertEqual(res_sec.status_code, 200)
        seqs = res_sec.json().get("secuencias", [])
        self.assertEqual(len(seqs), 1)
        self.assertEqual(seqs[0]["tenant_id"], self.tenant_alpha)

        # 4. Listas propias
        res_lists = self.client.get("/api/listas", headers=h_alpha)
        self.assertEqual(res_lists.status_code, 200)
        lists = res_lists.json().get("listas", [])
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]["tenant_id"], self.tenant_alpha)

        # 5. Exportación CSV de su propio tenant
        res_csv = self.client.get(f"/api/tenants/{self.tenant_alpha}/export-csv", headers=h_alpha)
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn("text/csv", res_csv.headers.get("content-type", ""))
        self.assertIn("Directora Alpha 1", res_csv.text)

    # ==========================================================================
    # ESCENARIO D: USUARIO DEL TENANT A INTENTANDO CONSULTAR TENANT B (RECHAZADO 403)
    # ==========================================================================

    def test_scenario_d_user_a_cannot_read_tenant_b_data(self):
        """D. Usuario de Alpha intentando acceder a datos de Beta recibe HTTP 403."""
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # Intento de filtrar prospectos de Beta
        res_leads = self.client.get(f"/api/prospectos?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_leads.status_code, 403, "Usuario de Alpha debe recibir 403 al consultar leads de Beta.")

        # Intento de consultar métricas de Beta
        res_metrics = self.client.get(f"/api/metricas?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_metrics.status_code, 403, "Usuario de Alpha debe recibir 403 al consultar métricas de Beta.")

        # Intento de consultar secuencias de Beta
        res_sec = self.client.get(f"/api/secuencias?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_sec.status_code, 403, "Usuario de Alpha debe recibir 403 al consultar secuencias de Beta.")

        # Intento de consultar listas de Beta
        res_lists = self.client.get(f"/api/listas?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_lists.status_code, 403, "Usuario de Alpha debe recibir 403 al consultar listas de Beta.")

        # Intento de consultar dashboard de Beta
        res_dash = self.client.get(f"/api/dashboard/metricas?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_dash.status_code, 403, "Usuario de Alpha debe recibir 403 al consultar dashboard de Beta.")

        # Intento de consultar configuración Zoho de Beta
        res_zoho = self.client.get(f"/api/tenants/{self.tenant_beta}/zoho-config", headers=h_alpha)
        self.assertEqual(res_zoho.status_code, 403)

        # Intento de modificar configuración Zoho de Beta
        res_up_zoho = self.client.post(
            f"/api/tenants/{self.tenant_beta}/zoho-config",
            json={"zoho_sync_activo": True, "zoho_org_id": "malicious_org"},
            headers=h_alpha
        )
        self.assertEqual(res_up_zoho.status_code, 403)

        # Intento de agregar a lista de supresión de Beta
        res_supp = self.client.post(
            f"/api/tenants/{self.tenant_beta}/suppression",
            json={"identifier": "victim@beta.com", "identifier_type": "EMAIL"},
            headers=h_alpha
        )
        self.assertEqual(res_supp.status_code, 403)

        # Intento de consultar actividades de lead de Beta
        res_act = self.client.get(f"/api/leads/lead_beta_1/activities?tenant_id={self.tenant_beta}", headers=h_alpha)
        self.assertEqual(res_act.status_code, 403)

        # Intento de consultar dispositivos, salud de cuenta, facturación, observabilidad y soporte de Beta
        for cross_url in [
            f"/api/devices/list?tenant_id={self.tenant_beta}",
            f"/api/accounts/acc_beta/health?tenant_id={self.tenant_beta}",
            f"/api/billing/subscription?tenant_id={self.tenant_beta}",
            f"/api/observability/metrics?tenant_id={self.tenant_beta}",
            f"/api/support/diagnostics-bundle?tenant_id={self.tenant_beta}",
        ]:
            with self.subTest(cross_url=cross_url):
                res_cross = self.client.get(cross_url, headers=h_alpha)
                self.assertEqual(res_cross.status_code, 403)

        # Intento de importar leads en el tenant Beta desde usuario Alpha
        res_imp = self.client.post(
            "/api/prospectos/importar-lote",
            json={"tenant_id": self.tenant_beta, "leads": [{"nombre": "Intruso", "perfil_url": "https://linkedin.com/in/intruso"}]},
            headers=h_alpha
        )
        self.assertEqual(res_imp.status_code, 403)

    # ==========================================================================
    # ESCENARIO E: USUARIO DEL TENANT A INTENTANDO EXPORTAR TENANT B (RECHAZADO 403)
    # ==========================================================================

    def test_scenario_e_user_a_cannot_export_tenant_b_data(self):
        """E. Usuario de Alpha intentando exportar CSV o datos ARCO de Beta recibe HTTP 403."""
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # 1. Exportación masiva CSV de Beta
        res_csv = self.client.get(f"/api/tenants/{self.tenant_beta}/export-csv", headers=h_alpha)
        self.assertEqual(res_csv.status_code, 403, "Debe rechazar exportación CSV ajena con 403 Forbidden.")

        # 2. Exportación de perfil de titular de datos (ARCO) de un lead de Beta
        res_arco = self.client.get(
            f"/api/tenants/{self.tenant_beta}/leads/lead_beta_1/export-subject-data",
            headers=h_alpha
        )
        self.assertEqual(res_arco.status_code, 403, "Debe rechazar exportación ARCO ajena con 403 Forbidden.")

        # 3. Supresión definitiva de datos (Derecho al Olvido) en Beta
        res_del = self.client.delete(
            f"/api/tenants/{self.tenant_beta}/leads/lead_beta_1/data-subject-deletion",
            headers=h_alpha
        )
        self.assertEqual(res_del.status_code, 403, "Debe rechazar borrado ARCO ajeno con 403 Forbidden.")

    # ==========================================================================
    # ESCENARIO F: PARÁMETRO TENANT_ID MANIPULADO EN URL
    # ==========================================================================

    def test_scenario_f_tampered_tenant_id_fails_closed(self):
        """F. Parámetros tenant_id manipulados, inexistentes o con inyección SQL son rechazados con 403."""
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        tampered_tenants = [
            "ten_superadmin",
            "tenant_inexistente_999",
            "' OR '1'='1",
            "ten_corp_alpha; DROP TABLE leads;--",
            "../etc/passwd",
            "ten_agency_gamma"
        ]

        for tampered in tampered_tenants:
            with self.subTest(tampered=tampered):
                res = self.client.get(f"/api/prospectos?tenant_id={tampered}", headers=h_alpha)
                self.assertEqual(res.status_code, 403, f"Parámetro manipulado '{tampered}' debió retornar 403.")

        # Intentar crear secuencia inyectando tenant_id de otro tenant en el body
        res_sec = self.client.post(
            "/api/secuencias",
            json={"nombre": "Ataque Cross-Tenant", "tenant_id": self.tenant_beta},
            headers=h_alpha
        )
        self.assertEqual(res_sec.status_code, 403, "No se debe permitir crear secuencias en tenant ajeno.")

        # Intentar crear lista inyectando tenant_id de otro tenant en el body
        res_list = self.client.post(
            "/api/listas",
            json={"nombre": "Lista Cross-Tenant", "tenant_id": self.tenant_beta},
            headers=h_alpha
        )
        self.assertEqual(res_list.status_code, 403, "No se debe permitir crear listas en tenant ajeno.")

    # ==========================================================================
    # ESCENARIO G: PRIVILEGIOS ADMINISTRATIVOS LEGÍTIMOS
    # ==========================================================================

    def test_scenario_g_administrative_privileges_enforced_strictly(self):
        """G. Super Admin y Agency Admin conservan únicamente los privilegios correspondientes."""
        h_super = {"Authorization": f"Bearer {self.token_super}"}
        h_gamma = {"Authorization": f"Bearer {self.token_gamma}"}
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # 1. Super Admin puede auditar tenant Alpha legítimamente
        res_s_alpha = self.client.get(f"/api/prospectos?tenant_id={self.tenant_alpha}", headers=h_super)
        self.assertEqual(res_s_alpha.status_code, 200)
        self.assertEqual(res_s_alpha.json()["total"], 2)

        # 2. Super Admin puede consultar el directorio global de tenants
        res_s_tenants = self.client.get("/api/tenants", headers=h_super)
        self.assertEqual(res_s_tenants.status_code, 200)

        # 3. Agency Admin puede consultar su propia cartera y sus subtenants autorizados
        res_g_sub = self.client.get(f"/api/prospectos?tenant_id={self.tenant_subordinate}", headers=h_gamma)
        self.assertEqual(res_g_sub.status_code, 200, "Agency Admin debe tener acceso a clientes de su cartera.")
        self.assertEqual(res_g_sub.json()["total"], 1)

        # 4. Agency Admin NO puede consultar tenants fuera de su cartera (Beta)
        res_g_beta = self.client.get(f"/api/prospectos?tenant_id={self.tenant_beta}", headers=h_gamma)
        self.assertEqual(res_g_beta.status_code, 403, "Agency Admin no debe tener acceso a tenants ajenos.")

        # 5. Company Admin NO puede acceder a endpoints reservados a Super Admin (403)
        res_a_tenants = self.client.get("/api/tenants", headers=h_alpha)
        self.assertEqual(res_a_tenants.status_code, 403)

        res_a_finances = self.client.get(f"/api/agencia/{self.tenant_agency}/finanzas", headers=h_alpha)
        self.assertEqual(res_a_finances.status_code, 403)

    # ==========================================================================
    # ESCENARIO H: NO FILTRACIÓN INDIRECTA DE MÉTRICAS, LISTAS O SECUENCIAS
    # ==========================================================================

    def test_scenario_h_no_indirect_leakage_in_metrics_lists_sequences(self):
        """H. Verifica que consultas agregadas no sumen ni filtren información de otros tenants."""
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}
        h_beta = {"Authorization": f"Bearer {self.token_beta}"}

        # Métricas de Alpha deben contar exactamente 2 leads (no los 3 de Beta ni el 1 de Gamma)
        res_m_a = self.client.get("/api/metricas", headers=h_alpha)
        self.assertEqual(res_m_a.status_code, 200)
        self.assertEqual(res_m_a.json()["total_leads"], 2)

        # Métricas de Beta deben contar exactamente 3 leads
        res_m_b = self.client.get("/api/metricas", headers=h_beta)
        self.assertEqual(res_m_b.status_code, 200)
        self.assertEqual(res_m_b.json()["total_leads"], 3)

        # Secuencias de Alpha: solo debe figurar la secuencia de Alpha
        res_s_a = self.client.get("/api/secuencias", headers=h_alpha)
        seqs_a = res_s_a.json().get("secuencias", [])
        self.assertEqual(len(seqs_a), 1)
        self.assertEqual(seqs_a[0]["id"], "sec_alpha_1")
        self.assertNotIn("sec_beta_1", [s["id"] for s in seqs_a])

        # Listas de Alpha: solo debe figurar la lista de Alpha
        res_l_a = self.client.get("/api/listas", headers=h_alpha)
        lists_a = res_l_a.json().get("listas", [])
        self.assertEqual(len(lists_a), 1)
        self.assertEqual(lists_a[0]["id"], "list_alpha_1")
        self.assertNotIn("list_beta_1", [l["id"] for l in lists_a])

        # Filtrar prospectos de Alpha pasando un lista_id o secuencia_id de Beta no debe filtrar nada
        res_cross_list = self.client.get("/api/prospectos?lista_id=list_beta_1", headers=h_alpha)
        self.assertEqual(res_cross_list.status_code, 200)
        self.assertEqual(res_cross_list.json()["total"], 0)

        res_cross_sec = self.client.get("/api/prospectos?secuencia_id=sec_beta_1", headers=h_alpha)
        self.assertEqual(res_cross_sec.status_code, 200)
        self.assertEqual(res_cross_sec.json()["total"], 0)

    # ==========================================================================
    # ESCENARIO I: AUDITORÍA DIRECTA DE _resolve_permitted_tenants (FAIL-CLOSED)
    # ==========================================================================

    def test_scenario_i_resolve_permitted_tenants_unit_fail_closed(self):
        """I. Prueba unitaria exhaustiva sobre _resolve_permitted_tenants garantizando
        que entradas nulas, incompletas o fraudulentas fallen de forma segura.
        """
        # 1. Caller es None
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants(None, "ten_corp_alpha")
        self.assertEqual(cm.exception.status_code, 401)

        # 2. Caller es diccionario vacío
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({}, "ten_corp_alpha")
        self.assertEqual(cm.exception.status_code, 401)

        # 3. Caller sin rol
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"id": "usr_1", "tenant_id": "ten_a"}, "ten_a")
        self.assertEqual(cm.exception.status_code, 401)

        # 3b. Caller sin id (identidad incompleta)
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"rol": "COMPANY_ADMIN", "tenant_id": "ten_a"}, "ten_a")
        self.assertEqual(cm.exception.status_code, 401)

        # 4. Caller sin tenant_id ni es superadmin
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"id": "usr_1", "rol": "COMPANY_MEMBER"}, "ten_a")
        self.assertEqual(cm.exception.status_code, 403)

        # 5. Caller con tenant_id vacío
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"id": "usr_1", "rol": "COMPANY_MEMBER", "tenant_id": "   "}, "ten_a")
        self.assertEqual(cm.exception.status_code, 403)

        # 6. Rol no reconocido (incluso consultando su propio tenant_id) -> 403 Fail-Closed
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"id": "usr_1", "rol": "ROL_EXTERNO", "tenant_id": "ten_a"}, "ten_a")
        self.assertEqual(cm.exception.status_code, 403)

        # 6b. Super Admin sin tenant_id y sin tenant_query -> 403 (sin fallback permisivo)
        with self.assertRaises(HTTPException) as cm:
            _resolve_permitted_tenants({"id": "usr_s", "rol": "SUPER_ADMIN"})
        self.assertEqual(cm.exception.status_code, 403)

        # 7. Super Admin con su propio tenant_id asignado y sin tenant_query -> retorna su propio ['ten_superadmin']
        res_super_default = _resolve_permitted_tenants({"id": "usr_s", "rol": "SUPER_ADMIN", "tenant_id": "ten_superadmin"})
        self.assertEqual(res_super_default, ["ten_superadmin"])

        # 8. Super Admin con tenant_query explícito -> retorna [tenant_query]
        res_super_explicit = _resolve_permitted_tenants({"id": "usr_s", "rol": "SUPER_ADMIN"}, "ten_cualquiera")
        self.assertEqual(res_super_explicit, ["ten_cualquiera"])

        # 9. Company Member consultando su propio tenant explícito -> retorna [caller_tenant]
        res_member_own = _resolve_permitted_tenants({"id": "usr_m", "rol": "COMPANY_MEMBER", "tenant_id": "ten_a"}, "ten_a")
        self.assertEqual(res_member_own, ["ten_a"])

        # 10. Company Member consultando su propio tenant con espacios -> se sanea y retorna [caller_tenant]
        res_member_whitespace = _resolve_permitted_tenants({"id": "usr_m", "rol": "COMPANY_MEMBER", "tenant_id": "ten_a"}, "  ten_a  ")
        self.assertEqual(res_member_whitespace, ["ten_a"])

    # ==========================================================================
    # ESCENARIOS TASK-03B-C: CIERRE DE BRECHAS REST Y VALIDACIÓN DE NO MUTACIÓN
    # ==========================================================================

    def test_task03bc_1_toggle_seat_sql_fix_and_rbac(self):
        """TASK-03B-C (1): Verifica la corrección SQL en PATCH /api/usuarios/{user_id}/puesto (tabla usuarios),
        éxito autenticado para administrador propio, rechazo 403 para COMPANY_MEMBER,
        rechazo 403 cross-tenant y 404 para ID inexistente sin alterar la base de datos.
        """
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}
        h_alpha_member = {"Authorization": f"Bearer {self.token_alpha_member}"}
        h_beta = {"Authorization": f"Bearer {self.token_beta}"}

        # 1. COMPANY_MEMBER no puede modificar puestos -> 403
        res_mem = self.client.patch(
            "/api/usuarios/usr_alpha_m/puesto",
            json={"puesto_activo": 0},
            headers=h_alpha_member
        )
        self.assertEqual(res_mem.status_code, 403)

        # 2. COMPANY_ADMIN de Beta no puede modificar puestos de Alpha -> 403
        res_cross = self.client.patch(
            "/api/usuarios/usr_alpha_m/puesto",
            json={"puesto_activo": 0},
            headers=h_beta
        )
        self.assertEqual(res_cross.status_code, 403)

        # Verificar que puesto_activo sigue en 1 tras los intentos no autorizados
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT puesto_activo FROM usuarios WHERE id = 'usr_alpha_m'")
            self.assertEqual(cur.fetchone()["puesto_activo"], 1)

        # 3. Usuario inexistente -> 404
        res_404 = self.client.patch(
            "/api/usuarios/usr_inexistente_999/puesto",
            json={"puesto_activo": 0},
            headers=h_alpha
        )
        self.assertEqual(res_404.status_code, 404)

        # 4. COMPANY_ADMIN de Alpha desactiva y reactiva el puesto de su miembro -> 200 OK
        res_off = self.client.patch(
            "/api/usuarios/usr_alpha_m/puesto",
            json={"puesto_activo": 0},
            headers=h_alpha
        )
        self.assertEqual(res_off.status_code, 200)
        self.assertTrue(res_off.json().get("exito"))
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT puesto_activo FROM usuarios WHERE id = 'usr_alpha_m'")
            self.assertEqual(cur.fetchone()["puesto_activo"], 0)

        res_on = self.client.patch(
            "/api/usuarios/usr_alpha_m/puesto",
            json={"puesto_activo": 1},
            headers=h_alpha
        )
        self.assertEqual(res_on.status_code, 200)
        self.assertTrue(res_on.json().get("exito"))

        # Re-autenticar a usr_alpha_m ya que desactivar el puesto expulsa su sesión en memoria
        relogin = auth_service.authenticate_user("member@alpha.com", "MemberAlpha123!")
        self.assertTrue(relogin["exito"])
        TestAuthAndTenantIsolationTask03B.token_alpha_member = relogin["token"]

    def test_task03bc_2_extraction_endpoints_auth_and_tenant_resolution(self):
        """TASK-03B-C (2): Verifica POST /api/extraccion/buscar y POST /api/extraccion/red-linkedin:
        autenticación obligatoria, resolución de tenant sin fallback a ten_superadmin,
        restricción de AGENCY_ADMIN a su cartera y validación de lista_id.
        """
        from unittest.mock import patch
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}
        h_gamma = {"Authorization": f"Bearer {self.token_gamma}"}

        with patch("extractor_engine.search_and_extract_leads", return_value={"status": "ok", "extraidos": 0}) as mock_search, \
             patch("extractor_engine.extract_network_leads", return_value={"status": "ok", "extraidos": 0}) as mock_net:

            # 1. COMPANY_ADMIN Alpha extrae para su propio tenant (sin pasar tenant_id) -> usa ten_corp_alpha, nunca ten_superadmin
            res_own = self.client.post("/api/extraccion/buscar?termino=Director", headers=h_alpha)
            self.assertEqual(res_own.status_code, 200)
            mock_search.assert_called_once_with(
                "Director", page=1, auto_save=True, list_id=None, tenant_id=self.tenant_alpha
            )
            mock_search.reset_mock()

            # 2. COMPANY_ADMIN Alpha intenta pasar tenant_id=Beta -> 403 y no ejecuta extracción
            res_cross_t = self.client.post(f"/api/extraccion/buscar?tenant_id={self.tenant_beta}", headers=h_alpha)
            self.assertEqual(res_cross_t.status_code, 403)
            mock_search.assert_not_called()

            # 3. COMPANY_ADMIN Alpha intenta pasar lista_id de Beta -> 403 y no ejecuta extracción
            res_cross_l = self.client.post("/api/extraccion/buscar?lista_id=list_beta_1", headers=h_alpha)
            self.assertEqual(res_cross_l.status_code, 403)
            mock_search.assert_not_called()

            # 4. COMPANY_ADMIN Alpha pasa lista_id inexistente -> 404
            res_404_l = self.client.post("/api/extraccion/buscar?lista_id=list_inexistente_999", headers=h_alpha)
            self.assertEqual(res_404_l.status_code, 404)
            mock_search.assert_not_called()

            # 5. AGENCY_ADMIN Gamma intenta extraer para tenant ajeno fuera de su cartera (Beta) -> 403
            res_gamma_forb = self.client.post(f"/api/extraccion/buscar?tenant_id={self.tenant_beta}", headers=h_gamma)
            self.assertEqual(res_gamma_forb.status_code, 403)
            res_gamma_net_forb = self.client.post(f"/api/extraccion/red-linkedin?tenant_id={self.tenant_beta}", headers=h_gamma)
            self.assertEqual(res_gamma_net_forb.status_code, 403)
            mock_search.assert_not_called()
            mock_net.assert_not_called()

            # 6. AGENCY_ADMIN Gamma extrae para su subtenant autorizado -> 200 con tenant_subordinate
            res_gamma_sub = self.client.post(
                f"/api/extraccion/red-linkedin?origen=connections&limite=25&tenant_id={self.tenant_subordinate}",
                headers=h_gamma
            )
            self.assertEqual(res_gamma_sub.status_code, 200)
            mock_net.assert_called_once_with(
                source="connections", limit=25, tenant_id=self.tenant_subordinate
            )

    def test_task03bc_3_sync_connections_and_sweep_delays(self):
        """TASK-03B-C (3): Verifica POST /api/leads/sincronizar-conexiones y POST /api/secuencias/barrer-esperas:
        exigen autenticación y autorización efectiva del tenant.
        """
        from unittest.mock import patch
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        with patch("connection_sync_service.start_periodic_connection_sync"), \
             patch("connection_sync_service.sync_accepted_connections", return_value={"status": "ok", "sincronizados": 1}) as mock_sync:
            # Intento cross-tenant -> 403
            res_forb = self.client.post(f"/api/leads/sincronizar-conexiones?tenant_id={self.tenant_beta}", headers=h_alpha)
            self.assertEqual(res_forb.status_code, 403)
            mock_sync.assert_not_called()

            # Propio tenant -> 200 y pasa tenant_id=ten_corp_alpha
            res_ok = self.client.post("/api/leads/sincronizar-conexiones", headers=h_alpha)
            self.assertEqual(res_ok.status_code, 200)
            mock_sync.assert_called_once_with(tenant_id=self.tenant_alpha, force_outside_hours=True)

        with patch("sequence_engine.promote_expired_delays", return_value=2) as mock_sweep:
            # Intento cross-tenant -> 403
            res_sweep_forb = self.client.post(f"/api/secuencias/barrer-esperas?tenant_id={self.tenant_beta}", headers=h_alpha)
            self.assertEqual(res_sweep_forb.status_code, 403)
            mock_sweep.assert_not_called()

            # Propio tenant -> 200 y pasa tenant_id=ten_corp_alpha
            res_sweep_ok = self.client.post("/api/secuencias/barrer-esperas", headers=h_alpha)
            self.assertEqual(res_sweep_ok.status_code, 200)
            self.assertEqual(res_sweep_ok.json().get("promovidos"), 2)
            mock_sweep.assert_called_once_with(tenant_id=self.tenant_alpha)

    def test_task03bc_4a_prospects_by_id_and_batch_isolation_and_no_db_mutation(self):
        """TASK-03B-C (4A): Verifica protección de /api/prospectos/{lead_id}*, operaciones por lote
        e importación con listas; demuestra que intentos no autorizados no modifican la base de datos.
        """
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # 1. Lectura o mutación sobre lead de otro tenant (lead_beta_1) -> 403
        self.assertEqual(self.client.get("/api/prospectos/lead_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.get("/api/leads/lead_beta_1/activities", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/leads/lead_beta_1/reunion", json={"valor_reunion": 500}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/prospectos/lead_beta_1/seguir?seguir=true", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/prospectos/lead_beta_1/retirar-invitacion", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/prospectos/lead_beta_1/sincronizar-linkedin", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.put("/api/prospectos/lead_beta_1/contacto?email=hacked@evil.com&telefono=999", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/prospectos/lead_beta_1/resolver-correo", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.delete("/api/prospectos/lead_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/prospectos/lead_beta_1/abrir-en-browseros", headers=h_alpha).status_code, 403)

        # 2. Operación por lote mezclando ID propio y ID de otro tenant -> 403 atómico
        res_batch_del = self.client.post(
            "/api/prospectos/eliminar-lote",
            json={"lead_ids": ["lead_alpha_1", "lead_beta_1"]},
            headers=h_alpha
        )
        self.assertEqual(res_batch_del.status_code, 403)

        res_batch_email = self.client.post(
            "/api/prospectos/lote/resolver-correo",
            json={"lead_ids": ["lead_alpha_1", "lead_beta_1"]},
            headers=h_alpha
        )
        self.assertEqual(res_batch_email.status_code, 403)

        # 3. Operación con IDs inexistentes -> 404 (y lote con ID inexistente no muta los válidos)
        self.assertEqual(self.client.get("/api/prospectos/lead_inexistente_999", headers=h_alpha).status_code, 404)
        self.assertEqual(self.client.delete("/api/prospectos/lead_inexistente_999", headers=h_alpha).status_code, 404)
        self.assertEqual(self.client.get("/api/leads/lead_inexistente_999/activities", headers=h_alpha).status_code, 404)
        res_batch_404 = self.client.post(
            "/api/prospectos/eliminar-lote",
            json={"lead_ids": ["lead_alpha_1", "lead_inexistente_999"]},
            headers=h_alpha
        )
        self.assertEqual(res_batch_404.status_code, 404)

        # 4. Importar lote vinculando lista de otro tenant -> 403
        res_imp_cross_list = self.client.post(
            "/api/prospectos/importar-lote",
            json={
                "lista_id": "list_beta_1",
                "leads": [{"nombre": "Nuevo Lead", "perfil_url": "https://linkedin.com/in/nuevo-lead-test"}]
            },
            headers=h_alpha
        )
        self.assertEqual(res_imp_cross_list.status_code, 403)

        # Verificar que ni lead_beta_1 ni lead_alpha_1 sufrieron modificaciones o borrados en la BD
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT email, estado, siguiendo, invitacion_retirada, valor_reunion FROM leads WHERE id = 'lead_beta_1'")
            b1 = cur.fetchone()
            self.assertIsNotNone(b1, "lead_beta_1 no debe haber sido eliminado.")
            self.assertEqual(b1["email"], "ceo@beta.com")
            self.assertEqual(b1["estado"], "EXTRAIDO")
            self.assertEqual(b1["siguiendo"] or 0, 0)
            self.assertEqual(b1["invitacion_retirada"] or 0, 0)
            self.assertEqual(b1["valor_reunion"] or 0, 0)

            cur.execute("SELECT id FROM leads WHERE id = 'lead_alpha_1'")
            self.assertIsNotNone(cur.fetchone(), "lead_alpha_1 no debe haber sido eliminado por un lote fallido.")

        # 5. Caso válido sobre recurso propio -> 200 OK
        res_own_detail = self.client.get("/api/prospectos/lead_alpha_1", headers=h_alpha)
        self.assertEqual(res_own_detail.status_code, 200)
        self.assertEqual(res_own_detail.json()["id"], "lead_alpha_1")

    def test_task03bc_4b_sequences_by_id_indirect_relations_and_no_global_leakage(self):
        """TASK-03B-C (4B): Verifica protección de /api/secuencias/{secuencia_id}*, relaciones indirectas
        en asignar-leads y ausencia de filtrado global accidental cuando lead_ids está vacío.
        """
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}

        # 1. Acceso cross-tenant a secuencia de Beta (sec_beta_1) -> 403
        self.assertEqual(self.client.get("/api/secuencias/sec_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.put("/api/secuencias/sec_beta_1", json={"nombre": "Sabotaje"}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.delete("/api/secuencias/sec_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/secuencias/sec_beta_1/pasos", json={"pasos": []}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/secuencias/sec_beta_1/pasos/agregar", json={"tipo_accion": "VISITAR_PERFIL"}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.delete("/api/secuencias/sec_beta_1/pasos/paso_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/secuencias/sec_beta_1/asignar-leads", json={"lead_ids": ["lead_beta_1"]}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.get("/api/secuencias/sec_beta_1/leads", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/secuencias/ejecutar-siguiente?secuencia_id=sec_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/secuencias/sec_beta_1/estado", json={"estado": "PAUSADA"}, headers=h_alpha).status_code, 403)

        # Verificar que sec_beta_1 sigue intacta en la BD
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, estado, activa FROM secuencias WHERE id = 'sec_beta_1'")
            sb = cur.fetchone()
            self.assertIsNotNone(sb)
            self.assertEqual(sb["nombre"], "Secuencia Beta Confidencial")
            self.assertEqual(sb["estado"], "PUBLICADA")

        # 2. IDs inexistentes -> 404
        self.assertEqual(self.client.get("/api/secuencias/sec_inexistente_999", headers=h_alpha).status_code, 404)
        self.assertEqual(self.client.delete("/api/secuencias/sec_inexistente_999", headers=h_alpha).status_code, 404)

        # 3. Relación indirecta: asignar lead de Beta a secuencia propia de Alpha -> 403 sin cambios en BD
        res_save_step = self.client.post(
            "/api/secuencias/sec_alpha_1/pasos",
            json={"pasos": [{"id": "paso_alpha_root", "tipo_accion": "VISITAR_PERFIL", "orden": 1, "condicion_rama": "RAIZ"}]},
            headers=h_alpha
        )
        self.assertEqual(res_save_step.status_code, 200)

        res_assign_mixed = self.client.post(
            "/api/secuencias/sec_alpha_1/asignar-leads",
            json={"lead_ids": ["lead_alpha_1", "lead_beta_1"]},
            headers=h_alpha
        )
        self.assertEqual(res_assign_mixed.status_code, 403)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as total FROM leads_en_secuencia WHERE secuencia_id = 'sec_alpha_1'")
            self.assertEqual(cur.fetchone()["total"], 0, "Un lote rechazado no debe inscribir ningún lead.")

        # 4. Ausencia de filtrado global accidental: asignar-leads con lead_ids=[] solo inscribe leads EXTRAIDO de Alpha
        res_assign_empty = self.client.post(
            "/api/secuencias/sec_alpha_1/asignar-leads",
            json={"lead_ids": []},
            headers=h_alpha
        )
        self.assertEqual(res_assign_empty.status_code, 200)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT lead_id FROM leads_en_secuencia WHERE secuencia_id = 'sec_alpha_1'")
            enrolled = [r["lead_id"] for r in cur.fetchall()]
            self.assertEqual(enrolled, ["lead_alpha_1"])
            self.assertNotIn("lead_beta_1", enrolled)
            self.assertNotIn("lead_sub_1", enrolled)

    def test_task03bc_4c_lists_by_id_and_cross_tenant_sequence_linking(self):
        """TASK-03B-C (4C): Verifica protección de /api/listas/{lista_id}*, asociación de leads por lote
        y vinculación lista-secuencia validando que ambos recursos pertenezcan al mismo tenant.
        """
        h_alpha = {"Authorization": f"Bearer {self.token_alpha}"}
        h_super = {"Authorization": f"Bearer {self.token_super}"}

        # 1. Operaciones sobre lista de otro tenant (list_beta_1) -> 403
        self.assertEqual(self.client.get("/api/listas/list_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.put("/api/listas/list_beta_1", json={"nombre": "Hack"}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.delete("/api/listas/list_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/listas/list_beta_1/leads", json={"lead_ids": ["lead_beta_1"]}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.delete("/api/listas/list_beta_1/leads/lead_beta_1", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/listas/list_beta_1/conectar-secuencia", json={"secuencia_id": "sec_beta_1"}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/listas/list_beta_1/desconectar-secuencia", json={"secuencia_id": "sec_beta_1"}, headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/listas/list_beta_1/iniciar-extraccion", headers=h_alpha).status_code, 403)
        self.assertEqual(self.client.post("/api/listas/list_beta_1/detener-extraccion", headers=h_alpha).status_code, 403)

        # Verificar que list_beta_1 no fue alterada ni eliminada
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre FROM listas_leads WHERE id = 'list_beta_1'")
            lb = cur.fetchone()
            self.assertIsNotNone(lb)
            self.assertEqual(lb["nombre"], "Audiencia Beta Q4")

        # 2. IDs inexistentes -> 404
        self.assertEqual(self.client.get("/api/listas/list_inexistente_999", headers=h_alpha).status_code, 404)
        self.assertEqual(self.client.delete("/api/listas/list_inexistente_999", headers=h_alpha).status_code, 404)

        # 3. Agregar lote con leads de distintos tenants a list_alpha_1 -> 403 sin cambios en BD
        res_add_mixed = self.client.post(
            "/api/listas/list_alpha_1/leads",
            json={"lead_ids": ["lead_alpha_1", "lead_beta_1"]},
            headers=h_alpha
        )
        self.assertEqual(res_add_mixed.status_code, 403)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as total FROM leads_en_lista WHERE lista_id = 'list_alpha_1'")
            self.assertEqual(cur.fetchone()["total"], 0)

        # 4. Intentar conectar lista de Alpha con secuencia de Beta -> 403 (incluso para SUPER_ADMIN por incompatibilidad de workspace)
        res_conn_cross = self.client.post(
            "/api/listas/list_alpha_1/conectar-secuencia",
            json={"secuencia_id": "sec_beta_1"},
            headers=h_alpha
        )
        self.assertEqual(res_conn_cross.status_code, 403)
        res_conn_super_mismatch = self.client.post(
            "/api/listas/list_alpha_1/conectar-secuencia",
            json={"secuencia_id": "sec_beta_1"},
            headers=h_super
        )
        self.assertEqual(res_conn_super_mismatch.status_code, 403)

        # 5. Caso válido: agregar lead_alpha_1 a list_alpha_1 y consultar detalle -> 200 OK
        res_add_ok = self.client.post(
            "/api/listas/list_alpha_1/leads",
            json={"lead_ids": ["lead_alpha_1"]},
            headers=h_alpha
        )
        self.assertEqual(res_add_ok.status_code, 200)
        res_list_ok = self.client.get("/api/listas/list_alpha_1", headers=h_alpha)
        self.assertEqual(res_list_ok.status_code, 200)

    def test_task03bc_5_global_and_administrative_endpoints_rbac(self):
        """TASK-03B-C (5): Verifica distinción estricta entre COMPANY_MEMBER, COMPANY_ADMIN,
        AGENCY_ADMIN y SUPER_ADMIN en operaciones administrativas y globales
        (/api/logs*, /api/seguridad/kill-switch/*, /api/seguridad/configuracion, /api/selectors/canary-run, etc.).
        """
        from unittest.mock import patch
        h_member = {"Authorization": f"Bearer {self.token_alpha_member}"}
        h_alpha_admin = {"Authorization": f"Bearer {self.token_alpha}"}
        h_super = {"Authorization": f"Bearer {self.token_super}"}

        # Sembrar logs sintéticos para Alpha y Beta y una invitación vencida en Beta
        old_invite_iso = "2020-01-01T00:00:00"
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_logs (timestamp, level, module, message, details_json, lead_id)
                VALUES (?, 'INFO', 'SEQUENCES', 'Evento Alpha', '{}', 'lead_alpha_1')
            """, (self.now_iso,))
            cur.execute("""
                INSERT INTO system_logs (timestamp, level, module, message, details_json, lead_id)
                VALUES (?, 'ERROR', 'SEQUENCES', 'Evento Confidencial Beta', '{}', 'lead_beta_1')
            """, (self.now_iso,))
            cur.execute("""
                UPDATE leads SET fecha_invitacion = ?, invitacion_retirada = 0
                WHERE id = 'lead_beta_2'
            """, (old_invite_iso,))
            conn.commit()

        # 1. COMPANY_MEMBER es rechazado con 403 en todas las operaciones administrativas y globales
        member_forbidden = [
            ("GET", "/api/logs", None),
            ("GET", "/api/logs/stats", None),
            ("DELETE", "/api/logs", None),
            ("POST", "/api/seguridad/kill-switch/activar", None),
            ("POST", "/api/seguridad/kill-switch/desactivar", None),
            ("POST", "/api/seguridad/configuracion", {"clave": "limite_linkedin_diario", "valor": "9"}),
            ("POST", "/api/linkedin/invitaciones-vencidas/retirar", None),
            ("POST", "/api/selectors/canary-run", None),
            ("POST", f"/api/tenants/{self.tenant_alpha}/puestos", {"delta": 1}),
            ("POST", f"/api/tenants/{self.tenant_alpha}/zoho-config", {"zoho_sync_activo": True}),
            ("POST", f"/api/tenants/{self.tenant_alpha}/purge-inactive-leads", None),
            ("POST", "/api/devices/revoke", {"device_id": "dev_1"}),
            ("POST", "/api/accounts/acc_alpha/reactivate", None),
        ]
        for method, url, payload in member_forbidden:
            with self.subTest(role="COMPANY_MEMBER", method=method, url=url):
                if method == "GET":
                    res = self.client.get(url, headers=h_member)
                elif method == "POST":
                    res = self.client.post(url, json=payload, headers=h_member)
                elif method == "DELETE":
                    res = self.client.delete(url, headers=h_member)
                self.assertEqual(res.status_code, 403, f"COMPANY_MEMBER debió recibir 403 en {method} {url}")

        # 2. COMPANY_ADMIN puede consultar /api/logs y /api/logs/stats pero SOLO ve eventos de su propio tenant
        res_logs_alpha = self.client.get("/api/logs", headers=h_alpha_admin)
        self.assertEqual(res_logs_alpha.status_code, 200)
        logs_list = res_logs_alpha.json()["logs"]
        self.assertTrue(all(l["lead_id"] == "lead_alpha_1" for l in logs_list))
        self.assertFalse(any("Confidencial Beta" in l["message"] for l in logs_list))

        res_logs_cross = self.client.get(f"/api/logs?tenant_id={self.tenant_beta}", headers=h_alpha_admin)
        self.assertEqual(res_logs_cross.status_code, 403)

        res_stats_alpha = self.client.get("/api/logs/stats", headers=h_alpha_admin)
        self.assertEqual(res_stats_alpha.status_code, 200)
        self.assertEqual(res_stats_alpha.json()["total"], 1)

        # 3. COMPANY_ADMIN NO puede borrar logs globales ni ejecutar canary-run (reservados a SUPER_ADMIN) -> 403
        self.assertEqual(self.client.delete("/api/logs", headers=h_alpha_admin).status_code, 403)
        self.assertEqual(self.client.post("/api/selectors/canary-run", headers=h_alpha_admin).status_code, 403)

        # 4. COMPANY_ADMIN al retirar invitaciones vencidas NO afecta las invitaciones vencidas de Beta
        res_stale_alpha = self.client.post("/api/linkedin/invitaciones-vencidas/retirar?dias_limite=21", headers=h_alpha_admin)
        self.assertEqual(res_stale_alpha.status_code, 200)
        self.assertEqual(res_stale_alpha.json()["retiradas"], 0)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT estado, invitacion_retirada FROM leads WHERE id = 'lead_beta_2'")
            b2 = cur.fetchone()
            self.assertEqual(b2["estado"], "INVITACION_ENVIADA")
            self.assertEqual(b2["invitacion_retirada"] or 0, 0)

        # 5. COMPANY_ADMIN puede operar kill-switch y configuración de seguridad -> 200 OK
        self.assertEqual(self.client.post("/api/seguridad/kill-switch/activar?motivo=TestAdmin", headers=h_alpha_admin).status_code, 200)
        self.assertEqual(self.client.post("/api/seguridad/kill-switch/desactivar", headers=h_alpha_admin).status_code, 200)
        self.assertEqual(
            self.client.post("/api/seguridad/configuracion", json={"clave": "limite_linkedin_diario", "valor": "12"}, headers=h_alpha_admin).status_code,
            200
        )

        # 6. SUPER_ADMIN puede ejecutar canary-run y limpiar logs -> 200 OK
        with patch("canary_service.run_full_canary_suite", return_value={"status": "ALL_GREEN"}):
            res_canary = self.client.post("/api/selectors/canary-run", headers=h_super)
            self.assertEqual(res_canary.status_code, 200)

        res_clear = self.client.delete("/api/logs", headers=h_super)
        self.assertEqual(res_clear.status_code, 200)


if __name__ == "__main__":
    unittest.main()
