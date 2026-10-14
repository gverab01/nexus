import os
import sys

# Agregar ruta raíz al path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import browser_service

def test_browser_service_with_electron():
    print("=== TEST 1: browser_service.is_browseros_running() con Electron ===")
    running = browser_service.is_browseros_running()
    is_elec = browser_service.is_electron_running()
    print(f"is_browseros_running: {running} | is_electron_running: {is_elec}")
    assert running is True
    assert is_elec is True

    print("\n=== TEST 2: browser_service.abrir_perfil_en_browseros(...) ===")
    test_url = "https://example.com/test-profile"
    res_nav = browser_service.abrir_perfil_en_browseros(test_url, "Nemesio Arancibia")
    print("Resultado Navegación:", res_nav)
    assert res_nav.get("status") == "ok"
    assert res_nav.get("tipo") == "electron_isolated"

    print("\n=== TEST 3: browser_service._call_mcp_evaluate(...) ===")
    eval_res = browser_service._call_mcp_evaluate("document.title")
    print("Resultado Evaluate:", eval_res)
    assert eval_res.get("ok") is True
    assert "Example Domain" in str(eval_res.get("value", ""))

    print("\n[OK] INTEGRACION BROWSER_SERVICE -> ELECTRON 100% FUNCIONAL Y FLUIDA!")

if __name__ == "__main__":
    test_browser_service_with_electron()
