# NEXUSREACH PRO — REVISIÓN POST TASK-03B Y CONCILIACIÓN DEL BACKLOG

**Fecha:** 28 de Octubre de 2026  
**Modo de Ejecución:** Inspección estática de solo lectura y verificación sin mutación de código ni de datos operativos (`leads.db` intacta: `1,126,400` bytes, MD5 `a610785d3a71994b742a608f9f94e2a6`).

---

## A. Hallazgos Confirmados mediante Inspección del Código

### A.1 Validación de la Entrega `TASK-03B` en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) y [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py)

1. **Blindaje efectivo de [`_resolve_permitted_tenants()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L265-L327)**:
   - **Confirmado en código:** La función exige `caller` tipo `dict`, con `id` y `rol` no vacíos (`HTTP 401` si faltan), valida `rol` contra la lista cerrada [`_ALLOWED_ROLES`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L255-L263) (`{"SUPER_ADMIN", "AGENCY_ADMIN", "COMPANY_ADMIN", "COMPANY_MEMBER", "INDIVIDUAL", "FREELANCER"}`) devolviendo `HTTP 403` ante cualquier rol desconocido, y eliminó los fallbacks permisivos `"ten_superadmin"` y `"ten_unauthorized"`.
   - **`SUPER_ADMIN` ([`main.py:297-305`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L297-L305)):** Si recibe `tenant_query`, devuelve `[clean_query]`; si no recibe `tenant_query`, devuelve `[caller_tenant]` si existe o lanza `HTTP 403` si el usuario no tiene tenant asignado.
   - **`AGENCY_ADMIN` ([`main.py:312-322`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L312-L322)):** Consulta en base de datos [`auth_service.list_agency_subtenants(caller_tenant)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/auth_service.py#L463-L497) (`WHERE parent_tenant_id = ? AND estado != 'ELIMINADO'`) y solo autoriza `clean_query` si coincide con `caller_tenant` o con un subtenant hijo legítimo; de lo contrario, lanza `HTTP 403`.
   - **Roles operativos (`COMPANY_ADMIN`, `COMPANY_MEMBER`, `INDIVIDUAL`, `FREELANCER` en [`main.py:324-330`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L324-L330)):** Quedan confinados estrictamente a `[caller_tenant]`, rechazando con `HTTP 403` cualquier `tenant_query` distinto.

2. **Defecto de ejecución oculto en [`PATCH /api/usuarios/{user_id}/puesto`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L524-L547) detectado al auditar la prueba frente al código**:
   - **Evidencia en [`main.py:539`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L539):**
     ```python
     cursor.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
     ```
   - **Diagnóstico:** La tabla real en SQLite y PostgreSQL se llama **`usuarios`** ([`database.py:216`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py#L216), [`schema_postgres.sql:47`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L47)), no `users`.
   - **Por qué la prueba dio PASS en `TASK-03B`:** En [`tests/test_auth_tenant_isolation_task03b.py:383`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py#L383), `PATCH /api/usuarios/usr_alpha_m/puesto` solo se probó en el **Escenario A (sin token)**, el cual retorna `401` en la línea 534 antes de ejecutar el `SELECT`. Cuando un administrador autenticado invoca este endpoint, falla con `sqlite3.OperationalError: no such table: users`.

3. **Endpoints privados en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) que AÚN aceptan `tenant_id` o IDs de recursos sin autorización efectiva**:
   - **A.3.1 Endpoints con parámetro `tenant_id` que conservan el patrón vulnerable o carecen de autenticación:**
     - [`POST /api/extraccion/buscar`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1281-L1305) y [`POST /api/extraccion/red-linkedin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1307-L1330): Ambos conservan el bloque legacy:
       ```python
       target_tenant = "ten_superadmin"
       if caller:
           target_tenant = caller.get("tenant_id") or "ten_superadmin"
           if caller.get("rol") in ("SUPER_ADMIN", "AGENCY_ADMIN") and tenant_id:
               target_tenant = tenant_id
       ```
       Permiten llamadas sin token (escribiendo en `"ten_superadmin"`) y permiten que un `AGENCY_ADMIN` envíe cualquier `tenant_id` ajeno sin verificar `list_agency_subtenants()`.
     - [`POST /api/leads/sincronizar-conexiones`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L917-L926): Acepta `tenant_id: Optional[str] = None` sin exigir autenticación.
     - [`POST /api/secuencias/barrer-esperas`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1444-L1448): Acepta `tenant_id: Optional[str] = Query(None)` sin exigir autenticación.
     - [`GET /api/worker/proxima-tarea`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1741) y [`POST /api/worker/reportar-resultado`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1743-L1746): Pendientes por diseño para `TASK-03A`.
   - **A.3.2 Endpoints de lectura/escritura por ID de recurso (`IDOR` / sin autenticación en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py)):**
     - **Prospectos por `lead_id`:** [`POST /api/leads/{lead_id}/reunion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L549-L561), [`GET /api/prospectos/{lead_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L786-L818), [`POST /api/prospectos/{lead_id}/seguir`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L820-L838), [`POST /api/prospectos/{lead_id}/retirar-invitacion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L840-L857), [`POST /api/prospectos/{lead_id}/sincronizar-linkedin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L859-L915), [`PUT /api/prospectos/{lead_id}/contacto`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L928-L945), [`POST /api/prospectos/{lead_id}/resolver-correo`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L947-L963), [`POST /api/prospectos/lote/resolver-correo`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L965-L976), [`DELETE /api/prospectos/{lead_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1042-L1046) y [`POST /api/prospectos/eliminar-lote`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1048-L1055) no llaman a `_get_current_user()` ni verifican que el `lead_id` pertenezca al tenant del usuario.
     - **Secuencias por `secuencia_id`:** [`GET /api/secuencias/{secuencia_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1346-L1352), [`PUT /api/secuencias/{secuencia_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1372-L1383), [`DELETE /api/secuencias/{secuencia_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1385-L1389), [`POST /api/secuencias/{secuencia_id}/pasos`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1391-L1396), [`POST /api/secuencias/{secuencia_id}/pasos/agregar`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1398-L1404), [`DELETE /api/secuencias/{secuencia_id}/pasos/{paso_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1406-L1412), [`POST /api/secuencias/{secuencia_id}/asignar-leads`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1414-L1424) (nota: si `lead_ids` viene vacío en la línea 1421, ejecuta `SELECT id FROM leads WHERE estado = 'EXTRAIDO'` sin filtrar por `tenant_id`), [`GET /api/secuencias/{secuencia_id}/leads`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1426-L1430), [`POST /api/secuencias/ejecutar-siguiente`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1432-L1435) y [`POST /api/secuencias/{secuencia_id}/estado`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1437-L1442) carecen de autenticación y validación de pertenencia de la secuencia al tenant.
     - **Listas por `lista_id`:** [`GET /api/listas/{lista_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1486-L1492), [`PUT /api/listas/{lista_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1519-L1531), [`DELETE /api/listas/{lista_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1533-L1537), [`POST /api/listas/{lista_id}/leads`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1539-L1543), [`DELETE /api/listas/{lista_id}/leads/{lead_id}`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1545-L1549), [`POST /api/listas/{lista_id}/conectar-secuencia`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1551-L1557), [`POST /api/listas/{lista_id}/desconectar-secuencia`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1559-L1566) y [`POST /api/listas/{lista_id}/iniciar|detener-extraccion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1568-L1578) carecen de autenticación y verificación de tenant.
     - **Endpoints operativos globales sin autenticación:** [`GET /api/logs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1583-L1594), [`GET /api/logs/stats`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1596-L1600), [`POST /api/seguridad/kill-switch/activar|desactivar`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1199-L1209), [`POST /api/seguridad/configuracion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1211-L1224) y [`POST /api/selectors/canary-run`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2096-L2106) (este último recibe headers de autorización en la firma pero no invoca `_get_current_user`).
   - **A.3.3 Granularidad de rol dentro del mismo tenant (`COMPANY_MEMBER` vs `COMPANY_ADMIN`):**
     - Endpoints destructivos o administrativos de tenant que usan únicamente `_resolve_permitted_tenants()` (como [`POST /api/tenants/{tenant_id}/purge-inactive-leads`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1916-L1933), [`DELETE /api/tenants/{tenant_id}/leads/{lead_id}/data-subject-deletion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1895-L1914), [`POST /api/devices/revoke`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1688-L1698) y [`POST /api/billing/checkout/*`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2152-L2209)) impiden el acceso cross-tenant, pero permiten que un `COMPANY_MEMBER` ejecute la operación dentro de su propio tenant.

---

### A.2 Estado Real de `TASK-03A` ([`GET /api/worker/proxima-tarea`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1741) y [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py))

La inspección de [`main.py:1724-1746`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1746), [`task_dispatcher.py:32-710`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L32-L710), [`command_signing_service.py:175-267`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L175-L267) y [`desktop/worker_runner.cjs:77-190`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs#L77-L190) confirma los siguientes huecos de seguridad:

1. **Ausencia de autenticación obligatoria en [`GET /api/worker/proxima-tarea`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1741)**:
   - Línea 1735: `resolved_tenant = caller.get("tenant_id") if caller else tenant_id`. Si no se envía token, acepta cualquier `tenant_id` por query string o pasa `None` al despachador.
2. **Inferencia insegura del tenant desde `audit_logs` ([`task_dispatcher.py:97-105`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L97-L105))**:
   - Si `tenant_id` es `None`, ejecuta `SELECT tenant_id FROM audit_logs WHERE accion = 'LOGIN_EXITOSO' ORDER BY timestamp DESC LIMIT 1`, asignando al worker el tenant del último usuario que inició sesión globalmente.
3. **Consulta fallback global cross-tenant ([`task_dispatcher.py:162-189`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L162-L189))**:
   - Si el tenant inferido no tiene candidatos listos (`if not candidates and target_tenant and not sequence_id and not tenant_id:`), ejecuta un `SELECT` global sobre `leads_en_secuencia` **sin filtrar por `s.tenant_id`**, entregando tareas de cualquier cliente.
4. **Omisión del filtro `s.tenant_id` cuando se envía `sequence_id` ([`task_dispatcher.py:126-131`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L126-L131))**:
   - El uso de `if sequence_id: ... elif target_tenant: ...` hace que, si se envía `secuencia_id`, no se agregue `AND s.tenant_id = ?`, permitiendo despachar tareas de una secuencia perteneciente a otro tenant.
5. **Validación débil de `device_id` y auto-registro de dispositivo ficticio ([`task_dispatcher.py:37-45, 465-481`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L37-L45))**:
   - Si `device_id` no se envía, el paso 0 (`if device_id:`) se omite por completo y en las líneas 472–479 el despachador auto-registra un dispositivo `"dev_default_local"` con clave estática truncada.
   - Si `device_id` sí se envía pero `tenant_id` es `None` (como hace actualmente [`desktop/worker_runner.cjs:139`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs#L139)), [`command_signing_service.is_device_active(device_id, None)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L255-L258) consulta `WHERE id = ?` sin comprobar a qué `tenant_id` pertenece el dispositivo.
   - Además, en [`command_signing_service.register_device()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L214-L231), si un `device_id` ya existe en la tabla `devices`, el `UPDATE` sobrescribe su clave pública sin verificar que el `tenant_id` coincida con el registrado originalmente.
6. **Reporte de resultados sin bloqueo ante firma inválida ([`task_dispatcher.py:549-564`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L549-L564))**:
   - En `process_executed_task_report()`, si `command_signing_service.record_command_result()` falla (por ejemplo, firma Ed25519 inválida o comando expirado) o si no se envía `device_id`, el código solo imprime un `Warning` y continúa mutando el estado del lead y avanzando la secuencia.

---

### A.3 Estado Real de `TASK-04B` (PostgreSQL RLS Real vs. Mocks vs. SQLite)

1. **Distinción estricta de pruebas ejecutadas hasta ahora**:
   - **Pruebas unitarias con mocks ([`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py)):** Ejecutadas (**8/8 PASS**). Simulan `psycopg2` mediante `unittest.mock.MagicMock` y comprueban únicamente que [`_configure_pg_context()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py#L140-L163) emite las sentencias `SET LOCAL app.is_super_admin` y `SET LOCAL app.current_tenant_id`. **No evalúan el motor PostgreSQL ni las políticas de [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql).**
   - **Pruebas SQLite ([`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py), [`tests/test_database_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_database_isolation.py)):** Ejecutadas sobre archivos SQLite temporales aislados. SQLite no posee motor RLS; sólo prueba el filtrado `WHERE tenant_id = ?` en la capa Python.
   - **Pruebas de integración PostgreSQL real (`TASK-04B`):** **NO ejecutadas.** El paquete `psycopg2` no está instalado en el entorno virtual (`psycopg2 installed: False`) y no hay instancia PostgreSQL activa. **Por lo tanto, RLS NO está validado en producción ni en integración real.**

2. **Defectos bloqueantes descubiertos en [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql) y en el uso de [`get_db()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py#L165-L212) al inspeccionar el código para `TASK-04B`**:
   - **Error de sintaxis SQL en [`schema_postgres.sql:468-475`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L468-L475):**
     ```sql
     CREATE POLICY rls_audit_logs_policy ON audit_logs
         FOR ALL
         USING (
             current_setting('app.is_super_admin', true) = 'true'
             OR tenant_id = current_setting('app.current_tenant_id', true)
             OR tenant_id IN (
                 SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
         ); -- <-- Falta un paréntesis de cierre ')' antes de ';'
     ```
     Este error impide ejecutar `schema_postgres.sql` en un motor PostgreSQL real.
   - **Tabla `mensajes_whatsapp` referenciada sin `CREATE TABLE` en [`schema_postgres.sql:308`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L308):**
     La línea 308 ejecuta `CREATE INDEX IF NOT EXISTS idx_mensajes_whatsapp_lead ON mensajes_whatsapp(lead_id);`, pero la tabla `mensajes_whatsapp` no está definida en `schema_postgres.sql` (sí existe en `database.py:322`), lo que aborta la carga del esquema en PostgreSQL.
   - **Ausencia de `FORCE ROW LEVEL SECURITY` en [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql):**
     Las tablas ejecutan `ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;`, pero ninguna incluye `ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;`. En PostgreSQL, el rol propietario de las tablas (*table owner*) ignora las políticas RLS aunque no sea `SUPERUSER`, a menos que se aplique `FORCE ROW LEVEL SECURITY` o la aplicación se conecte con un rol separado que no sea dueño del esquema (`NOSUPERUSER NOBYPASSRLS`).
   - **Llamadas `with get_db() as conn:` sin `tenant_id` en el código de aplicación:**
     Prácticamente la totalidad de [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) y de los servicios (`auth_service.py`, `extractor_engine.py`, `sequence_engine.py`, `lists_engine.py`) invocan `with get_db() as conn:` sin pasar `tenant_id=...` ni `is_super_admin=True`. Con el cierre fail-closed de `TASK-04` (`app.is_super_admin = 'false'`, `app.current_tenant_id = ''`), al conectar un PostgreSQL real con RLS activo, toda consulta que no propague `tenant_id` a `get_db(tenant_id=...)` devolverá 0 filas o fallará en `INSERT`/`UPDATE`.

---

## B. Hallazgos Respaldados Solo por Informes Anteriores (o con Discrepancias frente al Código)

1. **Confusión de numeración en la sección de "Riesgos Abiertos" de [`docs/informe_task03b_blindaje_auth_multitenant.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task03b_blindaje_auth_multitenant.md#L168-L170)**:
   - El informe de `TASK-03B` etiquetó erróneamente el saneamiento de `leads.db` como `TASK-02` (cuando en el backlog oficial es **`TASK-06`**) y la integración de límites/créditos comerciales como `TASK-08` (cuando en el backlog oficial es **`TASK-07`**).
2. **Supuesto de `TASK-06` en el backlog original ([`docs/backlog_estabilizacion_fase2.md:125`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/backlog_estabilizacion_fase2.md#L125)) sobre la titularidad de los 194 leads**:
   - El backlog original asumía que los leads legítimos estaban bajo `ten_superadmin`, mientras que la validación ([`docs/validacion_backlog_estabilizacion.md:19, 54`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/validacion_backlog_estabilizacion.md#L19)) documentó que `ten_superadmin` tiene 0 leads y que **175 de los 194 leads pertenecen a `ten_d933e9ca99`** (y 19 a tenants de prueba).
3. **Alcance incompleto de `TASK-09` en el backlog original ([`docs/backlog_estabilizacion_fase2.md:183`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/backlog_estabilizacion_fase2.md#L183))**:
   - El backlog original solo listaba `browser_service.py` y `extractor_engine.py`, omitiendo que `connection_sync_service.py:136`, `email_resolver_service.py:504` y `sequence_engine.py` también invocan `_call_mcp_evaluate`.

---

## C. Riesgos Abiertos Ordenados por Criticidad

| Prioridad | ID / Categoría | Descripción del Riesgo | Ubicación en Código |
| :---: | :--- | :--- | :--- |
| **P0 (Crítico)** | **Despachador y Reporte de Worker (`TASK-03A`)** | `/api/worker/proxima-tarea` permite consultas sin autenticar; `task_dispatcher.py` infiere el tenant desde `audit_logs`, hace fallback global cross-tenant cuando la cola del tenant está vacía, omite el filtro de tenant si se pasa `secuencia_id`, y `process_executed_task_report` procesa resultados aunque falle la firma del dispositivo. | [`main.py:1724-1746`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1746), [`task_dispatcher.py:37-190, 535-655`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L37-L190) |
| **P0 (Crítico)** | **Endpoints por ID de recurso (IDOR) y Extracción en `main.py`** | Los endpoints sobre `/api/prospectos/{lead_id}*`, `/api/secuencias/{secuencia_id}*`, `/api/listas/{lista_id}*`, `/api/extraccion/buscar` y `/api/extraccion/red-linkedin` aún carecen de autenticación obligatoria o verificación de pertenencia del recurso al tenant. | [`main.py:549, 786-976, 1042-1055, 1281-1330, 1346-1448, 1486-1578`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L786-L1578) |
| **P1 (Alto)** | **Bug SQL en `PATCH /api/usuarios/{user_id}/puesto`** | Consulta `SELECT tenant_id FROM users` en vez de `FROM usuarios`, provocando error 500 (`no such table: users`) al intentar activar/desactivar puestos con un administrador autenticado. | [`main.py:539`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L539) |
| **P1 (Alto)** | **Incompatibilidad de `schema_postgres.sql` y `get_db()` con PostgreSQL RLS real (`TASK-04B`)** | Error de sintaxis en línea 475 de `schema_postgres.sql`, ausencia de tabla `mensajes_whatsapp`, falta de `FORCE ROW LEVEL SECURITY` y llamadas `with get_db() as conn:` sin propagar `tenant_id`. | [`schema_postgres.sql:308, 475`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L468-L475), [`database.py:165`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py#L165) |
| **P1 (Alto)** | **Runner Desktop con `tenant_id: 'ten_superadmin'` fijo y sin token (`TASK-08`)** | `worker_runner.cjs` intenta registrar el dispositivo con `tenant_id: 'ten_superadmin'` sin enviar cabeceras de sesión (lo que ahora recibe `401` tras `TASK-03B`) y consulta `/api/worker/proxima-tarea` sin `tenant_id` ni token. | [`desktop/worker_runner.cjs:80-86, 139`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs#L80-L139) |
| **P1 (Alto)** | **Extracción de Búsqueda y Secuencias bloqueadas en Electron por C-01 (`TASK-02` y `TASK-05`)** | `extractor_engine.py` y `sequence_engine.py` aún invocan `browser_service._call_mcp_evaluate()`, que devuelve `403 ACCESO_DENEGADO (C-01)` cuando Electron está activo. | [`extractor_engine.py:379`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/extractor_engine.py#L379), `sequence_engine.py` |
| **P2 (Medio)** | **Divergencia de Tablas de Facturación y Datos Residuales (`TASK-06` y `TASK-07`)** | `auth_service.py` valida contra `suscripciones` (modelo legacy de puestos) mientras `entitlements_service.py` usa `subscriptions`/`entitlements` (actualmente vacías en `leads.db`), y `leads.db` conserva >30 tenants sintéticos de corridas previas a `TASK-01`. | [`auth_service.py:75-96`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/auth_service.py#L75-L96), [`entitlements_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/entitlements_service.py) |

---

## D. Tabla de Conciliación del Backlog

| ID Original | Alcance Original ([`backlog_estabilizacion_fase2.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/backlog_estabilizacion_fase2.md) / [`validacion_backlog_estabilizacion.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/validacion_backlog_estabilizacion.md)) | Estado Comprobado en Código | Discrepancias Detectadas entre Documentos e Informes |
| :--- | :--- | :---: | :--- |
| **`TASK-01`** | Aislamiento estricto de la suite de pruebas frente a `leads.db` mediante `SQLITE_DB_PATH` en [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py). | **COMPLETADA** (4/4 tests PASS en [`tests/test_database_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_database_isolation.py)). | Ninguna en numeración. Nota: las suites antiguas fuera de `test_database_isolation.py` y `test_auth_tenant_isolation_task03b.py` requieren que el entorno fije `SQLITE_DB_PATH` antes de importarlas. |
| **`TASK-02`** | **Desbloqueo de búsqueda y extracción de prospectos en Electron** (`extractor_engine.py`, `browser_service.py`, `desktop/main.cjs`). | **PENDIENTE** (`extractor_engine.py:379` aún llama a `_call_mcp_evaluate`). | **Discrepancia confirmada:** En [`docs/informe_task03b_blindaje_auth_multitenant.md:169`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task03b_blindaje_auth_multitenant.md#L169) se citó erróneamente `TASK-02` como *"saneamiento de registros sintéticos en `leads.db`"*, alcance que en realidad pertenece a **`TASK-06`**. |
| **`TASK-03A`** | **Aislamiento multi-tenant en el Despachador de Tareas** ([`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) y `/api/worker/proxima-tarea`). | **PENDIENTE** | En el backlog original figuraba como `TASK-03`; en [`docs/validacion_backlog_estabilizacion.md:67-68`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/validacion_backlog_estabilizacion.md#L67-L68) se desglosó en `TASK-03A` (Despachador) y `TASK-03B` (`main.py`). |
| **`TASK-03B`** | **Blindaje de `_resolve_permitted_tenants()` y endpoints REST afectados en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py).** | **IMPLEMENTADA PARCIALMENTE / VERIFICADA EN 30 ENDPOINTS** | `_resolve_permitted_tenants()` y 30 endpoints están blindados y probados (9/9 escenarios PASS), pero persiste el typo `FROM users` en `PATCH /api/usuarios/{user_id}/puesto` ([`main.py:539`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L539)), 2 endpoints de extracción con el patrón antiguo y los endpoints CRUD por `{lead_id}`, `{secuencia_id}` y `{lista_id}` sin autenticación. |
| **`TASK-04`** | **Corrección del bypass de Row-Level Security en PostgreSQL** dentro de [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py) (`_configure_pg_context`). | **COMPLETADA EN `database.py` (Mocks 8/8 PASS)** | Validada únicamente con mocks unitarios ([`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py)). Falta la validación e integración contra PostgreSQL real (**`TASK-04B`**). |
| **`TASK-04B`** | **Validación e integración real de RLS sobre motor PostgreSQL aislado con rol no-superuser.** | **PENDIENTE** | Identificada como extensión de verificación real de `TASK-04`; bloqueada actualmente por falta de `psycopg2`/PostgreSQL y por 2 errores de DDL en [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L308) (líneas 308 y 475). |
| **`TASK-05`** | **Desacoplamiento de ejecución de secuencias y eliminación de `_call_mcp_evaluate`** en `sequence_engine.py`. | **PENDIENTE** | Sin discrepancia de numeración. |
| **`TASK-06`** | **Saneamiento quirúrgico de `leads.db` y migración al modelo \$15/mes** (eliminar >30 tenants de test, conservar los 194 leads —175 de `ten_d933e9ca99`— y poblar `subscriptions`/`entitlements`). | **PENDIENTE** | Confundida nominalmente con `TASK-02` en la nota de riesgos de `informe_task03b`. Además, el backlog original asumía que los leads eran de `ten_superadmin` y la validación corrigió que pertenecen a `ten_d933e9ca99`. |
| **`TASK-07`** | **Unificación de Facturación, Metering (`entitlements_service.py`) y Desconexión de "Puestos de Agencia" (`suscripciones`).** | **PENDIENTE** (fallan 3 de 6 tests en `test_entitlements_and_billing.py`). | Confundida nominalmente con `TASK-08` en la nota de riesgos de `informe_task03b`. |
| **`TASK-08`** | **Parametrización dinámica del `tenant_id` y dispositivo en el Runner Desktop** ([`desktop/worker_runner.cjs:82`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs#L82)). | **PENDIENTE** (`tenant_id: 'ten_superadmin'` sigue hardcodeado en línea 82). | **Discrepancia confirmada:** En [`docs/informe_task03b_blindaje_auth_multitenant.md:170`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task03b_blindaje_auth_multitenant.md#L170) se citó erróneamente `TASK-08` como la integración de límites comerciales (`test_entitlements_and_billing.py`), cuando eso es **`TASK-07`** y el alcance real de **`TASK-08`** es parametrizar el tenant y token en `desktop/worker_runner.cjs`. |
| **`TASK-09`** | **Purga de dependencias y código obsoleto de BrowserOS MCP** (puerto `9010`, `_call_mcp_evaluate`). | **PENDIENTE** | La validación demostró que también abarca `connection_sync_service.py`, `email_resolver_service.py` y `main.py`. |

---

## E. Plan Recomendado para `TASK-03A` y `TASK-04B`

### E.1 Plan Recomendado para `TASK-03A` (y cierre de brechas remanentes de `TASK-03B`)
1. **Cierre puntual de brechas remanentes en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) (Fase previa o conjunta con `TASK-03A`):**
   - Corregir `SELECT tenant_id FROM users` → `SELECT tenant_id FROM usuarios` en [`PATCH /api/usuarios/{user_id}/puesto`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L539) y añadir prueba autenticada (`200` y `403` cross-tenant).
   - Aplicar `_resolve_permitted_tenants()` en [`POST /api/extraccion/buscar`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1281-L1305), [`POST /api/extraccion/red-linkedin`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1307-L1330), [`POST /api/leads/sincronizar-conexiones`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L917-L926) y [`POST /api/secuencias/barrer-esperas`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1444-L1448), así como validación de pertenencia por tenant en los endpoints por `{lead_id}`, `{secuencia_id}` y `{lista_id}`.
2. **Blindaje de [`GET /api/worker/proxima-tarea`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1741) y [`POST /api/worker/reportar-resultado`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1743-L1746):**
   - Exigir autenticación válida mediante `_get_current_user()` + `_resolve_permitted_tenants(caller, tenant_id)` **o** autenticación de dispositivo emparejado donde `device_id` sea obligatorio y esté registrado como `ACTIVE` bajo el `tenant_id` solicitado.
   - Exigir que `device_id` sea obligatorio en `/api/worker/proxima-tarea` y que [`command_signing_service.is_device_active(device_id, resolved_tenant)`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L248-L266) verifique simultáneamente `WHERE id = ? AND tenant_id = ? AND status = 'ACTIVE'`. Si no coincide, rechazar con `HTTP 403` / `dispositivo_revocado: True`.
3. **Eliminación de inferencias y fallbacks globales en [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py):**
   - Eliminar el bloque de inferencia por `audit_logs` ([`task_dispatcher.py:97-105`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L97-L105)). Si `tenant_id` es nulo o vacío, retornar de inmediato `{"hay_tarea": False, "codigo": "TENANT_REQUIRED"}`.
   - Eliminar el bloque fallback global sin `tenant_id` ([`task_dispatcher.py:162-189`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L162-L189)).
   - Cambiar `elif target_tenant:` por `if target_tenant:` en [`task_dispatcher.py:129`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L129) para que `s.tenant_id = ?` se aplique **siempre**, incluso cuando se filtra por `sequence_id`.
   - Eliminar el auto-registro del dispositivo ficticio `"dev_default_local"` ([`task_dispatcher.py:471-481`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L471-L481)).
   - En [`process_executed_task_report()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py#L535-L709), abortar la consolidación si `record_command_result()` no es exitoso y filtrar todas las actualizaciones (`UPDATE leads`, `UPDATE leads_en_secuencia`) verificando el `tenant_id` del comando registrado.
   - En [`command_signing_service.register_device()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py#L214-L231), impedir que un `device_id` existente sea reasignado o actualizado por un `tenant_id` distinto.

### E.2 Plan Recomendado para `TASK-04B` (Pruebas de Integración PostgreSQL con RLS Real)
1. **Corrección previa del DDL en [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql):**
   - Añadir el paréntesis de cierre faltante en la política `rls_audit_logs_policy` ([`schema_postgres.sql:475`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L475)).
   - Añadir `CREATE TABLE IF NOT EXISTS mensajes_whatsapp (...)` junto con su política RLS antes del índice en [`schema_postgres.sql:308`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql#L308).
   - Añadir `ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;` en todas las tablas con RLS y crear un rol de aplicación explícito sin privilegios de superusuario ni bypass (`CREATE ROLE nexus_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app;`).
2. **Propagación de contexto a `get_db(tenant_id=..., is_super_admin=...)`:**
   - Asegurar que las consultas a través de `get_db()` reciban el `tenant_id` resuelto en el servidor (o un `contextvars.ContextVar` alimentado tras `_resolve_permitted_tenants`) para que PostgreSQL reciba el `SET LOCAL app.current_tenant_id` correspondiente en cada transacción.
3. **Ejecución del arnés de pruebas reales PostgreSQL:**
   - Instalar `psycopg2-binary` en `venv`, levantar una base de datos PostgreSQL efímera de pruebas (`nexus_rls_test`), aplicar `schema_postgres.sql` como administrador y ejecutar la suite conectando como `nexus_app` (`NOSUPERUSER`, `NOBYPASSRLS`) con datos sintéticos de Tenant A, Tenant B y Agencia/Subtenant.

---

## F. Archivos Inspeccionados y Pruebas Ejecutadas

### F.1 Archivos Inspeccionados (Solo Lectura)
- [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) (2,346 líneas completas)
- [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py)
- [`auth_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/auth_service.py)
- [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py)
- [`command_signing_service.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/command_signing_service.py)
- [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql)
- [`desktop/worker_runner.cjs`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/worker_runner.cjs)
- [`docs/backlog_estabilizacion_fase2.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/backlog_estabilizacion_fase2.md)
- [`docs/validacion_backlog_estabilizacion.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/validacion_backlog_estabilizacion.md)
- [`docs/informe_task04_correccion_bypass_rls.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task04_correccion_bypass_rls.md)
- [`docs/informe_task03b_blindaje_auth_multitenant.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task03b_blindaje_auth_multitenant.md)
- [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py)
- [`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py)
- [`tests/test_database_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_database_isolation.py)

### F.2 Verificaciones Ejecutadas en esta Revisión
- **Verificación en solo lectura (`mode=ro`) de `leads.db`:** Tamaño `1,126,400` bytes, MD5 `a610785d3a71994b742a608f9f94e2a6`, `194` leads, `40` tenants (100% inalterada).
- **Comprobación de disponibilidad del driver PostgreSQL en `venv`:** `psycopg2 installed: False`.
- **Suites ejecutadas y validadas en sesión sobre SQLite temporal aislada:**
  - `tests/test_auth_tenant_isolation_task03b.py`: 9/9 OK (SQLite temporal).
  - `tests/test_database_isolation.py`: 4/4 OK (SQLite temporal).
  - `tests/test_postgres_rls_security.py`: 8/8 OK (Unitaria con mocks de `psycopg2`).

