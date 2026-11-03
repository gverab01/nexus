# NEXUSREACH PRO — INFORME DE ENTREGA TASK-03B-C
## Cierre de Brechas REST de Autenticación, Autorización y Aislamiento Multi-Tenant

**Fecha de emisión:** 28 de octubre de 2026  
**Tarea:** `TASK-03B-C`  
**Alcance ejecutado:** Exclusivamente endpoints REST en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) y suite de pruebas automatizadas en [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py).  

---

## 1. Resumen Técnico de los Cambios Realizados

1. **Corrección del error SQL en `PATCH /api/usuarios/{user_id}/puesto` ([`toggle_seat`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L648-L672))**:
   - Se corrigió la consulta `SELECT tenant_id FROM users WHERE id = ?` (que provocaba `sqlite3.OperationalError: no such table: users`) reemplazándola por `SELECT tenant_id FROM usuarios WHERE id = ?`.
   - Se mantuvo la exigencia de rol administrativo (`_ADMIN_ROLES = {"SUPER_ADMIN", "AGENCY_ADMIN", "COMPANY_ADMIN"}`) y la validación de pertenencia del usuario objetivo al tenant/subtenant autorizado del solicitante mediante [`_resolve_permitted_tenants`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L264-L333).

2. **Blindaje de `POST /api/extraccion/buscar` ([`extract_leads_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1622-L1651)) y `POST /api/extraccion/red-linkedin` ([`extract_network_leads_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1653-L1672))**:
   - Se eliminó por completo el fallback inseguro `target_tenant = "ten_superadmin"` y la asignación libre de `tenant_id` para `AGENCY_ADMIN`.
   - Ambos endpoints ahora resuelven `tenants = _resolve_permitted_tenants(caller, tenant_id)` (`HTTP 401` sin sesión válida; `HTTP 403` si `AGENCY_ADMIN` solicita un tenant ajeno a su agencia o cartera de subtenants).
   - En `POST /api/extraccion/buscar`, cuando se suministra `lista_id`, se verifica previamente su existencia y pertenencia al mismo `target_tenant` mediante [`_authorize_list_access`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L449-L470) (`HTTP 404` / `HTTP 403`).

3. **Blindaje de `POST /api/leads/sincronizar-conexiones` ([`sync_connections_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1066-L1082)) y `POST /api/secuencias/barrer-esperas` ([`sweep_expired_delays_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1868-L1880))**:
   - Se exige autenticación válida (`HTTP 401`) y resolución estricta de `target_tenant = _resolve_permitted_tenants(caller, tenant_id)[0]` (`HTTP 403` ante `tenant_id` ajeno), propagando siempre el `tenant_id` autorizado al motor subyacente.

4. **Protección de Recursos por ID, Relaciones Indirectas y Operaciones por Lote**:
   - Se implementaron los guardias reutilizables en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L363-L470):
     - [`_authorize_lead_access(caller, lead_id)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L363-L384)
     - [`_authorize_leads_batch_access(caller, lead_ids, expected_tenant=None)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L387-L422): valida de forma atómica y previa a cualquier mutación que ningún ID del lote pertenezca a otro tenant (`HTTP 403`) ni sea inexistente (`HTTP 404`).
     - [`_authorize_sequence_access(caller, secuencia_id)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L425-L446)
     - [`_authorize_list_access(caller, lista_id)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L449-L470)
   - **Corrección de colisión de rutas en FastAPI**: se reubicó `POST /api/prospectos/lote/resolver-correo` y `POST /api/leads/lote/resolver-correo` ([`batch_resolve_leads_email_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1107-L1122)) antes de `POST /api/prospectos/{lead_id}/resolver-correo` ([`resolve_lead_email_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1124-L1142)), evitando que el segmento literal `lote` fuera capturado como `lead_id="lote"`.
   - **Eliminación de filtrado global accidental en `POST /api/secuencias/{secuencia_id}/asignar-leads`** ([`assign_leads_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1786-L1805)): cuando `lead_ids` se envía vacío, la consulta cambió de `SELECT id FROM leads WHERE estado = 'EXTRAIDO'` (global) a `SELECT id FROM leads WHERE estado = 'EXTRAIDO' AND tenant_id = ?` acotado estrictamente al `tenant_id` de la secuencia. Cuando `lead_ids` se informa, se valida con `_authorize_leads_batch_access(caller, lead_ids, expected_tenant=sec_tenant)`.
   - **Relaciones cruzadas lista ↔ secuencia y lista ↔ leads**:
     - En `POST /api/listas/{lista_id}/conectar-secuencia` y `desconectar-secuencia`, se valida tanto la lista como la secuencia y se exige `lst["tenant_id"] == sec["tenant_id"]` (`HTTP 403` si difieren, incluso para `SUPER_ADMIN`).
     - En `POST /api/listas/{lista_id}/leads` y `DELETE /api/listas/{lista_id}/leads/{lead_id}`, se exige que todos los leads pertenezcan al mismo `tenant_id` de la lista.
     - En `POST /api/prospectos/importar-lote`, se valida cada lista en `lista_id`/`list_ids` con `_authorize_list_access` verificando que pertenezca a `target_tenant`.

5. **Operaciones Globales y Separación de Roles Administrativos (`COMPANY_MEMBER` vs. `COMPANY_ADMIN` / `AGENCY_ADMIN` / `SUPER_ADMIN`)**:
   - Se incorporaron [`_require_tenant_admin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L338-L348) y [`_require_super_admin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L351-L360).
   - `GET /api/logs` ([`get_logs_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2047-L2096)) y `GET /api/logs/stats` ([`get_log_stats_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2098-L2134)) exigen rol administrativo (`COMPANY_MEMBER` recibe `HTTP 403`) y acotan las consultas sobre `system_logs` mediante `WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN (...))` para administradores de tenant/agencia.
   - `DELETE /api/logs` ([`clear_logs_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2136-L2145)) y `POST /api/selectors/canary-run` ([`run_canary_audit_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2666-L2678)) quedaron restringidos exclusivamente a `SUPER_ADMIN`.
   - `POST /api/seguridad/kill-switch/activar`, `POST /api/seguridad/kill-switch/desactivar`, `POST /api/seguridad/configuracion`, `POST /api/linkedin/invitaciones-vencidas/retirar` (además acotado por `tenant_id` en SQL), `POST /api/tenants/{tenant_id}/puestos`, `POST /api/tenants/{tenant_id}/zoho-config`, `POST /api/tenants/{tenant_id}/purge-inactive-leads`, `POST /api/devices/revoke` y `POST /api/accounts/{account_id}/reactivate` exigen [`_require_tenant_admin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L338-L348), rechazando a `COMPANY_MEMBER` con `HTTP 403`.

---

## 2. Tabla de Endpoints Modificados

| Endpoint | Método | Regla de Autenticación | Regla de Autorización y Aislamiento de Tenant |
| :--- | :--- | :--- | :--- |
| `/api/tenants/{tenant_id}/puestos` | `POST` | Token válido (`401`) | `_require_tenant_admin` (`COMPANY_ADMIN` propio o `SUPER_ADMIN`; `COMPANY_MEMBER` -> `403`) |
| `/api/agencia/{agencia_id}/clientes` | `GET`, `POST` | Token válido (`401`) | Rol `AGENCY_ADMIN` de la agencia propietaria o `SUPER_ADMIN` (`COMPANY_MEMBER`/`COMPANY_ADMIN` -> `403`) |
| `/api/agencia/{agencia_id}/finanzas` | `GET` | Token válido (`401`) | Rol `AGENCY_ADMIN` de la agencia propietaria o `SUPER_ADMIN` (`403`) |
| `/api/tenants/{tenant_id}/miembros` | `GET` | Token válido (`401`) | `_resolve_permitted_tenants(caller, tenant_id)` (impide a `COMPANY_MEMBER` de agencia ver subtenants) |
| `/api/usuarios/{user_id}/puesto` | `PATCH` | Token válido (`401`) | Rol en `_ADMIN_ROLES` (`403`), consulta corregida en tabla `usuarios` (`404` si no existe) y `_resolve_permitted_tenants(caller, target_user["tenant_id"])` (`403`) |
| `/api/leads/{lead_id}/reunion` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` si no existe, `403` si es de otro tenant) |
| `/api/prospectos/{lead_id}` | `GET`, `DELETE` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/{lead_id}/seguir` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/{lead_id}/retirar-invitacion` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/{lead_id}/sincronizar-linkedin` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/{lead_id}/contacto` | `PUT` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/{lead_id}/resolver-correo` y `/api/leads/{lead_id}/resolver-correo` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/prospectos/lote/resolver-correo` y `/api/leads/lote/resolver-correo` | `POST` | Token válido (`401`) | `_authorize_leads_batch_access(caller, lead_ids)` (`403` si incluye lead ajeno, `404` si alguno no existe) |
| `/api/enrichment/test-diagnostico` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants(caller, None)` |
| `/api/prospectos/importar-lote` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants` + validación de cada `lista_id`/`list_ids` con `_authorize_list_access` en el mismo `target_tenant` (`403`/`404`) |
| `/api/prospectos/eliminar-lote` | `POST` | Token válido (`401`) | `_authorize_leads_batch_access(caller, lead_ids)` atómico antes de borrar (`403`/`404`) |
| `/api/prospectos/{lead_id}/abrir-en-browseros` | `POST` | Token válido (`401`) | `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/leads/sincronizar-conexiones` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants(caller, tenant_id)` (`403` cross-tenant) |
| `/api/seguridad/kill-switch/activar` y `desactivar` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, None)` (`COMPANY_MEMBER` -> `403`) |
| `/api/seguridad/configuracion` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, None)` (`COMPANY_MEMBER` -> `403`) |
| `/api/linkedin/invitaciones-vencidas/retirar` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, tenant_id)` (`403`) + filtrado `WHERE tenant_id IN (...)` |
| `/api/extraccion/buscar` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants(caller, tenant_id)` (sin fallback a `ten_superadmin`, restringe `AGENCY_ADMIN`) + `_authorize_list_access` en `lista_id` |
| `/api/extraccion/red-linkedin` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants(caller, tenant_id)` (sin fallback a `ten_superadmin`, restringe `AGENCY_ADMIN`) |
| `/api/secuencias/{secuencia_id}` | `GET`, `PUT`, `DELETE` | Token válido (`401`) | `_authorize_sequence_access(caller, secuencia_id)` (`404` / `403`) |
| `/api/secuencias/{secuencia_id}/pasos` y `/pasos/agregar` | `POST` | Token válido (`401`) | `_authorize_sequence_access(caller, secuencia_id)` (`404` / `403`) |
| `/api/secuencias/{secuencia_id}/pasos/{paso_id}` | `DELETE` | Token válido (`401`) | `_authorize_sequence_access(caller, secuencia_id)` (`404` / `403`) |
| `/api/secuencias/{secuencia_id}/asignar-leads` | `POST` | Token válido (`401`) | `_authorize_sequence_access` + `_authorize_leads_batch_access(..., expected_tenant=sec_tenant)` o `WHERE estado = 'EXTRAIDO' AND tenant_id = ?` cuando `lead_ids` es vacío |
| `/api/secuencias/{secuencia_id}/leads` | `GET` | Token válido (`401`) | `_authorize_sequence_access(caller, secuencia_id)` (`404` / `403`) |
| `/api/secuencias/ejecutar-siguiente` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants` + `_authorize_sequence_access` (o selección acotada a `s.tenant_id IN (...)` si `secuencia_id` es `None`) |
| `/api/secuencias/{secuencia_id}/estado` | `POST` | Token válido (`401`) | `_authorize_sequence_access(caller, secuencia_id)` (`404` / `403`) |
| `/api/secuencias/barrer-esperas` | `POST` | Token válido (`401`) | `_resolve_permitted_tenants(caller, tenant_id)` (`403` cross-tenant) |
| `/api/dashboard/metricas` | `GET` | Token válido (`401`) | `_resolve_permitted_tenants` + validación de pertenencia de `secuencia_id` y `lista_id` si se informan (`403`/`404`) |
| `/api/listas/{lista_id}` | `GET`, `PUT`, `DELETE` | Token válido (`401`) | `_authorize_list_access(caller, lista_id)` (`404` / `403`) |
| `/api/listas/{lista_id}/leads` | `POST` | Token válido (`401`) | `_authorize_list_access` + `_authorize_leads_batch_access(..., expected_tenant=lst["tenant_id"])` |
| `/api/listas/{lista_id}/leads/{lead_id}` | `DELETE` | Token válido (`401`) | `_authorize_list_access` + `_authorize_lead_access` en el mismo tenant (`403`) |
| `/api/listas/{lista_id}/conectar-secuencia` y `desconectar-secuencia` | `POST` | Token válido (`401`) | `_authorize_list_access` + `_authorize_sequence_access` exigiendo `lst["tenant_id"] == sec["tenant_id"]` (`403`) |
| `/api/listas/{lista_id}/iniciar-extraccion` y `detener-extraccion` | `POST` | Token válido (`401`) | `_authorize_list_access(caller, lista_id)` (`404` / `403`) |
| `/api/logs` y `/api/logs/stats` | `GET` | Token válido (`401`) | `_require_tenant_admin(caller, tenant_id)` (`COMPANY_MEMBER` -> `403`) + aislamiento por `lead_id IN (SELECT id FROM leads WHERE tenant_id IN (...))` |
| `/api/logs` | `DELETE` | Token válido (`401`) | `_require_super_admin(caller)` (solo `SUPER_ADMIN`; otros roles -> `403`) |
| `/api/devices/revoke` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, req.tenant_id)` (`COMPANY_MEMBER` -> `403`) |
| `/api/tenants/{tenant_id}/zoho-config` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, tenant_id)` (`COMPANY_MEMBER` -> `403`) |
| `/api/leads/{lead_id}/activities` | `GET` | Token válido (`401`) | `_resolve_permitted_tenants` + `_authorize_lead_access(caller, lead_id)` (`404` / `403`) |
| `/api/tenants/{tenant_id}/purge-inactive-leads` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, tenant_id)` (`COMPANY_MEMBER` -> `403`) |
| `/api/accounts/{account_id}/reactivate` | `POST` | Token válido (`401`) | `_require_tenant_admin(caller, tenant_id)` (`COMPANY_MEMBER` -> `403`) |
| `/api/selectors/canary-run` | `POST` | Token válido (`401`) | `_require_super_admin(caller)` (solo `SUPER_ADMIN`; otros roles -> `403`) |

---

## 3. Archivos Modificados

- [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py)
- [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py)

---

## 4. Pruebas Añadidas y Ejecutadas con su Resultado

Comando ejecutado sobre base temporal SQLite aislada (`SQLITE_DB_PATH`):

```powershell
.\venv\Scripts\python.exe -m unittest tests/test_auth_tenant_isolation_task03b.py tests/test_database_isolation.py tests/test_postgres_rls_security.py -v
```

**Resultado: 28 tests ejecutados en 2.716s — `OK` (100% PASS)**:

- `TestAuthAndTenantIsolationTask03B` ([`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py)):
  - `test_scenario_a_unauthenticated_request_rejected_with_401` (`OK` — 93 combinaciones método/ruta privadas verificadas sin token -> `401`)
  - `test_scenario_b_invalid_or_expired_token_rejected_with_401` (`OK`)
  - `test_scenario_c_authenticated_user_accesses_own_tenant` (`OK`)
  - `test_scenario_d_user_a_cannot_read_tenant_b_data` (`OK`)
  - `test_scenario_e_user_a_cannot_export_tenant_b_data` (`OK`)
  - `test_scenario_f_tampered_tenant_id_fails_closed` (`OK`)
  - `test_scenario_g_administrative_privileges_enforced_strictly` (`OK`)
  - `test_scenario_h_no_indirect_leakage_in_metrics_lists_sequences` (`OK`)
  - `test_scenario_i_resolve_permitted_tenants_unit_fail_closed` (`OK`)
  - `test_task03bc_1_toggle_seat_sql_fix_and_rbac` (`OK` — prueba éxito de `COMPANY_ADMIN`, `403` de `COMPANY_MEMBER`, `403` cross-tenant, `404` inexistente y no mutación de `puesto_activo`)
  - `test_task03bc_2_extraction_endpoints_auth_and_tenant_resolution` (`OK` — prueba ausencia de fallback a `ten_superadmin`, restricción de `AGENCY_ADMIN` a subtenants, y validación de `lista_id`)
  - `test_task03bc_3_sync_connections_and_sweep_delays` (`OK` — prueba `401`, `403` cross-tenant y propagación de `tenant_id` autorizado)
  - `test_task03bc_4a_prospects_by_id_and_batch_isolation_and_no_db_mutation` (`OK` — prueba todos los endpoints `/api/prospectos/{lead_id}*`, lotes mixtos `403`, IDs inexistentes `404` y verificación SQL directa de que `lead_beta_1` y `lead_alpha_1` no sufren cambios)
  - `test_task03bc_4b_sequences_by_id_indirect_relations_and_no_global_leakage` (`OK` — prueba `/api/secuencias/{secuencia_id}*`, lotes mixtos en `asignar-leads` y ausencia de filtrado global accidental cuando `lead_ids=[]`)
  - `test_task03bc_4c_lists_by_id_and_cross_tenant_sequence_linking` (`OK` — prueba `/api/listas/{lista_id}*`, lotes mixtos y bloqueo de conexión entre lista y secuencia de distintos tenants)
  - `test_task03bc_5_global_and_administrative_endpoints_rbac` (`OK` — prueba rechazo `403` a `COMPANY_MEMBER` en 13 rutas administrativas/globales, aislamiento de `/api/logs` y `/api/logs/stats` por tenant, aislamiento de retiro de invitaciones vencidas, y exclusividad `SUPER_ADMIN` en `DELETE /api/logs` y `POST /api/selectors/canary-run`)
- `TestDatabaseIsolation` ([`tests/test_database_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_database_isolation.py)): 4 tests (`OK`).
- `TestPostgresRlsSecurity` ([`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py)): 8 tests (`OK`).

---

## 5. Riesgos Residuales Fuera del Alcance de Esta Tarea

- **`TASK-03A` (Autenticación y vinculación dispositivo-tenant del runner en `/api/worker/proxima-tarea`, `/api/worker/reportar-resultado` y `task_dispatcher.py`)**: `GET /api/worker/proxima-tarea` y `POST /api/worker/reportar-resultado` permanecen sin modificar en esta entrega conforme a la restricción de alcance.
- **`TASK-04B` (Alineación de DDL PostgreSQL y pruebas de integración reales con RLS bajo rol no-`SUPERUSER`)**: pendiente de ejecución en su propia tarea dedicada.
- **Controladores locales del navegador de escritorio (`/api/browser/*`, `/api/zoho/login`, `/api/zoho/logout`, `/api/worker/estado`, `/api/worker/forzar-siguiente`, `/api/worker/piloto-automatico/toggle`, `/api/worker/heartbeat`)**: corresponden al contrato local con el proceso Electron (`TASK-03A` / `TASK-08`).
- **Aislamiento de configuración antiban en `configuracion_seguridad`**: la tabla `configuracion_seguridad` es clave-valor global en el esquema actual; su modificación quedó restringida a roles administrativos (`_ADMIN_ROLES`).

---

## 6. Confirmación de Integridad de `leads.db`

Se comprobó antes y después de la ejecución de las pruebas que la base de datos operativa [`leads.db`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/leads.db) no fue modificada ni tocada:

- **Tamaño**: `1,126,400` bytes (idéntico al estado inicial)
- **Hash MD5**: `a610785d3a71994b742a608f9f94e2a6` (idéntico al estado inicial)
- **Conteo de registros**: `194` leads, `40` tenants
- **`PRAGMA integrity_check`**: `ok`

---

## 7. Confirmación de Respeto de Alcance (`TASK-03A` y `TASK-04B`)

Se confirma expresamente que **no se implementaron `TASK-03A`, `TASK-04B`, `TASK-08` ni modificaciones en Electron, `task_dispatcher.py`, `database.py` o `schema_postgres.sql`** en esta entrega.

