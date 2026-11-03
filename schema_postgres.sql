-- ==============================================================================
-- NEXUSREACH PRO - ESQUEMA DE BASE DE DATOS POSTGRESQL MULTI-TENANT CON RLS
-- Diseñado para entornos de Nube (AWS RDS, Supabase, Neon.tech, Railway, Render)
-- Implementación TASK-04B: Row-Level Security, FORCE RLS y Rol de Privilegios Mínimos
-- ==============================================================================

-- 1. Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==============================================================================
-- TABLAS PRINCIPALES DEL SISTEMA Y GESTIÓN MULTI-TENANT (CONTROL PLANE)
-- ==============================================================================

-- Tenants (Empresas, Agencias y Sub-Tenants)
CREATE TABLE IF NOT EXISTS tenants (
    id VARCHAR(64) PRIMARY KEY,
    parent_tenant_id VARCHAR(64) REFERENCES tenants(id) ON DELETE CASCADE,
    razon_social VARCHAR(255) NOT NULL,
    tipo_tenant VARCHAR(32) NOT NULL DEFAULT 'EMPRESA', -- EMPRESA, AGENCIA, INDIVIDUAL, CLIENTE_AGENCIA
    estado VARCHAR(32) DEFAULT 'ACTIVO',               -- ACTIVO, SUSPENDIDO, CANCELADO, REVOCADO
    modelo_cobro_cliente VARCHAR(32) DEFAULT 'POR_PUESTO', -- POR_PUESTO, POR_REUNION, FEE_FIJO, RETAINER_FIJO, HIBRIDO, INTERNO
    tarifa_por_reunion NUMERIC(10, 2) DEFAULT 0.0,
    precio_cliente_por_puesto NUMERIC(10, 2) DEFAULT 0.0,
    fee_fijo_mensual NUMERIC(10, 2) DEFAULT 0.0,
    puestos_asignados INTEGER DEFAULT 1,
    zoho_sync_activo INTEGER DEFAULT 0,
    zoho_org_id VARCHAR(64),
    notas TEXT,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- Suscripciones y Bolsas de Puestos Comerciales
CREATE TABLE IF NOT EXISTS suscripciones (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    periodicidad VARCHAR(32) NOT NULL DEFAULT 'MENSUAL', -- MENSUAL, ANUAL
    estado VARCHAR(32) NOT NULL DEFAULT 'ACTIVA',        -- ACTIVA, TRIAL, SUSPENDIDA, CANCELADA, REVOCADA
    puestos_contratados INTEGER NOT NULL DEFAULT 1,
    precio_unitario_plataforma NUMERIC(10, 2) DEFAULT 35.0,
    fecha_inicio VARCHAR(64) NOT NULL,
    fecha_expiracion VARCHAR(64) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- Usuarios y Roles RBAC Multi-Tenant
CREATE TABLE IF NOT EXISTS usuarios (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) REFERENCES tenants(id) ON DELETE SET NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    nombre VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    salt VARCHAR(255) NOT NULL,
    rol VARCHAR(64) DEFAULT 'COMPANY_MEMBER', -- SUPER_ADMIN, AGENCY_ADMIN, COMPANY_ADMIN, COMPANY_MEMBER, INDIVIDUAL, FREELANCER
    puesto_activo INTEGER DEFAULT 1,
    estado VARCHAR(32) DEFAULT 'ACTIVO',
    suscripcion_estado VARCHAR(32) DEFAULT 'activa',
    suscripcion_plan VARCHAR(32) DEFAULT 'Pro',
    suscripcion_expira VARCHAR(64),
    ultimo_login VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- Configuración de Seguridad y Límites Anti-Baneo (GLOBAL: Control Plane Plataforma)
CREATE TABLE IF NOT EXISTS configuracion_seguridad (
    clave VARCHAR(128) PRIMARY KEY,
    valor TEXT NOT NULL,
    descripcion TEXT,
    updated_at VARCHAR(64)
);

-- Auditoría de Seguridad OWASP
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) REFERENCES tenants(id) ON DELETE SET NULL,
    usuario_id VARCHAR(64),
    accion VARCHAR(128) NOT NULL,
    detalle_json TEXT DEFAULT '{}',
    ip_address VARCHAR(64),
    timestamp VARCHAR(64) NOT NULL
);

-- ==============================================================================
-- TABLAS DE NEGOCIO Y PROSPECCIÓN (DATA PLANE - CON AISLAMIENTO RLS)
-- ==============================================================================

-- 1. Leads / Prospectos
CREATE TABLE IF NOT EXISTS leads (
    id VARCHAR(128) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre VARCHAR(255) NOT NULL,
    cargo_titular VARCHAR(255),
    cargo_actual VARCHAR(255),
    institucion_actual VARCHAR(255),
    ubicacion VARCHAR(255),
    grado_red VARCHAR(32) DEFAULT '2º',
    perfil_url TEXT NOT NULL,
    email VARCHAR(255),
    telefono VARCHAR(64),
    estado VARCHAR(64) DEFAULT 'EXTRAIDO',
    siguiendo INTEGER DEFAULT 0,
    siguiendo_desde VARCHAR(64),
    invitacion_retirada INTEGER DEFAULT 0,
    fecha_retiro_invitacion VARCHAR(64),
    fecha_extraccion VARCHAR(64),
    fecha_visita VARCHAR(64),
    fecha_invitacion VARCHAR(64),
    fecha_conexion VARCHAR(64),
    fecha_reunion_agendada VARCHAR(64),
    valor_reunion NUMERIC(10, 2) DEFAULT 0.0,
    tags TEXT DEFAULT '[]',
    notas TEXT,
    email_extracted VARCHAR(255),
    email_source VARCHAR(64),
    email_status VARCHAR(64),
    empresa_dominio VARCHAR(255),
    email_detalles_json TEXT DEFAULT '{}',
    email_zoho VARCHAR(255),
    zoho_entidad_tipo VARCHAR(32),
    zoho_id VARCHAR(64),
    zoho_lead_status VARCHAR(64),
    zoho_cuenta_id VARCHAR(64),
    zoho_cuenta_nombre VARCHAR(255),
    zoho_cuenta_dueno VARCHAR(255),
    zoho_cuenta_tipo VARCHAR(64),
    zoho_cuenta_es_cliente INTEGER DEFAULT 0,
    zoho_tratos_info TEXT DEFAULT '[]',
    zoho_synced_at VARCHAR(64),
    zoho_email_extracted_at VARCHAR(64),
    crm_external_id VARCHAR(128),
    crm_sync_status VARCHAR(64),
    crm_synced_at VARCHAR(64),
    source VARCHAR(64) DEFAULT 'LINKEDIN',
    source_url TEXT,
    legal_basis VARCHAR(64) DEFAULT 'INTERES_LEGITIMO',
    collected_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_leads_tenant_url UNIQUE (tenant_id, perfil_url)
);

-- 2. Listas de Prospectos (Audiencias / Segmentos)
CREATE TABLE IF NOT EXISTS listas_leads (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    termino_busqueda VARCHAR(255),
    estado VARCHAR(32) DEFAULT 'ACTIVA',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 3. Relación Leads <-> Listas (Tabla Puente Multi-Tenant)
CREATE TABLE IF NOT EXISTS leads_en_lista (
    id VARCHAR(128) PRIMARY KEY,
    lista_id VARCHAR(64) NOT NULL REFERENCES listas_leads(id) ON DELETE CASCADE,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    created_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_leads_en_lista UNIQUE (lista_id, lead_id)
);

-- 4. Secuencias Multicanal
CREATE TABLE IF NOT EXISTS secuencias (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    activa INTEGER DEFAULT 1,
    estado VARCHAR(32) DEFAULT 'PUBLICADA',
    es_default INTEGER DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 5. Pasos de la Secuencia (Árbol de Decisión)
CREATE TABLE IF NOT EXISTS pasos_secuencia (
    id VARCHAR(64) PRIMARY KEY,
    secuencia_id VARCHAR(64) NOT NULL REFERENCES secuencias(id) ON DELETE CASCADE,
    padre_paso_id VARCHAR(64),
    condicion_rama VARCHAR(32) DEFAULT 'DEFAULT',
    tipo_accion VARCHAR(64) NOT NULL,
    parametros_json TEXT DEFAULT '{}',
    orden INTEGER DEFAULT 1,
    created_at VARCHAR(64) NOT NULL
);

-- 6. Leads dentro de la Secuencia (Tabla Puente Multi-Tenant)
CREATE TABLE IF NOT EXISTS leads_en_secuencia (
    id VARCHAR(128) PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    secuencia_id VARCHAR(64) NOT NULL REFERENCES secuencias(id) ON DELETE CASCADE,
    paso_actual_id VARCHAR(64),
    estado VARCHAR(32) DEFAULT 'EN_CURSO',
    proxima_ejecucion_at VARCHAR(64),
    ultimo_resultado_json TEXT DEFAULT '{}',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_lead_secuencia UNIQUE (lead_id, secuencia_id)
);

-- 7. Relación Secuencias <-> Listas (Tabla Puente Multi-Tenant)
CREATE TABLE IF NOT EXISTS secuencia_listas (
    id VARCHAR(128) PRIMARY KEY,
    secuencia_id VARCHAR(64) NOT NULL REFERENCES secuencias(id) ON DELETE CASCADE,
    lista_id VARCHAR(64) NOT NULL REFERENCES listas_leads(id) ON DELETE CASCADE,
    activa INTEGER DEFAULT 1,
    auto_ingresar_nuevos INTEGER DEFAULT 1,
    created_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_secuencia_lista UNIQUE (secuencia_id, lista_id)
);

-- 8. Mensajes de LinkedIn
CREATE TABLE IF NOT EXISTS mensajes_linkedin (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campana_nombre VARCHAR(255),
    paso_secuencia INTEGER DEFAULT 1,
    contenido TEXT NOT NULL,
    tiene_adjuntos INTEGER DEFAULT 0,
    adjuntos_info TEXT DEFAULT '[]',
    estado VARCHAR(32) DEFAULT 'PENDIENTE',
    enviado_at VARCHAR(64),
    es_leido INTEGER DEFAULT 0,
    leido_at VARCHAR(64),
    fue_respondido INTEGER DEFAULT 0,
    respondido_at VARCHAR(64),
    respuesta_texto TEXT,
    created_at VARCHAR(64) NOT NULL
);

-- 9. Correos Electrónicos Outreach
CREATE TABLE IF NOT EXISTS correos_electronicos (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campana_nombre VARCHAR(255),
    paso_secuencia INTEGER DEFAULT 1,
    email_destino VARCHAR(255) NOT NULL,
    asunto VARCHAR(255) NOT NULL,
    cuerpo TEXT NOT NULL,
    tiene_adjunto INTEGER DEFAULT 0,
    estado VARCHAR(32) DEFAULT 'PENDIENTE',
    enviado_at VARCHAR(64),
    abierto INTEGER DEFAULT 0,
    abierto_at VARCHAR(64),
    clickeado INTEGER DEFAULT 0,
    respondido INTEGER DEFAULT 0,
    respondido_at VARCHAR(64),
    respuesta_texto TEXT,
    created_at VARCHAR(64) NOT NULL
);

-- 10. Mensajes de WhatsApp Web (Canal Local Antiban)
CREATE TABLE IF NOT EXISTS mensajes_whatsapp (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campana_nombre VARCHAR(255),
    paso_secuencia INTEGER DEFAULT 1,
    telefono_destino VARCHAR(64) NOT NULL,
    contenido TEXT NOT NULL,
    estado VARCHAR(32) DEFAULT 'PENDIENTE',
    enviado_at VARCHAR(64),
    fue_respondido INTEGER DEFAULT 0,
    respondido_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL
);

-- 11. Interacciones Sociales
CREATE TABLE IF NOT EXISTS interacciones_sociales (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tipo VARCHAR(64) NOT NULL,
    post_url TEXT,
    post_snippet TEXT,
    comentario_texto TEXT,
    fecha VARCHAR(64)
);

-- 12. Historial de Actividades
CREATE TABLE IF NOT EXISTS historial_actividades (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tipo_evento VARCHAR(64) NOT NULL,
    descripcion TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    timestamp VARCHAR(64) NOT NULL
);

-- 13. Logs de Sistema
CREATE TABLE IF NOT EXISTS system_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) REFERENCES tenants(id) ON DELETE SET NULL,
    timestamp VARCHAR(64) NOT NULL,
    level VARCHAR(32) NOT NULL,
    module VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    lead_id VARCHAR(128),
    created_at VARCHAR(64) NOT NULL
);

-- 14. Dispositivos Locales Emparejados (Workstream 5.1 - Ed25519)
CREATE TABLE IF NOT EXISTS devices (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(64) REFERENCES usuarios(id) ON DELETE SET NULL,
    device_name VARCHAR(255),
    public_key_ed25519 TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'ACTIVE', -- ACTIVE, REVOKED
    client_version VARCHAR(32) DEFAULT '1.0.0',
    last_seen_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 15. Comandos Criptográficamente Firmados (Backend -> Cliente)
CREATE TABLE IF NOT EXISTS commands (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    action VARCHAR(64) NOT NULL,
    params_json TEXT DEFAULT '{}',
    nonce VARCHAR(128) NOT NULL UNIQUE,
    issued_at VARCHAR(64) NOT NULL,
    expires_at VARCHAR(64) NOT NULL,
    signature TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'ISSUED', -- ISSUED, DISPATCHED, EXECUTED, EXPIRED, FAILED, REJECTED
    created_at VARCHAR(64) NOT NULL
);

-- 16. Resultados Autenticados de Ejecución (Cliente -> Backend)
CREATE TABLE IF NOT EXISTS command_results (
    id VARCHAR(64) PRIMARY KEY,
    command_id VARCHAR(64) NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    action VARCHAR(64) NOT NULL,
    success INTEGER DEFAULT 0,
    result_json TEXT DEFAULT '{}',
    error_message TEXT,
    device_signature TEXT,
    reported_at VARCHAR(64) NOT NULL
);

-- 17. Lista de Supresión (Opt-out) por Tenant
CREATE TABLE IF NOT EXISTS suppression_list (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    identifier_hash VARCHAR(128) NOT NULL,
    identifier_type VARCHAR(32) NOT NULL,
    reason VARCHAR(64) DEFAULT 'OPT_OUT',
    created_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_suppression_tenant_hash UNIQUE (tenant_id, identifier_hash)
);

-- 18. Bitácora Interna de Actividades por Lead
CREATE TABLE IF NOT EXISTS lead_activity (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    action_type VARCHAR(64) NOT NULL,
    details_json TEXT DEFAULT '{}',
    actor_id VARCHAR(64),
    created_at VARCHAR(64) NOT NULL
);

-- 19. Cuentas de LinkedIn Conectadas (Unidad Facturable - Workstream 5.3)
CREATE TABLE IF NOT EXISTS linkedin_accounts (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(64) REFERENCES usuarios(id) ON DELETE SET NULL,
    device_id VARCHAR(64) REFERENCES devices(id) ON DELETE SET NULL,
    account_name VARCHAR(255) NOT NULL,
    profile_url TEXT,
    linkedin_urn VARCHAR(128),
    status VARCHAR(32) DEFAULT 'WARMUP',
    warmup_day INTEGER DEFAULT 1,
    daily_invite_limit INTEGER DEFAULT 15,
    invites_sent_today INTEGER DEFAULT 0,
    last_action_at VARCHAR(64),
    health_score NUMERIC(5, 2) DEFAULT 100.0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 20. Cuentas de WhatsApp Conectadas (Warm Outreach Estricto - Workstream 5.3)
CREATE TABLE IF NOT EXISTS whatsapp_accounts (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    phone_number VARCHAR(64) NOT NULL,
    account_name VARCHAR(255),
    status VARCHAR(32) DEFAULT 'ACTIVE',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 21. Candidatos de Correo y Evidencia OSINT (Workstream 5.3 & 5.6)
CREATE TABLE IF NOT EXISTS email_candidates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    candidate_email VARCHAR(255) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    evidence_url TEXT,
    confidence_score NUMERIC(5, 2) DEFAULT 0.0,
    verification_status VARCHAR(32) DEFAULT 'UNVERIFIED',
    verification_provider VARCHAR(64),
    verification_cost_cents INTEGER DEFAULT 0,
    created_at VARCHAR(64) NOT NULL
);

-- 22. Registro de Consentimiento y Base de Licitud (Workstream 5.4 - Ley 21.719)
CREATE TABLE IF NOT EXISTS consent_records (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    channel VARCHAR(32) NOT NULL,
    legal_basis VARCHAR(64) NOT NULL,
    evidence_text TEXT,
    captured_at VARCHAR(64) NOT NULL
);

-- 23. Libro Mayor de Créditos y Límites Comerciales (Workstream 5.3 & 5.9)
CREATE TABLE IF NOT EXISTS credit_ledger (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(64),
    credit_type VARCHAR(32) NOT NULL,
    delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    description TEXT,
    created_at VARCHAR(64) NOT NULL
);

-- 24. Eventos de Uso y Costos (Workstream 5.6 & 5.9)
CREATE TABLE IF NOT EXISTS usage_events (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(64),
    event_type VARCHAR(64) NOT NULL,
    provider VARCHAR(64),
    cost_usd NUMERIC(10, 4) DEFAULT 0.0,
    credits_consumed INTEGER DEFAULT 0,
    details_json TEXT DEFAULT '{}',
    created_at VARCHAR(64) NOT NULL
);

-- 25. Contadores de Uso por Ciclo
CREATE TABLE IF NOT EXISTS usage_counters (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cycle_start VARCHAR(64) NOT NULL,
    cycle_end VARCHAR(64) NOT NULL,
    leads_activated INTEGER DEFAULT 0,
    actions_executed INTEGER DEFAULT 0,
    credits_consumed INTEGER DEFAULT 0,
    verification_cost_usd NUMERIC(10, 4) DEFAULT 0.0,
    security_incidents INTEGER DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 26. Versiones de Catálogo de Selectores Firmados (GLOBAL: Sin RLS por Tenant)
CREATE TABLE IF NOT EXISTS selector_versions (
    version VARCHAR(32) PRIMARY KEY,
    catalog_json TEXT NOT NULL,
    signature VARCHAR(128) NOT NULL,
    min_client_version VARCHAR(32) DEFAULT '1.0.0',
    is_active INTEGER DEFAULT 1,
    published_at VARCHAR(64) NOT NULL
);

-- 27. Estado de Salud y Degradación Segura por Acción (GLOBAL: Sin RLS por Tenant)
CREATE TABLE IF NOT EXISTS action_status (
    action VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) DEFAULT 'ACTIVE',
    pause_reason TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    updated_at VARCHAR(64) NOT NULL
);

-- 28. Bitácora de Fallos de Selectores (Contexto Sanitizado sin PII)
CREATE TABLE IF NOT EXISTS selector_failure_logs (
    id VARCHAR(64) PRIMARY KEY,
    action VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) REFERENCES tenants(id) ON DELETE SET NULL,
    command_id VARCHAR(64),
    context_json TEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL
);

-- 29. Suscripciones Comerciales (Workstream 5.9)
CREATE TABLE IF NOT EXISTS subscriptions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(64),
    provider VARCHAR(32) NOT NULL,
    provider_subscription_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'trialing',
    plan_type VARCHAR(32) NOT NULL DEFAULT 'MONTHLY',
    billing_country VARCHAR(8) NOT NULL,
    price_usd NUMERIC(10, 2) NOT NULL DEFAULT 15.00,
    price_lock_until VARCHAR(64),
    current_period_start VARCHAR(64),
    current_period_end VARCHAR(64),
    grace_period_days INTEGER DEFAULT 3,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 30. Límites Comerciales y Entitlements por Tenant (Workstream 5.9)
CREATE TABLE IF NOT EXISTS entitlements (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    subscription_id VARCHAR(64),
    leads_limit_cycle INTEGER NOT NULL DEFAULT 500,
    credits_limit_cycle INTEGER NOT NULL DEFAULT 100,
    max_linkedin_accounts INTEGER NOT NULL DEFAULT 1,
    allow_whatsapp INTEGER NOT NULL DEFAULT 0,
    is_trial INTEGER NOT NULL DEFAULT 0,
    trial_end VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 31. Registro Idempotente de Webhooks de Pasarelas de Pago (GLOBAL: Sin RLS por Tenant)
CREATE TABLE IF NOT EXISTS payment_webhook_events (
    id VARCHAR(128) PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload_json TEXT NOT NULL,
    processed_at VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'PROCESSED'
);

-- ==============================================================================
-- ÍNDICES DE RENDIMIENTO Y SEGURIDAD MULTI-TENANT
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado);
CREATE INDEX IF NOT EXISTS idx_leads_tenant_url ON leads(tenant_id, perfil_url);
CREATE INDEX IF NOT EXISTS idx_usuarios_tenant ON usuarios(tenant_id);
CREATE INDEX IF NOT EXISTS idx_secuencias_tenant ON secuencias(tenant_id);
CREATE INDEX IF NOT EXISTS idx_listas_tenant ON listas_leads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenants_parent ON tenants(parent_tenant_id);
CREATE INDEX IF NOT EXISTS idx_suscripciones_tenant ON suscripciones(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_ts ON audit_logs(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_leads_perfil ON leads(perfil_url);
CREATE INDEX IF NOT EXISTS idx_leads_en_lista_lead ON leads_en_lista(lead_id);
CREATE INDEX IF NOT EXISTS idx_leads_secuencia_lead ON leads_en_secuencia(lead_id);
CREATE INDEX IF NOT EXISTS idx_historial_lead ON historial_actividades(lead_id);
CREATE INDEX IF NOT EXISTS idx_mensajes_lead ON mensajes_linkedin(lead_id);
CREATE INDEX IF NOT EXISTS idx_correos_lead ON correos_electronicos(lead_id);
CREATE INDEX IF NOT EXISTS idx_mensajes_whatsapp_lead ON mensajes_whatsapp(lead_id);
CREATE INDEX IF NOT EXISTS idx_pasos_secuencia ON pasos_secuencia(secuencia_id);
CREATE INDEX IF NOT EXISTS idx_leads_secuencia ON leads_en_secuencia(secuencia_id, estado);
CREATE INDEX IF NOT EXISTS idx_leads_lista ON leads_en_lista(lista_id);
CREATE INDEX IF NOT EXISTS idx_secuencia_listas ON secuencia_listas(secuencia_id);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_module ON system_logs(module);
CREATE INDEX IF NOT EXISTS idx_devices_tenant ON devices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_commands_device ON commands(device_id);
CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);
CREATE INDEX IF NOT EXISTS idx_command_results_cmd ON command_results(command_id);
CREATE INDEX IF NOT EXISTS idx_suppression_hash ON suppression_list(tenant_id, identifier_hash);
CREATE INDEX IF NOT EXISTS idx_lead_activity_lead ON lead_activity(lead_id, created_at);
CREATE INDEX IF NOT EXISTS idx_lead_activity_tenant ON lead_activity(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_linkedin_accounts_tenant ON linkedin_accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_accounts_tenant ON whatsapp_accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_email_candidates_lead ON email_candidates(lead_id);
CREATE INDEX IF NOT EXISTS idx_consent_records_lead ON consent_records(lead_id);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_tenant ON credit_ledger(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_tenant ON usage_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_type ON usage_events(event_type);
CREATE INDEX IF NOT EXISTS idx_usage_counters_tenant ON usage_counters(tenant_id);
CREATE INDEX IF NOT EXISTS idx_selector_failures_action ON selector_failure_logs(action);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_tenant ON entitlements(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_provider ON payment_webhook_events(provider, event_type);

-- ==============================================================================
-- POLÍTICAS DE ROW-LEVEL SECURITY (RLS) Y FORCE RLS
-- ==============================================================================

-- Macro / regla estándar de aislamiento multi-tenant:
-- 1. Super Admin explícito (is_super_admin = 'true') concede bypass administrativo.
-- 2. Tenant actual exacto (NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL AND tenant_id = app.current_tenant_id).
-- 3. Modo cartera de agencia explícito (allow_agency_subtenants = 'true') permite acceder a subtenants donde parent_tenant_id = app.current_tenant_id.
-- 4. Sin tenant y sin superadmin -> NULLIF(...) IS NOT NULL es FALSO -> 0 filas accesibles (fail-closed).

-- ==============================================================================
-- AUTORIZACIÓN CRIPTOGRÁFICA Y CONTROL DE SUPERADMINISTRADOR (TASK-04C)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS system_admin_keys (
    key_name VARCHAR(64) PRIMARY KEY,
    key_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

REVOKE ALL ON system_admin_keys FROM PUBLIC;
REVOKE ALL ON system_admin_keys FROM nexus_app_role;
REVOKE ALL ON system_admin_keys FROM nexus_app;

INSERT INTO system_admin_keys (key_name, key_hash)
VALUES ('super_admin_bypass', encode(digest('nexus_superadmin_secure_key_2026', 'sha256'), 'hex'))
ON CONFLICT (key_name) DO UPDATE 
SET key_hash = EXCLUDED.key_hash;

CREATE OR REPLACE FUNCTION public.verify_super_admin_context()
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    provided_token TEXT;
    stored_hash TEXT;
BEGIN
    -- 1. Si el usuario de sesión es administrador nativo (ej. nexus_admin o postgres)
    IF SESSION_USER IN ('nexus_admin', 'postgres') THEN
        RETURN (pg_catalog.current_setting('app.is_super_admin', true) = 'true');
    END IF;

    -- 2. Para roles de aplicación (nexus_app), se exige bandera 'true' Y token criptográfico válido
    IF pg_catalog.current_setting('app.is_super_admin', true) <> 'true' THEN
        RETURN FALSE;
    END IF;

    provided_token := pg_catalog.current_setting('app.super_admin_token', true);
    IF provided_token IS NULL OR provided_token = '' THEN
        RETURN FALSE;
    END IF;

    -- Consulta estrictamente cualificada a la tabla del esquema public (inmune a manipulación de search_path o pg_temp)
    SELECT key_hash INTO stored_hash 
    FROM public.system_admin_keys 
    WHERE key_name = 'super_admin_bypass';

    IF stored_hash IS NULL THEN
        RETURN FALSE;
    END IF;

    RETURN (pg_catalog.encode(public.digest(provided_token, 'sha256'), 'hex') = stored_hash);
END;
$$;

REVOKE ALL ON FUNCTION public.verify_super_admin_context() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.verify_super_admin_context() TO nexus_app_role, nexus_app;
REVOKE ALL ON TABLE public.system_admin_keys FROM PUBLIC, nexus_app_role, nexus_app;

-- 1. Tenants (Jerarquía de organizaciones)
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_tenants_policy ON tenants;
CREATE POLICY rls_tenants_policy ON tenants
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                id = current_setting('app.current_tenant_id', true)
                OR parent_tenant_id = current_setting('app.current_tenant_id', true)
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                id = current_setting('app.current_tenant_id', true)
                OR parent_tenant_id = current_setting('app.current_tenant_id', true)
            )
        )
    );

-- 2. Suscripciones
ALTER TABLE suscripciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE suscripciones FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_suscripciones_policy ON suscripciones;
CREATE POLICY rls_suscripciones_policy ON suscripciones
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 3. Usuarios
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuarios FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_usuarios_policy ON usuarios;
CREATE POLICY rls_usuarios_policy ON usuarios
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 4. Leads
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_policy ON leads;
CREATE POLICY rls_leads_policy ON leads
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 5. Listas de Leads
ALTER TABLE listas_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE listas_leads FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_listas_policy ON listas_leads;
CREATE POLICY rls_listas_policy ON listas_leads
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 6. Secuencias
ALTER TABLE secuencias ENABLE ROW LEVEL SECURITY;
ALTER TABLE secuencias FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_secuencias_policy ON secuencias;
CREATE POLICY rls_secuencias_policy ON secuencias
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 7. Pasos Secuencia (Aislados a través de la secuencia padre protegida)
ALTER TABLE pasos_secuencia ENABLE ROW LEVEL SECURITY;
ALTER TABLE pasos_secuencia FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_pasos_policy ON pasos_secuencia;
CREATE POLICY rls_pasos_policy ON pasos_secuencia
    FOR ALL
    USING (
        verify_super_admin_context()
        OR secuencia_id IN (SELECT id FROM secuencias)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR secuencia_id IN (SELECT id FROM secuencias)
    );

-- 8. Leads en Lista (Tabla Puente: Protege tanto lead_id como lista_id)
ALTER TABLE leads_en_lista ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads_en_lista FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_lista_policy ON leads_en_lista;
CREATE POLICY rls_leads_lista_policy ON leads_en_lista
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (lead_id IN (SELECT id FROM leads) AND lista_id IN (SELECT id FROM listas_leads))
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (lead_id IN (SELECT id FROM leads) AND lista_id IN (SELECT id FROM listas_leads))
    );

-- 9. Leads en Secuencia (Tabla Puente: Protege tanto lead_id como secuencia_id)
ALTER TABLE leads_en_secuencia ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads_en_secuencia FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_sec_policy ON leads_en_secuencia;
CREATE POLICY rls_leads_sec_policy ON leads_en_secuencia
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (lead_id IN (SELECT id FROM leads) AND secuencia_id IN (SELECT id FROM secuencias))
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (lead_id IN (SELECT id FROM leads) AND secuencia_id IN (SELECT id FROM secuencias))
    );

-- 10. Secuencia Listas (Tabla Puente: Protege tanto secuencia_id como lista_id)
ALTER TABLE secuencia_listas ENABLE ROW LEVEL SECURITY;
ALTER TABLE secuencia_listas FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_secuencia_listas_policy ON secuencia_listas;
CREATE POLICY rls_secuencia_listas_policy ON secuencia_listas
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (secuencia_id IN (SELECT id FROM secuencias) AND lista_id IN (SELECT id FROM listas_leads))
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (secuencia_id IN (SELECT id FROM secuencias) AND lista_id IN (SELECT id FROM listas_leads))
    );

-- 11. Mensajes de LinkedIn (Aislados a través de leads)
ALTER TABLE mensajes_linkedin ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensajes_linkedin FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_mensajes_policy ON mensajes_linkedin;
CREATE POLICY rls_mensajes_policy ON mensajes_linkedin
    FOR ALL
    USING (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    );

-- 12. Correos Electrónicos Outreach (Aislados a través de leads)
ALTER TABLE correos_electronicos ENABLE ROW LEVEL SECURITY;
ALTER TABLE correos_electronicos FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_correos_policy ON correos_electronicos;
CREATE POLICY rls_correos_policy ON correos_electronicos
    FOR ALL
    USING (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    );

-- 13. Mensajes de WhatsApp Web (Aislados a través de leads)
ALTER TABLE mensajes_whatsapp ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensajes_whatsapp FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_mensajes_whatsapp_policy ON mensajes_whatsapp;
CREATE POLICY rls_mensajes_whatsapp_policy ON mensajes_whatsapp
    FOR ALL
    USING (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    );

-- 14. Interacciones Sociales (Aisladas a través de leads)
ALTER TABLE interacciones_sociales ENABLE ROW LEVEL SECURITY;
ALTER TABLE interacciones_sociales FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_interacciones_policy ON interacciones_sociales;
CREATE POLICY rls_interacciones_policy ON interacciones_sociales
    FOR ALL
    USING (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    );

-- 15. Historial de Actividades (Aislado a través de leads)
ALTER TABLE historial_actividades ENABLE ROW LEVEL SECURITY;
ALTER TABLE historial_actividades FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_historial_policy ON historial_actividades;
CREATE POLICY rls_historial_policy ON historial_actividades
    FOR ALL
    USING (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        verify_super_admin_context()
        OR lead_id IN (SELECT id FROM leads)
    );

-- 16. Audit Logs (Sintaxis SQL corregida con USING y WITH CHECK)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_audit_logs_policy ON audit_logs;
CREATE POLICY rls_audit_logs_policy ON audit_logs
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 17. System Logs
ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_system_logs_policy ON system_logs;
CREATE POLICY rls_system_logs_policy ON system_logs
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 18. Dispositivos (devices)
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE devices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_devices_policy ON devices;
CREATE POLICY rls_devices_policy ON devices
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 19. Comandos (commands)
ALTER TABLE commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE commands FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_commands_policy ON commands;
CREATE POLICY rls_commands_policy ON commands
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 20. Resultados de Comandos (command_results)
ALTER TABLE command_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE command_results FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_command_results_policy ON command_results;
CREATE POLICY rls_command_results_policy ON command_results
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 21. Lista de Supresión (suppression_list)
ALTER TABLE suppression_list ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppression_list FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_suppression_list_policy ON suppression_list;
CREATE POLICY rls_suppression_list_policy ON suppression_list
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 22. Bitácora de Acciones de Leads (lead_activity)
ALTER TABLE lead_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_activity FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_lead_activity_policy ON lead_activity;
CREATE POLICY rls_lead_activity_policy ON lead_activity
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 23. Cuentas de LinkedIn (linkedin_accounts)
ALTER TABLE linkedin_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_accounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_linkedin_accounts_policy ON linkedin_accounts;
CREATE POLICY rls_linkedin_accounts_policy ON linkedin_accounts
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 24. Cuentas de WhatsApp (whatsapp_accounts)
ALTER TABLE whatsapp_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_accounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_whatsapp_accounts_policy ON whatsapp_accounts;
CREATE POLICY rls_whatsapp_accounts_policy ON whatsapp_accounts
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 25. Candidatos de Correo (email_candidates)
ALTER TABLE email_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_email_candidates_policy ON email_candidates;
CREATE POLICY rls_email_candidates_policy ON email_candidates
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 26. Consentimiento y Licitud (consent_records)
ALTER TABLE consent_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_consent_records_policy ON consent_records;
CREATE POLICY rls_consent_records_policy ON consent_records
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 27. Libro Mayor de Créditos (credit_ledger)
ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_credit_ledger_policy ON credit_ledger;
CREATE POLICY rls_credit_ledger_policy ON credit_ledger
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 28. Eventos de Uso (usage_events)
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_usage_events_policy ON usage_events;
CREATE POLICY rls_usage_events_policy ON usage_events
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 29. Contadores de Uso (usage_counters)
ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_counters FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_usage_counters_policy ON usage_counters;
CREATE POLICY rls_usage_counters_policy ON usage_counters
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 30. Bitácora de Fallos de Selectores (selector_failure_logs)
ALTER TABLE selector_failure_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE selector_failure_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_selector_failure_logs_policy ON selector_failure_logs;
CREATE POLICY rls_selector_failure_logs_policy ON selector_failure_logs
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 31. Suscripciones Comerciales (subscriptions)
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_subscriptions_policy ON subscriptions;
CREATE POLICY rls_subscriptions_policy ON subscriptions
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- 32. Entitlements Comerciales (entitlements)
ALTER TABLE entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE entitlements FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_entitlements_policy ON entitlements;
CREATE POLICY rls_entitlements_policy ON entitlements
    FOR ALL
    USING (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    )
    WITH CHECK (
        verify_super_admin_context()
        OR (
            NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
            AND (
                tenant_id = current_setting('app.current_tenant_id', true)
                OR (
                    current_setting('app.allow_agency_subtenants', true) = 'true'
                    AND tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true))
                )
            )
        )
    );

-- ==============================================================================
-- ROL DE APLICACIÓN POSTGRESQL CON PRIVILEGIOS MÍNIMOS (Least Privilege)
-- ==============================================================================

-- Creación/Aseguramiento idempotente del rol de aplicación 'nexus_app_role'
-- Sin SUPERUSER, sin BYPASSRLS, sin CREATEDB, sin CREATEROLE
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app_role') THEN
        CREATE ROLE nexus_app_role NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    ELSE
        ALTER ROLE nexus_app_role NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

-- Concesión de privilegios mínimos sobre esquema y tablas públicas
GRANT USAGE ON SCHEMA public TO nexus_app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexus_app_role;

-- Privilegios por defecto para futuras tablas y secuencias creadas por el rol administrador
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_app_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO nexus_app_role;
