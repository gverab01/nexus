# NEXUSREACH PRO — INFORME DE ENTREGA: TASK-04
## Corrección del Bypass RLS en PostgreSQL y Blindaje de Contexto

**Fecha:** 26 de Octubre de 2026  
**Estado:** COMPLETADA Y VERIFICADA  
**Alcance:** Exclusivo TASK-04 (con verificación de no regresión en TASK-01)  
**Autorización:** Intervención quirúrgica sobre el contexto PostgreSQL/RLS sin alterar módulos secundarios ni datos operativos.

---

## 1. Archivos Modificados y Creados

| Archivo | Tipo de Intervención | Justificación |
| :--- | :--- | :--- |
| [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py) | **Modificación quirúrgica** | Eliminación de la elevación implícita a superadministrador cuando `tenant_id` es nulo. Implementación de `_configure_pg_context()` con aislamiento estricto por defecto (`is_super_admin = 'false'`, `current_tenant_id = ''`) y validación estricta de tipo booleano (`is True`). |
| [`tests/test_postgres_rls_security.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/tests/test_postgres_rls_security.py) | **Creación (Suite nueva)** | Arnés automatizado de pruebas unitarias y de seguridad para validar el ciclo de vida del contexto RLS, inyección/spoofing de parámetros, comportamiento en Connection Pool, manejo de excepciones y compatibilidad con SQLite. |

---

## 2. Diagnóstico del Problema Original y Corrección Aplicada

### 2.1 Diagnóstico de la Brecha de Seguridad
En [`database.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py) (líneas 146-147 y 169-170 de la versión previa), tanto en la rama con Connection Pool como en la rama de conexión directa a PostgreSQL, existía la siguiente lógica:

```python
if is_super_admin:
    cur.execute("SET LOCAL app.is_super_admin = 'true';")
elif tenant_id:
    cur.execute("SET LOCAL app.is_super_admin = 'false';")
    cur.execute("SET LOCAL app.current_tenant_id = %s;", (tenant_id,))
else:
    cur.execute("SET LOCAL app.is_super_admin = 'true';")  # <-- FALLO CRÍTICO: Elevación implícita
```

#### Impacto Técnico:
En PostgreSQL, las políticas Row-Level Security (RLS) definidas en [`schema_postgres.sql`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql) para todas las tablas de negocio (`leads`, `listas_leads`, `secuencias`, `linkedin_accounts`, etc.) evalúan la condición:
```sql
USING (
    current_setting('app.is_super_admin', true) = 'true'
    OR tenant_id = current_setting('app.current_tenant_id', true)
    OR tenant_id IN (
        SELECT id FROM tenants WHERE parent_tenant_id = current_setting('app.current_tenant_id', true)
    )
)
```
Dado que la rama `else` fijaba `app.is_super_admin = 'true'`, cualquier invocación a `get_db()` que no suministrara explícitamente `tenant_id` (por ejemplo, llamadas desde endpoints desprotegidos o tareas asíncronas no autenticadas) adquiría automáticamente visibilidad y capacidad de modificación irrestricta sobre los prospectos, secuencias y cuentas de **todos** los clientes del sistema.

### 2.2 Corrección Quirúrgica Aplicada
Se refactorizó la configuración de la sesión SQL en una función unificada y fuertemente tipada:

```python
def _configure_pg_context(cur, tenant_id=None, is_super_admin=False):
    """Configura el contexto de sesión PostgreSQL para Row-Level Security (RLS).
    Garantiza aislamiento estricto por defecto:
    - is_super_admin=True: Concede acceso administrativo completo (solo si es booleano estricto True).
    - tenant_id (no vacío): Aísla la sesión al tenant especificado.
    - Sin tenant_id ni superadmin: Restringe el contexto a 0 filas (is_super_admin='false', current_tenant_id='').
    """
    if is_super_admin is True:
        cur.execute("SET LOCAL app.is_super_admin = 'true';")
    else:
        cur.execute("SET LOCAL app.is_super_admin = 'false';")
        clean_tenant = str(tenant_id).strip() if tenant_id else ""
        if clean_tenant:
            cur.execute("SET LOCAL app.current_tenant_id = %s;", (clean_tenant,))
        else:
            cur.execute("SET LOCAL app.current_tenant_id = '';")
```

Ambas rutas de acceso a PostgreSQL en `get_db()` (`if pool is not None:` y `else:`) delegan en `_configure_pg_context(cur, tenant_id=tenant_id, is_super_admin=is_super_admin)`.

#### Principios de Seguridad Implementados:
1. **Restricción por defecto (Fail-Closed):** Si `tenant_id` es `None`, una cadena vacía o espacios en blanco, `app.is_super_admin` se fija en `'false'` y `app.current_tenant_id` en `''`. La consulta RLS evalúa a `FALSE` en todas las filas, devolviendo **0 registros** e impidiendo cualquier inserción no autorizada.
2. **Protección contra spoofing del cliente:** La condición `is_super_admin is True` valida que el argumento sea estrictamente un tipo booleano de Python con valor `True`. Strings o valores falsamente verdaderos (`"true"`, `"1"`, `1`, `["admin"]`) enviados en cuerpos JSON o parámetros de consulta son rechazados y conducen al contexto restringido.
3. **Aislamiento en Connection Pool:** Las variables `SET LOCAL` solo tienen vigencia dentro de la transacción activa de PostgreSQL. Al realizarse el `commit()` o `rollback()`, las variables se purgan automáticamente. Adicionalmente, cada vez que una conexión es extraída del pool, su contexto se reconfigura de forma determinista antes de ceder el control al código de la aplicación.
4. **Contención de Excepciones:** En caso de error dentro del bloque `with get_db()`, el context manager ejecuta inmediatamente `conn.rollback()`, asegurando que no queden privilegios residuales en la conexión antes de su devolución al pool o cierre.

---

## 3. Pruebas Automatizadas Ejecutadas y Resultados Reales

### 3.1 Suite de Seguridad RLS: `tests/test_postgres_rls_security.py`
Ejecución: `python -m unittest tests/test_postgres_rls_security.py -v`

| Escenario de Prueba | Descripción | Resultado |
| :--- | :--- | :---: |
| `test_scenario_a_no_tenant_id_unprivileged_remains_restricted` | Valida que sin `tenant_id` se emita `is_super_admin='false'` y `current_tenant_id=''`. | **PASÓ (OK)** |
| `test_scenario_b_valid_tenant_id_isolated_properly` | Valida que con `tenant_id="ten_techcorp"` se emita `is_super_admin='false'` y `current_tenant_id='ten_techcorp'`. | **PASÓ (OK)** |
| `test_scenario_c_empty_or_whitespace_tenant_id_remains_restricted` | Valida que valores vacíos (`""`, `"   "`) queden restringidos sin fallback a ningún tenant. | **PASÓ (OK)** |
| `test_scenario_d_strict_boolean_check_prevents_client_spoofing` | Valida que parámetros spoofed (`"true"`, `"1"`, `1`, `["admin"]`) no eleven privilegios. | **PASÓ (OK)** |
| `test_scenario_e_explicit_super_admin_authorized` | Valida que la elevación con `is_super_admin=True` legítimo configure `app.is_super_admin='true'`. | **PASÓ (OK)** |
| `test_scenario_f_pool_connection_lifecycle_and_reuse_isolation` | Valida que una conexión devuelta al pool tras una operación superadmin se reconfigure en modo restringido en la siguiente operación. | **PASÓ (OK)** |
| `test_scenario_g_exception_triggers_rollback_without_state_leak` | Valida que una excepción dentro del bloque invoque `conn.rollback()` inmediato y limpie el estado. | **PASÓ (OK)** |
| `test_scenario_h_sqlite_isolation_retains_task01_behavior` | Valida que las conexiones SQLite continúen usando `SQLITE_DB_PATH` y la base temporal sin alteración. | **PASÓ (OK)** |

**Resultado global:** 8 pruebas ejecutadas en 0.081s — **100% Exitosas**.

### 3.2 Verificación de No Regresión en TASK-01 (Aislamiento SQLite)
Ejecución: `python -m unittest tests/test_database_isolation.py -v`
- `test_default_path_when_env_unset`: **PASÓ (OK)**
- `test_default_path_when_env_empty_or_whitespace`: **PASÓ (OK)**
- `test_custom_path_redirection_and_isolation`: **PASÓ (OK)**
- `test_invalid_path_raises_error_without_fallback`: **PASÓ (OK)**

**Resultado global:** 4 pruebas ejecutadas — **100% Exitosas**.

---

## 4. Pruebas Pendientes y Motivos Técnicos

Conforme a la instrucción obligatoria de no inventar resultados ni suponer infraestructuras:
- **Estado de PostgreSQL en el entorno local:** Se inspeccionó el sistema y se confirmó que:
  - `DATABASE_URL` no está definida en el entorno local (`None`).
  - El paquete driver `psycopg` / `psycopg[binary]` no está instalado en el entorno de Python 3.12 del sistema.
  - No existe un servicio de PostgreSQL de Windows activo ni contenedor Docker disponible.
- **Verificación pendiente:** La ejecución física de consultas concurrentes y políticas RLS contra una instancia real de PostgreSQL (ej. AWS RDS São Paulo `sa-east-1`, Neon o Supabase) con un usuario estándar de aplicación no-superuser queda registrada como verificación pendiente de integración continua / despliegue a staging.
- **Cobertura obtenida:** La generación de las sentencias SQL `SET LOCAL`, el control de excepciones, la tipificación estricta y el ciclo de vida de transacciones quedaron cubiertos y validados al 100% mediante el arnés automatizado.

---

## 5. Operaciones Legítimas Identificadas que Requieren Privilegios

La auditoría del código determinó que las siguientes operaciones del sistema invocan legítimamente `get_db(is_super_admin=True)` y continúan operando con los privilegios requeridos:

1. **[`database.py:197`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/database.py#L197) (`init_db()`):** Inspección de `information_schema.tables`, aplicación de `schema_postgres.sql` y sembrado de usuarios y secuencias del sistema durante el despliegue inicial.
2. **[`safety_engine.py:957`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/safety_engine.py#L957) (`handle_account_incident()`):** Intervención de emergencia (kill-switch global) para congelar cuentas de LinkedIn a nivel plataforma ante detección de incidentes anti-ban en menos de 24 horas.
3. **[`privacy_compliance_service.py:187`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/privacy_compliance_service.py#L187) (`delete_tenant_cascade()`):** Supresión permanente de tenants y todos sus datos en cascada en cumplimiento del derecho al olvido (Ley 21.719 / GDPR).
4. **[`scripts/migrate_sqlite_to_postgres.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/migrate_sqlite_to_postgres.py):** Traspaso inicial masivo de prospectos hacia PostgreSQL.

---

## 6. Confirmación de Preservación Absoluta de `leads.db`

Se verificaron las métricas de la base de datos operativa antes y después de la intervención:

| Métrica de Control | Valor Baseline (Inicial) | Valor Tras TASK-04 | Estado |
| :--- | :--- | :--- | :---: |
| **Tamaño de archivo** | `1,126,400` bytes | `1,126,400` bytes | **Idéntico** |
| **Hash MD5** | `e11799e9412c4d452609d50bfc97a286` | `e11799e9412c4d452609d50bfc97a286` | **Idéntico** |
| **Total de Leads** | `194` | `194` | **Idéntico** |
| **Total de Tenants** | `40` | `40` | **Idéntico** |
| **Integridad SQLite (`PRAGMA integrity_check`)** | `ok` | `ok` | **Íntegro** |
| **Archivos auxiliares WAL / SHM** | Inexistentes | Inexistentes | **Limpio** |

Se certifica que la base operativa `leads.db` no sufrió ninguna modificación.

---

## 7. Riesgos de Seguridad y Pendientes Abiertos

1. **Propagación de `tenant_id` en endpoints de `main.py`:** En SQLite, las llamadas sin `tenant_id` siguen funcionando. Al migrar a PostgreSQL, los endpoints de `main.py` que llaman a `get_db()` sin extraer el tenant del JWT verán 0 filas. Esto debe abordarse cuando se intervenga `main.py` en la tarea correspondiente de saneamiento de endpoints.
2. **Rol de conexión en `DATABASE_URL`:** En PostgreSQL, los usuarios con rol de `SUPERUSER` ignoran las políticas RLS por defecto. Es indispensable que la base de datos de producción utilice un rol con privilegios estándar de aplicación (ej. `nexus_app`), o bien que se declare `FORCE ROW LEVEL SECURITY` en cada tabla para forzar RLS incluso sobre los propietarios de las tablas.
3. **Dependencia `cryptography` faltante en el entorno:** Sigue impidiendo la ejecución de las pruebas unitarias de firma de comandos de dispositivos (`tests/test_signed_commands.py`).

---

## Conclusión y Próximos Pasos

- **`TASK-01` (Aislamiento de pruebas SQLite):** COMPLETADA.
- **`TASK-04` (Corrección de Bypass RLS):** COMPLETADA.
- **Arnés de seguridad:** Activo y blindado contra regresiones.

El sistema se encuentra en un estado limpio, seguro y estable, a la espera de autorización explícita para la siguiente tarea del backlog.
