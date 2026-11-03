# INFORME TÉCNICO DE CIERRE — TASK-03A: AUDITORÍA Y CORRECCIÓN DEL AISLAMIENTO MULTI-TENANT DEL DISPATCHER Y RUNNER

**Fecha:** 28 de octubre de 2026  
**Proyecto:** NexusReach Pro  
**Tarea:** `TASK-03A` — Auditoría y corrección del aislamiento multi-tenant del dispatcher y runner  
**Estado:** COMPLETADA  

---

## 1. Estado inicial y archivos inspeccionados

Antes de realizar modificaciones se registró la huella de integridad de la base de datos operativa [`leads.db`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/leads.db):
- **Estado inicial**: `size=1126400 bytes`, `MD5=a610785d3a71994b742a608f9f94e2a6`, `leads=194`, `tenants=40`, `PRAGMA integrity_check=ok`.

**Archivos inspeccionados:**
- [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) — Motor central de selección, despacho, reserva y consolidación de reportes del worker.
- [`command_signing_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py) — Emparejamiento de dispositivos (`devices`), emisión de comandos firmados Ed25519 (`commands`) y verificación/registro de resultados (`command_results`).
- [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) (líneas `2155–2380`) — Endpoints de contrato del worker y dispositivos (`/api/devices/register`, `/api/devices/revoke`, `/api/devices/list`, `/api/worker/proxima-tarea`, `/api/worker/reportar-resultado`).
- [`desktop/worker_runner.cjs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs) y [`desktop/security/crypto_verifier.cjs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/security/crypto_verifier.cjs) — Cliente runner de escritorio Electron y verificador/firmante Ed25519 local.
- [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py) — Esquema de tablas `devices`, `commands`, `command_results`, `leads_en_secuencia`, `secuencias`, `pasos_secuencia`, `leads`, `linkedin_accounts`.
- [`tests/test_signed_commands.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_signed_commands.py), [`tests/test_hybrid_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_hybrid_dispatcher.py), [`tests/test_entitlements_and_billing.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_entitlements_and_billing.py) y [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py).

---

## 2. Flujo de autenticación, selección, asignación y reporte de resultados

1. **Emparejamiento de dispositivo (`POST /api/devices/register`)**:
   - El usuario autenticado registra un `device_id` junto con su clave pública Ed25519 (`public_key_ed25519`) vinculada a su `tenant_id` autorizado en la tabla `devices`.
2. **Solicitud de tarea (`GET /api/worker/proxima-tarea`)**:
   - El endpoint autentica al caller (`_get_current_user`) y valida sus permisos de tenant (`_resolve_permitted_tenants`), comprobando también la pertenencia de `secuencia_id` (si se especifica) y que el `device_id` esté activo y registrado bajo el `resolved_tenant`.
3. **Selección y reserva atómica ([`task_dispatcher.get_next_dispatched_task`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L36-L557))**:
   - Exige un `target_tenant` explícito; verifica que el dispositivo esté `ACTIVE` en `target_tenant`, que la secuencia (si se indica) pertenezca a `target_tenant` y que la suscripción del tenant esté activa.
   - Consulta candidatos en `leads_en_secuencia` filtrando simultáneamente `s.tenant_id = ?` y `l.tenant_id = ?`.
   - Reserva atómicamente la inscripción seleccionada (`UPDATE leads_en_secuencia SET paso_actual_id = ?, proxima_ejecucion_at = ? WHERE id = ? AND estado = 'EN_CURSO' AND (proxima_ejecucion_at IS NULL OR proxima_ejecucion_at <= ?)` con `cursor.rowcount == 1`, lease de 120s) antes de emitir el comando firmado Ed25519 en `commands` con `(lead_id, secuencia_id, paso_id)` ligados en `params_json`.
4. **Reporte de resultado (`POST /api/worker/reportar-resultado` -> [`task_dispatcher.process_executed_task_report`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L559-L868))**:
   - Verifica sesión/tenant (si se envían cabeceras de sesión) y exige `(command_id/tarea_id, device_id, device_signature)`.
   - Antes de cualquier mutación, comprueba en base de datos que `commands.id` exista (`404`), que `cmd_tenant` coincida con el tenant autenticado y reportado (`403`), que `cmd_device == device_id` (`403`), que `cmd_status in ('DISPATCHED', 'ISSUED')` (`409`), que `(lead_id, secuencia_id, paso_id)` coincidan con los parámetros firmados en el comando (`403`), que el lead y la secuencia pertenezcan a `cmd_tenant` (`403`/`404`) y que la inscripción en `leads_en_secuencia` esté en estado `EN_CURSO` (`409`).
   - Invoca [`command_signing_service.record_command_result`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L353-L503), que valida la firma Ed25519 del dispositivo sobre el payload canónico `(command_id, device_id, success, result, error)` y hace transición atómica `WHERE id = ? AND status IN ('DISPATCHED', 'ISSUED')` a `EXECUTED` o `FAILED`. Si falla la firma o el estado, aborta con `403`/`409` sin tocar `leads`, `leads_en_secuencia`, `historial_actividades` ni `linkedin_accounts`.

---

## 3. Vulnerabilidades encontradas (con referencias a archivos y líneas previas)

1. **Despacho sin autenticación ni validación de tenant/dispositivo (`main.py:2294-2311`)**:
   - `GET /api/worker/proxima-tarea` hacía `resolved_tenant = caller.get("tenant_id") if caller else tenant_id`. Permitía llamadas anónimas pasando cualquier `tenant_id`, no invocaba `_resolve_permitted_tenants()`, no validaba que `secuencia_id` perteneciera al tenant del caller y no comprobaba la vinculación de `device_id`.
2. **Inferencia del tenant desde el último `LOGIN_EXITOSO` global y fallback cross-tenant (`task_dispatcher.py:97-105, 126-131, 161-190`)**:
   - Cuando `tenant_id` era `None`, `get_next_dispatched_task` consultaba `SELECT tenant_id FROM audit_logs WHERE accion = 'LOGIN_EXITOSO' ORDER BY timestamp DESC LIMIT 1`, suplantando al último usuario que inició sesión en toda la plataforma.
   - Si no había candidatos para el tenant inferido, ejecutaba una consulta global (`lines 162-189`) sobre todas las secuencias de todos los tenants (`WHERE s.activa = 1 AND s.estado = 'PUBLICADA' ...`).
   - Además, usaba `if sequence_id: ... elif target_tenant: ...` (`lines 126-131`), omitiendo el filtro `s.tenant_id = ?` cuando se pasaba `sequence_id`.
3. **Fallbacks inseguros a `ten_superadmin` y auto-registro de dispositivo ficticio (`task_dispatcher.py:223, 450, 471-481, 500, 507-509, 554, 572`)**:
   - Si el tenant no tenía dispositivo activo, auto-registraba `"dev_default_local"` con una clave dummy bajo `target_tenant or "ten_superadmin"` y, si fallaba la firma del comando, despachaba un `task_id = f"task-{candidate['lead_id']}-..."` sin firma (`signed_command = None`).
4. **Ausencia de reserva atómica (condición de carrera entre workers) (`task_dispatcher.py:134-159, 497-533`)**:
   - Seleccionar una tarea en `get_next_dispatched_task` no actualizaba `proxima_ejecucion_at` en `leads_en_secuencia`. Dos workers concurrentes del mismo tenant recibían exactamente la misma tarea.
5. **Reporte de resultados sin autenticación y que ignoraba fallos de firma Ed25519 (`main.py:2313-2316`, `task_dispatcher.py:535-708`, `command_signing_service.py:348-420`)**:
   - `POST /api/worker/reportar-resultado` no exigía autenticación ni traducía errores a códigos HTTP.
   - En `process_executed_task_report` (`lines 549-565`), si `device_id` no se enviaba se saltaba `record_command_result`, y si `record_command_result` devolvía `{"ok": False, "error": "Firma del dispositivo inválida..."}`, solo imprimía un warning en consola y **ejecutaba igualmente todas las mutaciones en `leads`, `leads_en_secuencia`, `historial_actividades`, `lead_activity` y `linkedin_accounts`**.
   - Tampoco verificaba que el comando perteneciera al tenant, dispositivo, `lead_id`, `secuencia_id` y `paso_id` reportados, ni prevenía ataques de replay (`status` ya procesado).
6. **Secuestro cross-tenant de `device_id` en registro de dispositivos (`command_signing_service.py:214-231`)**:
   - `register_device` hacía `UPDATE devices SET public_key_ed25519 = ? ... WHERE id = ?` sin comprobar que `existing["tenant_id"] == tenant_id`, permitiendo que otro tenant sobrescribiera la clave pública de un `device_id` ajeno.

---

## 4. Correcciones realizadas y justificación

1. **[`command_signing_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py)**:
   - En [`register_device`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L212-L242): se valida `existing_tenant != tenant_id`, lanzando `PermissionError` (`HTTP 403` en `main.py`) y acotando el `UPDATE` con `WHERE id = ? AND tenant_id = ?`.
   - En [`record_command_result`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L353-L503): se exige `command_id`, `device_id`, `tenant_id` y `device_signature`; se comprueba que el dispositivo exista y esté `ACTIVE` en `tenant_id`; se comprueba que el comando exista (`404`), pertenezca a `tenant_id` (`403`) y a `device_id` (`403`), y esté en `('DISPATCHED', 'ISSUED')` (`409`); se verifica la firma Ed25519 antes de actualizar `commands` con Compare-And-Swap (`WHERE id = ? AND status IN ('DISPATCHED', 'ISSUED')`).
2. **[`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py)**:
   - En [`get_autopilot_status`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L16-L30): se acota por `tenant_id` cuando se proporciona.
   - En [`get_next_dispatched_task`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L36-L557):
     - Se exige `tenant_id` explícito (`TENANT_REQUIRED`); se eliminaron por completo la lectura de `audit_logs` (`LOGIN_EXITOSO`), el fallback global sin tenant, todos los fallbacks a `ten_superadmin` y el auto-registro de `dev_default_local`.
     - Se valida la pertenencia de `sequence_id` al `target_tenant` (`FORBIDDEN_SEQUENCE_TENANT`) y la suscripción activa del tenant.
     - Se filtra la consulta de candidatos exigiendo simultáneamente `s.tenant_id = ?` y `l.tenant_id = ?`.
     - Se añadió reserva atómica en `leads_en_secuencia` (lease de 120s verificado con `cursor.rowcount == 1`) y vinculación explícita de `lead_id`, `secuencia_id` y `paso_id` dentro de `cmd_params` del comando firmado.
     - Se corrigieron también dos bugs preexistentes en el camino de despacho de LinkedIn: las columnas del `INSERT OR IGNORE INTO linkedin_accounts` (`account_name` según esquema real en `database.py`) y la llamada a `safety_engine.calculate_per_account_delay(account_id=...)`.
   - En [`process_executed_task_report`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L559-L868):
     - Se valida la existencia del comando (`404`), coincidencia de tenant (`authenticated_tenant_id`, `permitted_tenants` y `reported_tenant` -> `403`), coincidencia de `device_id` (`403`), estado no procesado (`409`), coincidencia de `(lead_id, secuencia_id, paso_id)` con `commands.params_json` (`403`), pertenencia de `lead` y `secuencia` a `cmd_tenant` (`403`/`404`), e inscripción en `leads_en_secuencia` con `estado == 'EN_CURSO'` (`409`).
     - Si `command_signing_service.record_command_result` falla (`not reg_res.get("ok")`), retorna inmediatamente el error con su `http_status` (`401`/`403`/`404`/`409`) sin ejecutar ninguna mutación en la base de datos.
3. **[`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py)**:
   - En [`register_device_endpoint`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2232-L2257): se captura `PermissionError` devolviendo `HTTP 403`.
   - En [`get_worker_next_task`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2296-L2330) (`GET /api/worker/proxima-tarea`): se exige sesión válida y tenant autorizado mediante `_resolve_permitted_tenants(caller, tenant_id)`, se valida `secuencia_id` con `_authorize_sequence_access(caller, secuencia_id)` y se comprueba que `target_device` esté activo en `resolved_tenant` (`HTTP 403` en caso contrario).
   - En [`report_task_result`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2332-L2372) (`POST /api/worker/reportar-resultado`): se valida sesión y `permitted_tenants` cuando se envían cabeceras de autenticación (`401`/`403`), se exige firma criptográfica del dispositivo (`401` si falta) y se propagan los códigos `HTTPException` (`400`/`401`/`403`/`404`/`409`) devueltos por `process_executed_task_report`.

---

## 5. Archivos modificados

| Archivo | Tipo de cambio | Resumen |
| :--- | :--- | :--- |
| [`command_signing_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py) | Modificado | Protección contra secuestro cross-tenant en `register_device` y validación estricta de tenant, dispositivo, estado anti-replay y firma Ed25519 en `record_command_result`. |
| [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) | Modificado | Eliminación de inferencia por `audit_logs`, fallback global y `ten_superadmin`/`dev_default_local`; reserva atómica de tareas; bloqueo de mutaciones ante fallos de autorización o firma en `process_executed_task_report`. |
| [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) | Modificado | Controles de autenticación, autorización multi-tenant y validación de dispositivo en `/api/devices/register`, `/api/worker/proxima-tarea` y `/api/worker/reportar-resultado`. |
| [`tests/test_worker_dispatcher_isolation_task03a.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_worker_dispatcher_isolation_task03a.py) | Nuevo | Suite automatizada con 10 pruebas de aislamiento multi-tenant, firmas Ed25519 reales, anti-replay, concurrencia y cero mutaciones no autorizadas sobre SQLite temporal aislada. |

---

## 6. Pruebas ejecutadas, comando exacto y resultado real

### 6.1. Suite específica `TASK-03A` + suites de aislamiento y seguridad (`TASK-03B`, `TASK-03B-C`, `TASK-01`, `TASK-04A`)
- **Comando ejecutado**:
  ```powershell
  .\venv\Scripts\python.exe -m unittest tests/test_worker_dispatcher_isolation_task03a.py tests/test_auth_tenant_isolation_task03b.py tests/test_database_isolation.py tests/test_postgres_rls_security.py -v
  ```
- **Resultado real**: **38 tests ejecutados — 38 OK (`0 failures, 0 errors`) en `4.210s`**:
  - `test_01_worker_unauthenticated_and_expired_credentials_rejected` ... `ok`
  - `test_02_worker_obtains_only_own_tenant_task_and_never_other_tenant` ... `ok`
  - `test_03_agency_admin_subtenant_allowed_and_foreign_tenant_rejected` ... `ok`
  - `test_04_unauthorized_revoked_or_cross_tenant_device_rejected` ... `ok`
  - `test_05_report_result_cross_tenant_or_wrong_device_or_tampered_resources_rejected_without_mutation` ... `ok`
  - `test_06_invalid_signature_or_tampered_payload_rejected_without_mutation` ... `ok`
  - `test_07_valid_execution_and_replay_duplicate_report_rejected` ... `ok`
  - `test_08_nonexistent_command_and_incompatible_enrollment_state_rejected` ... `ok`
  - `test_09_concurrent_workers_cannot_claim_same_task_twice` ... `ok`
  - `test_10_valid_failure_report_schedules_retry_and_final_step_completes_enrollment` ... `ok`
  - 16/16 pruebas de `tests/test_auth_tenant_isolation_task03b.py` ... `ok`
  - 4/4 pruebas de `tests/test_database_isolation.py` ... `ok`
  - 8/8 pruebas de `tests/test_postgres_rls_security.py` ... `ok`

### 6.2. Suite de comandos firmados Ed25519 (`tests/test_signed_commands.py`) y bloqueo de despacho por suscripción inactiva (`tests/test_entitlements_and_billing.py`)
- **Comando ejecutado** (redirigiendo `SQLITE_DB_PATH` a archivo temporal aislado):
  ```powershell
  .\venv\Scripts\python.exe -c "import os, sys, tempfile, unittest; tmp = tempfile.NamedTemporaryFile(prefix='nexus_legacy_tests_', suffix='.db', delete=False); tmp.close(); os.environ['SQLITE_DB_PATH'] = tmp.name; import database; database.init_db(); suite = unittest.TestLoader().loadTestsFromName('tests.test_signed_commands'); res = unittest.TextTestRunner(verbosity=2).run(suite); os.remove(tmp.name); sys.exit(0 if res.wasSuccessful() else 1)"
  ```
- **Resultado real**:
  - `tests/test_signed_commands.py`: **7/7 OK (`0 failures, 0 errors`)**.
  - `test_05_inactive_subscription_blocks_task_dispatch` en `tests/test_entitlements_and_billing.py`: **OK** (verifica que `get_next_dispatched_task` bloquea con `TENANT_SUBSCRIPTION_INACTIVE`).

---

## 7. Pruebas omitidas, simuladas o pendientes, con sus motivos

- **No se simularon (mockearon) firmas criptográficas ni controles de autorización**: todas las pruebas en [`tests/test_worker_dispatcher_isolation_task03a.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_worker_dispatcher_isolation_task03a.py) utilizan pares de claves `Ed25519PrivateKey` reales generados con `cryptography`.
- **Único ajuste de entorno en la prueba**: `safety_engine.check_business_hours` se fijó a `(True, "OK Test Hours")` en `setUpClass` y se restauró en `tearDownClass` únicamente para permitir que las pruebas de despacho se ejecuten de forma determinista fuera del horario comercial local (20:35 h).
- **Pendientes fuera del alcance de `TASK-03A`**:
  - `TASK-08`: actualización del cliente Electron [`desktop/worker_runner.cjs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs) para dejar de usar `this.tenantId = 'ten_default'` hardcodeado en la línea 82 y enviar el token de sesión autenticado del worker en `GET /api/worker/proxima-tarea`.
  - `TASK-04B`: pruebas de integración contra una instancia PostgreSQL real con políticas RLS activas y rol no-superuser.

---

## 8. Evidencia de aislamiento multi-tenant y ausencia de mutaciones no autorizadas

1. **Sin inferencia desde `audit_logs` ni fallback global (`test_01`, `test_02`)**:
   - Con `ten_b` registrado como último `LOGIN_EXITOSO` en `audit_logs` y con tareas listas en `ten_b`, cuando la cola de `ten_a` queda vacía, `GET /api/worker/proxima-tarea` autenticado como `ten_a` retorna `hay_tarea: False` y jamás entrega tareas de `ten_b`.
2. **Aislamiento de parámetros manipulados (`test_02`, `test_03`, `test_04`)**:
   - Solicitar `?tenant_id=ten_b`, `?secuencia_id=seq_b` o `?device_id=dev_b` desde `ten_a` devuelve `HTTP 403`.
   - Intentar re-registrar `dev_a` desde `ten_b` en `POST /api/devices/register` devuelve `HTTP 403` y conserva intactos `tenant_id='ten_a'` y `public_key_ed25519` en la tabla `devices`.
3. **Cero mutaciones ante reportes no autorizados, firmas inválidas o replays (`test_05`, `test_06`, `test_07`, `test_08`)**:
   - Tras intentar reportar un comando de `ten_a` con credenciales/dispositivo de `ten_b`, con otro dispositivo del mismo tenant (`dev_a2`), cambiando `lead_id` a `lead_b1`, alterando `exito` después de firmar o reenviando un comando ya ejecutado, se comprobó en base de datos:
     - `leads.estado` permanece sin cambios (`NUEVO`);
     - `leads_en_secuencia.estado` y `paso_actual_id` permanecen sin cambios;
     - `commands.status` permanece `DISPATCHED` (en rechazos `403`/`404`) y no duplica filas en `command_results` (en replay `409`).

---

## 9. Evidencia de integridad de `leads.db`

Comprobación ejecutada antes y después de todas las pruebas:

| Momento | Tamaño (bytes) | Hash MD5 | Filas en `leads` | Filas en `tenants` | `PRAGMA integrity_check` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Antes de TASK-03A** | `1126400` | `a610785d3a71994b742a608f9f94e2a6` | `194` | `40` | `ok` |
| **Después de TASK-03A** | `1126400` | `a610785d3a71994b742a608f9f94e2a6` | `194` | `40` | `ok` |

`git status --short leads.db` no reporta cambios.

---

## 10. Diff revisado y posibles regresiones

- Se revisaron los cambios en [`command_signing_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py), [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) y [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py).
- **Compatibilidad de contratos**:
  - Se mantuvo el orden de verificación de `entitlements_service.is_tenant_subscription_active` en `get_next_dispatched_task` para que las suscripciones expiradas sigan devolviendo `codigo: "TENANT_SUBSCRIPTION_INACTIVE"` de forma determinista.
  - Se mantuvo la estructura de respuesta de `GET /api/worker/proxima-tarea` (`hay_tarea`, `comando`, `tarea`) y de `POST /api/worker/reportar-resultado` (`status: "ok" | "error"`, `tarea_id`, `mensaje`, `siguiente_paso_id`).
  - **Cambio de seguridad intencional documentado**: `GET /api/worker/proxima-tarea` ahora exige sesión autenticada (`HTTP 401` si no se envía token válido) y `POST /api/worker/reportar-resultado` exige firma Ed25519 válida del dispositivo asignado al comando (`HTTP 401`/`403`/`404`/`409`).

---

## 11. Riesgos residuales

1. **`TASK-08` (Runner Electron local)**: [`desktop/worker_runner.cjs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs#L82) tiene aún `this.tenantId = 'ten_default'` y realiza polling a `/api/worker/proxima-tarea` sin adjuntar el header `Authorization` / `X-Session-Token` del usuario autenticado en Electron. Con el backend ya blindado por `TASK-03A`, el runner local recibirá `HTTP 401` hasta que se implemente `TASK-08` para inyectar el token e identidad de tenant reales en el cliente Electron.
2. **Expiración de lease sin reporte**: Si un worker reclama una tarea (lease de 120s en `proxima_ejecucion_at`) y se desconecta abruptamente sin reportar resultado, la inscripción vuelve a ser elegible tras 120s y emitirá un nuevo `command_id` (el `command_id` anterior expira por su propio TTL de 120s).

---

## 12. Decisión de cierre

**COMPLETADA** — El aislamiento multi-tenant del dispatcher y runner en el backend (`main.py`, `task_dispatcher.py` y `command_signing_service.py`) ha sido auditado, corregido y verificado con pruebas automatizadas sobre SQLite temporal aislada, sin tocar `leads.db`.

