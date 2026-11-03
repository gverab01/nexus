import json
import time
import re
import urllib.parse
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

import database
from database import get_db
import browser_service
import safety_engine
import logger_service

SYNC_CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

EXTRACT_CONNECTIONS_JS = """
(async () => {
    try {
        // 1. Scroll suave progresivo hacia abajo para renderizar más tarjetas del DOM
        for (let s = 0; s < 3; s++) {
            window.scrollBy({ top: 1200, behavior: 'smooth' });
            await new Promise(r => setTimeout(r, 700));
        }

        const results = [];
        const seen = new Set();

        // 2. Extraer todos los enlaces de perfiles /in/ en la página de conexiones
        const allLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));

        for (const a of allLinks) {
            const rawHref = a.getAttribute('href') || '';
            const cleanHref = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
            if (!cleanHref.includes('/in/') || cleanHref.includes('/in/edit') || cleanHref.includes('/in/unavailable')) continue;
            if (seen.has(cleanHref)) continue;

            // Obtener contenedor de la tarjeta de conexión
            const card = a.closest('li') || a.parentElement;
            const cardText = card ? (card.innerText || '').trim() : '';
            const lines = cardText.split('\\n').map(s => s.trim()).filter(Boolean);

            // Extraer nombre, titular/cargo y fecha de conexión
            const name = (a.innerText || '').trim() || lines[0] || '';
            const headline = lines.find(l => !l.toLowerCase().includes('contacto desde') && !l.toLowerCase().includes('enviar mensaje') && l !== name) || '';
            const timeText = lines.find(l => l.toLowerCase().includes('contacto desde') || l.toLowerCase().includes('connected')) || '';

            seen.add(cleanHref);
            results.push({
                url: cleanHref,
                nombre: name,
                tiempo: timeText,
                cargo: headline
            });
        }

        return {
            ok: true,
            total_encontrados: results.length,
            conexiones: results
        };
    } catch (e) {
        return { ok: false, error: e.message };
    }
})()
"""

def normalize_profile_url(url: str) -> str:
    """Normaliza URLs de LinkedIn para matching exacto ignorando query params, slashes finales y decodificando tildes."""
    if not url:
        return ""
    # Decodificar percent-encoding (ej. %C3%AD -> í)
    unquoted = urllib.parse.unquote(url)
    clean = unquoted.split("?")[0].strip().rstrip("/")
    if clean and not clean.endswith("/"):
        clean += "/"
    return clean.lower()

def extract_slug(url: str) -> str:
    """Extrae el slug de perfil /in/{slug}/ para matching secundario tolerante a variaciones de URL."""
    norm = normalize_profile_url(url)
    m = re.search(r'/in/([^/]+)', norm)
    return m.group(1).lower() if m else ""

def sync_accepted_connections(tenant_id: Optional[str] = None, force_outside_hours: bool = False) -> Dict[str, Any]:
    """
    Inspecciona https://www.linkedin.com/mynetwork/invite-connect/connections/ en el navegador de trabajo
    y actualiza automáticamente el estado de los leads que hayan aceptado la solicitud a CONECTADO.
    """
    # 1. Comprobar controles antiban (a menos que sea forzado manualmente por el usuario)
    if not force_outside_hours:
        if not safety_engine.is_campaign_active():
            return {
                "ok": False,
                "motivo": "kill_switch",
                "mensaje": "La sincronización se omitió: Kill-Switch Antiban global está activado (campaña pausada)."
            }
        if not safety_engine.is_working_hours():
            return {
                "ok": False,
                "motivo": "fuera_horario",
                "mensaje": "La sincronización automática se omitió: Fuera de horario laboral configurado."
            }

    # 2. Comprobar si el navegador aislado está operativo y con sesión activa
    if not browser_service.is_electron_running() and not browser_service.is_browseros_running():
        return {
            "ok": False,
            "motivo": "browser_offline",
            "mensaje": "El navegador de trabajo (Chromium / BrowserOS) no está iniciado."
        }

    extracted_connections: List[Dict[str, str]] = []

    # 3. Vía preferente y segura: Función nativa precompilada en Electron (Regla C-01 Directrices v1.3)
    if browser_service.is_electron_running():
        net_res = browser_service.extract_network_from_electron(source="connections", limit=100)
        if not net_res.get("success") and not net_res.get("leads"):
            return {
                "ok": False,
                "motivo": "extract_error",
                "mensaje": f"Error extrayendo conexiones de LinkedIn: {net_res.get('error', 'Error en Electron')}"
            }
        for lead in net_res.get("leads", []):
            extracted_connections.append({
                "nombre": lead.get("nombre", ""),
                "perfil_url": lead.get("perfil_url", ""),
                "slug": lead.get("slug", ""),
                "cargo_titular": lead.get("cargo_titular", ""),
                "tiempo_conectado": lead.get("tiempo_conectado", "Reciente")
            })
    else:
        # Fallback BrowserOS MCP si no está en Electron
        nav_res = browser_service.open_url(SYNC_CONNECTIONS_URL)
        time.sleep(4.5)
        eval_res = browser_service._call_mcp_evaluate(EXTRACT_CONNECTIONS_JS)
        if not isinstance(eval_res, dict) or not eval_res.get("ok"):
            error_msg = eval_res.get("error") if isinstance(eval_res, dict) else str(eval_res)
            return {
                "ok": False,
                "motivo": "eval_error",
                "mensaje": f"Error extrayendo conexiones de LinkedIn: {error_msg}"
            }
        extracted_connections = eval_res.get("conexiones") or []

    if not extracted_connections:
        return {
            "ok": True,
            "nuevos_conectados": 0,
            "total_inspeccionados": 0,
            "mensaje": "No se encontraron conexiones visibles en la página o la sesión requiere reautenticación."
        }

    # 5. Obtener leads de la base de datos que tienen invitación pendiente o enviada
    with get_db() as conn:
        cursor = conn.cursor()
        tenant_filter = "AND tenant_id = ?" if tenant_id else ""
        params = [tenant_id] if tenant_id else []
        cursor.execute(f"""
            SELECT id, nombre, perfil_url, estado, tenant_id
            FROM leads
            WHERE estado IN ('INVITACION_ENVIADA', 'INVITACION_PENDIENTE', 'EXTRAIDO', 'PERFIL_VISITADO')
            {tenant_filter}
        """, params)
        pending_leads = cursor.fetchall()

    if not pending_leads:
        return {
            "ok": True,
            "nuevos_conectados": 0,
            "total_inspeccionados": len(extracted_connections),
            "mensaje": f"Se inspeccionaron {len(extracted_connections)} conexiones recientes en LinkedIn. No hay prospectos locales con invitación pendiente."
        }

    # 6. Mapear conexiones por URL y Slug
    conns_by_slug = {}
    conns_by_url = {}
    for c in extracted_connections:
        n_url = normalize_profile_url(c.get("url", ""))
        slug = extract_slug(n_url)
        if n_url:
            conns_by_url[n_url] = c
        if slug:
            conns_by_slug[slug] = c

    now_iso = datetime.now().isoformat()
    matched_leads = []

    with get_db() as conn:
        cursor = conn.cursor()
        for lead in pending_leads:
            lead_url = normalize_profile_url(lead.get("perfil_url", ""))
            lead_slug = extract_slug(lead_url)
            
            matched = conns_by_url.get(lead_url) or (conns_by_slug.get(lead_slug) if lead_slug else None)
            
            if matched:
                # Actualizar estado a CONECTADO con fecha y grado
                cursor.execute("""
                    UPDATE leads
                    SET estado = 'CONECTADO',
                        fecha_conexion = ?,
                        grado_red = '1º',
                        updated_at = ?
                    WHERE id = ?
                """, (now_iso, now_iso, lead["id"]))

                # Sincronizar también en secuencias activas
                cursor.execute("""
                    UPDATE leads_en_secuencia
                    SET notas_ejecucion = COALESCE(notas_ejecucion, '') || ' [Conexión aceptada]'
                    WHERE lead_id = ?
                """, (lead["id"],))

                # Registrar auditoría en historial
                cursor.execute("""
                    INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                    VALUES (?, 'CONEXION_ACEPTADA', ?, ?)
                """, (
                    lead["id"], 
                    f"Invitación aceptada confirmada vía inspección de conexiones de LinkedIn ({matched.get('tiempo', 'Reciente')}).", 
                    now_iso
                ))

                matched_leads.append({
                    "id": lead["id"],
                    "nombre": lead["nombre"],
                    "perfil_url": lead["perfil_url"],
                    "tiempo_linkedin": matched.get("tiempo", "")
                })

                # Disparar resolución/extracción de correo en cascada en segundo plano
                try:
                    import email_resolver_service
                    threading.Thread(
                        target=email_resolver_service.resolve_lead_email,
                        args=(lead["id"],),
                        daemon=True
                    ).start()
                except Exception as ex_err:
                    print(f"[Sync Warning] No se pudo iniciar extracción de correo para {lead['id']}: {ex_err}")

    # Registrar timestamp persistente de la última verificación en la base de datos
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO configuracion_seguridad (clave, valor, updated_at)
                VALUES ('ultima_verificacion_conexiones_at', ?, ?)
            """, (now_iso, now_iso))
    except Exception as e:
        print(f"[Sync Warning] Error persistiendo timestamp de verificación: {e}")

    # Emitir suceso estructurado en system_logs para la vista de Auditoría y Logs de la plataforma
    if matched_leads:
        logger_service.log_event(
            level="SUCCESS",
            module="SYNC",
            message=f"Verificación completada: {len(matched_leads)} nuevo(s) prospecto(s) aceptaron la conexión en LinkedIn.",
            details={
                "nuevos_conectados": len(matched_leads),
                "total_inspeccionados": len(extracted_connections),
                "leads": [m.get("nombre") for m in matched_leads]
            }
        )
    else:
        logger_service.log_event(
            level="INFO",
            module="SYNC",
            message=f"Inspección de conexiones completada: {len(extracted_connections)} perfiles revisados en LinkedIn (0 nuevas aceptaciones de prospectos pendientes).",
            details={
                "total_inspeccionados": len(extracted_connections),
                "pendientes_locales": len(pending_leads)
            }
        )

    return {
        "ok": True,
        "nuevos_conectados": len(matched_leads),
        "total_inspeccionados": len(extracted_connections),
        "leads": matched_leads,
        "mensaje": f"Sincronización completada: {len(matched_leads)} nuevo(s) prospecto(s) detectado(s) como CONECTADO.",
        "ultima_verificacion": now_iso
    }

def get_last_connection_sync_info() -> Dict[str, Any]:
    """Retorna la fecha y metadatos de la última verificación de conexiones ejecutada."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'ultima_verificacion_conexiones_at'")
            row = cursor.fetchone()
            return {"ultima_verificacion": row["valor"] if row else None}
    except Exception:
        return {"ultima_verificacion": None}

# =========================================================================
# BACKGROUND WORKER (Verificación periódica en horario comercial)
# =========================================================================
_sync_worker_thread = None
_sync_worker_running = False

def _periodic_sync_loop(interval_seconds: int = 1800):
    """
    Bucle en segundo plano que corre cada 30 minutos (1800 segundos)
    respetando horario comercial y controles antiban.
    """
    global _sync_worker_running
    while _sync_worker_running:
        try:
            # Esperar 45 segundos iniciales tras el arranque antes del primer chequeo
            time.sleep(45)
            
            # Ejecutar sincronización si estamos en horario comercial y con antiban activo
            if safety_engine.is_working_hours() and safety_engine.is_campaign_active():
                print("[ConnectionSync] Iniciando inspección programada de conexiones de LinkedIn...")
                res = sync_accepted_connections()
                print(f"[ConnectionSync] Resultado: {res.get('mensaje')}")
        except Exception as e:
            print(f"[ConnectionSync] Error en bucle periódico: {e}")

        # Dormir intervalo configurado (por defecto 30 minutos)
        sleep_elapsed = 0
        while _sync_worker_running and sleep_elapsed < interval_seconds:
            time.sleep(10)
            sleep_elapsed += 10

def start_periodic_connection_sync():
    """Inicia el hilo daemon en segundo plano para la verificación periódica."""
    global _sync_worker_thread, _sync_worker_running
    if _sync_worker_thread and _sync_worker_thread.is_alive():
        return
    _sync_worker_running = True
    _sync_worker_thread = threading.Thread(target=_periodic_sync_loop, daemon=True, name="NexusReach_ConnectionSync")
    _sync_worker_thread.start()
    print("[ConnectionSync] Worker de sincronización periódica de conexiones activado (cada 30 min en horario comercial).")
