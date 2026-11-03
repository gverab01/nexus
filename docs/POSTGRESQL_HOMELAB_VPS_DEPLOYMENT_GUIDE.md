# NEXUSREACH PRO — INFORME TÉCNICO Y ESPECIFICACIÓN DE DESPLIEGUE POSTGRESQL 16
## GUÍA OPERACIONAL Y DE ARQUITECTURA PARA HOMELAB / SERVIDOR VPS

- **Destinatario:** Agente de Despliegue / Administrador de Infraestructura (DevOps / SysAdmin)
- **Sistema:** NexusReach Pro (Backend FastAPI + PostgreSQL 16)
- **Objetivo:** Proporcionar la arquitectura, directivas de seguridad, configuración de contenedores, inicialización limpia (Clean Bootstrap), respaldos automáticos y checklist de auditoría para el despliegue en servidor Homelab / VPS.
- **Versión de Documento:** 1.0 (Producción)

---

## 1. RESUMEN EJECUTIVO Y FICHA TÉCNICA

NexusReach Pro utiliza **PostgreSQL 16** como su motor de base de datos relacional primario y obligatorio. La arquitectura está desacoplada de SQLite (que se mantiene únicamente como archivo histórico inmutable de solo lectura en `leads.db`).

### Ficha Técnica de la Base de Datos
| Parámetro | Valor Canónico / Especificación |
| :--- | :--- |
| **Motor & Versión** | PostgreSQL 16 (Imagen recomendada: `postgres:16-alpine` o `postgres:16-bookworm`) |
| **Nombre de Base de Datos** | `nexusreach_prod` |
| **Esquema Principal** | `public` |
| **Puerto Estándar** | `5432` (**Aislado estrictamente en `127.0.0.1` o red privada Docker, NUNCA expuesto a WAN / 0.0.0.0**) |
| **Aislamiento Multi-Tenant** | Nativo mediante **Row-Level Security (RLS)** y `FORCE ROW LEVEL SECURITY` |
| **Mecanismo de Conexión** | Pool de conexiones `psycopg` (v3) + `psycopg_pool.ConnectionPool` (2 a 10 hilos por réplica) |
| **Estrategia de Datos Inicial** | **Clean Bootstrap**: 1 tenant (`ten_primary`), 1 admin (`admin@nexusreach.com`), 0 prospectos residuales |

---

## 2. MODELO DE SEGURIDAD Y ROLES DE BASE DE DATOS

Por principio de mínimo privilegio y mitigación contra inyección SQL o elevación lateral, el sistema exige **dos roles separados**:

```
                                  ┌───────────────────────────┐
                                  │      nexus_admin          │
                                  │  (Owner / DDL / Migrator) │
                                  └─────────────┬─────────────┘
                                                │ Bootstrap / Migraciones / DDL
                                                ▼
┌─────────────────────────┐         ┌───────────────────────────┐
│     FastAPI Backend     │ ──────> │      nexusreach_prod      │
│      (nexus_app)        │   DML   │    (Tablas + 32 RLS)      │
└─────────────────────────┘         └───────────────────────────┘
```

### 2.1. Rol Operacional de Aplicación: `nexus_app`
Este es el único rol utilizado por el backend de FastAPI en tiempo de ejecución (`DATABASE_URL`).
- **Privilegios:** `SELECT, INSERT, UPDATE, DELETE` en tablas públicas existentes; `USAGE, SELECT` en secuencias.
- **Restricciones Mandatorias:**
  - `NOSUPERUSER`
  - `NOCREATEDB`
  - `NOCREATEROLE`
  - `NOINHERIT`
  - **`NOBYPASSRLS`** (Estrictamente auditado: si este flag está activo, la seguridad multi-tenant queda comprometida).
  - **`REVOKE ALL ON TABLE system_admin_keys FROM nexus_app`**: Acceso revocado a tablas que almacenan hashes de bypass de SuperAdmin.
- **Permisos de Ejecución Específicos:**
  - `GRANT EXECUTE ON FUNCTION verify_super_admin_context() TO nexus_app`

### 2.2. Rol de Mantenimiento y Migración: `nexus_admin`
Rol reservado exclusivamente para la creación inicial de tablas, ejecución de scripts de bootstrap y migraciones de esquema (`POSTGRES_ADMIN_URL`).
- Propietario (`OWNER`) de la base de datos `nexusreach_prod` y del esquema `public`.
- Posee privilegios DDL (`CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`).
- **Nunca debe utilizarse como conexión principal del servidor web/API.**

---

## 3. ARQUITECTURA MULTI-TENANT Y ROW-LEVEL SECURITY (RLS)

### 3.1. Tablas Protegidas
Existen **32 tablas multi-tenant** en las cuales RLS está habilitado y forzado (`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`). Esto garantiza que incluso si una consulta omite un `WHERE tenant_id = ...`, el motor de PostgreSQL impide la filtración o modificación de datos ajenos.

### 3.2. Variables de Contexto de Sesión
El backend inyecta variables de sesión al inicio de cada transacción o petición mediante `SET LOCAL`:

| Variable de Sesión | Tipo / Formato | Propósito |
| :--- | :--- | :--- |
| `app.current_tenant_id` | String (`ten_primary`, etc.) | Identificador del tenant activo en la petición |
| `app.is_super_admin` | `'true'` / `'false'` | Bandera que indica si el token de sesión reclama privilegios globales |
| `app.super_admin_token` | Hex SHA-256 (64 chars) | Secreto criptográfico validado mediante HMAC en DB |
| `app.allow_agency_subtenants` | `'true'` / `'false'` | Bandera para visibilidad jerárquica de subcuentas |

### 3.3. Validación Criptográfica Fail-Closed
El bypass de RLS no se concede por la simple presencia de una bandera. La función SQL `verify_super_admin_context()` computa el hash del token suministrado contra `system_admin_keys`: si la firma no coincide o no existe contexto, la evaluación retorna `FALSE` (Fail-Closed inmediato, 0 filas visibles).

---

## 4. ESPECIFICACIÓN DE DESPLIEGUE EN HOMELAB / VPS (DOCKER COMPOSE)

A continuación se detalla la configuración recomendada de contenedores para Homelab / VPS en Linux (Ubuntu/Debian) o WSL2/Windows.

### 4.1. Archivo `docker-compose.yml`

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: nexusreach_postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: nexusreach_prod
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_ROOT_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backups/postgres:/backups
    ports:
      # Bindeo ESTRICTO a localhost para evitar exposición en red pública / VPS
      - "127.0.0.1:5432:5432"
    command: >
      postgres
        -c max_connections=100
        -c shared_buffers=256MB
        -c effective_cache_size=768MB
        -c maintenance_work_mem=64MB
        -c checkpoint_completion_target=0.9
        -c wal_buffers=16MB
        -c default_statistics_target=100
        -c random_page_cost=1.1
        -c work_mem=4MB
        -c log_timezone='UTC'
        -c timezone='UTC'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d nexusreach_prod"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - nexus_network

volumes:
  postgres_data:
    driver: local

networks:
  nexus_network:
    driver: bridge
```

> [!CAUTION]
> En entornos VPS expuestos a Internet con IP pública, **NUNCA** publiques el puerto como `0.0.0.0:5432:5432`. El mapeo `127.0.0.1:5432:5432` asegura que solo los procesos locales o un túnel SSH puedan comunicarse con la base de datos.

---

## 5. GUÍA PASO A PASO: PROCESO DE INICIALIZACIÓN (BOOTSTRAP)

Una vez que el contenedor PostgreSQL esté en estado `healthy`, el agente debe seguir esta secuencia estricta:

### Paso 1: Creación de Roles y Permisos Base
Conectar como superusuario (`postgres`) para crear los roles `nexus_admin` y `nexus_app`:

```bash
# Variables temporales de contraseñas de alta entropía (generar con openssl rand -hex 24)
APP_PASS="<GENERAR_APP_PASSWORD>"
ADMIN_PASS="<GENERAR_ADMIN_PASSWORD>"

# Ejecución de SQL de aprovisionamiento de roles
docker exec -i nexusreach_postgres psql -U postgres -d nexusreach_prod <<EOF
-- Crear roles si no existen
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_admin') THEN
        CREATE ROLE nexus_admin WITH LOGIN PASSWORD '${ADMIN_PASS}' CREATEDB NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app') THEN
        CREATE ROLE nexus_app WITH LOGIN PASSWORD '${APP_PASS}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
\$\$;

-- Asignar ownership
ALTER DATABASE nexusreach_prod OWNER TO nexus_admin;
GRANT ALL ON SCHEMA public TO nexus_admin;
GRANT CONNECT ON DATABASE nexusreach_prod TO nexus_app;
GRANT USAGE ON SCHEMA public TO nexus_app;
EOF
```

### Paso 2: Aplicación del Esquema DDL y RLS
Ejecutar el esquema completo utilizando el usuario propietario `nexus_admin`:

```bash
docker exec -i nexusreach_postgres psql -U nexus_admin -d nexusreach_prod < schema_postgres.sql
```

### Paso 3: Concesión de Permisos DML a `nexus_app`
```bash
docker exec -i nexusreach_postgres psql -U nexus_admin -d nexusreach_prod <<EOF
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexus_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO nexus_app;

-- Revocación de seguridad sobre tabla de secretos
REVOKE ALL ON TABLE system_admin_keys FROM PUBLIC, nexus_app;

-- Permiso de ejecución en función criptográfica
GRANT EXECUTE ON FUNCTION verify_super_admin_context() TO nexus_app;
EOF
```

### Paso 4: Ejecución del Bootstrap Operacional Limpio
Desde la raíz del proyecto NexusReach Pro (con el entorno virtual de Python activo):

```bash
export TARGET_DATABASE_URL="postgresql://nexus_admin:${ADMIN_PASS}@127.0.0.1:5432/nexusreach_prod"
export SUPERADMIN_RLS_SECRET="<GENERAR_64_CHARS_HEX>"
export INITIAL_ADMIN_PASSWORD="<GENERAR_ADMIN_APP_PASSWORD>"

# Ejecutar el bootstrap
python scripts/bootstrap_postgres_clean.py --bootstrap

# Validar estado limpio y libre de prospectos residuales
python scripts/bootstrap_postgres_clean.py --verify-only
```

---

## 6. PLANTILLA DE CONFIGURACIÓN DE VARIABLES DE ENTORNO (`.env`)

En el servidor Homelab / VPS, el archivo `.env` en la raíz de NexusReach Pro debe contener:

```ini
# ==============================================================================
# NEXUSREACH PRO - PRODUCTION CONFIGURATION
# ==============================================================================

# 1. Motor de Base de Datos (OBLIGATORIO: postgres)
DB_ENGINE=postgres

# 2. Conexión Operacional de la API (Bajo el rol restringido nexus_app)
DATABASE_URL=postgresql://nexus_app:<APP_PASSWORD>@127.0.0.1:5432/nexusreach_prod
POSTGRES_APP_URL=postgresql://nexus_app:<APP_PASSWORD>@127.0.0.1:5432/nexusreach_prod

# 3. Conexión Administrativa (Solo para scripts de mantenimiento / backup)
POSTGRES_ADMIN_URL=postgresql://nexus_admin:<ADMIN_PASSWORD>@127.0.0.1:5432/nexusreach_prod

# 4. Secreto Criptográfico HMAC-SHA256 para Bypass Autorizado de SuperAdmin en RLS
# (Debe coincidir exactamente con el hash registrado en system_admin_keys)
SUPERADMIN_RLS_SECRET=<TOKEN_HEX_64_CARACTERES>

# 5. Parámetros del Servidor de Aplicación
ENV=production
HOST=127.0.0.1
PORT=8000

# 6. Datos de Administrador Inicial
INITIAL_ADMIN_EMAIL=admin@nexusreach.com
```

### Cómo Generar Claves Seguras
En la terminal del servidor, genera los secretos ejecutando:
```bash
# Secreto HMAC SuperAdmin (64 caracteres hexadecimales)
python3 -c "import secrets; print(secrets.token_hex(32))"

# Contraseña de base de datos nexus_app y nexus_admin
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

---

## 7. AUTOMATIZACIÓN DE RESPALDOS Y RECUPERACIÓN ANTE DESASTRES

El proyecto incluye el motor de respaldo automatizado en [`scripts/backup_postgres.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/backup_postgres.py).

### Características del Sistema de Respaldo
- **Formato:** Volcado `pg_dump` binario custom comprimido (`-Fc`).
- **Integridad:** Validación del encabezado mágico `PGDMP` y cálculo de hash SHA-256.
- **Retención:** 7 copias diarias continuas con rotación automática (los respaldos más antiguos se eliminan de forma segura).
- **Ruta en Host:** `backups/postgres/nexusreach_prod_backup_YYYYMMDD_HHMMSS.dump`.
- **Bitácora:** `backups/postgres/backup_history.log`.

### 7.1. Programación del Cron Job en VPS (Linux)
Añade la siguiente tarea al crontab del usuario que opera la aplicación (`crontab -e`):

```cron
# Ejecutar respaldo diario de PostgreSQL a las 02:00 AM con retención de 7 días
0 2 * * * cd /ruta/al/proyecto && /ruta/al/venv/bin/python scripts/backup_postgres.py --retention 7 >> /var/log/nexus_backup_cron.log 2>&1
```

### 7.2. Verificación de Restauración
Para probar la consistencia de un respaldo sin afectar la base operativa, ejecutar:
```bash
python scripts/verify_backup_restoration.py --backup-file backups/postgres/<NOMBRE_ARCHIVO>.dump
```
Este script crea una base de datos efímera `nexusreach_restore_test`, restaura el esquema, verifica conteos de tablas y políticas RLS, y luego limpia la base de pruebas.

---

## 8. CHECKLIST DE AUDITORÍA POST-DESPLIEGUE PARA EL AGENTE

Una vez desplegado el entorno, el agente debe ejecutar las siguientes consultas de validación en PostgreSQL:

### 1. Verificar que `nexus_app` NO tenga atributos de superusuario ni `BYPASSRLS`
```sql
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls 
FROM pg_roles 
WHERE rolname IN ('nexus_app', 'nexus_admin');
```
*Criterio de Aceptación:* `nexus_app` debe tener `rolsuper = false` y `rolbypassrls = false`.

### 2. Verificar que las 32 tablas tengan RLS forzado
```sql
SELECT relname, relrowsecurity, relforcerowsecurity 
FROM pg_class c 
JOIN pg_namespace n ON n.oid = c.relnamespace 
WHERE n.nspname = 'public' 
  AND c.relkind = 'r' 
  AND c.relname NOT IN ('schema_migrations', 'system_admin_keys')
  AND (relrowsecurity = false OR relforcerowsecurity = false);
```
*Criterio de Aceptación:* **0 filas devueltas** (todas las tablas operacionales deben tener `relrowsecurity = true` y `relforcerowsecurity = true`).

### 3. Verificar denegación estricta de `system_admin_keys` a `nexus_app`
```sql
-- Ejecutar conectado como nexus_app:
SELECT * FROM system_admin_keys;
```
*Criterio de Aceptación:* Debe fallar con `ERROR: permission denied for table system_admin_keys`.

### 4. Verificar salud del servicio FastAPI
```bash
curl -I http://127.0.0.1:8000/health
```
*Criterio de Aceptación:* HTTP 200 OK con estado operacional confirmado.

---

## 9. INFORMACIÓN DE CONTACTO / SOPORTE DE ARQUITECTURA
Si durante el despliegue surgen inconsistencias en extensiones o restricciones de red en el homelab:
1. Consultar el runbook de corte operacional en `docs/TASK-05B_CUTOVER_RUNBOOK.md`.
2. Para rollback de emergencia, seguir el procedimiento en `docs/TASK-05B_ROLLBACK_RUNBOOK.md`.
3. Para rotación de credenciales, ejecutar `python scripts/rotate_postgres_credentials.py`.

