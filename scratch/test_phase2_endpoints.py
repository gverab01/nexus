import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.request
import urllib.error
import json
import sqlite3

BASE_URL = "http://127.0.0.1:8000/api"

def make_req(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

print("\n--- TEST 1: FINANZAS DE LA AGENCIA GROWTHX ---")
st, data = make_req("/agencia/ten_growthx/finanzas")
print("Status:", st)
print("Resumen Bolsa:", data["resumen_bolsa"])
print("Consolidado Financiero:", data["consolidado_financiero"])
for c in data["clientes"]:
    print(f"- {c['razon_social']} ({c['modelo_cobro']}): Facturación: ${c['facturacion_cliente']} | Costo: ${c['costo_plataforma']} | Margen: ${c['margen_neto']}")

print("\n--- TEST 2: CONVERTIR UN LEAD A 'REUNION_AGENDADA' ---")
# Obtener un lead de la DB para marcarlo como reunión
conn = sqlite3.connect("leads.db")
lead_row = conn.execute("SELECT id FROM leads LIMIT 1").fetchone()
lead_id = lead_row[0]

# Asignar temporalmente este lead al cliente Colegio San Agustín
conn.execute("UPDATE leads SET tenant_id = 'ten_sanagustin' WHERE id = ?", (lead_id,))
conn.commit()
conn.close()

st_meet, data_meet = make_req(f"/leads/{lead_id}/reunion", method="POST", data={})
print(f"Lead {lead_id} marcado como reunión:", st_meet, data_meet)

# Re-consultar finanzas para comprobar que la facturación del colegio aumentó automáticamente en $150
st2, data2 = make_req("/agencia/ten_growthx/finanzas")
print("Nueva Facturación Agencia:", data2["consolidado_financiero"])
for c in data2["clientes"]:
    if c["id"] == "ten_sanagustin":
        print(f"-> Colegio San Agustín: Reuniones: {c['reuniones_agendadas']} | Facturación: ${c['facturacion_cliente']} | Margen: ${c['margen_neto']}")

print("\n--- TEST 3: CONTROL ESTRICTO DE PUESTOS EN TECHCORP (3 puestos) ---")
# TechCorp tiene 3 puestos (2 en uso actualmente).
# Crear usuario 3 (debe tener éxito)
st_u3, data_u3 = make_req("/tenants/ten_techcorp/usuarios", method="POST", data={
    "email": "nuevo3@techcorp.com",
    "password": "pass",
    "nombre": "Tercer Colaborador",
    "rol": "COMPANY_MEMBER"
})
print("Crear Usuario 3 (Cupo disponible):", st_u3, data_u3.get("exito"))

# Intentar crear usuario 4 (debe ser RECHAZADO por falta de puestos)
st_u4, data_u4 = make_req("/tenants/ten_techcorp/usuarios", method="POST", data={
    "email": "exceso4@techcorp.com",
    "password": "pass",
    "nombre": "Cuarto Colaborador (Exceso)",
    "rol": "COMPANY_MEMBER"
})
print("Crear Usuario 4 (Exceso de bolsa):", st_u4, data_u4.get("detail"))

print("\n--- TEST 4: LIBERAR PUESTO Y REASIGNAR ---")
if st_u3 == 200:
    uid3 = data_u3["usuario"]["id"]
    # Desactivar puesto del usuario 3
    st_lib, data_lib = make_req(f"/usuarios/{uid3}/puesto", method="PATCH", data={"puesto_activo": 0})
    print("Liberar Puesto de Usuario 3:", st_lib, data_lib)

    # Ahora que se liberó el puesto, crear usuario 4 debe tener ÉXITO
    st_re, data_re = make_req("/tenants/ten_techcorp/usuarios", method="POST", data={
        "email": "reemplazo4@techcorp.com",
        "password": "pass",
        "nombre": "Colaborador Reemplazo",
        "rol": "COMPANY_MEMBER"
    })
    print("Crear Usuario de Reemplazo en Puesto Liberado:", st_re, data_re.get("exito"))
