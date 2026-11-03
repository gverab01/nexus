# INFORME TÉCNICO: TASK-05A — SQLite to PostgreSQL Migration Readiness & Dry Run

**Proyecto:** NexusReach Pro  
**Ruta del Proyecto:** `C:\Users\gabri\OneDrive\Desktop\Proyectos\Linkedin\`  
**Dependencia:** TASK-04D — Super Admin Authorization Final Audit  
**Fecha:** 29 de Octubre de 2026  
**Estado:** **PASS** (100% de criterios técnicos y de seguridad satisfechos)  
**Entorno de Ejecución:** Windows 11 + Docker Desktop (PostgreSQL 16 en contenedor `nexusreach_postgres_rls_test`) + SQLite 3.x local.

---

## 1. Resumen Ejecutivo y Estado Final

En el marco de la evolución arquitectónica de NexusReach Pro hacia una infraestructura multi-tenant enterprise con Row-Level Security (RLS) en PostgreSQL, la tarea **TASK-05A** tuvo como objetivo ensayar, validar y auditar exhaustivamente la migración técnica de datos desde SQLite (`leads.db`) hacia PostgreSQL (`nexusreach_test`).

### Criterios Críticos de Ejecución Cumplidos
1. **Intactitud Absoluta de la Base Operativa (`leads.db`)**: No se ejecutaron modificaciones ni escrituras sobre `leads.db`. El hash MD5 y el tamaño en bytes se mantuvieron idénticos antes, durante y después del proceso:
   - MD5 Inicial y Final: `a610785d3a71994b742a608f9f94e2a6`
   - Tamaño: `1.126.400 bytes`
   - Estado de integridad SQLite: `ok`
   - Leads: `194` | Tenants: `40`
2. **Cero Migración de Producción**: El motor operativo del backend permanece configurado en SQLite para los flujos operativos estándar. La migración se ejecutó y ensayó exclusivamente contra una copia de trabajo certificada (`scratch/leads_migration_copy.db`) y hacia la base de datos PostgreSQL de prueba local (`nexusreach_test`).
3. **Paridad Total y Migración Idempotente**: Se auditaron las 36 tablas existentes en `leads.db`. Las 1.340 filas distribuidas en 20 tablas con datos fueron migradas con un 100% de correspondencia (1.340 filas en SQLite == 1.340 filas en PostgreSQL).
4. **Validación Profunda Celda por Celda (Fase 4)**: Se compararon 17.938 celdas individuales entre SQLite y PostgreSQL, logrando coincidencia canónica de hashes SHA-256 en el 100% de las tablas con datos.
5. **Aislamiento Multi-Tenant RLS Certificado (Fase 5)**: Se validó que el rol no privilegiado `nexus_app` quede estrictamente aislado por RLS sobre los datos consolidados migrados, impidiendo lecturas, mutaciones, inserciones cruzadas o bypass no autorizado.
6. **Regresión Global**: 88/88 pruebas aprobadas (100% PASS) en las suites combinadas de backend, RLS, dispatcher, runner y migración.

**Veredicto Final: PASS**

---

## 2. Inventario Exhaustivo de la Base SQLite Origen (`leads.db`)

Se realizó una auditoría forense completa sobre el archivo operativo `leads.db` utilizando conexiones en modo estrictamente de solo lectura (`file:leads.db?mode=ro`).

### Métricas de Integridad de Origen
- **Ruta:** `c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/leads.db`
- **MD5 Checksum:** `a610785d3a71994b742a608f9f94e2a6`
- **Tamaño:** `1.126.400 bytes`
- **PRAGMA integrity_check:** `ok`
- **PRAGMA foreign_key_check:** `0 violaciones`
- **Total Tablas:** 36 tablas de negocio

### Distribución de Filas por Tabla (1.340 filas totales)

| # | Tabla | Filas Origen (SQLite) | Clave Primaria | Presencia Multi-Tenant |
|---|---|---|---|---|
| 1 | `configuracion_seguridad` | 34 | `id` | Global / Clave-Valor |
| 2 | `selector_versions` | 1 | `version_id` | Global |
| 3 | `action_status` | 0 | `action_name` | Global |
| 4 | `payment_webhook_events` | 1 | `id` | Global / Auditoría Webhooks |
| 5 | `tenants` | 40 | `id` | Raíz jerárquica multi-tenant |
| 6 | `suscripciones` | 7 | `id` | `tenant_id` |
| 7 | `subscriptions` | 0 | `id` | `tenant_id` |
| 8 | `entitlements` | 4 | `id` | `tenant_id` |
| 9 | `credit_ledger` | 2 | `id` | `tenant_id` |
| 10 | `usage_counters` | 1 | `id` | `tenant_id` |
| 11 | `usage_events` | 2 | `id` | `tenant_id` |
| 12 | `suppression_list` | 1 | `id` | `tenant_id` |
| 13 | `system_logs` | 245 | `id` | `tenant_id` |
| 14 | `audit_logs` | 296 | `id` | `tenant_id` |
| 15 | `selector_failure_logs` | 3 | `id` | `tenant_id` |
| 16 | `usuarios` | 18 | `id` | `tenant_id` |
| 17 | `devices` | 0 | `device_id` | `tenant_id` |
| 18 | `whatsapp_accounts` | 0 | `id` | `tenant_id` |
| 19 | `linkedin_accounts` | 10 | `id` | `tenant_id` |
| 20 | `commands` | 0 | `command_id` | `tenant_id` |
| 21 | `command_results` | 0 | `result_id` | `tenant_id` |
| 22 | `listas_leads` | 31 | `id` | `tenant_id` |
| 23 | `leads` | 194 | `id` | `tenant_id` |
| 24 | `leads_en_lista` | 174 | `(lista_id, lead_id)` | Indirecto (`lista_id`, `lead_id`) |
| 25 | `secuencias` | 0 | `id` | `tenant_id` |
| 26 | `pasos_secuencia` | 0 | `id` | Indirecto (`secuencia_id`) |
| 27 | `secuencia_listas` | 0 | `(secuencia_id, lista_id)` | Indirecto |
| 28 | `leads_en_secuencia` | 0 | `(lead_id, secuencia_id)` | Indirecto |
| 29 | `mensajes_linkedin` | 0 | `id` | Indirecto (`lead_id`) |
| 30 | `correos_electronicos` | 0 | `id` | Indirecto (`lead_id`) |
| 31 | `mensajes_whatsapp` | 0 | `id` | Indirecto (`lead_id`) |
| 32 | `interacciones_sociales` | 0 | `id` | Indirecto (`lead_id`) |
| 33 | `historial_actividades` | 274 | `id` | Indirecto (`lead_id`) |
| 34 | `lead_activity` | 0 | `id` | `tenant_id` |
| 35 | `consent_records` | 0 | `id` | `tenant_id` |
| 36 | `email_candidates` | 2 | `id` | `tenant_id` |
| **TOTAL** | **36 tablas** | **1.340 filas** | — | — |

### Jerarquía y Autoconsistencia de `tenants`
- 30 tenants raíz (`parent_tenant_id IS NULL` o `parent_tenant_id = ''`).
- 10 sub-tenants de cartera (`parent_tenant_id` apuntando a agencias/padres válidos).
- 0 referencias rotas en la jerarquía de tenants.

---

## 3. Análisis de Paridad de Esquema SQLite vs PostgreSQL

Se realizó un cotejo estructural exhaustivo entre las definiciones DDL de SQLite y `schema_postgres.sql`.

### Hallazgos de Paridad
1. **Correspondencia de Tablas:** 36 de 36 tablas de negocio coinciden exactamente en nombre. PostgreSQL cuenta adicionalmente con la tabla de seguridad `system_admin_keys` (creada y blindada en TASK-04C/D para la autenticación criptográfica de superadministrador).
2. **Correspondencia de Columnas:** 100% de paridad en nombres de columnas y existencia de campos entre ambos motores.
3. **Mapeo de Tipos de Datos:**
   - **Identificadores y Textos:** `TEXT` en SQLite se mapea a `VARCHAR(64)` o `TEXT` en PostgreSQL.
   - **Fechas y Timestamps:** ISO-8601 en `TEXT` (SQLite) se mapea a `VARCHAR(64)` en PostgreSQL.
   - **Booleans:** `INTEGER` (0/1) en SQLite es compatible con `INTEGER` en PostgreSQL.
   - **Monetarios y Decimales:** `REAL` en SQLite se mapea a `NUMERIC(10,2)` o `NUMERIC(10,4)` en PostgreSQL. Psycopg deserializa estos valores como objetos `Decimal`, lo que fue contemplado y validado en la auditoría canónica.
   - **JSON:** Strings serializados en SQLite se mapean a `TEXT` en PostgreSQL con validación sintáctica JSON.

---

## 4. Estrategia y Orden Topológico de Migración

La migración hacia PostgreSQL requiere respetar estrictamente el árbol de dependencias de claves foráneas para evitar violaciones de integridad referencial durante la inserción.

### Orden Topológico Resuelto (36 tablas)
```
 1. configuracion_seguridad
 2. selector_versions
 3. action_status
 4. payment_webhook_events
 5. tenants (padres primero, luego hijos)
 6. suscripciones
 7. subscriptions
 8. entitlements
 9. credit_ledger
10. usage_counters
11. usage_events
12. suppression_list
13. system_logs
14. audit_logs
15. selector_failure_logs
16. usuarios
17. devices
18. whatsapp_accounts
19. linkedin_accounts
20. commands
21. command_results
22. listas_leads
23. leads
24. leads_en_lista
25. secuencias
26. pasos_secuencia
27. secuencia_listas
28. leads_en_secuencia
29. mensajes_linkedin
30. correos_electronicos
31. mensajes_whatsapp
32. interacciones_sociales
33. historial_actividades
34. lead_activity
35. consent_records
36. email_candidates
```

### Manejo de Casos Especiales de Integridad
1. **Auto-referencia en `tenants`:** Al migrar `tenants`, se implementó una cláusula explícita de ordenamiento:
   `ORDER BY CASE WHEN parent_tenant_id IS NULL OR parent_tenant_id = '' THEN 0 ELSE 1 END, created_at ASC`
   garantizando que todas las agencias/padres se inserten antes que sus sub-clientes dependientes.
2. **Audit Logs Históricos con Tenants Temporales:** En SQLite existían 60 filas en `audit_logs` generadas por pruebas unitarias previas con identificadores `ten_tst_b_...` inexistentes en `tenants`. Para preservar el 100% del audit trail sin pérdida de registros históricos ni alteración de hashes, el migrador opera como superadministrador configurando temporalmente `SET LOCAL session_replication_role = 'replica';` durante la transacción de carga por lotes, restaurándolo al finalizar a `origin`.

---

## 5. Resultados del Ensayo de Migración (Dry Run)

Se ejecutó la simulación transaccional con reversión automática mediante la herramienta [migrate_sqlite_to_postgres.py](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/migrate_sqlite_to_postgres.py):

```powershell
python scripts/migrate_sqlite_to_postgres.py `
    --source-db scratch/leads_migration_copy.db `
    --target-url "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test" `
    --dry-run
```

### Registro de Ejecución del Dry Run
```text
[INICIO] Proceso de migracion (Dry-run: True)
  Base de origen SQLite: C:\Users\gabri\OneDrive\Desktop\Proyectos\Linkedin\scratch\leads_migration_copy.db
  Base de destino PostgreSQL: 127.0.0.1:5432/nexusreach_test...
  Total de tablas a procesar: 36 (Filas origen: 1340)
  [OK] Tabla 'configuracion_seguridad': 34 filas preparadas/insertadas.
  [OK] Tabla 'selector_versions': 1 filas preparadas/insertadas.
  [OK] Tabla 'payment_webhook_events': 1 filas preparadas/insertadas.
  [OK] Tabla 'tenants': 40 filas preparadas/insertadas.
  [OK] Tabla 'suscripciones': 7 filas preparadas/insertadas.
  [OK] Tabla 'entitlements': 4 filas preparadas/insertadas.
  [OK] Tabla 'credit_ledger': 2 filas preparadas/insertadas.
  [OK] Tabla 'usage_counters': 1 filas preparadas/insertadas.
  [OK] Tabla 'usage_events': 2 filas preparadas/insertadas.
  [OK] Tabla 'suppression_list': 1 filas preparadas/insertadas.
  [OK] Tabla 'system_logs': 245 filas preparadas/insertadas.
  [OK] Tabla 'audit_logs': 296 filas preparadas/insertadas.
  [OK] Tabla 'selector_failure_logs': 3 filas preparadas/insertadas.
  [OK] Tabla 'usuarios': 18 filas preparadas/insertadas.
  [OK] Tabla 'linkedin_accounts': 10 filas preparadas/insertadas.
  [OK] Tabla 'listas_leads': 31 filas preparadas/insertadas.
  [OK] Tabla 'leads': 194 filas preparadas/insertadas.
  [OK] Tabla 'leads_en_lista': 174 filas preparadas/insertadas.
  [OK] Tabla 'historial_actividades': 274 filas preparadas/insertadas.
  [OK] Tabla 'email_candidates': 2 filas preparadas/insertadas.

[DRY RUN COMPLETO] 1340 filas simuladas. Todos los cambios fueron revertidos mediante rollback.
```

### Verificación de Reversibilidad Post-Dry Run
Se comprobó que ninguna fila de negocio quedó persistida en PostgreSQL tras el rollback del dry run:
- Tablas de negocio con filas: `0`
- Tablas del sistema (`system_admin_keys`): `1 fila (preservada)`

---

## 6. Resultados de la Migración en Base de Prueba

Posteriormente se ejecutó la migración real sobre la base de pruebas local:

```powershell
python scripts/migrate_sqlite_to_postgres.py `
    --source-db scratch/leads_migration_copy.db `
    --target-url "postgresql://nexus_admin:admin_secure_pass_123@127.0.0.1:5432/nexusreach_test" `
    --migrate
```

### Cotejo Exhaustivo de Conteos
```text
Tabla                        | SQLite     | PostgreSQL | Estado    
-----------------------------------------------------------------
configuracion_seguridad      | 34         | 34         | COINCIDE  
selector_versions            | 1          | 1          | COINCIDE  
action_status                | 0          | 0          | COINCIDE  
payment_webhook_events       | 1          | 1          | COINCIDE  
tenants                      | 40         | 40         | COINCIDE  
suscripciones                | 7          | 7          | COINCIDE  
subscriptions                | 0          | 0          | COINCIDE  
entitlements                 | 4          | 4          | COINCIDE  
credit_ledger                | 2          | 2          | COINCIDE  
usage_counters               | 1          | 1          | COINCIDE  
usage_events                 | 2          | 2          | COINCIDE  
suppression_list             | 1          | 1          | COINCIDE  
system_logs                  | 245        | 245        | COINCIDE  
audit_logs                   | 296        | 296        | COINCIDE  
selector_failure_logs        | 3          | 3          | COINCIDE  
usuarios                     | 18         | 18         | COINCIDE  
devices                      | 0          | 0          | COINCIDE  
whatsapp_accounts            | 0          | 0          | COINCIDE  
linkedin_accounts            | 10         | 10         | COINCIDE  
commands                     | 0          | 0          | COINCIDE  
command_results              | 0          | 0          | COINCIDE  
listas_leads                 | 31         | 31         | COINCIDE  
leads                        | 194        | 194        | COINCIDE  
leads_en_lista               | 174        | 174        | COINCIDE  
secuencias                   | 0          | 0          | COINCIDE  
pasos_secuencia              | 0          | 0          | COINCIDE  
secuencia_listas             | 0          | 0          | COINCIDE  
leads_en_secuencia           | 0          | 0          | COINCIDE  
mensajes_linkedin            | 0          | 0          | COINCIDE  
correos_electronicos         | 0          | 0          | COINCIDE  
mensajes_whatsapp            | 0          | 0          | COINCIDE  
interacciones_sociales       | 0          | 0          | COINCIDE  
historial_actividades        | 274        | 274        | COINCIDE  
lead_activity                | 0          | 0          | COINCIDE  
consent_records              | 0          | 0          | COINCIDE  
email_candidates             | 2          | 2          | COINCIDE  
-----------------------------------------------------------------
TOTAL                        | 1340       | 1340       | COINCIDE
```

---

## 7. Auditoría de Integridad Celda por Celda y Hashing Canónico (Fase 4)

A través del script de auditoría profunda `scratch/validate_migration_integrity.py`, se extrajeron ordenadamente por clave primaria todos los registros de cada motor, normalizando tipos flotantes/decimales y serializaciones JSON equivalentes.

### Resumen de la Auditoría Profunda
- **Total Celdas Auditadas:** 17.938 celdas individuales
- **Diferencias encontradas:** 0
- **Hash Canónico SHA-256:** Coincidencia idéntica en el 100% de las tablas con datos.

```text
Tabla                      | Filas   | Celdas   | Hash SHA256  | Estado    
---------------------------------------------------------------------------
configuracion_seguridad    | 34      | 136      | COINCIDE     | MATCH_100%
selector_versions          | 1       | 6        | COINCIDE     | MATCH_100%
action_status              | 0       | 0        | COINCIDE     | EMPTY_OK  
payment_webhook_events     | 1       | 6        | COINCIDE     | MATCH_100%
tenants                    | 40      | 600      | COINCIDE     | MATCH_100%
suscripciones              | 7       | 70       | COINCIDE     | MATCH_100%
subscriptions              | 0       | 0        | COINCIDE     | EMPTY_OK  
entitlements               | 4       | 44       | COINCIDE     | MATCH_100%
credit_ledger              | 2       | 16       | COINCIDE     | MATCH_100%
usage_counters             | 1       | 11       | COINCIDE     | MATCH_100%
usage_events               | 2       | 18       | COINCIDE     | MATCH_100%
suppression_list           | 1       | 6        | COINCIDE     | MATCH_100%
system_logs                | 245     | 2205     | COINCIDE     | MATCH_100%
audit_logs                 | 296     | 2072     | COINCIDE     | MATCH_100%
selector_failure_logs      | 3       | 18       | COINCIDE     | MATCH_100%
usuarios                   | 18      | 270      | COINCIDE     | MATCH_100%
devices                    | 0       | 0        | COINCIDE     | EMPTY_OK  
whatsapp_accounts          | 0       | 0        | COINCIDE     | EMPTY_OK  
linkedin_accounts          | 10      | 150      | COINCIDE     | MATCH_100%
commands                   | 0       | 0        | COINCIDE     | EMPTY_OK  
command_results            | 0       | 0        | COINCIDE     | EMPTY_OK  
listas_leads               | 31      | 248      | COINCIDE     | MATCH_100%
leads                      | 194     | 9700     | COINCIDE     | MATCH_100%
leads_en_lista             | 174     | 696      | COINCIDE     | MATCH_100%
secuencias                 | 0       | 0        | COINCIDE     | EMPTY_OK  
pasos_secuencia            | 0       | 0        | COINCIDE     | EMPTY_OK  
secuencia_listas           | 0       | 0        | COINCIDE     | EMPTY_OK  
leads_en_secuencia         | 0       | 0        | COINCIDE     | EMPTY_OK  
mensajes_linkedin          | 0       | 0        | COINCIDE     | EMPTY_OK  
correos_electronicos       | 0       | 0        | COINCIDE     | EMPTY_OK  
mensajes_whatsapp          | 0       | 0        | COINCIDE     | EMPTY_OK  
interacciones_sociales     | 0       | 0        | COINCIDE     | EMPTY_OK  
historial_actividades      | 274     | 1644     | COINCIDE     | MATCH_100%
lead_activity              | 0       | 0        | COINCIDE     | EMPTY_OK  
consent_records            | 0       | 0        | COINCIDE     | EMPTY_OK  
email_candidates           | 2       | 22       | COINCIDE     | MATCH_100%
---------------------------------------------------------------------------
RESULTADO FASE 4: PASS (100% Coincidencia)
```

---

## 8. Validación Funcional y de Aislamiento Multi-Tenant RLS (Fase 5)

Se desarrolló y ejecutó la suite automatizada [tests/test_migration_functional_task05a.py](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_migration_functional_task05a.py), validando el comportamiento de las políticas RLS sobre los datos reales migrados.

### Resultados de la Suite Funcional (8/8 PASS)
1. `test_01_migrated_leads_rls_isolation`: Conexión como rol restringido `nexus_app`. Con `app.current_tenant_id = 'ten_d933e9ca99'`, se aíslan exactamente sus 175 leads migrados. Con `ten_wa_daily_limit`, se aíslan exactamente sus 15 leads. Con contexto vacío o no autenticado, retorna `0` filas (fail-closed).
2. `test_02_migrated_usuarios_rls_isolation`: `ten_techcorp` visualiza exclusivamente sus 4 usuarios migrados. `ten_sanagustin` visualiza su único usuario. `ten_wa_daily_limit` (sin usuarios asignados) visualiza `0` usuarios.
3. `test_03_cross_tenant_update_blocked_by_rls`: Un tenant intentando actualizar prospectos de otro tenant ve 0 filas afectadas (`rowcount = 0`), sin mutación de datos.
4. `test_04_cross_tenant_delete_blocked_by_rls`: Un tenant intentando eliminar prospectos de otro tenant ve 0 filas afectadas (`rowcount = 0`).
5. `test_05_cross_tenant_insert_violates_with_check`: Un tenant intentando insertar un registro con `tenant_id` ajeno es bloqueado por la cláusula `WITH CHECK` de RLS levantando `InsufficientPrivilege`.
6. `test_06_superadmin_access_with_valid_token`: Una sesión con `app.is_super_admin = 'true'` y token criptográfico válido (`verify_super_admin_context()`) accede a la vista consolidada de los 194 leads, 40 tenants, 18 usuarios y 31 listas.
7. `test_07_unauthorized_superadmin_attempt_fails`: Sesión con bypass fraudulento (sin token o con token alterado) es bloqueada y confinada a `0` filas.
8. `test_08_backend_database_py_integration_with_migrated_data`: Se validó que el context manager central `database.get_db()` junto a `tenant_context_scope()` opere de forma nativa e idéntica contra PostgreSQL sobre los datos migrados.

---

## 9. Evidencia de Regresión Completa

Se ejecutaron todas las suites de regresión del proyecto:

| Suite de Pruebas | Entorno | Resultados | Estado |
|---|---|---|---|
| `test_migration_functional_task05a.py` | PostgreSQL RLS / App Role | 8/8 aprobadas | **PASS** |
| `test_superadmin_auth_hardening_task04d.py` | PostgreSQL RLS / Hardening | 9/9 aprobadas | **PASS** |
| `test_postgres_rls_integration_task04b.py` | PostgreSQL RLS / Integración Real | 20/20 aprobadas | **PASS** |
| `test_postgres_rls_security.py` | Contexto / Transacciones / Pool | 8/8 aprobadas | **PASS** |
| `test_database_isolation.py` | SQLite Redirección / Aislamiento | 4/4 aprobadas | **PASS** |
| `test_electron_runner_auth_task08.py` | Electron Runner Backend | 6/6 aprobadas | **PASS** |
| `test_worker_dispatcher_isolation_task03a.py` | Dispatcher & Worker Isolation | 10/10 aprobadas | **PASS** |
| `test_auth_tenant_isolation_task03b.py` | API Auth & Multi-Tenant RBAC | 16/16 aprobadas | **PASS** |
| `test_worker_runner_task08.cjs` | Runner Node.js Ed25519 | 7/7 aprobadas | **PASS** |
| **TOTAL CONSOLIDADO** | **Ecosistema Completo** | **88 / 88 pruebas** | **PASS** |

### Verificación Final de `leads.db`
```text
MD5: a610785d3a71994b742a608f9f94e2a6 (Coincide con referencia inicial)
Size: 1126400 bytes (Coincide con referencia inicial)
Integrity: ok
Leads: 194 | Tenants: 40
```

---

## 10. Plan de Corte Operativo para la Futura Migración de Producción (TASK-05B)

La viabilidad técnica de la migración queda 100% demostrada y certificada. Para la futura ejecución de corte definitivo en producción (**TASK-05B**), se define el siguiente protocolo:

### Protocolo de Transición (Cutover Runbook)
1. **Fase de Congelamiento Operativo (Maintenance Window):**
   - Detener el dispatcher y los runners activos (`worker_runner.cjs`).
   - Activar el kill-switch global en backend (`/api/kill-switch`).
   - Generar snapshot inmutable y copia de seguridad de `leads.db` con registro de hash SHA-256.
2. **Ejecución de la Migración en Producción:**
   - Ejecutar `python scripts/migrate_sqlite_to_postgres.py --source-db leads.db --target-url "$PROD_DATABASE_URL" --migrate`.
   - Ejecutar la verificación inmediata: `python scripts/migrate_sqlite_to_postgres.py --verify-only`.
3. **Conmutación de Variables de Entorno:**
   - Configurar en el entorno del backend FastAPI:
     ```env
     DATABASE_URL=postgresql://nexus_app:<secure_pass>@<pg_host>:5432/nexusreach_prod
     SUPERADMIN_RLS_SECRET=<production_crypto_secret>
     ```
   - Reiniciar el backend FastAPI y ejecutar health checks en `/health`.
4. **Plan de Contingencia y Rollback:**
   - Si la verificación de conteos o el health check falla:
     1. Revertir PostgreSQL mediante `python scripts/migrate_sqlite_to_postgres.py --rollback`.
     2. Remover `DATABASE_URL` del entorno para que `database.py` retorne automáticamente al motor SQLite local `leads.db`.
     3. Desactivar kill-switch y reanudar servicios en SQLite sin pérdida de datos ni corrupción.

---

## Conclusión

NexusReach Pro dispone ahora de un mecanismo de migración probado, idempotente y transaccional, con garantías matemáticas de integridad de datos y verificación exhaustiva de aislamiento multi-tenant RLS en PostgreSQL. La base SQLite original permanece intacta y operativa.

