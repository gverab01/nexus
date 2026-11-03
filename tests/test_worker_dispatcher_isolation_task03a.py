import os
import sys
import json
import tempfile
import unittest
import base64
from contextlib import AsyncExitStack
from urllib.parse import urlsplit
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Configurar base de datos SQLite temporal AISLADA antes de importar módulos del proyecto
_tmp_db_file = tempfile.NamedTemporaryFile(prefix="nexus_task03a_test_", suffix=".db", delete=False)
_tmp_db_path = _tmp_db_file.name
_tmp_db_file.close()

os.environ["SQLITE_DB_PATH"] = _tmp_db_path
os.environ["DATABASE_URL"] = ""

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fastapi.routing
import fastapi.dependencies.utils
import starlette.routing
import starlette.concurrency
from starlette.middleware.exceptions import ExceptionMiddleware


async def _inline_run_in_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)


fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
starlette.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool

import database
import auth_service
import command_signing_service
import task_dispatcher
import safety_engine
import main


class _Response:
    def __init__(self, status_code: int, body: bytes, headers: dict):
        self.status_code = status_code
        self.content = body
        self.headers = headers
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class SandboxSafeTestClient:
    """Cliente ASGI síncrono en memoria para probar FastAPI sin invocar socket.socketpair() en el sandbox de Windows."""

    def __init__(self, asgi_app):
        self.app = ExceptionMiddleware(asgi_app.router, handlers=asgi_app.exception_handlers)

    def request(self, method: str, url: str, headers: dict = None, json_body=None):
        parsed = urlsplit(url)
        path = parsed.path or "/"
        query_string = (parsed.query or "").encode("utf-8")

        req_headers = []
        if headers:
            for k, v in headers.items():
                req_headers.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))

        body_bytes = b""
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            req_headers.append((b"content-type", b"application/json"))
            req_headers.append((b"content-length", str(len(body_bytes)).encode("latin-1")))

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
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "state": {},
            "fastapi_middleware_astack": AsyncExitStack(),
        }

        resp_status = 500
        resp_headers = {}
        resp_body = bytearray()
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal resp_status, resp_headers
            if message["type"] == "http.response.start":
                resp_status = message["status"]
                resp_headers = {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in message.get("headers", [])
                }
            elif message["type"] == "http.response.body":
                resp_body.extend(message.get("body", b""))

        coro = self.app(scope, receive, send)
        try:
            while True:
                coro.send(None)
        except StopIteration:
            pass
        return _Response(resp_status, bytes(resp_body), resp_headers)

    def get(self, url: str, headers: dict = None):
        return self.request("GET", url, headers=headers)

    def post(self, url: str, headers: dict = None, json: dict = None):
        return self.request("POST", url, headers=headers, json_body=json)


def _generate_ed25519_keypair():
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    pub_b64 = base64.b64encode(pub_raw).decode("utf-8")
    return priv, pub_b64


def _sign_device_report(priv_key: Ed25519PrivateKey, payload: dict) -> str:
    signed_fields = {
        "command_id": payload["command_id"],
        "device_id": payload["device_id"],
        "success": bool(payload.get("success", False)),
        "result": payload.get("result") if payload.get("result") is not None else {},
        "error": payload.get("error") or ""
    }
    canonical_bytes = command_signing_service.canonicalize_json(signed_fields)
    sig_bytes = priv_key.sign(canonical_bytes)
    return base64.b64encode(sig_bytes).decode("utf-8")


class TestWorkerDispatcherIsolationTask03A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SQLITE_DB_PATH"] = _tmp_db_path
        database.DB_PATH = _tmp_db_path
        assert os.path.abspath(database.get_sqlite_db_path()) == os.path.abspath(_tmp_db_path), (
            f"peligro: DB_PATH apunta a {database.get_sqlite_db_path()} en lugar de la temporal {_tmp_db_path}"
        )
        database.init_db()
        cls.client = SandboxSafeTestClient(main.app)

        # Forzar horario laboral 24/7 y desactivar kill-switch en la BD temporal para pruebas deterministas
        cls._orig_check_bh = safety_engine.check_business_hours
        safety_engine.check_business_hours = lambda *args, **kwargs: (True, "OK Test Hours")

        cls._seed_base_data()

    @classmethod
    def tearDownClass(cls):
        safety_engine.check_business_hours = cls._orig_check_bh
        try:
            if os.path.exists(_tmp_db_path):
                os.remove(_tmp_db_path)
        except Exception:
            pass

    @classmethod
    def _seed_base_data(cls):
        now = datetime.now()
        now_iso = now.isoformat()
        future_iso = (now + timedelta(days=365)).isoformat()

        cls.priv_a, cls.pub_a = _generate_ed25519_keypair()
        cls.priv_a2, cls.pub_a2 = _generate_ed25519_keypair()
        cls.priv_b, cls.pub_b = _generate_ed25519_keypair()
        cls.priv_sub_a, cls.pub_sub_a = _generate_ed25519_keypair()

        with database.get_db() as conn:
            cursor = conn.cursor()

            # Desactivar kill-switch en BD temporal
            cursor.execute(
                "INSERT OR REPLACE INTO configuracion_seguridad (clave, valor, descripcion) VALUES ('kill_switch_activado', '0', 'test')"
            )

            # Tenants
            tenants = [
                ("ten_a", None, "Tenant Alpha", "AGENCIA"),
                ("ten_sub_a", "ten_a", "Subtenant Alpha Child", "EMPRESA"),
                ("ten_b", None, "Tenant Beta", "EMPRESA"),
            ]
            for t_id, parent_id, razon_social, tipo in tenants:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'ACTIVO', ?, ?)
                    """,
                    (t_id, parent_id, razon_social, tipo, now_iso, now_iso)
                )
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES (?, ?, 'ANUAL', 'ACTIVA', 5, 35.0, ?, ?, ?, ?)
                    """,
                    (f"sub_{t_id}", t_id, now_iso, future_iso, now_iso, now_iso)
                )

            # Usuarios
            users = [
                ("usr_a", "ten_a", "worker_a@alpha.io", "Worker Alpha", "PassA123!", "COMPANY_ADMIN"),
                ("usr_agency_a", "ten_a", "agency_a@alpha.io", "Agency Alpha", "PassAgencyA123!", "AGENCY_ADMIN"),
                ("usr_b", "ten_b", "worker_b@beta.io", "Worker Beta", "PassB123!", "COMPANY_ADMIN"),
            ]
            for u_id, t_id, email, name, pwd, rol in users:
                p_hash, p_salt = auth_service.hash_password(pwd)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'ACTIVO', ?, ?, ?)
                    """,
                    (u_id, t_id, email, name, p_hash, p_salt, rol, future_iso, now_iso, now_iso)
                )
            conn.commit()

        # Autenticar sesiones reales y fijar tokens deterministas para las pruebas
        # Nota: autenticamos worker_b de último para que el último LOGIN_EXITOSO en audit_logs sea de ten_b
        res_a = auth_service.authenticate_user("worker_a@alpha.io", "PassA123!")
        assert res_a["exito"], f"Login falló para worker_a: {res_a}"
        auth_service.ACTIVE_SESSIONS["tok_worker_a"] = dict(auth_service.ACTIVE_SESSIONS[res_a["token"]])

        res_ag = auth_service.authenticate_user("agency_a@alpha.io", "PassAgencyA123!")
        assert res_ag["exito"], f"Login falló para agency_a: {res_ag}"
        auth_service.ACTIVE_SESSIONS["tok_agency_a"] = dict(auth_service.ACTIVE_SESSIONS[res_ag["token"]])

        res_b = auth_service.authenticate_user("worker_b@beta.io", "PassB123!")
        assert res_b["exito"], f"Login falló para worker_b: {res_b}"
        auth_service.ACTIVE_SESSIONS["tok_worker_b"] = dict(auth_service.ACTIVE_SESSIONS[res_b["token"]])

        # Sesión expirada
        expired_session = dict(auth_service.ACTIVE_SESSIONS["tok_worker_a"])
        expired_session["expires_at"] = 1.0  # Expirada en 1970
        auth_service.ACTIVE_SESSIONS["tok_expired_a"] = expired_session

        # Registrar dispositivos con claves públicas Ed25519 reales
        command_signing_service.register_device("dev_a", "ten_a", cls.pub_a, "Runner Alpha 1", user_id="usr_a")
        command_signing_service.register_device("dev_a2", "ten_a", cls.pub_a2, "Runner Alpha 2", user_id="usr_a")
        command_signing_service.register_device("dev_b", "ten_b", cls.pub_b, "Runner Beta 1", user_id="usr_b")
        command_signing_service.register_device("dev_sub_a", "ten_sub_a", cls.pub_sub_a, "Runner Sub Alpha", user_id="usr_agency_a")
        command_signing_service.register_device("dev_revoked_a", "ten_a", cls.pub_a, "Runner Revoked", user_id="usr_a")
        command_signing_service.revoke_device("dev_revoked_a", "ten_a")

    def _reset_queues(self):
        """Limpia y recrea prospectos, secuencias, pasos, inscripciones y comandos antes de cada prueba."""
        now_iso = (datetime.now() - timedelta(minutes=5)).isoformat()
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM command_results")
            cursor.execute("DELETE FROM commands")
            cursor.execute("DELETE FROM leads_en_secuencia")
            cursor.execute("DELETE FROM pasos_secuencia")
            cursor.execute("DELETE FROM secuencias")
            cursor.execute("DELETE FROM leads")
            cursor.execute("DELETE FROM historial_actividades")
            cursor.execute("DELETE FROM lead_activity")

            # Leads
            leads = [
                ("lead_a1", "ten_a", "Alice Alpha", "Colegio Alpha", "Directora", "https://linkedin.com/in/alice-alpha", "alice@alpha.edu", "NUEVO"),
                ("lead_b1", "ten_b", "Bob Beta", "Colegio Beta", "Rector", "https://linkedin.com/in/bob-beta", "bob@beta.edu", "NUEVO"),
                ("lead_sub_a1", "ten_sub_a", "Sara SubAlpha", "Colegio SubAlpha", "Coordinadora", "https://linkedin.com/in/sara-sub", "sara@sub.edu", "NUEVO"),
            ]
            for l_id, t_id, nombre, inst, cargo, url, email, est in leads:
                cursor.execute(
                    """
                    INSERT INTO leads (id, tenant_id, nombre, institucion_actual, cargo_actual, perfil_url, email, estado, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (l_id, t_id, nombre, inst, cargo, url, email, est, now_iso)
                )

            # Secuencias publicadas y activas
            seqs = [
                ("seq_a", "ten_a", "Secuencia Alpha"),
                ("seq_b", "ten_b", "Secuencia Beta"),
                ("seq_sub_a", "ten_sub_a", "Secuencia SubAlpha"),
            ]
            for s_id, t_id, s_name in seqs:
                cursor.execute(
                    """
                    INSERT INTO secuencias (id, tenant_id, nombre, activa, estado, created_at)
                    VALUES (?, ?, ?, 1, 'PUBLICADA', ?)
                    """,
                    (s_id, t_id, s_name, now_iso)
                )

            # Pasos de secuencia (2 pasos en seq_a para probar avance de paso, 1 paso en seq_b y seq_sub_a)
            steps = [
                ("step_a_1", "seq_a", 1, "VISITAR_PERFIL", '{"nota": "Hola {{nombre}}"}'),
                ("step_a_2", "seq_a", 2, "ENVIAR_INVITACION", '{"nota": "Conectemos {{nombre}}"}'),
                ("step_b_1", "seq_b", 1, "VISITAR_PERFIL", '{"nota": "Hola {{nombre}} de Beta"}'),
                ("step_sub_a_1", "seq_sub_a", 1, "VISITAR_PERFIL", '{"nota": "Hola {{nombre}} de SubAlpha"}'),
            ]
            for st_id, s_id, orden, tipo, params_json in steps:
                cursor.execute(
                    """
                    INSERT INTO pasos_secuencia (id, secuencia_id, orden, tipo_accion, parametros_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (st_id, s_id, orden, tipo, params_json)
                )

            # Inscripciones listas para ejecutar
            enrollments = [
                ("enr_a1", "lead_a1", "seq_a", "step_a_1", "EN_CURSO", now_iso),
                ("enr_b1", "lead_b1", "seq_b", "step_b_1", "EN_CURSO", now_iso),
                ("enr_sub_a1", "lead_sub_a1", "seq_sub_a", "step_sub_a_1", "EN_CURSO", now_iso),
            ]
            for e_id, l_id, s_id, st_id, estado, prox in enrollments:
                cursor.execute(
                    """
                    INSERT INTO leads_en_secuencia (id, lead_id, secuencia_id, paso_actual_id, estado, proxima_ejecucion_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (e_id, l_id, s_id, st_id, estado, prox, now_iso)
                )

    def test_01_worker_unauthenticated_and_expired_credentials_rejected(self):
        """1 y 2. Worker sin credenciales o con credenciales inválidas/expiradas recibe 401."""
        self._reset_queues()

        # Sin credenciales en GET /api/worker/proxima-tarea
        r1 = self.client.get("/api/worker/proxima-tarea")
        self.assertEqual(r1.status_code, 401)

        # Sin credenciales intentando pasar tenant_id en query
        r2 = self.client.get("/api/worker/proxima-tarea?tenant_id=ten_a&device_id=dev_a")
        self.assertEqual(r2.status_code, 401)

        # Token inválido
        r3 = self.client.get(
            "/api/worker/proxima-tarea",
            headers={"Authorization": "Bearer token_inexistente"}
        )
        self.assertEqual(r3.status_code, 401)

        # Token expirado
        auth_service.ACTIVE_SESSIONS["tok_expired_a"] = {
            **auth_service.ACTIVE_SESSIONS["tok_worker_a"],
            "expires_at": 1.0
        }
        r4 = self.client.get(
            "/api/worker/proxima-tarea",
            headers={"Authorization": "Bearer tok_expired_a"}
        )
        self.assertEqual(r4.status_code, 401)

        # Sin credenciales ni firma en POST /api/worker/reportar-resultado
        r5 = self.client.post(
            "/api/worker/reportar-resultado",
            json={"lead_id": "lead_a1", "secuencia_id": "seq_a", "exito": True}
        )
        self.assertEqual(r5.status_code, 401)

        # Token expirado en POST /api/worker/reportar-resultado
        auth_service.ACTIVE_SESSIONS["tok_expired_a"] = {
            **auth_service.ACTIVE_SESSIONS["tok_worker_a"],
            "expires_at": 1.0
        }
        r6 = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_expired_a"},
            json={"command_id": "cmd_fake", "device_id": "dev_a", "device_signature": "sig", "lead_id": "lead_a1", "secuencia_id": "seq_a"}
        )
        self.assertEqual(r6.status_code, 401)

        # Llamada interna directa a get_next_dispatched_task sin tenant_id no infiere desde audit_logs
        direct_res = task_dispatcher.get_next_dispatched_task(tenant_id=None)
        self.assertFalse(direct_res["hay_tarea"])
        self.assertEqual(direct_res.get("error"), "TENANT_REQUIRED")

    def test_02_worker_obtains_only_own_tenant_task_and_never_other_tenant(self):
        """3, 4 y 5. Worker A obtiene tarea de su propio tenant y jamás obtiene tareas de Tenant B (ni por tenant_id, secuencia_id o cola vacía)."""
        self._reset_queues()

        # Worker A intenta pedir tenant_id=ten_b -> 403
        r_cross_tenant = self.client.get(
            "/api/worker/proxima-tarea?tenant_id=ten_b",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_cross_tenant.status_code, 403)

        # Worker A intenta pedir secuencia_id=seq_b (de ten_b) -> 403
        r_cross_seq = self.client.get(
            "/api/worker/proxima-tarea?secuencia_id=seq_b",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_cross_seq.status_code, 403)

        # Llamada directa a get_next_dispatched_task con tenant_id="ten_a" y sequence_id="seq_b" -> FORBIDDEN_SEQUENCE_TENANT
        direct_cross_seq = task_dispatcher.get_next_dispatched_task(
            tenant_id="ten_a",
            sequence_id="seq_b",
            device_id="dev_a"
        )
        self.assertFalse(direct_cross_seq["hay_tarea"])
        self.assertEqual(direct_cross_seq.get("error"), "FORBIDDEN_SEQUENCE_TENANT")

        # Worker A solicita su propia tarea legítimamente -> 200 OK con tarea de ten_a
        r_ok = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_ok.status_code, 200)
        body = r_ok.json()
        self.assertTrue(body["hay_tarea"])
        self.assertEqual(body["tarea"]["lead_id"], "lead_a1")
        self.assertEqual(body["tarea"]["secuencia_id"], "seq_a")
        self.assertEqual(body["tarea"]["tenant_id"], "ten_a")
        self.assertEqual(body["comando"]["tenant_id"], "ten_a")
        self.assertEqual(body["comando"]["device_id"], "dev_a")
        cmd_copy = {k: v for k, v in body["comando"].items() if k != "signature"}
        self.assertTrue(command_signing_service.verify_server_command_signature(cmd_copy, body["comando"]["signature"]))

        # Ahora la tarea de ten_a ya fue reservada (cola de ten_a vacía), mientras que ten_b tiene lead_b1 listo
        # y audit_logs tiene a ten_b como último LOGIN_EXITOSO.
        # Si Worker A vuelve a consultar, debe recibir hay_tarea=False y NUNCA la tarea de ten_b.
        r_empty_a = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_empty_a.status_code, 200)
        self.assertFalse(r_empty_a.json()["hay_tarea"])

        # Y la inscripción de ten_b sigue intacta para Worker B
        r_ok_b = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_b",
            headers={"Authorization": "Bearer tok_worker_b"}
        )
        self.assertEqual(r_ok_b.status_code, 200)
        body_b = r_ok_b.json()
        self.assertTrue(body_b["hay_tarea"])
        self.assertEqual(body_b["tarea"]["lead_id"], "lead_b1")
        self.assertEqual(body_b["tarea"]["tenant_id"], "ten_b")

    def test_03_agency_admin_subtenant_allowed_and_foreign_tenant_rejected(self):
        """5. AGENCY_ADMIN puede despachar tareas de su subtenant autorizado pero recibe 403 para un tenant ajeno."""
        self._reset_queues()

        # AGENCY_ADMIN de ten_a pide tarea de ten_b -> 403
        r_forbidden = self.client.get(
            "/api/worker/proxima-tarea?tenant_id=ten_b&device_id=dev_b",
            headers={"Authorization": "Bearer tok_agency_a"}
        )
        self.assertEqual(r_forbidden.status_code, 403)

        # AGENCY_ADMIN de ten_a pide tarea de su subtenant ten_sub_a con dev_sub_a -> 200 OK
        r_sub = self.client.get(
            "/api/worker/proxima-tarea?tenant_id=ten_sub_a&device_id=dev_sub_a",
            headers={"Authorization": "Bearer tok_agency_a"}
        )
        self.assertEqual(r_sub.status_code, 200)
        data = r_sub.json()
        self.assertTrue(data["hay_tarea"])
        self.assertEqual(data["tarea"]["tenant_id"], "ten_sub_a")
        self.assertEqual(data["tarea"]["lead_id"], "lead_sub_a1")

    def test_04_unauthorized_revoked_or_cross_tenant_device_rejected(self):
        """6. device_id no autorizado, revocado o de otro tenant es rechazado con 403, e impide secuestro en /api/devices/register."""
        self._reset_queues()

        # Worker A intenta usar dev_b (pertenece a ten_b) -> 403
        r_foreign_dev = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_b",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_foreign_dev.status_code, 403)

        # Worker A intenta usar dev_revoked_a (revocado) -> 403
        r_revoked_dev = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_revoked_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_revoked_dev.status_code, 403)

        # Worker A intenta usar un device_id inexistente -> 403
        r_unknown_dev = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_no_registrado",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_unknown_dev.status_code, 403)

        # Worker B intenta re-registrar/secuestrar dev_a (que pertenece a ten_a) en /api/devices/register -> 403
        r_hijack = self.client.post(
            "/api/devices/register",
            headers={"Authorization": "Bearer tok_worker_b"},
            json={
                "device_id": "dev_a",
                "public_key_ed25519": self.pub_b,
                "device_name": "Hijacked Runner"
            }
        )
        self.assertEqual(r_hijack.status_code, 403)

        # Verificar que dev_a sigue perteneciendo a ten_a con su clave pública original
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tenant_id, public_key_ed25519 FROM devices WHERE id = 'dev_a'")
            row = cursor.fetchone()
            self.assertEqual(row["tenant_id"], "ten_a")
            self.assertEqual(row["public_key_ed25519"], self.pub_a)

    def test_05_report_result_cross_tenant_or_wrong_device_or_tampered_resources_rejected_without_mutation(self):
        """7. Reportar resultado para tarea de otro tenant, otro dispositivo o recursos cruzados devuelve 403 sin mutar la BD."""
        self._reset_queues()

        # Despachar tarea legítima a dev_a (ten_a)
        r_disp = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_disp.status_code, 200)
        disp = r_disp.json()
        cmd_id = disp["tarea"]["command_id"]
        action = disp["tarea"]["action"]

        # Caso A: Worker B intenta reportar el comando de ten_a usando sesión de ten_b -> 403
        rep_payload_b = {
            "command_id": cmd_id,
            "device_id": "dev_b",
            "tenant_id": "ten_b",
            "action": action,
            "success": True,
            "result": {"ok": True},
            "error": ""
        }
        sig_b = _sign_device_report(self.priv_b, rep_payload_b)
        r_cross_rep = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_b"},
            json={
                **rep_payload_b,
                "tarea_id": cmd_id,
                "lead_id": "lead_a1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "exito": True,
                "device_signature": sig_b
            }
        )
        self.assertEqual(r_cross_rep.status_code, 403)

        # Caso B: Otro dispositivo del mismo tenant (dev_a2) intenta reportar un comando asignado a dev_a -> 403
        rep_payload_a2 = {
            "command_id": cmd_id,
            "device_id": "dev_a2",
            "tenant_id": "ten_a",
            "action": action,
            "success": True,
            "result": {"ok": True},
            "error": ""
        }
        sig_a2 = _sign_device_report(self.priv_a2, rep_payload_a2)
        r_wrong_dev = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json={
                **rep_payload_a2,
                "tarea_id": cmd_id,
                "lead_id": "lead_a1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "exito": True,
                "device_signature": sig_a2
            }
        )
        self.assertEqual(r_wrong_dev.status_code, 403)

        # Caso C: dev_a firma su comando pero intenta cambiar lead_id a lead_b1 (de otro tenant) -> 403
        rep_payload_a = {
            "command_id": cmd_id,
            "device_id": "dev_a",
            "tenant_id": "ten_a",
            "action": action,
            "success": True,
            "result": {"ok": True},
            "error": ""
        }
        sig_a = _sign_device_report(self.priv_a, rep_payload_a)
        r_tampered_lead = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json={
                **rep_payload_a,
                "tarea_id": cmd_id,
                "lead_id": "lead_b1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "exito": True,
                "device_signature": sig_a
            }
        )
        self.assertEqual(r_tampered_lead.status_code, 403)

        # Verificar CERO mutaciones en leads, leads_en_secuencia, commands y command_results
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_a1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_b1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")
            cursor.execute("SELECT estado, paso_actual_id FROM leads_en_secuencia WHERE id = 'enr_a1'")
            enr = cursor.fetchone()
            self.assertEqual(enr["estado"], "EN_CURSO")
            self.assertEqual(enr["paso_actual_id"], "step_a_1")
            cursor.execute("SELECT status FROM commands WHERE id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["status"], "DISPATCHED")
            cursor.execute("SELECT COUNT(*) as total FROM command_results")
            self.assertEqual(cursor.fetchone()["total"], 0)

    def test_06_invalid_signature_or_tampered_payload_rejected_without_mutation(self):
        """8. Reporte con firma Ed25519 inválida o payload alterado tras firmar devuelve 403 y no muta el estado."""
        self._reset_queues()

        r_disp = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        disp = r_disp.json()
        cmd_id = disp["tarea"]["command_id"]
        action = disp["tarea"]["action"]

        # Firmar con success=False pero enviar exito=True en el payload (alteración post-firma)
        signed_payload = {
            "command_id": cmd_id,
            "device_id": "dev_a",
            "tenant_id": "ten_a",
            "action": action,
            "success": False,
            "result": {},
            "error": "Failed"
        }
        sig_for_false = _sign_device_report(self.priv_a, signed_payload)

        r_tampered = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json={
                "command_id": cmd_id,
                "tarea_id": cmd_id,
                "device_id": "dev_a",
                "tenant_id": "ten_a",
                "lead_id": "lead_a1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "action": action,
                "exito": True,  # Alterado respecto a lo firmado
                "result": {},
                "error": "Failed",
                "device_signature": sig_for_false
            }
        )
        self.assertEqual(r_tampered.status_code, 403)

        # Verificar que el lead sigue NUEVO, la inscripción sigue en step_a_1 y el comando sigue DISPATCHED
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_a1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")
            cursor.execute("SELECT paso_actual_id, estado FROM leads_en_secuencia WHERE id = 'enr_a1'")
            enr = cursor.fetchone()
            self.assertEqual(enr["paso_actual_id"], "step_a_1")
            self.assertEqual(enr["estado"], "EN_CURSO")
            cursor.execute("SELECT status FROM commands WHERE id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["status"], "DISPATCHED")
            cursor.execute("SELECT COUNT(*) as total FROM command_results")
            self.assertEqual(cursor.fetchone()["total"], 0)

    def test_07_valid_execution_and_replay_duplicate_report_rejected(self):
        """9 y 12. Flujo válido avanza el paso y actualiza estado; un segundo reporte (replay) del mismo comando recibe 409 sin mutar."""
        self._reset_queues()

        r_disp = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        disp = r_disp.json()
        cmd_id = disp["tarea"]["command_id"]
        action = disp["tarea"]["action"]

        rep_payload = {
            "command_id": cmd_id,
            "device_id": "dev_a",
            "tenant_id": "ten_a",
            "action": action,
            "success": True,
            "result": {"visited": True},
            "error": ""
        }
        sig_a = _sign_device_report(self.priv_a, rep_payload)

        full_body = {
            **rep_payload,
            "tarea_id": cmd_id,
            "lead_id": "lead_a1",
            "secuencia_id": "seq_a",
            "paso_id": "step_a_1",
            "exito": True,
            "device_signature": sig_a
        }

        # Primer reporte legítimo -> 200 OK
        r_ok = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json=full_body
        )
        self.assertEqual(r_ok.status_code, 200)
        res_json = r_ok.json()
        self.assertEqual(res_json["status"], "ok")
        self.assertEqual(res_json["siguiente_paso_id"], "step_a_2")

        # Verificar mutación legítima en BD
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_a1'")
            self.assertEqual(cursor.fetchone()["estado"], "PERFIL_VISITADO")
            cursor.execute("SELECT paso_actual_id, estado FROM leads_en_secuencia WHERE id = 'enr_a1'")
            enr = cursor.fetchone()
            self.assertEqual(enr["paso_actual_id"], "step_a_2")
            self.assertEqual(enr["estado"], "EN_CURSO")
            cursor.execute("SELECT status FROM commands WHERE id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["status"], "EXECUTED")
            cursor.execute("SELECT COUNT(*) as total FROM command_results WHERE command_id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["total"], 1)

        # Segundo reporte idéntico (Replay attack) -> 409 Conflict
        r_replay = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json=full_body
        )
        self.assertEqual(r_replay.status_code, 409)

        # Verificar que el replay no avanzó el paso a COMPLETADO ni duplicó command_results
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT paso_actual_id, estado FROM leads_en_secuencia WHERE id = 'enr_a1'")
            enr_after = cursor.fetchone()
            self.assertEqual(enr_after["paso_actual_id"], "step_a_2")
            self.assertEqual(enr_after["estado"], "EN_CURSO")
            cursor.execute("SELECT COUNT(*) as total FROM command_results WHERE command_id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["total"], 1)

    def test_08_nonexistent_command_and_incompatible_enrollment_state_rejected(self):
        """10. Tarea inexistente (404) o inscripción en estado incompatible (409) es rechazada sin mutaciones."""
        self._reset_queues()

        # Comando inexistente -> 404
        fake_payload = {
            "command_id": "cmd_inexistente_999",
            "device_id": "dev_a",
            "tenant_id": "ten_a",
            "action": "LI_VISIT_PROFILE",
            "success": True,
            "result": {},
            "error": ""
        }
        sig_fake = _sign_device_report(self.priv_a, fake_payload)
        r_404 = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json={
                **fake_payload,
                "tarea_id": "cmd_inexistente_999",
                "lead_id": "lead_a1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "exito": True,
                "device_signature": sig_fake
            }
        )
        self.assertEqual(r_404.status_code, 404)

        # Despachar tarea real y luego pausar/completar la inscripción antes del reporte -> 409
        r_disp = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        disp = r_disp.json()
        cmd_id = disp["tarea"]["command_id"]
        action = disp["tarea"]["action"]

        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE leads_en_secuencia SET estado = 'PAUSADA' WHERE id = 'enr_a1'")
            conn.commit()

        rep_payload = {
            "command_id": cmd_id,
            "device_id": "dev_a",
            "tenant_id": "ten_a",
            "action": action,
            "success": True,
            "result": {},
            "error": ""
        }
        sig_a = _sign_device_report(self.priv_a, rep_payload)
        r_409 = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_a"},
            json={
                **rep_payload,
                "tarea_id": cmd_id,
                "lead_id": "lead_a1",
                "secuencia_id": "seq_a",
                "paso_id": "step_a_1",
                "exito": True,
                "device_signature": sig_a
            }
        )
        self.assertEqual(r_409.status_code, 409)

        # El comando no debe haberse marcado como COMPLETED ni el lead modificado
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_a1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")
            cursor.execute("SELECT status FROM commands WHERE id = ?", (cmd_id,))
            self.assertEqual(cursor.fetchone()["status"], "DISPATCHED")

    def test_09_concurrent_workers_cannot_claim_same_task_twice(self):
        """11. Dos workers del mismo tenant intentando reclamar la misma tarea reciben reserva exclusiva para el primero."""
        self._reset_queues()

        # Worker 1 (dev_a) reclama la tarea disponible de ten_a
        r_w1 = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_w1.status_code, 200)
        d1 = r_w1.json()
        self.assertTrue(d1["hay_tarea"])
        self.assertEqual(d1["tarea"]["lead_id"], "lead_a1")

        # Worker 2 (dev_a2) consulta inmediatamente para el mismo tenant ten_a
        r_w2 = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_a2",
            headers={"Authorization": "Bearer tok_worker_a"}
        )
        self.assertEqual(r_w2.status_code, 200)
        d2 = r_w2.json()
        self.assertFalse(d2["hay_tarea"])

        # Solo se emitió 1 comando en la tabla commands para lead_a1
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM commands WHERE tenant_id = 'ten_a'")
            self.assertEqual(cursor.fetchone()["total"], 1)

    def test_10_valid_failure_report_schedules_retry_and_final_step_completes_enrollment(self):
        """12. Regresión de reporte de fallo (+30m retry) y finalización completa de secuencia de 1 paso."""
        self._reset_queues()

        # 1) Despachar tarea de ten_b (que tiene 1 solo paso: step_b_1)
        r_disp_b = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_b",
            headers={"Authorization": "Bearer tok_worker_b"}
        )
        self.assertEqual(r_disp_b.status_code, 200)
        disp_b = r_disp_b.json()
        cmd_b1 = disp_b["tarea"]["command_id"]
        action_b1 = disp_b["tarea"]["action"]

        # Reportar fallo legítimo firmado por dev_b
        fail_payload = {
            "command_id": cmd_b1,
            "device_id": "dev_b",
            "tenant_id": "ten_b",
            "action": action_b1,
            "success": False,
            "result": {},
            "error": "Timeout cargando perfil"
        }
        sig_fail = _sign_device_report(self.priv_b, fail_payload)
        r_fail = self.client.post(
            "/api/worker/reportar-resultado",
            headers={"Authorization": "Bearer tok_worker_b"},
            json={
                **fail_payload,
                "tarea_id": cmd_b1,
                "lead_id": "lead_b1",
                "secuencia_id": "seq_b",
                "paso_id": "step_b_1",
                "exito": False,
                "device_signature": sig_fail
            }
        )
        self.assertEqual(r_fail.status_code, 200)
        self.assertEqual(r_fail.json()["status"], "error")

        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM commands WHERE id = ?", (cmd_b1,))
            self.assertEqual(cursor.fetchone()["status"], "FAILED")
            cursor.execute("SELECT estado, paso_actual_id, proxima_ejecucion_at FROM leads_en_secuencia WHERE id = 'enr_b1'")
            enr = cursor.fetchone()
            self.assertEqual(enr["estado"], "EN_CURSO")
            self.assertEqual(enr["paso_actual_id"], "step_b_1")
            # Reintento programado en el futuro (~30 min)
            self.assertGreater(enr["proxima_ejecucion_at"], (datetime.now() + timedelta(minutes=20)).isoformat())

            # Adelantar reloj de proxima_ejecucion_at para volver a despachar y completar el paso único
            cursor.execute(
                "UPDATE leads_en_secuencia SET proxima_ejecucion_at = ? WHERE id = 'enr_b1'",
                ((datetime.now() - timedelta(minutes=1)).isoformat(),)
            )
            conn.commit()

        # 2) Volver a despachar y reportar éxito -> debe pasar a COMPLETADO
        r_disp_b2 = self.client.get(
            "/api/worker/proxima-tarea?device_id=dev_b",
            headers={"Authorization": "Bearer tok_worker_b"}
        )
        self.assertEqual(r_disp_b2.status_code, 200)
        disp_b2 = r_disp_b2.json()
        cmd_b2 = disp_b2["tarea"]["command_id"]
        self.assertNotEqual(cmd_b1, cmd_b2)

        ok_payload = {
            "command_id": cmd_b2,
            "device_id": "dev_b",
            "tenant_id": "ten_b",
            "action": action_b1,
            "success": True,
            "result": {"visited": True},
            "error": ""
        }
        sig_ok = _sign_device_report(self.priv_b, ok_payload)
        r_ok = self.client.post(
            "/api/worker/reportar-resultado",
            json={
                **ok_payload,
                "tarea_id": cmd_b2,
                "lead_id": "lead_b1",
                "secuencia_id": "seq_b",
                "paso_id": "step_b_1",
                "exito": True,
                "device_signature": sig_ok
            }
        )
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(r_ok.json()["status"], "ok")

        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado, proxima_ejecucion_at FROM leads_en_secuencia WHERE id = 'enr_b1'")
            enr_final = cursor.fetchone()
            self.assertEqual(enr_final["estado"], "COMPLETADO")
            self.assertIsNone(enr_final["proxima_ejecucion_at"])


if __name__ == "__main__":
    unittest.main()
