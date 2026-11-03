-- ==============================================================================
-- NEXUSREACH PRO - INICIALIZACIÓN DE ROLES PARA PRUEBAS DE INTEGRACIÓN (TASK-04B)
-- ==============================================================================

-- 1. Crear usuario de aplicación 'nexus_app' con rol 'nexus_app_role' (Sin SUPERUSER, sin BYPASSRLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app') THEN
        CREATE ROLE nexus_app WITH LOGIN PASSWORD 'app_secure_pass_123' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    ELSE
        ALTER ROLE nexus_app WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

-- 2. Conceder rol de aplicación
GRANT nexus_app_role TO nexus_app;

-- 3. Asignar ownership y permisos sobre esquema
GRANT CONNECT ON DATABASE nexusreach_test TO nexus_app;
GRANT USAGE ON SCHEMA public TO nexus_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexus_app;

-- 4. Restricción estricta de tablas de claves de seguridad (TASK-04C)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'system_admin_keys') THEN
        REVOKE ALL ON system_admin_keys FROM PUBLIC, nexus_app_role, nexus_app;
    END IF;
END
$$;

-- 5. Concesión de ejecución de función de verificación criptográfica
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'verify_super_admin_context') THEN
        REVOKE ALL ON FUNCTION verify_super_admin_context() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION verify_super_admin_context() TO nexus_app_role, nexus_app;
    END IF;
END
$$;


