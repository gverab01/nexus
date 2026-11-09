import os
import json
from fastapi import FastAPI, HTTPException, Query, Header, Body, Response, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from database import get_db, init_db
import browser_service
import safety_engine
import extractor_engine
import sequence_engine
import lists_engine
import auth_service
import task_dispatcher
import task_queue_service
import whatsapp_safety_engine
import zoho_browser_service
import zoho_bridge_service
import dashboard_service
import command_signing_service
import privacy_compliance_service
import crypto_field_service

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
async def add_smart_cache_headers(request, call_next):
    """Aplica estrategia de caché y garantiza limpieza del contexto transaccional del tenant."""
    import database
    database.clear_current_tenant_context()
    try:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/dist/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path == "/" or path.endswith("index.html") or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
    finally:
        database.clear_current_tenant_context()

# Static files mounting
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    dist_assets_dir = os.path.join(STATIC_DIR, "dist", "assets")
    if os.path.exists(dist_assets_dir):
        app.mount("/assets", StaticFiles(directory=dist_assets_dir), name="dist_assets")

def start_periodic_delay_sweeper():
    """Inicia un hilo en segundo plano que promueve automáticamente prospectos en espera expirada cada 25 segundos."""
    import threading
    import time
    def sweeper_loop():
        time.sleep(3)
        while True:
            try:
                sequence_engine.promote_expired_delays()
            except Exception:
                pass
            time.sleep(25)

    thread = threading.Thread(target=sweeper_loop, daemon=True, name="NexusReach_DelaySweeper")
    thread.start()

@app.on_event("startup")
def startup_event():
    """Inicializa la base de datos y arranca los servicios en segundo plano."""
    init_db()
    try:
        import connection_sync_service
        connection_sync_service.start_periodic_connection_sync()
    except Exception as e:
        print(f"[Startup] Error iniciando sincronizador periódico de conexiones: {e}")
    try:
        start_periodic_delay_sweeper()
    except Exception as e:
        print(f"[Startup] Error iniciando promotor periódico de esperas: {e}")
    try:
        task_queue_service.start_periodic_queue_runner()
    except Exception as e:
        print(f"[Startup] Error iniciando despachador de cola central: {e}")

@app.get("/")
def read_root():
    """Sirve la interfaz compilada en React desde static/dist/index.html."""
    dist_index = os.path.join(STATIC_DIR, "dist", "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    return {
        "status": "online",
        "app": "NexusReach Pro",
        "mensaje": "Frontend no compilado. Ejecuta 'npm run build' dentro de frontend/."
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

@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Autentica al usuario y verifica el estado de su suscripción activa."""
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
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Verifica si el token en memoria es válido y si la suscripción continúa activa."""
    final_token = token or x_session_token
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

@app.post("/api/auth/logout")
def logout(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Cierra la sesión y destruye el token en memoria."""
    final_token = token or x_session_token
    if not final_token and authorization:
        if authorization.lower().startswith("bearer "):
            final_token = authorization[7:].strip()
        else:
            final_token = authorization.strip()

    if final_token:
        auth_service.logout_user(final_token)
    try:
        import browser_service
        browser_service.clear_electron_worker_session()
    except Exception:
        pass
    return {"status": "ok", "mensaje": "Sesión cerrada exitosamente"}

@app.get("/api/auth/usuarios")
def get_users(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista los usuarios y el estado de sus suscripciones (Solo SUPER_ADMIN)."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    return auth_service.list_users()

@app.patch("/api/auth/usuarios/{user_id}/suscripcion")
def update_subscription(
    user_id: str,
    req: UpdateSubscriptionRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Permite renovar, extender o pausar la suscripción de un usuario (Solo SUPER_ADMIN)."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
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

class DeltaSeatsRequest(BaseModel):
    delta: int

class CreateAgencyClientRequest(BaseModel):
    razon_social: str
    modelo_cobro: str = "POR_PUESTO"
    tarifa_por_reunion: float = 0.0
    precio_cliente_por_puesto: float = 0.0
    fee_fijo_mensual: float = 0.0
    puestos_asignados: int = 1

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

_ALLOWED_ROLES = {
    "SUPER_ADMIN",
    "AGENCY_ADMIN",
    "COMPANY_ADMIN",
    "COMPANY_MEMBER",
    "INDIVIDUAL",
    "FREELANCER",
}

def _resolve_permitted_tenants(caller: Optional[Dict[str, Any]], tenant_query: Optional[str] = None) -> List[str]:
    """
    Resuelve el tenant_id permitido para las consultas (AISLAMIENTO ESTRICTO MONO-TENANT):
    - Requiere autenticación válida obligatoria (caller con sesión activa, id y rol válidos).
    - Solicitud sin autenticación válida -> HTTPException(401).
    - Super Admin: tenant_query explícito accede ÚNICAMENTE a ese tenant. Por defecto: su propio tenant asignado.
    - Agency Admin: tenant_query explícito accede ÚNICAMENTE a su propia agencia o a una empresa cliente (subtenant) autorizada. Por defecto: su propia agencia.
    - Operadores / Miembros: Confinados estrictamente al tenant_id de su propia empresa. Si tenant_query difiere de su tenant_id -> HTTPException(403).
    - Parámetros tenant_id manipulados, roles desconocidos o ausencia de tenant -> HTTPException(403).
    """
    if not caller or not isinstance(caller, dict):
        raise HTTPException(
            status_code=401,
            detail="Autenticación requerida. Token inválido o ausente."
        )

    caller_id = caller.get("id")
    role = caller.get("rol")
    if not caller_id or not isinstance(caller_id, str) or not caller_id.strip() or not role or not isinstance(role, str):
        raise HTTPException(
            status_code=401,
            detail="Autenticación requerida. Identidad de sesión incompleta o inválida."
        )

    role = role.strip()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Contexto de seguridad inválido: rol no autorizado."
        )

    caller_tenant = (caller.get("tenant_id") or "").strip() if isinstance(caller.get("tenant_id"), str) else ""
    clean_query = tenant_query.strip() if (tenant_query and isinstance(tenant_query, str) and tenant_query.strip()) else None

    final_tenant = None
    if role == "SUPER_ADMIN":
        if clean_query:
            final_tenant = clean_query
        elif caller_tenant:
            final_tenant = caller_tenant
        else:
            raise HTTPException(
                status_code=403,
                detail="Contexto de seguridad inválido: tenant no asignado al usuario."
            )
    elif not caller_tenant:
        raise HTTPException(
            status_code=403,
            detail="Contexto de seguridad inválido: tenant no asignado al usuario."
        )
    elif role == "AGENCY_ADMIN":
        subtenants = auth_service.list_agency_subtenants(caller_tenant)
        valid_ids = [caller_tenant] + [st["id"] for st in subtenants]
        if clean_query:
            if clean_query in valid_ids:
                final_tenant = clean_query
            else:
                raise HTTPException(
                    status_code=403,
                    detail="No tienes autorización para acceder a los datos de este workspace."
                )
        else:
            final_tenant = caller_tenant
    else:
        # COMPANY_ADMIN, COMPANY_MEMBER, INDIVIDUAL, FREELANCER confinados estrictamente a su tenant
        if clean_query and clean_query != caller_tenant:
            raise HTTPException(
                status_code=403,
                detail="No tienes autorización para acceder a los datos de este workspace."
            )
        final_tenant = caller_tenant

    import database
    database.set_current_tenant_context(
        tenant_id=final_tenant,
        is_super_admin=(role == "SUPER_ADMIN" and not clean_query),
        allow_subtenants=False
    )
    return [final_tenant]

_ADMIN_ROLES = {"SUPER_ADMIN", "AGENCY_ADMIN", "COMPANY_ADMIN"}


def _require_tenant_admin(caller: Optional[Dict[str, Any]], tenant_query: Optional[str] = None) -> List[str]:
    """Exige usuario autenticado con rol administrativo (SUPER_ADMIN, AGENCY_ADMIN, COMPANY_ADMIN) y resuelve tenants permitidos."""
    tenants = _resolve_permitted_tenants(caller, tenant_query)
    if caller.get("rol") not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: Se requieren permisos administrativos en el workspace."
        )
    return tenants


def _require_super_admin(caller: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Exige usuario autenticado con rol SUPER_ADMIN."""
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: Se requiere rol SUPER_ADMIN."
        )
    return caller


def _authorize_lead_access(caller: Optional[Dict[str, Any]], lead_id: str) -> Dict[str, Any]:
    """Verifica autenticación, existencia del lead y pertenencia a un tenant autorizado del caller."""
    tenants = _resolve_permitted_tenants(caller, None)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    lead_tenant = lead.get("tenant_id")
    if caller.get("rol") != "SUPER_ADMIN" and lead_tenant not in tenants:
        # Para AGENCY_ADMIN, validar si el lead pertenece a la agencia o a un subtenant autorizado
        allowed_for_caller = set(tenants)
        if caller.get("rol") == "AGENCY_ADMIN":
            subtenants = auth_service.list_agency_subtenants(caller.get("tenant_id"))
            allowed_for_caller.update(st["id"] for st in subtenants)
        if lead_tenant not in allowed_for_caller:
            raise HTTPException(
                status_code=403,
                detail="No tienes autorización para acceder o modificar este prospecto."
            )
    return dict(lead)


def _authorize_leads_batch_access(
    caller: Optional[Dict[str, Any]],
    lead_ids: List[str],
    expected_tenant: Optional[str] = None
) -> str:
    """
    Verifica de forma atómica que todos los lead_ids existan y pertenezcan a los tenants autorizados
    del caller (y opcionalmente a expected_tenant) antes de ejecutar cualquier mutación.
    """
    tenants = _resolve_permitted_tenants(caller, expected_tenant)
    if not lead_ids:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos un lead_id")
    unique_ids = list(dict.fromkeys(lead_ids))
    with get_db() as conn:
        cursor = conn.cursor()
        placeholders = ", ".join(["?"] * len(unique_ids))
        cursor.execute(f"SELECT id, tenant_id FROM leads WHERE id IN ({placeholders})", unique_ids)
        rows = cursor.fetchall()
    found_map = {r["id"]: r["tenant_id"] for r in rows}

    allowed_for_caller = set(tenants)
    if caller.get("rol") == "AGENCY_ADMIN" and not expected_tenant:
        subtenants = auth_service.list_agency_subtenants(caller.get("tenant_id"))
        allowed_for_caller.update(st["id"] for st in subtenants)

    for lid in unique_ids:
        if lid in found_map:
            l_tenant = found_map[lid]
            if caller.get("rol") != "SUPER_ADMIN" and l_tenant not in allowed_for_caller:
                raise HTTPException(
                    status_code=403,
                    detail="Operación por lote rechazada: incluye prospectos de un workspace no autorizado."
                )
            if expected_tenant and l_tenant != expected_tenant:
                raise HTTPException(
                    status_code=403,
                    detail="Operación por lote rechazada: los prospectos no pertenecen al mismo workspace del recurso destino."
                )
    for lid in unique_ids:
        if lid not in found_map:
            raise HTTPException(status_code=404, detail=f"Lead no encontrado: {lid}")
    return expected_tenant or tenants[0]


def _authorize_sequence_access(caller: Optional[Dict[str, Any]], secuencia_id: str) -> Dict[str, Any]:
    """Verifica autenticación, existencia de la secuencia y pertenencia a un tenant autorizado del caller."""
    tenants = _resolve_permitted_tenants(caller, None)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM secuencias WHERE id = ?", (secuencia_id,))
        sec = cursor.fetchone()
    if not sec:
        raise HTTPException(status_code=404, detail="Secuencia no encontrada")
    sec_tenant = sec.get("tenant_id")
    if caller.get("rol") != "SUPER_ADMIN" and sec_tenant not in tenants:
        allowed_for_caller = set(tenants)
        if caller.get("rol") == "AGENCY_ADMIN":
            subtenants = auth_service.list_agency_subtenants(caller.get("tenant_id"))
            allowed_for_caller.update(st["id"] for st in subtenants)
        if sec_tenant not in allowed_for_caller:
            raise HTTPException(
                status_code=403,
                detail="No tienes autorización para acceder o modificar esta secuencia."
            )
    return dict(sec)


def _authorize_list_access(caller: Optional[Dict[str, Any]], lista_id: str) -> Dict[str, Any]:
    """Verifica autenticación, existencia de la lista y pertenencia a un tenant autorizado del caller."""
    tenants = _resolve_permitted_tenants(caller, None)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listas_leads WHERE id = ?", (lista_id,))
        lst = cursor.fetchone()
    if not lst:
        raise HTTPException(status_code=404, detail="Lista no encontrada")
    lst_tenant = lst.get("tenant_id")
    if caller.get("rol") != "SUPER_ADMIN" and lst_tenant not in tenants:
        allowed_for_caller = set(tenants)
        if caller.get("rol") == "AGENCY_ADMIN":
            subtenants = auth_service.list_agency_subtenants(caller.get("tenant_id"))
            allowed_for_caller.update(st["id"] for st in subtenants)
        if lst_tenant not in allowed_for_caller:
            raise HTTPException(
                status_code=403,
                detail="No tienes autorización para acceder o modificar esta lista."
            )
    return dict(lst)

@app.get("/api/tenants")
def get_tenants(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Directorio global de tenants para Super Admin."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    return auth_service.list_global_tenants()

@app.post("/api/admin/cuentas")
def create_account(
    req: CreateAccountRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea una nueva cuenta de cliente desde Super Admin (Freelancer, Empresa, Agencia)."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
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

@app.post("/api/tenants/{tenant_id}/revocar")
def revoke_tenant(
    tenant_id: str, 
    motivo: str = Query("Revocado por Super Admin"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Revoca la licencia de un tenant en tiempo real."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    auth_service.revoke_tenant_license(tenant_id, motivo)
    return {"status": "ok", "mensaje": f"Licencia de {tenant_id} revocada"}

@app.post("/api/tenants/{tenant_id}/reactivar")
def reactivate_tenant(
    tenant_id: str, 
    dias: int = Query(30),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Reactiva la licencia de un tenant."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    auth_service.reactivate_tenant_license(tenant_id, dias)
    return {"status": "ok", "mensaje": f"Licencia de {tenant_id} reactivada por {dias} días"}

@app.post("/api/tenants/{tenant_id}/puestos")
def adjust_seats(
    tenant_id: str, 
    req: DeltaSeatsRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Agrega o resta puestos contratados de la bolsa de licencias."""
    caller = _get_current_user(authorization, x_session_token)
    _require_tenant_admin(caller, tenant_id)
    if caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Acceso denegado a la gestión de puestos de este tenant.")
    res = auth_service.update_seat_pool(tenant_id, req.delta)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

@app.get("/api/agencia/{agencia_id}/clientes")
def get_agency_clients(
    agencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista todos los clientes de la agencia con sus puestos asignados y modelos financieros."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") not in ("SUPER_ADMIN", "AGENCY_ADMIN") or (caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id):
        raise HTTPException(status_code=403, detail="Acceso denegado: Cartera restringida a la administración de la agencia propietaria.")
    return auth_service.list_agency_subtenants(agencia_id)

@app.post("/api/agencia/{agencia_id}/clientes")
def create_agency_client(
    agencia_id: str, 
    req: CreateAgencyClientRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea un nuevo subtenant para la agencia verificando la disponibilidad de puestos en la bolsa."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") not in ("SUPER_ADMIN", "AGENCY_ADMIN") or (caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id):
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

class CreateTenantMemberRequest(BaseModel):
    email: str
    password: str
    nombre: str
    rol: str = "COMPANY_MEMBER"

class ToggleSeatRequest(BaseModel):
    puesto_activo: int

class MarkMeetingRequest(BaseModel):
    fecha_reunion: Optional[str] = None
    valor_reunion: Optional[float] = None

@app.get("/api/tenants/{tenant_id}/miembros")
def get_tenant_members(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista los miembros del tenant y el estado de asignación de su puesto."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="Acceso denegado: No tienes permiso para ver miembros de este tenant.")
    members = auth_service.list_tenant_users(tenant_id)
    return {"miembros": members, "total": len(members)}

@app.post("/api/tenants/{tenant_id}/usuarios")
def create_tenant_member(
    tenant_id: str,
    req: CreateTenantMemberRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea un usuario en el tenant asegurando que exista capacidad en los puestos."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _require_tenant_admin(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="Acceso denegado: No tienes permiso para crear miembros en este tenant.")
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

@app.patch("/api/usuarios/{user_id}/puesto")
def toggle_seat(
    user_id: str,
    req: ToggleSeatRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Asigna o libera el puesto de un usuario. Expulsa la sesión en memoria si se desactiva."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requieren permisos administrativos.")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (user_id,))
        target_user = cursor.fetchone()
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    _resolve_permitted_tenants(caller, target_user["tenant_id"])
    res = auth_service.toggle_user_seat(user_id, req.puesto_activo)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

@app.post("/api/leads/{lead_id}/reunion")
def mark_meeting(
    lead_id: str,
    req: Optional[MarkMeetingRequest] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Marca el lead como REUNION_AGENDADA y registra el valor de conversión."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
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

@app.get("/api/agencia/{agencia_id}/finanzas")
def get_agency_financials(
    agencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Calcula costos de plataforma, ingresos de clientes y margen neto para una agencia."""
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") not in ("SUPER_ADMIN", "AGENCY_ADMIN") or (caller.get("rol") != "SUPER_ADMIN" and caller.get("tenant_id") != agencia_id):
        raise HTTPException(status_code=403, detail="Acceso denegado: Finanzas privadas de la agencia.")
    res = auth_service.get_agency_financial_summary(agencia_id)
    if not res["exito"]:
        raise HTTPException(status_code=400, detail=res["mensaje"])
    return res

# ==========================================
# DASHBOARD METRICS (KPIs)
# ==========================================
@app.get("/api/metricas")
def get_metrics(
    tenant_id: Optional[str] = Query(None, description="Filtrar métricas por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Calcula y retorna las métricas y KPIs agregados del embudo comercial para los tenants autorizados."""
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
        
        # Contabiliza los prospectos en proceso (EN_CURSO) en secuencias activas y publicadas
        where_sec_tenant = ""
        if tenants:
            placeholders = ", ".join(["?"] * len(tenants))
            where_sec_tenant = f"AND s.tenant_id IN ({placeholders})"
        import dashboard_service
        target_tenant = tenants[0] if (tenants and len(tenants) == 1) else None
        dash = dashboard_service.get_dashboard_metrics(tenant_id=target_tenant)
        kpis = dash.get("metricas_clave", {})
        ab_li = dash.get("antiban_salud", {}).get("linkedin", {})

        return {
            "total_leads": kpis.get("total_leads_base", 0),
            "en_cola": kpis.get("leads_en_curso", 0),
            "visitados": kpis.get("perfiles_visitados", 0),
            "invitaciones_enviadas": kpis.get("invitaciones_enviadas", 0),
            "conectados": kpis.get("invitaciones_aceptadas", 0),
            "invitaciones_hoy": kpis.get("invitaciones_hoy", 0),
            "limite_diario": kpis.get("cupo_invitaciones_hoy", 8),
            "cupo_restante_hoy": kpis.get("cupo_restante_hoy", 0),
            "tasa_aceptacion_pct": kpis.get("tasa_aceptacion_pct", 0.0),
            "mensajes_enviados": kpis.get("mensajes_enviados", 0),
            "emails_enviados": kpis.get("mensajes_recibidos", 0),
            "semana_warmup": ab_li.get("semana", 1),
            "dia_warmup": ab_li.get("dia_actual", 1)
        }

# ==========================================
# PROSPECTS (LEADS) MANAGEMENT
# ==========================================
@app.get("/api/prospectos")
def get_prospects(
    estado: Optional[str] = Query(None, description="Filtrar por estado: EXTRAIDO, PERFIL_VISITADO, INVITACION_ENVIADA, CONECTADO"),
    busqueda: Optional[str] = Query(None, description="Buscar por nombre, cargo o institución"),
    lista_id: Optional[str] = Query(None, description="Filtrar por ID de lista de leads o 'sin_lista'"),
    secuencia_id: Optional[str] = Query(None, description="Filtrar por ID de secuencia o 'sin_secuencia'"),
    fecha_desde: Optional[str] = Query(None, description="Filtrar leads creados desde esta fecha ISO"),
    fecha_hasta: Optional[str] = Query(None, description="Filtrar leads creados hasta esta fecha ISO"),
    orden: str = Query("fecha_desc", description="Orden: fecha_desc, fecha_asc, nombre_asc, actividad_desc"),
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    limit: int = 50,
    offset: int = 0,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna la lista paginada de prospectos (leads) aplicando los filtros de estado, búsqueda, listas y secuencias."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)

    with get_db() as conn:
        cursor = conn.cursor()
        
        where_clauses = ["1=1"]
        params = []

        if tenants:
            placeholders = ", ".join(["?"] * len(tenants))
            where_clauses.append(f"l.tenant_id IN ({placeholders})")
            params.extend(tenants)
        else:
            where_clauses.append("1=0")
        
        if estado:
            where_clauses.append("l.estado = ?")
            params.append(estado)
            
        if busqueda:
            where_clauses.append("(l.nombre LIKE ? OR l.cargo_actual LIKE ? OR l.cargo_titular LIKE ? OR l.institucion_actual LIKE ? OR l.ubicacion LIKE ?)")
            term = f"%{busqueda}%"
            params.extend([term, term, term, term, term])

        if lista_id:
            if lista_id == "sin_lista":
                where_clauses.append("l.id NOT IN (SELECT lead_id FROM leads_en_lista)")
            else:
                placeholders_lst = ", ".join(["?"] * len(tenants))
                where_clauses.append(
                    f"l.id IN (SELECT lel.lead_id FROM leads_en_lista lel JOIN listas_leads ll ON ll.id = lel.lista_id WHERE lel.lista_id = ? AND ll.tenant_id IN ({placeholders_lst}))"
                )
                params.append(lista_id)
                params.extend(tenants)

        if secuencia_id:
            if secuencia_id == "sin_secuencia":
                where_clauses.append("l.id NOT IN (SELECT lead_id FROM leads_en_secuencia)")
            else:
                placeholders_sec = ", ".join(["?"] * len(tenants))
                where_clauses.append(
                    f"l.id IN (SELECT les.lead_id FROM leads_en_secuencia les JOIN secuencias s ON s.id = les.secuencia_id WHERE les.secuencia_id = ? AND s.tenant_id IN ({placeholders_sec}))"
                )
                params.append(secuencia_id)
                params.extend(tenants)

        if fecha_desde:
            where_clauses.append("l.created_at >= ?")
            params.append(fecha_desde)

        if fecha_hasta:
            where_clauses.append("l.created_at <= ?")
            params.append(fecha_hasta)

        where_sql = " AND ".join(where_clauses)

        # Contar total con los filtros aplicados
        cursor.execute(f"SELECT COUNT(*) as total FROM leads l WHERE {where_sql}", params)
        total_count = cursor.fetchone()["total"]

        # Ordenamiento
        order_sql = "ORDER BY l.created_at DESC"
        if orden == "fecha_asc":
            order_sql = "ORDER BY l.created_at ASC"
        elif orden == "nombre_asc":
            order_sql = "ORDER BY l.nombre COLLATE NOCASE ASC"
        elif orden == "actividad_desc":
            order_sql = "ORDER BY COALESCE((SELECT MAX(timestamp) FROM historial_actividades WHERE lead_id = l.id), l.created_at) DESC"

        query = f"""
            SELECT l.*,
                   (SELECT json_group_array(json_object('id', ll.id, 'nombre', ll.nombre))
                    FROM leads_en_lista lel
                    JOIN listas_leads ll ON lel.lista_id = ll.id
                    WHERE lel.lead_id = l.id AND ll.tenant_id = l.tenant_id) as listas_json,
                   (SELECT json_group_array(json_object('id', s.id, 'nombre', s.nombre, 'estado', s.estado, 'estado_lead', les.estado))
                    FROM leads_en_secuencia les
                    JOIN secuencias s ON les.secuencia_id = s.id
                    WHERE les.lead_id = l.id AND s.tenant_id = l.tenant_id) as secuencias_json,
                   (SELECT json_object('tipo_evento', ha.tipo_evento, 'descripcion', ha.descripcion, 'timestamp', ha.timestamp)
                    FROM historial_actividades ha
                    WHERE ha.lead_id = l.id
                    ORDER BY ha.timestamp DESC LIMIT 1) as ultima_actividad_json
            FROM leads l
            WHERE {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
        """
        params_with_pagination = list(params) + [limit, offset]
        cursor.execute(query, params_with_pagination)
        raw_leads = cursor.fetchall()

        leads = []
        for row in raw_leads:
            lead = dict(row)
            try:
                lead["tags"] = json.loads(lead.get("tags") or "[]")
            except Exception:
                lead["tags"] = []
            try:
                lead["listas"] = json.loads(lead.get("listas_json") or "[]")
            except Exception:
                lead["listas"] = []
            try:
                lead["secuencias"] = json.loads(lead.get("secuencias_json") or "[]")
            except Exception:
                lead["secuencias"] = []
            try:
                lead["ultima_actividad"] = json.loads(lead.get("ultima_actividad_json") or "null")
            except Exception:
                lead["ultima_actividad"] = None
            try:
                lead["zoho_tratos"] = json.loads(lead.get("zoho_tratos_info") or "[]")
            except Exception:
                lead["zoho_tratos"] = []

            lead.pop("listas_json", None)
            lead.pop("secuencias_json", None)
            lead.pop("ultima_actividad_json", None)
            leads.append(lead)

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "leads": leads
        }

@app.get("/api/prospectos/{lead_id}")
def get_lead_detail(
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Obtiene la ficha técnica completa del prospecto, incluyendo historial de actividades, mensajes y correos."""
    caller = _get_current_user(authorization, x_session_token)
    lead = _authorize_lead_access(caller, lead_id)
    with get_db() as conn:
        cursor = conn.cursor()
        lead["tags"] = json.loads(lead.get("tags") or "[]")
        try:
            lead["zoho_tratos"] = json.loads(lead.get("zoho_tratos_info") or "[]")
        except Exception:
            lead["zoho_tratos"] = []

        cursor.execute("SELECT * FROM historial_actividades WHERE lead_id = ? ORDER BY timestamp DESC", (lead_id,))
        lead["historial"] = cursor.fetchall()

        cursor.execute("SELECT * FROM mensajes_linkedin WHERE lead_id = ? ORDER BY created_at ASC", (lead_id,))
        lead["mensajes_linkedin"] = cursor.fetchall()

        cursor.execute("SELECT * FROM mensajes_whatsapp WHERE lead_id = ? ORDER BY created_at ASC", (lead_id,))
        lead["mensajes_whatsapp"] = cursor.fetchall()

        cursor.execute("SELECT * FROM correos_electronicos WHERE lead_id = ? ORDER BY created_at ASC", (lead_id,))
        lead["correos"] = cursor.fetchall()

        cursor.execute("SELECT * FROM interacciones_sociales WHERE lead_id = ? ORDER BY fecha DESC", (lead_id,))
        lead["interacciones"] = cursor.fetchall()

        return lead

@app.post("/api/prospectos/{lead_id}/seguir")
def toggle_follow(
    lead_id: str,
    seguir: bool = True,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Activa o desactiva el seguimiento directo del prospecto en la red social."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
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

@app.post("/api/prospectos/{lead_id}/retirar-invitacion")
def withdraw_invitation(
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retira la invitación pendiente de conexión enviada al prospecto."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
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

@app.post("/api/prospectos/{lead_id}/sincronizar-linkedin")
def sync_lead_with_linkedin(
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Sincroniza y enriquece en vivo los datos del prospecto (cargo actual, titular,
    empresa y ubicación) inspeccionando directamente su perfil real en LinkedIn.
    """
    caller = _get_current_user(authorization, x_session_token)
    lead = _authorize_lead_access(caller, lead_id)
    with get_db() as conn:
        cursor = conn.cursor()
        url = lead.get("perfil_url")
        if not url:
            raise HTTPException(status_code=400, detail="El lead no tiene URL de LinkedIn asignada")

        import extractor_engine
        enriched = extractor_engine.enrich_lead_from_live_profile(url)
        if not enriched.get("ok"):
            err_msg = enriched.get("error", "Error sincronizando con LinkedIn")
            status = 400 if any(k in err_msg.lower() for k in ["sesión", "no iniciada", "no permitida", "404", "parámetro"]) else 500
            raise HTTPException(status_code=status, detail=err_msg)

        now_iso = datetime.now().isoformat()
        nuevo_nombre = enriched.get("nombre")
        if not nuevo_nombre or "esta página no existe" in nuevo_nombre.lower() or "404" in nuevo_nombre.lower():
            nuevo_nombre = lead.get("nombre")
        nuevo_titular = enriched.get("cargo_titular") or lead.get("cargo_titular")
        nuevo_cargo_act = enriched.get("cargo_actual") or lead.get("cargo_actual")
        nueva_inst = (enriched.get("institucion_actual") or "").strip()
        if not nueva_inst or nueva_inst.lower() in ["institución educativa", "institución escolar", "empresa u organización", "chile"]:
            prev_inst = (lead.get("institucion_actual") or "").strip()
            if prev_inst and prev_inst.lower() not in ["institución educativa", "institución escolar", "empresa u organización", "chile"]:
                nueva_inst = prev_inst
            else:
                nueva_inst = ""
        nueva_ubic = enriched.get("ubicacion") or lead.get("ubicacion")
        nuevo_grado = enriched.get("grado_red") or lead.get("grado_red")
        nuevo_estado = "CONECTADO" if nuevo_grado == "1º" else lead.get("estado")
        nueva_fecha_conn = now_iso if (nuevo_grado == "1º" and not lead.get("fecha_conexion")) else lead.get("fecha_conexion")

        cursor.execute("""
            UPDATE leads
            SET nombre = ?, cargo_titular = ?, cargo_actual = ?, institucion_actual = ?, ubicacion = ?, grado_red = ?, estado = ?, fecha_conexion = ?, updated_at = ?
            WHERE id = ?
        """, (nuevo_nombre, nuevo_titular, nuevo_cargo_act, nueva_inst, nueva_ubic, nuevo_grado, nuevo_estado, nueva_fecha_conn, now_iso, lead_id))

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

@app.post("/api/leads/sincronizar-conexiones")
def sync_connections_endpoint(
    tenant_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Inspecciona en bloque https://www.linkedin.com/mynetwork/invite-connect/connections/
    y sincroniza automáticamente el estado de los leads que hayan aceptado la invitación a CONECTADO.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    import connection_sync_service
    connection_sync_service.start_periodic_connection_sync()
    res = connection_sync_service.sync_accepted_connections(tenant_id=target_tenant, force_outside_hours=True)
    return res

@app.put("/api/prospectos/{lead_id}/contacto")
def update_contact(
    lead_id: str,
    email: Optional[str] = None,
    telefono: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza manualmente los datos de contacto directo (correo electrónico y teléfono) del prospecto."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
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

@app.post("/api/prospectos/lote/resolver-correo")
@app.post("/api/leads/lote/resolver-correo")
def batch_resolve_leads_email_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Resuelve correos electrónicos para un lote de prospectos en cascada.
    """
    caller = _get_current_user(authorization, x_session_token)
    lead_ids = datos.get("lead_ids", [])
    forzar = bool(datos.get("forzar", False))
    _authorize_leads_batch_access(caller, lead_ids, expected_tenant=datos.get("tenant_id"))
    import email_resolver_service
    return email_resolver_service.batch_resolve_lead_emails(lead_ids, force_refresh=forzar)

@app.post("/api/prospectos/{lead_id}/resolver-correo")
@app.post("/api/leads/{lead_id}/resolver-correo")
def resolve_lead_email_endpoint(
    lead_id: str,
    forzar: bool = Query(False, description="Forzar nueva resolución aunque ya exista correo"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Resuelve el correo electrónico del lead utilizando la estrategia en cascada (Waterfall):
    1. Si es 1er grado: extracción directa desde LinkedIn contact-info overlay.
    2. Si es 2do/3er grado o privado: resolución de dominio, APIs externas,
       generación de patrones corporativos, validación DNS MX y ping SMTP.
    """
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
    import email_resolver_service
    resultado = email_resolver_service.resolve_lead_email(lead_id, force_refresh=forzar)
    if not resultado.get("ok") and not resultado.get("status"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Error resolviendo correo"))
    return resultado

@app.post("/api/enrichment/test-diagnostico")
def test_email_enrichment_diagnostics(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Herramienta de diagnóstico para probar sintaxis, DNS MX y verificación desacoplada (EmailVerifier).
    """
    caller = _get_current_user(authorization, x_session_token)
    _resolve_permitted_tenants(caller, None)
    import email_resolver_service
    import email_verifier_service
    email = datos.get("email", "").strip()
    dominio = datos.get("dominio", "").strip()
    nombre = datos.get("nombre", "").strip()
    institucion = (datos.get("institucion", "") or datos.get("empresa", "")).strip()

    verifier = email_verifier_service.get_email_verifier()

    if email:
        syntax_ok = email_resolver_service.check_email_syntax(email)
        dom = email.split("@")[-1] if "@" in email else ""
        mx_list = email_resolver_service.get_domain_mx_records(dom) if dom else []
        verify_res = verifier.verify(email).to_dict()
        return {
            "email": email,
            "sintaxis_valida": syntax_ok,
            "dominio": dom,
            "mx_records": mx_list,
            "verificacion_resultado": verify_res
        }
    elif institucion or (nombre and dominio):
        first, last, mat = email_resolver_service.parse_person_names(nombre)
        dom = dominio or (email_resolver_service.resolve_company_domain(institucion)[0] if institucion else "")
        patterns = email_resolver_service.generate_corporate_patterns(first, last, dom, mat) if dom else []
        mx_list = email_resolver_service.get_domain_mx_records(dom) if dom else []
        verify_res = verifier.verify(patterns[0]).to_dict() if patterns else {}
        return {
            "nombre": nombre,
            "institucion": institucion,
            "dominio_resuelto": dom,
            "patrones_generados": patterns,
            "mx_records": mx_list,
            "verificacion_resultado": verify_res
        }
    else:
        raise HTTPException(status_code=400, detail="Debe indicar 'email' o ('nombre' e 'institucion')")

@app.post("/api/prospectos/importar-lote")
def import_prospects_batch(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Guarda en la base de datos únicamente los prospectos seleccionados por el usuario y los vincula a las listas elegidas."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]

    leads = datos.get("leads", [])
    list_id = datos.get("lista_id")
    list_ids = list(datos.get("lista_ids") or datos.get("list_ids") or [])
    if list_id and list_id not in list_ids:
        list_ids.append(list_id)

    for lid in list_ids:
        lst = _authorize_list_access(caller, lid)
        if lst.get("tenant_id") != target_tenant:
            raise HTTPException(
                status_code=403,
                detail="No puedes vincular prospectos a una lista perteneciente a otro workspace."
            )

    if not leads:
        raise HTTPException(status_code=400, detail="No se proporcionaron prospectos para importar")
    return extractor_engine.import_selected_leads(leads, list_id=list_id, list_ids=list_ids, tenant_id=target_tenant)

@app.delete("/api/prospectos/{lead_id}")
def delete_prospect(
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina permanentemente un prospecto y todos sus registros asociados."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_lead_access(caller, lead_id)
    extractor_engine.delete_lead(lead_id)
    return {"status": "ok", "eliminado": True, "lead_id": lead_id}

@app.post("/api/prospectos/eliminar-lote")
def delete_prospects_batch(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina permanentemente múltiples prospectos seleccionados en lote."""
    caller = _get_current_user(authorization, x_session_token)
    lead_ids = datos.get("lead_ids", [])
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No se enviaron IDs de prospectos")
    _authorize_leads_batch_access(caller, lead_ids, expected_tenant=datos.get("tenant_id"))
    total = extractor_engine.delete_leads_batch(lead_ids)
    return {"status": "ok", "eliminados": total, "lead_ids": lead_ids}

# ==========================================
# WORK BROWSER INTEGRATION (ELECTRON / BROWSEROS)
# ==========================================
@app.get("/api/browser/estado")
def get_browser_status():
    """Retorna el estado de conectividad del navegador de trabajo (Chromium aislado en Electron o BrowserOS Neo)."""
    is_electron = browser_service.is_electron_running()
    electron_state = browser_service.get_electron_status() if is_electron else {}
    sesion_linkedin = bool(electron_state.get("sesion_linkedin_activa", False))
    sesion_whatsapp = bool(electron_state.get("sesion_whatsapp_activa", False))
    sesion_zoho = bool(electron_state.get("sesion_zoho_activa", False))
    if not sesion_zoho:
        try:
            import zoho_browser_service
            zo_res = zoho_browser_service.check_zoho_browser_session()
            sesion_zoho = bool(zo_res.get("active", False))
        except Exception:
            pass

    active = is_electron or browser_service.is_browseros_running()
    engine_name = "Chromium Embebido Aislado (Electron)" if is_electron else ("BrowserOS Neo" if active else "Inactivo")
    return {
        "activo": active,
        "is_electron": is_electron,
        "motor": engine_name,
        "sesion_linkedin_activa": sesion_linkedin,
        "sesion_whatsapp_activa": sesion_whatsapp,
        "sesion_zoho_activa": sesion_zoho,
        "visible": bool(electron_state.get("visible", False)),
        "mensaje": f"{engine_name} Conectado" if active else "Navegador de trabajo inactivo"
    }

@app.post("/api/zoho/login")
def login_zoho_endpoint():
    """Abre la pantalla oficial de acceso de Zoho Accounts para autenticar de forma limpia y persistente."""
    return browser_service.show_work_browser(url="https://accounts.zoho.com/signin?servicename=ZohoCRM", channel="zoho")

@app.post("/api/zoho/logout")
def logout_zoho_endpoint():
    """Cierra la sesión de Zoho, purga las cookies/caché y reinicia la ventana en la pantalla de login."""
    return browser_service.logout_zoho()

@app.post("/api/browser/iniciar")
def launch_browser():
    """Inicia las sesiones de trabajo en el navegador."""
    return browser_service.start_work_sessions()

@app.post("/api/browser/mostrar")
def show_browser(
    url: Optional[str] = Query(None, description="URL a la que navegar al mostrar"),
    channel: Optional[str] = Query(None, description="Canal específico ('linkedin', 'whatsapp' o 'zoho')")
):
    """Muestra la ventana del navegador de trabajo en primer plano."""
    return browser_service.show_work_browser(url=url, channel=channel)

@app.post("/api/browser/ocultar")
def hide_browser(
    channel: Optional[str] = Query(None, description="Canal específico ('linkedin', 'whatsapp' o 'zoho')")
):
    """Oculta la ventana del navegador de trabajo a segundo plano."""
    return browser_service.hide_work_browser(channel=channel)

@app.post("/api/browser/abrir")
def open_browser_link(url: str = Query(..., description="URL que se abrirá en el navegador de trabajo")):
    """Abre una URL específica en el navegador de trabajo activo."""
    return browser_service.open_url(url)

@app.post("/api/prospectos/{lead_id}/abrir-en-browseros")
def open_lead_in_browseros(
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Abre el perfil del prospecto en el navegador y registra el evento en el historial."""
    caller = _get_current_user(authorization, x_session_token)
    lead = _authorize_lead_access(caller, lead_id)
    with get_db() as conn:
        cursor = conn.cursor()
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

# ==========================================
# CENTRALIZED SAFETY & ANTI-BAN MANAGEMENT
# ==========================================
@app.get("/api/seguridad/estado")
def get_safety_status():
    """Retorna el diagnóstico integral de seguridad, pausas estocásticas, límites diarios y estado del freno de emergencia."""
    with get_db() as conn:
        config = safety_engine.get_all_safety_config(conn)
        diag_linkedin = safety_engine.check_linkedin_safety(conn)
        diag_email = safety_engine.check_email_workspace_safety(conn)
        diag_whatsapp = whatsapp_safety_engine.check_whatsapp_safety(conn)
        warmup_status = safety_engine.get_linkedin_warmup_status(conn)
        search_status = safety_engine.get_linkedin_search_usage(conn)
        in_hours, hours_detail = safety_engine.check_business_hours(config)
        
        return {
            "seguro_para_operar": diag_linkedin["autorizado"] and diag_whatsapp["safe"],
            "linkedin": diag_linkedin,
            "google_workspace": diag_email,
            "whatsapp": diag_whatsapp,
            "linkedin_warmup": warmup_status,
            "linkedin_busquedas": search_status,
            "horario_laboral": {
                "en_horario": in_hours,
                "detalle": hours_detail,
                "restriccion_activa": config.get("horario_laboral_activo", "1") == "1",
                "horario_inicio": config.get("horario_inicio", "09:00"),
                "horario_fin": config.get("horario_fin", "18:00"),
                "dias_laborales": config.get("dias_laborales", "0,1,2,3,4")
            },
            "pausas_antiban": {
                "activas": config.get("pausas_antiban_activas", "1") == "1",
                "min_seg": int(config.get("pausa_linkedin_min_seg", 180)),
                "max_seg": int(config.get("pausa_linkedin_max_seg", 360))
            },
            "limites_diarios": {
                "activos": config.get("limites_diarios_activos", "1") == "1",
                "limite_linkedin": int(config.get("limite_linkedin_diario", 5)),
                "limite_email": int(config.get("limite_email_workspace_diario", 15)),
                "limite_whatsapp": int(config.get("whatsapp_cuota_diaria", config.get("whatsapp_limite_diario", 15)))
            },
            "kill_switch": {
                "activado": config.get("kill_switch_activado") == "1" or config.get("seguridad_kill_switch") == "1",
                "motivo": config.get("kill_switch_motivo", "")
            },
            "configuracion": config,
            "pausa_sugerida_linkedin_seg": safety_engine.calculate_gaussian_delay(config=config),
            "pausa_sugerida_email_seg": safety_engine.calculate_email_delay(config=config),
            "pausa_sugerida_whatsapp_seg": whatsapp_safety_engine.calculate_whatsapp_delay(config=config)
        }

@app.post("/api/seguridad/kill-switch/activar")
def activate_kill_switch_manual(
    motivo: str = Query("Freno manual accionado por el usuario", description="Motivo de la parada de emergencia"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Activa manualmente el freno de emergencia (kill-switch) deteniendo todas las operaciones salientes."""
    caller = _get_current_user(authorization, x_session_token)
    _resolve_permitted_tenants(caller, None)
    with get_db() as conn:
        return safety_engine.activate_kill_switch(motivo, conn)

@app.post("/api/seguridad/kill-switch/desactivar")
def deactivate_kill_switch_manual(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Desactiva el freno de emergencia permitiendo reanudar las operaciones normales."""
    caller = _get_current_user(authorization, x_session_token)
    _resolve_permitted_tenants(caller, None)
    with get_db() as conn:
        return safety_engine.deactivate_kill_switch(conn)

@app.post("/api/seguridad/configuracion")
def update_safety_config(
    clave: Optional[str] = Query(None, description="Clave de configuración"),
    valor: Optional[str] = Query(None, description="Nuevo valor"),
    body: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza uno o varios parámetros clave en la configuración del motor de seguridad antiban y horarios."""
    caller = _get_current_user(authorization, x_session_token)
    _resolve_permitted_tenants(caller, None)

    updated = {}
    with get_db() as conn:
        if body and isinstance(body, dict):
            for k, v in body.items():
                if v is not None:
                    safety_engine.set_safety_config_val(k, str(v), conn)
                    updated[k] = str(v)
        
        target_clave = clave or (body.get("clave") if body and not updated else None)
        target_valor = valor if valor is not None else (body.get("valor") if body and not updated else None)
        if target_clave and target_valor is not None:
            safety_engine.set_safety_config_val(target_clave, str(target_valor), conn)
            updated[target_clave] = str(target_valor)

        if not updated:
            raise HTTPException(status_code=400, detail="Se requiere clave y valor o un cuerpo JSON con las configuraciones")

        return {"status": "ok", "actualizados": updated}

@app.post("/api/seguridad/spintax/probar")
def test_spintax(plantilla: str = Query(..., description="Texto con patrones Spintax como {Hola|Estimado}")):
    """Evalúa y procesa una plantilla con sintaxis Spintax generando una variación estocástica de prueba."""
    variation = safety_engine.process_spintax(plantilla)
    return {"plantilla_original": plantilla, "variacion_generada": variation}

@app.post("/api/seguridad/validar-email")
def validate_email_endpoint(email: str = Query(..., description="Correo electrónico del colegio a validar")):
    """Valida la sintaxis RFC y la existencia de registros DNS MX para un correo electrónico."""
    return safety_engine.validate_email_syntax_and_mx(email)

# ==========================================
# ZOHO CRM BROWSER-SESSION INTELLIGENCE & SYNC
# ==========================================
@app.get("/api/zoho/estado-sesion")
def get_zoho_session_status():
    """Consulta el estado de la sesión de Zoho CRM en el navegador de trabajo activo."""
    return zoho_browser_service.check_zoho_browser_session()

# ==========================================
# MULTICHANNEL ANTI-BAN SUITE (WHATSAPP & WARM-UP)
# ==========================================
@app.get("/api/whatsapp/seguridad/estado")
def get_whatsapp_safety_status():
    """Retorna el diagnóstico de seguridad, cuota diaria y pausas de WhatsApp Web."""
    with get_db() as conn:
        safety = whatsapp_safety_engine.check_whatsapp_safety(conn)
        usage = whatsapp_safety_engine.get_whatsapp_daily_usage(conn)
        delay = whatsapp_safety_engine.calculate_whatsapp_delay()
        return {
            "seguridad": safety,
            "uso_diario": usage,
            "pausa_sugerida_segundos": delay
        }

@app.get("/api/linkedin/warmup/estado")
def get_linkedin_warmup_status_endpoint():
    """Retorna el estado de la curva de calentamiento (warm-up) y uso comercial de búsquedas de LinkedIn."""
    with get_db() as conn:
        warmup = safety_engine.get_linkedin_warmup_status(conn)
        searches = safety_engine.get_linkedin_search_usage(conn)
        return {
            "warmup": warmup,
            "busquedas_comerciales": searches
        }

@app.post("/api/linkedin/invitaciones-vencidas/retirar")
def withdraw_stale_invitations_endpoint(
    dias_limite: int = Query(21, ge=7, le=90, description="Días de antigüedad máxima"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant a procesar"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retira en bloque las invitaciones pendientes que superen el límite de días configurado para el tenant autorizado."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _require_tenant_admin(caller, tenant_id)
    cutoff = (datetime.now() - timedelta(days=dias_limite)).isoformat()
    now_iso = datetime.now().isoformat()
    placeholders = ", ".join(["?"] * len(tenants))
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id
            FROM leads
            WHERE estado = 'INVITACION_ENVIADA'
              AND (invitacion_retirada IS NULL OR invitacion_retirada = 0)
              AND fecha_invitacion IS NOT NULL
              AND fecha_invitacion <= ?
              AND tenant_id IN ({placeholders})
            ORDER BY fecha_invitacion ASC
            """,
            [cutoff] + list(tenants)
        )
        stale_leads = cursor.fetchall()
        if not stale_leads:
            return {"retiradas": 0, "mensaje": "No hay invitaciones que superen el umbral de antigüedad."}
        retiradas = 0
        for lead in stale_leads:
            lid = lead["id"]
            cursor.execute(
                """
                UPDATE leads
                SET invitacion_retirada = 1,
                    fecha_retiro_invitacion = ?,
                    estado = 'INVITACION_RETIRADA',
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, lid)
            )
            cursor.execute(
                """
                INSERT INTO historial_actividades (lead_id, tipo_evento, descripcion, timestamp)
                VALUES (?, 'INVITACION_RETIRADA_AUTOMATICA', ?, ?)
                """,
                (lid, f"Retiro automático por antigüedad (> {dias_limite} días sin respuesta).", now_iso)
            )
            retiradas += 1
        return {
            "retiradas": retiradas,
            "invitaciones_retiradas": retiradas,
            "dias_umbral": dias_limite,
            "timestamp": now_iso,
            "mensaje": f"Se marcaron {retiradas} invitaciones como retiradas para proteger el ratio de aceptación."
        }

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
    """Ejecuta la búsqueda y extracción de prospectos desde LinkedIn según los parámetros indicados."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]

    if lista_id:
        lst = _authorize_list_access(caller, lista_id)
        if lst.get("tenant_id") != target_tenant:
            raise HTTPException(
                status_code=403,
                detail="La lista de destino no pertenece al workspace autorizado para esta extracción."
            )

    return extractor_engine.search_and_extract_leads(
        termino, 
        page=pagina, 
        auto_save=auto_guardar, 
        list_id=lista_id, 
        tenant_id=target_tenant
    )

@app.post("/api/extraccion/red-linkedin")
def extract_network_leads_endpoint(
    origen: str = Query("all", description="Canal de red: 'all', 'connections', o 'sent_invitations'"),
    limite: int = Query(50, description="Cantidad máxima de contactos a extraer de la cola (default 50)"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant destino"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Extrae decisores y contactos desde la red personal de LinkedIn (Conexiones 1º grado y/o Invitaciones enviadas).
    Devuelve la lista con el estado correspondiente para previsualización y guardado manual con la menor cantidad de clics.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]

    return extractor_engine.extract_network_leads(
        source=origen,
        limit=limite,
        tenant_id=target_tenant
    )

# ==========================================
# MULTICHANNEL SEQUENCE ENGINE (DECISION TREES)
# ==========================================
@app.get("/api/secuencias")
def list_sequences_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna todas las secuencias autorizadas para los tenants del usuario con sus métricas agregadas."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    return {"secuencias": sequence_engine.get_sequences(tenant_ids=tenants)}

# ==========================================
# REGISTRO HISTÓRICO DE SUCESOS (OPERADOR & ADMIN)
# NOTA: Debe declararse ANTES de /api/secuencias/{secuencia_id} para evitar colisión de ruta
# ==========================================
@app.get("/api/secuencias/sucesos")
@app.get("/api/sucesos")
def get_secuencias_sucesos_endpoint(
    limit: int = Query(50, description="Cantidad máxima de sucesos a retornar"),
    offset: int = Query(0, description="Desplazamiento para paginación"),
    tipo_evento: Optional[str] = Query(None, description="Filtro por tipo de evento"),
    search: Optional[str] = Query(None, description="Término de búsqueda por prospecto, cargo o detalle"),
    secuencia_id: Optional[str] = Query(None, description="Filtrar por ID de secuencia"),
    tenant_id: Optional[str] = Query(None, description="Filtrar sucesos por tenant autorizado"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Retorna el historial cronológico de sucesos y acciones ejecutadas por las secuencias
    (Visitas, Invitaciones, Mensajes, Esperas, Sincronizaciones).
    Accesible para el rol OPERADOR, COMPANY_ADMIN, AGENCY_ADMIN y SUPER_ADMIN.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    import sequence_engine
    return sequence_engine.get_sequence_events(
        tenant_ids=tenants,
        limit=limit,
        offset=offset,
        tipo_evento=tipo_evento,
        search=search,
        secuencia_id=secuencia_id
    )

@app.get("/api/secuencias/{secuencia_id}")
def get_sequence_endpoint(
    secuencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna el detalle completo de la secuencia y su árbol jerárquico de pasos."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    sec = sequence_engine.get_full_sequence(secuencia_id)
    if not sec:
        raise HTTPException(status_code=404, detail="Secuencia no encontrada")
    return sec

@app.post("/api/secuencias")
def create_sequence_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea una nueva secuencia multicanal asociada al tenant."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]

    nombre = datos.get("nombre", "Nueva Secuencia Multicanal")
    descripcion = datos.get("descripcion", "")
    estado = datos.get("estado", "BORRADOR")
    activa = bool(datos.get("activa", False) and estado == "PUBLICADA")
    plantilla = datos.get("plantilla", "multicanal")
    return sequence_engine.create_sequence(nombre, descripcion, activa, plantilla, tenant_id=target_tenant, estado=estado)

@app.put("/api/secuencias/{secuencia_id}")
def update_sequence_endpoint(
    secuencia_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza los metadatos principales de una secuencia."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    res = sequence_engine.update_sequence(
        secuencia_id,
        nombre=datos.get("nombre"),
        descripcion=datos.get("descripcion"),
        activa=datos.get("activa")
    )
    if not res:
        raise HTTPException(status_code=400, detail="No se pudo actualizar la secuencia")
    return {"status": "ok", "secuencia_id": secuencia_id}

@app.delete("/api/secuencias/{secuencia_id}")
def delete_sequence_endpoint(
    secuencia_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina una secuencia y todo su árbol de pasos asociados."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    sequence_engine.delete_sequence(secuencia_id)
    return {"status": "ok", "secuencia_id": secuencia_id}

@app.post("/api/secuencias/{secuencia_id}/pasos")
def save_steps_endpoint(
    secuencia_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Guarda o reemplaza el árbol completo de pasos de una secuencia."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    pasos = datos.get("pasos", [])
    sequence_engine.save_sequence_steps(secuencia_id, pasos)
    return {"status": "ok", "secuencia_id": secuencia_id, "total_pasos": len(pasos)}

@app.post("/api/secuencias/{secuencia_id}/pasos/agregar")
def add_step_endpoint(
    secuencia_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Inserta un nuevo paso en el árbol jerárquico de la secuencia."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    posicion = datos.get("posicion", "final")
    ref_id = datos.get("paso_referencia_id")
    res = sequence_engine.add_sequence_step(secuencia_id, datos, posicion, ref_id)
    return {"status": "ok", "secuencia_id": secuencia_id, "paso": res}

@app.delete("/api/secuencias/{secuencia_id}/pasos/{paso_id}")
def delete_step_endpoint(
    secuencia_id: str,
    paso_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina un paso específico de la secuencia."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    res = sequence_engine.delete_sequence_step(secuencia_id, paso_id)
    if not res:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    return {"status": "ok", "secuencia_id": secuencia_id, "paso_id": paso_id}

@app.post("/api/secuencias/{secuencia_id}/asignar-leads")
def assign_leads_endpoint(
    secuencia_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Inscribe y asigna una lista de prospectos en el paso inicial de la secuencia."""
    caller = _get_current_user(authorization, x_session_token)
    sec = _authorize_sequence_access(caller, secuencia_id)
    sec_tenant = sec.get("tenant_id")

    lead_ids = datos.get("lead_ids", [])
    if lead_ids:
        _authorize_leads_batch_access(caller, lead_ids, expected_tenant=sec_tenant)
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE estado = 'EXTRAIDO' AND tenant_id = ?", (sec_tenant,))
            lead_ids = [r["id"] for r in cur.fetchall()]

    return sequence_engine.assign_leads_to_sequence(secuencia_id, lead_ids)

@app.get("/api/secuencias/{secuencia_id}/leads")
def list_sequence_leads_endpoint(
    secuencia_id: str,
    estado: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna los prospectos inscritos en la secuencia con su estado de avance actual."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    leads = sequence_engine.get_leads_in_sequence(secuencia_id, estado)
    return {"leads": leads, "total": len(leads)}

@app.post("/api/secuencias/ejecutar-siguiente")
def execute_next_step_endpoint(
    secuencia_id: Optional[str] = Query(None, description="ID opcional de la secuencia a procesar"),
    tenant_id: Optional[str] = Query(None, description="ID opcional del tenant"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Ejecuta el siguiente paso pendiente de una secuencia aplicando todas las reglas de seguridad antiban."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    if secuencia_id:
        sec = _authorize_sequence_access(caller, secuencia_id)
        if tenant_id and sec.get("tenant_id") not in tenants:
            raise HTTPException(status_code=403, detail="La secuencia no pertenece al workspace solicitado.")
        return sequence_engine.execute_next_step(secuencia_id)

    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        placeholders = ", ".join(["?"] * len(tenants))
        cursor.execute(
            f"""
            SELECT ls.secuencia_id
            FROM leads_en_secuencia ls
            JOIN secuencias s ON ls.secuencia_id = s.id
            WHERE ls.estado = 'EN_CURSO'
              AND s.activa = 1
              AND s.estado = 'PUBLICADA'
              AND ls.proxima_ejecucion_at <= ?
              AND s.tenant_id IN ({placeholders})
            ORDER BY ls.proxima_ejecucion_at ASC
            LIMIT 1
            """,
            [now_iso] + list(tenants)
        )
        row = cursor.fetchone()
    if not row:
        return {
            "status": "idle",
            "mensaje": "No hay prospectos con pasos pendientes listos para ejecutar en este momento (o están en período de espera)."
        }
    return sequence_engine.execute_next_step(row["secuencia_id"])

@app.post("/api/secuencias/{secuencia_id}/estado")
def change_sequence_status_endpoint(
    secuencia_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Publica, pausa o archiva una secuencia modificando su estado de ejecución."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_sequence_access(caller, secuencia_id)
    nuevo_estado = datos.get("estado", "PUBLICADA")
    sequence_engine.change_sequence_publish_status(secuencia_id, nuevo_estado)
    return {"status": "ok", "secuencia_id": secuencia_id, "estado": nuevo_estado}

@app.post("/api/secuencias/barrer-esperas")
def sweep_expired_delays_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Ejecuta de forma explícita el barrido y promoción de prospectos con esperas vencidas."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    count = sequence_engine.promote_expired_delays(tenant_id=target_tenant)
    return {"status": "ok", "promovidos": count}

# ==========================================
# B2B METRICS DASHBOARD
# ==========================================
@app.get("/api/dashboard/metricas")
def get_dashboard_metrics_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant"),
    secuencia_id: Optional[str] = Query(None, description="Filtrar por secuencia"),
    lista_id: Optional[str] = Query(None, description="Filtrar por lista"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna las métricas agregadas, embudo de conversión y estado de salud antiban para el Dashboard."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0] if tenants else None

    if secuencia_id:
        sec = _authorize_sequence_access(caller, secuencia_id)
        if target_tenant and sec.get("tenant_id") != target_tenant:
            raise HTTPException(status_code=403, detail="La secuencia solicitada no pertenece al workspace activo.")

    if lista_id:
        lst = _authorize_list_access(caller, lista_id)
        if target_tenant and lst.get("tenant_id") != target_tenant:
            raise HTTPException(status_code=403, detail="La lista solicitada no pertenece al workspace activo.")

    return dashboard_service.get_dashboard_metrics(
        tenant_id=target_tenant,
        sequence_id=secuencia_id,
        list_id=lista_id
    )

# ==========================================
# LEAD LISTS MANAGEMENT (AUDIENCES)
# ==========================================
@app.get("/api/listas")
def list_lists_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna todas las listas de prospectos autorizadas para el tenant."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    return {"listas": lists_engine.get_lead_lists(tenant_ids=tenants)}

@app.get("/api/listas/{lista_id}")
def get_list_detail_endpoint(
    lista_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna el detalle de una lista de leads y sus prospectos asociados."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_list_access(caller, lista_id)
    res = lists_engine.get_lead_list_detail(lista_id)
    if not res:
        raise HTTPException(status_code=404, detail="Lista no encontrada")
    return res

@app.post("/api/listas")
def create_list_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea una nueva lista de prospectos vinculada a su tenant correspondiente."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]

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

@app.put("/api/listas/{lista_id}")
def update_list_endpoint(
    lista_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza los metadatos de una lista de leads."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_list_access(caller, lista_id)
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

@app.delete("/api/listas/{lista_id}")
def delete_list_endpoint(
    lista_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina una lista de prospectos."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_list_access(caller, lista_id)
    lists_engine.delete_lead_list(lista_id)
    return {"status": "ok", "lista_id": lista_id}

@app.post("/api/listas/{lista_id}/leads")
def add_leads_to_list_endpoint(
    lista_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Agrega prospectos a una lista e inscribe automáticamente en las secuencias activas conectadas."""
    caller = _get_current_user(authorization, x_session_token)
    lst = _authorize_list_access(caller, lista_id)
    lead_ids = datos.get("lead_ids", [])
    _authorize_leads_batch_access(caller, lead_ids, expected_tenant=lst.get("tenant_id"))
    return lists_engine.add_leads_to_list(lista_id, lead_ids)

@app.delete("/api/listas/{lista_id}/leads/{lead_id}")
def remove_lead_from_list_endpoint(
    lista_id: str,
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Remueve un prospecto de una lista específica."""
    caller = _get_current_user(authorization, x_session_token)
    lst = _authorize_list_access(caller, lista_id)
    lead = _authorize_lead_access(caller, lead_id)
    if lead.get("tenant_id") != lst.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="El prospecto y la lista pertenecen a workspaces distintos."
        )
    lists_engine.remove_lead_from_list(lista_id, lead_id)
    return {"status": "ok", "lista_id": lista_id, "lead_id": lead_id}

@app.post("/api/listas/{lista_id}/conectar-secuencia")
def connect_list_to_sequence_endpoint(
    lista_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Conecta una lista de leads con una secuencia automatizada."""
    caller = _get_current_user(authorization, x_session_token)
    lst = _authorize_list_access(caller, lista_id)
    secuencia_id = datos.get("secuencia_id")
    if not secuencia_id:
        raise HTTPException(status_code=400, detail="secuencia_id es requerido")
    sec = _authorize_sequence_access(caller, secuencia_id)
    if lst.get("tenant_id") != sec.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="No puedes conectar una lista con una secuencia perteneciente a otro workspace."
        )
    return lists_engine.connect_list_to_sequence(secuencia_id, lista_id)

@app.post("/api/listas/{lista_id}/desconectar-secuencia")
def disconnect_list_from_sequence_endpoint(
    lista_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Desconecta una lista de leads de una secuencia automatizada."""
    caller = _get_current_user(authorization, x_session_token)
    lst = _authorize_list_access(caller, lista_id)
    secuencia_id = datos.get("secuencia_id")
    if not secuencia_id:
        raise HTTPException(status_code=400, detail="secuencia_id es requerido")
    sec = _authorize_sequence_access(caller, secuencia_id)
    if lst.get("tenant_id") != sec.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="No puedes desconectar recursos pertenecientes a distintos workspaces."
        )
    lists_engine.disconnect_list_from_sequence(secuencia_id, lista_id)
    return {"status": "ok", "secuencia_id": secuencia_id, "lista_id": lista_id}

@app.post("/api/listas/{lista_id}/iniciar-extraccion")
def start_list_extraction_endpoint(
    lista_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Inicia la extracción y enriquecimiento automático de prospectos para una lista respetando pausas antiban."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_list_access(caller, lista_id)
    res = lists_engine.start_list_extraction(lista_id)
    return res

@app.post("/api/listas/{lista_id}/detener-extraccion")
def stop_list_extraction_endpoint(
    lista_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Detiene la extracción automática de prospectos en curso para una lista."""
    caller = _get_current_user(authorization, x_session_token)
    _authorize_list_access(caller, lista_id)
    res = lists_engine.stop_list_extraction(lista_id)
    return res

# ==========================================
# STAGING & MATCHING ENGINE (LINKEDIN DISCOVERY)
# ==========================================
import matching_engine

@app.get("/api/matching/leads")
def list_matching_leads_endpoint(
    estado: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista los prospectos del buzón de matching y staging con filtros."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    return matching_engine.list_staging_leads(
        tenant_id=target_tenant,
        estado=estado,
        search=search,
        limit=limit,
        offset=offset
    )

@app.get("/api/matching/stats")
def get_matching_stats_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna métricas consolidadas del buzón de matching."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    return matching_engine.get_staging_stats(tenant_id=target_tenant)

@app.post("/api/matching/leads")
def create_manual_staging_lead_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Crea un nuevo prospecto manual uno a uno en el buzón de staging."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]
    try:
        lead = matching_engine.create_staging_lead(datos, tenant_id=target_tenant)
        if datos.get("buscar_inmediato"):
            match_res = matching_engine.search_candidate_for_staging_lead(lead["id"])
            lead = matching_engine.get_staging_lead(lead["id"]) or lead
            lead["match_resultado"] = match_res
        return lead
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/matching/leads/importar-lote")
def import_batch_staging_leads_endpoint(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Importa prospectos en bloque desde CSV o estructura JSON al staging."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]
    leads_list = datos.get("leads") or []
    origen = datos.get("origen", "CSV")
    return matching_engine.batch_create_staging_leads(leads_list, tenant_id=target_tenant, origen=origen)

@app.post("/api/matching/leads/importar-zoho")
def import_zoho_staging_leads_endpoint(
    datos: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Consulta e importa contactos desde Zoho CRM al buzón de matching."""
    caller = _get_current_user(authorization, x_session_token)
    t_req = datos.get("tenant_id") if datos else None
    tenants = _resolve_permitted_tenants(caller, t_req)
    target_tenant = tenants[0]
    max_rec = datos.get("max_registros", 50) if datos else 50
    return matching_engine.import_from_zoho_to_staging(tenant_id=target_tenant, max_records=max_rec)

@app.post("/api/matching/leads/{staging_id}/buscar")
def search_candidate_staging_endpoint(
    staging_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Dispara la búsqueda de perfiles coincidentes en LinkedIn para un prospecto."""
    caller = _get_current_user(authorization, x_session_token)
    return matching_engine.search_candidate_for_staging_lead(staging_id)

@app.post("/api/matching/leads/{staging_id}/confirmar")
def confirm_staging_lead_endpoint(
    staging_id: str,
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Valida y promueve un prospecto del staging al Directorio oficial o a una lista."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id"))
    target_tenant = tenants[0]
    try:
        return matching_engine.confirm_and_promote_staging_lead(
            staging_id=staging_id,
            target_list_id=datos.get("lista_id"),
            custom_url=datos.get("perfil_url"),
            custom_nombre=datos.get("nombre"),
            custom_cargo=datos.get("cargo_actual"),
            custom_institucion=datos.get("institucion_actual"),
            tenant_id=target_tenant
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/matching/leads/{staging_id}/descartar")
def discard_staging_lead_endpoint(
    staging_id: str,
    datos: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Marca como descartado un prospecto de staging."""
    caller = _get_current_user(authorization, x_session_token)
    motivo = (datos.get("motivo") or "") if datos else ""
    res = matching_engine.discard_staging_lead(staging_id, motivo=motivo)
    return {"ok": res, "staging_id": staging_id}

@app.delete("/api/matching/leads/{staging_id}")
def delete_staging_lead_endpoint(
    staging_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Elimina definitivamente un prospecto del buzón de staging."""
    caller = _get_current_user(authorization, x_session_token)
    res = matching_engine.delete_staging_lead(staging_id)
    return {"ok": res, "staging_id": staging_id}

# ==========================================
# ACTIVITY LOGS & AUDIT
# ==========================================
@app.get("/api/logs")
def get_logs_endpoint(
    limit: int = Query(150, description="Cantidad máxima de eventos a retornar"),
    module: Optional[str] = Query(None, description="Filtro por módulo: EXTRACTOR, SEQUENCES, BROWSER, SAFETY, etc."),
    level: Optional[str] = Query(None, description="Filtro por nivel: INFO, SUCCESS, WARNING, ERROR"),
    search: Optional[str] = Query(None, description="Término de búsqueda de texto"),
    since_id: Optional[int] = Query(None, description="Filtrar eventos con ID superior a este"),
    tenant_id: Optional[str] = Query(None, description="Filtrar logs por tenant autorizado"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna los registros de actividad cronológicos del sistema con opciones de filtrado."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    if caller.get("rol") == "SUPER_ADMIN" and not tenant_id:
        import logger_service
        logs = logger_service.get_logs(limit=limit, module=module, level=level, search=search, since_id=since_id)
        return {"logs": logs, "total": len(logs)}

    placeholders = ", ".join(["?"] * len(tenants))
    with get_db() as conn:
        cursor = conn.cursor()
        query = f"SELECT * FROM system_logs WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN ({placeholders}))"
        params: List[Any] = list(tenants)
        if module and module != "ALL":
            query += " AND module = ?"
            params.append(module.upper())
        if level and level != "ALL":
            query += " AND level = ?"
            params.append(level.upper())
        if since_id is not None:
            query += " AND id > ?"
            params.append(since_id)
        if search:
            query += " AND (message LIKE ? OR details_json LIKE ?)"
            q = f"%{search}%"
            params.extend([q, q])
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
        logs = []
        for r in rows:
            item = dict(r)
            try:
                item["details"] = json.loads(item.get("details_json") or "{}")
            except Exception:
                item["details"] = {}
            logs.append(item)
        return {"logs": logs, "total": len(logs)}

@app.get("/api/logs/stats")
def get_log_stats_endpoint(
    tenant_id: Optional[str] = Query(None, description="Filtrar estadísticas de logs por tenant autorizado"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna estadísticas agregadas de los registros y eventos del sistema."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    if caller.get("rol") == "SUPER_ADMIN" and not tenant_id:
        import logger_service
        return logger_service.get_log_stats()

    placeholders = ", ".join(["?"] * len(tenants))
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT level, COUNT(*) as count FROM system_logs WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN ({placeholders})) GROUP BY level",
            list(tenants)
        )
        by_level = {r["level"]: r["count"] for r in cursor.fetchall()}
        cursor.execute(
            f"SELECT module, COUNT(*) as count FROM system_logs WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN ({placeholders})) GROUP BY module",
            list(tenants)
        )
        by_module = {r["module"]: r["count"] for r in cursor.fetchall()}
        cursor.execute(
            f"SELECT COUNT(*) as total FROM system_logs WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN ({placeholders}))",
            list(tenants)
        )
        total = cursor.fetchone()["total"]
        return {
            "total": total,
            "por_nivel": by_level,
            "por_modulo": by_module
        }

@app.delete("/api/logs")
def clear_logs_endpoint(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Limpia y vacía el historial global de registros de auditoría y actividades (Solo SUPER_ADMIN)."""
    caller = _get_current_user(authorization, x_session_token)
    _require_super_admin(caller)
    import logger_service
    logger_service.clear_logs()
    return {"status": "ok", "message": "Logs eliminados correctamente"}

def _extract_raw_session_token(
    authorization: Optional[str] = None,
    x_session_token: Optional[str] = None
) -> Optional[str]:
    token = x_session_token
    if not token and authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()
    return token or None

# ==========================================
# LOCAL RUNNER CONTRACT (HYBRID ARCHITECTURE)
# ==========================================
@app.get("/api/worker/estado")
def get_worker_dispatcher_status(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna el estado del despachador y el estado en tiempo real del bucle ejecutor en Electron."""
    import browser_service
    resolved_tenant = None
    if authorization or x_session_token or tenant_id:
        caller = _get_current_user(authorization, x_session_token)
        tenants = _resolve_permitted_tenants(caller, tenant_id)
        resolved_tenant = tenant_id if (tenant_id and tenant_id in tenants) else caller.get("tenant_id")

    electron_worker = browser_service.get_electron_worker_status()
    runner_data = electron_worker.get("status", {})
    is_active = bool(runner_data.get("activo", False))
    estado_runner = runner_data.get("estado_actual", "En reposo" if not is_active else "Consultando...")
    
    return {
        "piloto_automatico": is_active,
        "estado_actual": estado_runner,
        "secuencias_activas": task_dispatcher.get_autopilot_status(tenant_id=resolved_tenant),
        "status": "online",
        "fase": runner_data.get("fase", "activo" if is_active else "reposo"),
        "accion_actual": runner_data.get("accion_actual", estado_runner),
        "detalle_accion": runner_data.get("detalle_accion", ""),
        "prospecto_actual": runner_data.get("prospecto_actual"),
        "institucion_actual": runner_data.get("institucion_actual"),
        "tipo_accion": runner_data.get("tipo_accion"),
        "canal": runner_data.get("canal"),
        "cuenta_regresiva_hasta": runner_data.get("cuenta_regresiva_hasta"),
        "segundos_totales": runner_data.get("segundos_totales"),
        "segundos_restantes": runner_data.get("segundos_restantes"),
        "pausa_inicio_ts": runner_data.get("pausa_inicio_ts"),
        "ultima_accion": runner_data.get("ultima_accion"),
        "requiere_autenticacion": bool(runner_data.get("requiere_autenticacion", False)),
        "error_autorizacion": bool(runner_data.get("error_autorizacion", False)),
        "dispositivo_revocado": bool(runner_data.get("dispositivo_revocado", False)),
        "tenant_id": runner_data.get("tenant_id") or resolved_tenant
    }

@app.post("/api/worker/forzar-siguiente")
def force_worker_next_cycle(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Fuerza al bucle ejecutor en Electron a saltarse la pausa actual y procesar la siguiente tarea de inmediato."""
    import browser_service
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenant_id if (tenant_id and tenant_id in tenants) else caller.get("tenant_id")
    raw_token = _extract_raw_session_token(authorization, x_session_token)

    res = browser_service.force_electron_worker_next(session_token=raw_token, tenant_id=resolved_tenant)
    return {"status": "ok", "tenant_id": resolved_tenant, "resultado": res}

@app.post("/api/worker/piloto-automatico/toggle")
def toggle_autopilot(
    activo: Optional[bool] = Query(None),
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Activa o pausa el piloto automático de campañas y notifica al ejecutor de escritorio con el contexto autenticado."""
    import browser_service
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenant_id if (tenant_id and tenant_id in tenants) else caller.get("tenant_id")
    raw_token = _extract_raw_session_token(authorization, x_session_token)

    curr_status = browser_service.get_electron_worker_status()
    currently_active = bool(curr_status.get("status", {}).get("activo", False))
    target_active = not currently_active if activo is None else bool(activo)
    
    if target_active:
        res = browser_service.start_electron_worker(session_token=raw_token, tenant_id=resolved_tenant)
    else:
        res = browser_service.stop_electron_worker()
        
    return {
        "status": "ok",
        "piloto_automatico": target_active,
        "tenant_id": resolved_tenant,
        "detalle": res,
        "mensaje": "Piloto automático activado" if target_active else "Piloto automático en pausa"
    }

@app.post("/api/worker/heartbeat")
def worker_heartbeat(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Recibe el latido periódico de sincronización desde el ejecutor de escritorio Electron."""
    resolved_tenant = None
    if authorization or x_session_token:
        caller = _get_current_user(authorization, x_session_token)
        tenants = _resolve_permitted_tenants(caller, datos.get("tenant_id") if isinstance(datos, dict) else None)
        resolved_tenant = tenants[0]
    return {
        "ok": True,
        "servidor_tiempo": datetime.now().isoformat(),
        "piloto_automatico": task_dispatcher.get_autopilot_status(tenant_id=resolved_tenant)
    }

class DeviceRegisterRequest(BaseModel):
    device_id: str
    tenant_id: Optional[str] = None
    public_key_ed25519: str
    device_name: Optional[str] = None
    client_version: Optional[str] = "1.3.0"

class DeviceRevokeRequest(BaseModel):
    device_id: str
    tenant_id: Optional[str] = None

@app.post("/api/devices/register")
def register_device_endpoint(
    req: DeviceRegisterRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Registra y empareja un dispositivo con su clave pública Ed25519 (Workstream 5.1)."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, req.tenant_id)
    tenant_id = tenants[0]
    user_id = caller.get("id") if caller else None
    try:
        res = command_signing_service.register_device(
            device_id=req.device_id,
            tenant_id=tenant_id,
            public_key_ed25519=req.public_key_ed25519,
            device_name=req.device_name,
            client_version=req.client_version,
            user_id=user_id
        )
        return res
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/devices/revoke")
def revoke_device_endpoint(
    req: DeviceRevokeRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Revoca un dispositivo impidiendo que ejecute o reporte comandos (Kill-Switch)."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _require_tenant_admin(caller, req.tenant_id)
    tenant_id = tenants[0]
    success = command_signing_service.revoke_device(req.device_id, tenant_id)
    return {"ok": success, "device_id": req.device_id, "status": "REVOKED"}

@app.get("/api/devices/list")
def list_devices_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista los dispositivos emparejados del tenant."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, tenant_id, device_name, status, client_version, last_seen_at, created_at FROM devices WHERE tenant_id = ? ORDER BY created_at DESC", (target_tenant,))
        devices = cursor.fetchall()
        return {"ok": True, "devices": devices}

@app.get("/api/devices/server-public-key")
def get_server_public_key_endpoint():
    """Retorna la clave pública Ed25519 del servidor para fijación (pinning) en clientes."""
    return {
        "ok": True,
        "algorithm": "Ed25519",
        "public_key_b64": command_signing_service.get_server_public_key_b64()
    }

@app.get("/api/worker/proxima-tarea")
def get_worker_next_task(
    tenant_id: Optional[str] = Query(None, description="Filtrar por tenant específico"),
    secuencia_id: Optional[str] = Query(None, description="Filtrar por secuencia específica"),
    device_id: Optional[str] = Query(None, description="Identificador del dispositivo cliente"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Entrega la siguiente tarea pendiente autorizada con comando firmado con Ed25519 al ejecutor de escritorio."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenant_id if (tenant_id and tenant_id in tenants) else caller.get("tenant_id")

    if secuencia_id:
        sec = _authorize_sequence_access(caller, secuencia_id)
        if tenant_id and sec["tenant_id"] != tenant_id:
            raise HTTPException(status_code=403, detail="La secuencia no pertenece al tenant solicitado.")
        resolved_tenant = sec["tenant_id"]

    target_device = (device_id or x_device_id or "").strip() or None
    if target_device:
        is_active, dev_reason, _ = command_signing_service.is_device_active(target_device, resolved_tenant)
        if not is_active:
            raise HTTPException(
                status_code=403,
                detail=f"Dispositivo no autorizado o revocado para este tenant ({dev_reason})."
            )

    return task_dispatcher.get_next_dispatched_task(
        tenant_id=resolved_tenant,
        sequence_id=secuencia_id,
        device_id=target_device
    )

@app.post("/api/worker/reportar-resultado")
def report_task_result(
    datos: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Procesa el reporte de finalización de una tarea ejecutada por el runner local, verificando su firma y asignación."""
    if not isinstance(datos, dict):
        raise HTTPException(status_code=400, detail="Payload de reporte inválido.")

    authenticated_tenant_id = None
    permitted_tenants = None
    if authorization or x_session_token:
        caller = _get_current_user(authorization, x_session_token)
        if not caller:
            raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
        req_tenant = datos.get("tenant_id")
        permitted_tenants = _resolve_permitted_tenants(caller, req_tenant)
        if req_tenant:
            authenticated_tenant_id = req_tenant
        elif caller.get("role") != "SUPER_ADMIN" and len(permitted_tenants) == 1:
            authenticated_tenant_id = permitted_tenants[0]
    else:
        task_id = (datos.get("command_id") or datos.get("tarea_id") or "").strip()
        device_id = (datos.get("device_id") or "").strip()
        device_sig = (datos.get("device_signature") or "").strip()
        if not task_id or not device_id or not device_sig:
            raise HTTPException(
                status_code=401,
                detail="Se requiere sesión autenticada o firma criptográfica Ed25519 del dispositivo asignado."
            )

    res = task_dispatcher.process_executed_task_report(
        datos,
        authenticated_tenant_id=authenticated_tenant_id,
        permitted_tenants=permitted_tenants
    )
    if not res.get("ok", True) and res.get("http_status"):
        raise HTTPException(status_code=res["http_status"], detail=res.get("error", "Error procesando reporte de tarea."))
    return res


# ==============================================================================
# COLA CENTRALIZADA DE TAREAS Y POLÍTICAS DE RITMO ANTIBAN (TASK-QUEUE-04)
# ==============================================================================

class EnqueueBatchRequest(BaseModel):
    tipo_tarea: str
    lead_ids: List[str]
    payload: Optional[Dict[str, Any]] = None
    prioridad: Optional[int] = 5

class UpdatePolicyRequest(BaseModel):
    limite_diario: Optional[int] = None
    pausa_min_seg: Optional[int] = None
    pausa_max_seg: Optional[int] = None
    activo: Optional[bool] = None

class CancelTasksRequest(BaseModel):
    task_ids: Optional[List[str]] = None

@app.get("/api/cola-tareas/estado")
def get_queue_status_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna métricas ejecutivas de la cola persistente para el tenant activo."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    return task_queue_service.get_queue_summary(target_tenant)

@app.get("/api/cola-tareas/politicas")
def get_queue_policies_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna las políticas de ritmo y límites diarios de cada acción para el tenant."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    policies = task_queue_service.get_tenant_policies(target_tenant)
    return {"ok": True, "politicas": policies}

@app.put("/api/cola-tareas/politicas/{tipo_tarea}")
def update_queue_policy_endpoint(
    tipo_tarea: str,
    req: UpdatePolicyRequest,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza los límites diarios y pausas mínimas/máximas de una acción en el tenant."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    try:
        updated = task_queue_service.update_tenant_policy(
            target_tenant,
            tipo_tarea=tipo_tarea,
            limite_diario=req.limite_diario,
            pausa_min_seg=req.pausa_min_seg,
            pausa_max_seg=req.pausa_max_seg,
            activo=req.activo
        )
        return {"ok": True, "politica": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/cola-tareas/politicas/restaurar")
def reset_queue_policies_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Restaura las políticas de ritmo a los valores recomendados antiban (50 inv/día)."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    restored = task_queue_service.reset_tenant_policies_to_recommended(target_tenant)
    return {"ok": True, "politicas": restored}

@app.post("/api/cola-tareas/encolar")
def enqueue_tasks_endpoint(
    req: EnqueueBatchRequest,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Encola un lote de acciones para prospectos en PostgreSQL con cálculo de jitter estocástico."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    try:
        res = task_queue_service.enqueue_batch_actions(
            target_tenant,
            tipo_tarea=req.tipo_tarea,
            lead_ids=req.lead_ids,
            payload=req.payload,
            prioridad=req.prioridad or 5
        )
        return {"ok": True, **res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/cola-tareas/cancelar")
def cancel_queue_tasks_endpoint(
    req: Optional[CancelTasksRequest] = None,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Cancela tareas pendientes en la cola central de PostgreSQL."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    ids = req.task_ids if req else None
    count = task_queue_service.cancel_pending_tasks(target_tenant, task_ids=ids)
    return {"ok": True, "canceladas": count}

@app.get("/api/cola-tareas/items")
def get_queue_items_endpoint(
    tenant_id: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Lista las tareas de la cola central paginadas para inspección."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    target_tenant = tenants[0]
    with get_db(tenant_id=target_tenant) as conn:
        cursor = conn.cursor()
        where_clauses = ["c.tenant_id = %s"]
        params = [target_tenant]
        if estado:
            where_clauses.append("c.estado = %s")
            params.append(estado)
        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"""
            SELECT c.*, l.nombre as lead_nombre, l.cargo_actual as lead_cargo, l.institucion_actual as lead_empresa
            FROM cola_tareas_central c
            LEFT JOIN leads l ON l.id = c.lead_id
            WHERE {where_sql}
            ORDER BY c.programado_para ASC, c.prioridad ASC
            LIMIT %s OFFSET %s;
        """, params + [limit, offset])
        items = [dict(r) for r in cursor.fetchall()]
        return {"ok": True, "items": items}



# ==============================================================================
# ZOHO BRIDGE TRANSITORIO, DEDUPLICACIÓN Y EXPORTACIÓN CSV (WORKSTREAM 5.2)
# ==============================================================================

@app.get("/api/tenants/{tenant_id}/export-csv")
def export_leads_csv_endpoint(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Exportación CSV nativa y trazable de los leads del tenant con su bitácora cronológica."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado para exportar datos de este tenant.")
    
    csv_content = zoho_bridge_service.export_leads_with_activity_csv(tenant_id)
    filename = f"nexusreach_leads_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )

@app.get("/api/tenants/{tenant_id}/zoho-config")
def get_zoho_config_endpoint(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna la configuración y feature flag de Zoho para el tenant."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado.")
    return zoho_bridge_service.get_zoho_config(tenant_id)

class ZohoConfigUpdate(BaseModel):
    zoho_sync_activo: bool
    zoho_org_id: Optional[str] = None

@app.post("/api/tenants/{tenant_id}/zoho-config")
def update_zoho_config_endpoint(
    tenant_id: str,
    body: ZohoConfigUpdate,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Actualiza la activación de Zoho Bridge y su Org ID dinámico para el tenant."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _require_tenant_admin(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado para modificar la configuración.")
    
    zoho_bridge_service.set_zoho_config(tenant_id, body.zoho_sync_activo, body.zoho_org_id)
    return {"ok": True, "tenant_id": tenant_id, "zoho_sync_activo": body.zoho_sync_activo, "zoho_org_id": body.zoho_org_id}

class SuppressionRequest(BaseModel):
    identifier: str
    identifier_type: str  # 'EMAIL', 'PHONE', 'LINKEDIN_URL'
    reason: Optional[str] = "OPT_OUT"

@app.post("/api/tenants/{tenant_id}/suppression")
def add_suppression_endpoint(
    tenant_id: str,
    body: SuppressionRequest,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Registra un identificador en la lista de supresión (Opt-out) con hash SHA-256."""
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado.")
    
    success = zoho_bridge_service.add_to_suppression_list(
        tenant_id=tenant_id,
        identifier=body.identifier,
        identifier_type=body.identifier_type,
        reason=body.reason or "OPT_OUT"
    )
    return {"ok": success, "tenant_id": tenant_id}

@app.get("/api/leads/{lead_id}/activities")
def get_lead_activities_endpoint(
    lead_id: str,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """Retorna la bitácora cronológica de actividades del lead (lead_activity)."""
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    lead = _authorize_lead_access(caller, lead_id)
    lead_tenant = lead.get("tenant_id")
    if tenant_id and lead_tenant not in tenants:
        raise HTTPException(status_code=403, detail="El prospecto no pertenece al workspace solicitado.")
    activities = zoho_bridge_service.get_lead_activities(lead_tenant, lead_id)
    return {"ok": True, "lead_id": lead_id, "activities": activities}


# ==============================================================================
# CUMPLIMIENTO DE DATOS PERSONALES, RETENCIÓN Y DERECHOS ARCO (WORKSTREAM 5.4 [P0])
# ==============================================================================

class OptOutRequest(BaseModel):
    tenant_id: str
    identifier: str
    identifier_type: str = "EMAIL"  # 'EMAIL', 'PHONE', 'LINKEDIN_URL'
    reason: Optional[str] = "SOLICITO_BAJA"

@app.post("/api/opt-out")
def opt_out_endpoint(req: OptOutRequest):
    """
    Endpoint de baja (Opt-out):
    Registra el identificador con hash SHA-256 en la lista de supresión,
    detiene secuencias en curso y marca al lead como 'OPT_OUT'.
    """
    res = privacy_compliance_service.process_opt_out(
        tenant_id=req.tenant_id,
        identifier=req.identifier,
        identifier_type=req.identifier_type,
        reason=req.reason or "SOLICITO_BAJA"
    )
    return res

@app.get("/api/tenants/{tenant_id}/leads/{lead_id}/export-subject-data")
def export_subject_data_endpoint(
    tenant_id: str,
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Derecho de Acceso (Ley 21.719 / ARCO):
    Exporta toda la información almacenada de un titular de datos.
    """
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado para acceder a este tenant.")

    profile = privacy_compliance_service.export_data_subject_profile(tenant_id, lead_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return profile

@app.delete("/api/tenants/{tenant_id}/leads/{lead_id}/data-subject-deletion")
def delete_subject_data_endpoint(
    tenant_id: str,
    lead_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Derecho al Olvido / Supresión (Ley 21.719):
    Elimina definitivamente los datos del lead y añade sus identificadores a la lista de supresión.
    """
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _resolve_permitted_tenants(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado para modificar datos de este tenant.")

    success = privacy_compliance_service.delete_data_subject_profile(tenant_id, lead_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"ok": True, "lead_id": lead_id, "status": "DELETED_AND_SUPPRESSED"}

@app.post("/api/tenants/{tenant_id}/purge-inactive-leads")
def purge_inactive_leads_endpoint(
    tenant_id: str,
    months: int = Query(12, ge=1, le=60),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Retención Configurable:
    Purga automáticamente los leads que no han tenido actividad en los últimos N meses (por defecto 12 meses).
    """
    caller = _get_current_user(authorization, x_session_token)
    resolved_tenants = _require_tenant_admin(caller, tenant_id)
    if tenant_id not in resolved_tenants:
        raise HTTPException(status_code=403, detail="No autorizado.")

    purged = privacy_compliance_service.purge_inactive_leads(tenant_id, months=months)
    return {"ok": True, "tenant_id": tenant_id, "leads_purged": purged, "months_threshold": months}

@app.delete("/api/tenants/{tenant_id}/cascade-deletion")
def delete_tenant_cascade_endpoint(
    tenant_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Borrado Completo de Tenant en Cascada (<= 30 días tras cancelación):
    Elimina todas las filas dependientes en todas las tablas del sistema.
    Requiere rol SUPER_ADMIN o COMPANY_ADMIN del propio tenant.
    """
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    is_super = caller.get("rol") == "SUPER_ADMIN"
    is_owner = caller.get("tenant_id") == tenant_id and caller.get("rol") in ("COMPANY_ADMIN", "AGENCY_ADMIN")
    if not (is_super or is_owner):
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requieren permisos administrativos de tenant.")

    counts = privacy_compliance_service.delete_tenant_cascade(tenant_id)
    return {"ok": True, "tenant_id": tenant_id, "deleted_entities": counts}


# ==============================================================================
# WORKSTREAM 5.5: ANTIBAN Y GESTIÓN DE SALUD DE CUENTAS
# ==============================================================================

class RiskSignalPayload(BaseModel):
    signal_type: str
    details: Optional[Dict[str, Any]] = None

@app.get("/api/accounts/{account_id}/health")
def get_account_health_endpoint(
    account_id: str,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Retorna los indicadores de salud antiban de una cuenta de LinkedIn (0 - 100),
    incluyendo tasa de aceptación, incidentes recientes y recomendación de límite.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]
    health = safety_engine.calculate_account_health(account_id, resolved_tenant)
    warmup = safety_engine.calculate_adaptive_warmup_limit(account_id, resolved_tenant)
    return {
        "ok": True,
        "account_id": account_id,
        "tenant_id": resolved_tenant,
        "health": health,
        "warmup": warmup
    }

@app.post("/api/accounts/{account_id}/risk-signal")
def report_risk_signal_endpoint(
    account_id: str,
    payload: RiskSignalPayload,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Registra una señal de riesgo (checkpoint, CAPTCHA, PIN, restricción) reportada
    por el runner local. Congela de inmediato la cola de la cuenta y evalúa si se
    debe activar el Kill-Switch global por anomalía múltiple (>= 3 cuentas en 24h).
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]
    result = safety_engine.report_risk_signal(
        account_id=account_id,
        tenant_id=resolved_tenant,
        signal_type=payload.signal_type,
        details=payload.details
    )
    return result

@app.post("/api/accounts/{account_id}/reactivate")
def reactivate_account_endpoint(
    account_id: str,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Reactivación manual de una cuenta congelada tras resolución humana.
    Reinicia el calentamiento al piso seguro de 15 invitaciones/día.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _require_tenant_admin(caller, tenant_id)
    resolved_tenant = tenants[0]
    result = safety_engine.reactivate_account(account_id, resolved_tenant)
    return result


# ==============================================================================
# WORKSTREAM 5.8: RESILIENCIA ANTE CAMBIOS DE INTERFAZ Y SELECTORES COMO DATOS
# ==============================================================================

class PublishSelectorCatalogPayload(BaseModel):
    version: str
    min_client_version: Optional[str] = "1.0.0"
    catalog: Dict[str, Any]
    signature: str


@app.get("/api/selectors/active")
def get_active_selectors_endpoint():
    """
    Retorna el catálogo activo de selectores firmado criptográficamente con Ed25519.
    El cliente descarga esta configuración para ejecutar acciones sin requerir actualización de binarios.
    """
    import selector_service
    pkg = selector_service.get_active_selector_catalog()
    return pkg


@app.post("/api/selectors/publish")
def publish_selectors_endpoint(
    payload: PublishSelectorCatalogPayload,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Publica una nueva versión de catálogo de selectores firmada.
    Verifica la firma Ed25519 antes de guardar y reactiva las acciones pausadas.
    Requiere permisos de Super Administrador.
    """
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN para publicar catálogos de selectores.")

    import selector_service
    try:
        pkg = {
            "version": payload.version,
            "min_client_version": payload.min_client_version,
            "catalog": payload.catalog,
            "signature": payload.signature
        }
        res = selector_service.publish_selector_catalog(pkg)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/selectors/status")
def get_selectors_status_endpoint():
    """
    Retorna el estado de salud y degradación de todas las acciones del sistema.
    Indica si alguna acción está pausada por rotura de interfaz.
    """
    import selector_service
    statuses = selector_service.get_all_actions_status()
    return {"ok": True, "actions": statuses}


@app.post("/api/selectors/canary-run")
def run_canary_audit_endpoint(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Ejecuta la suite completa de canarios para auditar la resiliencia de los selectores.
    """
    caller = _get_current_user(authorization, x_session_token)
    _require_super_admin(caller)
    import canary_service
    audit_report = canary_service.run_full_canary_suite()
    return {"ok": True, "report": audit_report}


# ==============================================================================
# WORKSTREAM 5.9: FACTURACIÓN, LÍMITES COMERCIALES, ENTITLEMENTS Y PASARELAS DE PAGO
# ==============================================================================

class SubscriptionCheckoutPayload(BaseModel):
    account_id: Optional[str] = None
    plan_type: Optional[str] = "MONTHLY"
    billing_country: Optional[str] = "CL"
    return_url: Optional[str] = "https://app.nexusreach.io/billing"


class PackCheckoutPayload(BaseModel):
    pack_type: str
    return_url: Optional[str] = "https://app.nexusreach.io/billing"


@app.get("/api/billing/subscription")
def get_billing_subscription_endpoint(
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Retorna el estado de la suscripción, límites de ciclo, consumo de leads y créditos,
    avisos tempranos al 80% y 100%, y procesador asignado (Mercado Pago para CL, PayPal para otros).
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]

    import entitlements_service
    import payment_gateway_service

    summary = entitlements_service.get_cycle_usage_summary(resolved_tenant)
    sub = entitlements_service.get_active_subscription(resolved_tenant)
    country = sub.get("billing_country", "CL") if sub else "CL"
    provider = payment_gateway_service.get_payment_provider(country)

    summary["provider"] = provider.provider_name
    summary["billing_country"] = country
    return summary


@app.post("/api/billing/checkout/subscription")
def create_subscription_checkout_endpoint(
    payload: SubscriptionCheckoutPayload,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Inicia la sesión de suscripción (15 USD/mo o 150 USD/yr con 2 meses gratis por cuenta).
    Dirige a Mercado Pago para clientes en Chile (CL) o PayPal para el resto del mundo.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]
    account_id = payload.account_id or f"li_acc_{resolved_tenant}"

    import payment_gateway_service
    provider = payment_gateway_service.get_payment_provider(payload.billing_country or "CL")
    checkout = provider.create_subscription_checkout(
        tenant_id=resolved_tenant,
        account_id=account_id,
        plan_type=payload.plan_type or "MONTHLY",
        billing_country=payload.billing_country or "CL",
        return_url=payload.return_url or "https://app.nexusreach.io/billing"
    )
    return checkout


@app.post("/api/billing/checkout/pack")
def create_pack_checkout_endpoint(
    payload: PackCheckoutPayload,
    tenant_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Inicia la compra de un pack adicional:
    - LEADS_500: +500 leads para el ciclo en curso por 5 USD
    - CREDITS_100: 100 créditos de correo por 6 USD (sin vencimiento)
    - CREDITS_500: 500 créditos de correo por 28 USD (sin vencimiento)
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]

    import entitlements_service
    import payment_gateway_service

    sub = entitlements_service.get_active_subscription(resolved_tenant)
    country = sub.get("billing_country", "CL") if sub else "CL"
    provider = payment_gateway_service.get_payment_provider(country)

    checkout = provider.create_pack_checkout(
        tenant_id=resolved_tenant,
        pack_type=payload.pack_type,
        return_url=payload.return_url or "https://app.nexusreach.io/billing"
    )
    return checkout


@app.post("/api/billing/webhooks/{provider}")
async def payment_webhook_endpoint(
    provider: str,
    request: Request
):
    """
    Recepción segura e idempotente de webhooks de Mercado Pago y PayPal.
    Verifica firma criptográfica y previene doble acreditación de créditos o estados.
    """
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        payload = {}

    headers = dict(request.headers)

    import payment_gateway_service
    try:
        result = payment_gateway_service.handle_incoming_webhook(
            provider_name=provider,
            headers=headers,
            payload=payload,
            raw_body=raw_body
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==============================================================================
# WORKSTREAM 5.10 & 5.11: OBSERVABILIDAD, SOPORTE Y DISTRIBUCIÓN
# ==============================================================================

@app.get("/api/observability/metrics")
def get_observability_metrics_endpoint(
    tenant_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Retorna métricas de telemetría operativa: acciones ejecutadas, tasas de éxito,
    tasa de aceptación del embudo de LinkedIn, latencia de comandos e incidentes.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]
    import observability_service
    metrics = observability_service.get_telemetry_metrics(tenant_id=resolved_tenant, account_id=account_id)
    return {"ok": True, "metrics": metrics}


@app.get("/api/observability/team-alerts")
def get_team_alerts_endpoint(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Tablero interno del equipo de operaciones con alertas activas:
    - Picos de incidentes y cuentas en riesgo.
    - Acciones con tasa de fallo anómala (> 15%).
    - Acciones pausadas por rotura de interfaz.
    """
    caller = _get_current_user(authorization, x_session_token)
    if not caller:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if caller.get("rol") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere rol SUPER_ADMIN.")
    import observability_service
    alerts = observability_service.get_team_internal_dashboard_alerts()
    return alerts


@app.get("/api/support/diagnostics-bundle")
def get_support_diagnostics_bundle_endpoint(
    tenant_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token")
):
    """
    Genera el paquete de diagnóstico de soporte exportable por el usuario.
    Estrictamente sanitizado sin credenciales, tokens ni textos de mensajes privados.
    """
    caller = _get_current_user(authorization, x_session_token)
    tenants = _resolve_permitted_tenants(caller, tenant_id)
    resolved_tenant = tenants[0]
    import observability_service
    bundle = observability_service.generate_support_diagnostics_bundle(tenant_id=resolved_tenant, account_id=account_id)
    return {"ok": True, "bundle": bundle}


@app.get("/api/system/version")
def get_system_version_endpoint():
    """
    Retorna la versión actual del servidor, la versión mínima soportada del cliente
    y la URL oficial de descargas.
    """
    import observability_service
    return {
        "ok": True,
        "server_version": observability_service.CURRENT_SERVER_VERSION,
        "min_client_version_required": observability_service.MIN_CLIENT_VERSION,
        "download_url": "https://releases.nexusreach.io/desktop/"
    }




