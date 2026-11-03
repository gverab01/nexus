# INFORME DE CIERRE TÉCNICO — TASK-08: CORRECCIÓN DE IDENTIDAD, AUTENTICACIÓN Y TENANT DEL RUNNER ELECTRON

**Fecha:** 28 de octubre de 2026  
**Proyecto:** NexusReach Pro  
**Tarea:** `TASK-08` — Corrección de Identidad, Autenticación y Tenant del Runner Electron  
**Estado:** Completado y Verificado (`PASS`)

---

## 1. Hallazgos iniciales en `desktop/worker_runner.cjs` y `desktop/security/crypto_verifier.cjs`

Durante la inspección inicial del runner Electron y su integración con el backend de NexusReach Pro se confirmaron los siguientes hallazgos críticos:

1. **Tenant hardcodeado (`ten_superadmin`) en el registro del dispositivo:**
   - En [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs) (línea 82 original), `registerDeviceWithBackend()` enviaba un payload con `tenant_id: 'ten_superadmin'` fijo y sin encabezados de autenticación, intentando registrar el dispositivo bajo el tenant de superadministración independientemente de qué usuario operara el escritorio.
2. **Ausencia de credenciales de sesión en solicitudes del runner:**
   - Las llamadas a `POST /api/devices/register`, `GET /api/worker/proxima-tarea` y `POST /api/worker/reportar-resultado` en [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs) no adjuntaban `Authorization: Bearer <token>` ni `X-Session-Token`.
   - Tampoco existía resolución ni validación previa de la sesión activa (`GET /api/auth/sesion`) antes de iniciar el polling.
3. **Bucle infinito de reintentos ante errores `401` / `403`:**
   - `pollNextTask()` utilizaba `fetchJson()` ignorando el código de estado HTTP y programando incondicionalmente `setTimeout(() => this.pollNextTask(), 15000)` en el bloque `finally`, provocando reintentos infinitos cuando el backend rechazaba al worker por falta de sesión (`401`) o por dispositivo revocado / tenant cruzado (`403`).
4. **Verificación incompleta de identidad y `tenant_id` en comandos firmados:**
   - En [`desktop/security/crypto_verifier.cjs`](../desktop/security/crypto_verifier.cjs), `REQUIRED_FIELDS` no exigía `tenant_id` ni `device_id`, y `verifyCommand(command)` no contrastaba `command.tenant_id` frente al tenant autenticado del runner (`expectedTenantId`).
   - Además, el `setInterval` de purga de nonces en `crypto_verifier.cjs` carecía de `.unref()`, pudiendo retener el bucle de eventos de Node.js al finalizar pruebas automatizadas.
5. **Confirmación optimista no verificada al reportar resultados:**
   - En `reportTaskResult()` de [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs), el runner actualizaba `this.status.ultima_accion` como ejecutada sin comprobar si `POST /api/worker/reportar-resultado` había devuelto `200 OK` o había sido rechazado (`401`/`403`/`409`).

---

## 2. Flujo real de sesión, token, tenant y dispositivo encontrado en Electron

La inspección del flujo de extremo a extremo entre frontend, Electron y FastAPI determinó el siguiente contrato real:

1. **Inicio de sesión y almacenamiento en el renderer:**
   - El frontend ([`static/index.html`](../static/index.html)) autentica contra `POST /api/auth/login` o `POST /api/auth/bootstrap`, que crean una sesión en la tabla `user_sessions` ([`database.py`](../database.py)) y devuelven `session.token` (`session_token`) junto con los datos del usuario (`tenant_id`, `role`, etc.).
   - El renderer almacena el token en `localStorage.getItem('nexus_session_token')` y el tenant seleccionado en `localStorage.getItem('currentTenant')`.
   - El interceptor global de `window.fetch` en [`static/index.html`](../static/index.html) inyecta `Authorization: Bearer <token>` y `X-Session-Token: <token>` en todas las peticiones a `/api/*`.
2. **Validación de sesión en el backend (`main.py`):**
   - [`_extract_request_token(request)`](../main.py#L223-L234) extrae el token desde `Authorization: Bearer <token>`, `X-Session-Token` o cookie `session_token`.
   - [`_get_current_user(request)`](../main.py#L237-L249) valida dicho token contra `get_session_user(token)` y devuelve el contexto autenticado del usuario (`user_id`, `tenant_id`, `role`).
   - [`GET /api/auth/sesion`](../main.py#L1408-L1416) devuelve `{ "authenticated": True, "user": user }` para la sesión vigente.
3. **Arranque del runner (`browser_service.py` y `desktop/main.cjs`):**
   - El proceso principal Electron ([`desktop/main.cjs`](../desktop/main.cjs)) instancia `WorkerRunner` y expone un puente HTTP local en `127.0.0.1:8001` (`/internal/worker/start`, `/internal/worker/stop`, `/internal/worker/status`, `/internal/worker/force-next`, `/internal/worker/clear-session`).
   - También expone canales IPC en [`desktop/preload.cjs`](../desktop/preload.cjs) (`worker:start`, `worker:stop`, `worker:status`, `worker:force-next`).
   - Cuando el usuario inicia el worker desde la UI (`POST /api/worker/iniciar`), `main.py` invoca `browser_manager.start_worker(...)` en [`browser_service.py`](../browser_service.py), que delega en `POST http://127.0.0.1:8001/internal/worker/start`.

---

## 3. Archivos modificados

- [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs)
- [`desktop/security/crypto_verifier.cjs`](../desktop/security/crypto_verifier.cjs)
- [`desktop/main.cjs`](../desktop/main.cjs)
- [`browser_service.py`](../browser_service.py)
- [`main.py`](../main.py)
- [`desktop/tests/test_worker_runner_task08.cjs`](../desktop/tests/test_worker_runner_task08.cjs) *(nuevo)*
- [`tests/test_electron_runner_auth_task08.py`](../tests/test_electron_runner_auth_task08.py) *(nuevo)*

---

## 4. Detalle de los cambios realizados

### A. Eliminación del tenant hardcodeado y gestión de sesión en [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs)
- Se eliminó por completo el uso de `tenant_id: 'ten_superadmin'` o cualquier otro tenant fijo.
- Se incorporaron los métodos `setAuthContext({ sessionToken, tenantId })` y `clearSession(reason)` para gestionar e invalidar de forma explícita las credenciales en memoria (`this.sessionToken`, `this.authenticatedTenantId`, `this.authenticatedUser`, `this.deviceRegistered`).
- Se añadió `verifyAuthenticatedSession()`, que consulta `GET /api/auth/sesion` adjuntando `Authorization: Bearer <token>` y `X-Session-Token: <token>`, y establece `this.authenticatedTenantId` exclusivamente a partir de la respuesta verificada del backend (`res.body.user.tenant_id`, o un `requestedTenantId` validado contra el backend).
- Si no existe `sessionToken` o `GET /api/auth/sesion` falla, el runner entra en estado `AUTH_REQUIRED` (`ejecutando = false`, `auth_state = 'AUTH_REQUIRED'`) y no inicia el polling ni registra el dispositivo.

### B. Autenticación en todos los endpoints del runner y manejo de `401` / `403` / revocación
- `buildAuthHeaders()` construye los encabezados `Authorization: Bearer <token>` y `X-Session-Token: <token>` para todas las llamadas de `registerDeviceWithBackend()`, `pollNextTask()` y `reportTaskResult()`.
- `requestJson()` devuelve `{ statusCode, ok, body }` en lugar de descartar el código HTTP.
- Si `registerDeviceWithBackend()`, `pollNextTask()` o `reportTaskResult()` reciben HTTP `401` o `403`:
  - El runner invoca inmediatamente `handleUnauthorizedOrForbidden(statusCode, detail, source)`.
  - Si el motivo corresponde a dispositivo revocado (`revocado` / `revoked`), establece `auth_state = 'DEVICE_REVOKED'`; si es `401`, establece `auth_state = 'AUTH_REQUIRED'`; si es `403`, establece `auth_state = 'FORBIDDEN'`.
  - Se detiene `this.isRunning = false`, se cancela `this.pollTimeout` y **no se reprograma ningún `setTimeout`**, eliminando los bucles infinitos de reintentos.

### C. Sincronización de clave pública Ed25519 del servidor y verificación estricta del comando firmado
- Al registrar el dispositivo en `POST /api/devices/register`, si el backend devuelve `server_public_key_pem`, el runner la registra dinámicamente en el verificador mediante `this.verifier.addPinnedServerPublicKey(res.body.server_public_key_pem)`.
- En [`desktop/security/crypto_verifier.cjs`](../desktop/security/crypto_verifier.cjs):
  - `REQUIRED_FIELDS` ahora exige `['command_id', 'nonce', 'timestamp', 'expires_at', 'tenant_id', 'device_id', 'action', 'payload', 'signature']`.
  - `verifyCommand(command, expectedTenantId)` valida que `command.device_id === this.deviceId` y, cuando se proporciona `expectedTenantId`, que `command.tenant_id === expectedTenantId`, rechazando cualquier discrepancia antes o después de la verificación criptográfica Ed25519 y registrando el evento de seguridad.
  - Se añadió `.unref()` al temporizador de `setInterval` de limpieza de nonces para no bloquear el cierre limpio de procesos Node.js.
- En `pollNextTask()` de [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs), además de invocar `this.verifier.verifyCommand(signedCmd, this.authenticatedTenantId)`, se verifica explícitamente `signedCmd.tenant_id === this.authenticatedTenantId` y `signedCmd.device_id === this.verifier.deviceId`. Si la validación falla, la tarea **no se ejecuta** y se reporta el incidente de seguridad.

### D. Verificación del reporte de resultados (`reportTaskResult`)
- `reportTaskResult()` envía el payload firmado con Ed25519 del dispositivo (`device_id`, `tenant_id`, `command_id`, `task_id`, `timestamp`, `status`, `result_data`, `signature`) junto con los encabezados de sesión autenticada.
- Si el backend responde con `401` o `403`, detiene el runner y marca `ultima_accion.confirmado_servidor = false` con estado `RECHAZADO_SERVIDOR`.
- Solo cuando el servidor responde `200 OK` (`res.ok && res.body?.status === 'ok'`) el runner registra `confirmado_servidor = true`.

### E. Propagación segura de sesión entre FastAPI, `browser_service.py` y Electron (`desktop/main.cjs`)
- En [`main.py`](../main.py):
  - `POST /api/worker/iniciar` y `POST /api/worker/forzar-siguiente` extraen el token de sesión validado (`_extract_request_token(request)`) y el `target_tenant` autorizado (`_resolve_Requested_tenant(request, tenant_id)`), pasándolos a `browser_manager.start_worker(session_token=..., tenant_id=...)` y `browser_manager.force_next_task(session_token=..., tenant_id=...)`.
  - `POST /api/auth/logout` invoca `browser_manager.clear_worker_session(reason="Sesión cerrada desde el backend.")` para detener inmediatamente el runner y limpiar sus credenciales en memoria al cerrar sesión.
- En [`browser_service.py`](../browser_service.py):
  - `start_worker` y `force_next_task` transmiten `{ session_token, tenant_id }` por POST JSON a `http://127.0.0.1:8001/internal/worker/start` y `/internal/worker/force-next`.
  - Se añadió `clear_worker_session` hacia `POST http://127.0.0.1:8001/internal/worker/clear-session`.
- En [`desktop/main.cjs`](../desktop/main.cjs):
  - Se añadió `resolveRendererAuthContext()`, que si el arranque se invoca desde IPC sin argumentos explícitos lee de forma segura `nexus_session_token` y `currentTenant` desde el `localStorage` de `mainWindow.webContents` sin exponer claves privadas al renderer.
  - Se añadió el endpoint interno `/internal/worker/clear-session` y el canal IPC `worker:clear-session`.

---

## 5. Cómo resuelve y valida ahora el runner el token de sesión, el tenant y el `device_id`

1. **Token de sesión (`sessionToken`):** Se recibe desde el backend autenticado (`/internal/worker/start`) o se recupera del `localStorage` de la ventana autenticada de Electron en el proceso principal (`resolveRendererAuthContext()`).
2. **Validación del tenant (`authenticatedTenantId`):** Antes de registrar el dispositivo o hacer polling, `verifyAuthenticatedSession()` invoca `GET /api/auth/sesion` con el token. El `authenticatedTenantId` se toma del usuario autenticado devuelto por el backend (o de un `requestedTenantId` previamente autorizado por el backend). Nunca se usa un valor hardcodeado.
3. **Identidad de dispositivo (`device_id`):** El `CryptoCommandVerifier` carga o genera el par de claves Ed25519 del dispositivo en el llavero seguro local y calcula `device_id = dev_<sha256(publicKeyDer)[0:16]>`. A continuación, `registerDeviceWithBackend()` registra ese `device_id` y su clave pública bajo la sesión autenticada y el `authenticatedTenantId`.

---

## 6. Cómo se garantiza que un runner de Tenant A no pueda recibir, ejecutar ni reportar tareas de Tenant B

1. **En el registro (`POST /api/devices/register`):** El backend vincula el `device_id` al `tenant_id` autorizado de la sesión autenticada y rechaza (`403`) cualquier intento de registrar un dispositivo para un tenant no autorizado o de reasignar un dispositivo existente de otro tenant.
2. **En el despacho (`GET /api/worker/proxima-tarea`):**
   - El backend exige sesión válida (`401` si falta/expira), comprueba que el `device_id` pertenezca al tenant autorizado y esté activo (`403` si pertenece a otro tenant o está revocado), y selecciona únicamente tareas con `tenant_id == authorized_tenant`.
   - Además, el backend firma el comando Ed25519 incluyendo `tenant_id` y `device_id` dentro del payload canónico firmado.
3. **En el runner antes de ejecutar (`pollNextTask` + `verifyCommand`):**
   - El runner verifica criptográficamente la firma Ed25519 del servidor y comprueba que `signedCmd.tenant_id === this.authenticatedTenantId` y `signedCmd.device_id === this.verifier.deviceId`. Si un comando trajera otro `tenant_id`, otro `device_id` o una firma inválida, se aborta antes de tocar Playwright.
4. **En el reporte (`POST /api/worker/reportar-resultado`):**
   - El runner firma el reporte con su clave privada Ed25519 e incluye su token de sesión.
   - El backend verifica sesión, pertenencia del dispositivo al tenant, firma Ed25519 del resultado y que la tarea reportada esté en estado `EN_PROCESO` asignada exactamente a `(tenant_id, device_id, command_id)`. Un reporte cruzado entre tenants o dispositivos recibe `403` y no altera la base de datos.

---

## 7. Cómo responde el runner ante ausencia de sesión, `401`, `403`, dispositivo revocado y comando inválido

| Condición | Comportamiento del Runner (`desktop/worker_runner.cjs`) |
| :--- | :--- |
| **Ausencia de sesión (`sessionToken` vacío o inválido)** | `start()` aborta antes de iniciar el polling, fija `ejecutando = false`, `auth_state = 'AUTH_REQUIRED'` y devuelve `{ status: 'auth_required' }`. |
| **Respuesta HTTP `401` (sesión expirada/inválida)** | `handleUnauthorizedOrForbidden()` detiene `isRunning = false`, cancela `pollTimeout`, fija `auth_state = 'AUTH_REQUIRED'` y no programa nuevos reintentos. |
| **Respuesta HTTP `403` (tenant no autorizado / acceso denegado)** | `handleUnauthorizedOrForbidden()` detiene `isRunning = false`, cancela `pollTimeout`, fija `auth_state = 'FORBIDDEN'` y detiene el polling. |
| **Dispositivo revocado (`403` con detalle de revocación)** | `handleUnauthorizedOrForbidden()` detecta la revocación, detiene `isRunning = false`, fija `auth_state = 'DEVICE_REVOKED'` y bloquea futuras ejecuciones. |
| **Comando con firma inválida, `tenant_id` distinto o `device_id` distinto** | `verifyCommand()` rechaza el comando, registra el incidente en el log de seguridad (`SECURITY_COMMAND_REJECTED`), **no ejecuta** la acción en el navegador y reporta el rechazo al backend. |
| **Logout (`clearSession`)** | Limpia `sessionToken`, `authenticatedTenantId`, `authenticatedUser` y `deviceRegistered`, cancela `pollTimeout` y pasa a `auth_state = 'AUTH_REQUIRED'`. |

---

## 8. Pruebas creadas o actualizadas y qué valida cada una

### A. Suite unitaria/integración Node.js del runner Electron: [`desktop/tests/test_worker_runner_task08.cjs`](../desktop/tests/test_worker_runner_task08.cjs)
Valida con un servidor HTTP local aislado y llaves criptográficas temporales:
1. **Caso 1 — Sin sesión activa:** `runner.start()` sin token se detiene en `AUTH_REQUIRED` y realiza `0` llamadas a `/api/worker/proxima-tarea`.
2. **Caso 2 — Flujo autenticado válido:** Verifica sesión en `/api/auth/sesion`, registra el dispositivo en `/api/devices/register` con `tenant_id === 'ten_alpha'` (confirmando que `ten_superadmin` y `ten_default` nunca se envían), recibe comando firmado Ed25519 para `ten_alpha`, lo verifica, ejecuta la acción simulada y confirma el reporte en `/api/worker/reportar-resultado` (`confirmado_servidor === true`).
3. **Caso 3 — Rechazo de `tenant_id` cruzado en comando:** Comando firmado pero con `tenant_id = 'ten_beta'` mientras el runner está autenticado en `'ten_alpha'` es rechazado por `verifyCommand` y no ejecuta el navegador.
4. **Caso 4 — Rechazo de `device_id` distinto en comando:** Comando firmado para otro `device_id` es rechazado y no se ejecuta.
5. **Caso 5 — Rechazo de firma Ed25519 inválida:** Comando con payload adulterado es rechazado criptográficamente y no se ejecuta.
6. **Caso 6 — Detención ante `401` / `403` / dispositivo revocado:** Verifica que ante `401` (`AUTH_REQUIRED`) y ante `403` por revocación (`DEVICE_REVOKED`) el runner se detiene inmediatamente (`isRunning === false`, `pollTimeout === null`) sin entrar en bucle de reintentos, y que `clearSession()` limpia las credenciales en memoria.

### B. Suite de extremo a extremo Python + Node.js contra FastAPI real: [`tests/test_electron_runner_auth_task08.py`](../tests/test_electron_runner_auth_task08.py)
Ejecuta el código real de [`desktop/worker_runner.cjs`](../desktop/worker_runner.cjs) mediante Node.js contra los endpoints reales de FastAPI ([`main.py`](../main.py)) sobre una base SQLite temporal aislada:
1. `test_01_runner_without_session_does_not_poll`: El runner sin sesión no invoca `/api/worker/proxima-tarea`.
2. `test_02_authenticated_runner_registers_executes_and_reports_own_tenant_only`: El runner autenticado en `ten_alpha` registra su dispositivo, reclama únicamente la tarea de `ten_alpha` (dejando intacta la tarea `PENDIENTE` de `ten_beta`), verifica la firma del servidor, ejecuta y reporta el resultado firmado completando la tarea en la base de datos.
3. `test_03_runner_cannot_access_other_tenant_tasks`: El runner de `ten_alpha` recibe `null` cuando solo quedan tareas de `ten_beta`, y si intenta forzar `tenant_id = 'ten_beta'` recibe `403` y pasa a `FORBIDDEN` (`isRunning == False`).
4. `test_04_revoked_device_stops_runner_on_403`: Al revocar el dispositivo via `POST /api/devices/revoke`, el siguiente ciclo del runner recibe `403`, se detiene con `auth_state == 'DEVICE_REVOKED'` y no deja tareas huérfanas.
5. `test_05_expired_or_invalid_session_stops_runner_on_401`: Un token inválido recibe `401` y detiene el runner con `auth_state == 'AUTH_REQUIRED'`.
6. `test_06_tampered_result_signature_rejected_and_runner_marks_unconfirmed`: Si la firma del resultado reportado se corrompe, FastAPI rechaza con `403`, la tarea permanece `EN_PROCESO` en la BD y el runner registra `confirmado_servidor == False` (`RECHAZADO_SERVIDOR`).

---

## 9. Resultado de la ejecución de las pruebas

Todas las suites (Node.js y Python) finalizaron con código de salida `0`:

- **`node desktop/tests/test_worker_runner_task08.cjs`**: `ALL TASK-08 ELECTRON RUNNER TESTS PASSED` (6/6 escenarios verificados).
- **`node desktop/tests/test_security_subsystem.cjs`**: `ALL SECURITY SUBSYSTEM TESTS PASSED`.
- **`python -m unittest -v tests/test_electron_runner_auth_task08.py`**: `Ran 6 tests in 2.264s — OK`.
- **Suite completa de regresión Python (`tests/test_electron_runner_auth_task08.py`, `tests/test_worker_dispatcher_isolation_task03a.py`, `tests/test_auth_tenant_isolation_task03b.py`, `tests/test_rest_closure_task03bc.py`)**: `Ran 44 tests in 7.020s — OK`.

---

## 10. Confirmación explícita de que `leads.db` no fue modificada

Se verificó el archivo operativo `leads.db` antes y después de todas las modificaciones y ejecuciones de pruebas:

- **Tamaño:** `1,126,400` bytes (sin cambios)
- **Hash MD5:** `a610785d3a71994b742a608f9f94e2a6` (idéntico al estado inicial)
- **Conteos operativos:** `leads = 194`, `tenants = 40` (sin cambios)
- **`PRAGMA integrity_check`:** `ok`

