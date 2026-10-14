import urllib.request
import json

res = urllib.request.urlopen('http://127.0.0.1:8000/api/tenants')
data = json.loads(res.read().decode('utf-8'))
print(f"Total Tenants retornados por la API: {len(data)}")
for t in data:
    puestos = f"{t.get('puestos_ocupados')}/{t.get('puestos_contratados')}"
    print(f"- {t['razon_social']} ({t['tipo_tenant']}) | Puestos: {puestos} | Estado: {t.get('sub_estado')}")

# Test subtenants de la agencia
res_agency = urllib.request.urlopen('http://127.0.0.1:8000/api/agencia/ten_growthx/clientes')
sub_data = json.loads(res_agency.read().decode('utf-8'))
print(f"\nSub-clientes de Agencia GrowthX (API): {len(sub_data)}")
for c in sub_data:
    print(f"- Cliente: {c['razon_social']} | Modelo: {c['modelo_cobro_cliente']} | Puestos: {c['puestos_usados']}/{c['puestos_asignados']}")
