import urllib.request
import json

def test_extraction_on_electron():
    # Probemos una función de extracción robusta moderna directamente en Electron
    script = """
    (() => {
        const seenUrls = new Set();
        const leads = [];

        // En LinkedIn los resultados de búsqueda de personas son tarjetas 'li' dentro de listas
        // Cada tarjeta suele tener uno o dos links a '/in/nombre-slug/'
        const allProfileLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));

        allProfileLinks.forEach(a => {
            const rawHref = a.href || '';
            const cleanUrl = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
            
            // Ignorar enlaces de contactos en común u otros enlaces secundarios
            if (!cleanUrl.includes('/in/') || cleanUrl.endsWith('/in/')) return;
            if (seenUrls.has(cleanUrl)) return;

            // Encontrar la tarjeta contenedor más cercana
            const card = a.closest('li') || a.closest('.entity-result') || a.parentElement;
            if (!card) return;

            const cardText = card.innerText ? card.innerText.trim() : '';
            const lines = cardText.split('\\n').map(l => l.trim()).filter(Boolean);

            // Validar que sea una tarjeta de resultado y no un widget lateral
            // En una tarjeta de persona, el enlace principal o sus líneas tienen el nombre y grado de red
            let nombre = '';
            let grado = '2º';
            let cargo = '';
            let ubicacion = 'Chile';

            // 1. Extraer nombre del link o de la primera línea relevante
            const linkText = a.innerText.trim();
            if (linkText && !linkText.includes('\\n') && !linkText.includes('contactos en común')) {
                nombre = linkText;
            } else if (lines.length > 0) {
                nombre = lines[0].split('•')[0].split('\\n')[0].trim();
            }

            if (!nombre || nombre.length < 2 || nombre.includes('contactos en común') || nombre.includes('LinkedIn')) {
                return;
            }

            // Limpiar sufijos
            nombre = nombre.replace(/•.*$/g, '').replace(/Verificado|Premium|\\s+/g, ' ').trim();

            // 2. Extraer grado de red (1º, 2º, 3º+)
            for (const line of lines.slice(0, 3)) {
                if (line.includes('1º') || line.includes('1er')) grado = '1º';
                else if (line.includes('2º') || line.includes('2do')) grado = '2º';
                else if (line.includes('3º') || line.includes('3er')) grado = '3º+';
            }

            // 3. Extraer titular/cargo y ubicación
            // En las tarjetas de LinkedIn, la línea que sigue al nombre (o nombre • grado) es el cargo/titular
            // y la siguiente es la ubicación geográfica
            for (let i = 1; i < lines.length; i++) {
                const l = lines[i];
                if (l === grado || l.includes('•') || l.includes('Pendiente') || l.includes('Conectar') || l.includes('Mensaje')) {
                    continue;
                }
                if (!cargo) {
                    cargo = l;
                } else if (!ubicacion || ubicacion === 'Chile') {
                    if (l.includes('Chile') || l.includes('Región') || l.includes('Santiago') || l.includes('Área') || l.includes('Valparaíso') || l.includes('Concepción')) {
                        ubicacion = l;
                        break;
                    }
                }
            }

            // 4. Extraer institución escolar o empresa
            let institucion = '';
            if (cargo.toLowerCase().includes(' en ')) {
                institucion = cargo.split(/ en /i)[1].split(';')[0].split('|')[0].trim();
            } else if (cargo.toLowerCase().includes('colegio')) {
                const m = cargo.match(/colegio[^\\n;|,]+/i);
                if (m) institucion = m[0].trim();
            } else if (cargo.toLowerCase().includes('escuela')) {
                const m = cargo.match(/escuela[^\\n;|,]+/i);
                if (m) institucion = m[0].trim();
            } else if (cargo.toLowerCase().includes('liceo')) {
                const m = cargo.match(/liceo[^\\n;|,]+/i);
                if (m) institucion = m[0].trim();
            } else if (cargo.toLowerCase().includes('red ')) {
                const m = cargo.match(/red [^\\n;|,]+/i);
                if (m) institucion = m[0].trim();
            }

            seenUrls.add(cleanUrl);
            leads.push({
                nombre: nombre,
                grado_red: grado,
                cargo_titular: cargo || 'Docente / Directivo',
                institucion_actual: institucion || 'Institución Escolar',
                ubicacion: ubicacion || 'Chile',
                perfil_url: cleanUrl
            });
        });

        return {
            total: leads.length,
            leads: leads
        };
    })()
    """

    payload = json.dumps({"script": script}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:9099/evaluate", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10.0) as res:
        data = json.loads(res.read().decode("utf-8"))
        print(f"Total leads extraídos en Electron: {data.get('result', {}).get('total', 0)}")
        print("Muestra de leads:")
        for idx, l in enumerate(data.get('result', {}).get('leads', [])[:5]):
            print(f"  {idx+1}. {l['nombre']} | {l['cargo_titular'][:45]}... | {l['institucion_actual']} | {l['perfil_url']}")

if __name__ == "__main__":
    test_extraction_on_electron()
