-- ==============================================================================
-- NEXUSREACH PRO - ESQUEMA DE BASE DE DATOS POSTGRESQL MULTI-TENANT CON RLS
-- Diseñado para entornos de Nube (AWS RDS, Supabase, Neon.tech, Railway, Render)
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
    estado VARCHAR(32) DEFAULT 'ACTIVO',               -- ACTIVO, SUSPENDIDO, CANCELADO
    modelo_cobro_cliente VARCHAR(32) DEFAULT 'POR_PUESTO', -- POR_PUESTO, POR_REUNION, FEE_FIJO
    tarifa_por_reunion NUMERIC(10, 2) DEFAULT 0.0,
    precio_cliente_por_puesto NUMERIC(10, 2) DEFAULT 0.0,
    fee_fijo_mensual NUMERIC(10, 2) DEFAULT 0.0,
    puestos_asignados INTEGER DEFAULT 1,
    notas TEXT,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- Suscripciones y Bolsas de Puestos Comerciales
CREATE TABLE IF NOT EXISTS suscripciones (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    periodicidad VARCHAR(32) NOT NULL DEFAULT 'MENSUAL', -- MENSUAL, ANUAL
    estado VARCHAR(32) NOT NULL DEFAULT 'ACTIVA',        -- ACTIVA, TRIAL, SUSPENDIDA, CANCELADA
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
    rol VARCHAR(64) DEFAULT 'COMPANY_MEMBER', -- SUPER_ADMIN, AGENCY_ADMIN, COMPANY_ADMIN, COMPANY_MEMBER, INDIVIDUAL
    puesto_activo INTEGER DEFAULT 1,
    estado VARCHAR(32) DEFAULT 'ACTIVO',
    suscripcion_estado VARCHAR(32) DEFAULT 'activa',
    suscripcion_plan VARCHAR(32) DEFAULT 'Pro',
    suscripcion_expira VARCHAR(64),
    ultimo_login VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- Configuración de Seguridad y Límites Anti-Baneo
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
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'ten_superadmin' REFERENCES tenants(id) ON DELETE CASCADE,
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
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_leads_tenant_url UNIQUE (tenant_id, perfil_url)
);

-- 2. Listas de Prospectos (Audiencias / Segmentos)
CREATE TABLE IF NOT EXISTS listas_leads (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'ten_superadmin' REFERENCES tenants(id) ON DELETE CASCADE,
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    termino_busqueda VARCHAR(255),
    estado VARCHAR(32) DEFAULT 'ACTIVA',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

-- 3. Relación Leads <-> Listas
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
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'ten_superadmin' REFERENCES tenants(id) ON DELETE CASCADE,
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

-- 6. Leads dentro de la Secuencia
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

-- 7. Relación Secuencias <-> Listas
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

-- 10. Interacciones Sociales
CREATE TABLE IF NOT EXISTS interacciones_sociales (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tipo VARCHAR(64) NOT NULL,
    post_url TEXT,
    post_snippet TEXT,
    comentario_texto TEXT,
    fecha VARCHAR(64),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

-- 11. Historial de Actividades
CREATE TABLE IF NOT EXISTS historial_actividades (
    id BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(128) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tipo_evento VARCHAR(64) NOT NULL,
    descripcion TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    timestamp VARCHAR(64) NOT NULL
);

-- 12. Logs de Sistema
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

-- ==============================================================================
-- ÍNDICES DE ALTO RENDIMIENTO
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
CREATE INDEX IF NOT EXISTS idx_historial_lead ON historial_actividades(lead_id);
CREATE INDEX IF NOT EXISTS idx_mensajes_lead ON mensajes_linkedin(lead_id);
CREATE INDEX IF NOT EXISTS idx_correos_lead ON correos_electronicos(lead_id);
CREATE INDEX IF NOT EXISTS idx_pasos_secuencia ON pasos_secuencia(secuencia_id);
CREATE INDEX IF NOT EXISTS idx_leads_secuencia ON leads_en_secuencia(secuencia_id, estado);
CREATE INDEX IF NOT EXISTS idx_leads_lista ON leads_en_lista(lista_id);
CREATE INDEX IF NOT EXISTS idx_secuencia_listas ON secuencia_listas(secuencia_id);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_module ON system_logs(module);
CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);

-- ==============================================================================
-- POLÍTICAS DE ROW-LEVEL SECURITY (RLS) - SEGURIDAD A NIVEL DE MOTOR POSTGRESQL
-- ==============================================================================

-- 1. Leads
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_policy ON leads;
CREATE POLICY rls_leads_policy ON leads
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    );

-- 2. Listas de Leads
ALTER TABLE listas_leads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_listas_policy ON listas_leads;
CREATE POLICY rls_listas_policy ON listas_leads
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    );

-- 3. Secuencias
ALTER TABLE secuencias ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_secuencias_policy ON secuencias;
CREATE POLICY rls_secuencias_policy ON secuencias
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    );

-- 4. Pasos Secuencia (Aislados a través de la secuencia padre protegida)
ALTER TABLE pasos_secuencia ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_pasos_policy ON pasos_secuencia;
CREATE POLICY rls_pasos_policy ON pasos_secuencia
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR secuencia_id IN (SELECT id FROM secuencias)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR secuencia_id IN (SELECT id FROM secuencias)
    );

-- 5. Leads en Secuencia (Aislados a través de leads protegidos)
ALTER TABLE leads_en_secuencia ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_sec_policy ON leads_en_secuencia;
CREATE POLICY rls_leads_sec_policy ON leads_en_secuencia
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    );

-- 6. Leads en Lista (Aislados a través de leads protegidos)
ALTER TABLE leads_en_lista ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_leads_lista_policy ON leads_en_lista;
CREATE POLICY rls_leads_lista_policy ON leads_en_lista
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    );

-- 7. Mensajes de LinkedIn (Aislados a través del lead)
ALTER TABLE mensajes_linkedin ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_mensajes_policy ON mensajes_linkedin;
CREATE POLICY rls_mensajes_policy ON mensajes_linkedin
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    );

-- 8. Correos Electrónicos (Aislados a través del lead)
ALTER TABLE correos_electronicos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_correos_policy ON correos_electronicos;
CREATE POLICY rls_correos_policy ON correos_electronicos
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    );

-- 9. Historial de Actividades (Aislado a través del lead)
ALTER TABLE historial_actividades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_historial_policy ON historial_actividades;
CREATE POLICY rls_historial_policy ON historial_actividades
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR lead_id IN (SELECT id FROM leads)
    );

-- 10. Audit Logs
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_audit_logs_policy ON audit_logs;
CREATE POLICY rls_audit_logs_policy ON audit_logs
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = current_setting('app.current_tenant_id', true)
        OR tenant_id IN (
            SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
        )
    );
