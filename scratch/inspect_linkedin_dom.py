import urllib.request
import json

def inspect():
    script = """
    (() => {
        const links = Array.from(document.querySelectorAll('a[href*="/in/"]'));
        const linkSamples = links.slice(0, 10).map(a => ({
            href: a.href,
            text: a.innerText.trim(),
            parentText: a.parentElement ? a.parentElement.innerText.slice(0, 80) : ''
        }));
        
        // Buscar contenedores de resultados
        const cards = Array.from(document.querySelectorAll('li, div.entity-result, div[data-view-name*="result"]'));
        const entityResults = document.querySelectorAll('.entity-result, [data-chameleon-result-urn]').length;
        
        return {
            title: document.title,
            currentUrl: window.location.href,
            totalProfileLinks: links.length,
            entityResultsCount: entityResults,
            linkSamples: linkSamples,
            bodyPreview: document.body.innerText.slice(0, 300)
        };
    })()
    """
    payload = json.dumps({"script": script}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:9099/evaluate", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10.0) as res:
        data = json.loads(res.read().decode("utf-8"))
        print(json.dumps(data, indent=2, ensure_ascii=True))

if __name__ == "__main__":
    inspect()
