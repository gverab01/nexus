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
    print("🚀 Iniciando Test de Integración End-to-End Multi-Tenant...")

    # 1. Login Super Admin
    status, res = request_api("POST", "/api/auth/login", {"email": "admin@nexusreach.com", "password": "admin123"})
    assert status == 200, f"Login Super Admin falló: {res}"
    admin_token = res["token"]
    print("✅ 1. Login Super Admin exitoso. Token:", admin_token[:10] + "...")

    # Super Admin consulta tenants
    status, tenants = request_api("GET", "/api/tenants", token=admin_token)
    assert status == 200, f"Error listando tenants: {tenants}"
    print(f"✅ 2. Super Admin obtuvo {len(tenants)} organizaciones registradas.")

    # 2. Login Agency Admin
    status, res = request_api("POST", "/api/auth/login", {"email": "agencia@growthx.com", "password": "growth123"})
    assert status == 200, f"Login Agency Admin falló: {res}"
    agency_token = res["token"]
    print("✅ 3. Login Agency Admin exitoso.")

    # Consulta finanzas de agencia
    status, fin = request_api("GET", "/api/agencia/ten_growthx/finanzas", token=agency_token)
    assert status == 200, f"Error obteniendo finanzas: {fin}"
    print("✅ 4. Finanzas de Agencia obtenidas:")
    print(f"   - Bolsa: {fin['resumen_bolsa']['puestos_ocupados']}/{fin['resumen_bolsa']['puestos_contratados']} puestos")
    print(f"   - Facturación a clientes: ${fin['consolidado_financiero']['facturacion_total_clientes']} USD")
    print(f"   - Costo plataforma: ${fin['consolidado_financiero']['costo_total_plataforma']} USD")
    print(f"   - Margen neto agencia: ${fin['consolidado_financiero']['margen_neto_agencia']} USD ({fin['consolidado_financiero']['porcentaje_margen']}%)")

    # Ampliación de bolsa (+1 seat a demanda)
    status, adj = request_api("POST", "/api/tenants/ten_growthx/puestos", {"delta": 1}, token=agency_token)
    assert status == 200, f"Error ajustando puestos: {adj}"
    print(f"✅ 5. Bolsa ampliada dinámicamente: {adj['puestos_contratados']} puestos totales.")

    # 3. Aislamiento y Seguridad: Operador / Sub-Cliente (director@sanagustin.cl)
    status, res = request_api("POST", "/api/auth/login", {"email": "director@sanagustin.cl", "password": "san123"})
    assert status == 200, f"Login Sub-cliente falló: {res}"
    client_token = res["token"]
    print("✅ 6. Login Operador / Sub-Cliente exitoso.")

    # Intento de acceso a endpoints de Super Admin -> Debe retornar 403 Forbidden
    status, forbidden_tenants = request_api("GET", "/api/tenants", token=client_token)
    assert status == 403, f"Violación de aislamiento! Esperaba 403, obtuve {status}"
    print("🛡️ 7. OWASP Validado: Operador bloqueado con 403 al intentar acceder a la consola de Super Admin.")

    # Intento de acceso a finanzas de la agencia -> Debe retornar 403 Forbidden
    status, forbidden_fin = request_api("GET", "/api/agencia/ten_growthx/finanzas", token=client_token)
    assert status == 403, f"Violación de aislamiento! Esperaba 403, obtuve {status}"
    print("🛡️ 8. OWASP Validado: Operador bloqueado con 403 al intentar ver finanzas/márgenes de la agencia.")

    # 4. Prueba de Revocación Instantánea
    print("⚠️ 9. Probando Revocación Instantánea de Licencia en vivo...")
    status, rev = request_api("POST", "/api/tenants/ten_fintech/revocar", {"motivo": "Falta de pago"}, token=admin_token)
    assert status == 200, f"Error revocando: {rev}"
    print("   - Licencia de ten_fintech marcada como REVOCADA por Super Admin.")

    # Intento de login del usuario de ten_fintech mientras está revocada
    status, res = request_api("POST", "/api/auth/login", {"email": "sales@fintech.com", "password": "fin123"})
    assert status in [400, 401, 403], f"Esperaba bloqueo de login, obtuve {status}: {res}"
    print(f"✅ 10. Login denegado exitosamente para usuario con licencia revocada ({res.get('codigo')}).")

    # Reactivar licencia
    status, reac = request_api("POST", "/api/tenants/ten_fintech/reactivar", {"dias": 30}, token=admin_token)
    assert status == 200, f"Error reactivando: {reac}"
    print("   - Licencia reactivada exitosamente.")

    # Login ahora debe funcionar
    status, res = request_api("POST", "/api/auth/login", {"email": "sales@fintech.com", "password": "fin123"})
    assert status == 200, f"Login debió funcionar tras reactivar: {res}"
    print("✅ 11. Login restituido inmediatamente tras reactivación.")

    print("\n🎉 TODOS LOS 11 TESTS E2E MULTI-TENANT PASARON CON ÉXITO ROTUNDO!")

if __name__ == "__main__":
    run_tests()
