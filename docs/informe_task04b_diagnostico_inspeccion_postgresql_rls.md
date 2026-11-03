# DIAGNÓSTICO PREVIO E INSPECCIÓN OBLIGATORIA — TASK-04B

**Fecha:** 28 de octubre de 2026  
**Proyecto:** NexusReach Pro  
**Tarea:** `TASK-04B` — Implementación y validación real del aislamiento multi-tenant en PostgreSQL mediante RLS  
**Fase:** Fase 1 — Inspección Obligatoria y Diagnóstico

---

## 1. Inspección de `database.py`, `schema_postgres.sql`, conexiones y migraciones

Tras la inspección estática y comparativa de los archivos de persistencia, se detectaron los siguientes hallazgos críticos:

### A. Error de sintaxis SQL bloqueante en `schema_postgres.sql`
- En [`schema_postgres.sql`](../schema_postgres.sql#L468-L476), la política `rls_audit_logs_policy` tiene un error de sintaxis que impide ejecutar el script en cualquier servidor PostgreSQL real:
  ```sql
  CREATE POLICY rls_audit_logs_policy ON audit_logs
      FOR ALL
      USING (
          current_setting('app.is_super_admin', true) = 'true'
          OR tenant_id = current_setting('app.current_tenant_id', true)
          OR tenant_id IN (
              SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
      ); -- << FALTA PARÉNTESIS DE CIERRE ')'
  ```
- Este error interrumpe la carga de cualquier esquema en PostgreSQL (`syntax error at or near ";"`).

### B. Tabla ausente en `schema_postgres.sql`
- La tabla [`mensajes_whatsapp`](../database.py#L317-L330) (creada en SQLite en `database.py`) no existe en [`schema_postgres.sql`](../schema_postgres.sql), a pesar de que la línea 308 intenta crear un índice sobre ella (`CREATE INDEX IF NOT EXISTS idx_mensajes_whatsapp_lead ON mensajes_whatsapp(lead_id);`), lo que generaría un error de relación inexistente.

### C. Fallback residual de tenant hardcodeado en el esquema PostgreSQL
- En [`schema_postgres.sql`](../schema_postgres.sql), las tablas `leads` (línea 91), `listas_leads` (línea 146) y `secuencias` (línea 167) conservan:
  `tenant_id VARCHAR(64) NOT NULL DEFAULT 'ten_superadmin'`
- Este valor por defecto vulnera el principio de aislamiento estricto y contraviene la regla de "no introducir fallbacks inseguros ni defaults a identidades privilegiadas".

### D. Sintaxis de inicialización no compatible con PostgreSQL en `init_db()`
- En [`database.py`](../database.py#L215-L217), cuando `IS_POSTGRES = True`, `init_db()` invoca `seed_default_users`, `seed_default_sequence` y `seed_default_lead_list`.
- Dichas funciones ejecutan instrucciones con sintaxis privativa de SQLite (`INSERT OR REPLACE INTO usuarios ...`, `INSERT OR IGNORE INTO leads_en_lista ...`), lo que fallará en PostgreSQL si no se normalizan a `INSERT ... ON CONFLICT (...) DO UPDATE / DO NOTHING`.

---

## 2. Identificación del flujo de `tenant_id` y contexto de sesión

1. **Obtención del tenant autenticado:**
   - La API autentica al usuario mediante [`_get_current_user(request)`](../main.py#L246-L258) validando el token contra `auth_service.verify_token(token)`.
   - El tenant autorizado se resuelve con [`_resolve_permitted_tenants(caller, tenant_query)`](../main.py#L269-L339), devolviendo una lista estricta mono-tenant (`target_tenant`).
2. **Propagación actual hacia la base de datos:**
   - [`database.py`](../database.py#L127-L143) define `_configure_pg_context(cur, tenant_id=None, is_super_admin=False)`, el cual ejecuta `SET LOCAL app.is_super_admin` y `SET LOCAL app.current_tenant_id = %s`.
   - **Brecha detectada:** La mayoría de los módulos de negocio ([`main.py`](../main.py), [`lists_engine.py`](../lists_engine.py), [`sequence_engine.py`](../sequence_engine.py), [`task_dispatcher.py`](../task_dispatcher.py)) invocaban históricamente `with get_db() as conn:` sin pasar `tenant_id`. En PostgreSQL con RLS activado, una conexión sin `tenant_id` queda confinada a 0 filas (`app.current_tenant_id = ''`), bloqueando todas las lecturas y escrituras si el contexto no se enlaza explícitamente a la transacción.

---

## 3. Inventario de tablas multi-tenant y estado de políticas RLS

Comparación de las 36 tablas del sistema:

| Tabla | Contiene `tenant_id` / Relación Tenant | RLS en `schema_postgres.sql` actual | Diagnóstico / Acción Requerida |
| :--- | :---: | :---: | :--- |
| `leads` | Sí (`tenant_id`) | Habilitado (`rls_leads_policy`) | Eliminar `DEFAULT 'ten_superadmin'`, añadir `FORCE RLS` y afinar `WITH CHECK`. |
| `listas_leads` | Sí (`tenant_id`) | Habilitado (`rls_listas_policy`) | Eliminar `DEFAULT 'ten_superadmin'`, añadir `FORCE RLS`. |
| `secuencias` | Sí (`tenant_id`) | Habilitado (`rls_secuencias_policy`) | Eliminar `DEFAULT 'ten_superadmin'`, añadir `FORCE RLS`. |
| `pasos_secuencia` | Vía `secuencia_id` | Habilitado (`rls_pasos_policy`) | Añadir `FORCE RLS`. |
| `leads_en_secuencia` | Vía `lead_id` y `secuencia_id` | Habilitado parcial (solo `lead_id`) | Proteger tanto `lead_id` como `secuencia_id` en `USING` y `WITH CHECK`, añadir `FORCE RLS`. |
| `leads_en_lista` | Vía `lead_id` y `lista_id` | Habilitado parcial (solo `lead_id`) | Proteger tanto `lead_id` como `lista_id` en `USING` y `WITH CHECK`, añadir `FORCE RLS`. |
| `secuencia_listas` | Vía `secuencia_id` y `lista_id` | **NO HABILITADO** | Requiere `ENABLE RLS`, `FORCE RLS` y política por `secuencia_id` + `lista_id`. |
| `mensajes_linkedin` | Vía `lead_id` | Habilitado (`rls_mensajes_policy`) | Añadir `FORCE RLS`. |
| `correos_electronicos` | Vía `lead_id` | Habilitado (`rls_correos_policy`) | Añadir `FORCE RLS`. |
| `mensajes_whatsapp` | Vía `lead_id` | **TABLA AUSENTE** | Crear tabla en esquema, `ENABLE RLS`, `FORCE RLS` y política RLS. |
| `interacciones_sociales` | Vía `lead_id` | **NO HABILITADO** | Requiere `ENABLE RLS`, `FORCE RLS` y política por `lead_id`. |
| `historial_actividades` | Vía `lead_id` | Habilitado (`rls_historial_policy`) | Añadir `FORCE RLS`. |
| `audit_logs` | Sí (`tenant_id`) | Habilitado con **error de sintaxis** | Corregir sintaxis SQL, añadir `WITH CHECK` y `FORCE RLS`. |
| `tenants` | Sí (`id`, `parent_tenant_id`) | **NO HABILITADO** | Habilitar `RLS` y `FORCE RLS` para lectura propia y de subtenants autorizados. |
| `suscripciones` | Sí (`tenant_id`) | **NO HABILITADO** | Habilitar `RLS`, `FORCE RLS` y política por `tenant_id`. |
| `usuarios` | Sí (`tenant_id`) | **NO HABILITADO** | Habilitar `RLS`, `FORCE RLS` (aislando usuarios por `tenant_id`). |
| `system_logs` | Sí (`tenant_id`) | **NO HABILITADO** | Habilitar `RLS`, `FORCE RLS` y política por `tenant_id`. |
| `devices` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `commands` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `command_results` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `suppression_list` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `lead_activity` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `linkedin_accounts` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `whatsapp_accounts` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `email_candidates` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `consent_records` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `credit_ledger` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `usage_events` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `usage_counters` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `subscriptions` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `entitlements` | Sí (`tenant_id`) | Habilitado | Añadir `FORCE RLS` y `WITH CHECK` estricto. |
| `selector_failure_logs` | Sí (`tenant_id`) | **NO HABILITADO** | Habilitar `RLS`, `FORCE RLS` y política por `tenant_id`. |
| `configuracion_seguridad` | Control Plane Global | No aplica RLS por tenant | Protegido por RBAC API (`SUPER_ADMIN`). |
| `selector_versions` | Control Plane Global | No aplica RLS por tenant | Catálogo firmado común a todos los workers. |
| `action_status` | Control Plane Global | No aplica RLS por tenant | Estado de selectores global. |
| `payment_webhook_events` | Integración Global Pasarela | No aplica RLS por tenant | Registro idempotente con firma de proveedor. |

---

## 4. Rol de PostgreSQL y privilegios efectivos

1. **Omisión de rol de aplicación:** Actualmente `schema_postgres.sql` no define un rol sin privilegios para la aplicación. Si la aplicación conecta con el usuario propietario de la base de datos (p. ej. `postgres` en local o el admin de RDS/Supabase), PostgreSQL **omite las políticas RLS por defecto**.
2. **Requisitos de rol para la aplicación:**
   - Debe crearse y configurarse el rol `nexus_app_role` con atributos: `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOBYPASSRLS`.
   - Se debe conceder únicamente `USAGE` sobre el esquema `public`, y privilegios DML (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) sobre las tablas, junto con `USAGE, SELECT` sobre secuencias.
3. **Importancia de `FORCE ROW LEVEL SECURITY`:**
   - La directiva `ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;` debe aplicarse a todas las tablas multi-tenant. De este modo, incluso si la conexión opera bajo el rol propietario de la tabla, las políticas RLS son forzadas rigurosamente por el motor de base de datos.
4. **Verificación de postura de seguridad:**
   - Se implementará en `database.py` la función `verify_pg_security_posture(conn)` que consulte `pg_roles` y `pg_class` para garantizar que la conexión activa no sea `SUPERUSER` y no posea `BYPASSRLS`.

---

## 5. Revisión de pruebas existentes

- [`tests/test_postgres_rls_security.py`](../tests/test_postgres_rls_security.py): Suite unitaria (8 escenarios con `MagicMock` y SQLite temporal) que valida que `_configure_pg_context` no asuma privilegios de superadmin por valores no tipados y emita los `SET LOCAL` esperados.
- [`tests/test_database_isolation.py`](../tests/test_database_isolation.py): Suite unitaria para aislamiento SQLite (`SQLITE_DB_PATH`).
- [`tests/test_auth_tenant_isolation_task03b.py`](../tests/test_auth_tenant_isolation_task03b.py) y [`tests/test_tenant_data_isolation.py`](../tests/test_tenant_data_isolation.py): Validan aislamiento en la capa REST contra SQLite temporal.
- **Brecha:** No existía hasta el momento una suite de integración real contra PostgreSQL que verifique RLS con un rol no privilegiado en una instancia de PostgreSQL en vivo.

---

## 6. Estado del entorno de ejecución y diagnóstico de infraestructura

Se realizaron las comprobaciones en el host local (Windows):
- Binarios PostgreSQL (`psql`, `postgres`, `initdb`, `pg_isready`): **No instalados en PATH ni en directorios estándar de Windows**.
- Docker / Podman: **No instalados / no disponibles en el entorno**.
- Puerto `5432`: **Cerrado (sin servicio de escucha local)**.
- Paquetes Python (`psycopg`, `psycopg2`, `psycopg_pool`): **No instalados en el entorno virtual actual**.

### Plan de Cambios Propuesto para Fase 2 y Fase 3:
1. **Actualizar [`schema_postgres.sql`](../schema_postgres.sql):**
   - Corregir el error de sintaxis en `audit_logs`.
   - Incorporar la tabla faltante `mensajes_whatsapp`.
   - Eliminar `DEFAULT 'ten_superadmin'` de las columnas `tenant_id`.
   - Habilitar `ENABLE ROW LEVEL SECURITY` y `FORCE ROW LEVEL SECURITY` en las 31 tablas que contienen datos de negocio o particionables por tenant.
   - Definir el rol no privilegiado `nexus_app_role` (`NOSUPERUSER NOBYPASSRLS`) con sus permisos mínimos.
2. **Actualizar [`database.py`](../database.py):**
   - Implementar `set_tenant_context()` / `tenant_context_scope()` mediante `contextvars` para propagar de forma transparente el tenant autenticado de la petición HTTP a `get_db()`.
   - Robustecer `_configure_pg_context` para sanitizar parámetros y limpiar variables de sesión en transacciones reutilizadas del pool.
   - Añadir `verify_pg_security_posture(conn)` para detectar y rechazar roles con `SUPERUSER` o `BYPASSRLS`.
   - Adaptar `PgCursorWrapper` para soportar `SET LOCAL` con parámetros o `set_config` en PostgreSQL real.
3. **Crear Suite de Integración Real PostgreSQL:**
   - Crear `tests/test_postgres_rls_integration_task04b.py` con pruebas rigurosas contra PostgreSQL real (aislamiento cruzado, `FORCE RLS`, inyección/tampering de tenant, verificación de rol no-superuser, reutilización de pool sin fugas, y bypass administrativo explícito).
   - Diseñar la suite para detectar automáticamente la disponibilidad de una instancia PostgreSQL real (vía `TEST_DATABASE_URL`), reportando con precisión su ejecución o su indisponibilidad.
   - Crear la plantilla de entorno Docker [`docker-compose.postgres-test.yml`](../docker-compose.postgres-test.yml) para que cualquier entorno CI/CD o desarrollador pueda levantar la instancia de prueba con un solo comando.
4. **Regresión y verificación de datos:**
   - Ejecutar la regresión completa (`TASK-03A`, `TASK-03B`, `TASK-03B-C`, `TASK-08` y pruebas de persistencia).
   - Verificar la inalterabilidad de `leads.db` (hash MD5 y conteos).

