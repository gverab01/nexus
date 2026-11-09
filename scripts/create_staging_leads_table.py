"""
NexusReach Pro - Migration: Create Staging Leads Table for Discovery and Matching
Crea la tabla `staging_leads` con Row-Level Security (RLS) y otorga privilegios a `nexus_app`.
"""

import os
import sys
import psycopg

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

POSTGRES_ADMIN_URL = os.environ.get("POSTGRES_ADMIN_URL") or "postgresql://nexus_admin:OCYWedh9XE1mZ8MpX0HRWBHy0jswLnvV@127.0.0.1:5432/nexusreach_prod"

def migrate():
    print(f"[MIGRATION] Conectando a PostgreSQL administrativo...")
    with psycopg.connect(POSTGRES_ADMIN_URL) as conn:
        with conn.cursor() as cur:
            print("[MIGRATION] Creando tabla staging_leads...")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS staging_leads (
                id VARCHAR(128) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL DEFAULT 'ten_superadmin',
                nombre VARCHAR(255) NOT NULL,
                institucion VARCHAR(255),
                email VARCHAR(255),
                cargo_declarado VARCHAR(255),
                telefono VARCHAR(64),
                origen VARCHAR(64) DEFAULT 'MANUAL',
                zoho_id VARCHAR(64),
                estado VARCHAR(64) DEFAULT 'PENDIENTE',
                candidato_nombre VARCHAR(255),
                candidato_url VARCHAR(500),
                candidato_titular TEXT,
                candidato_cargo VARCHAR(255),
                candidato_institucion VARCHAR(255),
                candidato_ubicacion VARCHAR(255),
                candidato_grado VARCHAR(32),
                score_coincidencia INTEGER DEFAULT 0,
                candidatos_alternativos_json TEXT DEFAULT '[]',
                notas TEXT,
                promovido_lead_id VARCHAR(128),
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            );
            """)

            print("[MIGRATION] Creando índices...")
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_staging_tenant_estado ON staging_leads(tenant_id, estado);
            CREATE INDEX IF NOT EXISTS idx_staging_email ON staging_leads(email);
            CREATE INDEX IF NOT EXISTS idx_staging_zoho_id ON staging_leads(zoho_id);
            """)

            print("[MIGRATION] Configurando RLS y permisos para nexus_app...")
            cur.execute("ALTER TABLE staging_leads ENABLE ROW LEVEL SECURITY;")
            cur.execute("ALTER TABLE staging_leads FORCE ROW LEVEL SECURITY;")
            cur.execute("DROP POLICY IF EXISTS rls_staging_leads_policy ON staging_leads;")
            cur.execute("""
            CREATE POLICY rls_staging_leads_policy ON staging_leads
            FOR ALL
            USING (
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR current_setting('app.is_super_admin', true) = 'true'
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR current_setting('app.is_super_admin', true) = 'true'
            );
            """)
            cur.execute("GRANT ALL PRIVILEGES ON staging_leads TO nexus_app;")

        conn.commit()
    print("[MIGRATION] Tabla staging_leads creada y permisos otorgados exitosamente!")

if __name__ == "__main__":
    migrate()

