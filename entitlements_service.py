"""
Servicio de Entitlements, Metering y Límites Comerciales (Workstream 5.9)
NexusReach Pro - Directrices v1.3

Reglas de Diseño y Compromisos NO Negociables:
1. Modelo comercial: 15 USD/mes por cuenta de LinkedIn (unidad de cobro: cuenta, no usuario).
2. Todo límite es CONFIGURACIÓN en base de datos (`entitlements`), nunca codificado en duro.
3. Los límites de seguridad (Workstream 5.5) NUNCA son comerciales. Comprar un pack comercial
   JAMÁS relaja ni altera los límites de seguridad antiban.
4. Los límites comerciales SOLO bloquean nuevas activaciones de prospectos en el ciclo.
   Los prospectos ya activos continúan sus secuencias, seguimientos y respuestas (NUNCA cortar flujos en curso).
5. Visibilidad al 80% y 100% de cuota por ciclo, con motivos explícitos:
   - `LIMIT_LEADS_REACHED`
   - `LIMIT_CREDITS_REACHED`
6. Período de prueba (Trial) de 14 días sin tarjeta (100 leads y 20 créditos). Al expirar sin suscripción activa,
   el tenant no recibe comandos.
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List

from database import get_db

# Valores de referencia por defecto iniciales (se leen de BD o se inicializan en entitlements)
DEFAULT_LEADS_LIMIT_CYCLE = 500
DEFAULT_CREDITS_LIMIT_CYCLE = 100
DEFAULT_TRIAL_LEADS = 100
DEFAULT_TRIAL_CREDITS = 20
DEFAULT_TRIAL_DAYS = 14
DEFAULT_GRACE_PERIOD_DAYS = 3


def get_current_cycle_bounds(reference_date: Optional[datetime] = None) -> Tuple[str, str]:
    """
    Calcula los límites del ciclo mensual actual (primer y último día del mes en formato ISO).
    """
    ref = reference_date or datetime.now(timezone.utc)
    start_of_month = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Próximo mes día 1
    if start_of_month.month == 12:
        end_of_month = start_of_month.replace(year=start_of_month.year + 1, month=1)
    else:
        end_of_month = start_of_month.replace(month=start_of_month.month + 1)
    return start_of_month.strftime("%Y-%m-%d"), end_of_month.strftime("%Y-%m-%d")


def get_or_create_entitlements(tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Obtiene o inicializa los límites comerciales (`entitlements`) para un tenant.
    Los límites residen en la base de datos, no en el código.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    trial_end = (datetime.now(timezone.utc) + timedelta(days=DEFAULT_TRIAL_DAYS)).isoformat()

    def _query(c):
        cursor = c.cursor()
        cursor.execute("SELECT * FROM entitlements WHERE tenant_id = ?", (tenant_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)

        ent_id = f"ent_{tenant_id}"
        cursor.execute("""
            INSERT INTO entitlements 
            (id, tenant_id, subscription_id, leads_limit_cycle, credits_limit_cycle, max_linkedin_accounts, allow_whatsapp, is_trial, trial_end, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?, 1, 0, 1, ?, ?, ?)
        """, (ent_id, tenant_id, DEFAULT_LEADS_LIMIT_CYCLE, DEFAULT_CREDITS_LIMIT_CYCLE, trial_end, now_iso, now_iso))

        # Acreditar créditos iniciales del trial en el ledger
        cursor.execute("""
            INSERT OR IGNORE INTO credit_ledger 
            (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
            VALUES (?, ?, NULL, 'TRIAL_GRANT', ?, ?, 'Créditos iniciales del período de prueba (Trial)', ?)
        """, (f"cred_{uuid.uuid4()}", tenant_id, DEFAULT_CREDITS_LIMIT_CYCLE, DEFAULT_CREDITS_LIMIT_CYCLE, now_iso))

        cursor.execute("SELECT * FROM entitlements WHERE tenant_id = ?", (tenant_id,))
        return dict(cursor.fetchone())

    if conn is not None:
        return _query(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _query(c)


def get_active_subscription(tenant_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """
    Retorna la suscripción activa o en trial de un tenant, considerando días de gracia.
    """
    def _query(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT * FROM subscriptions 
            WHERE tenant_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (tenant_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _query(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _query(c)


def is_tenant_subscription_active(tenant_id: str, conn=None) -> Tuple[bool, str]:
    """
    Verifica si el tenant tiene derecho a ejecutar comandos según su suscripción o período de prueba.
    Retorna (activo: bool, motivo: str).
    """
    ent = get_or_create_entitlements(tenant_id, conn=conn)
    sub = get_active_subscription(tenant_id, conn=conn)
    now = datetime.now(timezone.utc)

    # 1. Si está en período de prueba (Trial)
    if ent.get("is_trial") == 1:
        trial_end_str = ent.get("trial_end")
        if trial_end_str:
            trial_end_dt = datetime.fromisoformat(trial_end_str.replace("Z", "+00:00"))
            if now <= trial_end_dt:
                return True, "En período de prueba activo (Trial de 14 días)."
            else:
                return False, "El período de prueba de 14 días ha expirado. Requiere contratar suscripción activa (15 USD/mes) para continuar."

    # 2. Si tiene suscripción formal
    if sub:
        status = sub.get("status", "").lower()
        if status == "active":
            return True, "Suscripción activa."
        elif status == "trialing":
            return True, "Suscripción en período de evaluación inicial."
        elif status == "past_due":
            # Verificar si está dentro del período de gracia (3 días por defecto)
            grace_days = sub.get("grace_period_days", DEFAULT_GRACE_PERIOD_DAYS)
            updated_str = sub.get("updated_at")
            if updated_str:
                upd_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                if now <= upd_dt + timedelta(days=grace_days):
                    return True, f"Suscripción en período de gracia tras intento de cobro ({grace_days} días)."
            return False, "Suscripción vencida (past_due) fuera del período de gracia. Comandos suspendidos."
        elif status == "canceled":
            return False, "La suscripción ha sido cancelada. Comandos suspendidos."

    # Si es trial terminado o sin suscripción
    if ent.get("is_trial") == 0 and not sub:
        return False, "Sin suscripción activa. Requiere activar suscripción de 15 USD/mes por cuenta de LinkedIn."

    return False, "Acceso comercial no disponible."


def get_or_create_cycle_counter(tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Obtiene o crea el registro de contadores de uso para el ciclo mensual actual.
    """
    cycle_start, cycle_end = get_current_cycle_bounds()
    now_iso = datetime.now(timezone.utc).isoformat()
    counter_id = f"cnt_{tenant_id}_{cycle_start}"

    def _get(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT * FROM usage_counters 
            WHERE tenant_id = ? AND cycle_start = ?
        """, (tenant_id, cycle_start))
        row = cursor.fetchone()
        if row:
            return dict(row)

        cursor.execute("""
            INSERT INTO usage_counters 
            (id, tenant_id, cycle_start, cycle_end, leads_activated, actions_executed, credits_consumed, verification_cost_usd, security_incidents, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, 0, 0.0, 0, ?, ?)
        """, (counter_id, tenant_id, cycle_start, cycle_end, now_iso, now_iso))

        cursor.execute("SELECT * FROM usage_counters WHERE id = ?", (counter_id,))
        return dict(cursor.fetchone())

    if conn is not None:
        return _get(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _get(c)


def check_lead_activation_entitlement(
    tenant_id: str,
    lead_id: str,
    conn=None
) -> Dict[str, Any]:
    """
    REGLA DE ORO DE LÍMITES COMERCIALES (Sección 5.9.A.2):
    - Los límites comerciales SOLO bloquean nuevas activaciones en el ciclo.
    - Si el lead ya fue activado en este ciclo (o ya tiene interacciones previas en curso),
      se APRUEBA inmediatamente porque NUNCA se cortan conversaciones en curso.
    - Si es un prospecto nuevo que recibirá su primera acción en el ciclo:
      Se verifica si leads_activated < leads_limit_cycle.
      Si se alcanzó el límite: se RECHAZA con `LIMIT_LEADS_REACHED`.
    """
    cycle_start, cycle_end = get_current_cycle_bounds()
    now_iso = datetime.now(timezone.utc).isoformat()

    def _eval(c):
        cursor = c.cursor()

        # 1. Comprobar si el lead ya está activo en este ciclo
        cursor.execute("""
            SELECT COUNT(*) AS total FROM lead_activity 
            WHERE lead_id = ? AND created_at >= ?
        """, (lead_id, cycle_start))
        act_row = cursor.fetchone()
        act_count = (dict(act_row).get("total") or 0) if act_row else 0

        if act_count > 0:
            # Lead ya en conversación/secuencia activa: permitido sin tocar cuota de activación
            return {
                "aprobado": True,
                "is_new_activation": False,
                "motivo": "Lead ya activo en el ciclo en curso. Secuencia en curso respetada."
            }

        # 2. Es un prospecto nuevo: evaluar límite mensual de activaciones
        ent = get_or_create_entitlements(tenant_id, conn=c)
        counter = get_or_create_cycle_counter(tenant_id, conn=c)

        leads_limit = int(ent.get("leads_limit_cycle", DEFAULT_LEADS_LIMIT_CYCLE))
        leads_activated = int(counter.get("leads_activated", 0))

        if leads_activated >= leads_limit:
            return {
                "aprobado": False,
                "codigo": "LIMIT_LEADS_REACHED",
                "is_new_activation": True,
                "leads_activated": leads_activated,
                "leads_limit": leads_limit,
                "motivo": f"Cuota mensual de nuevos leads alcanzada ({leads_activated}/{leads_limit}). Se ofrece adquirir un pack de +500 leads o esperar al siguiente ciclo."
            }

        # 3. Aprobado para nueva activación: registrar incremento
        cursor.execute("""
            UPDATE usage_counters 
            SET leads_activated = leads_activated + 1, updated_at = ?
            WHERE id = ?
        """, (now_iso, counter["id"]))

        # Registrar en usage_events
        event_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO usage_events 
            (id, tenant_id, account_id, event_type, provider, cost_usd, credits_consumed, details_json, created_at)
            VALUES (?, ?, NULL, 'LEAD_ACTIVATED', 'INTERNAL', 0.0, 0, ?, ?)
        """, (event_id, tenant_id, json.dumps({"lead_id": lead_id, "cycle": cycle_start}), now_iso))

        return {
            "aprobado": True,
            "is_new_activation": True,
            "leads_activated": leads_activated + 1,
            "leads_limit": leads_limit,
            "motivo": "Nueva activación autorizada dentro de la cuota del ciclo."
        }

    if conn is not None:
        return _eval(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _eval(c)


def check_email_credits_entitlement(tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Verifica si el tenant dispone de créditos para consultas externas de pago (verificadores).
    Si los créditos están agotados, retorna `LIMIT_CREDITS_REACHED`.
    Las búsquedas públicas gratuitas (OSINT de colegios, etc.) no son bloqueadas.
    """
    def _eval(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT balance_after FROM credit_ledger 
            WHERE tenant_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (tenant_id,))
        row = cursor.fetchone()
        if not row:
            ent = get_or_create_entitlements(tenant_id, conn=c)
            balance = int(ent.get("credits_limit_cycle", DEFAULT_CREDITS_LIMIT_CYCLE))
        else:
            balance = dict(row).get("balance_after", 0)

        if balance <= 0:
            return {
                "aprobado": False,
                "codigo": "LIMIT_CREDITS_REACHED",
                "balance": balance,
                "motivo": "Créditos de verificación de correo agotados (0 disponibles). Se requiere pack de créditos para continuar verificaciones externas."
            }

        return {
            "aprobado": True,
            "balance": balance,
            "motivo": "Créditos disponibles."
        }

    if conn is not None:
        return _eval(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _eval(c)


def add_pack_leads(
    tenant_id: str,
    leads_quantity: int = 500,
    price_usd: float = 5.0,
    conn=None
) -> Dict[str, Any]:
    """
    Agrega un pack adicional de leads para el ciclo en curso (+500 por 5 USD).
    Expira con el ciclo actual (no acumulable entre ciclos).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    def _add(c):
        cursor = c.cursor()
        ent = get_or_create_entitlements(tenant_id, conn=c)
        new_limit = int(ent.get("leads_limit_cycle", DEFAULT_LEADS_LIMIT_CYCLE)) + leads_quantity

        cursor.execute("""
            UPDATE entitlements 
            SET leads_limit_cycle = ?, updated_at = ?
            WHERE tenant_id = ?
        """, (new_limit, now_iso, tenant_id))

        # Registrar evento de compra
        cursor.execute("""
            INSERT INTO usage_events 
            (id, tenant_id, account_id, event_type, provider, cost_usd, credits_consumed, details_json, created_at)
            VALUES (?, ?, NULL, 'PACK_LEADS_PURCHASED', 'BILLING', ?, 0, ?, ?)
        """, (str(uuid.uuid4()), tenant_id, price_usd, json.dumps({"quantity": leads_quantity, "new_limit": new_limit}), now_iso))

        return {
            "ok": True,
            "pack_type": "LEADS",
            "quantity_added": leads_quantity,
            "new_leads_limit": new_limit,
            "price_usd": price_usd
        }

    if conn is not None:
        return _add(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _add(c)


def add_pack_credits(
    tenant_id: str,
    credits_quantity: int,
    price_usd: float,
    conn=None
) -> Dict[str, Any]:
    """
    Agrega un pack de créditos de correo (100 por 6 USD, o 500 por 28 USD).
    Sin vencimiento (quedan en credit_ledger permanentemente hasta su consumo).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    def _add(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT balance_after FROM credit_ledger 
            WHERE tenant_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (tenant_id,))
        row = cursor.fetchone()
        current_balance = dict(row).get("balance_after", 0) if row else 0
        new_balance = current_balance + credits_quantity

        cursor.execute("""
            INSERT INTO credit_ledger 
            (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
            VALUES (?, ?, NULL, 'PACK_PURCHASE', ?, ?, ?, ?)
        """, (f"cred_pack_{uuid.uuid4()}", tenant_id, credits_quantity, new_balance, f"Compra de pack de {credits_quantity} créditos de correo ({price_usd} USD)", now_iso))

        # Registrar en usage_events
        cursor.execute("""
            INSERT INTO usage_events 
            (id, tenant_id, account_id, event_type, provider, cost_usd, credits_consumed, details_json, created_at)
            VALUES (?, ?, NULL, 'PACK_CREDITS_PURCHASED', 'BILLING', ?, 0, ?, ?)
        """, (str(uuid.uuid4()), tenant_id, price_usd, json.dumps({"credits": credits_quantity, "new_balance": new_balance}), now_iso))

        return {
            "ok": True,
            "pack_type": "CREDITS",
            "credits_added": credits_quantity,
            "new_balance": new_balance,
            "price_usd": price_usd
        }

    if conn is not None:
        return _add(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _add(c)


def get_cycle_usage_summary(tenant_id: str, conn=None) -> Dict[str, Any]:
    """
    Retorna el estado integral de consumo del ciclo actual para paneles de usuario
    y alertas tempranas (aviso preventivo al 80% y bloqueo al 100%).
    """
    def _get(c):
        ent = get_or_create_entitlements(tenant_id, conn=c)
        counter = get_or_create_cycle_counter(tenant_id, conn=c)

        cursor = c.cursor()
        cursor.execute("""
            SELECT balance_after FROM credit_ledger 
            WHERE tenant_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (tenant_id,))
        row = cursor.fetchone()
        credit_balance = dict(row).get("balance_after", 0) if row else 0

        leads_limit = int(ent.get("leads_limit_cycle", DEFAULT_LEADS_LIMIT_CYCLE))
        leads_act = int(counter.get("leads_activated", 0))
        leads_pct = (leads_act / leads_limit * 100.0) if leads_limit > 0 else 0.0

        alert_80 = leads_pct >= 80.0
        alert_100 = leads_pct >= 100.0

        sub = get_active_subscription(tenant_id, conn=c)
        is_active, sub_msg = is_tenant_subscription_active(tenant_id, conn=c)

        return {
            "tenant_id": tenant_id,
            "subscription_active": is_active,
            "subscription_status": sub.get("status") if sub else ("trial" if ent.get("is_trial") else "none"),
            "status_message": sub_msg,
            "cycle_start": counter.get("cycle_start"),
            "cycle_end": counter.get("cycle_end"),
            "leads": {
                "activated": leads_act,
                "limit": leads_limit,
                "percentage_used": round(leads_pct, 1),
                "alert_80_reached": alert_80,
                "limit_reached": alert_100
            },
            "credits": {
                "balance": credit_balance,
                "consumed_in_cycle": counter.get("credits_consumed", 0),
                "is_empty": credit_balance <= 0
            },
            "financials_cycle": {
                "external_verification_cost_usd": counter.get("verification_cost_usd", 0.0)
            }
        }

    if conn is not None:
        return _get(conn)
    else:
        with get_db(tenant_id=tenant_id) as c:
            return _get(c)
