import sqlite3
import json
import os
import re
from datetime import datetime
from contextlib import contextmanager

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Carga de respaldo de .env para entornos sin python-dotenv
def _load_env_fallback():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env_fallback()

DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

def get_sqlite_db_path() -> str:
    """Retorna la ruta activa de SQLite.
    Prioriza la variable de entorno SQLITE_DB_PATH cuando está definida y no vacía.
    De lo contrario, retorna la ruta predeterminada de producción (leads.db).
    """
    env_path = os.getenv("SQLITE_DB_PATH", "").strip()
    return env_path if env_path else DEFAULT_SQLITE_PATH

DB_PATH = get_sqlite_db_path()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")))

# PostgreSQL es el motor operacional predeterminado de NexusReach Pro (TASK-05B-05)
DB_ENGINE = os.getenv("DB_ENGINE", "postgres").strip().lower()
if DB_ENGINE in ("postgres", "postgresql") and not IS_POSTGRES:
    raise RuntimeError(
        "CONFIGURACIÓN CRÍTICA INVÁLIDA: NexusReach Pro opera con PostgreSQL como motor predeterminado. "
        "DATABASE_URL debe estar configurada con un esquema válido ('postgresql://' o 'postgres://') apuntando al rol 'nexus_app'. "
        "Operación abortada para impedir un fallback silencioso a SQLite."
    )
if DATABASE_URL and not IS_POSTGRES:
    raise RuntimeError(
        f"CONFIGURACIÓN CRÍTICA INVÁLIDA: DATABASE_URL está configurada pero tiene un esquema no soportado ('{DATABASE_URL.split('://')[0] if '://' in DATABASE_URL else DATABASE_URL[:10]}'). "
        "Operación abortada para impedir un fallback silencioso a SQLite."
    )

def get_superadmin_rls_secret() -> str:
    """Obtiene el token criptográfico para bypass de superadministrador en PostgreSQL RLS.
    En entornos productivos o staging exige obligatoriamente un secreto configurado vía entorno.
    Si no está configurado en producción, retorna cadena vacía garantizando comportamiento fail-closed.
    """
    secret = os.getenv("SUPERADMIN_RLS_SECRET", "").strip()
    if secret:
        return secret
    env = os.getenv("ENV", os.getenv("ENVIRONMENT", "development")).lower()
    if env in ("production", "prod", "staging"):
        return ""
    # Valor predeterminado seguro exclusivo para entornos locales y suites de pruebas
    return "nexus_superadmin_secure_key_2026"

SUPERADMIN_RLS_SECRET = get_superadmin_rls_secret()

from contextvars import ContextVar
from typing import Optional, Dict, Any, List

# Variables de contexto transaccional / asíncrono para propagación segura de tenant
_current_tenant_ctx: ContextVar[Optional[str]] = ContextVar("_current_tenant_ctx", default=None)
_current_super_admin_ctx: ContextVar[bool] = ContextVar("_current_super_admin_ctx", default=False)
_current_allow_subtenants_ctx: ContextVar[bool] = ContextVar("_current_allow_subtenants_ctx", default=False)

@contextmanager
def tenant_context_scope(tenant_id: Optional[str] = None, is_super_admin: bool = False, allow_subtenants: bool = False):
    """Context manager para delimitar el contexto de seguridad del tenant dentro del ciclo de vida de una petición o tarea."""
    clean_tenant = str(tenant_id).strip() if (tenant_id and isinstance(tenant_id, str) and tenant_id.strip()) else None
    t_token = _current_tenant_ctx.set(clean_tenant)
    sa_token = _current_super_admin_ctx.set(is_super_admin is True)
    st_token = _current_allow_subtenants_ctx.set(allow_subtenants is True)
    try:
        yield
    finally:
        _current_tenant_ctx.reset(t_token)
        _current_super_admin_ctx.reset(sa_token)
        _current_allow_subtenants_ctx.reset(st_token)

def set_current_tenant_context(tenant_id: Optional[str] = None, is_super_admin: bool = False, allow_subtenants: bool = False):
    """Fija el contexto de tenant en la variable de contexto actual."""
    clean_tenant = str(tenant_id).strip() if (tenant_id and isinstance(tenant_id, str) and tenant_id.strip()) else None
    _current_tenant_ctx.set(clean_tenant)
    _current_super_admin_ctx.set(is_super_admin is True)
    _current_allow_subtenants_ctx.set(allow_subtenants is True)

def clear_current_tenant_context():
    """Limpia el contexto de tenant devolviéndolo al estado restrictivo por defecto."""
    _current_tenant_ctx.set(None)
    _current_super_admin_ctx.set(False)
    _current_allow_subtenants_ctx.set(False)

def get_current_tenant_context() -> Dict[str, Any]:
    """Retorna una instantánea del contexto de tenant activo."""
    return {
        "tenant_id": _current_tenant_ctx.get(),
        "is_super_admin": _current_super_admin_ctx.get(),
        "allow_subtenants": _current_allow_subtenants_ctx.get()
    }

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def _convert_placeholders(query: str) -> str:
    """Reemplaza los marcadores de posición de parámetros ? no entrecomillados por %s para compatibilidad con PostgreSQL."""
    if "?" not in query:
        return query
    parts = re.split(r"('(?:''|[^'])*')", query)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("?", "%s")
    return "".join(parts)

def _convert_query_to_pg(query: str) -> str:
    """Normaliza y traduce sintaxis específica de SQLite (INSERT OR IGNORE, INSERT OR REPLACE) a PostgreSQL de forma transparente."""
    q = query.strip()

    # 1. SET LOCAL app.current_tenant_id con parámetros posicionales
    if q.startswith("SET LOCAL app.current_tenant_id = %s"):
        return q

    # 2. INSERT OR IGNORE INTO ... -> INSERT INTO ... ON CONFLICT DO NOTHING
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO\s+", q, re.IGNORECASE):
        q = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", q, flags=re.IGNORECASE)
        has_semicolon = q.endswith(";")
        if has_semicolon:
            q = q[:-1].rstrip()
        q = f"{q} ON CONFLICT DO NOTHING;"

    # 3. INSERT OR REPLACE INTO configuracion_seguridad
    elif re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+configuracion_seguridad", q, re.IGNORECASE):
        q = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", q, flags=re.IGNORECASE)
        has_semicolon = q.endswith(";")
        if has_semicolon:
            q = q[:-1].rstrip()
        q = f"{q} ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, updated_at = EXCLUDED.updated_at;"

    # 4. INSERT OR REPLACE INTO action_status
    elif re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+action_status", q, re.IGNORECASE):
        q = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", q, flags=re.IGNORECASE)
        has_semicolon = q.endswith(";")
        if has_semicolon:
            q = q[:-1].rstrip()
        q = f"{q} ON CONFLICT (action) DO UPDATE SET status = EXCLUDED.status, pause_reason = EXCLUDED.pause_reason, consecutive_failures = EXCLUDED.consecutive_failures, updated_at = EXCLUDED.updated_at;"

    # 5. INSERT OR REPLACE INTO selector_versions
    elif re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+selector_versions", q, re.IGNORECASE):
        q = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", q, flags=re.IGNORECASE)
        has_semicolon = q.endswith(";")
        if has_semicolon:
            q = q[:-1].rstrip()
        q = f"{q} ON CONFLICT (version) DO UPDATE SET catalog_json = EXCLUDED.catalog_json, signature = EXCLUDED.signature, min_client_version = EXCLUDED.min_client_version, is_active = EXCLUDED.is_active, published_at = EXCLUDED.published_at;"

    # 6. INSERT OR REPLACE INTO suppression_list
    elif re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+suppression_list", q, re.IGNORECASE):
        q = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", q, flags=re.IGNORECASE)
        has_semicolon = q.endswith(";")
        if has_semicolon:
            q = q[:-1].rstrip()
        q = f"{q} ON CONFLICT (id) DO UPDATE SET identifier_hash = EXCLUDED.identifier_hash, identifier_type = EXCLUDED.identifier_type, reason = EXCLUDED.reason, created_at = EXCLUDED.created_at;"

    # 7. Traducir funciones JSON de SQLite a PostgreSQL
    if "json_group_array" in q or "json_object" in q:
        # json_group_array(...) -> json_agg(...)
        q = re.sub(r"\bjson_group_array\b", "json_agg", q, flags=re.IGNORECASE)
        # json_object(...) -> json_build_object(...)
        q = re.sub(r"\bjson_object\b", "json_build_object", q, flags=re.IGNORECASE)

    # 8. Convertir ? a %s fuera de comillas simples
    return _convert_placeholders(q)

class PgCursorWrapper:
    """Envoltorio de cursor para PostgreSQL que convierte marcadores de posición ? y dialectos SQLite a PostgreSQL de manera transparente."""
    def __init__(self, cursor):
        self._cur = cursor

    def execute(self, query, params=None):
        # En PostgreSQL nativo con psycopg3 (protocolo extendido $1), los comandos SET no admiten $1 posicional.
        # Traducir SET LOCAL app.current_tenant_id = %s; a SELECT set_config('app.current_tenant_id', %s, true);
        if query.strip().startswith("SET LOCAL app.current_tenant_id = %s") and params is not None:
            return self._cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", params)
        pg_query = _convert_query_to_pg(query)
        if params is not None:
            return self._cur.execute(pg_query, params)
        return self._cur.execute(pg_query)

    def executemany(self, query, params_seq):
        pg_query = _convert_query_to_pg(query)
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
    """Envoltorio de conexión para PostgreSQL que expone métodos de cursor y transacciones."""
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

_pg_pool = None

def get_pg_pool():
    """Retorna o inicializa el ConnectionPool reutilizable para PostgreSQL."""
    global _pg_pool
    if _pg_pool is None and IS_POSTGRES:
        try:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
            _pg_pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=2,
                max_size=20,
                timeout=10.0,
                kwargs={"row_factory": dict_row}
            )
        except Exception as e:
            _pg_pool = None
    return _pg_pool

def _configure_pg_context(cur, tenant_id=None, is_super_admin=False, allow_subtenants=False):
    """Configura el contexto de sesión PostgreSQL para Row-Level Security (RLS).
    Garantiza aislamiento estricto por defecto:
    - is_super_admin=True: Concede acceso administrativo completo autenticado con token criptográfico (solo si es booleano estricto True).
    - tenant_id (no vacío): Aísla la sesión al tenant especificado.
    - Sin tenant_id ni superadmin: Restringe el contexto a 0 filas (is_super_admin='false', current_tenant_id='').
    - allow_subtenants=True: Habilita explícitamente el acceso a la cartera de sub-clientes para agencias.
    """
    effective_secret = get_superadmin_rls_secret()
    if is_super_admin is True and effective_secret:
        cur.execute("SELECT set_config('app.is_super_admin', 'true', true);")
        cur.execute("SELECT set_config('app.super_admin_token', %s, true);", (effective_secret,))
    else:
        cur.execute("SELECT set_config('app.is_super_admin', 'false', true);")
        cur.execute("SELECT set_config('app.super_admin_token', '', true);")
        clean_tenant = str(tenant_id).strip() if tenant_id else ""
        if clean_tenant:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (clean_tenant,))
        else:
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")

    if allow_subtenants is True:
        cur.execute("SELECT set_config('app.allow_agency_subtenants', 'true', true);")

def verify_pg_security_posture(conn, strict: bool = False) -> Dict[str, Any]:
    """Inspecciona y valida la postura de seguridad de la conexión PostgreSQL y políticas RLS.
    Garantiza que el rol de aplicación NO sea SUPERUSER ni BYPASSRLS,
    y que las tablas multi-tenant tengan ROW LEVEL SECURITY y FORCE ROW LEVEL SECURITY activos.
    """
    report = {
        "is_postgres": IS_POSTGRES,
        "role": None,
        "is_superuser": None,
        "is_bypassrls": None,
        "tables_audited": 0,
        "tables_with_rls": 0,
        "tables_with_force_rls": 0,
        "unprotected_tables": [],
        "secure": False,
        "details": []
    }
    cursor = conn.cursor()
    try:
        # 1. Comprobar rol de conexión
        cursor.execute("""
            SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
            FROM pg_roles 
            WHERE rolname = current_user
        """)
        role_row = cursor.fetchone()
        if role_row:
            report["role"] = role_row["rolname"] if isinstance(role_row, dict) else role_row[0]
            report["is_superuser"] = bool(role_row["rolsuper"] if isinstance(role_row, dict) else role_row[1])
            report["is_bypassrls"] = bool(role_row["rolbypassrls"] if isinstance(role_row, dict) else role_row[2])

        if report["is_superuser"] or report["is_bypassrls"]:
            msg = f"Postura de seguridad insegura: El rol PostgreSQL '{report['role']}' tiene SUPERUSER={report['is_superuser']} o BYPASSRLS={report['is_bypassrls']}."
            report["details"].append(msg)
            if strict:
                raise RuntimeError(msg)

        # 2. Comprobar RLS y FORCE RLS en tablas multi-tenant
        cursor.execute("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' 
              AND c.relkind = 'r'
              AND c.relname NOT IN ('configuracion_seguridad', 'selector_versions', 'action_status', 'payment_webhook_events', 'system_admin_keys')
            ORDER BY c.relname;
        """)
        tables = cursor.fetchall()
        report["tables_audited"] = len(tables)
        for t in tables:
            t_name = t["relname"] if isinstance(t, dict) else t[0]
            has_rls = bool(t["relrowsecurity"] if isinstance(t, dict) else t[1])
            has_force = bool(t["relforcerowsecurity"] if isinstance(t, dict) else t[2])
            if has_rls:
                report["tables_with_rls"] += 1
            if has_force:
                report["tables_with_force_rls"] += 1
            if not (has_rls and has_force):
                report["unprotected_tables"].append(t_name)

        is_role_safe = (report["is_superuser"] is False and report["is_bypassrls"] is False)
        are_tables_safe = (len(report["unprotected_tables"]) == 0 and report["tables_audited"] > 0)
        report["secure"] = is_role_safe and are_tables_safe
    except Exception as e:
        report["error"] = str(e)
        if strict:
            raise
    return report

@contextmanager
def get_db(tenant_id=None, is_super_admin=False, allow_subtenants=False):
    """
    Context manager de conexión de base de datos dual:
    - Si DATABASE_URL está configurado: Conecta a PostgreSQL con ConnectionPool y Row-Level Security (RLS).
      Establece y limpia context variables locales (SET LOCAL) para el tenant autorizado.
    - Si no está configurado: Usa SQLite local leads.db en modo WAL con busy_timeout configurado.
    """
    ctx_tenant = _current_tenant_ctx.get()
    ctx_super_admin = _current_super_admin_ctx.get()
    ctx_subtenants = _current_allow_subtenants_ctx.get()

    effective_tenant = tenant_id if tenant_id is not None else ctx_tenant
    effective_super_admin = is_super_admin if is_super_admin is not False else ctx_super_admin
    effective_subtenants = allow_subtenants if allow_subtenants is not False else ctx_subtenants

    if IS_POSTGRES:
        pool = get_pg_pool()
        if pool is not None:
            with pool.connection() as conn:
                wrapped = PgConnWrapper(conn)
                try:
                    with conn.cursor() as cur:
                        _configure_pg_context(cur, tenant_id=effective_tenant, is_super_admin=effective_super_admin, allow_subtenants=effective_subtenants)
                    yield wrapped
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    try:
                        with conn.cursor() as cur:
                            cur.execute("RESET app.current_tenant_id; RESET app.is_super_admin; RESET app.super_admin_token; RESET app.allow_agency_subtenants;")
                    except Exception:
                        pass
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError:
                raise RuntimeError("El paquete 'psycopg' es requerido para conectar a PostgreSQL. Instálalo con pip install psycopg[binary]")

            conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            wrapped = PgConnWrapper(conn)
            try:
                with conn.cursor() as cur:
                    _configure_pg_context(cur, tenant_id=effective_tenant, is_super_admin=effective_super_admin, allow_subtenants=effective_subtenants)
                yield wrapped
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    elif DB_ENGINE == "sqlite":
        active_db_path = get_sqlite_db_path()
        conn = sqlite3.connect(active_db_path, timeout=15.0)
        conn.row_factory = dict_factory
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 15000;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        raise RuntimeError(
            f"ERROR DE PERSISTENCIA: El motor configurado '{DB_ENGINE}' no es válido y no hay una conexión PostgreSQL activa. "
            "El fallback silencioso a SQLite está deshabilitado."
        )

def init_db():
    if IS_POSTGRES:
        # En PostgreSQL, verificar la existencia del esquema operacional.
        # Las modificaciones DDL son responsabilidad exclusiva del script administrativo bootstrap_postgres_clean.py.
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT count(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'leads';
            """)
            row = cursor.fetchone()
            count = row[0] if isinstance(row, (list, tuple)) else (row.get("count", 0) if isinstance(row, dict) else 0)
            if count == 0:
                print("[DATABASE WARNING] La base PostgreSQL no contiene la tabla 'leads'. Ejecute 'python scripts/bootstrap_postgres_clean.py --bootstrap' para inicializar el esquema.")
        return

    # Si se especificó explícitamente DB_ENGINE=sqlite para tests legacy:
    if DB_ENGINE != "sqlite":
        raise RuntimeError("ERROR DE PERSISTENCIA: Inicialización de SQLite bloqueada porque el motor predeterminado es PostgreSQL.")

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
            email_extracted TEXT,
            email_source TEXT,
            email_status TEXT,
            empresa_dominio TEXT,
            email_detalles_json TEXT DEFAULT '{}',
            email_zoho TEXT,
            zoho_entidad_tipo TEXT,
            zoho_id TEXT,
            zoho_lead_status TEXT,
            zoho_cuenta_id TEXT,
            zoho_cuenta_nombre TEXT,
            zoho_cuenta_dueno TEXT,
            zoho_cuenta_tipo TEXT,
            zoho_cuenta_es_cliente INTEGER DEFAULT 0,
            zoho_tratos_info TEXT DEFAULT '[]',
            zoho_synced_at TEXT,
            zoho_email_extracted_at TEXT,
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

        # 3b. Mensajes de WhatsApp Web (Canal Local Antiban)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mensajes_whatsapp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            campana_nombre TEXT,
            paso_secuencia INTEGER DEFAULT 1,
            telefono_destino TEXT NOT NULL,
            contenido TEXT NOT NULL,
            estado TEXT DEFAULT 'PENDIENTE',
            enviado_at TEXT,
            fue_respondido INTEGER DEFAULT 0,
            respondido_at TEXT,
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

        # 18. Dispositivos Locales Emparejados (Workstream 5.1 - Ed25519)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT,
            device_name TEXT,
            public_key_ed25519 TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            client_version TEXT DEFAULT '1.0.0',
            last_seen_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 19. Comandos Criptográficamente Firmados (Backend -> Cliente)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            action TEXT NOT NULL,
            params_json TEXT DEFAULT '{}',
            nonce TEXT NOT NULL UNIQUE,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            signature TEXT NOT NULL,
            status TEXT DEFAULT 'ISSUED',
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
        );
        """)

        # 20. Resultados Autenticados de Ejecución (Cliente -> Backend)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS command_results (
            id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            success INTEGER DEFAULT 0,
            result_json TEXT DEFAULT '{}',
            error_message TEXT,
            device_signature TEXT,
            reported_at TEXT NOT NULL,
            FOREIGN KEY (command_id) REFERENCES commands (id) ON DELETE CASCADE,
            FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
        );
        """)

        # 21. Lista de Supresión / Opt-out por Tenant (Hash SHA-256) - Workstream 5.2 & 5.4
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppression_list (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            identifier_hash TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            reason TEXT DEFAULT 'OPT_OUT',
            created_at TEXT NOT NULL,
            UNIQUE(tenant_id, identifier_hash),
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 22. Bitácora Interna de Acciones de Leads (lead_activity) - Workstream 5.2
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS lead_activity (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            details_json TEXT DEFAULT '{}',
            actor_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 23. Cuentas de LinkedIn Conectadas (Unidad Facturable - Workstream 5.3)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS linkedin_accounts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT,
            device_id TEXT,
            account_name TEXT NOT NULL,
            profile_url TEXT,
            linkedin_urn TEXT,
            status TEXT DEFAULT 'WARMUP',
            warmup_day INTEGER DEFAULT 1,
            daily_invite_limit INTEGER DEFAULT 15,
            invites_sent_today INTEGER DEFAULT 0,
            last_action_at TEXT,
            health_score REAL DEFAULT 100.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES usuarios (id) ON DELETE SET NULL,
            FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE SET NULL
        );
        """)

        # 24. Cuentas de WhatsApp Conectadas (Warm Outreach Estricto - Workstream 5.3)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_accounts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            account_name TEXT,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 25. Candidatos de Correo y Evidencia OSINT (Workstream 5.3 & 5.6)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_candidates (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            candidate_email TEXT NOT NULL,
            source_type TEXT NOT NULL,
            evidence_url TEXT,
            confidence_score REAL DEFAULT 0.0,
            verification_status TEXT DEFAULT 'UNVERIFIED',
            verification_provider TEXT,
            verification_cost_cents INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 26. Registro de Consentimiento y Base de Licitud (Workstream 5.4 - Ley 21.719)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consent_records (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            legal_basis TEXT NOT NULL,
            evidence_text TEXT,
            captured_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
            FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
        );
        """)

        # 27. Libro Mayor de Créditos y Límites Comerciales (Workstream 5.3 & 5.9)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_ledger (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            account_id TEXT,
            credit_type TEXT NOT NULL,
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 28. Eventos de Consumo y Costo Real (Workstream 5.6 & 5.9)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            account_id TEXT,
            event_type TEXT NOT NULL,
            provider TEXT,
            cost_usd REAL DEFAULT 0.0,
            credits_consumed INTEGER DEFAULT 0,
            details_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 29. Contadores de Uso por Ciclo (Workstream 5.6 & 5.9)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_counters (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cycle_start TEXT NOT NULL,
            cycle_end TEXT NOT NULL,
            leads_activated INTEGER DEFAULT 0,
            actions_executed INTEGER DEFAULT 0,
            credits_consumed INTEGER DEFAULT 0,
            verification_cost_usd REAL DEFAULT 0.0,
            security_incidents INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 30. Versiones de Catálogo de Selectores Firmados (Workstream 5.8)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS selector_versions (
            version TEXT PRIMARY KEY,
            catalog_json TEXT NOT NULL,
            signature TEXT NOT NULL,
            min_client_version TEXT DEFAULT '1.0.0',
            is_active INTEGER DEFAULT 1,
            published_at TEXT NOT NULL
        );
        """)

        # 31. Estado de Salud y Degradación Segura por Acción (Workstream 5.8)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_status (
            action TEXT PRIMARY KEY,
            status TEXT DEFAULT 'ACTIVE',
            pause_reason TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """)

        # 32. Bitácora de Fallos de Selectores (Contexto Sanitizado sin PII) (Workstream 5.8)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS selector_failure_logs (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            tenant_id TEXT,
            command_id TEXT,
            context_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # 33. Suscripciones Comerciales (Workstream 5.9 - 15 USD/mo por cuenta LinkedIn)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            account_id TEXT,
            provider TEXT NOT NULL,
            provider_subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'trialing',
            plan_type TEXT NOT NULL DEFAULT 'MONTHLY',
            billing_country TEXT NOT NULL,
            price_usd REAL NOT NULL DEFAULT 15.0,
            price_lock_until TEXT,
            current_period_start TEXT,
            current_period_end TEXT,
            grace_period_days INTEGER DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 34. Límites Comerciales y Entitlements por Tenant (Workstream 5.9)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS entitlements (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL UNIQUE,
            subscription_id TEXT,
            leads_limit_cycle INTEGER NOT NULL DEFAULT 500,
            credits_limit_cycle INTEGER NOT NULL DEFAULT 100,
            max_linkedin_accounts INTEGER NOT NULL DEFAULT 1,
            allow_whatsapp INTEGER NOT NULL DEFAULT 0,
            is_trial INTEGER NOT NULL DEFAULT 0,
            trial_end TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
        );
        """)

        # 35. Registro Idempotente de Webhooks de Pasarelas de Pago (Workstream 5.9)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_webhook_events (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            status TEXT DEFAULT 'PROCESSED'
        );
        """)

        # 36. Buzón de Staging y Matching de Prospectos (LinkedIn Discovery & Validation)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS staging_leads (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'ten_superadmin',
            nombre TEXT NOT NULL,
            institucion TEXT,
            email TEXT,
            cargo_declarado TEXT,
            telefono TEXT,
            origen TEXT DEFAULT 'MANUAL',
            zoho_id TEXT,
            estado TEXT DEFAULT 'PENDIENTE',
            candidato_nombre TEXT,
            candidato_url TEXT,
            candidato_titular TEXT,
            candidato_cargo TEXT,
            candidato_institucion TEXT,
            candidato_ubicacion TEXT,
            candidato_grado TEXT,
            score_coincidencia INTEGER DEFAULT 0,
            candidatos_alternativos_json TEXT DEFAULT '[]',
            notas TEXT,
            promovido_lead_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_perfil ON leads(tenant_id, perfil_url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_perfil ON leads(perfil_url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_en_lista_lead ON leads_en_lista(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_secuencia_lead ON leads_en_secuencia(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_historial_lead ON historial_actividades(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lead_activity_lead ON lead_activity(lead_id, created_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lead_activity_tenant ON lead_activity(tenant_id, created_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppression_hash ON suppression_list(tenant_id, identifier_hash);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mensajes_lead ON mensajes_linkedin(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_correos_lead ON correos_electronicos(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mensajes_whatsapp_lead ON mensajes_whatsapp(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pasos_secuencia ON pasos_secuencia(secuencia_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_secuencia ON leads_en_secuencia(secuencia_id, estado);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_lista ON leads_en_lista(lista_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_secuencia_listas ON secuencia_listas(secuencia_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staging_tenant_estado ON staging_leads(tenant_id, estado);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staging_email ON staging_leads(email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_module ON system_logs(module);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_ts ON audit_logs(tenant_id, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_zoho_id ON leads(zoho_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_tenant ON devices(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_commands_device ON commands(device_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_command_results_cmd ON command_results(command_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_linkedin_accounts_tenant ON linkedin_accounts(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_accounts_tenant ON whatsapp_accounts(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_candidates_lead ON email_candidates(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_consent_records_lead ON consent_records(lead_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_credit_ledger_tenant ON credit_ledger(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entitlements_tenant ON entitlements(tenant_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_selector_failures_action ON selector_failure_logs(action);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events_provider ON payment_webhook_events(provider, event_type);")

        # Normalización preventiva de estados completados en secuencias
        try:
            cursor.execute("UPDATE leads_en_secuencia SET estado = 'COMPLETADO' WHERE estado IN ('FINALIZADA', 'FINALIZADO');")
        except Exception:
            pass

        # Cargar defaults de seguridad si no existen
        now_iso = datetime.now().isoformat()
        security_defaults = [
            ("limite_linkedin_diario", "5", "Máximo de invitaciones LinkedIn al día"),
            ("limite_email_workspace_diario", "15", "Máximo de correos Google Workspace al día (Warmup)"),
            ("horario_laboral_activo", "1", "Restringir actividad a horario laboral de oficina (0 o 1)"),
            ("pausas_antiban_activas", "1", "Pausas humanas estocásticas entre acciones (0 o 1)"),
            ("limites_diarios_activos", "1", "Control estricto de cuotas diarias de invitaciones (0 o 1)"),
            ("horario_inicio", "09:00", "Hora inicio laboral en Chile (HH:MM)"),
            ("horario_fin", "18:00", "Hora fin laboral en Chile (HH:MM)"),
            ("pausa_linkedin_min_seg", "180", "Pausa mínima entre acciones LinkedIn (segundos)"),
            ("pausa_linkedin_max_seg", "360", "Pausa máxima entre acciones LinkedIn (segundos)"),
            ("pausa_email_min_seg", "480", "Pausa mínima entre emails Google Workspace (segundos)"),
            ("pausa_email_max_seg", "900", "Pausa máxima entre emails Google Workspace (segundos)"),
            ("kill_switch_activado", "0", "Freno de emergencia activo (0=normal, 1=bloqueo total)"),
            ("kill_switch_motivo", "", "Motivo del último disparo de freno de emergencia"),
            ("hunter_api_key", "", "Clave API de Hunter.io para búsqueda de correos corporativos"),
            ("dropcontact_api_key", "", "Clave API de Dropcontact para enriquecimiento"),
            ("anymail_api_key", "", "Clave API de Anymail Finder"),
            ("enriquecimiento_cascada_activo", "1", "Activar resolución por patrones y verificación DNS/SMTP (1=sí, 0=no)"),
            ("linkedin_warmup_activo", "1", "Activar rampa de calentamiento progresivo para invitaciones LinkedIn (1=sí, 0=no)"),
            ("linkedin_warmup_semana", "1", "Semana actual del ciclo de calentamiento (1 a 4)"),
            ("linkedin_warmup_inicio", now_iso, "Fecha de inicio del ciclo de calentamiento"),
            ("linkedin_busquedas_mes", "0", "Contador de búsquedas comerciales en LinkedIn este mes"),
            ("linkedin_busquedas_periodo", now_iso[:7], "Período actual YYYY-MM para control Commercial Use Limit"),
            ("whatsapp_cuota_diaria", "15", "Máximo de conversaciones nuevas en WhatsApp Web al día"),
            ("whatsapp_pausa_min_seg", "360", "Pausa mínima entre mensajes WhatsApp a contactos nuevos (segundos)"),
            ("whatsapp_pausa_max_seg", "900", "Pausa máxima entre mensajes WhatsApp a contactos nuevos (segundos)"),
            ("whatsapp_primer_mensaje_sin_enlaces", "1", "Bloquear enlaces en el primer mensaje de WhatsApp Web (1=sí, 0=no)"),
            ("zoho_sync_activo", "1", "Habilitar sincronización con Zoho CRM vía sesión de navegador (1=sí, 0=no)")
        ]
        for key, val, desc in security_defaults:
            cursor.execute("""
                INSERT OR IGNORE INTO configuracion_seguridad (clave, valor, descripcion, updated_at)
                VALUES (?, ?, ?, ?)
            """, (key, val, desc, now_iso))

        # Sembrar únicamente usuarios esenciales del sistema si no existen
        seed_default_users(cursor, now_iso)

def migrate_multitenant_schema(cursor):
    """
    Ensures all tables have the necessary columns for multi-tenant isolation,
    seat management, and commercial pricing models.
    """
    columns_by_table = {
        "tenants": [
            ("zoho_sync_activo", "INTEGER DEFAULT 0"),
            ("zoho_org_id", "TEXT DEFAULT NULL")
        ],
        "usuarios": [
            ("tenant_id", "TEXT"),
            ("puesto_activo", "INTEGER DEFAULT 1"),
            ("estado", "TEXT DEFAULT 'ACTIVO'")
        ],
        "leads": [
            ("tenant_id", "TEXT"),
            ("cargo_actual", "TEXT"),
            ("fecha_reunion_agendada", "TEXT"),
            ("valor_reunion", "REAL DEFAULT 0.0"),
            ("email_extracted", "TEXT"),
            ("email_source", "TEXT"),
            ("email_status", "TEXT"),
            ("empresa_dominio", "TEXT"),
            ("email_detalles_json", "TEXT DEFAULT '{}'"),
            ("email_zoho", "TEXT"),
            ("zoho_entidad_tipo", "TEXT"),
            ("zoho_id", "TEXT"),
            ("zoho_lead_status", "TEXT"),
            ("zoho_cuenta_id", "TEXT"),
            ("zoho_cuenta_nombre", "TEXT"),
            ("zoho_cuenta_dueno", "TEXT"),
            ("zoho_cuenta_tipo", "TEXT"),
            ("zoho_cuenta_es_cliente", "INTEGER DEFAULT 0"),
            ("zoho_tratos_info", "TEXT DEFAULT '[]'"),
            ("zoho_synced_at", "TEXT"),
            ("zoho_email_extracted_at", "TEXT"),
            ("crm_external_id", "TEXT"),
            ("crm_sync_status", "TEXT"),
            ("crm_synced_at", "TEXT"),
            ("source", "TEXT DEFAULT 'LINKEDIN'"),
            ("source_url", "TEXT"),
            ("legal_basis", "TEXT DEFAULT 'INTERES_LEGITIMO'"),
            ("collected_at", "TEXT")
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
    row = cursor.fetchone()
    count = row["total"] if isinstance(row, dict) else row[0]
    if count > 0:
        return

    target_tenant = "ten_superadmin"
    cursor.execute("SELECT id FROM tenants WHERE id = 'ten_superadmin'")
    if not cursor.fetchone():
        cursor.execute("SELECT id FROM tenants ORDER BY created_at ASC LIMIT 1")
        t_row = cursor.fetchone()
        if t_row:
            target_tenant = t_row["id"] if isinstance(t_row, dict) else t_row[0]
        else:
            return

    sec_id = "sec-default-directores-2026"
    cursor.execute("""
        INSERT INTO secuencias (id, tenant_id, nombre, descripcion, activa, es_default, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, ?, ?)
    """, (
        sec_id,
        target_tenant,
        "Outreach Directores 2026 (LinkedIn + Workspace Multicanal)",
        "Árbol de decisión completo: Visita de perfil -> Espera 4h -> Invitación -> Bifurcación: Si conecta -> Mensajes LinkedIn en secuencia; Si no conecta -> Cold Email Google Workspace institucional.",
        now_iso,
        now_iso
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
        """, (p_id, s_id, padre_id, cond, tipo, params, orden, now_iso))

    seed_default_lead_list(cursor, now_iso)

def ensure_default_sequences_for_all_tenants(cursor, now_iso):
    """
    Ensures every active tenant has at least one complete multichannel sequence configured.
    Includes LinkedIn, Google Workspace Email, and local WhatsApp Web actions with human antiban timing.
    Connects existing tenant lists and auto-enrolls ready leads into the sequence tree.
    """
    try:
        import secrets
        cursor.execute("SELECT id, razon_social FROM tenants WHERE estado = 'ACTIVO'")
        tenants = cursor.fetchall()
        for t in tenants:
            tid = t["id"] if isinstance(t, dict) else t[0]
            cursor.execute("SELECT COUNT(*) as total FROM secuencias WHERE tenant_id = ?", (tid,))
            row = cursor.fetchone()
            count = row["total"] if isinstance(row, dict) else row[0]
            if count == 0:
                sec_id = f"sec-{tid[:8]}-{secrets.token_hex(3)}"
                cursor.execute("""
                    INSERT INTO secuencias (id, nombre, descripcion, activa, es_default, estado, tenant_id, created_at, updated_at)
                    VALUES (?, 'Outreach Multicanal (LinkedIn + Workspace + WhatsApp Web)', 
                            'Secuencia inteligente de prospección: LinkedIn, seguimiento Google Workspace y mensajes WhatsApp Web local con tiempos antiban.',
                            1, 1, 'PUBLICADA', ?, ?, ?)
                """, (sec_id, tid, now_iso, now_iso))

                pasos = [
                    (f"step-{sec_id}-1", sec_id, None, "DEFAULT", "VISITAR_PERFIL", json.dumps({
                        "tiempo_lectura_min_seg": 6,
                        "tiempo_lectura_max_seg": 12,
                        "simular_scroll": True,
                        "etiqueta": "1. Visitar Perfil LinkedIn (Scroll y Lectura Humana)"
                    }), 1),
                    (f"step-{sec_id}-2", sec_id, f"step-{sec_id}-1", "DEFAULT", "ESPERAR", json.dumps({
                        "horas_espera": 4,
                        "etiqueta": "2. Esperar 4 Horas (Pausa Estratégica)"
                    }), 2),
                    (f"step-{sec_id}-3", sec_id, f"step-{sec_id}-2", "DEFAULT", "ENVIAR_INVITACION", json.dumps({
                        "incluir_nota": True,
                        "usar_spintax": True,
                        "plantilla_nota": "Hola {nombre}, un gusto saludarte. Veo tu labor en {empresa}. Me encantaría conectar contigo por este medio.",
                        "etiqueta": "3. Enviar Invitación a Conectar (Nota Personalizada)"
                    }), 3),
                    (f"step-{sec_id}-4", sec_id, f"step-{sec_id}-3", "DEFAULT", "ESPERAR", json.dumps({
                        "horas_espera": 48,
                        "etiqueta": "4. Esperar 48 Horas para Aceptación"
                    }), 4),
                    (f"step-{sec_id}-5", sec_id, f"step-{sec_id}-4", "DEFAULT", "VERIFICAR_ESTADO", json.dumps({
                        "descripcion": "¿El contacto aceptó la invitación?",
                        "etiqueta": "5. Bifurcación Condicional: ¿Aceptó en LinkedIn?"
                    }), 5),

                    # RAMA A: SI ACEPTÓ (Canal LinkedIn)
                    (f"step-{sec_id}-6a", sec_id, f"step-{sec_id}-5", "SI_ACEPTO", "ENVIAR_MENSAJE_LINKEDIN", json.dumps({
                        "asunto": "Mensaje de Bienvenida",
                        "plantilla_mensaje": "Hola {nombre}, un gusto conectar contigo. Quería compartirte algunas iniciativas prácticas que estamos desarrollando en torno a optimización de procesos en {empresa}. ¿Te interesaría revisar una breve síntesis?",
                        "etiqueta": "6A. [Si Conectó] Enviar Mensaje 1 de Valor en LinkedIn"
                    }), 6),
                    (f"step-{sec_id}-7a", sec_id, f"step-{sec_id}-6a", "DEFAULT", "ESPERAR", json.dumps({
                        "horas_espera": 72,
                        "etiqueta": "7A. Esperar 3 Días (72 hrs)"
                    }), 7),
                    (f"step-{sec_id}-8a", sec_id, f"step-{sec_id}-7a", "DEFAULT", "ENVIAR_MENSAJE_LINKEDIN", json.dumps({
                        "asunto": "Mensaje de Seguimiento",
                        "plantilla_mensaje": "Estimado/a {nombre}, espero que estés teniendo una excelente semana en {empresa}. Quería consultar si tuviste ocasión de revisar mi mensaje anterior o si prefieres coordinar una llamada breve de 10 minutos.",
                        "etiqueta": "8A. Enviar Mensaje 2 de Seguimiento en LinkedIn"
                    }), 8),

                    # RAMA B: SI NO ACEPTÓ (Canal Email Workspace + WhatsApp Web Local)
                    (f"step-{sec_id}-6b", sec_id, f"step-{sec_id}-5", "SI_NO_ACEPTO", "ENVIAR_CORREO_WORKSPACE", json.dumps({
                        "asunto": "Oportunidad de colaboración con {empresa}",
                        "cuerpo_email": "Estimado/a {nombre},\n\nEspero que se encuentre muy bien. Le escribo en relación a su labor en {empresa}.\n\nIntenté conectar con usted recientemente por LinkedIn; no obstante, le escribo por este medio formal para presentarle una breve síntesis de herramientas para optimizar operaciones...\n\nQuedo a su disposición si estima conveniente conversar brevemente.\n\nAtentamente,\nGabriel",
                        "requiere_email_valido": True,
                        "etiqueta": "6B. [Si NO Conectó] Enviar Email Google Workspace"
                    }), 6),
                    (f"step-{sec_id}-7b", sec_id, f"step-{sec_id}-6b", "DEFAULT", "ESPERAR", json.dumps({
                        "horas_espera": 48,
                        "etiqueta": "7B. Esperar 48 Horas"
                    }), 7),
                    (f"step-{sec_id}-8b", sec_id, f"step-{sec_id}-7b", "DEFAULT", "ENVIAR_WHATSAPP_WEB", json.dumps({
                        "plantilla_mensaje": "{Hola|Buenos días} {nombre}, espero que estés muy bien. Te contacto brevemente en relación a tu gestión en {empresa}. Te había enviado un correo anteriormente y quería dejarte mi contacto directo por esta vía.",
                        "etiqueta": "8B. [Multicanal] Enviar Mensaje WhatsApp Web Local (Antiban)"
                    }), 8),
                    (f"step-{sec_id}-9b", sec_id, f"step-{sec_id}-8b", "DEFAULT", "ESPERAR", json.dumps({
                        "horas_espera": 96,
                        "etiqueta": "9B. Esperar 4 Días (96 hrs)"
                    }), 9),
                    (f"step-{sec_id}-10b", sec_id, f"step-{sec_id}-9b", "DEFAULT", "RETIRAR_INVITACION", json.dumps({
                        "motivo": "Retiro automático por falta de respuesta para proteger ratio de cuenta",
                        "etiqueta": "10B. Retirar Solicitud de Conexión en LinkedIn"
                    }), 10)
                ]

                for p_id, s_id, padre_id, cond, tipo, params_json, orden in pasos:
                    cursor.execute("""
                        INSERT INTO pasos_secuencia (id, secuencia_id, padre_paso_id, condicion_rama, tipo_accion, parametros_json, orden, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (p_id, s_id, padre_id, cond, tipo, params_json, orden, now_iso))

                # Vincular listas del tenant a la secuencia
                cursor.execute("SELECT id FROM listas_leads WHERE tenant_id = ?", (tid,))
                tenant_lists = cursor.fetchall()
                for lst in tenant_lists:
                    lid = lst["id"] if isinstance(lst, dict) else lst[0]
                    cursor.execute("""
                        INSERT OR IGNORE INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
                        VALUES (?, ?, ?, 1, 1, ?)
                    """, (f"sl-{sec_id}-{lid}", sec_id, lid, now_iso))

                    # Auto-enrolar leads con datos extraídos
                    cursor.execute("""
                        SELECT ld.id 
                        FROM leads_en_lista ll
                        JOIN leads ld ON ll.lead_id = ld.id
                        WHERE ll.lista_id = ? 
                          AND ld.cargo_actual IS NOT NULL 
                          AND ld.cargo_actual != '' 
                          AND ld.cargo_actual != 'No determinado'
                    """, (lid,))
                    ready_leads = cursor.fetchall()
                    root_step_id = f"step-{sec_id}-1"
                    for rld in ready_leads:
                        lead_id = rld["id"] if isinstance(rld, dict) else rld[0]
                        cursor.execute("""
                            INSERT OR IGNORE INTO leads_en_secuencia (id, lead_id, secuencia_id, paso_actual_id, estado, proxima_ejecucion_at, created_at, updated_at)
                            VALUES (?, ?, ?, ?, 'EN_CURSO', ?, ?, ?)
                        """, (f"les-{sec_id}-{lead_id}", lead_id, sec_id, root_step_id, now_iso, now_iso, now_iso))
    except Exception as e:
        print(f"[DB Migration] Warning ensuring default sequences: {e}")

def seed_default_lead_list(cursor, ahora_iso):
    """Inicializa la lista de prospectos por defecto si la tabla está vacía."""
    cursor.execute("SELECT COUNT(*) as total FROM listas_leads")
    row = cursor.fetchone()
    count = row["total"] if isinstance(row, dict) else row[0]
    if count > 0:
        return

    target_tenant = "ten_superadmin"
    cursor.execute("SELECT id FROM tenants WHERE id = 'ten_superadmin'")
    if not cursor.fetchone():
        cursor.execute("SELECT id FROM tenants ORDER BY created_at ASC LIMIT 1")
        t_row = cursor.fetchone()
        if t_row:
            target_tenant = t_row["id"] if isinstance(t_row, dict) else t_row[0]
        else:
            return

    lista_id = "lista-directores-chile-lote-1"
    cursor.execute("""
        INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, termino_busqueda, estado, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'ACTIVA', ?, ?)
    """, (
        lista_id,
        target_tenant,
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
        lead_id = l["id"] if isinstance(l, dict) else l[0]
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO leads_en_lista (id, lista_id, lead_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (lista_id, lead_id) DO NOTHING
            """, (f"ll-{lista_id}-{lead_id}", lista_id, lead_id, ahora_iso))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id, created_at)
                VALUES (?, ?, ?, ?)
            """, (f"ll-{lista_id}-{lead_id}", lista_id, lead_id, ahora_iso))

    # Conectar esta lista a la secuencia por defecto
    if IS_POSTGRES:
        cursor.execute("""
            INSERT INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
            VALUES (?, 'sec-default-directores-2026', ?, 1, 1, ?)
            ON CONFLICT (secuencia_id, lista_id) DO NOTHING
        """, (f"sl-sec-default-{lista_id}", lista_id, ahora_iso))
    else:
        cursor.execute("""
            INSERT OR IGNORE INTO secuencia_listas (id, secuencia_id, lista_id, activa, auto_ingresar_nuevos, created_at)
            VALUES (?, 'sec-default-directores-2026', ?, 1, 1, ?)
        """, (f"sl-sec-default-{lista_id}", lista_id, ahora_iso))

def migrate_from_json() -> int:
    """Migra prospectos históricos desde archivos JSON iniciales a la base de datos."""
    init_db()
    json_path = os.path.join(os.path.dirname(__file__), "scripts", "seeds", "prospectos_seed.json")
    if not os.path.exists(json_path):
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



if __name__ == "__main__":
    init_db()
    migrados = migrate_from_json()
    print(f"Base de datos leads.db inicializada con éxito. Migrados: {migrados} leads.")
