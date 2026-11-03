import urllib.request
import json
import time

API_BASE = "http://127.0.0.1:8000"

def test_linkedin_session_flow():
    print("\n--- TEST 1: Estado del Navegador y Detección de Sesión ---")
    req = urllib.request.Request(f"{API_BASE}/api/browser/estado")
    with urllib.request.urlopen(req, timeout=3.0) as res:
        data = json.loads(res.read().decode("utf-8"))
        print("Respuesta /api/browser/estado:", json.dumps(data, indent=2))
        assert "sesion_linkedin_activa" in data, "Falta campo sesion_linkedin_activa"
        assert data["is_electron"] is True, "Electron debería estar corriendo"

    print("\n--- TEST 2: Comportamiento del Despachador sin Sesión de LinkedIn ---")
    # Activar piloto automático para probar
    req_toggle = urllib.request.Request(f"{API_BASE}/api/worker/piloto-automatico/toggle?activo=true", method="POST")
    with urllib.request.urlopen(req_toggle, timeout=3.0) as res:
        toggle_data = json.loads(res.read().decode("utf-8"))
        print("Piloto activado:", toggle_data)

    # Consultar proxima tarea
    req_tarea = urllib.request.Request(f"{API_BASE}/api/worker/proxima-tarea")
    with urllib.request.urlopen(req_tarea, timeout=3.0) as res:
        tarea_data = json.loads(res.read().decode("utf-8"))
        print("Respuesta /api/worker/proxima-tarea (JSON):", json.dumps(tarea_data, indent=2, ensure_ascii=True))
        if not data["sesion_linkedin_activa"]:
            assert tarea_data["hay_tarea"] is False, "No debe despachar tareas si no hay sesión"
            assert tarea_data.get("requiere_login_linkedin") is True, "Debe advertir que requiere login"
            print(">>> EXITO: El despachador bloqueo correctamente la tarea por falta de login de LinkedIn.")

    # Restaurar piloto a pausado por seguridad
    req_pause = urllib.request.Request(f"{API_BASE}/api/worker/piloto-automatico/toggle?activo=false", method="POST")
    urllib.request.urlopen(req_pause, timeout=3.0)
    print("\n--- TODOS LOS CHEQUEOS PASARON SATISFACTORIAMENTE ---")

if __name__ == "__main__":
    test_linkedin_session_flow()
