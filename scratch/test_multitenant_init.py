import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import auth_service

database.init_db()

print("\n--- TENANTS GLOBALES (Super Admin) ---")
tenants = auth_service.listar_tenants_global()
for t in tenants:
    puestos = f"{t.get('puestos_ocupados')}/{t.get('puestos_contratados')}"
    print(f"- [{t['tipo_tenant']}] {t['razon_social']} (ID: {t['id']}) | Puestos: {puestos} | Suscripción: {t.get('sub_estado')} {t.get('periodicidad')}")

print("\n--- SUB-CLIENTES DE AGENCIA (GrowthX) ---")
subtenants = auth_service.listar_subtenants_agencia("ten_growthx")
for st in subtenants:
    print(f"- [Cliente] {st['razon_social']} | Modelo: {st['modelo_cobro_cliente']} | Puestos: {st['puestos_usados']}/{st['puestos_asignados']}")

print("\n--- PRUEBAS DE AUTENTICACIÓN ---")
test_logins = [
    ("admin@nexusreach.com", "admin123", "Super Admin"),
    ("agencia@growthx.com", "growth123", "Agency Admin"),
    ("director@sanagustin.cl", "san123", "Cliente Agencia (Pay-per-Meeting)"),
    ("sales@fintech.com", "fin123", "Cliente Agencia (Por Puesto)"),
    ("admin@techcorp.com", "tech123", "Company Admin Directo"),
    ("demo@nexusreach.com", "demo123", "Freelancer")
]

for email, pwd, label in test_logins:
    res = auth_service.autenticar_usuario(email, pwd)
    if res["exito"]:
        u = res["usuario"]
        t = u["tenant"] or {}
        s = u["suscripcion"] or {}
        print(f"[OK] {label}: Login OK -> {u['nombre']} | Rol: {u['rol']} | Org: {t.get('razon_social')} | Sub: {s.get('estado')}")
    else:
        print(f"[FALLO] {label}: Fallo -> {res['mensaje']}")
