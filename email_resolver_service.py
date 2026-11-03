import os
import re
import socket
import unicodedata
import time
import random
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import dns.resolver

from database import get_db
import browser_service
import logger_service
import zoho_bridge_service
import email_verifier_service

# ==============================================================================
# EMAIL RESOLVER SERVICE & WATERFALL ENRICHMENT ENGINE
# ==============================================================================
# Cumplimiento Directrices v1.3 - Workstream 5.6 [P1] y Prohibición 14:
# - CERO conexiones salientes SMTP (RCPT TO) en puerto 25.
# - Cascada ordenada estrictamente por costo:
#   1. Correo publicado en fuentes públicas / OSINT (Costo $0 - $0.001)
#   2. Contacto de 1er grado en LinkedIn (Costo $0)
#   3. Inferencia de patrón de dominio a partir de la misma organización y tenant (Costo $0)
#   4. Controles gratuitos locales: sintaxis RFC 5322, DNS MX, listas desechables (Costo $0)
#   5. Verificación externa pagada (MillionVerifier / ZeroBounce) con tope <= 3 consultas por lead.
# - Registro de evidencia por candidato en email_candidates.
# - Registro de costo real en USD en usage_events y deducción en credit_ledger.
# - Aislamiento estricto por tenant: la caché y patrones nunca se comparten entre tenants.
# ==============================================================================

# Diccionario curado de dominios institucionales en Chile y LATAM
KNOWN_INSTITUTION_DOMAINS = {
    # Universidades
    "universidad de chile": "uchile.cl",
    "uchile": "uchile.cl",
    "pontificia universidad catolica de chile": "uc.cl",
    "universidad catolica": "uc.cl",
    "uc chile": "uc.cl",
    "universidad de santiago de chile": "usach.cl",
    "usach": "usach.cl",
    "universidad adolfo ibanez": "uai.cl",
    "uai": "uai.cl",
    "universidad diego portales": "udp.cl",
    "udp": "udp.cl",
    "universidad andres bello": "unab.cl",
    "unab": "unab.cl",
    "universidad de los andes": "uandes.cl",
    "uandes": "uandes.cl",
    "universidad san sebastian": "uss.cl",
    "uss": "uss.cl",
    "universidad santo tomas": "ust.cl",
    "universidad de concepcion": "udec.cl",
    "udec": "udec.cl",
    "universidad del bio-bio": "ubiobio.cl",
    "universidad de la frontera": "ufro.cl",
    "universidad de valparaiso": "uv.cl",
    "universidad central": "ucen.cl",
    "duoc uc": "duoc.cl",
    "duoc": "duoc.cl",
    "inacap": "inacap.cl",
    "aiep": "aiep.cl",

    # Instituciones Públicas y Educación
    "ministerio de educacion": "mineduc.cl",
    "mineduc": "mineduc.cl",
    "agencia de calidad de la educacion": "agenciaeducacion.cl",
    "superintendencia de educacion": "supereduc.cl",
    "junji": "junji.gob.cl",
    "junta nacional de jardines infantiles": "junji.gob.cl",
    "fundacion integra": "integra.cl",
    "cpeip": "cpeip.cl",
    "demre": "demre.cl",

    # Colegios y Redes Educacionales reconocidas
    "colegio mayor": "colegiomayor.cl",
    "colegio san ignacio": "sanignacio.cl",
    "colegio san ignacio el bosque": "sanignacioelbosque.cl",
    "colegio san ignacio alonso ovalle": "csiao.cl",
    "colegio pumahue": "pumahue.cl",
    "red de colegios pumahue": "pumahue.cl",
    "colegio manhasset": "manquecura.cl",
    "colegio manquecura": "manquecura.cl",
    "red educacional santo tomas de aquino": "secst.cl",
    "secst": "secst.cl",
    "colegio alcantara": "alcantara.cl",
    "colegio alicante": "colegiosalicante.cl",
    "the grange school": "grange.cl",
    "craighouse school": "craighouse.cl",
    "santiago college": "scollege.cl",
    "nido de aguilas": "nido.cl",
    "instituto nacional": "institutonacional.cl",
    "liceo 1 javiera carrera": "liceo1.cl",

    # Empresas e Instituciones Corporativas
    "codelco": "codelco.cl",
    "banco de chile": "bancochile.cl",
    "bci": "bci.cl",
    "banco santander": "santander.cl",
    "santander": "santander.cl",
    "banco estado": "bancoestado.cl",
    "bancoestado": "bancoestado.cl",
    "scotiabank": "scotiabank.cl",
    "itau": "itau.cl",
    "falabella": "falabella.cl",
    "cencosud": "cencosud.com",
    "ripley": "ripley.com",
    "entel": "entel.cl",
    "movistar": "movistar.cl",
    "vtr": "vtr.cl",
    "enel": "enel.com",
    "latam": "latam.com",
    "latam airlines": "latam.com"
}

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "throwawaymail.com",
    "guerrillamail.com", "yopmail.com", "trashmail.com", "sharklasers.com"
}

GENERIC_ROLE_PREFIXES = {
    "info", "contacto", "contact", "ventas", "sales", "soporte", "support",
    "admin", "hola", "hello", "recepcion", "rrhh", "rr.hh", "postulaciones",
    "comunicaciones", "prensa", "facturacion", "cobranzas", "ayuda", "help"
}

# ==============================================================================
# 1. NORMALIZACIÓN DE NOMBRES Y DOMINIOS
# ==============================================================================

def normalize_text_ascii(text: str) -> str:
    """Elimina acentos, tildes y caracteres no ASCII para la síntesis de correos electrónicos."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    clean = "".join([c for c in nfkd if not unicodedata.combining(c)])
    clean = clean.replace('ñ', 'n').replace('Ñ', 'N')
    return re.sub(r'[^a-zA-Z0-9\s._-]', '', clean).strip()

def parse_person_names(full_name: str) -> Tuple[str, str, str]:
    """Divide el nombre completo en (primer_nombre, apellido_paterno, apellido_materno) filtrando prefijos académicos y profesionales."""
    if not full_name:
        return ("", "", "")

    clean = re.sub(r'^(?:Dr\.?|Dra\.?|Lic\.?|Mg\.?|Prof\.?|Ing\.?|Ps\.?|Educ\.?)\s+', '', full_name, flags=re.IGNORECASE)
    clean = normalize_text_ascii(clean)
    tokens = [t.lower() for t in clean.split() if t]

    if not tokens:
        return ("", "", "")

    compound_prefixes = {"de", "del", "la", "las", "los", "san", "santa"}
    first_name = tokens[0]

    remaining = tokens[1:]
    if not remaining:
        return (first_name, "", "")

    # Reconstrucción de apellidos compuestos
    merged_surnames = []
    i = 0
    while i < len(remaining):
        if remaining[i] in compound_prefixes and (i + 1) < len(remaining):
            merged_surnames.append(f"{remaining[i]}{remaining[i+1]}")
            i += 2
        else:
            merged_surnames.append(remaining[i])
            i += 1

    last_name = merged_surnames[0] if merged_surnames else ""
    maternal_last = merged_surnames[1] if len(merged_surnames) > 1 else ""

    return (first_name, last_name, maternal_last)

def clean_domain_name(raw_url_or_domain: str) -> str:
    """Extrae y normaliza el FQDN a partir de una URL o cadena."""
    if not raw_url_or_domain:
        return ""
    d = raw_url_or_domain.strip().lower()
    d = re.sub(r'^https?://', '', d)
    d = re.sub(r'^www\.', '', d)
    d = d.split('/')[0].split(':')[0].strip()
    return d

def resolve_company_domain(company_name: str, location: str = "") -> Tuple[Optional[str], str]:
    """Resuelve el dominio corporativo o institucional mediante coincidencia en diccionario curado o heurística con validación DNS MX."""
    if not company_name:
        return (None, "sin_institucion")

    clean_comp = normalize_text_ascii(company_name).lower()
    
    # 1. Coincidencia exacta en diccionario
    if clean_comp in KNOWN_INSTITUTION_DOMAINS:
        return (KNOWN_INSTITUTION_DOMAINS[clean_comp], "diccionario_exacto")

    # 2. Coincidencia de subcadena en diccionario
    for k, dom in KNOWN_INSTITUTION_DOMAINS.items():
        if k in clean_comp:
            return (dom, "diccionario_parcial")

    # 3. Limpieza de ruido societario
    noise_patterns = [
        r'\b(?:spa|s\.a\.?|ltda\.?|limitada|e\.i\.r\.l\.?|corporaci[oó]n|fundaci[oó]n)\b',
        r'\b(?:colegio|liceo|escuela|instituto|jard[ií]n|sala cuna|universidad)\b',
        r'\b(?:de|del|la|las|los|en|y|chile|santiago)\b'
    ]
    stripped = clean_comp
    for pat in noise_patterns:
        stripped = re.sub(pat, ' ', stripped, flags=re.IGNORECASE)
    
    slug_tokens = [t for t in stripped.split() if len(t) >= 2]
    if not slug_tokens:
        slug_tokens = [t for t in clean_comp.split() if len(t) >= 2]

    if not slug_tokens:
        return (None, "institucion_invalida")

    candidates = []
    cand_full = "".join(slug_tokens)
    candidates.append(f"{cand_full}.cl")
    candidates.append(f"{cand_full}.com")

    first_token = slug_tokens[0]
    if len(first_token) >= 4:
        candidates.append(f"{first_token}.cl")
        candidates.append(f"{first_token}.com")

    if "colegio" in clean_comp and len(slug_tokens) >= 1:
        candidates.append(f"colegio{slug_tokens[0]}.cl")

    if "municipalidad" in clean_comp or "munistgo" in clean_comp:
        muni_target = slug_tokens[0] if slug_tokens else ""
        if muni_target:
            candidates.append(f"muni{muni_target}.cl")
            candidates.append(f"municipalidad{muni_target}.cl")

    # Probar candidatos contra DNS MX
    for cand in candidates:
        cand_clean = cand.strip().lower()
        try:
            mx_records = get_domain_mx_records(cand_clean)
            if mx_records:
                return (cand_clean, "heuristica_dns_mx_valido")
        except Exception:
            continue

    best_guess = f"{cand_full}.cl" if "chile" in location.lower() or "santiago" in location.lower() or not location else f"{cand_full}.com"
    return (best_guess, "heuristica_probabilidad")

# ==============================================================================
# 2. VALIDACIÓN SINTÁCTICA Y DNS MX (SIN SMTP SALIENTE)
# ==============================================================================

def check_email_syntax(email: str) -> bool:
    """Verifica el cumplimiento estricto del estándar RFC 5322 y descarta dominios temporales desechables."""
    if not email or len(email) > 254:
        return False
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(pattern, email):
        return False
    domain = email.split('@')[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        return False
    return True

def is_role_account(email: str) -> bool:
    """Detecta cuentas de rol genéricas que no pertenecen a personas naturales."""
    if not email or "@" not in email:
        return False
    prefix = email.split("@")[0].lower().strip()
    return prefix in GENERIC_ROLE_PREFIXES

def get_domain_mx_records(domain: str) -> List[Tuple[int, str]]:
    """Consulta los registros DNS MX de un dominio y retorna lista ordenada de servidores."""
    if not domain:
        return []
    clean_domain = domain.strip().lower().rstrip('.')
    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 3.0
        resolver.lifetime = 4.0
        answers = resolver.resolve(clean_domain, 'MX')
        results = []
        for r in answers:
            pref = int(r.preference)
            exch = str(r.exchange).rstrip('.')
            results.append((pref, exch))
        results.sort(key=lambda x: x[0])
        return results
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, dns.resolver.NoNameservers):
        return []
    except Exception as e:
        logger_service.log_debug(f"DNS MX Lookup warning for {clean_domain}: {e}")
        return []

# ==============================================================================
# 3. GENERADOR DE PATRONES CORPORATIVOS
# ==============================================================================

def generate_corporate_patterns(
    first_name: str,
    last_name: str,
    domain: str,
    maternal_last_name: str = ""
) -> List[str]:
    """Genera patrones estándar de correo corporativo ordenados por prevalencia en Chile y Latinoamérica."""
    if not first_name or not last_name or not domain:
        return []

    f = first_name.lower().strip()
    l = last_name.lower().strip()
    m = maternal_last_name.lower().strip() if maternal_last_name else ""
    dom = domain.lower().strip()

    f_init = f[0] if f else ""
    l_init = l[0] if l else ""
    m_init = m[0] if m else ""

    patterns = [
        f"{f}.{l}@{dom}",             # alejandro.pereira@dominio
        f"{f_init}{l}@{dom}",          # apereira@dominio
        f"{f}{l}@{dom}",               # alejandropereira@dominio
        f"{f}_{l}@{dom}",              # alejandro_pereira@dominio
        f"{f_init}.{l}@{dom}",         # a.pereira@dominio
        f"{l}.{f}@{dom}",              # pereira.alejandro@dominio
        f"{f}@{dom}",                  # alejandro@dominio
        f"{l}@{dom}",                  # pereira@dominio
    ]

    if m:
        patterns.extend([
            f"{f_init}{l}{m_init}@{dom}",      # apereirab@dominio
            f"{f}.{l}.{m_init}@{dom}",        # alejandro.pereira.b@dominio
            f"{f}.{m}@{dom}",                 # alejandro.barrientos@dominio
            f"{f_init}{m}@{dom}"              # abarrientos@dominio
        ])

    seen = set()
    unique_patterns = []
    for p in patterns:
        if p not in seen and check_email_syntax(p) and not is_role_account(p):
            seen.add(p)
            unique_patterns.append(p)

    return unique_patterns

# ==============================================================================
# 4. INFERENCIA DE PATRÓN ORGANIZACIONAL (POR TENANT)
# ==============================================================================

def infer_organization_pattern_from_tenant(
    tenant_id: str,
    domain: str,
    first_name: str,
    last_name: str,
    conn=None
) -> Optional[str]:
    """
    Infiere el patrón de correo corporativo a partir de otros contactos ya confirmados
    de la misma organización dentro del MISMO tenant (Aislamiento Multi-Tenant estricto).
    """
    if not tenant_id or not domain or not first_name or not last_name:
        return None

    close_conn = False
    if conn is None:
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT email_extracted, nombre FROM leads
            WHERE tenant_id = ? AND empresa_dominio = ? AND email_status = 'VERIFICADO' AND email_extracted IS NOT NULL
            LIMIT 5
        """, (tenant_id, domain))
        rows = cursor.fetchall()

        if not rows:
            return None

        for r in rows:
            confirmed_email = r["email_extracted"] if isinstance(r, dict) else r[0]
            lead_name = r["nombre"] if isinstance(r, dict) else r[1]
            if not confirmed_email or "@" not in confirmed_email or not lead_name:
                continue

            cf, cl, cm = parse_person_names(lead_name)
            if not cf or not cl:
                continue

            prefix = confirmed_email.split("@")[0].lower()
            f_clean = cf.lower()
            l_clean = cl.lower()

            target_f = first_name.lower().strip()
            target_l = last_name.lower().strip()

            if prefix == f"{f_clean}.{l_clean}":
                return f"{target_f}.{target_l}@{domain}"
            elif prefix == f"{f_clean[0]}{l_clean}":
                return f"{target_f[0]}{target_l}@{domain}"
            elif prefix == f"{f_clean}_{l_clean}":
                return f"{target_f}_{target_l}@{domain}"
            elif prefix == f"{f_clean}{l_clean}":
                return f"{target_f}{target_l}@{domain}"
            elif prefix == f"{f_clean[0]}.{l_clean}":
                return f"{target_f[0]}.{target_l}@{domain}"

        return None
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)

# ==============================================================================
# 5. EXTRACCIÓN DIRECTA LINKEDIN (CONTACTOS 1ER GRADO)
# ==============================================================================

LINKEDIN_CONTACT_INFO_EXTRACT_JS = r"""
(() => {
    try {
        const res = {
            ok: true,
            email: null,
            telefono: null,
            sitios_web: [],
            fecha_conexion: null
        };
        const mailto = document.querySelector('a[href^="mailto:"]');
        if (mailto) {
            const raw = mailto.getAttribute('href') || '';
            res.email = raw.replace(/^mailto:/i, '').split('?')[0].trim();
        }
        if (!res.email) {
            const emailSec = document.querySelector('.ci-email, section.pv-contact-info__contact-type.ci-email, div[data-field="email"]');
            if (emailSec) {
                const a = emailSec.querySelector('a');
                if (a) {
                    res.email = a.innerText.trim();
                } else {
                    const m = (emailSec.innerText || '').match(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/);
                    if (m) res.email = m[0];
                }
            }
        }
        return res;
    } catch (e) {
        return { ok: false, error: e.message };
    }
})()
"""

def extract_linkedin_direct_contact(profile_url: str, lead_name: str = "") -> Dict[str, Any]:
    """Extrae el correo electrónico visible directamente del modal de contacto de LinkedIn para contactos de 1er grado."""
    if not profile_url:
        return {"ok": False, "motivo": "Sin URL de perfil"}

    if not browser_service.is_electron_running() and not browser_service.is_browseros_running():
        return {"ok": False, "motivo": "Navegador local no disponible (iniciar aplicación desktop)"}

    clean_url = profile_url.split("?")[0].rstrip("/") + "/"

    time.sleep(random.uniform(1.2, 2.0))

    try:
        # 1. Vía preferente y segura: Función nativa precompilada en Electron (Regla C-01 Directrices v1.3)
        if browser_service.is_electron_running():
            res_electron = browser_service.extract_contact_info_from_electron(clean_url)
            data_res = res_electron.get("result") if isinstance(res_electron.get("result"), dict) else res_electron
            if res_electron.get("success") or data_res.get("email") or data_res.get("phone"):
                email_found = data_res.get("email")
                if email_found and check_email_syntax(email_found):
                    return {
                        "ok": True,
                        "email": email_found.strip(),
                        "telefono": data_res.get("phone"),
                        "sitios_web": data_res.get("websites", []),
                        "source": "linkedin_direct",
                        "status": "VERIFICADO"
                    }
                elif data_res.get("phone"):
                    return {
                        "ok": True,
                        "email": None,
                        "telefono": data_res.get("phone"),
                        "sitios_web": data_res.get("websites", []),
                        "source": "linkedin_direct",
                        "status": "TELEFONO_SOLO"
                    }
            return {"ok": False, "motivo": "Contacto de 1er grado con correo privado o sin visibilidad"}

        # 2. Fallback BrowserOS MCP si no está en Electron
        contact_overlay_url = clean_url + "overlay/contact-info/"
        browser_service.open_profile_in_browseros(contact_overlay_url, f"Contacto - {lead_name}")
        time.sleep(random.uniform(2.5, 3.8))

        res = browser_service._call_mcp_evaluate(LINKEDIN_CONTACT_INFO_EXTRACT_JS)
        data = res.get("result") if isinstance(res, dict) and "result" in res and isinstance(res["result"], dict) else res

        if isinstance(data, dict) and data.get("ok"):
            email_found = data.get("email")
            if email_found and check_email_syntax(email_found):
                return {
                    "ok": True,
                    "email": email_found.strip(),
                    "telefono": data.get("telefono"),
                    "sitios_web": data.get("sitios_web", []),
                    "fecha_conexion": data.get("fecha_conexion"),
                    "source": "linkedin_direct",
                    "status": "VERIFICADO"
                }

        return {"ok": False, "motivo": "Contacto de 1er grado con correo privado o sin visibilidad"}
    except Exception as e:
        return {"ok": False, "motivo": f"Excepción durante extracción LinkedIn: {str(e)}"}

# ==============================================================================
# 6. MOTOR UNIFICADO EN CASCADA (WATERFALL ENRICHMENT ENGINE)
# ==============================================================================

def resolve_lead_email(lead_id: str, force_refresh: bool = False, conn=None) -> Dict[str, Any]:
    """
    Flujo de resolución en cascada ordenada por costo (Sección 5.6):
    Paso 0: Lista de supresión (Opt-out)
    Paso 1: OSINT público / web (Costo $0 - $0.001)
    Paso 2: Contacto 1er grado LinkedIn (Costo $0)
    Paso 3: Inferencia de patrón de dominio del mismo tenant (Costo $0)
    Paso 4: Controles gratuitos (Sintaxis RFC 5322, DNS MX, listas desechables) (Costo $0)
    Paso 5: Verificación externa pagada (MillionVerifier / ZeroBounce) con tope de 3 consultas
    Registro de evidencia en email_candidates, consumo en credit_ledger y registro en usage_events.
    """
    now_iso = datetime.now().isoformat()
    close_conn = False
    if conn is None:
        ctx = get_db()
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()

        if not lead:
            return {"ok": False, "error": f"Lead {lead_id} no encontrado en base de datos"}

        tenant_id = (lead.get("tenant_id") if isinstance(lead, dict) else lead[0]) or "ten_superadmin"
        lead_name = (lead.get("nombre") if isinstance(lead, dict) else lead[1]) or ""
        company = (lead.get("institucion_actual") if isinstance(lead, dict) else lead[4]) or ""
        profile_url = (lead.get("perfil_url") if isinstance(lead, dict) else lead[7]) or ""
        location = (lead.get("ubicacion") if isinstance(lead, dict) else lead[5]) or "Chile"
        grado_red = (lead.get("grado_red") if isinstance(lead, dict) else lead[6]) or "2º"
        current_extracted = lead.get("email_extracted") if isinstance(lead, dict) else None
        current_status = lead.get("email_status") if isinstance(lead, dict) else None

        # Si ya está verificado y no se solicitó actualización forzada
        if not force_refresh and current_extracted and current_status == "VERIFICADO":
            return {
                "ok": True,
                "email": current_extracted,
                "source": lead.get("email_source", "preexistente") if isinstance(lead, dict) else "preexistente",
                "status": "VERIFICADO",
                "dominio": lead.get("empresa_dominio") if isinstance(lead, dict) else None,
                "mensaje": "Correo ya verificado en base de datos"
            }

        first_name, last_name, maternal_last = parse_person_names(lead_name)
        domain, domain_method = resolve_company_domain(company, location)

        # ----------------------------------------------------------------------
        # PASO 1: BÚSQUEDA OSINT PÚBLICA (Sitio institucional / Web)
        # ----------------------------------------------------------------------
        serper = email_verifier_service.SerperSearchProvider()
        osint_res = serper.search_public_email(lead_name, company, target_domain=domain or "")
        if osint_res and osint_res.get("email"):
            cand_email = osint_res["email"]
            if check_email_syntax(cand_email) and not is_role_account(cand_email):
                # Registrar candidato en email_candidates
                cand_id = f"cand_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
                cursor.execute("""
                    INSERT INTO email_candidates 
                    (id, tenant_id, lead_id, candidate_email, source_type, evidence_url, confidence_score, verification_status, verification_provider, verification_cost_cents, created_at)
                    VALUES (?, ?, ?, ?, 'PUBLIC_OSINT_WEB', ?, 0.85, 'VALID', 'serper', 0, ?)
                """, (cand_id, tenant_id, lead_id, cand_email, osint_res.get("evidence_url"), now_iso))

                # Registrar costo real en usage_events (sin consumo de créditos comerciales por ser fuente pública)
                email_verifier_service.record_verification_usage(
                    tenant_id=tenant_id,
                    account_id=None,
                    provider="serper_osint",
                    cost_usd=osint_res.get("cost_usd", 0.001),
                    credits_consumed=0,
                    details={"source": "PUBLIC_OSINT_WEB", "query": lead_name},
                    conn=conn
                )

                cursor.execute("""
                    UPDATE leads
                    SET email_extracted = ?, email_source = 'PUBLIC_OSINT_WEB', email_status = 'VERIFICADO',
                        empresa_dominio = ?, email = COALESCE(email, ?), email_detalles_json = ?, updated_at = ?
                    WHERE id = ?
                """, (cand_email, domain, cand_email, json.dumps(osint_res), now_iso, lead_id))

                if close_conn:
                    conn.commit()

                return {
                    "ok": True,
                    "email": cand_email,
                    "source": "PUBLIC_OSINT_WEB",
                    "status": "VERIFICADO",
                    "confidence": 0.85,
                    "evidence_url": osint_res.get("evidence_url")
                }

        # ----------------------------------------------------------------------
        # PASO 2: CONTACTO DE 1ER GRADO EN LINKEDIN
        # ----------------------------------------------------------------------
        is_1st_degree = grado_red in ("1º", "1er", "1°", "1st") or (lead.get("estado") if isinstance(lead, dict) else "") == "CONECTADO"
        if is_1st_degree and profile_url:
            direct_res = extract_linkedin_direct_contact(profile_url, lead_name)
            if direct_res.get("ok") and direct_res.get("email"):
                extracted_email = direct_res["email"]
                cand_id = f"cand_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
                cursor.execute("""
                    INSERT INTO email_candidates 
                    (id, tenant_id, lead_id, candidate_email, source_type, evidence_url, confidence_score, verification_status, verification_provider, verification_cost_cents, created_at)
                    VALUES (?, ?, ?, ?, 'LINKEDIN_1ST_DEGREE', ?, 0.95, 'VALID', 'linkedin_direct', 0, ?)
                """, (cand_id, tenant_id, lead_id, extracted_email, profile_url, now_iso))

                cursor.execute("""
                    UPDATE leads
                    SET email_extracted = ?, email_source = 'linkedin_direct', email_status = 'VERIFICADO',
                        telefono = COALESCE(telefono, ?), email = COALESCE(email, ?),
                        email_detalles_json = ?, updated_at = ?
                    WHERE id = ?
                """, (extracted_email, direct_res.get("telefono"), extracted_email, json.dumps(direct_res), now_iso, lead_id))

                if close_conn:
                    conn.commit()

                return {
                    "ok": True,
                    "email": extracted_email,
                    "source": "linkedin_direct",
                    "status": "VERIFICADO",
                    "confidence": 0.95
                }

        # ----------------------------------------------------------------------
        # PASO 3: INFERENCIA DE PATRÓN ORGANIZACIONAL (MISMO TENANT)
        # ----------------------------------------------------------------------
        if domain:
            inferred_email = infer_organization_pattern_from_tenant(tenant_id, domain, first_name, last_name, conn=conn)
            if inferred_email and check_email_syntax(inferred_email):
                cand_id = f"cand_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
                cursor.execute("""
                    INSERT INTO email_candidates 
                    (id, tenant_id, lead_id, candidate_email, source_type, evidence_url, confidence_score, verification_status, verification_provider, verification_cost_cents, created_at)
                    VALUES (?, ?, ?, ?, 'DOMAIN_PATTERN_INFERENCE', NULL, 0.80, 'PROBABLE', 'tenant_pattern', 0, ?)
                """, (cand_id, tenant_id, lead_id, inferred_email, now_iso))

                cursor.execute("""
                    UPDATE leads
                    SET email_extracted = ?, email_source = 'DOMAIN_PATTERN_INFERENCE', email_status = 'PROBABLE',
                        empresa_dominio = ?, email = COALESCE(email, ?), email_detalles_json = ?, updated_at = ?
                    WHERE id = ?
                """, (inferred_email, domain, inferred_email, json.dumps({"metodo": "inferencia_patron_tenant", "dominio": domain}), now_iso, lead_id))

                if close_conn:
                    conn.commit()

                return {
                    "ok": True,
                    "email": inferred_email,
                    "source": "DOMAIN_PATTERN_INFERENCE",
                    "status": "PROBABLE",
                    "confidence": 0.80
                }

        # ----------------------------------------------------------------------
        # PASO 4: CONTROLES GRATUITOS Y GENERACIÓN DE PATRONES
        # ----------------------------------------------------------------------
        if not domain:
            cursor.execute("""
                UPDATE leads
                SET email_status = 'NO_ENCONTRADO',
                    email_detalles_json = ?, updated_at = ?
                WHERE id = ?
            """, (json.dumps({"motivo": f"No se pudo determinar el dominio para la institución '{company}'"}), now_iso, lead_id))

            if close_conn:
                conn.commit()

            return {
                "ok": False,
                "email": None,
                "status": "NO_ENCONTRADO",
                "motivo": f"No se pudo determinar el dominio para '{company}'"
            }

        mx_records = get_domain_mx_records(domain)
        if not mx_records:
            cursor.execute("""
                UPDATE leads
                SET empresa_dominio = ?, email_status = 'NO_ENCONTRADO',
                    email_detalles_json = ?, updated_at = ?
                WHERE id = ?
            """, (domain, json.dumps({"motivo": f"Dominio {domain} sin registros MX activos"}), now_iso, lead_id))

            if close_conn:
                conn.commit()

            return {
                "ok": False,
                "email": None,
                "status": "NO_ENCONTRADO",
                "motivo": f"El dominio {domain} no posee registros DNS MX configurados."
            }

        patterns = generate_corporate_patterns(first_name, last_name, domain, maternal_last)
        if not patterns:
            return {
                "ok": False,
                "email": None,
                "status": "NO_ENCONTRADO",
                "motivo": "No fue posible generar patrones corporativos con los nombres del prospecto."
            }

        # ----------------------------------------------------------------------
        # PASO 5: VERIFICACIÓN EXTERNA PAGADA (CON TOPE <= 3 CONSULTAS POR LEAD)
        # ----------------------------------------------------------------------
        # Criterio no negociable 5.6.2.e: Tope máximo de 3 consultas por lead
        import entitlements_service
        credit_ent = entitlements_service.check_email_credits_entitlement(tenant_id, conn=conn)
        if not credit_ent["aprobado"]:
            return {
                "ok": False,
                "email": None,
                "status": "CREDITOS_AGOTADOS",
                "codigo": "LIMIT_CREDITS_REACHED",
                "motivo": credit_ent["motivo"]
            }

        MAX_EXTERNAL_CHECKS = 3
        candidates_to_check = patterns[:MAX_EXTERNAL_CHECKS]
        verifier = email_verifier_service.get_email_verifier()

        chosen_result: Optional[email_verifier_service.EmailVerificationResult] = None
        checks_performed = 0

        for candidate_email in candidates_to_check:
            checks_performed += 1
            v_res = verifier.verify(candidate_email, tenant_id=tenant_id)

            cand_id = f"cand_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
            cursor.execute("""
                INSERT INTO email_candidates 
                (id, tenant_id, lead_id, candidate_email, source_type, evidence_url, confidence_score, verification_status, verification_provider, verification_cost_cents, created_at)
                VALUES (?, ?, ?, ?, 'EXTERNAL_VERIFIER', NULL, ?, ?, ?, ?, ?)
            """, (
                cand_id,
                tenant_id,
                lead_id,
                candidate_email,
                v_res.confidence,
                v_res.status.upper(),
                v_res.provider,
                v_res.cost_cents,
                now_iso
            ))

            # Registrar costo real en usage_events
            credits_to_debit = 1 if v_res.is_usable() else 0
            email_verifier_service.record_verification_usage(
                tenant_id=tenant_id,
                account_id=None,
                provider=v_res.provider,
                cost_usd=v_res.cost_usd,
                credits_consumed=credits_to_debit,
                details={"candidate": candidate_email, "status": v_res.status, "confidence": v_res.confidence},
                conn=conn
            )

            if v_res.is_usable():
                chosen_result = v_res
                break  # Detención inmediata en el primer candidato utilizable (cost-ordered cascade)

        if chosen_result:
            detalles_save = {
                "dominio": domain,
                "metodo_dominio": domain_method,
                "proveedor": chosen_result.provider,
                "confidence": chosen_result.confidence,
                "status": chosen_result.status,
                "consultas_realizadas": checks_performed,
                "costo_usd": chosen_result.cost_usd
            }

            lead_status = "VERIFICADO" if chosen_result.status == "valid" else "PROBABLE"
            cursor.execute("""
                UPDATE leads
                SET email_extracted = ?, email_source = ?, email_status = ?, empresa_dominio = ?,
                    email = COALESCE(email, ?), email_detalles_json = ?, updated_at = ?
                WHERE id = ?
            """, (chosen_result.email, f"external_{chosen_result.provider}", lead_status, domain, chosen_result.email, json.dumps(detalles_save), now_iso, lead_id))

            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'EMAIL_VERIFICADO_EXTERNO', ?, ?)
            """, (lead_id, f"Correo resuelto vía {chosen_result.provider}: {chosen_result.email} [{lead_status}]", now_iso))

            if close_conn:
                conn.commit()

            return {
                "ok": True,
                "email": chosen_result.email,
                "source": f"external_{chosen_result.provider}",
                "status": lead_status,
                "confidence": chosen_result.confidence,
                "dominio": domain,
                "consultas": checks_performed
            }
        else:
            # Ningún candidato externo fue utilizable
            detalles_fail = {
                "dominio": domain,
                "consultas_realizadas": checks_performed,
                "patrones_evaluados": len(candidates_to_check),
                "motivo": "Candidatos rechazados por verificador externo"
            }
            cursor.execute("""
                UPDATE leads
                SET empresa_dominio = ?, email_status = 'NO_ENCONTRADO',
                    email_detalles_json = ?, updated_at = ?
                WHERE id = ?
            """, (domain, json.dumps(detalles_fail), now_iso, lead_id))

            if close_conn:
                conn.commit()

            return {
                "ok": False,
                "email": None,
                "status": "NO_ENCONTRADO",
                "dominio": domain,
                "consultas": checks_performed,
                "motivo": "Ninguno de los candidatos evaluados fue validado por el proveedor externo."
            }
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)

# ==============================================================================
# 7. RESOLUCIÓN POR LOTES
# ==============================================================================

def batch_resolve_lead_emails(
    lead_ids: List[str],
    force_refresh: bool = False,
    max_workers: int = 3
) -> Dict[str, Any]:
    """Resuelve direcciones de correo corporativo para múltiples prospectos con pausas controladas."""
    results = []
    resueltos = 0
    no_encontrados = 0

    for lid in lead_ids:
        try:
            res = resolve_lead_email(lid, force_refresh=force_refresh)
            results.append({"lead_id": lid, "resultado": res})
            if res.get("ok"):
                resueltos += 1
            else:
                no_encontrados += 1
            time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            results.append({"lead_id": lid, "resultado": {"ok": False, "error": str(e)}})
            no_encontrados += 1

    return {
        "ok": True,
        "total": len(lead_ids),
        "resueltos": resueltos,
        "no_encontrados": no_encontrados,
        "detalles": results
    }
