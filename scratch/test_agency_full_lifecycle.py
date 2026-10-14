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

def run_agency_lifecycle_tests():
    print("🚀 Probando Ciclo Completo de Agencia, Clientes, Operadores y Switcher de Workspace...")

    # 1. Login Administrador de Agencia
    status, auth = request_api("POST", "/api/auth/login", {"email": "agencia@growthx.com", "password": "growth123"})
    assert status == 200, f"Error login agencia: {auth}"
    agency_token = auth["token"]
    print("✅ 1. Login exitoso como Administrador de Agencia GrowthX.")

    # 2. Consultar Cartera & Finanzas de la Agencia
    status, finances = request_api("GET", "/api/agencia/ten_growthx/finanzas", token=agency_token)
    assert status == 200, f"Error obteniendo finanzas: {finances}"
    assert "consolidado" in finances
    assert "clientes" in finances
    print(f"✅ 2. Finanzas de agencia cargadas: {len(finances['clientes'])} clientes en cartera.")

    # 3. Crear Nuevo Cliente en la Cartera de la Agencia
    nuevo_cliente = {
        "razon_social": "Colegio San Francisco Test",
        "modelo_cobro": "POR_REUNION",
        "tarifa_por_reunion": 180.0,
        "precio_cliente_por_puesto": 0.0,
        "fee_fijo_mensual": 0.0,
        "puestos_asignados": 2
    }
    status, cliente_creado = request_api("POST", "/api/agencia/ten_growthx/clientes", nuevo_cliente, token=agency_token)
    assert status == 200, f"Error creando cliente: {cliente_creado}"
    client_id = cliente_creado["cliente"]["id"]
    print(f"✅ 3. Nuevo cliente creado con éxito (ID: {client_id}, Razón: {cliente_creado['cliente']['razon_social']}).")

    # 4. Crear Operador en el Workspace del Cliente
    import time
    ts = int(time.time())
    op_email = f"francisca_{ts}@sanfrancisco-test.cl"
    nuevo_operador = {
        "nombre": "Francisca Operadora",
        "email": op_email,
        "password": "fran123password"
    }
    status, op_res = request_api("POST", f"/api/tenants/{client_id}/usuarios", nuevo_operador, token=agency_token)
    assert status == 200, f"Error creando operador: {op_res}"
    user_id = op_res["usuario"]["id"]
    assert op_res["usuario"]["puesto_activo"] == 1
    print(f"✅ 4. Operador creado en el workspace del cliente (Usuario ID: {user_id}, puesto_activo=1).")

    # 5. Listar Miembros del Cliente
    status, miembros = request_api("GET", f"/api/tenants/{client_id}/miembros", token=agency_token)
    assert status == 200
    assert len(miembros["miembros"]) >= 1
    print(f"✅ 5. Lista de operadores del cliente auditada: {len(miembros['miembros'])} miembro(s).")

    # 6. Desactivar y Activar Puesto del Operador (Seat Toggle)
    # PATCH /api/usuarios/{user_id}/puesto
    status, toggle_off = request_api("PATCH", f"/api/usuarios/{user_id}/puesto", {"puesto_activo": 0}, token=agency_token)
    assert status == 200, f"Error desactivando puesto: {toggle_off}"
    assert toggle_off["usuario"]["puesto_activo"] == 0
    print("✅ 6a. Puesto del operador revocado con éxito (puesto_activo=0).")

    status, toggle_on = request_api("PATCH", f"/api/usuarios/{user_id}/puesto", {"puesto_activo": 1}, token=agency_token)
    assert status == 200, f"Error reactivando puesto: {toggle_on}"
    assert toggle_on["usuario"]["puesto_activo"] == 1
    print("✅ 6b. Puesto del operador reactivado con éxito (puesto_activo=1).")

    # 7. Login como el Nuevo Operador y Verificar Aislamiento
    status, op_auth = request_api("POST", "/api/auth/login", {
        "email": op_email,
        "password": "fran123password"
    })
    assert status == 200, f"Error login operador: {op_auth}"
    op_token = op_auth["token"]
    assert op_auth["usuario"]["rol"] == "COMPANY_MEMBER"
    assert op_auth["usuario"]["tenant_id"] == client_id
    print("✅ 7. Operador logueado correctamente como COMPANY_MEMBER con su tenant asignado.")

    # 8. Operador no puede ver finanzas de la agencia (debe dar 403)
    status, op_fin_forbidden = request_api("GET", "/api/agencia/ten_growthx/finanzas", token=op_token)
    assert status == 403, f"Operador no debió ver finanzas! status: {status}"
    print("🛡️ 8. OWASP Validado: Operador de cliente tiene acceso bloqueado (403) a finanzas y precios de la agencia.")

    # 9. Operador ve 0 prospectos en su espacio vacío inicial
    status, op_leads = request_api("GET", "/api/prospectos", token=op_token)
    assert status == 200
    assert op_leads["total"] == 0
    print(f"✅ 9. Operador ve únicamente su propio directorio aislado ({op_leads['total']} leads).")

    # 10. Agencia Admin crea una lista dentro de este workspace cliente
    nueva_lista = {
        "nombre": "Lista Directores San Francisco",
        "descripcion": "Audiencia objetivo para outreach",
        "termino_busqueda": "Director San Francisco",
        "tenant_id": client_id
    }
    status, lista_res = request_api("POST", "/api/listas", nueva_lista, token=agency_token)
    assert status == 200, f"Error creando lista: {lista_res}"
    print(f"✅ 10. Agencia creó lista en el workspace del cliente ({lista_res.get('nombre')}).")

    # 11. Operador consulta listas y ve la lista creada para su tenant
    status, op_lists = request_api("GET", "/api/listas", token=op_token)
    assert status == 200
    assert any(l["id"] == lista_res["id"] for l in op_lists["listas"])
    print(f"✅ 11. Operador ve la lista configurada en su propio workspace ({len(op_lists['listas'])} lista(s)).")

    # 12. Otra empresa (ej: ten_sanagustin) no ve la lista de San Francisco Test
    status, san_auth = request_api("POST", "/api/auth/login", {"email": "director@sanagustin.cl", "password": "san123"})
    san_token = san_auth["token"]
    status, san_lists = request_api("GET", "/api/listas", token=san_token)
    assert status == 200
    assert not any(l["id"] == lista_res["id"] for l in san_lists["listas"])
    print("🛡️ 12. OWASP Validado: Listas de clientes estrictamente aisladas entre empresas diferentes.")

    # 13. Importar un lead en el workspace del cliente y marcar REUNION_AGENDADA
    nuevo_lead = [{
        "nombre": "Alonso Valenzuela",
        "cargo_titular": "Director Ejecutivo",
        "institucion_actual": "Colegio San Francisco",
        "perfil_url": f"https://www.linkedin.com/in/alonso-valenzuela-{ts}",
        "ubicacion": "Santiago, Chile",
        "grado_red": "2°",
        "email": "alonso@sanfrancisco-test.cl"
    }]
    status, import_res = request_api("POST", "/api/prospectos/importar-lote", {
        "leads": nuevo_lead,
        "lista_id": lista_res["id"],
        "tenant_id": client_id
    }, token=agency_token)
    assert status == 200, f"Error importando lead: {import_res}"

    status, leads_client = request_api("GET", "/api/prospectos", token=op_token)
    assert status == 200 and leads_client["total"] >= 1
    target_lead_id = leads_client["leads"][0]["id"]

    # Marcar reunión comercial
    status, meeting_res = request_api("POST", f"/api/leads/{target_lead_id}/reunion", {
        "fecha_reunion": "2026-10-15",
        "valor_reunion": 180.0
    }, token=op_token)
    assert status == 200, f"Error marcando reunión: {meeting_res}"
    assert meeting_res["estado"] == "REUNION_AGENDADA"
    print(f"✅ 13. Lead marcado como REUNION_AGENDADA (Valor: ${meeting_res['valor_reunion']} USD).")

    # 14. Verificar impacto en finanzas de la agencia
    status, fin_updated = request_api("GET", "/api/agencia/ten_growthx/finanzas", token=agency_token)
    assert status == 200
    client_fin = next((c for c in fin_updated["clientes"] if c["id"] == client_id), None)
    assert client_fin is not None
    assert client_fin["reuniones_agendadas"] >= 1
    assert client_fin["facturacion_cliente"] >= 180.0
    print(f"🎉 14. Impacto financiero en tiempo real validado: {client_fin['razon_social']} facturación = ${client_fin['facturacion_cliente']} USD (Margen: ${client_fin['margen_neto']} USD).")

    print("\n🎉 TODOS LOS 14 TESTS DEL CICLO DE AGENCIA, OPERADORES, WORKSPACES Y CONVERSIONES PASARON EXITOSAMENTE!")

if __name__ == "__main__":
    run_agency_lifecycle_tests()
