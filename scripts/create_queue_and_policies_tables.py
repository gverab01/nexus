"""
NexusReach Pro - Migration: Create Central Task Queue and Task Rate Policies (TASK-QUEUE-01)
Crea las tablas `cola_tareas_central` y `politicas_ritmo_tareas` con Row-Level Security (RLS)
y siembra las políticas de ritmo recomendadas para cada tenant existente.
"""

import os
import sys
import json
import psycopg
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_superadmin_rls_secret

POSTGRES_ADMIN_URL = os.environ.get("POSTGRES_ADMIN_URL") or "postgresql://nexus_admin:OCYWedh9XE1mZ8MpX0HRWBHy0jswLnvV@127.0.0.1:5432/nexusreach_prod"
POSTGRES_APP_URL = os.environ.get("POSTGRES_APP_URL") or os.environ.get("DATABASE_URL") or "postgresql://nexus_app:8kiW5ZTyGKV0hQvrmYcCeSlyM2pP84Ad@127.0.0.1:5432/nexusreach_prod"

POLITICAS_BASE = [
    {
        "tipo_tarea": "LI_INVITE",
        "descripcion": "Enviar Invitación con/sin nota",
        "limite_diario": 50,
        "pausa_min_seg": 240,  # 4 min
        "pausa_max_seg": 480,  # 8 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_VISIT",
        "descripcion": "Visitar perfil orgánicamente",
        "limite_diario": 70,
        "pausa_min_seg": 90,   # 1.5 min
        "pausa_max_seg": 180,  # 3 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_ENRICH",
        "descripcion": "Sincronizar y enriquecer perfil en vivo",
        "limite_diario": 50,
        "pausa_min_seg": 120,  # 2 min
        "pausa_max_seg": 240,  # 4 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_MESSAGE",
        "descripcion": "Mensaje directo a conexión",
        "limite_diario": 35,
        "pausa_min_seg": 180,  # 3 min
        "pausa_max_seg": 360,  # 6 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_ENDORSE",
        "descripcion": "Validar aptitudes (Skill Endorse)",
        "limite_diario": 25,
        "pausa_min_seg": 120,  # 2 min
        "pausa_max_seg": 240,  # 4 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_REACT",
        "descripcion": "Reaccionar a última publicación (Like/Celeb)",
        "limite_diario": 40,
        "pausa_min_seg": 90,   # 1.5 min
        "pausa_max_seg": 180,  # 3 min
        "nivel_riesgo": "MEDIO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_COMMENT",
        "descripcion": "Comentario asistido en publicación",
        "limite_diario": 12,
        "pausa_min_seg": 300,  # 5 min
        "pausa_max_seg": 600,  # 10 min
        "nivel_riesgo": "ALTO",
        "activo": True
    },
    {
        "tipo_tarea": "EMAIL_OUTREACH",
        "descripcion": "Envío de correo corporativo frío (SMTP)",
        "limite_diario": 60,
        "pausa_min_seg": 60,   # 1 min
        "pausa_max_seg": 150,  # 2.5 min
        "nivel_riesgo": "MEDIO",
        "activo": True
    },
    {
        "tipo_tarea": "ZOHO_SYNC",
        "descripcion": "Cruce y validación con Zoho CRM",
        "limite_diario": 300,
        "pausa_min_seg": 3,
        "pausa_max_seg": 8,
        "nivel_riesgo": "BAJO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_WITHDRAW_STALE",
        "descripcion": "Retiro de invitaciones vencidas (>21 d)",
        "limite_diario": 25,
        "pausa_min_seg": 60,   # 1 min
        "pausa_max_seg": 120,  # 2 min
        "nivel_riesgo": "BAJO",
        "activo": True
    },
    {
        "tipo_tarea": "LI_SYNC_ACCEPTED",
        "descripcion": "Detección de nuevas conexiones aceptadas",
        "limite_diario": 10,
        "pausa_min_seg": 60,
        "pausa_max_seg": 120,
        "nivel_riesgo": "BAJO",
        "activo": True
    }
]

def migrate():
    admin_url = POSTGRES_ADMIN_URL
    print(f"[MIGRATION] Conectando a PostgreSQL administrativo...")
    with psycopg.connect(admin_url) as conn:
        with conn.cursor() as cur:
            # 1. Tabla de políticas de ritmo
            print("[MIGRATION] Creando tabla politicas_ritmo_tareas...")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS politicas_ritmo_tareas (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                tipo_tarea VARCHAR(50) NOT NULL,
                descripcion TEXT,
                limite_diario INTEGER NOT NULL DEFAULT 50,
                pausa_min_seg INTEGER NOT NULL DEFAULT 120,
                pausa_max_seg INTEGER NOT NULL DEFAULT 240,
                nivel_riesgo VARCHAR(20) NOT NULL DEFAULT 'ALTO',
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_tenant_tipo_tarea UNIQUE (tenant_id, tipo_tarea)
            );
            """)

            # 2. Tabla centralizada de tareas
            print("[MIGRATION] Creando tabla cola_tareas_central...")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS cola_tareas_central (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                lead_id TEXT REFERENCES leads(id) ON DELETE SET NULL,
                tipo_tarea VARCHAR(50) NOT NULL,
                prioridad INTEGER NOT NULL DEFAULT 5,
                estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                resultado_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                intentos INTEGER NOT NULL DEFAULT 0,
                max_intentos INTEGER NOT NULL DEFAULT 3,
                error_detalle TEXT,
                programado_para TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                iniciado_at TIMESTAMPTZ,
                finalizado_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)

            # 3. Índices de alta velocidad
            print("[MIGRATION] Creando índices de optimización...")
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cola_despacho_prioridad 
            ON cola_tareas_central (tenant_id, estado, programado_para, prioridad);

            CREATE INDEX IF NOT EXISTS idx_cola_lead 
            ON cola_tareas_central (tenant_id, lead_id);

            CREATE INDEX IF NOT EXISTS idx_cola_tipo_fecha 
            ON cola_tareas_central (tenant_id, tipo_tarea, estado, finalizado_at);
            """)

            # 4. RLS y permisos
            print("[MIGRATION] Configurando Row-Level Security y permisos para nexus_app...")
            for tbl in ["politicas_ritmo_tareas", "cola_tareas_central"]:
                cur.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
                cur.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
                cur.execute(f"DROP POLICY IF EXISTS rls_{tbl}_policy ON {tbl};")
                cur.execute(f"""
                CREATE POLICY rls_{tbl}_policy ON {tbl}
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
                cur.execute(f"GRANT ALL PRIVILEGES ON {tbl} TO nexus_app;")

            # 5. Sembrar políticas base para todos los tenants existentes
            print("[MIGRATION] Sembrando políticas de ritmo base para tenants...")
            cur.execute("SELECT id FROM tenants;")
            tenants = [r[0] for r in cur.fetchall()]
            for t_id in tenants:
                for pol in POLITICAS_BASE:
                    cur.execute("""
                    INSERT INTO politicas_ritmo_tareas 
                    (tenant_id, tipo_tarea, descripcion, limite_diario, pausa_min_seg, pausa_max_seg, nivel_riesgo, activo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, tipo_tarea) DO NOTHING;
                    """, (
                        t_id, pol["tipo_tarea"], pol["descripcion"], pol["limite_diario"],
                        pol["pausa_min_seg"], pol["pausa_max_seg"], pol["nivel_riesgo"], pol["activo"]
                    ))

        conn.commit()
    print(f"[MIGRATION] Migración completada con éxito. Políticas aplicadas a {len(tenants)} tenants.")

if __name__ == "__main__":
    migrate()
