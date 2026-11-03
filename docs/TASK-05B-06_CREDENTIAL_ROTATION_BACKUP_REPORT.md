# TASK-05B-06 — PostgreSQL Credential Rotation & Backup Foundation
## INFORME TÉCNICO DE SEGURIDAD, ROTACIÓN Y GESTIÓN DE RESPALDOS

- **Proyecto:** NexusReach Pro
- **Ruta del Proyecto:** `C:\Users\gabri\OneDrive\Desktop\Proyectos\Linkedin\`
- **Fecha de Ejecución:** 01 de Noviembre de 2026
- **Responsable:** Antigravity AI Engineering Assistant & DevSecOps Lead
- **Dictamen Final:** **PASS — ROTACIÓN DE SECRETOS Y BASE DE RESPALDOS COMPLETADAS EXITOSAMENTE**

---

## 1. RESUMEN EJECUTIVO

Tras la activación operacional de PostgreSQL 16 reportada en TASK-05B-05, se ejecutó una intervención integral de endurecimiento de seguridad y resiliencia operacional:

1. **Rotación Criptográfica Completa:** Se generaron y aplicaron nuevas credenciales de alta entropía para los roles `nexus_app` y `nexus_admin`, se rotó el secreto criptográfico `SUPERADMIN_RLS_SECRET` (HMAC-SHA256) actualizando la tabla protegida `system_admin_keys`, y se regeneró la contraseña del administrador inicial (`admin@nexusreach.com`) con un nuevo salt criptográfico de 16 bytes y hash PBKDF2-SHA256.
2. **Invalidación Estricta:** Se comprobó de forma automatizada que todas las credenciales y secretos previos quedaron 100% invalidados y son rechazados con `password authentication failed` o `HTTP 401 Unauthorized`.
3. **Mecanismo de Respaldo Lógico Automatizado:** Se implementó y validó el motor de backups en [`scripts/backup_postgres.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/backup_postgres.py), que genera volcados `pg_dump` en formato custom (`-Fc`) directamente en almacenamiento persistente del host (`backups/postgres/`), fuera del contenedor Docker, con una política de retención automática de 7 copias diarias y bitácora estructurada de eventos (`backup_history.log`).
4. **Verificación de Restauración Independiente:** Mediante [`scripts/verify_backup_restoration.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/verify_backup_restoration.py), se aprovisionó una base de datos aislada (`nexusreach_restore_test`) y se restauró el volcado más reciente. Se comprobó que las 37 tablas, esquemas, recuentos de registros, políticas RLS y FORCE RLS (en las 32 tablas multi-tenant) y la autorización de SuperAdmin coinciden con exactitud matemática con `nexusreach_prod`.
5. **Regresión Funcional y Servidor en Vivo:** Toda la suite funcional (`tests/test_credential_rotation_regression_task05b06.py`), las pruebas de activación (`tests/test_production_activation_task05b05.py`), los tests de worker runner de Node.js (`desktop/tests/test_worker_runner_task08.cjs`) y el servidor en vivo Uvicorn (`scratch/validate_live_fastapi_server.py`) operan al 100% bajo el rol no privilegiado `nexus_app`.
6. **Preservación de SQLite:** La base histórica `leads.db` se mantuvo estrictamente intacta en modo lectura (MD5: `6491976477eed4a87595dc0c107beb86`, 1.126.400 bytes, `PRAGMA integrity_check = ok`, 194 leads).

---

## 2. SECRETOS ROTADOS Y GESTIÓN DE CONFIGURACIÓN

En estricto cumplimiento de las políticas de seguridad y la directriz de confidencialidad, **los valores en claro de los secretos nunca se imprimen ni se registran en este informe ni en terminales**:

| Elemento / Rol | Tipo de Secreto | Mecanismo de Generación | Ubicación de Almacenamiento | Estado Previo | Estado Posterior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Rol `nexus_app`** | Contraseña de conexión DB | Alfanumérico criptográfico (32 bytes) | PostgreSQL `pg_authid` & `.env` (`DATABASE_URL`) | Expuesto / Comprometido | **Rotado e Invalidado** |
| **Rol `nexus_admin`** | Contraseña administrativa DB | Alfanumérico criptográfico (32 bytes) | PostgreSQL `pg_authid` & `.env` (`POSTGRES_ADMIN_URL`) | Expuesto / Comprometido | **Rotado e Invalidado** |
| **SuperAdmin Bypass** | Secreto HMAC-SHA256 | Hexadecimal seguro (64 chars) | Hash SHA-256 en `system_admin_keys` & `.env` | Expuesto / Comprometido | **Rotado e Invalidado** |
| **Admin de Aplicación** | Credencial de usuario | Alfanumérico seguro (24 bytes) | Salt 16B + PBKDF2 en `usuarios` & `.env` | Expuesto / Comprometido | **Rotado e Invalidado** |

### 2.1. Sanitización de Inyección de Credenciales
- La ejecución del cambio de contraseñas en PostgreSQL se realizó mediante tuberías binarias / `stdin` hacia `psql`, impidiendo que las contraseñas figuren como argumentos en la tabla de procesos (`ps aux` / Process Explorer) o en el historial de comandos del shell.
- El archivo `.env` fue reescrito de forma atómica y permanece protegido en el entorno local (ignorado por `.gitignore`).

---

## 3. VALIDACIÓN DE INVALIDACIÓN Y ESTADO DE PERMISOS

Se ejecutaron pruebas negativas para confirmar que las credenciales anteriores carecen de acceso:

1. **Intento de conexión con contraseña previa de `nexus_app`:**
   - Resultado: **Rechazado** (`psycopg.OperationalError: password authentication failed for user "nexus_app"`).
2. **Intento de conexión con contraseña previa de `nexus_admin`:**
   - Resultado: **Rechazado** (`psycopg.OperationalError: password authentication failed for user "nexus_admin"`).
3. **Intento de bypass RLS con token SuperAdmin previo:**
   - Resultado: **0 filas devueltas** (Fail-Closed garantizado por `verify_super_admin_context()`).
4. **Intento de login HTTP con contraseña previa de `admin@nexusreach.com`:**
   - Resultado: **HTTP 401 Unauthorized** (`detail: {"exito": false, "mensaje": "Credenciales inválidas"}`).
5. **Estado de Permisos de `nexus_app`:**
   - `usesuper = false`.
   - `rolcreaterole = false`.
   - `rolcreatedb = false`.
   - `CREATE TABLE` (DDL): Denegado (`psycopg.errors.InsufficientPrivilege: permission denied for schema public`).
   - `SELECT * FROM system_admin_keys`: Denegado (`psycopg.errors.InsufficientPrivilege: permission denied for table system_admin_keys`).

---

## 4. MECANISMO DE BACKUP AUTOMÁTICO

### 4.1. Arquitectura y Componentes
El mecanismo fue implementado en [`scripts/backup_postgres.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/backup_postgres.py):
- **Motor de volcado:** `pg_dump` ejecutado en modo custom (`-Fc`).
- **Almacenamiento persistente:** Directorio `backups/postgres/` en el sistema de archivos del host (Windows), fuera del ciclo de vida de los contenedores Docker.
- **Nomenclatura no destructiva:** `nexusreach_prod_backup_YYYYMMDD_HHMMSS.dump`.
- **Validación de integridad:** Comprobación del encabezado mágico `PGDMP` y cálculo de suma criptográfica SHA-256.
- **Política de retención:** Conservación de las **7 copias diarias más recientes**. Los respaldos más antiguos son purgados automáticamente tras cada ejecución exitosa.
- **Bitácora de auditoría:** Cada ejecución registra timestamp ISO, nombre, tamaño, SHA-256, duración en segundos y estado en `backups/postgres/backup_history.log`.
- **Cero contraseñas en código:** Las credenciales se leen exclusivamente desde variables de entorno o `.env`.

### 4.2. Registro Real de Ejecuciones (Bitácora)
```
2026-11-01T21:15:54.046221 | SUCCESS | nexusreach_prod_backup_20261101_211552.dump | 156957 bytes | SHA256:1d20f7e32fa56e5f0c99748eeb2c648017fac628ffe65ab0648e10136ec03a80 | Duracion:1.44s | Ninguno purgado
2026-11-01T21:16:12.196328 | SUCCESS | nexusreach_prod_backup_20261101_211611.dump | 156957 bytes | SHA256:2e2a2a22e13a273d9711f204b0d7cd4fa9e23773e3d1c6f21ec9a918926731b9 | Duracion:0.53s | Ninguno purgado
```

### 4.3. Automatización en Producción
Para programar la ejecución recurrente sin intervención manual:
- **En Windows Server / Desktop:** Configurar una tarea programada en *Task Scheduler* que invoque:
  `python scripts\backup_postgres.py --retention 7` a las 02:00 AM diariamente.
- **En Linux / Docker Host:** Añadir entrada en `crontab`:
  `0 2 * * * cd /ruta/al/proyecto && python3 scripts/backup_postgres.py --retention 7 >> /var/log/nexus_backup_cron.log 2>&1`

---

## 5. EVIDENCIA DE RESTAURACIÓN EN BASE INDEPENDIENTE

La capacidad de recuperación ante desastres fue demostrada mediante [`scripts/verify_backup_restoration.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scripts/verify_backup_restoration.py):

```
================================================================================
VERIFICACIÓN DE RESTAURACIÓN DE BACKUP POSTGRESQL (TASK-05B-06)
================================================================================

[PASO 1] Archivo de backup seleccionado para restauración:
  Ruta: C:\Users\gabri\OneDrive\Desktop\Proyectos\Linkedin\backups\postgres\nexusreach_prod_backup_20261101_211611.dump
  Tamaño: 156,957 bytes

[PASO 2] Capturando estado base de nexusreach_prod...
  [✓] 37 tablas auditadas en nexusreach_prod.

[PASO 3] Creando base de datos independiente 'nexusreach_restore_test'...
  [✓] Base de datos nexusreach_restore_test creada y aprovisionada limpiamente.

[PASO 4] Restaurando volcado mediante pg_restore en 'nexusreach_restore_test'...
  [✓] pg_restore finalizado con éxito (código de salida: 0 ).

[PASO 5] Comparando estructura y registros (nexusreach_prod vs nexusreach_restore_test)...
  [✓] Estructura exacta y recuento idéntico en las 37 tablas.

[PASO 6] Auditando Row-Level Security (RLS) en la base restaurada...
  [✓] Las 32 tablas multi-tenant restauradas conservan RLS=true y FORCE_RLS=true.

[PASO 7] Validando rol de aplicación (nexus_app) en la base restaurada...
  [✓] nexus_app consulta tenant_id='ten_primary' correctamente.
  [✓] Acceso a system_admin_keys denegado a nexus_app (REVOKE preservado).
  [✓] Función verify_super_admin_context() operativa en base restaurada.

[PASO 8] Comprobando que nexusreach_prod se mantuvo inalterada...
  [✓] nexusreach_prod completamente intacta (cero mutaciones).

================================================================================
>>> VERIFICACIÓN DE RESTAURACIÓN COMPLETADA EXITOSAMENTE (PASS) <<<
================================================================================
```

> [!NOTE]
> La restauración se realizó estrictamente sobre la base aislada `nexusreach_restore_test`. En ningún momento se restauró sobre `nexusreach_prod`, y el recuento de filas de todas las tablas de producción se mantuvo idéntico antes y después de la prueba.

---

## 6. PRUEBAS FUNCIONALES Y REGRESIÓN POST-ROTACIÓN

Se ejecutaron múltiples baterías de pruebas para garantizar la estabilidad operativa total:

### 6.1. Suite Específica de Rotación (`tests/test_credential_rotation_regression_task05b06.py`)
- **Prueba 1:** Endpoint `/api/health` 200 OK y confirmación de que FastAPI ejecuta bajo `nexus_app` sin superusuario.
- **Prueba 2:** Autenticación con contraseña rotada exitosa (200 OK) y rechazo inmediato de contraseña previa (401).
- **Prueba 3:** Ingesta de prospecto sintético (`POST /api/prospectos/importar-lote`), consulta con filtros (`GET /api/prospectos`), actualización de contacto (`PUT /api/prospectos/{id}/contacto`) y eliminación física (`DELETE /api/prospectos/{id}` comprobando HTTP 404).
- **Prueba 4:** Aislamiento multi-tenant RLS bidireccional entre Tenant A (`ten_primary`) y Tenant B (`ten_corp_beta_rot`), verificando que las consultas y accesos por ID directo devuelven 404 entre organizaciones.
- **Prueba 5:** Persistencia demostrada a través de reinicio en frío del cliente y purga completa del almacén de sesiones en memoria.
- **Resultado:** **5/5 pruebas APROBADAS (OK en 4.889s)**.

### 6.2. Suite de Producción (`tests/test_production_activation_task05b05.py`)
- Ejecución completa adaptada para consumir dinámicamente las credenciales rotadas desde `.env`.
- **Resultado:** **6/6 pruebas APROBADAS (OK en 5.964s)**.

### 6.3. Validación en Vivo con Servidor Real Uvicorn (`scratch/validate_live_fastapi_server.py`)
- Proceso Uvicorn lanzado en `http://127.0.0.1:8005`.
- Login HTTP real con la nueva contraseña de `admin@nexusreach.com`.
- Confirmación de escritura y persistencia en la tabla `audit_logs` de PostgreSQL.
- Ingesta y eliminación en vivo de prospecto de prueba.
- **Resultado:** **Aprobado con éxito**.

### 6.4. Worker Runner Node.js (`desktop/tests/test_worker_runner_task08.cjs`)
- Verificación estática de ausencia de tenants hardcodeados.
- Validación de firmas criptográficas Ed25519 y rechazo ante alteración de tenants.
- **Resultado:** **7/7 pruebas APROBADAS al 100%**.

---

## 7. PRESERVACIÓN DEL ARCHIVO HISTÓRICO SQLITE

Se auditó el archivo `leads.db` antes y después de todas las pruebas:
- **Ruta:** `c:\Users\gabri\OneDrive\Desktop\Proyectos\Linkedin\leads.db`
- **Tamaño:** `1.126.400 bytes` (inalterado).
- **Hash MD5:** `6491976477eed4a87595dc0c107beb86` (idéntico al de referencia).
- **Integridad Física:** `PRAGMA integrity_check = ok`.
- **Volumetría Preservada:** 194 leads intactos.
- **Conclusión:** No se produjeron lecturas ni escrituras sobre `leads.db`.

---

## 8. ANÁLISIS DE RIESGOS Y LIMITACIONES

1. **Aislamiento de Docker en el Host:** El contenedor `nexusreach_postgres_rls_test` se encuentra enlazado a `127.0.0.1:5432`. No debe exponerse a `0.0.0.0` sin un firewall perimetral y túnel TLS/VPN.
2. **Respaldo Lógico vs. Físico:** El mecanismo actual implementa respaldos lógicos diarios (`pg_dump`). Para entornos de producción de misión crítica con grandes volúmenes transaccionales (RPO < 15 minutos), se recomienda complementar esta base con el archivo continuo de WALs (Point-In-Time Recovery - PITR).
3. **Almacenamiento de Backups Offsite:** Actualmente los archivos `.dump` se almacenan localmente en `backups/postgres/`. Se recomienda sincronizar este directorio con un bucket de almacenamiento seguro en la nube (AWS S3, Google Cloud Storage o Azure Blob) con cifrado en reposo (KMS) y versionado inmutable.

---

## 9. DICTAMEN FINAL

### Dictamen
**PASS — ROTACIÓN DE SECRETOS Y BASE DE RESPALDOS COMPLETADAS EXITOSAMENTE**

NexusReach Pro continúa operando con total normalidad sobre PostgreSQL 16 (`nexusreach_prod`). El sistema cuenta ahora con credenciales completamente renovadas y seguras, las credenciales previas han sido invalidadas en su totalidad, los permisos de mínimo privilegio permanecen inalterados, y se ha establecido y demostrado un mecanismo reproducible de respaldo lógico y restauración integral.

