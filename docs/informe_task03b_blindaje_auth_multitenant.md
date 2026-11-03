# NEXUSREACH PRO — INFORME DE ENTREGA: TASK-03B
## Blindaje de Autenticación y Aislamiento Multi-Tenant en `main.py`

**Fecha:** 28 de Octubre de 2026  
**Estado:** COMPLETADA Y VERIFICADA  
**Alcance:** Exclusivo TASK-03B (con verificación de no regresión en TASK-01 y TASK-04)  
**Autorización:** Intervención quirúrgica sobre `_resolve_permitted_tenants()`, los endpoints REST afectados en [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) y su suite de pruebas automatizadas en [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py), sin alterar [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py), [`task_dispatcher.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) ni los datos operativos en `leads.db`.

---

## 1. Archivos Modificados y Creados

| Archivo | Tipo de Intervención | Justificación |
| :--- | :--- | :--- |
| [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) | **Modificación quirúrgica** | Endurecimiento Fail-Closed de `_resolve_permitted_tenants()` (exigencia de `id` y `rol` válidos, lista blanca `_ALLOWED_ROLES`, eliminación de fallbacks permisivos `"ten_superadmin"` / `"ten_unauthorized"`), protección de todos los endpoints REST que resolvían `tenant_id` desde parámetros del cliente sin validar autorización, y aislamiento por tenant en las subconsultas de listas/secuencias en `/api/prospectos`. |
| [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py) | **Actualización y ampliación** | Suite automatizada para los escenarios obligatorios **A–I** sobre una base SQLite temporal 100% aislada (`SQLITE_DB_PATH`), con cliente ASGI síncrono en memoria compatible con el sandbox de Windows. |
| [`docs/informe_task03b_blindaje_auth_multitenant.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/informe_task03b_blindaje_auth_multitenant.md) | **Creación (Documentación)** | Informe técnico de diagnóstico, cambios aplicados, matriz de endpoints revisados, resultados de pruebas y verificación de integridad de `leads.db`. |

---

## 2. Diagnóstico (FASE 1) y Descripción de la Corrección (FASE 2)

### 2.1 Diagnóstico de la Brecha de Seguridad
1. **Resolución de Identidad y Permisos en [`_resolve_permitted_tenants()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L265-L327)**:
   - La autenticación se realiza mediante [`_get_current_user()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L241-L253), que extrae el token desde `X-Session-Token` o `Authorization: Bearer <token>` y delega en [`auth_service.verify_token()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/auth_service.py#L268-L325) la verificación en memoria y base de datos (existencia de sesión, expiración, estado activo del usuario, puesto activo, estado del tenant y vigencia de la suscripción).
   - En `_resolve_permitted_tenants()`, era necesario exigir que `caller` contenga tanto `id` como `rol` válidos, validar que `rol` pertenezca exclusivamente a los roles reconocidos del sistema (`_ALLOWED_ROLES = {"SUPER_ADMIN", "AGENCY_ADMIN", "COMPANY_ADMIN", "COMPANY_MEMBER", "INDIVIDUAL", "FREELANCER"}`) y eliminar el fallback `caller_tenant = "ten_superadmin"` cuando `caller_tenant` y `tenant_query` estuvieran ausentes.
2. **Patrón de Bypass por `tenant_id` o Fallback a `"ten_superadmin"` en Endpoints REST**:
   - Además de los endpoints principales de lectura y exportación (`/api/prospectos`, `/api/metricas`, `/api/secuencias`, `/api/listas`, `/api/dashboard/metricas`, `/api/tenants/{tenant_id}/export-csv`, Zoho Config, Supresión y Derechos ARCO), la inspección exhaustiva de [`main.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py) detectó **16 endpoints adicionales** que aún presentaban la expresión vulnerable:
     ```python
     resolved_tenant = tenant_id or (caller.get("tenant_id") if caller else "ten_superadmin")
     ```
     o carecían de verificación de `caller`:
     - [`GET /api/auth/usuarios`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L177-L188) y [`PATCH /api/auth/usuarios/{user_id}/suscripcion`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L190-L212)
     - [`POST /api/tenants/{tenant_id}/usuarios`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L499-L522) y [`PATCH /api/usuarios/{user_id}/puesto`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L524-L547)
     - [`POST /api/prospectos/importar-lote`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L996-L1016)
     - [`POST /api/devices/register`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1664-L1686), [`POST /api/devices/revoke`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1688-L1698) y [`GET /api/devices/list`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1700-L1714)
     - [`GET /api/accounts/{account_id}/health`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1966-L1988), [`POST /api/accounts/{account_id}/risk-signal`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1990-L2012) y [`POST /api/accounts/{account_id}/reactivate`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2014-L2029)
     - [`POST /api/selectors/publish`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2054-L2082)
     - [`GET /api/billing/subscription`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2125-L2149), [`POST /api/billing/checkout/subscription`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2152-L2177) y [`POST /api/billing/checkout/pack`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2180-L2209)
     - [`GET /api/observability/metrics`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2246-L2262), [`GET /api/observability/team-alerts`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2265-L2283) y [`GET /api/support/diagnostics-bundle`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L2286-L2302)

### 2.2 Corrección Aplicada
1. **Blindaje de [`_resolve_permitted_tenants()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L265-L327)**:
   ```python
   _ALLOWED_ROLES = {
       "SUPER_ADMIN",
       "AGENCY_ADMIN",
       "COMPANY_ADMIN",
       "COMPANY_MEMBER",
       "INDIVIDUAL",
       "FREELANCER",
   }

   def _resolve_permitted_tenants(caller: Optional[Dict[str, Any]], tenant_query: Optional[str] = None) -> List[str]:
       if not caller or not isinstance(caller, dict):
           raise HTTPException(status_code=401, detail="Autenticación requerida. Token inválido o ausente.")

       caller_id = caller.get("id")
       role = caller.get("rol")
       if not caller_id or not isinstance(caller_id, str) or not caller_id.strip() or not role or not isinstance(role, str):
           raise HTTPException(status_code=401, detail="Autenticación requerida. Identidad de sesión incompleta o inválida.")

       role = role.strip()
       if role not in _ALLOWED_ROLES:
           raise HTTPException(status_code=403, detail="Contexto de seguridad inválido: rol no autorizado.")

       caller_tenant = (caller.get("tenant_id") or "").strip() if isinstance(caller.get("tenant_id"), str) else ""
       clean_query = tenant_query.strip() if (tenant_query and isinstance(tenant_query, str) and tenant_query.strip()) else None

       if role == "SUPER_ADMIN":
           if clean_query:
               return [clean_query]
           if caller_tenant:
               return [caller_tenant]
           raise HTTPException(status_code=403, detail="Contexto de seguridad inválido: tenant no asignado al usuario.")

       if not caller_tenant:
           raise HTTPException(status_code=403, detail="Contexto de seguridad inválido: tenant no asignado al usuario.")

       if role == "AGENCY_ADMIN":
           subtenants = auth_service.list_agency_subtenants(caller_tenant)
           valid_ids = [caller_tenant] + [st["id"] for st in subtenants]
           if clean_query:
               if clean_query in valid_ids:
                   return [clean_query]
               raise HTTPException(status_code=403, detail="No tienes autorización para acceder a los datos de este workspace.")
           return [caller_tenant]

       if clean_query and clean_query != caller_tenant:
           raise HTTPException(status_code=403, detail="No tienes autorización para acceder a los datos de este workspace.")

       return [caller_tenant]
   ```
2. **Aislamiento de Subconsultas en [`GET /api/prospectos`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L657-L680)**:
   - Los filtros opcionales `lista_id` y `secuencia_id` ahora verifican mediante `JOIN` que tanto la lista (`listas_leads.tenant_id`) como la secuencia (`secuencias.tenant_id`) pertenezcan al conjunto de `tenants` autorizados del solicitante.
3. **Eliminación de Fallbacks Permisivos en Todos los Endpoints Privados**:
   - Se sustituyó toda resolución directa de `tenant_id` o fallback a `"ten_superadmin"` por `_resolve_permitted_tenants(caller, ...)`.

---

## 3. Matriz de Endpoints Revisados y Resultado

| Endpoint | Método | Clasificación | Estado Final | Comportamiento de Seguridad |
| :--- | :---: | :---: | :---: | :--- |
| `/api/metricas` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`). Filtra por `_resolve_permitted_tenants(caller, tenant_id)` (`403` si es ajeno). |
| `/api/prospectos` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`). Filtra leads, `lista_id` y `secuencia_id` por tenant autorizado (`403` si es ajeno). |
| `/api/prospectos/importar-lote` | `POST` | Privado (Tenant) | **Corregido** | Eliminado fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, datos.get("tenant_id"))`. |
| `/api/secuencias` | `GET`, `POST` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`). Aísla lectura y creación por `_resolve_permitted_tenants` (`403` si es ajeno). |
| `/api/listas` | `GET`, `POST` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`). Aísla lectura y creación por `_resolve_permitted_tenants` (`403` si es ajeno). |
| `/api/dashboard/metricas` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`). Aísla métricas por `_resolve_permitted_tenants` (`403` si es ajeno). |
| `/api/tenants/{tenant_id}/export-csv` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y pertenencia/autorización sobre `tenant_id` (`403` si intenta exportar otro tenant). |
| `/api/tenants/{tenant_id}/zoho-config` | `GET`, `POST` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y autorización sobre `tenant_id` (`403`). |
| `/api/tenants/{tenant_id}/suppression` | `POST` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y autorización sobre `tenant_id` (`403`). |
| `/api/leads/{lead_id}/activities` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y filtra actividades dentro del tenant autorizado (`403`). |
| `/api/tenants/{tenant_id}/leads/{lead_id}/export-subject-data` | `GET` | Privado (ARCO) | **Blindado** | Requiere token válido (`401`) y autorización sobre `tenant_id` (`403`). |
| `/api/tenants/{tenant_id}/leads/{lead_id}/data-subject-deletion` | `DELETE` | Privado (ARCO) | **Blindado** | Requiere token válido (`401`) y autorización sobre `tenant_id` (`403`). |
| `/api/tenants/{tenant_id}/purge-inactive-leads` | `POST` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y autorización sobre `tenant_id` (`403`). |
| `/api/tenants/{tenant_id}/cascade-deletion` | `DELETE` | Privado (Admin) | **Blindado** | Requiere token válido (`401`) y rol `SUPER_ADMIN` o admin propietario del tenant (`403`). |
| `/api/tenants` | `GET` | Privado (SuperAdmin) | **Blindado** | Requiere token válido (`401`) y rol `SUPER_ADMIN` (`403`). |
| `/api/admin/cuentas` | `POST` | Privado (SuperAdmin) | **Blindado** | Requiere token válido (`401`) y rol `SUPER_ADMIN` (`403`). |
| `/api/auth/usuarios` | `GET` | Privado (SuperAdmin) | **Corregido** | Añadida exigencia de token válido (`401`) y rol `SUPER_ADMIN` (`403`). |
| `/api/auth/usuarios/{user_id}/suscripcion` | `PATCH` | Privado (SuperAdmin) | **Corregido** | Añadida exigencia de token válido (`401`) y rol `SUPER_ADMIN` (`403`). |
| `/api/tenants/{tenant_id}/revocar` | `POST` | Privado (Admin) | **Blindado** | Requiere token válido (`401`) y `SUPER_ADMIN` o `AGENCY_ADMIN` padre (`403`). |
| `/api/tenants/{tenant_id}/reactivar` | `POST` | Privado (Admin) | **Blindado** | Requiere token válido (`401`) y `SUPER_ADMIN` o `AGENCY_ADMIN` padre (`403`). |
| `/api/tenants/{tenant_id}/puestos` | `POST` | Privado (Admin) | **Blindado** | Requiere token válido (`401`) y `SUPER_ADMIN` o `AGENCY_ADMIN` padre (`403`). |
| `/api/agencia/{agencia_id}/clientes` | `GET`, `POST` | Privado (Agencia) | **Blindado** | Requiere token válido (`401`) y pertenencia a la agencia o `SUPER_ADMIN` (`403`). |
| `/api/agencia/{agencia_id}/finanzas` | `GET` | Privado (Agencia) | **Blindado** | Requiere token válido (`401`) y pertenencia a la agencia o `SUPER_ADMIN` (`403`). |
| `/api/tenants/{tenant_id}/miembros` | `GET` | Privado (Tenant) | **Blindado** | Requiere token válido (`401`) y autorización sobre el tenant o subtenant (`403`). |
| `/api/tenants/{tenant_id}/usuarios` | `POST` | Privado (Admin) | **Corregido** | Añadida validación `_resolve_permitted_tenants(caller, tenant_id)` y rol administrativo (`401`/`403`). |
| `/api/usuarios/{user_id}/puesto` | `PATCH` | Privado (Admin) | **Corregido** | Añadida validación de token (`401`), rol administrativo y autorización sobre el `tenant_id` del usuario objetivo (`403`). |
| `/api/devices/register` | `POST` | Privado (Tenant) | **Corregido** | Eliminado default `"ten_superadmin"`. Resuelve tenant con `_resolve_permitted_tenants(caller, req.tenant_id)`. |
| `/api/devices/revoke` | `POST` | Privado (Tenant) | **Corregido** | Resuelve tenant con `_resolve_permitted_tenants(caller, req.tenant_id)` (`401`/`403`). |
| `/api/devices/list` | `GET` | Privado (Tenant) | **Corregido** | Eliminado fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/accounts/{account_id}/health` | `GET` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/accounts/{account_id}/risk-signal` | `POST` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/accounts/{account_id}/reactivate` | `POST` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/selectors/publish` | `POST` | Privado (SuperAdmin) | **Corregido** | Exige `if not caller: raise HTTPException(401)` además de `rol == "SUPER_ADMIN"` (`403`). |
| `/api/billing/subscription` | `GET` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/billing/checkout/subscription` | `POST` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/billing/checkout/pack` | `POST` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/observability/metrics` | `GET` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/observability/team-alerts` | `GET` | Privado (SuperAdmin) | **Corregido** | Exige token válido (`401`) y rol `SUPER_ADMIN` (`403`). |
| `/api/support/diagnostics-bundle` | `GET` | Privado (Tenant) | **Corregido** | Eliminado bypass por `tenant_id` y fallback `"ten_superadmin"`. Usa `_resolve_permitted_tenants(caller, tenant_id)`. |
| `/api/auth/login`, `/api/opt-out`, `/api/billing/webhooks/{provider}`, `/api/devices/server-public-key`, `/api/selectors/active`, `/api/system/version` | Varios | Públicos Legítimos | **Conservados** | Documentados como públicos por contrato (inicio de sesión, baja ARCO pública por identificador, webhooks firmados con HMAC y metadatos públicos del cliente). No exponen datos privados de tenants. |

---

## 4. Pruebas Ejecutadas y Resultados Reales (FASE 3)

### 4.1 Suite Obligatoria TASK-03B (`tests/test_auth_tenant_isolation_task03b.py`)
Comando ejecutado:
```powershell
.\venv\Scripts\python.exe -m unittest tests/test_auth_tenant_isolation_task03b.py tests/test_database_isolation.py tests/test_postgres_rls_security.py -v
```

| Escenario | Método de Prueba | Resultado |
| :---: | :--- | :---: |
| **A** | `test_scenario_a_unauthenticated_request_rejected_with_401` (52 sub-pruebas sin credenciales, con y sin `tenant_id` en URL) | **OK (PASS)** |
| **B** | `test_scenario_b_invalid_or_expired_token_rejected_with_401` (tokens falsos, vacíos, malformados y sesiones expiradas) | **OK (PASS)** |
| **C** | `test_scenario_c_authenticated_user_accesses_own_tenant` (`200 OK` en prospectos, métricas, secuencias, listas y CSV propio) | **OK (PASS)** |
| **D** | `test_scenario_d_user_a_cannot_read_tenant_b_data` (`403 Forbidden` en todos los endpoints al consultar `tenant_beta` desde `token_alpha`) | **OK (PASS)** |
| **E** | `test_scenario_e_user_a_cannot_export_tenant_b_data` (`403 Forbidden` en `/export-csv`, `/export-subject-data` y `/data-subject-deletion` de otro tenant) | **OK (PASS)** |
| **F** | `test_scenario_f_tampered_tenant_id_fails_closed` (`403 Forbidden` ante `tenant_id` manipulados o inyecciones SQL en query/body) | **OK (PASS)** |
| **G** | `test_scenario_g_administrative_privileges_enforced_strictly` (`SUPER_ADMIN` audita tenants; `AGENCY_ADMIN` accede a subtenant propio pero recibe `403` en ajenos; `COMPANY_ADMIN` recibe `403` en rutas de `SUPER_ADMIN`/agencia) | **OK (PASS)** |
| **H** | `test_scenario_h_no_indirect_leakage_in_metrics_lists_sequences` (aislamiento en conteos de `/api/metricas`, listas, secuencias y filtros cruzados `lista_id`/`secuencia_id`) | **OK (PASS)** |
| **I** | `test_scenario_i_resolve_permitted_tenants_unit_fail_closed` (12 casos de borde con `caller` nulo, vacío, sin `id`, sin `rol`, rol desconocido o sin `tenant_id`) | **OK (PASS)** |

### 4.2 Suites de No Regresión Ejecutadas en Base Temporal Aislada
- [`tests/test_database_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_database_isolation.py) (TASK-01): **4/4 OK**
- [`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py) (TASK-04): **8/8 OK**
- [`tests/test_multitenancy_and_auth.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_multitenancy_and_auth.py): **3/3 OK**
- [`tests/test_data_privacy_compliance.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_data_privacy_compliance.py): **5/5 OK**
- [`tests/test_zoho_bridge_and_dedup.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_zoho_bridge_and_dedup.py): **6/6 OK**
- [`tests/test_observability_and_distribution.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_observability_and_distribution.py): **5/5 OK**
- [`tests/test_safety_and_antiban.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_safety_and_antiban.py): **6/6 OK**

---

## 5. Pruebas Pendientes y Limitaciones del Entorno

1. **Instancia PostgreSQL en Vivo (`USE_POSTGRES=true`)**:
   - No existe un servidor PostgreSQL activo en el entorno de ejecución local. El comportamiento de Row-Level Security (RLS) se validó mediante el arnés de pruebas unitarias con mocks de conexión en [`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py) (8/8 OK), quedando pendiente la prueba de integración contra un motor PostgreSQL en vivo.
2. **Scripts con Cliente HTTP Externo (`urllib.request` hacia `http://localhost:8000`)**:
   - Los scripts [`tests/test_agency_full_lifecycle.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_agency_full_lifecycle.py), [`tests/test_tenant_data_isolation.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_tenant_data_isolation.py) y [`tests/test_phase2_endpoints.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_phase2_endpoints.py) abren sockets TCP loopback hacia `localhost:8000`, operación restringida dentro del sandbox de Windows (`WinError 10013`). Sus escenarios de negocio equivalentes fueron verificados en memoria dentro de [`tests/test_auth_tenant_isolation_task03b.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_auth_tenant_isolation_task03b.py).

---

## 6. Riesgos que Continúan Abiertos (Fuera del Alcance de TASK-03B)

- **TASK-03A (Pendiente)**: El endpoint [`GET /api/worker/proxima-tarea`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/main.py#L1724-L1741) y [`task_dispatcher.get_next_dispatched_task()`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/task_dispatcher.py) aún requieren el blindaje específico de despacho de tareas y emparejamiento de dispositivo del worker local, alcance reservado a `TASK-03A`.
- **TASK-02 (Pendiente)**: Existen registros sintéticos residuales de corridas previas en `leads.db` cuyo saneamiento controlado corresponde a `TASK-02`.
- **TASK-08 (Pendiente)**: La integración completa de límites comerciales y créditos en el despachador ([`tests/test_entitlements_and_billing.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_entitlements_and_billing.py)) corresponde a `TASK-08`.

---

## 7. Confirmación de No Modificación de Datos Operativos (`leads.db`)

Se auditó el archivo operativo `leads.db` en modo solo lectura (`mode=ro`) antes y después de realizar los cambios y ejecutar todas las suites de pruebas:

| Métrica | Antes de TASK-03B | Después de TASK-03B | Estado |
| :--- | :---: | :---: | :---: |
| **Tamaño en disco** | `1,126,400` bytes | `1,126,400` bytes | **Idéntico** |
| **Hash MD5** | `a610785d3a71994b742a608f9f94e2a6` | `a610785d3a71994b742a608f9f94e2a6` | **Idéntico** |
| **Total de Leads** | `194` | `194` | **Sin cambios** |
| **Total de Tenants** | `40` | `40` | **Sin cambios** |
| **`PRAGMA integrity_check`** | `ok` | `ok` | **Íntegro** |

