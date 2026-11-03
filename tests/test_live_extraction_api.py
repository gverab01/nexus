import urllib.request
import json

def test_api_search():
    url = "http://127.0.0.1:8000/api/extraccion/buscar?termino=Encargado%20de%20Convivencia%20Escolar&pagina=1&auto_guardar=true"
    print(f"Probando endpoint: {url}")
    req = urllib.request.Request(url, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=25.0) as res:
        data = json.loads(res.read().decode("utf-8"))
        print("\n=== RESPUESTA DE EXTRACCIÓN ===")
        print(f"Status: {data.get('status')}")
        print(f"Total encontrados: {data.get('total_encontrados')}")
        print(f"Nuevos importados: {data.get('nuevos_importados')}")
        print(f"Duplicados omitidos: {data.get('duplicados_omitidos')}")
        print("\nPrimeros 3 leads:")
        for idx, l in enumerate(data.get("leads", [])[:3]):
            nombre = l.get("nombre", "").encode("ascii", "replace").decode("ascii")
            cargo = l.get("cargo_titular", "").encode("ascii", "replace").decode("ascii")
            col = l.get("institucion_actual", "").encode("ascii", "replace").decode("ascii")
            print(f"  {idx+1}. {nombre} | {cargo[:40]}... | {col}")

if __name__ == "__main__":
    test_api_search()
