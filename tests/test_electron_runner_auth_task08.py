"""
Suite de Integración End-to-End TASK-08:
Conecta el módulo real de Node.js `desktop/worker_runner.cjs` (con `CryptoVerifier` Ed25519 real)
contra el backend real FastAPI (`main.app`, `task_dispatcher`, `command_signing_service`, `auth_service`)
sobre una base de datos SQLite temporal aislada (`SQLITE_DB_PATH`).

Comprueba los 10 escenarios obligatorios de TASK-08 sin mocks de seguridad ni firmas:
1. Un runner sin sesión no obtiene tareas.
2. Un runner autenticado obtiene tareas únicamente de su ámbito autorizado.
3. Manipular el tenant no permite acceder a tareas ajenas.
4. Un dispositivo revocado no puede continuar despachando tareas.
5. Una sesión expirada no inicia nuevas ejecuciones.
6. Una firma inválida no permite ejecutar comandos ni reportar resultados aceptados.
7. Los errores HTTP 401 y 403 no provocan bucles ilimitados.
8. La ausencia de tareas no genera errores ni mutaciones indebidas.
9. Un resultado no se considera confirmado antes de la aceptación del backend.
10. El flujo legítimo de inicio de sesión, despacho, ejecución y reporte funciona de extremo a extremo.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess
from contextlib import AsyncExitStack
from urllib.parse import urlsplit
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Base de datos SQLite temporal aislada
_tmp_db_file = tempfile.NamedTemporaryFile(prefix="nexus_task08_e2e_", suffix=".db", delete=False)
_tmp_db_path = _tmp_db_file.name
_tmp_db_file.close()

os.environ["SQLITE_DB_PATH"] = _tmp_db_path
os.environ["DATABASE_URL"] = ""

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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
import safety_engine
import main


class _Response:
    def __init__(self, status_code: int, body: bytes, headers: dict):
        self.status_code = status_code
        self.content = body
        self.headers = headers
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text) if self.text else {}


class SandboxSafeTestClient:
    """Cliente ASGI síncrono en memoria para ejecutar el stack completo de FastAPI."""

    def __init__(self, asgi_app):
        self.app = ExceptionMiddleware(asgi_app.router, handlers=asgi_app.exception_handlers)

    def request(self, method: str, url: str, headers: dict = None, json_body=None):
        parsed = urlsplit(url)
        path = parsed.path or "/"
        query_string = (parsed.query or "").encode("utf-8")

        req_headers = []
        if headers:
            for k, v in headers.items():
                if v is not None:
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


# Script puente Node.js que carga el `desktop/worker_runner.cjs` real y enruta sus peticiones HTTP
# hacia el proceso padre en Python (FastAPI real) por stdio línea a línea.
NODE_BRIDGE_SCRIPT = r"""
const readline = require('readline');
const path = require('path');
const workerRunner = require(path.join(process.cwd(), 'desktop', 'worker_runner.cjs'));

const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });
let pendingHttpResolve = null;
let executedActions = [];
let httpHistory = [];
let responseMutator = null;

function sendMsg(obj) {
  process.stdout.write('__BRIDGE__' + JSON.stringify(obj) + '\n');
}

function bridgeTransport(method, url, headers, body) {
  return new Promise((resolve) => {
    pendingHttpResolve = (res) => {
      httpHistory.push({ method, url, statusCode: res.statusCode });
      if (responseMutator) {
        res = responseMutator(method, url, res);
      }
      resolve(res);
    };
    sendMsg({ type: 'http_req', method, url, headers, body });
  });
}

rl.on('line', async (line) => {
  if (!line.startsWith('__PY__')) return;
  const msg = JSON.parse(line.slice(6));

  if (msg.type === 'http_res') {
    if (pendingHttpResolve) {
      const fn = pendingHttpResolve;
      pendingHttpResolve = null;
      fn(msg.res);
    }
    return;
  }

  if (msg.type === 'cmd') {
    try {
      if (msg.action === 'init') {
        executedActions = [];
        httpHistory = [];
        responseMutator = null;
        workerRunner.stopWorker();
        workerRunner.clearAuthSession();
        workerRunner.configureRunner({
          keysDir: msg.keysDir,
          transport: bridgeTransport,
          actionExecutor: async (action, params) => {
            executedActions.push({ action, params });
            return { success: true, result: { executed_by: 'node_worker_runner' } };
          }
        });
        sendMsg({ type: 'cmd_res', ok: true, status: workerRunner.getStatus() });
      } else if (msg.action === 'set_session') {
        workerRunner.setAuthSession({ sessionToken: msg.sessionToken, tenantId: msg.tenantId });
        sendMsg({ type: 'cmd_res', ok: true, status: workerRunner.getStatus() });
      } else if (msg.action === 'clear_session') {
        workerRunner.clearAuthSession();
        sendMsg({ type: 'cmd_res', ok: true, status: workerRunner.getStatus() });
      } else if (msg.action === 'set_mutator') {
        if (msg.mode === 'tamper_command_sig') {
          responseMutator = (method, url, res) => {
            if (url.includes('/api/worker/proxima-tarea') && res.data && res.data.comando) {
              res.data.comando.params.profile_url = 'https://www.linkedin.com/in/tampered-by-mitm';
            }
            return res;
          };
        } else if (msg.mode === 'fail_report_500') {
          responseMutator = (method, url, res) => {
            if (url.includes('/api/worker/reportar-resultado')) {
              return { statusCode: 500, ok: false, data: { detail: 'Simulated backend failure before confirmation' } };
            }
            return res;
          };
        } else {
          responseMutator = null;
        }
        sendMsg({ type: 'cmd_res', ok: true });
      } else if (msg.action === 'run_cycle') {
        // Ejecutar un ciclo completo de manera determinista esperando la promesa de startWorker
        await workerRunner.startWorker(null);
        const st = workerRunner.getStatus();
        const wasActive = st.activo;
        workerRunner.stopWorker();
        sendMsg({
          type: 'cmd_res',
          ok: true,
          wasActive,
          status: st,
          executedActions,
          httpHistory
        });
      }
    } catch (err) {
      sendMsg({ type: 'cmd_res', ok: false, error: err.message });
    }
  }
});
"""


class NodeRunnerBridge:
    """Controla una instancia real de `desktop/worker_runner.cjs` en un subproceso Node.js."""

    def __init__(self, asgi_client: SandboxSafeTestClient):
        self.client = asgi_client
        self.proc = subprocess.Popen(
            ["node", "-e", NODE_BRIDGE_SCRIPT],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1
        )

    def call(self, payload: dict) -> dict:
        self.proc.stdin.write("__PY__" + json.dumps(payload) + "\n")
        self.proc.stdin.flush()

        while True:
            line = self.proc.stdout.readline()
            if not line:
                err_out = self.proc.stderr.read()
                raise RuntimeError(f"Proceso Node.js terminó inesperadamente: {err_out}")
            line = line.strip()
            if not line.startswith("__BRIDGE__"):
                continue
            msg = json.loads(line[len("__BRIDGE__"):])
            if msg["type"] == "http_req":
                resp = self.client.request(
                    msg["method"],
                    msg["url"],
                    headers=msg.get("headers") or {},
                    json_body=msg.get("body")
                )
                try:
                    data = resp.json()
                except Exception:
                    data = {"detail": resp.text}
                res_obj = {
                    "statusCode": resp.status_code,
                    "ok": 200 <= resp.status_code < 300,
                    "data": data
                }
                self.proc.stdin.write("__PY__" + json.dumps({"type": "http_res", "res": res_obj}) + "\n")
                self.proc.stdin.flush()
            elif msg["type"] == "cmd_res":
                return msg

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=2)
        except Exception:
            pass


class TestElectronRunnerAuthTask08(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SQLITE_DB_PATH"] = _tmp_db_path
        database.DB_PATH = _tmp_db_path
        assert os.path.abspath(database.get_sqlite_db_path()) == os.path.abspath(_tmp_db_path)
        database.init_db()
        cls.client = SandboxSafeTestClient(main.app)
        cls._orig_bh = safety_engine.check_business_hours
        safety_engine.check_business_hours = lambda *args, **kwargs: (True, "OK Test Hours")
        cls.keys_root = tempfile.mkdtemp(prefix="nexus_task08_keys_")
        cls._seed_base_data()
        cls.bridge = NodeRunnerBridge(cls.client)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "bridge") and cls.bridge:
            cls.bridge.close()
        safety_engine.check_business_hours = cls._orig_bh
        shutil.rmtree(cls.keys_root, ignore_errors=True)
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

        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO configuracion_seguridad (clave, valor, descripcion) VALUES ('kill_switch_activado', '0', 'test')"
            )

            tenants = [
                ("ten_a", None, "Tenant Alpha", "EMPRESA"),
                ("ten_b", None, "Tenant Beta", "EMPRESA"),
            ]
            for t_id, parent_id, razon, tipo in tenants:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'ACTIVO', ?, ?)
                    """,
                    (t_id, parent_id, razon, tipo, now_iso, now_iso)
                )
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                    VALUES (?, ?, 'ANUAL', 'ACTIVA', 5, 35.0, ?, ?, ?, ?)
                    """,
                    (f"sub_{t_id}", t_id, now_iso, future_iso, now_iso, now_iso)
                )

            users = [
                ("usr_a", "ten_a", "runner_a@alpha.io", "Runner Alpha", "PassA123!", "COMPANY_ADMIN"),
                ("usr_b", "ten_b", "runner_b@beta.io", "Runner Beta", "PassB123!", "COMPANY_ADMIN"),
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

        # Login real contra /api/auth/login
        r_login_a = cls.client.request("POST", "/api/auth/login", json_body={"email": "runner_a@alpha.io", "password": "PassA123!"})
        assert r_login_a.status_code == 200, r_login_a.text
        cls.token_a = r_login_a.json()["token"]

        r_login_b = cls.client.request("POST", "/api/auth/login", json_body={"email": "runner_b@beta.io", "password": "PassB123!"})
        assert r_login_b.status_code == 200, r_login_b.text
        cls.token_b = r_login_b.json()["token"]

    def _reset_queues(self):
        now_iso = (datetime.now() - timedelta(minutes=5)).isoformat()
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM command_results")
            cursor.execute("DELETE FROM commands")
            cursor.execute("DELETE FROM devices")
            cursor.execute("DELETE FROM leads_en_secuencia")
            cursor.execute("DELETE FROM pasos_secuencia")
            cursor.execute("DELETE FROM secuencias")
            cursor.execute("DELETE FROM leads")
            cursor.execute("DELETE FROM historial_actividades")
            cursor.execute("DELETE FROM lead_activity")

            leads = [
                ("lead_a1", "ten_a", "Alice Alpha", "Colegio Alpha", "Directora", "https://www.linkedin.com/in/alice-alpha", "alice@alpha.edu", "NUEVO"),
                ("lead_b1", "ten_b", "Bob Beta", "Colegio Beta", "Rector", "https://www.linkedin.com/in/bob-beta", "bob@beta.edu", "NUEVO"),
            ]
            for l_id, t_id, nombre, inst, cargo, url, email, est in leads:
                cursor.execute(
                    """
                    INSERT INTO leads (id, tenant_id, nombre, institucion_actual, cargo_actual, perfil_url, email, estado, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (l_id, t_id, nombre, inst, cargo, url, email, est, now_iso)
                )

            seqs = [
                ("seq_a", "ten_a", "Secuencia Alpha"),
                ("seq_b", "ten_b", "Secuencia Beta"),
            ]
            for s_id, t_id, s_name in seqs:
                cursor.execute(
                    """
                    INSERT INTO secuencias (id, tenant_id, nombre, activa, estado, created_at)
                    VALUES (?, ?, ?, 1, 'PUBLICADA', ?)
                    """,
                    (s_id, t_id, s_name, now_iso)
                )

            steps = [
                ("step_a_1", "seq_a", 1, "VISITAR_PERFIL", '{"nota": "Hola {{nombre}}"}'),
                ("step_a_2", "seq_a", 2, "ENVIAR_INVITACION", '{"nota": "Conectemos {{nombre}}"}'),
                ("step_b_1", "seq_b", 1, "VISITAR_PERFIL", '{"nota": "Hola {{nombre}} Beta"}'),
            ]
            for st_id, s_id, orden, tipo, params_json in steps:
                cursor.execute(
                    """
                    INSERT INTO pasos_secuencia (id, secuencia_id, orden, tipo_accion, parametros_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (st_id, s_id, orden, tipo, params_json)
                )

            enrollments = [
                ("enr_a1", "lead_a1", "seq_a", "step_a_1", "EN_CURSO", now_iso),
                ("enr_b1", "lead_b1", "seq_b", "step_b_1", "EN_CURSO", now_iso),
            ]
            for e_id, l_id, s_id, st_id, estado, prox in enrollments:
                cursor.execute(
                    """
                    INSERT INTO leads_en_secuencia (id, lead_id, secuencia_id, paso_actual_id, estado, proxima_ejecucion_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (e_id, l_id, s_id, st_id, estado, prox, now_iso)
                )
            conn.commit()

    def test_01_runner_without_session_does_not_obtain_tasks(self):
        """1 y 7. Runner sin sesión se detiene en autenticacion_requerida, no hace polling y no obtiene tareas."""
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k1")})
        res = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertTrue(res["ok"])
        self.assertFalse(res["wasActive"], "El runner debe detener el bucle al carecer de sesión")
        self.assertEqual(res["status"]["fase"], "autenticacion_requerida")
        self.assertTrue(res["status"]["requiere_autenticacion"])
        self.assertEqual(len(res["executedActions"]), 0)
        self.assertEqual(len(res["httpHistory"]), 0)

    def test_02_expired_session_stops_runner_without_infinite_loops(self):
        """5 y 7. Sesión expirada (HTTP 401) detiene el runner sin iniciar ejecuciones ni bucles ilimitados."""
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k2")})

        # Crear token expirado en auth_service
        auth_service.ACTIVE_SESSIONS["tok_expired_runner"] = {
            **auth_service.ACTIVE_SESSIONS[self.token_a],
            "expires_at": 1.0
        }
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": "tok_expired_runner"})
        res = self.bridge.call({"type": "cmd", "action": "run_cycle"})

        self.assertFalse(res["wasActive"], "El bucle debe detenerse tras recibir HTTP 401")
        self.assertEqual(res["status"]["fase"], "autenticacion_requerida")
        self.assertTrue(res["status"]["requiere_autenticacion"])
        self.assertEqual(len(res["executedActions"]), 0)
        # Solo debió consultar /api/auth/sesion (401) y detenerse sin llamar a /api/worker/proxima-tarea
        urls = [h["url"] for h in res["httpHistory"]]
        self.assertTrue(any("/api/auth/sesion" in u for u in urls))
        self.assertFalse(any("/api/worker/proxima-tarea" in u for u in urls))

    def test_03_tampered_tenant_rejected_with_403_and_stops_runner(self):
        """3 y 7. Manipular el tenant en el runner (usuario de ten_a pidiendo ten_b) recibe 403 y detiene el runner."""
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k3")})
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": self.token_a, "tenantId": "ten_b"})

        res = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertFalse(res["wasActive"], "El bucle debe detenerse tras recibir HTTP 403")
        self.assertEqual(res["status"]["fase"], "error")
        self.assertTrue(res["status"]["error_autorizacion"])
        self.assertEqual(len(res["executedActions"]), 0)

        # Verificar que la tarea de ten_b sigue intacta en la base de datos
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_b1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")
            cursor.execute("SELECT COUNT(*) as total FROM commands WHERE tenant_id = 'ten_b'")
            self.assertEqual(cursor.fetchone()["total"], 0)

    def test_04_legitimate_end_to_end_login_dispatch_execution_and_report(self):
        """2, 8 y 10. Runner autenticado obtiene únicamente tareas de su propio tenant, ejecuta, firma con Ed25519 y consolida en BD; cuando la cola queda vacía entra en espera_cola sin tocar ten_b."""
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k4")})
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": self.token_a})

        # Ciclo 1: ejecuta paso 1 de lead_a1 (ten_a)
        res1 = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertTrue(res1["ok"])
        self.assertEqual(len(res1["executedActions"]), 1)
        self.assertEqual(res1["executedActions"][0]["action"], "LI_VISIT_PROFILE")
        self.assertEqual(res1["executedActions"][0]["params"]["lead_id"], "lead_a1")
        self.assertEqual(res1["status"]["tenant_id"], "ten_a")
        self.assertIsNotNone(res1["status"]["ultima_accion"])
        self.assertTrue(res1["status"]["ultima_accion"]["confirmado_servidor"])
        self.assertEqual(res1["status"]["ultima_accion"]["siguiente_paso_id"], "step_a_2")

        # Verificar en BD que lead_a1 avanzó a step_a_2 y lead_b1 (ten_b) no fue tocado
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_a1'")
            self.assertEqual(cursor.fetchone()["estado"], "PERFIL_VISITADO")
            cursor.execute("SELECT paso_actual_id, estado FROM leads_en_secuencia WHERE id = 'enr_a1'")
            enr_a = cursor.fetchone()
            self.assertEqual(enr_a["paso_actual_id"], "step_a_2")
            self.assertEqual(enr_a["estado"], "EN_CURSO")
            cursor.execute("SELECT status FROM commands WHERE tenant_id = 'ten_a'")
            self.assertEqual(cursor.fetchone()["status"], "EXECUTED")
            # Tenant B intacto
            cursor.execute("SELECT estado FROM leads WHERE id = 'lead_b1'")
            self.assertEqual(cursor.fetchone()["estado"], "NUEVO")

            # Poner proxima_ejecucion_at de enr_a1 en el futuro para simular cola vacía en ten_a
            cursor.execute(
                "UPDATE leads_en_secuencia SET proxima_ejecucion_at = ? WHERE id = 'enr_a1'",
                ((datetime.now() + timedelta(hours=2)).isoformat(),)
            )
            conn.commit()

        # Ciclo 2: Cola de ten_a vacía (aunque ten_b tiene lead_b1 listo) -> espera_cola sin tocar ten_b
        res2 = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["status"]["fase"], "espera_cola")
        self.assertEqual(len(res2["executedActions"]), 1, "No debe haber ejecutado ninguna tarea adicional")

    def test_05_revoked_device_stops_runner_and_blocks_dispatch(self):
        """4. Un dispositivo revocado no puede continuar despachando tareas y detiene el runner."""
        self._reset_queues()
        init_res = self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k5")})
        dev_id = init_res["status"]["device_id"]
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": self.token_a})

        # Registrar primero el dispositivo y luego revocarlo en el backend via /api/devices/revoke
        with database.get_db() as conn:
            cursor = conn.cursor()
            # Dejar la cola de ten_a vacía para el primer ciclo de registro
            cursor.execute(
                "UPDATE leads_en_secuencia SET proxima_ejecucion_at = ? WHERE id = 'enr_a1'",
                ((datetime.now() + timedelta(hours=1)).isoformat(),)
            )
            conn.commit()

        self.bridge.call({"type": "cmd", "action": "run_cycle"})

        # Revocar el dispositivo mediante el endpoint oficial /api/devices/revoke
        r_rev = self.client.request(
            "POST",
            "/api/devices/revoke",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json_body={"device_id": dev_id, "tenant_id": "ten_a"}
        )
        self.assertEqual(r_rev.status_code, 200)

        # Reactivar tarea en cola e intentar nuevo ciclo con el dispositivo revocado
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE leads_en_secuencia SET proxima_ejecucion_at = ? WHERE id = 'enr_a1'",
                ((datetime.now() - timedelta(minutes=1)).isoformat(),)
            )
            conn.commit()

        res_revoked = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertFalse(res_revoked["wasActive"], "El runner debe detenerse al estar revocado el dispositivo")
        self.assertTrue(res_revoked["status"]["dispositivo_revocado"])
        self.assertEqual(len(res_revoked["executedActions"]), 0)

    def test_06_invalid_signature_and_unconfirmed_backend_report_handling(self):
        """6 y 9. Comando alterado en tránsito no se ejecuta; si el backend falla al confirmar el reporte, no se marca como completado localmente."""
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k6")})
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": self.token_a})

        # Caso A: Alterar comando en tránsito -> verifyCommand rechaza la firma y NO ejecuta la acción
        self.bridge.call({"type": "cmd", "action": "set_mutator", "mode": "tamper_command_sig"})
        res_tamper = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertEqual(len(res_tamper["executedActions"]), 0, "No debe ejecutar un comando cuyo payload fue alterado")
        self.assertIsNone(res_tamper["status"]["ultima_accion"])

        # Caso B: Restaurar tarea y simular fallo HTTP 500 al reportar resultado -> no debe marcarse como confirmado
        self._reset_queues()
        self.bridge.call({"type": "cmd", "action": "init", "keysDir": os.path.join(self.keys_root, "k6b")})
        self.bridge.call({"type": "cmd", "action": "set_session", "sessionToken": self.token_a})
        self.bridge.call({"type": "cmd", "action": "set_mutator", "mode": "fail_report_500"})

        res_unconf = self.bridge.call({"type": "cmd", "action": "run_cycle"})
        self.assertEqual(len(res_unconf["executedActions"]), 1)
        self.assertIsNone(res_unconf["status"]["ultima_accion"], "No debe confirmar ultima_accion si el backend no aceptó el reporte")
        self.assertIn("no confirmado", res_unconf["status"]["accion_actual"])


if __name__ == "__main__":
    unittest.main()
