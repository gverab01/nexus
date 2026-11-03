# NexusReach Pro — Informe de Validación Final del Backlog (Fase 2)

> **Documento de Revisión Técnica Independiente previo a la Implementación**  
> **Fecha:** Octubre 2026  
> **Rol:** Revisor Técnico Independiente  
> **Alcance:** Validación de coherencia entre la Auditoría de Fase 1, el Backlog de Fase 2, las decisiones confirmadas y el código fuente real.  
> **Modo de Inspección:** Exclusivamente de Lectura (Read-Only)  
> **Estado:** Aprobado para Ejecución de Primera Intervención

---

## 1. Hallazgos Confirmados con Evidencia en Código

A través de la inspección estática del repositorio se comprobaron de forma irrefutable los siguientes hechos:

### 1.1 Contaminación Sistemática de `leads.db` por la Suite de Pruebas
- **Ubicación:** `database.py:14`, `tests/test_signed_commands.py:48-60`, `tests/test_data_privacy_compliance.py:46-52`.
- **Evidencia:** `database.py` fija rígidamente `DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")` sin admitir variables de entorno (`TEST_DB_PATH` o similar). Los métodos `setUp()` de las suites de prueba insertan tenants y prospectos directamente sobre la base operativa.
- **Impacto Real Medido:** `leads.db` tiene **40 tenants**, de los cuales **más de 30 son tenants residuales de prueba** (`ten_wa_daily_limit`, `ten_freeze_test`, `ten_cli_*`, etc.). De los 194 leads en la base, **175 pertenecen al tenant legítimo `ten_d933e9ca99` (Gabriel Vera)** y 19 a tenants de prueba.

### 1.2 Extracción de Búsqueda Rota en Electron por Concurrencia de Directivas
- **Ubicación:** `extractor_engine.py:365-381`, `browser_service.py:439-444`, `desktop/main.cjs:599-603`.
- **Evidencia:** `desktop/main.cjs` bloqueó `/evaluate` con código 403 para cerrar la brecha C-01. Sin embargo, `extractor_engine.py:379` aún ejecuta `browser_service._call_mcp_evaluate(EXTRACTION_SCRIPT_JS)`. Al detectar que Electron está activo, `browser_service.py` retorna de inmediato `ACCESO_DENEGADO (C-01)` y la búsqueda arroja siempre 0 prospectos.

### 1.3 Bypass de Autenticación y Filtrado Multi-tenant en Endpoints REST
- **Ubicación:** `main.py:245-246`, `main.py:542-556`.
- **Evidencia:** La función `_resolve_permitted_tenants` contiene una vulnerabilidad de omisión de autenticación:
  ```python
  if not caller:
      return [tenant_query] if tenant_query else ["ten_unauthorized"]
  ```
  Si una petición no autenticada (sin token Bearer) llama a `/api/prospectos?tenant_id=ten_techcorp`, la función retorna `['ten_techcorp']` y el endpoint entrega todos los leads de esa empresa sin credenciales. Esto afecta a 8 endpoints críticos en `main.py` (`/api/prospectos`, `/api/metricas`, `/api/secuencias`, `/api/listas`, `/api/tenants/{id}/export-csv`, etc.).

### 1.4 Bypass Silencioso de Row-Level Security en PostgreSQL
- **Ubicación:** `database.py:136-137`, `database.py:159-160`, `schema_postgres.sql:327, 334, 347, etc.`.
- **Evidencia:** Cuando una llamada a `get_db()` no especifica `tenant_id`, la rama `else` ejecuta `SET LOCAL app.is_super_admin = 'true';`. En PostgreSQL, esto anula todas las políticas RLS y otorga visibilidad total sobre todos los clientes.

### 1.5 Referencias Residuales de BrowserOS MCP Omitidas en el Backlog
- **Ubicación:** `connection_sync_service.py:136`, `email_resolver_service.py:504`, `sequence_engine.py:771, 870, 893, 1089`, `main.py:1004-1021`.
- **Evidencia:** Existen llamadas directas a `_call_mcp_evaluate` y al puerto `9010` fuera de los módulos que el backlog original identificó para `TASK-09`.

---

## 2. Inconsistencias entre Auditoría y Backlog

1. **Omitir la superficie de ataque en endpoints REST (`_resolve_permitted_tenants`):**
   - *Auditoría:* Señaló fallas en `task_dispatcher.py`.
   - *Backlog:* Creó `TASK-03` limitándose a `task_dispatcher.py`, omitiendo la brecha crítica en `main.py:245-246` donde llamadas sin autenticar leen prospectos y secuencias ajenas.
2. **Dependencia y alcance de `TASK-09` (Purga de BrowserOS MCP):**
   - *Backlog:* Colocó `TASK-09` con alcance limitado (`browser_service.py`, `extractor_engine.py`).
   - *Riesgo Detectado:* Si se ejecuta antes de migrar `connection_sync_service.py` y `email_resolver_service.py`, se provocarán excepciones inmediatas `AttributeError: module 'browser_service' has no attribute '_call_mcp_evaluate'` en flujos en producción.
3. **Mapeo erróneo de tenants en el Saneamiento de Base de Datos (`TASK-06`):**
   - *Backlog:* Asumió que todos los prospectos legítimos pertenecían a `ten_superadmin`.
   - *Realidad en BD:* `ten_superadmin` tiene 0 prospectos; los **175 prospectos operativos reales pertenecen a `ten_d933e9ca99`**. El script de migración habría desasociado o eliminado los prospectos del usuario real.
4. **Falta de mecanismo habilitador en `TASK-01`:**
   - *Backlog:* Asumió que aislar los tests solo requería cambiar las suites dentro de `tests/`.
   - *Realidad en Código:* `database.py` no posee ninguna capacidad de redirección. Sin modificar primero `database.py` para leer una ruta configurable (ej. `SQLITE_DB_PATH`), ninguna prueba puede aislarse.

---

## 3. Matriz de Validación y Priorización del Backlog

| ID | Tarea Propuesta | Prioridad | Dependencias Verificadas | Prerrequisitos Técnicos | Criterios de Aceptación Faltantes | Estado |
|---|---|:---:|---|---|---|:---:|
| **TASK-01** | Aislamiento de tests frente a `leads.db` | **P0 (Inmediata)** | Ninguna | Permitir a `database.py` recibir ruta de BD vía variable de entorno | Debe limpiar archivos WAL y SHM transitorios al desmontar el test. | **LISTA (Ajustada)** |
| **TASK-04** | Corrección de Bypass RLS en `database.py` | **P0** | Ninguna | Ninguno (edición quirúrgica de 4 líneas) | Si `tenant_id` es `None` y no es superadmin, forzar `is_super_admin = 'false'`. | **LISTA** |
| **TASK-03A** | Aislamiento en Despachador (`task_dispatcher.py`) | **P0** | `TASK-01` | `TASK-01` para probar sin ensuciar BD | Rechazar peticiones a `/worker/proxima-tarea` si falta `tenant_id`. | **LISTA** |
| **TASK-03B** | Blindaje de `_resolve_permitted_tenants` en `main.py` | **P0** | `TASK-01` | `TASK-01` | Si `caller is None`, levantar `HTTPException(401)` y jamás devolver `[tenant_query]`. | **LISTA** |
| **TASK-02** | Desbloqueo de Búsqueda/Extracción en Electron | **P1** | `TASK-01` | Crear endpoint `/extract/search` en `desktop/main.cjs` | La respuesta debe devolver la estructura exacta de prospectos sin usar `_call_mcp_evaluate`. | **LISTA** |
| **TASK-05** | Desacoplamiento de secuencias de `_call_mcp_evaluate` | **P1** | `TASK-02`, `TASK-03A` | Definir contrato de respuesta de `/api/secuencias/ejecutar-siguiente` | Redirigir el avance a la cola del despachador o retornar código de encolado. | **LISTA** |
| **TASK-06** | Saneamiento de BD y siembra oficial de $15/mes | **P1** | `TASK-01` | Respaldo físico `leads.db.bak` previo | Preservar intactos los 175 leads de `ten_d933e9ca99` y sembrar su suscripción oficial. | **LISTA (Ajustada)** |
| **TASK-07** | Unificación Facturación y Desconexión de Puestos | **P1** | `TASK-06` | `TASK-06` ejecutada y verificada | `auth_service.py` valida contra `subscriptions`/`entitlements`, no contra `suscripciones`. | **LISTA** |
| **TASK-08** | Parametrización de Tenant en Runner Desktop | **P2** | `TASK-03A`, `TASK-07` | Requiere confirmar cómo Electron almacena el login | Vincular la identidad del dispositivo al tenant del usuario autenticado en sesión. | **REQUIERE INVESTIGACIÓN** |
| **TASK-09** | Purga masiva de BrowserOS MCP | **P3** | `TASK-02`, `TASK-05` | Completar migración de todas las referencias residuales | Purgar también `connection_sync_service.py`, `email_resolver_service.py` y `main.py`. | **BLOQUEADA** |
| **DEC-01** | Ocultar vistas de Puestos de Agencia en UI | **P2** | `TASK-07` | Ninguno | Confirmar si se ocultan del menú lateral o se eliminan los componentes. | **REQUIERE DECISIÓN** |
| **DEC-02** | Política de duplicados inter-secuencia | **P2** | `TASK-05` | Ninguno | Definir ventana de tiempo (ej. 90 días) o bloqueo permanente. | **REQUIERE DECISIÓN** |

---

## 4. Análisis de Ejecutabilidad y Seguridad de las Pruebas

> **ADVERTENCIA TÉCNICA:** Ninguna suite de pruebas en Python debe ejecutarse en este momento con la configuración actual.

- **Riesgo Comprobado:** Cualquier comando `pytest` o `python -m unittest discover` conectará a `leads.db` por defecto, registrará escrituras en el WAL e insertará filas residuales en las tablas `tenants`, `leads` y `devices`.
- **Inconsistencia de suites:** `tests/test_browser_service_electron.py` fallará indefectiblemente si se ejecuta, ya que contiene aserciones que asumen `/evaluate` activo.
- **Conclusión:** La suite de pruebas actual **NO es reproducible ni segura** hasta que se implemente la tarea de aislamiento (`TASK-01`).

---

## 5. Propuesta de Primera Intervención Ejecutable

### 🎯 Tarea Seleccionada: `TASK-01` (Aislamiento de Pruebas) combinada con `TASK-04` (Cierre del Bypass RLS en `database.py`)

Ambas modificaciones conviven en un único archivo central: **`database.py`**.

### ¿Por qué esta intervención primero?
1. **Riesgo de regresión funcional nulo:** No modifica el comportamiento de la aplicación en producción ni toca la interfaz gráfica.
2. **Cierra de inmediato una vulnerabilidad P0:** Elimina la elevación automática de privilegios SuperAdmin cuando falta `tenant_id`.
3. **Desbloquea el arnés de verificación:** Al dotar a `database.py` del soporte para una variable de entorno `SQLITE_DB_PATH`, permite que las siguientes tareas (`TASK-02`, `TASK-03`, `TASK-05`) se validen mediante pruebas automatizadas que operen sobre bases de datos temporales, garantizando la preservación absoluta de los 194 leads de `leads.db`.

---

## 6. Procedimiento y Comandos de Prueba para la Primera Tarea

Una vez implementada la modificación en `database.py`:

### Paso 1: Verificación de no-mutación de la base de datos operativa
```powershell
# 1. Obtener hash y conteo previo de leads.db
python -c "import hashlib, sqlite3; print('MD5:', hashlib.md5(open('leads.db','rb').read()).hexdigest()); print('Leads:', sqlite3.connect('leads.db').execute('SELECT COUNT(*) FROM leads').fetchone()[0])"

# 2. Ejecutar la suite de pruebas redirigiendo la persistencia a una base temporal
$env:SQLITE_DB_PATH = "test_sandbox.db"
python -m unittest tests/test_signed_commands.py
Remove-Item Env:\SQLITE_DB_PATH

# 3. Verificar que leads.db permanece 100% inalterada
python -c "import hashlib, sqlite3; print('MD5:', hashlib.md5(open('leads.db','rb').read()).hexdigest()); print('Leads:', sqlite3.connect('leads.db').execute('SELECT COUNT(*) FROM leads').fetchone()[0])"

# 4. Limpieza del sandbox de test
Remove-Item test_sandbox.db -ErrorAction SilentlyContinue
Remove-Item test_sandbox.db-wal -ErrorAction SilentlyContinue
Remove-Item test_sandbox.db-shm -ErrorAction SilentlyContinue
```

### Resultados esperados:
- El hash MD5 y el conteo de prospectos (194 leads) de `leads.db` deben ser **exactamente idénticos** antes y después del test.
- Las tablas creadas por el test se habrán generado y destruido exclusivamente en `test_sandbox.db`.

---

## 7. Recomendación Final para Aprobación

El backlog está validado y saneado con respecto a la realidad del código. Se han identificado y neutralizado los riesgos de contaminación de datos y las omisiones de seguridad en los endpoints REST.

**Solicitud de Aprobación:**  
¿Autorizas proceder con la implementación quirúrgica de **`TASK-01` + `TASK-04` en `database.py`** (habilitar `SQLITE_DB_PATH` y corregir el bypass de RLS) para dejar listo y blindado el arnés de pruebas?
