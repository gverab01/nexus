import sqlite3
import json
import os
import re
from datetime import datetime
from contextlib import contextmanager

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")))

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def _convert_placeholders(query: str) -> str:
    """Replaces unquoted ? parameter placeholders with %s for PostgreSQL compatibility."""
    if "?" not in query:
        return query
    parts = re.split(r"('(?:''|[^'])*')", query)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("?", "%s")
    return "".join(parts)

class PgCursorWrapper:
    """Cursor wrapper for PostgreSQL that converts SQLite ? placeholders to %s transparently."""
    def __init__(self, cursor):
        self._cur = cursor

    def execute(self, query, params=None):
        pg_query = _convert_placeholders(query)
        if params is not None:
            return self._cur.execute(pg_query, params)
        return self._cur.execute(pg_query)

    def executemany(self, query, params_seq):
        pg_query = _convert_placeholders(query)
        return self._cur.executemany(pg_query, params_seq)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size)

    @property
    def lastrowid(self):
        return getattr(self._cur, "lastrowid", None)

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def __iter__(self):
        return iter(self._cur)

    def close(self):
        return self._cur.close()

class PgConnWrapper:
    """Connection wrapper for PostgreSQL exposing cursor and transaction methods."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return PgCursorWrapper(self._conn.cursor())

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

@contextmanager
def get_db(tenant_id=None, is_super_admin=False):
    """
    Context manager de conexión de base de datos dual:
    - Si DATABASE_URL está configurado: Conecta a PostgreSQL con Row-Level Security (RLS).
    - Si no está configurado: Usa SQLite local leads.db en modo WAL.
    """
    if IS_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise RuntimeError("El paquete 'psycopg' es requerido para conectar a PostgreSQL. Instálalo con pip install psycopg[binary]")

        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        wrapped = PgConnWrapper(conn)
        try:
            # Configurar contexto de sesión RLS en PostgreSQL
            with conn.cursor() as cur:
                if is_super_admin:
                    cur.execute("SET LOCAL app.is_super_admin = 'true';")
                elif tenant_id:
                    cur.execute("SET LOCAL app.is_super_admin = 'false';")
                    cur.execute("SET LOCAL app.current_tenant_id = %s;", (tenant_id,))
                else:
                    cur.execute("SET LOCAL app.is_super_admin = 'true';")
            yield wrapped
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = dict_factory
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_db():
    if IS_POSTGRES:
        # En PostgreSQL, aplicar schema_postgres.sql si no existen las tablas principales
        with get_db(is_super_admin=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'leads'
            """)
            if not cursor.fetchone():
                schema_path = os.path.join(os.path.dirname(__file__), "schema_postgres.sql")
                if os.path.exists(schema_path):
                    with open(schema_path, "r", encoding="utf-8") as f:
                        cursor.execute(f.read())
            now_iso = datetime.now().isoformat()
            seed_default_users(cursor, now_iso)
            seed_default_sequence(cursor, now_iso)
            seed_default_lead_list(cursor, now_iso)
        return
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Tabla de Leads principal
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            cargo_titular TEXT,
            cargo_actual TEXT,
            institucion_actual TEXT,
            ubicacion TEXT,
            grado_red TEXT DEFAULT '2º',
            perfil_url TEXT NOT NULL,
            email TEXT,
            telefono TEXT,
            estado TEXT DEFAULT 'EXTRAIDO',
            siguiendo INTEGER DEFAULT 0,
            siguiendo_desde TEXT,
            invitacion_retirada INTEGER DEFAULT 0,
            fecha_retiro_invitacion TEXT,
            fecha_extraccion TEXT,
            fecha_visita TEXT,
            fecha_invitacion TEXT,
            fecha_conexion TEXT,
            tags TEXT DEFAULT '[]',
            notas TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """)

        # 2. Mensajes de LinkedIn (Secuencias y Drips)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mensajes_linkedin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            campana_nombre TEXT,
            paso_secuencia INTEGER DEFAULT 1,
            contenido TEXT NOT NULL,
            tiene_adjuntos INTEGER DEFAULT 0,
            adjuntos_info TEXT DEFAULT '[]',
            estado TEXT DEFAULT 'PENDIENTE',
            enviado_at TEXT,
            es_leido INTEGER DEFAULT 0,
            leido_at TEXT,
            fue_respondido INTEGER DEFAULT 0,
            respondido_at TEXT,
            respuesta_texto TEXT,
            created_at TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 3. Correos Electrónicos (Email Outreach)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS correos_electronicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            campana_nombre TEXT,
            paso_secuencia INTEGER DEFAULT 1,
            email_destino TEXT NOT NULL,
            asunto TEXT NOT NULL,
            cuerpo TEXT NOT NULL,
            tiene_adjunto INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'PENDIENTE',
            enviado_at TEXT,
            abierto INTEGER DEFAULT 0,
            abierto_at TEXT,
            clickeado INTEGER DEFAULT 0,
            respondido INTEGER DEFAULT 0,
            respondido_at TEXT,
            respuesta_texto TEXT,
            created_at TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 4. Interacciones Sociales (Likes y Comentarios en posts)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS interacciones_sociales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            post_url TEXT,
            post_snippet TEXT,
            comentario_texto TEXT,
            fecha TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 5. Historial y Auditoría cronológica de eventos
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            timestamp TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 6. Configuración de Seguridad y Límites Anti-Baneo
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_seguridad (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            descripcion TEXT,
            updated_at TEXT
        );
        """)

        # 7. Secuencias y Campañas Multicanal Configurables
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS secuencias (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            activa INTEGER DEFAULT 1,
            es_default INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        """)

        # 8. Pasos Atómicos del Árbol de Decisión de la Secuencia
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pasos_secuencia (
            id TEXT PRIMARY KEY,
            secuencia_id TEXT NOT NULL,
            padre_paso_id TEXT,
            condicion_rama TEXT DEFAULT 'DEFAULT',
            tipo_accion TEXT NOT NULL,
            parametros_json TEXT DEFAULT '{}',
            orden INTEGER DEFAULT 1,
            created_at TEXT,
            FOREIGN KEY (secuencia_id) REFERENCES secuencias (id) ON DELETE CASCADE
        );
        """)

        # 9. Asignación y Estado de Leads dentro de la Secuencia
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads_en_secuencia (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            secuencia_id TEXT NOT NULL,
            paso_actual_id TEXT,
            estado TEXT DEFAULT 'EN_CURSO',
            proxima_ejecucion_at TEXT,
            ultimo_resultado_json TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(lead_id, secuencia_id),
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE,
            FOREIGN KEY (secuencia_id) REFERENCES secuencias (id) ON DELETE CASCADE
        );
        """)

        # 10. Listas de Prospectos (Segmentos / Audiencias)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS listas_leads (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            termino_busqueda TEXT,
            estado TEXT DEFAULT 'ACTIVA',
            created_at TEXT,
            updated_at TEXT
        );
        """)

        # 11. Relación Leads <-> Listas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads_en_lista (
            id TEXT PRIMARY KEY,
            lista_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            created_at TEXT,
            UNIQUE(lista_id, lead_id),
            FOREIGN KEY (lista_id) REFERENCES listas_leads (id) ON DELETE CASCADE,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 12. Relación Secuencias <-> Listas de Leads (Públicos asignados)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS secuencia_listas (
            id TEXT PRIMARY KEY,
            secuencia_id TEXT NOT NULL,
            lista_id TEXT NOT NULL,
            activa INTEGER DEFAULT 1,
            auto_ingresar_nuevos INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(secuencia_id, lista_id),
            FOREIGN KEY (secuencia_id) REFERENCES secuencias (id) ON DELETE CASCADE,
            FOREIGN KEY (lista_id) REFERENCES listas_leads (id) ON DELETE CASCADE
        );
        """)

        # 13. Registro de Sucesos y Auditoría Global del Sistema (Activity Log)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level TEXT NOT NULL,
            module TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT DEFAULT '{}',
            lead_id TEXT,
            created_at TEXT
        );
        """)

        # 14. Tenants (Empresas, Agencias y Clientes Sub-Tenants)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            parent_tenant_id TEXT,
            razon_social TEXT NOT NULL,
            tipo_tenant TEXT NOT NULL DEFAULT 'EMPRESA',
            estado TEXT DEFAULT 'ACTIVO',
            modelo_cobro_cliente TEXT DEFAULT 'POR_PUESTO',
            tarifa_por_reunion REAL DEFAULT 0.0,
            precio_cliente_por_puesto REAL DEFAULT 0.0,
            fee_fijo_mensual REAL DEFAULT 0.0,
            puestos_asignados INTEGER DEFAULT 1,
            notas TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (parent_tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 15. Suscripciones y Bolsas de Puestos
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS suscripciones (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL UNIQUE,
            periodicidad TEXT NOT NULL DEFAULT 'MENSUAL',
            estado TEXT NOT NULL DEFAULT 'ACTIVA',
            puestos_contratados INTEGER NOT NULL DEFAULT 1,
            precio_unitario_plataforma REAL DEFAULT 35.0,
            fecha_inicio TEXT NOT NULL,
            fecha_expiracion TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 16. Auditoría y Trazabilidad (Audit Logs OWASP)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            usuario_id TEXT,
            accion TEXT NOT NULL,
            detalle_json TEXT DEFAULT '{}',
            ip_address TEXT,
            timestamp TEXT NOT NULL
        );
        """)

        # 17. Usuarios y Roles (RBAC Multi-Tenant)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            email TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            rol TEXT DEFAULT 'COMPANY_MEMBER',
            puesto_activo INTEGER DEFAULT 1,
            estado TEXT DEFAULT 'ACTIVO',
            suscripcion_estado TEXT DEFAULT 'activa',
            suscripcion_plan TEXT DEFAULT 'Pro',
            suscripcion_expira TEXT,
            ultimo_login TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE SET NULL
        );
        """)

        # Migrar tablas existentes para incorporar tenant_id y columnas requeridas
        migrate_multitenant_schema(cursor)

        # Asegurar columna 'estado' en secuencias si no existe
        try:
            cursor.execute("ALTER TABLE secuencias ADD COLUMN estado TEXT DEFAULT 'PUBLICADA'")
        except Exception:
            pass

        # Índices para búsquedas y consultas rápidas
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_historial_lead ON historial_actividades(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mensajes_lead ON mensajes_linkedin(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_correos_lead ON correos_electronicos(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pasos_secuencia ON pasos_secuencia(secuencia_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_secuencia ON leads_en_secuencia(secuencia_id, estado);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_lista ON leads_en_lista(lista_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_secuencia_listas ON secuencia_listas(secuencia_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_module ON system_logs(module);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);")

        # Cargar defaults de seguridad si no existen
        now_iso = datetime.now().isoformat()
        security_defaults = [
            ("limite_linkedin_diario", "5", "Máximo de invitaciones LinkedIn al día"),
            ("limite_email_workspace_diario", "15", "Máximo de correos Google Workspace al día (Warmup)"),
            ("horario_laboral_activo", "1", "Restringir actividad a horario laboral de oficina (0 o 1)"),
            ("horario_inicio", "09:00", "Hora inicio laboral en Chile (HH:MM)"),
            ("horario_fin", "18:00", "Hora fin laboral en Chile (HH:MM)"),
            ("pausa_linkedin_min_seg", "180", "Pausa mínima entre acciones LinkedIn (segundos)"),
            ("pausa_linkedin_max_seg", "360", "Pausa máxima entre acciones LinkedIn (segundos)"),
            ("pausa_email_min_seg", "480", "Pausa mínima entre emails Google Workspace (segundos)"),
            ("pausa_email_max_seg", "900", "Pausa máxima entre emails Google Workspace (segundos)"),
            ("kill_switch_activado", "0", "Freno de emergencia activo (0=normal, 1=bloqueo total)"),
            ("kill_switch_motivo", "", "Motivo del último disparo de freno de emergencia")
        ]
        for key, val, desc in security_defaults:
            cursor.execute("""
                INSERT OR IGNORE INTO configuracion_seguridad (clave, valor, descripcion, updated_at)
                VALUES (?, ?, ?, ?)
            """, (key, val, desc, now_iso))

        # Sembrar secuencia multicanal por defecto si no hay ninguna
        seed_default_sequence(cursor, now_iso)
        seed_default_lead_list(cursor, now_iso)
        seed_default_users(cursor, now_iso)

def migrate_multitenant_schema(cursor):
    """
    Ensures all tables have the necessary columns for multi-tenant isolation,
    seat management, and commercial pricing models.
    """
    columns_by_table = {
        "usuarios": [
            ("tenant_id", "TEXT"),
            ("puesto_activo", "INTEGER DEFAULT 1"),
            ("estado", "TEXT DEFAULT 'ACTIVO'")
        ],
        "leads": [
            ("tenant_id", "TEXT"),
            ("cargo_actual", "TEXT"),
            ("fecha_reunion_agendada", "TEXT"),
            ("valor_reunion", "REAL DEFAULT 0.0")
        ],
        "secuencias": [
            ("tenant_id", "TEXT")
        ],
        "listas_leads": [
            ("tenant_id", "TEXT")
        ],
        "system_logs": [
            ("tenant_id", "TEXT")
        ]
    }
    
    for table_name, cols in columns_by_table.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_cols = {r["name"] if isinstance(r, dict) else r[1] for r in cursor.fetchall()}
        for col_name, col_type in cols:
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

    # Aislamiento e índices Multi-Tenant
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_tenant ON usuarios(tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_secuencias_tenant ON secuencias(tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_listas_tenant ON listas_leads(tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_parent ON tenants(parent_tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_suscripciones_tenant ON suscripciones(tenant_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant ON audit_logs(tenant_id);")

    # Si hay entidades huérfanas sin tenant_id, vincularlas por defecto a ten_superadmin
    try:
        cursor.execute("UPDATE leads SET tenant_id = 'ten_superadmin' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE secuencias SET tenant_id = 'ten_superadmin' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE listas_leads SET tenant_id = 'ten_superadmin' WHERE tenant_id IS NULL OR tenant_id = ''")
    except Exception:
        pass

    # Regularizar y poblar cargo_actual si está vacío
    backfill_cargo_actual(cursor)

    # Migrar constraint UNIQUE de leads si sigue siendo global
    migrate_leads_unique_constraint(cursor)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_tenant_url ON leads(tenant_id, perfil_url);")

    # Asegurar que cada tenant activo tenga al menos una lista por defecto
    ensure_default_lead_lists_for_all_tenants(cursor, datetime.now().isoformat())

def backfill_cargo_actual(cursor):
    """
    Rellena el campo `cargo_actual` de manera limpia y precisa para todos los leads existentes
    que solo tenían registrado el titular/headline de LinkedIn.
    """
    try:
        from lead_parser import parse_cargo_and_institucion
        cursor.execute("SELECT id, cargo_titular, institucion_actual FROM leads WHERE cargo_actual IS NULL OR cargo_actual = ''")
        leads_pendientes = cursor.fetchall()
        for l in leads_pendientes:
            lid = l["id"] if isinstance(l, dict) else l[0]
            titular = l["cargo_titular"] if isinstance(l, dict) else l[1]
            inst = l["institucion_actual"] if isinstance(l, dict) else l[2]
            c_actual, _ = parse_cargo_and_institucion(titular, default_institucion=inst)
            cursor.execute("UPDATE leads SET cargo_actual = ? WHERE id = ?", (c_actual, lid))
    except Exception as e:
        print(f"[DB Migration] Warning backfilling cargo_actual: {e}")

def migrate_leads_unique_constraint(cursor):
    """
    Migrates `leads` table from legacy global UNIQUE(perfil_url) to tenant-scoped UNIQUE(tenant_id, perfil_url).
    """
    try:
        cursor.execute("PRAGMA index_list(leads)")
        indexes = cursor.fetchall()
        has_legacy_unique = False
        for idx in indexes:
            idx_name = idx["name"] if isinstance(idx, dict) else idx[1]
            idx_unique = idx["unique"] if isinstance(idx, dict) else idx[2]
            if idx_unique and "autoindex" in str(idx_name):
                cursor.execute(f"PRAGMA index_info({idx_name})")
                cols = cursor.fetchall()
                col_names = [c["name"] if isinstance(c, dict) else c[2] for c in cols]
                if col_names == ["perfil_url"]:
                    has_legacy_unique = True
                    break

        if has_legacy_unique:
            cursor.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("""
                CREATE TABLE leads_tenant_migrated (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    cargo_titular TEXT,
                    cargo_actual TEXT,
                    institucion_actual TEXT,
                    ubicacion TEXT,
                    grado_red TEXT DEFAULT '2º',
                    perfil_url TEXT NOT NULL,
                    email TEXT,
                    telefono TEXT,
                    estado TEXT DEFAULT 'EXTRAIDO',
                    siguiendo INTEGER DEFAULT 0,
                    siguiendo_desde TEXT,
                    invitacion_retirada INTEGER DEFAULT 0,
                    fecha_retiro_invitacion TEXT,
                    fecha_extraccion TEXT,
                    fecha_visita TEXT,
                    fecha_invitacion TEXT,
                    fecha_conexion TEXT,
                    tags TEXT DEFAULT '[]',
                    notas TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    tenant_id TEXT,
                    fecha_reunion_agendada TEXT,
                    valor_reunion REAL DEFAULT 0.0
                )
            """)
            cursor.execute("""
                INSERT INTO leads_tenant_migrated (
                    id, nombre, cargo_titular, cargo_actual, institucion_actual, ubicacion, grado_red,
                    perfil_url, email, telefono, estado, siguiendo, siguiendo_desde,
                    invitacion_retirada, fecha_retiro_invitacion, fecha_extraccion,
                    fecha_visita, fecha_invitacion, fecha_conexion, tags, notas,
                    created_at, updated_at, tenant_id, fecha_reunion_agendada, valor_reunion
                )
                SELECT 
                    id, nombre, cargo_titular, cargo_actual, institucion_actual, ubicacion, grado_red,
                    perfil_url, email, telefono, estado, siguiendo, siguiendo_desde,
                    invitacion_retirada, fecha_retiro_invitacion, fecha_extraccion,
                    fecha_visita, fecha_invitacion, fecha_conexion, tags, notas,
                    created_at, updated_at, COALESCE(tenant_id, 'ten_superadmin'),
                    fecha_reunion_agendada, valor_reunion
                FROM leads
            """)
            cursor.execute("DROP TABLE leads")
            cursor.execute("ALTER TABLE leads_tenant_migrated RENAME TO leads")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_tenant_url ON leads(tenant_id, perfil_url);")
            cursor.execute("PRAGMA foreign_keys = ON")
    except Exception as e:
        print(f"[DB Migration] Warning migrating leads table: {e}")

def ensure_default_lead_lists_for_all_tenants(cursor, now_iso):
    """
    Ensures every active tenant has at least one default lead list so users can organize prospects immediately.
    """
    try:
        import secrets
        cursor.execute("SELECT id, razon_social FROM tenants WHERE estado = 'ACTIVO'")
        tenants = cursor.fetchall()
        for t in tenants:
            tid = t["id"] if isinstance(t, dict) else t[0]
            cursor.execute("SELECT COUNT(*) as total FROM listas_leads WHERE tenant_id = ?", (tid,))
            row = cursor.fetchone()
            count = row["total"] if isinstance(row, dict) else row[0]
            if count == 0:
                new_list_id = f"lista-{secrets.token_hex(4)}"
                cursor.execute("""
                    INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, estado, created_at, updated_at)
                    VALUES (?, ?, 'Mi Primera Lista', 'Lista inicial creada automáticamente para prospección', 'ACTIVA', ?, ?)
                """, (new_list_id, tid, now_iso, now_iso))
    except Exception as e:
        print(f"[DB Migration] Warning ensuring default lists: {e}")

def seed_default_users(cursor, now_iso):
    import auth_service
    auth_service.seed_multitenant_ecosystem_if_empty(cursor=cursor)

def seed_default_sequence(cursor, now_iso):
    cursor.execute("SELECT COUNT(*) as total FROM secuencias")
    if cursor.fetchone()["total"] > 0:
        return

    sec_id = "sec-default-directores-2026"
    cursor.execute("""
        INSERT INTO secuencias (id, nombre, descripcion, activa, es_default, created_at, updated_at)
        VALUES (?, ?, ?, 1, 1, ?, ?)
    """, (
        sec_id,
        "Outreach Directores 2026 (LinkedIn + Workspace Multicanal)",
        "Árbol de decisión completo: Visita de perfil -> Espera 4h -> Invitación -> Bifurcación: Si conecta -> Mensajes LinkedIn en secuencia; Si no conecta -> Cold Email Google Workspace institucional.",
        ahora_iso,
        ahora_iso
    ))

    pasos = [
        # Paso 1: Raíz - Visitar
        ("step-1", sec_id, None, "DEFAULT", "VISITAR_PERFIL", json.dumps({
            "tiempo_lectura_min_seg": 6,
            "tiempo_lectura_max_seg": 12,
            "simular_scroll": True,
            "etiqueta": "1. Visitar Perfil LinkedIn (Scroll y Lectura Humana)"
        }), 1),
        # Paso 2: Espera antes de invitar
        ("step-2", sec_id, "step-1", "DEFAULT", "ESPERAR", json.dumps({
            "horas_espera": 4,
            "etiqueta": "2. Esperar 4 Horas (Pausa Estratégica)"
        }), 2),
        # Paso 3: Enviar Invitación
        ("step-3", sec_id, "step-2", "DEFAULT", "ENVIAR_INVITACION", json.dumps({
            "incluir_nota": True,
            "usar_spintax": True,
            "plantilla_nota": "Hola {nombre}, un gusto saludarte. Veo tu gestión directiva en {colegio}. Me encantaría conectar contigo por este medio.",
            "etiqueta": "3. Enviar Invitación a Conectar (Nota Personalizada)"
        }), 3),
        # Paso 4: Esperar aceptación
        ("step-4", sec_id, "step-3", "DEFAULT", "ESPERAR", json.dumps({
            "horas_espera": 48,
            "etiqueta": "4. Esperar 48 Horas para Aceptación"
        }), 4),
        # Paso 5: Bifurcación / Árbol de decisión
        ("step-5", sec_id, "step-4", "DEFAULT", "VERIFICAR_ESTADO", json.dumps({
            "descripcion": "¿El director aceptó la invitación?",
            "etiqueta": "5. Bifurcación Condicional: ¿Aceptó en LinkedIn?"
        }), 5),

        # RAMA A: SI ACEPTÓ (Canal LinkedIn)
        ("step-6a", sec_id, "step-5", "SI_ACEPTO", "ENVIAR_MENSAJE_LINKEDIN", json.dumps({
            "asunto": "Mensaje de Bienvenida",
            "plantilla_mensaje": "Hola {nombre}, gracias por aceptar la conexión. Quería compartir contigo algunas experiencias prácticas que estamos implementando con directores escolares en torno a optimización de gestión en {colegio}. ¿Te interesaría revisar un resumen breve?",
            "etiqueta": "6A. [Si Conectó] Enviar Mensaje 1 de Valor en LinkedIn"
        }), 6),
        ("step-7a", sec_id, "step-6a", "DEFAULT", "ESPERAR", json.dumps({
            "horas_espera": 72,
            "etiqueta": "7A. Esperar 3 Días (72 hrs)"
        }), 7),
        ("step-8a", sec_id, "step-7a", "DEFAULT", "ENVIAR_MENSAJE_LINKEDIN", json.dumps({
            "asunto": "Mensaje de Seguimiento",
            "plantilla_mensaje": "Estimado/a {nombre}, espero que estés teniendo una excelente semana en {colegio}. Quería consultarte si tuviste ocasión de revisar mi mensaje anterior o si prefieres coordinar una llamada de 10 minutos.",
            "etiqueta": "8A. Enviar Mensaje 2 de Seguimiento en LinkedIn"
        }), 8),

        # RAMA B: SI NO ACEPTÓ (Canal Google Workspace Email)
        ("step-6b", sec_id, "step-5", "SI_NO_ACEPTO", "ENVIAR_CORREO_WORKSPACE", json.dumps({
            "asunto": "Consulta sobre gestión escolar en {colegio}",
            "cuerpo_email": "Estimado/a {nombre},\n\nEspero que se encuentre muy bien. Le escribo en relación a su labor como directivo en {colegio}.\n\nIntenté conectar con usted recientemente por LinkedIn; no obstante, le escribo por este medio formal de correo institucional para presentarle una breve síntesis de herramientas para directores escolares...\n\nQuedo a su disposición si estima conveniente conversar brevemente.\n\nAtentamente,\nGabriel",
            "requiere_email_valido": True,
            "etiqueta": "6B. [Si NO Conectó] Enviar Email Google Workspace"
        }), 6),
        ("step-7b", sec_id, "step-6b", "DEFAULT", "ESPERAR", json.dumps({
            "horas_espera": 168,
            "etiqueta": "7B. Esperar 7 Días (168 hrs)"
        }), 7),
        ("step-8b", sec_id, "step-7b", "DEFAULT", "RETIRAR_INVITACION", json.dumps({
            "motivo": "Retiro automático por falta de respuesta para proteger ratio de cuenta",
            "etiqueta": "8B. Retirar Solicitud de Conexión en LinkedIn"
        }), 8)
    ]

    for p_id, s_id, padre_id, cond, tipo, params, orden in pasos:
        cursor.execute("""
            INSERT INTO pasos_secuencia (id, secuencia_id, padre_paso_id, condicion_rama, tipo_accion, parametros_json, orden, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (p_id, s_id, padre_id, cond, tipo, params, orden, ahora_iso))

    seed_default_lead_list(cursor, ahora_iso)

def seed_default_lead_list(cursor, ahora_iso):
    cursor.execute("SELECT COUNT(*) as total FROM listas_leads")
    if cursor.fetchone()["total"] > 0:
        return

    lista_id = "lista-directores-chile-lote-1"
    cursor.execute("""
        INSERT INTO listas_leads (id, nombre, descripcion, termino_busqueda, estado, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'ACTIVA', ?, ?)
    """, (
        lista_id,
        "Directores de Colegio Chile (Lote Inicial 1)",
        "Segmento inicial de directivos escolares extraídos para campaña multicanal 2026.",
        "Director de Colegio Chile",
        ahora_iso,
        ahora_iso
    ))

    # Asociar todos los leads existentes a esta lista
    cursor.execute("SELECT id FROM leads")
    leads_existentes = cursor.fetchall()
    for l in leads_existentes:
        cursor.execute("""
            INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (f"ll-{lista_id}-{l['id']}", lista_id, l["id"], ahora_iso))

    # Conectar esta lista a la secuencia por defecto
    cursor.execute("""
        INSERT OR IGNORE INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
        VALUES (?, 'sec-default-directores-2026', ?, 1, 1, ?)
    """, (f"sl-sec-default-{lista_id}", lista_id, ahora_iso))

def migrate_from_json() -> int:
    init_db()
    json_path = os.path.join(os.path.dirname(__file__), "prospectos.json")
    if not os.path.exists(json_path):
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        prospectos = json.load(f)

    ahora = datetime.now().isoformat()
    migrados = 0

    with get_db() as conn:
        cursor = conn.cursor()
        for p in prospectos:
            lead_id = p.get("id")
            cursor.execute("SELECT id FROM leads WHERE id = ?", (lead_id,))
            if not cursor.fetchone():
                cursor.execute("""
                INSERT INTO leads (
                    id, nombre, cargo_titular, institucion_actual, ubicacion, grado_red,
                    perfil_url, estado, fecha_extraccion, fecha_visita, fecha_invitacion,
                    tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lead_id,
                    p.get("nombre"),
                    p.get("cargo_titular"),
                    p.get("institucion_actual"),
                    p.get("ubicacion"),
                    p.get("grado_red", "2º"),
                    p.get("perfil_url"),
                    p.get("estado", "EXTRAIDO"),
                    p.get("fecha_extraccion"),
                    p.get("fecha_visita"),
                    p.get("fecha_invitacion"),
                    json.dumps(["Director de Colegio", "Chile"]),
                    ahora,
                    ahora
                ))

                for h in p.get("historial", []):
                    cursor.execute("""
                    INSERT INTO historial_actividades (
                        lead_id, tipo_evento, descripcion, timestamp
                    ) VALUES (?, ?, ?, ?)
                    """, (
                        lead_id,
                        h.get("accion", "MIGRADO"),
                        h.get("detalle", ""),
                        h.get("fecha", ahora)
                    ))
                migrados += 1
    return migrados

# ==========================================
# ALIASES FOR BACKWARD COMPATIBILITY
# ==========================================
migrar_esquema_multitenant = migrate_multitenant_schema
seed_default_secuencia = seed_default_sequence
seed_default_lista_leads = seed_default_lead_list
migrar_desde_json = migrate_from_json

if __name__ == "__main__":
    init_db()
    migrados = migrate_from_json()
    print(f"Base de datos leads.db inicializada con éxito. Migrados: {migrados} leads.")
