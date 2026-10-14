import os
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import urllib.request
import urllib.error
from database import get_db

# ==============================================================================
# MOTOR DE AUTENTICACIÓN, TENANTS Y SUSCRIPCIONES (NexusReach Pro)
# ==============================================================================

# In-memory active sessions store:
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESIONES_ACTIVAS = ACTIVE_SESSIONS

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Genera hash seguro PBKDF2 con salt criptográfico de 16 bytes."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    )
    return dk.hex(), salt

def verify_password(password: str, salt: str, password_hash: str) -> bool:
    """Valida una contraseña contra su hash y salt guardados."""
    dk, _ = hash_password(password, salt)
    return secrets.compare_digest(dk, password_hash)

# ==============================================================================
# SEMBRADO INICIAL DEL ECOSISTEMA MULTI-TENANT (Fase 1)
# ==============================================================================

def _seed_ecosystem(cursor):
    """Inicializa la base de datos con un ecosistema completo para pruebas inmediatas."""
    cursor.execute("SELECT COUNT(*) as total FROM tenants")
    row = cursor.fetchone()
    total_tenants = row["total"] if isinstance(row, dict) else row[0]
    
    if total_tenants > 0:
        return

    ahora = datetime.now()
    ahora_iso = ahora.isoformat()
    un_mes_iso = (ahora + timedelta(days=30)).isoformat()
    un_ano_iso = (ahora + timedelta(days=365)).isoformat()
    dos_anos_iso = (ahora + timedelta(days=730)).isoformat()

    # --------------------------------------------------------------------------
    # 1. TENANT PLATAFORMA / SUPER ADMIN (Gabriel)
    # --------------------------------------------------------------------------
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
        VALUES (?, NULL, ?, 'EMPRESA', 'ACTIVO', ?, ?)
    """, ("ten_superadmin", "NexusReach Core", ahora_iso, ahora_iso))

    cursor.execute("""
        INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
        VALUES (?, 'ten_superadmin', 'ANUAL', 'ACTIVA', 999, 0.0, ?, ?, ?, ?)
    """, ("sub_superadmin", ahora_iso, dos_anos_iso, ahora_iso, ahora_iso))

    p_admin_hash, admin_salt = hash_password("admin123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_superadmin', ?, ?, ?, ?, 'SUPER_ADMIN', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_superadmin", "admin@nexusreach.com", "Gabriel (Super Admin)", p_admin_hash, admin_salt, dos_anos_iso, ahora_iso, ahora_iso))

    # --------------------------------------------------------------------------
    # 2. TENANT EMPRESA CORPORATIVA DIRECTA (TechCorp)
    # --------------------------------------------------------------------------
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
        VALUES (?, NULL, ?, 'EMPRESA', 'ACTIVO', ?, ?)
    """, ("ten_techcorp", "TechCorp Inmobiliaria", ahora_iso, ahora_iso))

    cursor.execute("""
        INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
        VALUES (?, 'ten_techcorp', 'ANUAL', 'ACTIVA', 3, 29.0, ?, ?, ?, ?)
    """, ("sub_techcorp", ahora_iso, un_ano_iso, ahora_iso, ahora_iso))

    p_tech_adm, s_tech_adm = hash_password("tech123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_techcorp', ?, ?, ?, ?, 'COMPANY_ADMIN', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_tech_adm", "admin@techcorp.com", "Gerente TechCorp", p_tech_adm, s_tech_adm, un_ano_iso, ahora_iso, ahora_iso))

    p_tech_vend, s_tech_vend = hash_password("vend123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_techcorp', ?, ?, ?, ?, 'COMPANY_MEMBER', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_tech_vend", "vendedor@techcorp.com", "Vendedor TechCorp", p_tech_vend, s_tech_vend, un_ano_iso, ahora_iso, ahora_iso))

    # --------------------------------------------------------------------------
    # 3. TENANT MATRIZ AGENCIA (GrowthX Media)
    # --------------------------------------------------------------------------
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
        VALUES (?, NULL, ?, 'AGENCIA', 'ACTIVO', ?, ?)
    """, ("ten_growthx", "Agencia GrowthX Media", ahora_iso, ahora_iso))

    cursor.execute("""
        INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
        VALUES (?, 'ten_growthx', 'MENSUAL', 'ACTIVA', 5, 35.0, ?, ?, ?, ?)
    """, ("sub_growthx", ahora_iso, un_mes_iso, ahora_iso, ahora_iso))

    p_growth, s_growth = hash_password("growth123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_growthx', ?, ?, ?, ?, 'AGENCY_ADMIN', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_growth_adm", "agencia@growthx.com", "Director GrowthX", p_growth, s_growth, un_mes_iso, ahora_iso, ahora_iso))

    # Sub-Tenant 3A: Cliente Colegio San Agustín (Cobro Por Reunión: $150 c/u)
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, modelo_cobro_cliente, tarifa_por_reunion, puestos_asignados, created_at, updated_at)
        VALUES (?, 'ten_growthx', ?, 'CLIENTE_AGENCIA', 'ACTIVO', 'POR_REUNION', 150.0, 1, ?, ?)
    """, ("ten_sanagustin", "Colegio San Agustín", ahora_iso, ahora_iso))

    p_san, s_san = hash_password("san123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_sanagustin', ?, ?, ?, ?, 'COMPANY_MEMBER', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_san_dir", "director@sanagustin.cl", "Rector San Agustín", p_san, s_san, un_mes_iso, ahora_iso, ahora_iso))

    # Sub-Tenant 3B: Cliente Fintech Soluciones (Cobro Por Puesto: $75/puesto)
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, modelo_cobro_cliente, precio_cliente_por_puesto, puestos_asignados, created_at, updated_at)
        VALUES (?, 'ten_growthx', ?, 'CLIENTE_AGENCIA', 'ACTIVO', 'POR_PUESTO', 75.0, 1, ?, ?)
    """, ("ten_fintech", "Fintech Soluciones SpA", ahora_iso, ahora_iso))

    p_fin, s_fin = hash_password("fin123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_fintech', ?, ?, ?, ?, 'COMPANY_MEMBER', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_fin_sales", "sales@fintech.com", "Account Exec Fintech", p_fin, s_fin, un_mes_iso, ahora_iso, ahora_iso))

    # --------------------------------------------------------------------------
    # 4. TENANT FREELANCE MONOUSUARIO (Consultor Independiente)
    # --------------------------------------------------------------------------
    cursor.execute("""
        INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
        VALUES (?, NULL, ?, 'INDIVIDUAL', 'ACTIVO', ?, ?)
    """, ("ten_freelance", "Consultor Growth Independiente", ahora_iso, ahora_iso))

    cursor.execute("""
        INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
        VALUES (?, 'ten_freelance', 'MENSUAL', 'ACTIVA', 1, 35.0, ?, ?, ?, ?)
    """, ("sub_freelance", ahora_iso, un_mes_iso, ahora_iso, ahora_iso))

    p_demo, s_demo = hash_password("demo123")
    cursor.execute("""
        INSERT OR REPLACE INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
        VALUES (?, 'ten_freelance', ?, ?, ?, ?, 'INDIVIDUAL', 1, 'ACTIVO', ?, ?, ?)
    """, ("usr_demo", "demo@nexusreach.com", "Usuario Demo Freelance", p_demo, s_demo, un_mes_iso, ahora_iso, ahora_iso))

    print("🏛️ [Multi-Tenant Core] Ecosistema completo inicializado (Super Admin, Empresa Directa, Agencia con Sub-Clientes y Freelancer).")

def seed_multitenant_ecosystem_if_empty(cursor=None, conn=None):
    """Punto de entrada seguro para sembrado sin provocar bloqueos de SQLite."""
    if cursor is not None:
        _seed_ecosystem(cursor)
    elif conn is not None:
        _seed_ecosystem(conn.cursor())
    else:
        with get_db() as c:
            _seed_ecosystem(c.cursor())

# ==============================================================================
# CONSULTAS Y UTILIDADES DE DOMINIO
# ==============================================================================

def calculate_days_remaining(expires_iso: str) -> int:
    """Calculates remaining subscription days."""
    try:
        expires_dt = datetime.fromisoformat(expires_iso)
        delta = expires_dt - datetime.now()
        return max(0, delta.days)
    except Exception:
        return 0

def get_user_by_email(email: str, conn=None) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM usuarios WHERE LOWER(email) = LOWER(?)"
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (email.strip(),))
        return cursor.fetchone()
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (email.strip(),))
        return cursor.fetchone()

def get_user_by_id(user_id: str, conn=None) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM usuarios WHERE id = ?"
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (user_id,))
        return cursor.fetchone()
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (user_id,))
        return cursor.fetchone()

def get_tenant_by_id(tenant_id: str, conn=None) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM tenants WHERE id = ?"
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (tenant_id,))
        return cursor.fetchone()
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (tenant_id,))
        return cursor.fetchone()

def get_subscription_by_tenant(tenant_id: str, conn=None) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM suscripciones WHERE tenant_id = ?"
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (tenant_id,))
        return cursor.fetchone()
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (tenant_id,))
        return cursor.fetchone()

def count_occupied_seats_tenant(tenant_id: str, conn=None) -> int:
    """Calculates how many active seats are occupied by a tenant or agency with its clients."""
    query = """
        SELECT COUNT(*) as total 
        FROM usuarios 
        WHERE puesto_activo = 1 
          AND estado = 'ACTIVO'
          AND (tenant_id = ? OR tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = ?))
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (tenant_id, tenant_id))
        row = cursor.fetchone()
        return row["total"] if isinstance(row, dict) else row[0]
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (tenant_id, tenant_id))
        row = cursor.fetchone()
        return row["total"] if isinstance(row, dict) else row[0]

# ==============================================================================
# MOTOR DE AUTENTICACIÓN Y VALIDACIÓN MULTI-TENANT
# ==============================================================================

def authenticate_user(email: str, password: str, remote_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Autentica al usuario y valida rigurosamente su tenant, puesto y suscripción (anual/mensual).
    """
    if not email or not password:
        return {
            "exito": False,
            "codigo": "CAMPOS_REQUERIDOS",
            "mensaje": "Por favor ingresa tanto tu correo electrónico como tu contraseña."
        }

    user = get_user_by_email(email)
    if not user:
        return {
            "exito": False,
            "codigo": "USUARIO_NO_ENCONTRADO",
            "mensaje": "No existe una cuenta registrada con este correo electrónico."
        }

    # 1. Validar contraseña
    if not verify_password(password, user["salt"], user["password_hash"]):
        return {
            "exito": False,
            "codigo": "PASSWORD_INCORRECTO",
            "mensaje": "La contraseña ingresada no es correcta."
        }

    # 2. Validar estado de la cuenta
    if user.get("estado") == "BLOQUEADO":
        return {
            "exito": False,
            "codigo": "USUARIO_BLOQUEADO",
            "mensaje": "Tu usuario ha sido bloqueado preventivamente por administración."
        }

    if user.get("puesto_activo", 1) == 0:
        return {
            "exito": False,
            "codigo": "PUESTO_REVOCADO",
            "mensaje": "Tu puesto asignado en la organización ha sido revocado. Contacta a tu administrador."
        }

    # 3. Validar Tenant y Suscripción Asociada
    tenant_id = user.get("tenant_id")
    tenant = get_tenant_by_id(tenant_id) if tenant_id else None
    
    # El Super Admin siempre tiene acceso
    if user.get("rol") == "SUPER_ADMIN":
        pass
    elif tenant:
        if tenant.get("estado") != "ACTIVO":
            return {
                "exito": False,
                "codigo": "TENANT_SUSPENDIDO",
                "mensaje": f"La organización '{tenant.get('razon_social')}' se encuentra suspendida."
            }

        # Si es cliente de agencia, la suscripción que rige es la de la agencia matriz
        target_tenant_id = tenant.get("parent_tenant_id") or tenant["id"]
        subscription = get_subscription_by_tenant(target_tenant_id)

        if not subscription:
            return {
                "exito": False,
                "codigo": "SIN_SUSCRIPCION",
                "mensaje": "No se encontró una suscripción válida vinculada a esta organización."
            }

        if subscription.get("estado") == "REVOCADA":
            return {
                "exito": False,
                "codigo": "SUSCRIPCION_REVOCADA",
                "mensaje": "La licencia de tu organización ha sido revocada por el administrador de la plataforma."
            }

        # Verificar vencimiento
        expires_str = subscription.get("fecha_expiracion")
        if expires_str:
            try:
                expires_dt = datetime.fromisoformat(expires_str)
                if expires_dt < datetime.now():
                    with get_db() as c:
                        c.cursor().execute("UPDATE suscripciones SET estado = 'VENCIDA' WHERE id = ?", (subscription["id"],))
                    return {
                        "exito": False,
                        "codigo": "SUSCRIPCION_VENCIDA",
                        "mensaje": f"La suscripción de tu organización expiró el {expires_dt.strftime('%d/%m/%Y')}. Por favor renuévala para continuar."
                    }
            except Exception:
                pass

        if subscription.get("estado") not in ["ACTIVA", "EN_PRUEBA"]:
            return {
                "exito": False,
                "codigo": "SUSCRIPCION_INACTIVA",
                "mensaje": f"El estado de la suscripción es '{subscription.get('estado')}'. No tienes acceso a la plataforma."
            }
    else:
        return {
            "exito": False,
            "codigo": "SIN_ORGANIZACION",
            "mensaje": "Tu usuario no está vinculado a ninguna organización válida."
        }

    # 4. Generar Token de Sesión en Memoria (No persistido en disco)
    token = secrets.token_urlsafe(32)
    now_iso = datetime.now().isoformat()
    
    # Perfil seguro para enviar al cliente
    subscription_info = None
    if tenant:
        t_id_sub = tenant.get("parent_tenant_id") or tenant["id"]
        sub = get_subscription_by_tenant(t_id_sub) or {}
        subscription_info = {
            "estado": sub.get("estado", "ACTIVA"),
            "periodicidad": sub.get("periodicidad", "MENSUAL"),
            "puestos_contratados": sub.get("puestos_contratados", 1),
            "expira": sub.get("fecha_expiracion"),
            "dias_restantes": calculate_days_remaining(sub.get("fecha_expiracion", "")),
            "es_activa": True
        }

    profile = {
        "id": user["id"],
        "email": user["email"],
        "nombre": user["nombre"],
        "rol": user["rol"],
        "tenant_id": tenant_id,
        "tenant": {
            "id": tenant["id"] if tenant else None,
            "razon_social": tenant["razon_social"] if tenant else "NexusReach",
            "tipo_tenant": tenant["tipo_tenant"] if tenant else "EMPRESA",
            "parent_tenant_id": tenant.get("parent_tenant_id") if tenant else None,
            "modelo_cobro_cliente": tenant.get("modelo_cobro_cliente", "POR_PUESTO") if tenant else None,
            "tarifa_por_reunion": tenant.get("tarifa_por_reunion", 0.0) if tenant else 0.0,
            "precio_cliente_por_puesto": tenant.get("precio_cliente_por_puesto", 0.0) if tenant else 0.0,
            "fee_fijo_mensual": tenant.get("fee_fijo_mensual", 0.0) if tenant else 0.0,
        } if tenant else None,
        "suscripcion": subscription_info,
        "login_at": now_iso
    }

    ACTIVE_SESSIONS[token] = profile

    # Registrar último login y audit log
    with get_db() as c:
        c.cursor().execute("UPDATE usuarios SET ultimo_login = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, user["id"]))
        c.cursor().execute("""
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (?, ?, 'LOGIN_EXITOSO', ?, ?)
        """, (tenant_id, user["id"], json.dumps({"rol": user["rol"]}), now_iso))

    return {
        "exito": True,
        "token": token,
        "usuario": profile,
        "mensaje": f"¡Bienvenido, {user['nombre']}! Acceso autorizado como {user['rol']}."
    }

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida un token en memoria y revalida la vigencia de la suscripción."""
    if not token or token not in ACTIVE_SESSIONS:
        return None
    
    session_data = ACTIVE_SESSIONS[token]
    user = get_user_by_id(session_data["id"])
    if not user or user.get("estado") != "ACTIVO" or user.get("puesto_activo", 1) == 0:
        ACTIVE_SESSIONS.pop(token, None)
        return None

    if user.get("rol") != "SUPER_ADMIN":
        tenant = get_tenant_by_id(user.get("tenant_id"))
        if not tenant or tenant.get("estado") != "ACTIVO":
            ACTIVE_SESSIONS.pop(token, None)
            return None

        t_val_id = tenant.get("parent_tenant_id") or tenant["id"]
        sub = get_subscription_by_tenant(t_val_id)
        if not sub or sub.get("estado") not in ["ACTIVA", "EN_PRUEBA"]:
            ACTIVE_SESSIONS.pop(token, None)
            return None

        # Actualizar días restantes al vuelo
        days = calculate_days_remaining(sub.get("fecha_expiracion", ""))
        session_data["suscripcion"]["dias_restantes"] = days
        session_data["suscripcion"]["estado"] = sub.get("estado")

    return session_data

def logout_user(token: str) -> bool:
    """Elimina el token de la memoria."""
    if token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]
        return True
    return False

# ==============================================================================
# OPERACIONES DE GESTIÓN PARA SUPER ADMIN (Gabriel)
# ==============================================================================

def list_global_tenants(conn=None) -> List[Dict[str, Any]]:
    """Retorna todos los tenants con sus puestos, clientes y suscripción para el Super Admin."""
    query = """
        SELECT t.*, s.periodicidad, s.estado as sub_estado, s.puestos_contratados, 
               s.precio_unitario_plataforma, s.fecha_expiracion
        FROM tenants t
        LEFT JOIN suscripciones s ON s.tenant_id = t.id
        WHERE t.parent_tenant_id IS NULL
        ORDER BY t.created_at DESC
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
    else:
        with get_db() as c:
            cursor = c.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()

    res = []
    for r in rows:
        item = dict(r)
        item["puestos_ocupados"] = count_occupied_seats_tenant(item["id"], conn)
        item["dias_restantes"] = calculate_days_remaining(item.get("fecha_expiracion") or "")
        res.append(item)
    return res

def revoke_tenant_license(tenant_id: str, motivo: str = "Revocación por Super Admin") -> bool:
    """Revoca la licencia de un tenant e invalida de inmediato todas sus sesiones activas."""
    now_iso = datetime.now().isoformat()
    with get_db() as c:
        c.cursor().execute("UPDATE suscripciones SET estado = 'REVOCADA', updated_at = ? WHERE tenant_id = ?", (now_iso, tenant_id))
        c.cursor().execute("UPDATE tenants SET estado = 'REVOCADO', updated_at = ? WHERE id = ?", (now_iso, tenant_id))
        c.cursor().execute("""
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (?, 'SUPER_ADMIN', 'LICENCIA_REVOCADA', ?, ?)
        """, (tenant_id, json.dumps({"motivo": motivo}), now_iso))

    # Invalidar todas las sesiones en memoria asociadas al tenant o sus sub-tenants
    for tok, ses in list(ACTIVE_SESSIONS.items()):
        t_id = ses.get("tenant_id")
        t_obj = ses.get("tenant") or {}
        if t_id == tenant_id or t_obj.get("parent_tenant_id") == tenant_id:
            del ACTIVE_SESSIONS[tok]
    return True

def reactivate_tenant_license(tenant_id: str, extension_days: int = 30) -> bool:
    """Reactiva la licencia de un tenant y extiende su fecha de expiración."""
    now = datetime.now()
    new_expires = (now + timedelta(days=extension_days)).isoformat()
    with get_db() as c:
        c.cursor().execute("""
            UPDATE suscripciones 
            SET estado = 'ACTIVA', fecha_expiracion = ?, updated_at = ? 
            WHERE tenant_id = ?
        """, (new_expires, now.isoformat(), tenant_id))
        c.cursor().execute("UPDATE tenants SET estado = 'ACTIVO', updated_at = ? WHERE id = ?", (now.isoformat(), tenant_id))
    return True

def update_seat_pool(tenant_id: str, seat_delta: int) -> Dict[str, Any]:
    """Suma o resta puestos contratados a la bolsa de una agencia o empresa."""
    sub = get_subscription_by_tenant(tenant_id)
    if not sub:
        return {"exito": False, "mensaje": "Suscripción no encontrada"}

    current_seats = sub.get("puestos_contratados", 1)
    new_seats = max(1, current_seats + seat_delta)
    
    with get_db() as c:
        c.cursor().execute("UPDATE suscripciones SET puestos_contratados = ?, updated_at = ? WHERE tenant_id = ?", (new_seats, datetime.now().isoformat(), tenant_id))

    return {"exito": True, "puestos_anteriores": current_seats, "puestos_actuales": new_seats, "puestos_contratados": new_seats}

# ==============================================================================
# OPERACIONES DE GESTIÓN PARA AGENCIA (Agency Admin)
# ==============================================================================

def list_agency_subtenants(agency_tenant_id: str, conn=None) -> List[Dict[str, Any]]:
    """Lists all client sub-tenants of an agency with their seats and metrics."""
    query = """
        SELECT t.*, 
               (SELECT COUNT(*) FROM leads WHERE tenant_id = t.id) as total_leads,
               (SELECT COUNT(*) FROM leads WHERE tenant_id = t.id AND estado = 'REUNION_AGENDADA') as total_reuniones,
               (SELECT COUNT(*) FROM usuarios WHERE tenant_id = t.id AND puesto_activo = 1) as puestos_usados
        FROM tenants t
        WHERE t.parent_tenant_id = ?
        ORDER BY t.created_at DESC
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (agency_tenant_id,))
        return [dict(r) for r in cursor.fetchall()]
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (agency_tenant_id,))
        return [dict(r) for r in cursor.fetchall()]

def create_agency_client(
    agency_tenant_id: str,
    company_name: str,
    billing_model: str = "POR_PUESTO",
    meeting_rate: float = 0.0,
    client_seat_price: float = 0.0,
    fixed_monthly_fee: float = 0.0,
    assigned_seats: int = 1,
    **kwargs
) -> Dict[str, Any]:
    """Allows an agency to register a new client checking that free seats exist in its pool."""
    # Resolve aliases
    meeting_rate = kwargs.get("meeting_fee", kwargs.get("tarifa_por_reunion", meeting_rate))
    client_seat_price = kwargs.get("seat_price_charged", kwargs.get("precio_cliente_por_puesto", client_seat_price))
    fixed_monthly_fee = kwargs.get("monthly_fixed_fee", kwargs.get("fee_fijo_mensual", fixed_monthly_fee))
    company_name = kwargs.get("razon_social", company_name)
    billing_model = kwargs.get("modelo_cobro", billing_model)
    assigned_seats = kwargs.get("puestos_asignados", assigned_seats)

    sub_agency = get_subscription_by_tenant(agency_tenant_id)
    if not sub_agency or sub_agency.get("estado") != "ACTIVA":
        return {"exito": False, "mensaje": "La agencia no posee una suscripción activa."}

    total_seats = sub_agency.get("puestos_contratados", 1)
    occupied_seats = count_occupied_seats_tenant(agency_tenant_id)

    if occupied_seats + assigned_seats > total_seats:
        return {
            "exito": False, 
            "mensaje": f"No tienes suficientes puestos libres en tu bolsa ({occupied_seats}/{total_seats} en uso). Por favor amplía tus puestos primero."
        }

    now_iso = datetime.now().isoformat()
    new_id = "ten_cli_" + secrets.token_hex(6)

    with get_db() as c:
        c.cursor().execute("""
            INSERT INTO tenants (
                id, parent_tenant_id, razon_social, tipo_tenant, estado,
                modelo_cobro_cliente, tarifa_por_reunion, precio_cliente_por_puesto,
                fee_fijo_mensual, puestos_asignados, created_at, updated_at
            ) VALUES (?, ?, ?, 'CLIENTE_AGENCIA', 'ACTIVO', ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_id, agency_tenant_id, company_name, billing_model,
            meeting_rate, client_seat_price, fixed_monthly_fee,
            assigned_seats, now_iso, now_iso
        ))

    return {
        "exito": True, 
        "tenant_id": new_id, 
        "razon_social": company_name,
        "cliente": {"id": new_id, "razon_social": company_name}
    }

def list_tenant_users(tenant_id: str, conn=None) -> List[Dict[str, Any]]:
    """Lists users belonging to a tenant."""
    query = """
        SELECT id, tenant_id, email, nombre, rol, puesto_activo, estado, ultimo_login, created_at
        FROM usuarios
        WHERE tenant_id = ?
        ORDER BY created_at ASC
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query, (tenant_id,))
        return [dict(r) for r in cursor.fetchall()]
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query, (tenant_id,))
        return [dict(r) for r in cursor.fetchall()]

def create_user_for_tenant(
    tenant_id: str,
    email: str,
    password: str,
    name: str,
    role: str = "COMPANY_MEMBER"
) -> Dict[str, Any]:
    """Creates a new user ensuring seat pool capacity."""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {"exito": False, "mensaje": "Organización no encontrada."}

    # Verify existing email
    if get_user_by_email(email):
        return {"exito": False, "mensaje": "Ya existe un usuario con este correo electrónico."}

    # Validate seat quota
    agency_id = tenant.get("parent_tenant_id")
    if agency_id:
        sub_agency = get_subscription_by_tenant(agency_id)
        if not sub_agency or sub_agency.get("estado") != "ACTIVA":
            return {"exito": False, "mensaje": "La suscripción de la agencia no está activa."}
        total_seats = sub_agency.get("puestos_contratados", 1)
        occupied_seats = count_occupied_seats_tenant(agency_id)
        if occupied_seats >= total_seats:
            return {
                "exito": False, 
                "mensaje": f"Se alcanzó el límite de puestos de la agencia ({occupied_seats}/{total_seats}). Amplía tu bolsa primero."
            }
    else:
        sub_company = get_subscription_by_tenant(tenant_id)
        if not sub_company or sub_company.get("estado") != "ACTIVA":
            return {"exito": False, "mensaje": "La suscripción de la empresa no está activa."}
        total_seats = sub_company.get("puestos_contratados", 1)
        occupied_seats = count_occupied_seats_tenant(tenant_id)
        if occupied_seats >= total_seats:
            return {
                "exito": False, 
                "mensaje": f"Se alcanzó el límite de puestos contratados ({occupied_seats}/{total_seats}). Amplía tus puestos primero."
            }

    now_iso = datetime.now().isoformat()
    one_year_iso = (datetime.now() + timedelta(days=365)).isoformat()
    user_id = "usr_" + secrets.token_hex(6)
    p_hash, salt = hash_password(password)

    with get_db() as c:
        c.cursor().execute("""
            INSERT INTO usuarios (
                id, tenant_id, email, nombre, password_hash, salt, rol,
                puesto_activo, estado, suscripcion_expira, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'ACTIVO', ?, ?, ?)
        """, (user_id, tenant_id, email.strip(), name.strip(), p_hash, salt, role, one_year_iso, now_iso, now_iso))

        c.cursor().execute("""
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (?, ?, 'USUARIO_CREADO', ?, ?)
        """, (tenant_id, user_id, json.dumps({"email": email, "rol": role}), now_iso))

    return {
        "exito": True, 
        "usuario": {"id": user_id, "email": email, "nombre": name, "rol": role, "puesto_activo": 1}
    }

def toggle_user_seat(user_id: str, new_seat_status: int) -> Dict[str, Any]:
    """Assigns or frees a user seat. If removed, drops session immediately."""
    user = get_user_by_id(user_id)
    if not user:
        return {"exito": False, "mensaje": "Usuario no encontrado."}

    now_iso = datetime.now().isoformat()
    tenant_id = user.get("tenant_id")

    if new_seat_status == 1 and tenant_id:
        tenant = get_tenant_by_id(tenant_id)
        t_val_id = tenant.get("parent_tenant_id") or tenant_id
        sub = get_subscription_by_tenant(t_val_id)
        if sub:
            p_total = sub.get("puestos_contratados", 1)
            p_used = count_occupied_seats_tenant(t_val_id)
            if p_used >= p_total:
                return {"exito": False, "mensaje": f"No hay puestos libres en la bolsa ({p_used}/{p_total} en uso)."}

    with get_db() as c:
        c.cursor().execute("""
            UPDATE usuarios 
            SET puesto_activo = ?, updated_at = ? 
            WHERE id = ?
        """, (new_seat_status, now_iso, user_id))

        action_name = "PUESTO_ASIGNADO" if new_seat_status == 1 else "PUESTO_LIBERADO"
        c.cursor().execute("""
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (tenant_id, user_id, action_name, json.dumps({"puesto_activo": new_seat_status}), now_iso))

    if new_seat_status == 0:
        for tok, ses in list(ACTIVE_SESSIONS.items()):
            if ses.get("id") == user_id:
                del ACTIVE_SESSIONS[tok]

    return {
        "exito": True, 
        "usuario_id": user_id, 
        "puesto_activo": new_seat_status,
        "usuario": {"id": user_id, "puesto_activo": new_seat_status}
    }

def mark_lead_meeting_booked(
    lead_id: str, 
    meeting_date: Optional[str] = None, 
    meeting_value: Optional[float] = None
) -> Dict[str, Any]:
    """Marks a prospect as REUNION_AGENDADA and stores conversion value."""
    now_iso = datetime.now().isoformat()
    final_date = meeting_date or now_iso

    with get_db() as c:
        cur = c.cursor()
        cur.execute("SELECT id, tenant_id FROM leads WHERE id = ?", (lead_id,))
        lead = cur.fetchone()
        if not lead:
            return {"exito": False, "mensaje": "Lead no encontrado"}

        final_value = meeting_value
        if final_value is None and lead.get("tenant_id"):
            cur.execute("SELECT tarifa_por_reunion FROM tenants WHERE id = ?", (lead["tenant_id"],))
            t_row = cur.fetchone()
            if t_row:
                final_value = float(t_row.get("tarifa_por_reunion") or 0.0)
        if final_value is None:
            final_value = 0.0

        cur.execute("""
            UPDATE leads 
            SET estado = 'REUNION_AGENDADA', 
                fecha_reunion_agendada = ?, 
                valor_reunion = ?, 
                updated_at = ?
            WHERE id = ?
        """, (final_date, final_value, now_iso, lead_id))

        cur.execute("""
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (?, NULL, 'LEAD_REUNION_AGENDADA', ?, ?)
        """, (lead.get("tenant_id"), json.dumps({"lead_id": lead_id, "valor": final_value, "fecha": final_date}), now_iso))

    return {"exito": True, "lead_id": lead_id, "estado": "REUNION_AGENDADA", "valor_reunion": final_value}

def get_agency_financial_summary(agency_tenant_id: str, conn=None) -> Dict[str, Any]:
    """Calculates agency costs, revenue and net margin across its client portfolio."""
    sub = get_subscription_by_tenant(agency_tenant_id, conn)
    if not sub:
        return {"exito": False, "mensaje": "Suscripción no encontrada"}

    pool_seats = sub.get("puestos_contratados", 1)
    unit_platform_cost = sub.get("precio_unitario_plataforma", 35.0)
    total_platform_cost = pool_seats * unit_platform_cost

    subtenants = list_agency_subtenants(agency_tenant_id, conn)
    client_breakdown = []
    total_client_revenue = 0.0
    total_occupied_seats = 0

    for st in subtenants:
        model = st.get("modelo_cobro_cliente") or "POR_PUESTO"
        meetings = st.get("total_reuniones", 0)
        used_seats = st.get("puestos_usados", 0)
        assigned_seats = st.get("puestos_asignados", 1)
        meeting_fee = float(st.get("tarifa_por_reunion") or 0.0)
        seat_price = float(st.get("precio_cliente_por_puesto") or 0.0)
        monthly_fee = float(st.get("fee_fijo_mensual") or 0.0)

        client_rev = 0.0
        if model == "POR_REUNION":
            client_rev = meetings * meeting_fee
        elif model == "POR_PUESTO":
            client_rev = used_seats * seat_price
        elif model == "RETAINER_FIJO":
            client_rev = monthly_fee
        elif model == "HIBRIDO":
            client_rev = monthly_fee + (meetings * meeting_fee)
        elif model == "INTERNO":
            client_rev = 0.0

        imputed_cost = used_seats * unit_platform_cost
        client_margin = client_rev - imputed_cost
        total_client_revenue += client_rev
        total_occupied_seats += used_seats

        client_breakdown.append({
            "id": st["id"],
            "razon_social": st["razon_social"],
            "modelo_cobro": model,
            "reuniones_agendadas": meetings,
            "puestos_usados": used_seats,
            "puestos_asignados": assigned_seats,
            "facturacion_cliente": round(client_rev, 2),
            "costo_plataforma": round(imputed_cost, 2),
            "margen_neto": round(client_margin, 2)
        })

    agency_net_margin = total_client_revenue - total_platform_cost
    margin_percentage = (
        round((agency_net_margin / total_client_revenue) * 100, 1) 
        if total_client_revenue > 0 else 0.0
    )

    return {
        "exito": True,
        "resumen_bolsa": {
            "puestos_contratados": pool_seats,
            "puestos_ocupados": total_occupied_seats,
            "puestos_libres": max(0, pool_seats - total_occupied_seats),
            "costo_unitario": unit_platform_cost,
            "costo_total_plataforma": round(total_platform_cost, 2),
            "periodicidad": sub.get("periodicidad", "MENSUAL"),
            "expira": sub.get("fecha_expiracion")
        },
        "consolidado_financiero": {
            "facturacion_total_clientes": round(total_client_revenue, 2),
            "costo_total_plataforma": round(total_platform_cost, 2),
            "margen_neto_agencia": round(agency_net_margin, 2),
            "porcentaje_margen": margin_percentage
        },
        "consolidado": {
            "facturacion_total_clientes": round(total_client_revenue, 2),
            "costo_total_plataforma": round(total_platform_cost, 2),
            "margen_neto_agencia": round(agency_net_margin, 2),
            "porcentaje_margen": margin_percentage
        },
        "clientes": client_breakdown
    }

def list_users(conn=None) -> List[Dict[str, Any]]:
    """Lists all users across the platform for Super Admin."""
    query = """
        SELECT u.id, u.tenant_id, u.email, u.nombre, u.rol, u.puesto_activo, u.estado, 
               u.suscripcion_expira, u.ultimo_login, u.created_at,
               t.razon_social as organizacion
        FROM usuarios u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        ORDER BY u.created_at DESC
    """
    if conn:
        cursor = conn.cursor()
        cursor.execute(query)
        return [dict(r) for r in cursor.fetchall()]
    with get_db() as c:
        cursor = c.cursor()
        cursor.execute(query)
        return [dict(r) for r in cursor.fetchall()]

def update_user_subscription(
    user_id: str,
    estado: Optional[str] = None,
    plan: Optional[str] = None,
    dias_extra: Optional[int] = None,
    nueva_fecha_expira: Optional[str] = None
) -> Dict[str, Any]:
    """Updates a user's subscription details."""
    with get_db() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,))
        usr = cur.fetchone()
        if not usr:
            return {"exito": False, "mensaje": "Usuario no encontrado"}

        now = datetime.now()
        current_exp = usr.get("suscripcion_expira")
        if dias_extra:
            base = datetime.fromisoformat(current_exp) if current_exp else now
            new_exp = (base + timedelta(days=dias_extra)).isoformat()
        elif nueva_fecha_expira:
            new_exp = nueva_fecha_expira
        else:
            new_exp = current_exp

        new_status = estado or usr.get("estado", "ACTIVO")

        cur.execute("""
            UPDATE usuarios 
            SET estado = ?, suscripcion_expira = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, new_exp, now.isoformat(), user_id))

    return {
        "exito": True,
        "usuario_id": user_id,
        "estado": new_status,
        "suscripcion_expira": new_exp,
        "mensaje": "Suscripción de usuario actualizada con éxito"
    }

# ==========================================
# BACKWARD COMPATIBILITY ALIASES
# ==========================================
SESIONES_ACTIVAS = ACTIVE_SESSIONS
calcular_dias_restantes = calculate_days_remaining
obtener_usuario_por_email = get_user_by_email
obtener_usuario_por_id = get_user_by_id
obtener_tenant_por_id = get_tenant_by_id
obtener_suscripcion_por_tenant = get_subscription_by_tenant
contar_puestos_ocupados_tenant = count_occupied_seats_tenant
autenticar_usuario = authenticate_user
verificar_token = verify_token
cerrar_sesion = logout_user
listar_tenants_global = list_global_tenants
revocar_licencia_tenant = revoke_tenant_license
reactivar_licencia_tenant = reactivate_tenant_license
actualizar_puestos_bolsa = update_seat_pool
listar_subtenants_agencia = list_agency_subtenants
crear_cliente_agencia = create_agency_client
listar_usuarios_tenant = list_tenant_users
crear_usuario_para_tenant = create_user_for_tenant
toggle_puesto_usuario = toggle_user_seat
marcar_lead_reunion_agendada = mark_lead_meeting_booked
obtener_resumen_financiero_agencia = get_agency_financial_summary
listar_usuarios = list_users
actualizar_suscripcion_usuario = update_user_subscription


