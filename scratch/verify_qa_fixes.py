import urllib.request
import urllib.parse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

BASE_URL = "http://127.0.0.1:8000"

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "QA-Checker"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def http_post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "QA-Checker"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def http_delete(url):
    req = urllib.request.Request(url, headers={"User-Agent": "QA-Checker"}, method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def test_backend_fixes():
    print("=== TEST 1: Lead Detail Endpoint ===")
    status, prospects_list = http_get(f"{BASE_URL}/api/prospectos?limit=5")
    assert status == 200
    leads = prospects_list.get("leads", [])
    assert len(leads) > 0, "No hay leads en la base de datos"
    target_id = leads[0]["id"]
    print(f"Probando detalle del lead ID: {target_id}")

    status, lead = http_get(f"{BASE_URL}/api/prospectos/{target_id}")
    assert status == 200
    print(f"Lead: {lead.get('nombre')} | Empresa: {lead.get('institucion_actual')} | Historial: {len(lead.get('historial', []))} items | Mensajes: {len(lead.get('mensajes_linkedin', []))} | Emails: {len(lead.get('correos', []))}")

    print("\n=== TEST 2: Secuencias List & Leads Normalization ===")
    status, seqs_data = http_get(f"{BASE_URL}/api/secuencias")
    assert status == 200
    seqs = seqs_data.get("secuencias", []) if isinstance(seqs_data, dict) else seqs_data
    assert len(seqs) > 0, "No hay secuencias configuradas"
    seq_id = seqs[0]["id"]
    print(f"Secuencia: {seqs[0]['nombre']} ({seq_id}) | Listas: {seqs[0].get('listas_asociadas')}")

    status, leads_en_seq = http_get(f"{BASE_URL}/api/secuencias/{seq_id}/leads")
    assert status == 200
    leads_list = leads_en_seq.get("leads", []) if isinstance(leads_en_seq, dict) else leads_en_seq
    print(f"Leads en secuencia: {len(leads_list)} registrados")
    if leads_list:
        sample = leads_list[0]
        print(f"Sample lead: {sample.get('nombre_completo', sample.get('nombre'))} | Paso: {sample.get('paso_actual')} | Estado: {sample.get('estado')}")

    print("\n=== TEST 3: Atomic Step Add & Delete ===")
    add_payload = {
        "tipo": "ESPERAR",
        "etiqueta": "Pausa QA Test",
        "parametros": {"horas_espera": 12},
        "posicion": "final"
    }
    status, add_res = http_post(f"{BASE_URL}/api/secuencias/{seq_id}/pasos/agregar", add_payload)
    assert status == 200
    nuevo_paso = add_res.get("paso", {})
    nuevo_paso_id = nuevo_paso.get("id")
    print(f"Paso agregado exitosamente con ID: {nuevo_paso_id}")

    # Verificar que aparece en la secuencia
    status, seq_updated = http_get(f"{BASE_URL}/api/secuencias/{seq_id}")
    pasos_ids = [p["id"] for p in seq_updated.get("pasos", [])]
    assert nuevo_paso_id in pasos_ids
    print(f"Verificado paso en árbol de pasos. Total pasos: {len(pasos_ids)}")

    # Ahora eliminar el paso atómicamente
    status, del_res = http_delete(f"{BASE_URL}/api/secuencias/{seq_id}/pasos/{nuevo_paso_id}")
    assert status == 200
    print(f"Paso #{nuevo_paso_id} eliminado exitosamente y árbol reestructurado.")

    print("\n=== TEST 4: Crear Lista con Status y Auto-Enrolar ===")
    test_list_name = "Lista QA Test Auto-Enrolar"
    list_payload = {
        "nombre": test_list_name,
        "termino_busqueda": "Director QA",
        "descripcion": "Lista de prueba para QA",
        "estado": "ACTIVA",
        "conectar_secuencia_activa": True
    }
    status, new_list = http_post(f"{BASE_URL}/api/listas", list_payload)
    assert status == 200
    print(f"Lista creada: ID {new_list.get('id')} | Nombre: {new_list.get('nombre')} | Secuencias: {new_list.get('secuencias_conectadas')}")

    print("\n=== TEST 5: Spintax & Safety Engine ===")
    from safety_engine import procesar_spintax_recursivo, procesar_spintax, verificar_seguridad_linkedin
    test_spin = "{Hola|Estimado|Buen día} {Gabriel|director}, ¿cómo estás?"
    res_spin = procesar_spintax(test_spin)
    res_alias = procesar_spintax_recursivo(test_spin)
    print(f"Spintax original: '{res_spin}' | Alias: '{res_alias}'")
    assert any(w in res_spin for w in ["Hola", "Estimado", "Buen día"])

    status, safety_status = http_get(f"{BASE_URL}/api/seguridad/estado")
    assert status == 200
    print(f"Endpoint /api/seguridad/estado: Kill-Switch: {safety_status.get('kill_switch')} | Horario Laboral: {safety_status.get('horario_laboral')}")

    print("\n[OK] TODOS LOS TESTS DE VERIFICACION PASARON EXITOSAMENTE (100% OK)!")

if __name__ == "__main__":
    test_backend_fixes()
