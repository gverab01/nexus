import re
from typing import Tuple

ACADEMIC_OR_FLUFF = [
    r'^(mag[ií]ster|mg\.?|master|mba|phd|diplomad[oa]|doctor[a]?|licenciad[oa]|post[g-]?grado)\b',
    r'^(ayudo|helping|apasionad[oa]|comprometid[oa]|transformando|buscando|abiert[oa]|speaker|conferencista|top voice|creador[a]?|liderazgo|innovaci[oó]n|educaci[oó]n)\b',
    r'^(?:cuando|si\s|por\s|para\s|creo|creemos|generando|construyendo)\b',
    r'^(ex-|former\s)\b',
    r'^(estudiante|alumno|postulante)\b'
]

EMPLOYMENT_TYPES = {
    'jornada completa', 'jornada parcial', 'tiempo completo', 'medio tiempo',
    'profesional independiente', 'autónomo', 'autónoma', 'contrato temporal',
    'contrato de prácticas', 'contrato de formación', 'de temporada', 'en prácticas',
    'full-time', 'part-time', 'self-employed', 'freelance', 'contract', 'internship', 'seasonal'
}

INVALID_ROLES_REGEX = [
    r'^(?:trabajo\s+en\s+equipo|resoluci[oó]n\s+de\s+problemas|comunicaci[oó]n\s+(?:asertiva|efectiva)|liderazgo\s+de\s+equipos|gesti[oó]n\s+del\s+tiempo|adaptabilidad|empat[ií]a|pensamiento\s+cr[ií]tico|aptitudes?|habilidades?|competencias?)\b',
    r'^(?:voluntari[oa]|voluntariado|volunteer)\b'
]

INVALID_INSTITUTIONS_REGEX = [
    r'^(?:voluntariado|voluntario|voluntaria|volunteer)\b',
    r'^(?:sin\s+informaci[oó]n|ningun[oa]|no\s+aplica|n/a)\b'
]

def is_invalid_role(role: str) -> bool:
    if not role:
        return True
    clean = role.strip().lower()
    return any(re.search(pat, clean, re.IGNORECASE) for pat in INVALID_ROLES_REGEX)

def is_invalid_institution(inst: str) -> bool:
    if not inst:
        return True
    clean = inst.strip().lower()
    if clean in EMPLOYMENT_TYPES or clean in ["institución escolar", "chile", "empresa u organización", "institución educativa"]:
        return True
    return any(re.search(pat, clean, re.IGNORECASE) for pat in INVALID_INSTITUTIONS_REGEX)

def refine_pie_institution(institucion: str, role: str = "", headline: str = "", location: str = "") -> str:
    """
    Si la institución es el genérico 'Programa de Integración Escolar' o 'PIE',
    intenta resolver el colegio real mencionado o la comuna/DAEM correspondiente.
    """
    if not institucion:
        return ""
    clean_inst = institucion.strip()
    is_pie = re.search(r'^(?:programa\s+(?:de\s+)?integraci[oó]n\s+escolar|p\.?i\.?e\.?)\b', clean_inst, re.IGNORECASE)
    if not is_pie:
        return clean_inst

    combined = f"{role} {headline}".strip()
    # 1. Buscar si se menciona un colegio o institución educativa específica
    school_match = re.search(r'\b(Colegio|Liceo|Escuela|Instituto|Jard[ií]n|Universidad|DAEM|SLEP|Fundaci[oó]n)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9\s]+?)(?:\s+(?:en|at|@|–|-|\||•|·|\.|\,|$)|$)', combined, re.IGNORECASE)
    if school_match:
        found_school = f"{school_match.group(1)} {school_match.group(2)}".strip()
        found_school = re.sub(r'[\/|;,\-–—]+$', '', found_school).strip()
        if len(found_school) > 5 and not re.search(r'integraci[oó]n|escolar', found_school, re.IGNORECASE):
            return found_school

    # 2. Buscar si la ubicación o descripción aporta una comuna específica
    commune = ""
    if location:
        loc_parts = [p.strip() for p in location.split(',') if p.strip()]
        if loc_parts:
            first_loc = loc_parts[0]
            if first_loc.lower() not in ['chile', 'área metropolitana de santiago', 'gran santiago', 'región metropolitana']:
                commune = first_loc

    if commune:
        return f"Programa de Integración Escolar (PIE - {commune})"
    return "Programa de Integración Escolar (PIE)"

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
    r'^gestor[a]?\b',
    r'^orientador[a]?\b',
    r'^l[ií]der\b',
    r'^facilitador[a]?\b',
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

def parse_cargo_and_institucion(headline: str, snippet_actual: str = "", default_institucion: str = "", location: str = "") -> Tuple[str, str]:
    """
    Extrae de forma precisa el cargo actual ('cargo_actual') y la institución u organización ('institucion_actual')
    a partir del snippet directo de LinkedIn ('Actual: ...') o del titular / headline del usuario.
    """
    headline = (headline or "").strip()
    snippet_actual = (snippet_actual or "").strip()
    
    cargo_actual = ""
    institucion = (default_institucion or "").strip()
    if is_invalid_institution(institucion):
        institucion = ""

    # 1. Prioridad: Snippet explícito de LinkedIn: "Actual: Director de Colegio en San Ignacio" o "Current: Managing Director at X"
    if snippet_actual:
        clean_snip = re.sub(r'^(Actual|Current|Experiencia actual)\s*:\s*', '', snippet_actual, flags=re.IGNORECASE).strip()
        if clean_snip and not is_fluff_or_academic(clean_snip):
            if re.search(r'\s+en\s+', clean_snip, re.IGNORECASE):
                parts = re.split(r'\s+en\s+', clean_snip, maxsplit=1, flags=re.IGNORECASE)
                cand_role = parts[0].strip()
                if not is_invalid_role(cand_role):
                    cargo_actual = cand_role
                if not institucion and len(parts) > 1 and not is_invalid_institution(parts[1]):
                    institucion = parts[1].strip()
            elif re.search(r'\s+at\s+', clean_snip, re.IGNORECASE):
                parts = re.split(r'\s+at\s+', clean_snip, maxsplit=1, flags=re.IGNORECASE)
                cand_role = parts[0].strip()
                if not is_invalid_role(cand_role):
                    cargo_actual = cand_role
                if not institucion and len(parts) > 1 and not is_invalid_institution(parts[1]):
                    institucion = parts[1].strip()
            else:
                if not is_invalid_role(clean_snip):
                    cargo_actual = clean_snip

    # 2. Si no hay snippet directo o el cargo extraído no era válido, analizar el titular / headline
    if not cargo_actual and headline:
        # Limpiar emojis o caracteres decorativos iniciales
        clean_head = re.sub(r'^[^\w\s]+', '', headline).strip()

        # Segmentar por separadores habituales de LinkedIn: | , ; • · – — , punto y espacio, o ' - '
        segments = [s.strip() for s in re.split(r'\s*(?:[|;•·\n\–\—]|\.\s+|\s-\s)\s*', clean_head) if s.strip()]

        # Si no hay barras pero hay '/' con roles (ej: Director de Colegio/ Líder Educativo Senior)
        if len(segments) <= 1 and '/' in clean_head:
            sub_segs = [s.strip() for s in clean_head.split('/') if s.strip()]
            if len(sub_segs) > 1:
                segments = sub_segs

        # Descartar segmentos que sean puramente académicos, slogans o frases filosóficas
        viable_segments = [s for s in segments if not is_fluff_or_academic(s) and not is_invalid_role(s)]
        if not viable_segments:
            viable_segments = segments

        # Buscar el segmento que contenga relación laboral " en " o " at " o "@"
        best_segment = ""
        best_idx = 0
        for i, seg in enumerate(viable_segments):
            if re.search(r'\b(en|at|@)\b', seg, re.IGNORECASE):
                best_segment = seg
                best_idx = i
                break
        
        # Si no tiene "en", buscar prefijos de cargos conocidos
        if not best_segment:
            for i, seg in enumerate(viable_segments):
                if any(re.search(pat, seg, re.IGNORECASE) for pat in COMMON_TITLES_PREFIX):
                    best_segment = seg
                    best_idx = i
                    break

        if not best_segment:
            best_segment = viable_segments[0]
            best_idx = 0

        # Si la institución no ha sido determinada, verificar si el siguiente segmento viable es la empresa
        if not institucion and best_idx + 1 < len(viable_segments):
            next_cand = re.sub(r'[\.\,]+$', '', viable_segments[best_idx + 1]).strip()
            if next_cand and len(next_cand) < 70 and not is_invalid_institution(next_cand) and not is_fluff_or_academic(next_cand):
                institucion = next_cand

        # Descomponer best_segment en Puesto y Empresa
        # Caso A: Separador explícito ' en ' o ' at ' o ' @ '
        if re.search(r'\s+(?:en|at|@)\s+', best_segment, re.IGNORECASE):
            parts = re.split(r'\s+(?:en|at|@)\s+', best_segment, maxsplit=1, flags=re.IGNORECASE)
            cargo_actual = parts[0].strip()
            comp = parts[1].strip()
            if not institucion and comp and not is_invalid_institution(comp):
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
                    if not institucion and company_part and not is_invalid_institution(company_part):
                        institucion = company_part
            else:
                cargo_actual = best_segment

    # 3. Limpiezas especiales de cargo_actual
    if is_invalid_role(cargo_actual):
        cargo_actual = ""

    # Si el cargo contiene una frase subordinada como "en Programa de Integración Escolar (P.I.E) colegio Angol"
    if cargo_actual and re.search(r'\s+en\s+', cargo_actual, re.IGNORECASE):
        sub_parts = re.split(r'\s+en\s+', cargo_actual, maxsplit=1, flags=re.IGNORECASE)
        base_role = sub_parts[0].strip()
        trailing = sub_parts[1].strip()
        if not is_invalid_role(base_role):
            if ("pie" in cargo_actual.lower() or "pie" in headline.lower() or "integración escolar" in cargo_actual.lower()) and "pie" not in base_role.lower():
                cargo_actual = f"{base_role} (PIE)"
            else:
                cargo_actual = base_role
        if not institucion:
            institucion = trailing

    # Limpiezas finales de puntuación
    cargo_actual = re.sub(r'[\/|;,\-–—]+$', '', cargo_actual).strip()
    cargo_actual = re.sub(r'^[\/|;,\-–—]+', '', cargo_actual).strip()
    cargo_actual = re.sub(r'\s+(?:de|del|en|at|para|por)\s*$', '', cargo_actual, flags=re.IGNORECASE).strip()

    if '/' in cargo_actual and not re.search(r'\b(y|and)\b', cargo_actual):
        cargo_actual = cargo_actual.split('/')[0].strip()

    if len(cargo_actual) > 60:
        cargo_actual = cargo_actual[:60].rsplit(' ', 1)[0].strip()

    if cargo_actual.islower():
        cargo_actual = cargo_actual.title()

    if not cargo_actual or cargo_actual.upper() in ['CHILE', 'PROFESIONAL']:
        cargo_actual = 'Profesional / Directivo'

    if not institucion:
        institucion = default_institucion or ''

    institucion = re.sub(r'[|,;·•].*$', '', institucion).strip()
    institucion = re.sub(r'[\/|;,\-–—]+$', '', institucion).strip()
    if is_invalid_institution(institucion):
        institucion = ""

    # 4. Refinar instituciones genéricas de tipo 'Programa de Integración Escolar' / 'PIE'
    institucion = refine_pie_institution(institucion, role=cargo_actual, headline=headline, location=location)

    return cargo_actual, institucion

