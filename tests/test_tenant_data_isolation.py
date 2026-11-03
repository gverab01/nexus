import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import json
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"

def request_api(method, endpoint, payload=None, token=None):
    url = f"{BASE_URL}{endpoint}"
    data = json.dumps(payload).encode('utf-8') if payload else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Session-Token"] = token
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"error": body}
        return e.code, parsed

def run_tests():
    print("🚀 Probando Aislamiento Estricto de Datos Multi-Tenant (Leads & Métricas)...")

    # 1. Login Sub-Cliente Operador (San Agustín)
    _, res = request_api("POST", "/api/auth/login", {"email": "director@sanagustin.cl", "password": "san123"})
    client_token = res["token"]

    status, p_client = request_api("GET", "/api/prospectos", token=client_token)
    assert status == 200, f"Error obteniendo prospectos de cliente: {p_client}"
    assert p_client["total"] == 1, f"Fallo aislamiento: Operador de San Agustín debía ver 1 lead, vio {p_client['total']}"
    assert p_client["leads"][0]["tenant_id"] == "ten_sanagustin"
    print(f"✅ 1. Operador San Agustín ve únicamente su propio lead ({p_client['total']} lead, tenant_id='ten_sanagustin').")

    status, m_client = request_api("GET", "/api/metricas", token=client_token)
    assert status == 200
    assert m_client["total_leads"] == 1, f"Métricas debían reflejar 1 lead, reflejan {m_client['total_leads']}"
    print(f"✅ 2. Métricas del operador San Agustín aisladas: total_leads = {m_client['total_leads']}.")

    # 2. Login Agencia Admin (GrowthX)
    _, res = request_api("POST", "/api/auth/login", {"email": "agencia@growthx.com", "password": "growth123"})
    agency_token = res["token"]

    # Vista de la agencia sin cliente seleccionado: solo ve su espacio propio, NUNCA mezcla leads de clientes
    status, p_agency_all = request_api("GET", "/api/prospectos", token=agency_token)
    assert status == 200
    assert p_agency_all["total"] == 0, f"Violación de aislamiento: La agencia no debe ver leads de clientes mezclados, vio {p_agency_all['total']}"
    print(f"✅ 3. Aislamiento Estricto: Agencia GrowthX sin cliente seleccionado solo ve su sede propia (0 leads, sin mezclar clientes).")

    # Filtro específico al entrar al workspace de un cliente de su cartera
    status, p_agency_san = request_api("GET", "/api/prospectos?tenant_id=ten_sanagustin", token=agency_token)
    assert status == 200
    assert p_agency_san["total"] == 1
    print(f"✅ 4. Agencia GrowthX entra al workspace de San Agustín y ve únicamente los leads de esa empresa ({p_agency_san['total']} lead).")

    # Intento de la agencia de espiar datos de otra empresa ajena (ten_techcorp) -> Debe retornar 403 Forbidden!
    status, p_forbidden = request_api("GET", "/api/prospectos?tenant_id=ten_techcorp", token=agency_token)
    assert status == 403, f"Violación de aislamiento! Esperaba 403, obtuve {status}: {p_forbidden}"
    print("🛡️ 5. OWASP Validado: Agencia bloqueada con 403 al intentar consultar workspace de otra empresa ajena.")

    # 3. Login Super Admin (Global)
    _, res = request_api("POST", "/api/auth/login", {"email": "admin@nexusreach.com", "password": "admin123"})
    admin_token = res["token"]

    # Super Admin en su consola master no tiene sopa global de leads
    status, p_admin_all = request_api("GET", "/api/prospectos?limit=200", token=admin_token)
    assert status == 200
    # No mezcla leads de sanagustin ni otras empresas: solo ve ten_superadmin
    assert all(l.get("tenant_id") == "ten_superadmin" for l in p_admin_all["leads"])
    print(f"✅ 6. Super Admin sin workspace no mezcla prospectos de otras empresas ({p_admin_all['total']} leads propios administrativos).")

    # Super Admin entra a prospectar/auditar en un workspace de operador específico
    status, p_admin_filtered = request_api("GET", "/api/prospectos?tenant_id=ten_sanagustin", token=admin_token)
    assert status == 200
    assert p_admin_filtered["total"] == 1
    print(f"✅ 7. Super Admin entra al workspace del operador San Agustín y ve únicamente sus datos ({p_admin_filtered['total']} lead).")

    print("\n🎉 TODOS LOS 7 TESTS DE AISLAMIENTO MULTI-TENANT PASARON EXITOSAMENTE!")

if __name__ == "__main__":
    run_tests()
