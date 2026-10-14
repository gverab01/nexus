import urllib.request
import json
import sys

def test_electron_integration():
    print("=== TEST 1: Estado del Servidor Interno de Electron (Puerto 9099) ===")
    req = urllib.request.Request("http://127.0.0.1:9099/status")
    with urllib.request.urlopen(req, timeout=3.0) as res:
        status_data = json.loads(res.read().decode("utf-8"))
        print("Respuesta Electron /status:", status_data)
        assert status_data.get("ok") is True
        assert status_data.get("tipo") == "ELECTRON_CHROMIUM_ISOLATED"

    print("\n=== TEST 2: Detección Automática en FastAPI (/api/browser/estado) ===")
    req = urllib.request.Request("http://127.0.0.1:8000/api/browser/estado")
    with urllib.request.urlopen(req, timeout=3.0) as res:
        api_data = json.loads(res.read().decode("utf-8"))
        print("Respuesta FastAPI:", api_data)
        assert api_data.get("activo") is True
        assert api_data.get("is_electron") is True
        assert "Electron" in api_data.get("motor", "")

    print("\n=== TEST 3: Navegación Atómica en Chromium Embebido ===")
    nav_payload = json.dumps({"url": "https://example.com"}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:9099/navigate", data=nav_payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15.0) as res:
        nav_data = json.loads(res.read().decode("utf-8"))
        print("Respuesta Navegación:", nav_data)
        assert nav_data.get("ok") is True
        assert "example.com" in nav_data.get("url", "")

    print("\n=== TEST 4: Evaluación de JavaScript en Chromium Embebido ===")
    eval_script = "document.title"
    eval_payload = json.dumps({"script": eval_script}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:9099/evaluate", data=eval_payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5.0) as res:
        eval_data = json.loads(res.read().decode("utf-8"))
        print("Respuesta Evaluación JS:", eval_data)
        assert eval_data.get("ok") is True
        assert eval_data.get("result") == "Example Domain"

    print("\n[OK] FASE 1: INTEGRACION DE CHROMIUM EMBEBIDO AISLADO EXITOSA AL 100%!")

if __name__ == "__main__":
    test_electron_integration()
