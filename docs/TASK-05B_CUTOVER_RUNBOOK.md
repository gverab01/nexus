# RUNBOOK DE CORTE OPERACIONAL (CUTOVER RUNBOOK) — TASK-05B-03

**Proyecto:** NexusReach Pro  
**Documento:** `docs/TASK-05B_CUTOVER_RUNBOOK.md`  
**Versión:** 2.0 (Auditoría Post-Rehearsal TASK-05B-03)  
**Estrategia:** Inicialización Operacional Limpia (Clean Bootstrap sin migración de datos históricos)  
**Entorno de Aplicación:** Producción (Linux Ubuntu 22.04/24.04 LTS con Docker / Systemd o Windows Server)  
**Autorización Requerida:** Aprobación explícita de Dirección Técnica / Lead de Infraestructura tras revisión de `TASK-05B-03_CUTOVER_REHEARSAL_FINAL_AUTHORIZATION.md`.

---

## 1. PRINCIPIO Y CAMBIO ESTRATÉGICO

> **[IMPORTANTE - DECISIÓN TÉCNICA APROBADA]**  
> Se **DESCARTA DEFINITIVAMENTE** la importación de prospectos, historiales, interacciones y auditorías históricas desde SQLite.  
> PostgreSQL se inicializará como una **base de datos completamente limpia**, conteniendo exclusivamente:
> - Esquema completo (37 tablas con Row-Level Security y FORCE RLS activas en las 32 tablas multi-tenant).
> - Roles de mínimos privilegios (`nexus_admin` para DDL/mantenimiento, `nexus_app` para conexiones del backend FastAPI).
> - Mecanismo de autorización SuperAdmin criptográfico (`verify_super_admin_context()` y `system_admin_keys`).
> - Un tenant inicial (`ten_primary`).
> - Un usuario administrador inicial (`admin@nexusreach.com`) con credenciales seguras PBKDF2-HMAC-SHA256.
> - Parámetros de seguridad del sistema en `configuracion_seguridad`.
>
> La base SQLite `leads.db` se conservará como **archivo de respaldo histórico inmutable de solo lectura**. La información operacional se reconstruirá progresivamente mediante las funciones nativas de prospección, búsqueda y enriquecimiento de la plataforma.

---

## 2. PRE-REQUISITOS Y VERIFICACIÓN PREVIA (T - 2 Horas)

1. **Instancia PostgreSQL 16+ Verificada**:
   - PostgreSQL 16+ accesible en red privada aislada (sin exposición pública en 0.0.0.0).
   - Base de datos vacía aprovisionada (`nexusreach_prod`).
   - Binarios de PostgreSQL/Docker accesibles en el sistema.
2. **Configuración de Point-in-Time Recovery (PITR) y WAL Archiving**:
   - Confirmar parámetros en `postgresql.conf` / `postgresql.auto.conf`:
     ```ini
     wal_level = replica
     archive_mode = on
     archive_command = 'cp %p /var/lib/postgresql/wal_archive/%f'  # O comando WAL-G / S3
     archive_timeout = 60s
     ```
   - Directorio de archivado `/var/lib/postgresql/wal_archive` aprovisionado en volumen persistente o almacenamiento secundario.
3. **Generación Segura de Secretos de Producción**:
   - `SUPERADMIN_RLS_SECRET`: Token de 64 caracteres hex criptográficos generado con `secrets.token_hex(32)`. Validado en PostgreSQL mediante hash SHA-256 en `system_admin_keys`.
   - `INITIAL_ADMIN_PASSWORD`: Contraseña de alta entropía (mínimo 16 caracteres, mayúsculas, minúsculas, números y símbolos). Hash almacenado con PBKDF2-HMAC-SHA256 (100.000 iteraciones y sal aleatoria).
   - `POSTGRES_APP_PASSWORD` y `POSTGRES_ADMIN_PASSWORD`: Contraseñas independientes de alta seguridad para `nexus_app` y `nexus_admin`.
4. **Verificación de Invarianza de `leads.db`**:
   - Verificar integridad de la base SQLite antes de congelar:
     ```bash
     python -c "import sqlite3; conn = sqlite3.connect('leads.db'); print(conn.execute('PRAGMA integrity_check;').fetchone()[0])"
     ```
     *Criterio:* Debe retornar `ok`.
5. **Disponibilidad de Scripts y Suites**:
   - `scripts/bootstrap_postgres_clean.py`.
   - Suite de smoke tests `tests/test_fastapi_http_postgres_task05b02c.py`.

---

## 3. VENTANA DE CORTE Y TIEMPOS EMPÍRICOS MEDIDOS

En el ensayo cronometrado oficial (TASK-05B-03), el tiempo total de ejecución automatizada fue de **9.22 segundos** (~0.15 minutos).

La ventana de mantenimiento se fija formalmente en **45 MINUTOS**, lo que proporciona un margen de seguridad de más del **90% de holgura** para absorber comprobaciones visuales del operador, validaciones de red, confirmaciones de health checks y decisiones de corte/reversión sin presión de tiempo.

```
[T-00:00] INICIO VENTANA DE MANTENIMIENTO
   │
   ├─► 1. Notificación a Usuarios / Activar Banner de Mantenimiento (1 min)
   │
   ├─► 2. Activar Kill-Switch Global (/api/seguridad/kill-switch/activar) (30 seg)
   │
   ├─► 3. Detener Runners Locales (Electron desktop/worker_runner.cjs) (1 min)
   │
   ├─► 4. Detener Servidor FastAPI (uvicorn main:app / systemctl stop) (30 seg)
   │
   ├─► 5. Archivar y Congelar leads.db (Snapshot inmutable con SHA-256 de solo lectura) (1 min)
   │
   ├─► 6. Ejecutar Bootstrap Limpio de PostgreSQL (bootstrap_postgres_clean.py --bootstrap) (2 min)
   │
   ├─► 7. Ejecutar Verificación Exhaustiva (bootstrap_postgres_clean.py --verify-only) (1 min)
   │
   ├─► 8. Configurar Variables de Entorno de Producción (DB_ENGINE=postgres con nexus_app) (1 min)
   │
   ├─► 9. Iniciar FastAPI y Ejecutar Smoke Tests (Salud, Login, RLS, Dispatcher) (5 min)
   │
   ├─► 10. Validación Visual del Operador en Frontend / Dashboard (10 min)
   │
   ├─► 11. Desactivar Kill-Switch y Habilitar Acceso Administrativo (1 min)
   │
[T+00:45] FIN VENTANA — PLATAFORMA OPERATIVA EN POSTGRESQL LIMPIO
```

---

## 4. PROCEDIMIENTO PASO A PASO POR ENTORNO

### Paso 1: Activar Kill-Switch y Detener Tráfico Saliente
1. Activar kill-switch global para congelar inmediatamente todas las tareas salientes y runners:
   ```bash
   curl -X POST "http://localhost:8000/api/seguridad/kill-switch/activar?motivo=Ventana+de+Cutover+PostgreSQL+Limpio" \
        -H "Authorization: Bearer <ADMIN_SESSION_TOKEN>"
   ```
2. Detener los runners Electron en los puestos comerciales.

### Paso 2: Detener FastAPI y Congelar `leads.db`

#### En Linux (Ubuntu / Debian):
```bash
# 1. Detener el servicio backend
sudo systemctl stop nexusreach-backend

# 2. Generar snapshot inmutable con SHA-256
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_DIR="backups/historical_sqlite_$TIMESTAMP"
mkdir -p "$ARCHIVE_DIR"
cp leads.db "$ARCHIVE_DIR/leads.db"
sha256sum "$ARCHIVE_DIR/leads.db" | awk '{print $1}' > "$ARCHIVE_DIR/leads.db.sha256"
chmod 444 "$ARCHIVE_DIR/leads.db"
echo "Archivo histórico congelado exitosamente en: $ARCHIVE_DIR/leads.db"
```

#### En Windows (PowerShell):
```powershell
# 1. Detener el servicio o proceso Uvicorn
Stop-Process -Name "python" -ErrorAction SilentlyContinue

# 2. Generar snapshot inmutable con SHA-256
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$ARCHIVE_DIR = "backups/historical_sqlite_$TIMESTAMP"
New-Item -ItemType Directory -Path $ARCHIVE_DIR -Force
Copy-Item "leads.db" "$ARCHIVE_DIR/leads.db"
$HASH = (Get-FileHash "$ARCHIVE_DIR/leads.db" -Algorithm SHA256).Hash
$HASH | Out-File "$ARCHIVE_DIR/leads.db.sha256"
Set-ItemProperty "$ARCHIVE_DIR/leads.db" -Name IsReadOnly -Value $true
Write-Host "Archivo histórico congelado exitosamente en: $ARCHIVE_DIR/leads.db (SHA256: $HASH)"
```

### Paso 3: Ejecutar Bootstrap Limpio en PostgreSQL

#### En Linux (bash):
```bash
export TARGET_DATABASE_URL="postgresql://nexus_admin:<admin_password>@<pg_host>:5432/nexusreach_prod"
export SUPERADMIN_RLS_SECRET="<secreto_criptografico_64_chars>"
export INITIAL_ADMIN_PASSWORD="<password_segura_admin>"

# Ejecutar inicialización limpia
python3 scripts/bootstrap_postgres_clean.py --bootstrap

# Ejecutar verificación de integridad limpia
python3 scripts/bootstrap_postgres_clean.py --verify-only
```

#### En Windows (PowerShell):
```powershell
$env:TARGET_DATABASE_URL = "postgresql://nexus_admin:<admin_password>@<pg_host>:5432/nexusreach_prod"
$env:SUPERADMIN_RLS_SECRET = "<secreto_criptografico_64_chars>"
$env:INITIAL_ADMIN_PASSWORD = "<password_segura_admin>"

# Ejecutar inicialización limpia
python scripts/bootstrap_postgres_clean.py --bootstrap

# Ejecutar verificación de integridad limpia
python scripts/bootstrap_postgres_clean.py --verify-only
```
*Criterio de Aprobación:* Código de salida `0`, exactamente 1 tenant (`ten_primary`), exactamente 1 admin (`admin@nexusreach.com`), 0 leads, 0 listas y 0 secuencias históricas.

### Paso 4: Configurar Backend bajo Rol No Privilegiado `nexus_app`
En el archivo `.env` o gestor de secretos de producción (AWS Secrets Manager / HashiCorp Vault):
```ini
DB_ENGINE=postgres
DATABASE_URL=postgresql://nexus_app:<app_secure_password>@<pg_host>:5432/nexusreach_prod
SUPERADMIN_RLS_SECRET=<secreto_criptografico_64_chars>
ENV=production
```
> **[REGLA DE SEGURIDAD ESTRICTA]**  
> `DATABASE_URL` debe utilizar obligatoriamente el usuario de aplicación `nexus_app`, NUNCA `nexus_admin`. Esto garantiza que todas las políticas RLS y FORCE RLS se evalúen obligatoriamente en cada consulta y previene que el backend realice alteraciones DDL o acceda a `system_admin_keys`.

### Paso 5: Iniciar Backend y Smoke Tests

#### En Linux:
```bash
sudo systemctl start nexusreach-backend
python3 -m unittest tests/test_fastapi_http_postgres_task05b02c.py
```

#### En Windows:
```powershell
python -m unittest tests/test_fastapi_http_postgres_task05b02c.py
```

Comprobar manualmente los 4 puntos de control operacional:
1. `GET /api/health` -> `200 OK` (`"status": "healthy"`).
2. `POST /api/auth/login` con `admin@nexusreach.com` y la contraseña inicial -> `200 OK` con sesión válida.
3. `GET /api/prospectos` -> Retorna `{"leads": [], "total": 0}` (Limpio).
4. Crear un prospecto de prueba, verificar persistencia y confirmar aislamiento RLS.

### Paso 6: Reanudar Operaciones Normales
1. Desactivar el Kill-Switch:
   ```bash
   curl -X POST "http://localhost:8000/api/seguridad/kill-switch/desactivar" \
        -H "Authorization: Bearer <ADMIN_SESSION_TOKEN>"
   ```
2. Reanudar runners Electron en los puestos comerciales.
3. Notificar a los operadores comerciales que la plataforma está disponible en PostgreSQL.
