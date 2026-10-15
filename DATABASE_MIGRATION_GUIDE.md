# Guía Completa de Migración a PostgreSQL con Row-Level Security (RLS)
## NexusReach Pro Multi-Tenant Cloud Architecture

Esta guía documenta la arquitectura dual y el procedimiento paso a paso para migrar la base de datos de **SQLite (`leads.db`)** a **PostgreSQL** en la nube con aislamiento estricto mediante **Row-Level Security (RLS)** a nivel de motor.

---

### 1. ¿Cómo Funciona la Arquitectura Dual?

El sistema cuenta con un adaptador transparente en [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py):

- **Modo Local (Por defecto)**: Si la variable de entorno `DATABASE_URL` no está definida o está vacía, el sistema usa SQLite en [`leads.db`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/leads.db) en modo WAL. Es ideal para desarrollo local o uso sin conexión.
- **Modo Cloud PostgreSQL**: En el momento en que se define `DATABASE_URL=postgresql://...` en el archivo `.env`, el sistema se conecta a PostgreSQL de forma automática, aplicando:
  - Compatibilidad completa de consultas y placeholders (`?` a `%s`).
  - Row factory tipado como diccionario (`dict_row`).
  - **Aislamiento por Row-Level Security (RLS)** inyectando el contexto de sesión:
    ```sql
    SET LOCAL app.current_tenant_id = 'ten_gabriel';
    SET LOCAL app.is_super_admin = 'false';
    ```

---

### 2. Cómo Obtener una Base de Datos PostgreSQL Gratuita en 2 Minutos

Cualquier proveedor estándar de PostgreSQL funciona con Nexus. Dos de las opciones más recomendadas y rápidas son:

#### Opción A: Neon.tech (Serveless Postgres - Muy Recomendado)
1. Ve a [neon.tech](https://neon.tech) y crea una cuenta gratuita.
2. Crea un proyecto nuevo (ej. `nexus-production`).
3. En el dashboard copia la cadena de conexión:
   ```
   postgresql://usuario:password@ep-ejemplo.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

#### Opción B: Supabase (Postgres Gestionado)
1. Ve a [supabase.com](https://supabase.com) y crea un nuevo proyecto.
2. En `Project Settings > Database > Connection string > URI`, copia la URL de conexión.

---

### 3. Procedimiento de Migración de Datos (Paso a Paso)

El script automatizado [`scripts/migrate_sqlite_to_postgres.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/migrate_sqlite_to_postgres.py) se encarga de todo el proceso:

#### Paso 1: Simulación previa (Dry-Run)
Para analizar cuántos registros existen en cada tabla sin escribir nada en PostgreSQL:
```bash
python scripts/migrate_sqlite_to_postgres.py --dest "postgresql://usuario:password@host/dbname" --dry-run
```

#### Paso 2: Ejecutar la migración real
```bash
python scripts/migrate_sqlite_to_postgres.py --dest "postgresql://usuario:password@host/dbname"
```

El script ejecutará automáticamente:
1. Creación de las 17 tablas normalizadas desde [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql).
2. Creación de todos los índices optimizados.
3. Activación y configuración de las políticas de **Row-Level Security (RLS)** en todas las tablas de negocio.
4. Volcado ordenado de registros respetando dependencias de claves foráneas.
5. Reajuste de secuencias autoincrementales (`SERIAL`).
6. **Prueba de verificación RLS**: Comprueba en tiempo real que el Super Admin vea el universo global y que un tenant específico solo vea sus propios prospectos.

---

### 4. Activar PostgreSQL en la Aplicación

Una vez finalizada la migración, para que el servidor FastAPI utilice PostgreSQL de forma permanente:

1. Crea o edita el archivo `.env` en la raíz del proyecto (basado en [`.env.example`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/.env.example)):
   ```env
   DATABASE_URL=postgresql://usuario:password@host/dbname?sslmode=require
   PORT=8000
   HOST=127.0.0.1
   ```
2. Reinicia el servidor FastAPI:
   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. El log del servidor confirmará:
   ```
   [INFO] Conectado a PostgreSQL con Row-Level Security activo.
   ```

---

### 5. Resumen de Seguridad Multi-Tenant

| Capa de Seguridad | Implementación en SQLite | Implementación en PostgreSQL |
| :--- | :--- | :--- |
| **Aislamiento de Leads** | Filtro SQL en código (`WHERE tenant_id = ?`) | **Garantizado por el Motor con RLS (`USING tenant_id = ...`)** |
| **Prevención de Fuga de Datos** | Depende del programador | **Física e impenetrable en el kernel de la BD** |
| **Unicidad de Perfiles** | Índice único `(tenant_id, perfil_url)` | Constraint nativo `uq_leads_tenant_url` |
| **Consola Master Super Admin** | Filtro manual por tenant | Bypass autorizado por rol en RLS |
| **Concurrencia / Bloqueos** | Bloqueo de archivo (WAL) | Concurrencia transaccional MVCC ilimitada |
