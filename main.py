import os
import json
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from database import get_db, init_db, migrar_desde_json
import browser_service
import safety_engine
import extractor_engine
import sequence_engine
import lists_engine
import auth_service
import task_dispatcher

app = FastAPI(
    title="NexusReach Pro",
    description="Motor local de prospección y gestión multicanal B2B",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Static files mounting
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
def startup_event():
    init_db()
    migrar_desde_json()

@app.get("/")
def read_root():
    dist_index = os.path.join(STATIC_DIR, "dist", "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "status": "online",
        "app": "NexusReach Pro"
    }

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "uptime": "ok"}

# ==========================================
# AUTHENTICATION & SUBSCRIPTION VALIDATION
# ==========================================

class LoginRequest(BaseModel):
    email: str
    password: str

class UpdateSubscriptionRequest(BaseModel):
    estado: Optional[str] = None
    plan: Optional[str] = None
    dias_extra: Optional[int] = None
    nueva_fecha_expira: Optional[str] = None

# Backward compatibility alias for request model
UpdateSuscripcionRequest = UpdateSubscriptionRequest

@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Authenticates user and checks active subscription."""
    remote_url = os.environ.get("REMOTE_AUTH_URL")
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'remote_auth_url'")
            row = cur.fetchone()
            if row and row["valor"]:
                remote_url = row["valor"]
    except Exception:
        pass

    result = auth_service.authenticate_user(req.email, req.password, remote_url=remote_url)
    if not result["exito"]:
        status_code = 403 if "SUSCRIPCION" in result.get("codigo", "") else 401
        raise HTTPException(status_code=status_code, detail=result)
    return result

@app.get("/api/auth/sesion")
def verify_session(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """Verifies whether memory token is valid and subscription remains active."""
    final_token = token
    if not final_token and authorization:
        if authorization.lower().startswith("bearer "):
            final_token = authorization[7:].strip()
        else:
            final_token = authorization.strip()

    if not final_token:
        raise HTTPException(status_code=401, detail="Token de sesión no suministrado")

    session = auth_service.verify_token(final_token)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión no válida o suscripción inactiva")

    return {"autenticado": True, "usuario": session}

verificar_sesion = verify_session

@app.post("/api/auth/logout")
def logout(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """Logs out and destroys memory session token."""
    final_token = token
    if not final_token and authorization:
        if authorization.lower().startswith("bearer "):
            final_token = authorization[7:].strip()
        else:
            final_token = authorization.strip()

    if final_token:
        auth_service.logout_user(final_token)
    return {"status": "ok", "mensaje": "Sesión cerrada exitosamente"}

@app.get("/api/auth/usuarios")
def get_users():
    """Lists users and their subscription statuses."""
    return auth_service.list_users()

get_usuarios = get_users

@app.patch("/api/auth/usuarios/{user_id}/suscripcion")
def update_subscription(user_id: str, req: UpdateSubscriptionRequest):
    """Allows renewing, extending, or pausing a user's subscription."""
    res = auth_service.update_user_subscription(
        user_id=user_id,
        status=req.estado,
        plan=req.plan,
        extra_days=req.dias_extra,
        new_expires_at=req.nueva_fecha_expira
    )
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

update_suscripcion = update_subscription

class DeltaSeatsRequest(BaseModel):
    delta: int

DeltaPuestosRequest = DeltaSeatsRequest

class CreateAgencyClientRequest(BaseModel):
    razon_social: str
    modelo_cobro: str = "POR_PUESTO"
    tarifa_por_reunion: float = 0.0
    precio_cliente_por_puesto: float = 0.0
    fee_fijo_mensual: float = 0.0
    puestos_asignados: int = 1

CrearClienteAgenciaRequest = CreateAgencyClientRequest

class CreateAccountRequest(BaseModel):
    tipo_cuenta: str  # 'FREELANCER', 'EMPRESA', 'AGENCIA'
    razon_social: str
    admin_nombre: str
    admin_email: str
    admin_password: str
    precio_unitario: float = 35.0
    puestos_contratados: int = 1
    periodicidad: str = "MENSUAL"
    operadores: Optional[List[Dict[str, str]]] = []
    cliente_empresa_inicial: Optional[Dict[str, Any]] = None

CrearCuentaRequest = CreateAccountRequest

# ==========================================
# MULTI-TENANT & AGENCY ENDPOINTS
# ==========================================

def _get_current_user(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
) -> Optional[Dict[str, Any]]:
    token = x_session_token
    if not token and authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()
    if not token:
        return None
    return auth_service.verify_token(token)

_obtener_usuario_actual = _get_current_user

def _resolve_permitted_tenants(caller: Optional[Dict[str, Any]], tenant_query: Optional[str] = None) -> List[str]:
    """
    Resolves permitted tenant_id for queries (STRICT MONO-TENANT ISOLATION):
    - Leads, sequences, and list tables are NEVER shared across different companies.
    - Super Admin: Explicit tenant_query accesses ONLY that tenant. Default: own 'ten_superadmin'.
    - Agency Admin: Explicit tenant_query accesses ONLY that company. Default: own agency.
    - Operators / Members: Strictly confined to their own company tenant_id.
    """
    if not caller:
        return [tenant_query] if tenant_query else ["ten_unauthorized"]

    role = caller.get("rol")
    caller_tenant = caller.get("tenant_id") or "ten_superadmin"

    if role == "SUPER_ADMIN":
        return [tenant_query] if tenant_query else [caller_tenant]

    if role == "AGENCY_ADMIN":
        subtenants = auth_service.list_agency_subtenants(caller_tenant)
        valid_ids = [caller_tenant] + [st["id"] for st in subtenants]
        if tenant_query:
            if tenant_query in valid_ids:
                return [tenant_query]
            raise HTTPException(status_code=403, detail="No tienes autorización para acceder a los datos de este workspace.")
        return [caller_tenant]

    return [caller_tenant]

_resolver_tenants_permitidos = _resolve_permitted_tenants

@app.get("/api/tenants")
def get_tenants(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Global tenant directory for Super Admin."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    return auth_service.list_global_tenants()

@app.post("/api/admin/cuentas")
def create_account(
    req: CreateAccountRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Creates a new client account from Super Admin (Freelancer, Empresa, Agencia)."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    res = auth_service.create_account_full(
        tipo_cuenta=req.tipo_cuenta,
        razon_social=req.razon_social,
        admin_nombre=req.admin_nombre,
        admin_email=req.admin_email,
        admin_password=req.admin_password,
        precio_unitario=req.precio_unitario,
        puestos_contratados=req.puestos_contratados,
        periodicidad=req.periodicidad,
        operadores=req.operadores,
        cliente_empresa_inicial=req.cliente_empresa_inicial
    )
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje", "Error al crear la cuenta."))
    return res

crear_cuenta = create_account

@app.post("/api/tenants/{tenant_id}/revocar")
def revoke_tenant(
    tenant_id: str, 
    motivo: str = Query("Revocado por Super Admin"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Revokes a tenant license in real-time."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    auth_service.revoke_tenant_license(tenant_id, motivo)
    return {"status": "ok", "mensaje": f"Licencia de {tenant_id} revocada"}

revocar_tenant = revoke_tenant

@app.post("/api/tenants/{tenant_id}/reactivar")
def reactivate_tenant(
    tenant_id: str, 
    dias: int = Query(30),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Reactivates a tenant license."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    auth_service.reactivate_tenant_license(tenant_id, dias)
    return {"status": "ok", "mensaje": f"Licencia de {tenant_id} reactivada por {dias} días"}

reactivar_tenant = reactivate_tenant

@app.post("/api/tenants/{tenant_id}/puestos")
def adjust_seats(
    tenant_id: str, 
    req: DeltaSeatsRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Adds or subtracts contracted seats from pool."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Acceso denegado a la gestión de puestos de este tenant.")
    res = auth_service.update_seat_pool(tenant_id, req.delta)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

ajustar_puestos = adjust_seats

@app.get("/api/agencia/{agencia_id}/clientes")
def get_agency_clients(
    agencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lists all agency clients with allocated seats and financial models."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id:
        raise HTTPException(status_code=403, detail="Acceso denegado: Cartera restringida a la agencia propietaria.")
    return auth_service.list_agency_subtenants(agencia_id)

get_clientes_agencia = get_agency_clients

@app.post("/api/agencia/{agencia_id}/clientes")
def create_agency_client(
    agencia_id: str, 
    req: CreateAgencyClientRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Creates a new subtenant client checking pool seat availability."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id:
        raise HTTPException(status_code=403, detail="Acceso denegado: No autorizado para crear clientes en esta agencia.")
    res = auth_service.create_agency_client(
        agency_tenant_id=agencia_id,
        company_name=req.razon_social,
        billing_model=req.modelo_cobro,
        meeting_fee=req.tarifa_por_reunion,
        seat_price_charged=req.precio_cliente_por_puesto,
        monthly_fixed_fee=req.fee_fijo_mensual,
        assigned_seats=req.puestos_asignados
    )
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

create_cliente_agencia = create_agency_client

class CreateTenantMemberRequest(BaseModel):
    email: str
    password: str
    nombre: str
    rol: str = "COMPANY_MEMBER"

CrearMiembroTenantRequest = CreateTenantMemberRequest

class ToggleSeatRequest(BaseModel):
    puesto_activo: int

TogglePuestoRequest = ToggleSeatRequest

class MarkMeetingRequest(BaseModel):
    fecha_reunion: Optional[str] = None
    valor_reunion: Optional[float] = None

MarcarReunionRequest = MarkMeetingRequest

@app.get("/api/tenants/{tenant_id}/miembros")
def get_tenant_members(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lists tenant members and their active seat allocation status."""
    caller = _get_current_user(authorization, x_session_token)
    if caller:
        role = caller.get("rol")
        caller_tenant = caller.get("tenant_id")
        if role != "SUPER_ADMIN" and caller_tenant != tenant_id:
            subtenants = auth_service.list_agency_subtenants(caller_tenant)
            sub_ids = [st["id"] for st in subtenants]
            if tenant_id not in sub_ids:
                raise HTTPException(status_code=403, detail="Acceso denegado: No tienes permiso para ver miembros de este tenant.")
    members = auth_service.list_tenant_users(tenant_id)
    return {"miembros": members, "total": len(members)}

get_miembros_tenant = get_tenant_members

@app.post("/api/tenants/{tenant_id}/usuarios")
def create_tenant_member(tenant_id: str, req: CreateTenantMemberRequest):
    """Creates a user in the tenant ensuring seat capacity."""
    res = auth_service.create_user_for_tenant(
        tenant_id=tenant_id,
        email=req.email,
        password=req.password,
        name=req.nombre,
        role=req.rol
    )
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

create_miembro_tenant = create_tenant_member

@app.patch("/api/usuarios/{user_id}/puesto")
def toggle_seat(user_id: str, req: ToggleSeatRequest):
    """Allocates or releases a user seat. Kicks memory session if deactivated."""
    res = auth_service.toggle_user_seat(user_id, req.puesto_activo)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

toggle_puesto = toggle_seat

@app.post("/api/leads/{lead_id}/reunion")
def mark_meeting(lead_id: str, req: Optional[MarkMeetingRequest] = None):
    """Marks lead as REUNION_AGENDADA and records conversion value."""
    meeting_date = req.fecha_reunion if req else None
    meeting_val = req.valor_reunion if req else None
    res = auth_service.mark_lead_meeting_booked(
        lead_id=lead_id,
        meeting_date=meeting_date,
        meeting_value=meeting_val
    )
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

marcar_reunion = mark_meeting

@app.get("/api/agencia/{agencia_id}/finanzas")
def get_agency_financials(
    agencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Calculates platform costs, client revenue, and net margin for an agency."""
    caller = _get_current_user(authorization, x_session_token)
    if caller and caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id:
        raise HTTPException(status_code=403, detail="Acceso denegado: Finanzas privadas de la agencia.")
    res = auth_service.get_agency_financial_summary(agencia_id)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

get_finanzas_agencia = get_agency_financials

# ==========================================
# DASHBOARD METRICS (KPIs)
# ==========================================
@app.get("/api/metricas")
def get_metrics(
    tenant_id: Optional[str] = Query(None, description="Filtrar métricas por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)

    with get_db() as conn:
        cursor = conn.cursor()
        
        where_tenant = ""
        and_tenant = ""
        params_tenant = []
        if tenants:
            placeholders = ", ".join(["?"] * len(tenants))
            where_tenant = f"WHERE tenant_id IN ({placeholders})"
            and_tenant = f"AND tenant_id IN ({placeholders})"
            params_tenant.extend(tenants)
        else:
            where_tenant = "WHERE 1=0"
            and_tenant = "AND 1=0"
        
        cursor.execute(f"SELECT COUNT(*) as total FROM leads {where_tenant}", params_tenant)
        total_leads = cursor.fetchone()["total"]
        
        cursor.execute(f"SELECT COUNT(*) as pendientes FROM leads WHERE estado = 'EXTRAIDO' {and_tenant}", params_tenant)
        en_cola = cursor.fetchone()["pendientes"]
        
        cursor.execute(f"SELECT COUNT(*) as visitados FROM leads WHERE estado = 'PERFIL_VISITADO' {and_tenant}", params_tenant)
        visitados = cursor.fetchone()["visitados"]
        
        cursor.execute(f"SELECT COUNT(*) as invitados FROM leads WHERE estado = 'INVITACION_ENVIADA' {and_tenant}", params_tenant)
        invitados = cursor.fetchone()["invitados"]

        cursor.execute(f"SELECT COUNT(*) as conectados FROM leads WHERE estado = 'CONECTADO' {and_tenant}", params_tenant)
        conectados = cursor.fetchone()["conectados"]

        today = date.today().isoformat()
        cursor.execute(f"""
            SELECT COUNT(*) as hoy 
            FROM leads 
            WHERE fecha_invitacion LIKE ? {and_tenant}
        """, [f"{today}%"] + params_tenant)
        enviadas_hoy = cursor.fetchone()["hoy"]

        cursor.execute("SELECT COUNT(*) as total_msg FROM mensajes_linkedin WHERE estado = 'ENVIADO'")
        mensajes_enviados = cursor.fetchone()["total_msg"]

        cursor.execute("SELECT COUNT(*) as total_emails FROM correos_electronicos WHERE estado = 'ENVIADO'")
        emails_enviados = cursor.fetchone()["total_emails"]

        tasa_aceptacion = 0
        if invitados > 0:
            tasa_aceptacion = round((conectados / invitados) * 100, 1)

        return {
            "total_leads": total_leads,
            "en_cola": en_cola,
            "visitados": visitados,
            "invitaciones_enviadas": invitados,
            "conectados": conectados,
            "invitaciones_hoy": enviadas_hoy,
            "limite_diario": 5,
            "cupo_restante_hoy": max(0, 5 - enviadas_hoy),
            "tasa_aceptacion_pct": tasa_aceptacion,
            "mensajes_enviados": mensajes_enviados,
            "emails_enviados": emails_enviados
        }

get_metricas = get_metrics

# ==========================================
# PROSPECTS (LEADS) MANAGEMENT
# ==========================================
@app.get("/api/prospectos")
def get_prospects(
    estado: Optional[str] = Query(None, description="Filtrar por estado: EXTRAIDO, PERFIL_VISITADO, INVITACION_ENVIADA, CONECTADO"),
    busqueda: Optional[str] = Query(None, description="Buscar por nombre, cargo o institución"),
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    limit: int = 50,
    offset: int = 0,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)

    with get_db() as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM leads WHERE 1=1"
        params = []

        if tenants:
            placeholders = ", ".join(["?"] * len(tenants))
            query += f" AND tenant_id IN ({placeholders})"
            params.extend(tenants)
        else:
            query += " AND 1=0"
        
        if estado:
            query += " AND estado = ?"
            params.append(estado)
            
        if busqueda:
            query += " AND (nombre LIKE ? OR cargo_actual LIKE ? OR cargo_titular LIKE ? OR institucion_actual LIKE ?)"
            term = f"%{busqueda}%"
            params.extend([term, term, term, term])
            
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        leads = cursor.fetchall()

        for lead in leads:
            try:
                lead["tags"] = json.loads(lead.get("tags") or "[]")
            except Exception:
                lead["tags"] = []

        return {"total": len(leads), "leads": leads}

get_prospectos = get_prospects

@app.get("/api/prospectos/{lead_id}")
def get_lead_detail(lead_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
            
        lead["tags"] = json.loads(lead.get("tags") or "[]")

        cursor.execute("SELECT * FROM historial_actividades WHERE lead_id = ? ORDER BY timestamp DESC", (lead_id,))
        lead["historial"] = cursor.fetchall()

        cursor.execute("SELECT * FROM mensajes_linkedin WHERE lead_id = ? ORDER BY created_at ASC", (lead_id,))
        lead["mensajes_linkedin"] = cursor.fetchall()

        cursor.execute("SELECT * FROM correos_electronicos WHERE lead_id = ? ORDER BY created_at ASC", (lead_id,))
        lead["correos"] = cursor.fetchall()

        cursor.execute("SELECT * FROM interacciones_sociales WHERE lead_id = ? ORDER BY fecha DESC", (lead_id,))
        lead["interacciones"] = cursor.fetchall()

        return lead

get_lead_detalle = get_lead_detail

@app.post("/api/prospectos/{lead_id}/seguir")
def toggle_follow(lead_id: str, seguir: bool = True):
    with get_db() as conn:
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            UPDATE leads 
            SET siguiendo = ?, siguiendo_desde = ?, updated_at = ?
            WHERE id = ?
        """, (1 if seguir else 0, now_iso if seguir else None, now_iso, lead_id))
        
        event = "COMENZO_A_SEGUIR" if seguir else "DEJO_DE_SEGUIR"
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, ?, ?, ?)
        """, (lead_id, event, f"Cambio de estado: siguiendo={seguir}", now_iso))
        
        return {"status": "ok", "lead_id": lead_id, "siguiendo": seguir}

toggle_seguir = toggle_follow

@app.post("/api/prospectos/{lead_id}/retirar-invitacion")
def withdraw_invitation(lead_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            UPDATE leads 
            SET invitacion_retirada = 1, fecha_retiro_invitacion = ?, estado = 'INVITACION_RETIRADA', updated_at = ?
            WHERE id = ?
        """, (now_iso, now_iso, lead_id))
        
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'RETIRO_INVITACION', 'Invitación retirada desde la aplicación', ?)
        """, (lead_id, now_iso))
        
        return {"status": "ok", "lead_id": lead_id, "estado": "INVITACION_RETIRADA"}

retirar_invitacion = withdraw_invitation

@app.post("/api/prospectos/{lead_id}/sincronizar-linkedin")
def sync_lead_with_linkedin(lead_id: str):
    """
    Sincroniza y enriquece en vivo los datos del prospecto (cargo actual, titular,
    empresa y ubicación) inspeccionando directamente su perfil real en LinkedIn.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        
        url = lead.get("perfil_url")
        if not url:
            raise HTTPException(status_code=400, detail="El lead no tiene URL de LinkedIn asignada")

        import extractor_engine
        enriched = extractor_engine.enrich_lead_from_live_profile(url)
        if not enriched.get("ok"):
            raise HTTPException(status_code=500, detail=enriched.get("error", "Error sincronizando con LinkedIn"))

        now_iso = datetime.now().isoformat()
        nuevo_nombre = enriched.get("nombre") or lead.get("nombre")
        nuevo_titular = enriched.get("cargo_titular") or lead.get("cargo_titular")
        nuevo_cargo_act = enriched.get("cargo_actual") or lead.get("cargo_actual")
        nueva_inst = enriched.get("institucion_actual") or lead.get("institucion_actual")
        nueva_ubic = enriched.get("ubicacion") or lead.get("ubicacion")

        cursor.execute("""
            UPDATE leads
            SET nombre = ?, cargo_titular = ?, cargo_actual = ?, institucion_actual = ?, ubicacion = ?, updated_at = ?
            WHERE id = ?
        """, (nuevo_nombre, nuevo_titular, nuevo_cargo_act, nueva_inst, nueva_ubic, now_iso, lead_id))

        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'LEAD_SINCRONIZADO_LINKEDIN', ?, ?)
        """, (lead_id, f"Perfil sincronizado en vivo desde LinkedIn: {nuevo_cargo_act} en {nueva_inst}", now_iso))

        cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        updated_lead = cursor.fetchone()
        try:
            updated_lead["tags"] = json.loads(updated_lead.get("tags") or "[]")
        except Exception:
            updated_lead["tags"] = []

        return {
            "status": "ok",
            "mensaje": f"Perfil sincronizado exitosamente: {nuevo_cargo_act} en {nueva_inst}",
            "lead": updated_lead
        }

sincronizar_lead_linkedin = sync_lead_with_linkedin

@app.put("/api/prospectos/{lead_id}/contacto")
def update_contact(lead_id: str, email: Optional[str] = None, telefono: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            UPDATE leads
            SET email = ?, telefono = ?, updated_at = ?
            WHERE id = ?
        """, (email, telefono, now_iso, lead_id))
        
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'CONTACTO_ACTUALIZADO', ?, ?)
        """, (lead_id, f"Datos de contacto actualizados: email={email}, tel={telefono}", now_iso))
        
        return {"status": "ok", "lead_id": lead_id, "email": email, "telefono": telefono}

update_contacto = update_contact

@app.post("/api/prospectos/importar-lote")
def import_prospects_batch(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Saves only user-selected prospects to database."""
    leads = datos.get("leads", [])
    list_id = datos.get("lista_id")
    caller = _get_current_user(authorization, x_session_token)
    target_tenant = "ten_superadmin"
    if caller:
        target_tenant = caller.get("tenant_id") or "ten_superadmin"
        if caller.get("rol") in ("SUPER_ADMIN", "AGENCY_ADMIN") and datos.get("tenant_id"):
            target_tenant = datos.get("tenant_id")

    if not leads:
        raise HTTPException(status_code=400, detail="No se proporcionaron prospectos para importar")
    return extractor_engine.import_selected_leads(leads, list_id=list_id, tenant_id=target_tenant)

importar_prospectos_lote = import_prospects_batch

@app.delete("/api/prospectos/{lead_id}")
def delete_prospect(lead_id: str):
    """Permanently deletes a prospect and all associated records."""
    extractor_engine.delete_lead(lead_id)
    return {"status": "ok", "eliminado": True, "lead_id": lead_id}

eliminar_prospecto = delete_prospect

@app.post("/api/prospectos/eliminar-lote")
def delete_prospects_batch(datos: Dict[str, Any]):
    """Permanently deletes multiple selected prospects."""
    lead_ids = datos.get("lead_ids", [])
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No se enviaron IDs de prospectos")
    total = extractor_engine.delete_leads_batch(lead_ids)
    return {"status": "ok", "eliminados": total, "lead_ids": lead_ids}

eliminar_prospectos_lote = delete_prospects_batch

# ==========================================
# WORK BROWSER INTEGRATION (ELECTRON / BROWSEROS)
# ==========================================
@app.get("/api/browser/estado")
def get_browser_status():
    is_electron = browser_service.is_electron_running()
    electron_state = browser_service.get_electron_status() if is_electron else {}
    sesion_linkedin = bool(electron_state.get("sesion_linkedin_activa", False))
    active = is_electron or browser_service.is_browseros_running()
    engine_name = "Chromium Embebido Aislado (Electron)" if is_electron else ("BrowserOS Neo" if active else "Inactivo")
    return {
        "activo": active,
        "is_electron": is_electron,
        "motor": engine_name,
        "sesion_linkedin_activa": sesion_linkedin,
        "visible": bool(electron_state.get("visible", False)),
        "mensaje": f"{engine_name} Conectado" if active else "Navegador de trabajo inactivo"
    }

get_browser_estado = get_browser_status

@app.post("/api/browser/iniciar")
def launch_browser():
    return browser_service.start_work_sessions()

iniciar_browser = launch_browser

@app.post("/api/browser/mostrar")
def show_browser(url: Optional[str] = Query(None, description="URL a la que navegar al mostrar")):
    return browser_service.show_work_browser(url=url)

mostrar_browser = show_browser

@app.post("/api/browser/ocultar")
def hide_browser():
    return browser_service.hide_work_browser()

ocultar_browser = hide_browser

@app.post("/api/browser/abrir")
def open_browser_link(url: str = Query(..., description="URL que se abrirá en el navegador de trabajo")):
    return browser_service.open_url(url)

abrir_enlace_browser = open_browser_link

@app.post("/api/prospectos/{lead_id}/abrir-en-browseros")
def open_lead_in_browseros(lead_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, perfil_url FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        
        profile_url = lead["perfil_url"]
        res = browser_service.open_url(profile_url)
        
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
            VALUES (?, 'PERFIL_ABIERTO_BROWSEROS', ?, ?)
        """, (lead_id, f"Perfil abierto en BrowserOS: {profile_url}", now_iso))
        
        return {
            "status": "ok",
            "lead_id": lead_id,
            "nombre": lead["nombre"],
            "perfil_url": profile_url,
            "browser_info": res
        }

abrir_lead_en_browseros = open_lead_in_browseros

# ==========================================
# CENTRALIZED SAFETY & ANTI-BAN MANAGEMENT
# ==========================================
@app.get("/api/seguridad/estado")
def get_safety_status():
    with get_db() as conn:
        config = safety_engine.get_all_safety_config(conn)
        diag_linkedin = safety_engine.check_linkedin_safety(conn)
        diag_email = safety_engine.check_email_workspace_safety(conn)
        in_hours, hours_detail = safety_engine.check_business_hours(config)
        
        return {
            "seguro_para_operar": diag_linkedin["autorizado"],
            "linkedin": diag_linkedin,
            "google_workspace": diag_email,
            "horario_laboral": {
                "en_horario": in_hours,
                "detalle": hours_detail,
                "restriccion_activa": config.get("horario_laboral_activo") == "1"
            },
            "kill_switch": {
                "activado": config.get("kill_switch_activado") == "1",
                "motivo": config.get("kill_switch_motivo", "")
            },
            "configuracion": config,
            "pausa_sugerida_linkedin_seg": safety_engine.calculate_gaussian_delay(config=config),
            "pausa_sugerida_email_seg": safety_engine.calculate_email_delay(config=config)
        }

get_seguridad_estado = get_safety_status

@app.post("/api/seguridad/kill-switch/activar")
def activate_kill_switch_manual(motivo: str = Query("Freno manual accionado por el usuario", description="Motivo de la parada de emergencia")):
    with get_db() as conn:
        return safety_engine.activate_kill_switch(motivo, conn)

activar_kill_switch_manual = activate_kill_switch_manual

@app.post("/api/seguridad/kill-switch/desactivar")
def deactivate_kill_switch_manual():
    with get_db() as conn:
        return safety_engine.deactivate_kill_switch(conn)

desactivar_kill_switch_manual = deactivate_kill_switch_manual

@app.post("/api/seguridad/configuracion")
def update_safety_config(clave: str, valor: str):
    with get_db() as conn:
        safety_engine.set_safety_config_val(clave, valor, conn)
        return {"status": "ok", "clave": clave, "valor": valor}

actualizar_configuracion_seguridad = update_safety_config

@app.post("/api/seguridad/spintax/probar")
def test_spintax(plantilla: str = Query(..., description="Texto con patrones Spintax como {Hola|Estimado}")):
    variation = safety_engine.process_spintax(plantilla)
    return {"plantilla_original": plantilla, "variacion_generada": variation}

probar_spintax = test_spintax

@app.post("/api/seguridad/validar-email")
def validate_email_endpoint(email: str = Query(..., description="Correo electrónico del colegio a validar")):
    return safety_engine.validate_email_syntax_and_mx(email)

validar_email_endpoint = validate_email_endpoint

# ==========================================
# SEARCH & EXTRACTION ENGINE (LINKEDIN)
# ==========================================
@app.post("/api/extraccion/buscar")
def extract_leads_endpoint(
    termino: str = Query("CEO Founder Chile", description="Cargo o palabras clave para buscar en LinkedIn"),
    pagina: int = Query(1, ge=1, le=20, description="Página de resultados a extraer"),
    auto_guardar: bool = Query(True, description="Guardar automáticamente en leads.db"),
    lista_id: Optional[str] = Query(None, description="ID de la lista de destino para vincular y auto-ingresar a secuencias"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant destino"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    caller = _get_current_user(authorization, x_session_token)
    target_tenant = "ten_superadmin"
    if caller:
        target_tenant = caller.get("tenant_id") or "ten_superadmin"
        if caller.get("rol") in ("SUPER_ADMIN", "AGENCY_ADMIN") and tenant_id:
            target_tenant = tenant_id

    return extractor_engine.search_and_extract_leads(
        termino, 
        page=pagina, 
        auto_save=auto_guardar, 
        list_id=lista_id, 
        tenant_id=target_tenant
    )

extraer_leads_endpoint = extract_leads_endpoint

# ==========================================
# MULTICHANNEL SEQUENCE ENGINE (DECISION TREES)
# ==========================================
@app.get("/api/secuencias")
def list_sequences_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Returns all authorized sequences with aggregated metrics."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    return {"secuencias": sequence_engine.get_sequences(tenant_ids=tenants)}

listar_secuencias_endpoint = list_sequences_endpoint

@app.get("/api/secuencias/{secuencia_id}")
def get_sequence_endpoint(secuencia_id: str):
    """Returns sequence detail and hierarchical step tree."""
    sec = sequence_engine.get_full_sequence(secuencia_id)
    if not sec:
        raise HTTPException(status_code=404, detail="Secuencia no encontrada")
    return sec

obtener_secuencia_endpoint = get_sequence_endpoint

@app.post("/api/secuencias")
def create_sequence_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Creates a new sequence associated with tenant."""
    caller = _get_current_user(authorization, x_session_token)
    target_tenant = "ten_superadmin"
    if caller:
        target_tenant = caller.get("tenant_id") or "ten_superadmin"
        if caller.get("rol") in ("SUPER_ADMIN", "AGENCY_ADMIN") and datos.get("tenant_id"):
            target_tenant = datos.get("tenant_id")

    nombre = datos.get("nombre", "Nueva Secuencia Multicanal")
    descripcion = datos.get("descripcion", "")
    activa = datos.get("activa", True)
    plantilla = datos.get("plantilla", "multicanal")
    return sequence_engine.create_sequence(nombre, descripcion, activa, plantilla, tenant_id=target_tenant)

crear_secuencia_endpoint = create_sequence_endpoint

@app.put("/api/secuencias/{secuencia_id}")
def update_sequence_endpoint(secuencia_id: str, datos: Dict[str, Any]):
    """Updates sequence metadata."""
    res = sequence_engine.update_sequence(
        secuencia_id,
        nombre=datos.get("nombre"),
        descripcion=datos.get("descripcion"),
        activa=datos.get("activa")
    )
    if not res:
        raise HTTPException(status_code=400, detail="No se pudo actualizar la secuencia")
    return {"status": "ok", "secuencia_id": secuencia_id}

actualizar_secuencia_endpoint = update_sequence_endpoint

@app.delete("/api/secuencias/{secuencia_id}")
def delete_sequence_endpoint(secuencia_id: str):
    """Deletes a sequence and its steps."""
    sequence_engine.delete_sequence(secuencia_id)
    return {"status": "ok", "secuencia_id": secuencia_id}

eliminar_secuencia_endpoint = delete_sequence_endpoint

@app.post("/api/secuencias/{secuencia_id}/pasos")
def save_steps_endpoint(secuencia_id: str, datos: Dict[str, Any]):
    """Saves or replaces sequence step tree."""
    pasos = datos.get("pasos", [])
    sequence_engine.save_sequence_steps(secuencia_id, pasos)
    return {"status": "ok", "secuencia_id": secuencia_id, "total_pasos": len(pasos)}

guardar_pasos_endpoint = save_steps_endpoint

@app.post("/api/secuencias/{secuencia_id}/pasos/agregar")
def add_step_endpoint(secuencia_id: str, datos: Dict[str, Any]):
    """Inserts a step into sequence tree."""
    posicion = datos.get("posicion", "final")
    ref_id = datos.get("paso_referencia_id")
    res = sequence_engine.add_sequence_step(secuencia_id, datos, posicion, ref_id)
    return {"status": "ok", "secuencia_id": secuencia_id, "paso": res}

agregar_paso_endpoint = add_step_endpoint

@app.delete("/api/secuencias/{secuencia_id}/pasos/{paso_id}")
def delete_step_endpoint(secuencia_id: str, paso_id: str):
    """Deletes a sequence step."""
    res = sequence_engine.delete_sequence_step(secuencia_id, paso_id)
    if not res:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    return {"status": "ok", "secuencia_id": secuencia_id, "paso_id": paso_id}

eliminar_paso_endpoint = delete_step_endpoint

@app.post("/api/secuencias/{secuencia_id}/asignar-leads")
def assign_leads_endpoint(secuencia_id: str, datos: Dict[str, Any]):
    """Assigns list of leads to sequence root step."""
    lead_ids = datos.get("lead_ids", [])
    if not lead_ids:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE estado = 'EXTRAIDO'")
            lead_ids = [r["id"] for r in cur.fetchall()]

    return sequence_engine.assign_leads_to_sequence(secuencia_id, lead_ids)

asignar_leads_endpoint = assign_leads_endpoint

@app.get("/api/secuencias/{secuencia_id}/leads")
def list_sequence_leads_endpoint(secuencia_id: str, estado: Optional[str] = None):
    """Returns prospects enrolled in sequence."""
    leads = sequence_engine.get_leads_in_sequence(secuencia_id, estado)
    return {"leads": leads, "total": len(leads)}

listar_leads_secuencia_endpoint = list_sequence_leads_endpoint

@app.post("/api/secuencias/ejecutar-siguiente")
def execute_next_step_endpoint(secuencia_id: Optional[str] = Query(None, description="ID opcional de la secuencia a procesar")):
    """Executes next pending sequence step enforcing safety rules."""
    return sequence_engine.execute_next_step(secuencia_id)

ejecutar_siguiente_paso_endpoint = execute_next_step_endpoint

@app.post("/api/secuencias/{secuencia_id}/estado")
def change_sequence_status_endpoint(secuencia_id: str, datos: Dict[str, Any]):
    """Pauses or publishes a sequence."""
    nuevo_estado = datos.get("estado", "PUBLICADA")
    sequence_engine.change_sequence_publish_status(secuencia_id, nuevo_estado)
    return {"status": "ok", "secuencia_id": secuencia_id, "estado": nuevo_estado}

cambiar_estado_secuencia_endpoint = change_sequence_status_endpoint

# ==========================================
# LEAD LISTS MANAGEMENT (AUDIENCES)
# ==========================================
@app.get("/api/listas")
def list_lists_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Returns all authorized lead lists."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    return {"listas": lists_engine.get_lead_lists(tenant_ids=tenants)}

listar_listas_endpoint = list_lists_endpoint

@app.get("/api/listas/{lista_id}")
def get_list_detail_endpoint(lista_id: str):
    """Returns lead list detail and prospects."""
    res = lists_engine.get_lead_list_detail(lista_id)
    if not res:
        raise HTTPException(status_code=404, detail="Lista no encontrada")
    return res

obtener_lista_detalle_endpoint = get_list_detail_endpoint

@app.post("/api/listas")
def create_list_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Creates a new lead list linked to its tenant."""
    caller = _get_current_user(authorization, x_session_token)
    target_tenant = "ten_superadmin"
    if caller:
        target_tenant = caller.get("tenant_id") or "ten_superadmin"
        if caller.get("rol") in ("SUPER_ADMIN", "AGENCY_ADMIN") and datos.get("tenant_id"):
            target_tenant = datos.get("tenant_id")

    name = datos.get("nombre", "Nueva Lista de Leads")
    desc = datos.get("descripcion", "")
    term = datos.get("termino_busqueda", "")
    status = datos.get("estado", "ACTIVA")
    auto_connect = bool(datos.get("conectar_secuencia_activa", False))
    return lists_engine.create_lead_list(
        name, 
        desc, 
        term, 
        status=status, 
        auto_connect_sequence=auto_connect,
        tenant_id=target_tenant
    )

crear_lista_endpoint = create_list_endpoint

@app.put("/api/listas/{lista_id}")
def update_list_endpoint(lista_id: str, datos: Dict[str, Any]):
    """Updates lead list metadata."""
    res = lists_engine.update_lead_list(
        lista_id,
        name=datos.get("nombre"),
        description=datos.get("descripcion"),
        status=datos.get("estado"),
        search_term=datos.get("termino_busqueda")
    )
    if not res:
        raise HTTPException(status_code=400, detail="No se pudo actualizar la lista")
    return {"status": "ok", "lista_id": lista_id}

actualizar_lista_endpoint = update_list_endpoint

@app.delete("/api/listas/{lista_id}")
def delete_list_endpoint(lista_id: str):
    """Deletes a lead list."""
    lists_engine.delete_lead_list(lista_id)
    return {"status": "ok", "lista_id": lista_id}

eliminar_lista_endpoint = delete_list_endpoint

@app.post("/api/listas/{lista_id}/leads")
def add_leads_to_list_endpoint(lista_id: str, datos: Dict[str, Any]):
    """Adds leads to a list and enrolls in connected sequences."""
    lead_ids = datos.get("lead_ids", [])
    return lists_engine.add_leads_to_list(lista_id, lead_ids)

agregar_leads_a_lista_endpoint = add_leads_to_list_endpoint

@app.post("/api/listas/{lista_id}/conectar-secuencia")
def connect_list_to_sequence_endpoint(lista_id: str, datos: Dict[str, Any]):
    """Connects a list to a sequence."""
    secuencia_id = datos.get("secuencia_id")
    if not secuencia_id:
        raise HTTPException(status_code=400, detail="secuencia_id es requerido")
    return lists_engine.connect_list_to_sequence(secuencia_id, lista_id)

conectar_lista_secuencia_endpoint = connect_list_to_sequence_endpoint

@app.post("/api/listas/{lista_id}/desconectar-secuencia")
def disconnect_list_from_sequence_endpoint(lista_id: str, datos: Dict[str, Any]):
    """Disconnects a list from a sequence."""
    secuencia_id = datos.get("secuencia_id")
    if not secuencia_id:
        raise HTTPException(status_code=400, detail="secuencia_id es requerido")
    lists_engine.disconnect_list_from_sequence(secuencia_id, lista_id)
    return {"status": "ok", "secuencia_id": secuencia_id, "lista_id": lista_id}

desconectar_lista_secuencia_endpoint = disconnect_list_from_sequence_endpoint

# ==========================================
# ACTIVITY LOGS & AUDIT
# ==========================================
@app.get("/api/logs")
def get_logs_endpoint(
    limit: int = Query(150, description="Cantidad máxima de eventos a retornar"),
    module: Optional[str] = Query(None, description="Filtro por módulo: EXTRACTOR, SEQUENCES, BROWSER, SAFETY, etc."),
    level: Optional[str] = Query(None, description="Filtro por nivel: INFO, SUCCESS, WARNING, ERROR"),
    search: Optional[str] = Query(None, description="Término de búsqueda de texto"),
    since_id: Optional[int] = Query(None, description="Filtrar eventos con ID superior a este")
):
    """Returns chronological activity logs."""
    import logger_service
    logs = logger_service.get_logs(limit=limit, module=module, level=level, search=search, since_id=since_id)
    return {"logs": logs, "total": len(logs)}

@app.get("/api/logs/stats")
def get_log_stats_endpoint():
    """Returns aggregated system stats."""
    import logger_service
    return logger_service.get_log_stats()

@app.delete("/api/logs")
def clear_logs_endpoint():
    """Clears system logs."""
    import logger_service
    logger_service.clear_logs()
    return {"status": "ok", "message": "Logs eliminados correctamente"}

# ==========================================
# LOCAL RUNNER CONTRACT (HYBRID ARCHITECTURE)
# ==========================================
@app.get("/api/worker/estado")
def get_worker_dispatcher_status():
    """Returns dispatcher status and autopilot mode."""
    return {
        "piloto_automatico": task_dispatcher.get_autopilot_status(),
        "status": "online"
    }

get_worker_dispatcher_estado = get_worker_dispatcher_status

@app.post("/api/worker/piloto-automatico/toggle")
def toggle_autopilot(activo: Optional[bool] = None):
    """Activates or pauses campaign autopilot."""
    new_state = not task_dispatcher.get_autopilot_status() if activo is None else bool(activo)
    task_dispatcher.set_autopilot_status(new_state)
    return {
        "status": "ok",
        "piloto_automatico": new_state,
        "mensaje": "Piloto automático activado" if new_state else "Piloto automático en pausa"
    }

toggle_piloto_automatico = toggle_autopilot

@app.post("/api/worker/heartbeat")
def worker_heartbeat(datos: Dict[str, Any]):
    """Receives periodic pulse from Electron desktop runner."""
    return {
        "ok": True,
        "servidor_tiempo": datetime.now().isoformat(),
        "piloto_automatico": task_dispatcher.get_autopilot_status()
    }

@app.get("/api/worker/proxima-tarea")
def get_worker_next_task():
    """Delivers next authorized task to desktop runner."""
    return task_dispatcher.get_next_dispatched_task()

get_worker_proxima_tarea = get_worker_next_task

@app.post("/api/worker/reportar-resultado")
def report_task_result(datos: Dict[str, Any]):
    """Processes task completion report from local runner."""
    return task_dispatcher.process_executed_task_report(datos)

reportar_resultado_tarea = report_task_result
