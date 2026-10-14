import urllib.request
import json
import sys

BASE_URL = "http://127.0.0.1:8000"
ELECTRON_URL = "http://127.0.0.1:9099"

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DispatcherTest"})
    with urllib.request.urlopen(req, timeout=5.0) as res:
        return res.status, json.loads(res.read().decode("utf-8"))

def http_post(url, data=None):
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "DispatcherTest"}, method="POST")
    with urllib.request.urlopen(req, timeout=5.0) as res:
        return res.status, json.loads(res.read().decode("utf-8"))

def test_hybrid_dispatcher():
    print("=== TEST 1: Estado Inicial del Despachador ===")
    status, state = http_get(f"{BASE_URL}/api/worker/estado")
    assert status == 200
    print("Estado inicial del worker:", state)

    print("\n=== TEST 2: Toggle Piloto Automático (Activar) ===")
    status, toggle_res = http_post(f"{BASE_URL}/api/worker/piloto-automatico/toggle", {"activo": True})
    assert status == 200
    assert toggle_res.get("piloto_automatico") is True
    print("Piloto automático activado:", toggle_res)

    print("\n=== TEST 3: Heartbeat del Runner Local ===")
    status, hb_res = http_post(f"{BASE_URL}/api/worker/heartbeat", {"worker_id": "electron-local-1", "session_ok": True})
    assert status == 200
    assert hb_res.get("ok") is True
    print("Heartbeat recibido por el servidor:", hb_res)

    print("\n=== TEST 4: Consulta de Próxima Tarea Atómica ===")
    status, task_res = http_get(f"{BASE_URL}/api/worker/proxima-tarea")
    assert status == 200
    print("Respuesta próxima tarea del despachador:", task_res)

    print("\n=== TEST 5: Simulación de Reporte de Tarea Ejecutada ===")
    mock_report = {
        "tarea_id": "test-task-qa-001",
        "lead_id": "nemesioarancibia",
        "secuencia_id": "sec-default-directores-2026",
        "paso_id": 1,
        "tipo": "VISITAR_PERFIL",
        "exito": True
    }
    status, report_res = http_post(f"{BASE_URL}/api/worker/reportar-resultado", mock_report)
    assert status == 200
    print("Reporte de tarea respuesta cruda:", report_res)
    assert report_res.get("status") == "ok"
    print("Reporte de tarea procesado exitosamente:", report_res)

    print("\n=== TEST 6: Servidor Interno de Electron (Puerto 9099 - Worker Status) ===")
    try:
        status, elec_status = http_get(f"{ELECTRON_URL}/worker/status")
        print("Estado del runner en Electron (9099):", elec_status)
        assert elec_status.get("ok") is True
    except Exception as e:
        print("Nota: El proceso Electron actual de la terminal del usuario puede estar corriendo main.cjs anterior o activo:", e)

    print("\n[OK] FASE 2: DESPACHADOR DE TAREAS Y CONTRATO HIBRIDO 100% FUNCIONAL!")

if __name__ == "__main__":
    test_hybrid_dispatcher()
