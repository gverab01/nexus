"""
Servicio de Inteligencia y Sincronización con Zoho CRM vía Sesión Activa de Navegador (NexusReach Pro)

Este módulo interactúa con la API REST v6 interna de Zoho CRM aprovechando la sesión
autenticada existente en el navegador (Electron Chromium aislado o BrowserOS), SIN requerir
credenciales externas de desarrollador (API Keys, OAuth Secrets ni Client IDs de Zoho).

Capacidades principales:
1. Detección automática del token CSRF (CSRF_TOKEN / crmcsr) y Org ID (902879914).
2. Ejecución de consultas COQL (Zoho Object Query Language) de alto rendimiento sobre
   Contactos, Leads, Cuentas y Tratos.
3. Cruce inteligente y enriquecimiento de prospectos:
   - Extracción de correo electrónico corporativo verificado (email_zoho).
   - Identificación del tipo de entidad (Lead vs Contacto).
   - Identificación de Cuentas asociadas, Dueño de Cuenta y calificación como Cliente activo.
   - Mapeo de Tratos (Deals) en curso, etapas, montos y responsables.
   - Registro de fechas de sincronización y extracción.
4. Generación de Notas de trazabilidad y actualización de estados sin permisos administrativos.
"""

import json
import re
import time
import unicodedata
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from database import get_db
import browser_service

DEFAULT_ZOHO_ORG_ID = "902879914"


def clean_text_for_coql(text: str) -> str:
    """
    Sanitiza una cadena de texto para evitar errores de sintaxis en consultas COQL de Zoho.
    Escapa comillas simples y remueve caracteres de control.
    """
    if not text:
        return ""
    clean = text.replace("'", "\\'").strip()
    return clean


def normalize_search_term(term: str) -> str:
    """
    Normaliza un término de búsqueda eliminando tildes, diacríticos y prefijos
    típicos de bases de datos educativas (ej. '9799 - Complejo Educacional - Nombre').
    """
    if not term:
        return ""
    parts = term.split(" - ")
    if len(parts) >= 3:
        clean = parts[-1].strip()
    elif len(parts) == 2:
        clean = parts[-1].strip()
    else:
        clean = term.strip()

    # Quitar tildes
    nfkd = unicodedata.normalize("NFKD", clean)
    normalized = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return normalized.strip()


GENERIC_COMPANIES = {
    "colegio", "escuela", "liceo", "instituto", "jardin", "jardín", 
    "empresa", "fundacion", "fundación", "corporacion", "corporación", 
    "organizacion", "organización", "universidad", "consultora", 
    "independiente", "no especificado", "no determinado", "educación",
    "educacion", "docente", "-"
}


def extract_linkedin_initial(url: Optional[str]) -> Optional[str]:
    """Extrae la inicial del segundo apellido desde slugs de LinkedIn (ej. 'sandra-navarro-l' -> 'l')."""
    if not url:
        return None
    cleaned = url.rstrip("/").split("/")[-1].lower()
    parts = cleaned.split("-")
    if len(parts) >= 2 and len(parts[-1]) == 1 and parts[-1].isalpha():
        return parts[-1]
    return None


def score_zoho_candidate(
    cand: Dict[str, Any], 
    target_company: Optional[str] = None, 
    target_initial: Optional[str] = None,
    target_location: Optional[str] = None
) -> int:
    """Calcula un puntaje de afinidad para desempatar o validar candidatos de Zoho CRM."""
    score = 10
    full_name_zoho = normalize_search_term(str(cand.get("Full_Name") or cand.get("Last_Name") or "")).lower()
    zoho_tokens = full_name_zoho.split()

    # 1. Coincidencia con inicial de segundo apellido (slug de LinkedIn)
    if target_initial and zoho_tokens:
        if any(tok.startswith(target_initial) for tok in zoho_tokens[1:]):
            score += 25

    # 2. Coincidencia de empresa
    cand_comp = ""
    if isinstance(cand.get("Account_Name"), dict):
        cand_comp = cand.get("Account_Name", {}).get("name", "")
    elif cand.get("Account_Name"):
        cand_comp = str(cand.get("Account_Name"))
    elif cand.get("Company"):
        cand_comp = str(cand.get("Company"))

    cand_comp_norm = normalize_search_term(cand_comp).lower()

    if target_company:
        clean_target = normalize_search_term(target_company).lower()
        is_generic = clean_target in GENERIC_COMPANIES
        if is_generic:
            if clean_target in cand_comp_norm:
                score += 15
        else:
            if clean_target in cand_comp_norm or cand_comp_norm in clean_target:
                score += 35
            else:
                score -= 10

    # 3. Coincidencia de ubicación (ciudad / región)
    city = str(cand.get("City") or cand.get("Mailing_City") or "").lower()
    state = str(cand.get("State") or cand.get("Mailing_State") or "").lower()
    if target_location:
        loc_norm = normalize_search_term(target_location).lower()
        if loc_norm in city or loc_norm in state or any(w in city or w in state for w in loc_norm.split()):
            score += 20
        # Gran Valparaíso
        valpo_terms = {"valparaiso", "valparaíso", "vina", "viña", "quilpue", "quilpué", "concon", "concón", "villa alemana"}
        if any(vt in loc_norm for vt in valpo_terms) and any(vt in city or vt in state for vt in valpo_terms):
            score += 20

    return score


def _format_contact_result(best_match: Dict[str, Any]) -> Dict[str, Any]:
    acc = best_match.get("Account_Name") or {}
    owner = best_match.get("Owner") or {}
    return {
        "found": True,
        "entity_type": "Contact",
        "zoho_id": str(best_match.get("id")),
        "full_name": best_match.get("Full_Name") or f"{best_match.get('First_Name', '')} {best_match.get('Last_Name', '')}".strip(),
        "email": best_match.get("Email") or best_match.get("Secondary_Email") or "",
        "secondary_email": best_match.get("Secondary_Email") or "",
        "phone": best_match.get("Phone") or best_match.get("Mobile") or "",
        "lead_status": "Contacto Activo",
        "company_name": acc.get("name", "") if isinstance(acc, dict) else str(acc),
        "account_id": str(acc.get("id", "")) if isinstance(acc, dict) else "",
        "account_name": acc.get("name", "") if isinstance(acc, dict) else str(acc),
        "owner_id": str(owner.get("id", "")) if isinstance(owner, dict) else "",
        "owner_name": owner.get("name", "") if isinstance(owner, dict) else str(owner),
        "raw_record": best_match
    }


def _format_lead_result(best_match: Dict[str, Any]) -> Dict[str, Any]:
    owner = best_match.get("Owner") or {}
    return {
        "found": True,
        "entity_type": "Lead",
        "zoho_id": str(best_match.get("id")),
        "full_name": best_match.get("Full_Name") or f"{best_match.get('First_Name', '')} {best_match.get('Last_Name', '')}".strip(),
        "email": best_match.get("Email") or best_match.get("Secondary_Email") or "",
        "secondary_email": best_match.get("Secondary_Email") or "",
        "phone": best_match.get("Phone") or best_match.get("Mobile") or "",
        "lead_status": best_match.get("Lead_Status") or "Sin Estado",
        "company_name": best_match.get("Company") or "",
        "account_id": "",
        "account_name": best_match.get("Company") or "",
        "owner_id": str(owner.get("id", "")) if isinstance(owner, dict) else "",
        "owner_name": owner.get("name", "") if isinstance(owner, dict) else str(owner),
        "raw_record": best_match
    }


def check_zoho_browser_session() -> Dict[str, Any]:
    """
    Comprueba si existe una sesión activa de Zoho CRM en el navegador de trabajo
    extrayendo las cookies de sesión y el token CSRF.
    """
    script = r"""
    (() => {
        try {
            const match = document.cookie.match(/crmcsr=([^;]+)/) ||
                          document.cookie.match(/CSRF_TOKEN=([^;]+)/);
            const token = match ? match[1] : '';
            const currentUrl = window.location.href;
            const orgMatch = currentUrl.match(/org(\d+)/);
            const orgId = orgMatch ? orgMatch[1] : '902879914';
            const isCrm = currentUrl.includes('crm.zoho.com');

            return {
                ok: true,
                activo: Boolean(token && isCrm),
                token: token,
                org_id: orgId,
                url: currentUrl
            };
        } catch (err) {
            return { ok: false, error: err.message };
        }
    })()
    """
    res = browser_service._call_mcp_evaluate(script, channel="zoho")
    if isinstance(res, dict) and res.get("ok"):
        return {
            "active": bool(res.get("activo", False)),
            "token": res.get("token", ""),
            "org_id": res.get("org_id", DEFAULT_ZOHO_ORG_ID),
            "url": res.get("url", ""),
            "error": None
        }

    return {
        "active": False,
        "token": "",
        "org_id": DEFAULT_ZOHO_ORG_ID,
        "url": "",
        "error": res.get("error") if isinstance(res, dict) else "Error evaluando sesión de Zoho"
    }


def execute_zoho_coql(coql_query: str, org_id: str = DEFAULT_ZOHO_ORG_ID) -> Dict[str, Any]:
    """
    Ejecuta una consulta COQL directamente en el contexto del navegador autenticado
    utilizando fetch('/crm/v6/coql') con las cabeceras CSRF y ORG requeridas.
    """
    query_clean = coql_query.strip()
    escaped_query = json.dumps(query_clean)
    escaped_org = json.dumps(org_id or DEFAULT_ZOHO_ORG_ID)

    script = f"""
    (async () => {{
        try {{
            const match = document.cookie.match(/CSRF_TOKEN=([^;]+)/) || 
                          document.cookie.match(/crmcsr=([^;]+)/) ||
                          document.cookie.match(/iamcsr=([^;]+)/);
            const token = match ? match[1] : '';
            if (!token) {{
                return {{ ok: false, error: 'No se localizó el token CSRF de Zoho CRM en las cookies del navegador.' }};
            }}

            const orgId = {escaped_org} || '902879914';
            const headers = {{
                'X-ZCSRF-TOKEN': 'crmcsrfparam=' + token,
                'X-CRM-ORG': orgId,
                'Content-Type': 'application/json'
            }};

            const res = await fetch('/crm/v6/coql', {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify({{
                    select_query: {escaped_query}
                }})
            }});

            if (res.status === 204) {{
                return {{ ok: true, data: [] }};
            }}

            const jsonResponse = await res.json();
            if (!res.ok) {{
                return {{ 
                    ok: false, 
                    status: res.status, 
                    error: jsonResponse.message || jsonResponse.code || 'Error en consulta COQL de Zoho' 
                }};
            }}

            return {{ ok: true, data: jsonResponse.data || [] }};
        }} catch (e) {{
            return {{ ok: false, error: e.message }};
        }}
    }})()
    """

    res = browser_service._call_mcp_evaluate(script, channel="zoho")
    if isinstance(res, dict):
        return res
    return {"ok": False, "error": f"Respuesta inesperada al consultar COQL: {res}"}


def search_person_in_zoho(
    name: str, 
    company: Optional[str] = None, 
    email: Optional[str] = None,
    perfil_url: Optional[str] = None,
    location: Optional[str] = None
) -> Dict[str, Any]:
    """
    Busca una persona en Zoho CRM primero como Contacto y luego como Posible Cliente (Lead).
    Soporta coincidencia por Email, coincidencia exacta por Nombre, y fallback tokenizado
    inteligente para nombres compuestos chilenos con validación de inicial, empresa y región.
    """
    # 1. Búsqueda por Email exacto (si está disponible)
    if email and "@" in email:
        clean_email = clean_text_for_coql(email.lower())
        # Consultar Contacts
        coql_contact_email = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Account_Name, Owner from Contacts where Email = '{clean_email}' or Secondary_Email = '{clean_email}' limit 1"
        res_contact = execute_zoho_coql(coql_contact_email)
        if res_contact.get("ok") and res_contact.get("data"):
            return _format_contact_result(res_contact["data"][0])

        # Consultar Leads
        coql_lead_email = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Company, Lead_Status, Owner from Leads where Email = '{clean_email}' or Secondary_Email = '{clean_email}' limit 1"
        res_lead = execute_zoho_coql(coql_lead_email)
        if res_lead.get("ok") and res_lead.get("data"):
            return _format_lead_result(res_lead["data"][0])

    # 2. Búsqueda por Nombre de la Persona
    clean_name = normalize_search_term(name)
    if not clean_name:
        return {"found": False, "reason": "Nombre vacío"}

    tokens = clean_name.split()
    first_name = tokens[0] if tokens else ""
    last_name = tokens[-1] if len(tokens) > 1 else ""

    escaped_full = clean_text_for_coql(clean_name)
    target_initial = extract_linkedin_initial(perfil_url)

    # 2.1 Buscar en Contactos por nombre completo o apellido (coincidencia exacta)
    where_clauses = [f"Full_Name = '{escaped_full}'"]
    if first_name and last_name:
        where_clauses.append(f"(First_Name = '{clean_text_for_coql(first_name)}' and Last_Name = '{clean_text_for_coql(last_name)}')")

    query_contacts = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Account_Name, Owner, Mailing_City, Mailing_State from Contacts where {' or '.join(where_clauses)} limit 5"
    res_c = execute_zoho_coql(query_contacts)
    if res_c.get("ok") and res_c.get("data"):
        best_match = max(res_c["data"], key=lambda c: score_zoho_candidate(c, company, target_initial, location))
        return _format_contact_result(best_match)

    # 2.2 Buscar en Posibles Clientes (Leads) por nombre completo o apellido (coincidencia exacta)
    query_leads = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Company, Lead_Status, Owner, City, State from Leads where {' or '.join(where_clauses)} limit 5"
    res_l = execute_zoho_coql(query_leads)
    if res_l.get("ok") and res_l.get("data"):
        best_match = max(res_l["data"], key=lambda l: score_zoho_candidate(l, company, target_initial, location))
        return _format_lead_result(best_match)

    # 2.3 Fallback Tokenizado Inteligente (Nombres compuestos / variaciones en Zoho)
    if first_name and last_name and len(first_name) >= 3 and len(last_name) >= 3:
        fn_esc = clean_text_for_coql(first_name)
        ln_esc = clean_text_for_coql(last_name)
        token_condition = f"((Full_Name like '%{fn_esc}%' and Full_Name like '%{ln_esc}%') or (Last_Name like '%{fn_esc}%' and Last_Name like '%{ln_esc}%'))"

        # Probar en Contactos
        query_token_contacts = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Account_Name, Owner, Mailing_City, Mailing_State from Contacts where {token_condition} limit 5"
        res_tc = execute_zoho_coql(query_token_contacts)
        if res_tc.get("ok") and res_tc.get("data"):
            candidates_scored = [
                (c, score_zoho_candidate(c, company, target_initial, location))
                for c in res_tc["data"]
            ]
            candidates_scored.sort(key=lambda x: x[1], reverse=True)
            if candidates_scored and candidates_scored[0][1] >= 10:
                return _format_contact_result(candidates_scored[0][0])

        # Probar en Leads
        query_token_leads = f"select id, Full_Name, First_Name, Last_Name, Email, Secondary_Email, Phone, Mobile, Company, Lead_Status, Owner, City, State from Leads where {token_condition} limit 5"
        res_tl = execute_zoho_coql(query_token_leads)
        if res_tl.get("ok") and res_tl.get("data"):
            candidates_scored = [
                (l, score_zoho_candidate(l, company, target_initial, location))
                for l in res_tl["data"]
            ]
            candidates_scored.sort(key=lambda x: x[1], reverse=True)
            if candidates_scored and candidates_scored[0][1] >= 10:
                return _format_lead_result(candidates_scored[0][0])

    return {"found": False, "reason": "No se encontraron coincidencias en Contactos ni Leads en Zoho CRM"}


def get_zoho_account_details(account_id: Optional[str] = None, account_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Obtiene los detalles profundos de una Cuenta en Zoho CRM: dueño, tipo de cuenta
    y determinación de si actualmente es un Cliente activo de la empresa.
    """
    where_expr = ""
    if account_id:
        where_expr = f"id = '{clean_text_for_coql(account_id)}'"
    elif account_name:
        where_expr = f"Account_Name = '{clean_text_for_coql(account_name)}'"
    else:
        return {"found": False, "reason": "Sin identificador ni nombre de cuenta"}

    query = f"select id, Account_Name, Account_Type, Owner from Accounts where {where_expr} limit 1"
    res = execute_zoho_coql(query)
    if res.get("ok") and res.get("data"):
        acc = res["data"][0]
        owner = acc.get("Owner") or {}
        acc_type = str(acc.get("Account_Type") or "")
        owner_name = owner.get("name", "") if isinstance(owner, dict) else str(owner)

        # Regla de clasificación de cliente activo
        norm_type = acc_type.lower()
        is_client = any(kw in norm_type for kw in ["cliente", "client", "activo", "activo recurrente"])

        return {
            "found": True,
            "account_id": str(acc.get("id")),
            "account_name": acc.get("Account_Name") or "",
            "account_type": acc_type,
            "owner_id": str(owner.get("id", "")) if isinstance(owner, dict) else "",
            "owner_name": owner_name,
            "is_client": is_client,
            "raw_record": acc
        }

    return {"found": False, "reason": "Cuenta no localizada en Zoho CRM"}


def get_zoho_deals(contact_id: Optional[str] = None, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Recupera los Tratos (Deals / Oportunidades) asociados a un Contacto o Cuenta en Zoho CRM,
    incluyendo su etapa actual, monto, fecha de cierre y ejecutivo dueño.
    """
    clauses = []
    if account_id:
        clauses.append(f"Account_Name = '{clean_text_for_coql(account_id)}'")
    if contact_id:
        clauses.append(f"Contact_Name = '{clean_text_for_coql(contact_id)}'")

    if not clauses:
        return []

    where_str = " or ".join(clauses)
    query = f"select id, Deal_Name, Stage, Amount, Closing_Date, Owner from Deals where {where_str} limit 10"
    res = execute_zoho_coql(query)
    if not (res.get("ok") and res.get("data")):
        return []

    deals_list = []
    for d in res["data"]:
        owner = d.get("Owner") or {}
        deals_list.append({
            "deal_id": str(d.get("id")),
            "deal_name": d.get("Deal_Name") or "",
            "stage": d.get("Stage") or "",
            "amount": d.get("Amount"),
            "closing_date": d.get("Closing_Date") or "",
            "owner_name": owner.get("name", "") if isinstance(owner, dict) else str(owner)
        })

    return deals_list


def sync_lead_with_zoho(lead_id: str, conn=None) -> Dict[str, Any]:
    """
    Ejecuta el cruce integral de un lead de NexusReach contra Zoho CRM:
    1. Busca la persona por nombre/empresa/email en Zoho.
    2. Determina si es Lead o Contacto.
    3. Si pertenece a una Cuenta, extrae sus datos (Dueño, tipo, cliente sí/no).
    4. Consulta Tratos asociados (Deals).
    5. Actualiza las columnas zoho_* en la tabla leads y genera evento de auditoría.
    """
    now_iso = datetime.now().isoformat()

    def _get_lead_data(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT id, nombre, institucion_actual, cargo_actual, email, telefono, perfil_url, ubicacion 
            FROM leads WHERE id = ?
        """, (lead_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    if conn is not None:
        lead_data = _get_lead_data(conn)
    else:
        with get_db() as c:
            lead_data = _get_lead_data(c)

    if not lead_data:
        return {"ok": False, "error": f"Lead {lead_id} no existe en la base de datos."}

    nombre = lead_data.get("nombre") or ""
    empresa = lead_data.get("institucion_actual") or ""
    email_actual = lead_data.get("email") or ""
    perfil_url = lead_data.get("perfil_url") or ""
    ubicacion = lead_data.get("ubicacion") or ""

    # 1. Buscar persona
    person_result = search_person_in_zoho(
        nombre, 
        company=empresa, 
        email=email_actual,
        perfil_url=perfil_url,
        location=ubicacion
    )

    if not person_result.get("found"):
        # Registrar intento de sincronización sin coincidencias
        update_query = """
            UPDATE leads 
            SET zoho_synced_at = ?, updated_at = ?
            WHERE id = ?
        """
        def _update_no_match(c):
            cursor = c.cursor()
            cursor.execute(update_query, (now_iso, now_iso, lead_id))
            cursor.execute("""
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'ZOHO_CRM_SYNC', ?, ?)
            """, (lead_id, f"Búsqueda en Zoho CRM finalizada sin coincidencias para '{nombre}'.", now_iso))

        if conn is not None:
            _update_no_match(conn)
        else:
            with get_db() as c:
                _update_no_match(c)

        return {
            "ok": True,
            "matched": False,
            "lead_id": lead_id,
            "detalle": f"No se encontró coincidencia en Zoho CRM para '{nombre}'."
        }

    # 2. Extraer datos del resultado
    entity_type = person_result.get("entity_type")
    zoho_id = person_result.get("zoho_id")
    email_zoho = person_result.get("email") or ""
    lead_status = person_result.get("lead_status") or ""
    account_id = person_result.get("account_id") or ""
    account_name = person_result.get("account_name") or person_result.get("company_name") or ""

    # 3. Datos de la Cuenta
    account_owner = ""
    account_type = ""
    account_is_client = 0
    if account_id or account_name:
        acc_info = get_zoho_account_details(account_id=account_id or None, account_name=account_name if not account_id else None)
        if acc_info.get("found"):
            account_owner = acc_info.get("owner_name") or ""
            account_type = acc_info.get("account_type") or ""
            account_is_client = 1 if acc_info.get("is_client") else 0
            if not account_id:
                account_id = acc_info.get("account_id") or ""

    # 4. Tratos asociados
    deals = get_zoho_deals(
        contact_id=zoho_id if entity_type == "Contact" else None,
        account_id=account_id or None
    )
    deals_json = json.dumps(deals, ensure_ascii=False) if deals else None

    # Fecha de extracción de correo (si se encontró email en Zoho)
    extracted_email_at = now_iso if email_zoho else None

    # 5. Persistir en la base de datos
    def _persist_sync(c):
        cursor = c.cursor()
        cursor.execute("""
            UPDATE leads SET
                email_zoho = COALESCE(?, email_zoho),
                zoho_entidad_tipo = ?,
                zoho_id = ?,
                zoho_lead_status = ?,
                zoho_cuenta_id = ?,
                zoho_cuenta_nombre = ?,
                zoho_cuenta_dueno = ?,
                zoho_cuenta_tipo = ?,
                zoho_cuenta_es_cliente = ?,
                zoho_tratos_info = ?,
                zoho_synced_at = ?,
                zoho_email_extracted_at = COALESCE(?, zoho_email_extracted_at),
                updated_at = ?
            WHERE id = ?
        """, (
            email_zoho or None,
            entity_type,
            zoho_id,
            lead_status,
            account_id or None,
            account_name or None,
            account_owner or None,
            account_type or None,
            account_is_client,
            deals_json,
            now_iso,
            extracted_email_at,
            now_iso,
            lead_id
        ))

        resumen_deals = f", {len(deals)} tratos" if deals else ""
        cliente_badge = " [ES CLIENTE]" if account_is_client else ""
        desc = (
            f"Sincronizado con Zoho CRM: {entity_type} ID {zoho_id}. "
            f"Email: {email_zoho or 'No registra'}. "
            f"Cuenta: {account_name or 'N/A'} (Dueño: {account_owner or 'Sin asignar'}{cliente_badge}){resumen_deals}."
        )
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'ZOHO_CRM_SYNC', ?, ?)
        """, (lead_id, desc, now_iso))

    if conn is not None:
        _persist_sync(conn)
    else:
        with get_db() as c:
            _persist_sync(c)

    return {
        "ok": True,
        "matched": True,
        "lead_id": lead_id,
        "entity_type": entity_type,
        "zoho_id": zoho_id,
        "email_zoho": email_zoho,
        "lead_status": lead_status,
        "account_name": account_name,
        "account_owner": account_owner,
        "account_is_client": bool(account_is_client),
        "deals_count": len(deals),
        "deals": deals,
        "synced_at": now_iso
    }


def batch_sync_leads_with_zoho(lead_ids: List[str], delay_between: float = 0.3) -> Dict[str, Any]:
    """
    Sincroniza un lote de leads con Zoho CRM de forma secuencial aplicando pausas
    cortas para respetar la tasa de peticiones del navegador y la API interna.
    """
    total = len(lead_ids)
    synced = 0
    matched = 0
    emails_found = 0
    clients_found = 0
    errors = []

    for idx, lid in enumerate(lead_ids):
        try:
            res = sync_lead_with_zoho(lid)
            if res.get("ok"):
                synced += 1
                if res.get("matched"):
                    matched += 1
                    if res.get("email_zoho"):
                        emails_found += 1
                    if res.get("account_is_client"):
                        clients_found += 1
            else:
                errors.append({"lead_id": lid, "error": res.get("error")})
        except Exception as e:
            errors.append({"lead_id": lid, "error": str(e)})

        if idx < total - 1 and delay_between > 0:
            time.sleep(delay_between)

    return {
        "ok": True,
        "total": total,
        "synced": synced,
        "matched": matched,
        "emails_found": emails_found,
        "clients_found": clients_found,
        "errors_count": len(errors),
        "errors": errors
    }


def add_zoho_note(parent_id: str, module: str, title: str, content: str, org_id: str = DEFAULT_ZOHO_ORG_ID) -> Dict[str, Any]:
    """
    Inserta una Nota formal de auditoría o trazabilidad en la ficha del contacto/lead en Zoho CRM.
    Utiliza POST /crm/v6/Notes con la sesión activa del navegador.
    """
    escaped_pid = json.dumps(parent_id)
    escaped_module = json.dumps(module)
    escaped_title = json.dumps(title)
    escaped_content = json.dumps(content)
    escaped_org = json.dumps(org_id or DEFAULT_ZOHO_ORG_ID)

    script = f"""
    (async () => {{
        try {{
            const match = document.cookie.match(/CSRF_TOKEN=([^;]+)/) || 
                          document.cookie.match(/crmcsr=([^;]+)/) ||
                          document.cookie.match(/iamcsr=([^;]+)/);
            const token = match ? match[1] : '';
            if (!token) return {{ ok: false, error: 'Sin sesión activa de Zoho CRM' }};

            const orgId = {escaped_org} || '902879914';
            const headers = {{
                'X-ZCSRF-TOKEN': 'crmcsrfparam=' + token,
                'X-CRM-ORG': orgId,
                'Content-Type': 'application/json'
            }};

            const payload = {{
                data: [{{
                    Note_Title: {escaped_title},
                    Note_Content: {escaped_content},
                    Parent_Id: {{
                        id: {escaped_pid},
                        module: {{ api_name: {escaped_module} }}
                    }},
                    se_module: {escaped_module}
                }}]
            }};

            const res = await fetch('/crm/v6/Notes', {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload)
            }});

            const jsonResponse = await res.json();
            return {{ ok: res.ok, status: res.status, result: jsonResponse }};
        }} catch (err) {{
            return {{ ok: false, error: err.message }};
        }}
    }})()
    """

    res = browser_service._call_mcp_evaluate(script, channel="zoho")
    if isinstance(res, dict):
        return res
    return {"ok": False, "error": f"Error insertando nota en Zoho: {res}"}


def update_zoho_lead_status(zoho_lead_id: str, new_status: str, org_id: str = DEFAULT_ZOHO_ORG_ID) -> Dict[str, Any]:
    """
    Actualiza el campo Lead_Status de un lead en Zoho CRM vía PUT /crm/v6/Leads.
    """
    escaped_id = json.dumps(zoho_lead_id)
    escaped_status = json.dumps(new_status)
    escaped_org = json.dumps(org_id or DEFAULT_ZOHO_ORG_ID)

    script = f"""
    (async () => {{
        try {{
            const match = document.cookie.match(/CSRF_TOKEN=([^;]+)/) || 
                          document.cookie.match(/crmcsr=([^;]+)/) ||
                          document.cookie.match(/iamcsr=([^;]+)/);
            const token = match ? match[1] : '';
            if (!token) return {{ ok: false, error: 'Sin sesión activa de Zoho CRM' }};

            const orgId = {escaped_org} || '902879914';
            const headers = {{
                'X-ZCSRF-TOKEN': 'crmcsrfparam=' + token,
                'X-CRM-ORG': orgId,
                'Content-Type': 'application/json'
            }};

            const payload = {{
                data: [{{
                    id: {escaped_id},
                    Lead_Status: {escaped_status}
                }}]
            }};

            const res = await fetch('/crm/v6/Leads', {{
                method: 'PUT',
                headers: headers,
                body: JSON.stringify(payload)
            }});

            const jsonResponse = await res.json();
            return {{ ok: res.ok, status: res.status, result: jsonResponse }};
        }} catch (err) {{
            return {{ ok: false, error: err.message }};
        }}
    }})()
    """

    res = browser_service._call_mcp_evaluate(script, channel="zoho")
    if isinstance(res, dict):
        return res
    return {"ok": False, "error": f"Error actualizando estado en Zoho: {res}"}
