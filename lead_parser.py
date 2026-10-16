import re
from typing import Tuple

ACADEMIC_OR_FLUFF = [
    r'^(mag[ií]ster|mg\.?|master|mba|phd|diplomad[oa]|doctor[a]?|licenciad[oa]|post[g-]?grado)\b',
    r'^(ayudo|helping|apasionad[oa]|transformando|buscando|abiert[oa]|speaker|conferencista|top voice|creador[a]?|liderazgo|innovaci[oó]n|educaci[oó]n)\b',
    r'^(ex-|former\s)\b',
    r'^(estudiante|alumno|postulante)\b'
]

COMMON_TITLES_PREFIX = [
    r'^director[a]?\s+general\b',
    r'^director[a]?\s+ejecutiv[oa]\b',
    r'^director[a]?\s+acad[eé]mic[oa]\b',
    r'^director[a]?\s+administrativ[oa]\b',
    r'^director[a]?\s+de\s+estudios\b',
    r'^director[a]?\s+de\s+carrera\b',
    r'^director[a]?\s+de\s+admisi[oó]n\b',
    r'^director[a]?\s+de\s+operaciones\b',
    r'^director[a]?\s+de\s+colegio\b',
    r'^director[a]?\s+escolar\b',
    r'^director[a]?\b',
    r'^subdirector[a]?\b',
    r'^inspector[a]?\s+general\b',
    r'^inspector[a]?\b',
    r'^gerente\s+general\b',
    r'^gerente\s+de\s+operaciones\b',
    r'^gerente\b',
    r'^general\s+manager\b',
    r'^managing\s+director\b',
    r'^c-level\s+executive\b',
    r'^ceo\b',
    r'^co-?founder\b',
    r'^fundador[a]?\b',
    r'^rector[a]?\b',
    r'^vicerrector[a]?\b',
    r'^jefe\s+de\s+utp\b',
    r'^jefe\b',
    r'^jefa\b',
    r'^coordinador[a]?\s+de\s+convivencia\s+escolar\b',
    r'^coordinador[a]?\s+acad[eé]mic[oa]\b',
    r'^coordinador[a]?\b',
    r'^encargad[oa]\s+de\s+convivencia\s+escolar\b',
    r'^encargad[oa]\b',
    r'^profesor[a]?\b',
    r'^docente\b',
    r'^psic[oó]log[oa]\s+educacional\b',
    r'^psic[oó]log[oa]\s+convivencia\s+escolar\b',
    r'^psic[oó]log[oa]\b',
    r'^sostenedor[a]?\b',
    r'^abogad[oa]\b',
    r'^ingeniero[a]?\b',
    r'^consultor[a]?\b',
    r'^asesor[a]?\b'
]

def is_fluff_or_academic(text: str) -> bool:
    clean = text.strip().lower()
    return any(re.search(pat, clean, re.IGNORECASE) for pat in ACADEMIC_OR_FLUFF)

def parse_cargo_and_institucion(headline: str, snippet_actual: str = "", default_institucion: str = "") -> Tuple[str, str]:
    """
    Extrae de forma precisa el cargo actual ('cargo_actual') y la institución u organización ('institucion_actual')
    a partir del snippet directo de LinkedIn ('Actual: ...') o del titular / headline del usuario.
    """
    headline = (headline or "").strip()
    snippet_actual = (snippet_actual or "").strip()
    
    cargo_actual = ""
    institucion = (default_institucion or "").strip()
    if institucion in ["Institución Escolar", "Chile"]:
        institucion = ""

    # 1. Prioridad: Snippet explícito de LinkedIn: "Actual: Director de Colegio en San Ignacio" o "Current: Managing Director at X"
    if snippet_actual:
        clean_snip = re.sub(r'^(Actual|Current|Experiencia actual)\s*:\s*', '', snippet_actual, flags=re.IGNORECASE).strip()
        if clean_snip and not is_fluff_or_academic(clean_snip):
            if re.search(r'\s+en\s+', clean_snip, re.IGNORECASE):
                parts = re.split(r'\s+en\s+', clean_snip, maxsplit=1, flags=re.IGNORECASE)
                cargo_actual = parts[0].strip()
                if not institucion and len(parts) > 1:
                    institucion = parts[1].strip()
            elif re.search(r'\s+at\s+', clean_snip, re.IGNORECASE):
                parts = re.split(r'\s+at\s+', clean_snip, maxsplit=1, flags=re.IGNORECASE)
                cargo_actual = parts[0].strip()
                if not institucion and len(parts) > 1:
                    institucion = parts[1].strip()
            else:
                cargo_actual = clean_snip

    # 2. Si no hay snippet directo, analizar el titular / headline
    if not cargo_actual and headline:
        # Limpiar emojis o caracteres decorativos iniciales
        clean_head = re.sub(r'^[^\w\s]+', '', headline).strip()

        # Segmentar por separadores habituales de LinkedIn: | , ; • · – — y ' - '
        segments = [s.strip() for s in re.split(r'\s*(?:[|;•·\n\–\—]|\s-\s)\s*', clean_head) if s.strip()]

        # Si no hay barras pero hay '/' con roles (ej: Director de Colegio/ Líder Educativo Senior)
        if len(segments) <= 1 and '/' in clean_head:
            sub_segs = [s.strip() for s in clean_head.split('/') if s.strip()]
            if len(sub_segs) > 1:
                segments = sub_segs

        # Descartar segmentos que sean puramente académicos o slogans promocionales
        viable_segments = [s for s in segments if not is_fluff_or_academic(s)]
        if not viable_segments:
            viable_segments = segments

        # Buscar el segmento que contenga relación laboral " en " o " at " o "@"
        best_segment = ""
        for seg in viable_segments:
            if re.search(r'\b(en|at|@)\b', seg, re.IGNORECASE):
                best_segment = seg
                break
        
        # Si no tiene "en", buscar prefijos de cargos conocidos
        if not best_segment:
            for seg in viable_segments:
                if any(re.search(pat, seg, re.IGNORECASE) for pat in COMMON_TITLES_PREFIX):
                    best_segment = seg
                    break

        if not best_segment:
            best_segment = viable_segments[0]

        # Descomponer best_segment en Puesto y Empresa
        # Caso A: Separador explícito ' en ' o ' at ' o ' @ '
        if re.search(r'\s+(?:en|at|@)\s+', best_segment, re.IGNORECASE):
            parts = re.split(r'\s+(?:en|at|@)\s+', best_segment, maxsplit=1, flags=re.IGNORECASE)
            cargo_actual = parts[0].strip()
            comp = parts[1].strip()
            if not institucion and comp:
                institucion = comp
        # Caso B: Separador por institución escolar explícita (Colegio, Liceo, Escuela, Universidad, Instituto, etc.)
        else:
            comp_match = re.search(r'\b(Colegio|Liceo|Escuela|Universidad|Instituto|Fundaci[oó]n|Red\s+de\s+Colegios|Rappi|TOP PARTNERS)\b', best_segment, re.IGNORECASE)
            if comp_match and comp_match.start() > 2:
                prefix = best_segment[:comp_match.start()].strip()
                company_part = best_segment[comp_match.start():].strip()
                if prefix.lower() in ["director de", "coordinador de", "encargado de", "jefe de"]:
                    cargo_actual = best_segment
                else:
                    cargo_actual = prefix
                    if not institucion and company_part:
                        institucion = company_part
            else:
                cargo_actual = best_segment

    # Limpiezas finales de cargo_actual
    cargo_actual = re.sub(r'[\/|;,\-–—]+$', '', cargo_actual).strip()
    cargo_actual = re.sub(r'^[\/|;,\-–—]+', '', cargo_actual).strip()
    # Eliminar preposiciones colgantes al final
    cargo_actual = re.sub(r'\s+(?:de|del|en|at|para|por)\s*$', '', cargo_actual, flags=re.IGNORECASE).strip()

    # Si aún tiene '/' (ej: General Manager/Business Manager), tomar el primero
    if '/' in cargo_actual and not re.search(r'\b(y|and)\b', cargo_actual):
        cargo_actual = cargo_actual.split('/')[0].strip()

    # Truncado elegante si supera 60 caracteres
    if len(cargo_actual) > 60:
        cargo_actual = cargo_actual[:60].rsplit(' ', 1)[0].strip()

    # Normalizar capitalización si venía todo en minúsculas
    if cargo_actual.islower():
        cargo_actual = cargo_actual.title()

    if not cargo_actual or cargo_actual.upper() in ['CHILE', 'PROFESIONAL']:
        cargo_actual = 'Profesional / Directivo'

    if not institucion:
        institucion = default_institucion or ''

    institucion = re.sub(r'[|,;·•].*$', '', institucion).strip()
    institucion = re.sub(r'[\/|;,\-–—]+$', '', institucion).strip()

    return cargo_actual, institucion

