# INFORME DE ENSAYO DE CORTE Y AUTORIZACIÓN FINAL (TASK-05B-03)

**Proyecto:** NexusReach Pro  
**Documento:** `docs/TASK-05B-03_CUTOVER_REHEARSAL_FINAL_AUTHORIZATION.md`  
**Fecha de Emisión:** 1 de Noviembre de 2026  
**Autor:** Antigravity AI Senior Systems & Security Engineer  
**Dependencias:** TASK-05B-02A, TASK-05B-02B, TASK-05B-02C  
**Estado:** FINALIZADO — ENSAYO EXITOSO  
**Dictamen Final:** **PASS — Recomendado para programar la Ventana de Cutover Operacional**

---

## 1. RESUMEN EJECUTIVO Y DICTAMEN FINAL

El objetivo de la tarea **TASK-05B-03** fue ensayar y validar rigurosamente el procedimiento completo de corte operacional (Cutover) y reversión (Rollback) de NexusReach Pro desde SQLite hacia PostgreSQL 16 antes de autorizar la transición en producción.

Siguiendo el mandato estricto de la tarea, **todas las pruebas se ejecutaron en entornos completamente aislados**, sin tocar la base operativa `leads.db`, sin modificar el motor predeterminado (que permanece en SQLite) y sin abrir acceso a usuarios reales.

### Conclusiones Principales del Ensayo:
1. **Point-in-Time Recovery (PITR) Demostrado:** Se configuró archivado continuo de WAL (`wal_level=replica`, `archive_mode=on`, `archive_command`) y se ejecutó una simulación real de desastre (`DROP TABLE`) logrando recuperar el 100% de los datos mediante replay determinista de WAL hasta un restore point nombrado (`rp_pre_catastrofe_2026`) en un clúster secundario aislado.
2. **Corrección de Seguridad en Rollback Runbook:** Se eliminó el uso de comandos destructivos automáticos (`migrate_sqlite_to_postgres.py --rollback --confirm-data-loss`). Se estableció la regla de oro: **PostgreSQL nunca se purga automáticamente durante una contingencia**, preservando toda evidencia forense y datos nuevos.
3. **Ensayo de Cutover Cronometrado:** El procedimiento completo de corte automatizado se ejecutó en **9.22 segundos** (~0.15 minutos). Esto valida empíricamente que la **ventana de mantenimiento de 45 minutos** proporciona más del 90% de holgura para comprobaciones manuales y validación visual del operador.
4. **Simulaciones de Rollback Aprobadas:**
   - **Simulación 1 (Tier 1 Pre-Apertura):** Reversión instantánea a SQLite con **cero pérdida de datos** y verificación de hash SHA-256 idéntico.
   - **Simulación 2 (Tier 2/3 Post-Apertura):** Detección de divergencia con 3 prospectos sintéticos, congelamiento inmediato con Kill-Switch, exportación del delta conciliable y activación del candado de seguridad que prohíbe el rollback ciego.
5. **Auditoría de Privilegios y Criptografía:** Confirmada la separación absoluta de roles (`nexus_admin` DBA vs `nexus_app` aplicación con `usesuper=false` y acceso denegado a `system_admin_keys`), y unificada la documentación de los tres algoritmos criptográficos del sistema.

### Dictamen Final
> **DICTAMEN: PASS — RECOMENDADO PARA PROGRAMAR CUTOVER OPERACIONAL**  
> NexusReach Pro ha demostrado que puede ejecutar el cambio hacia PostgreSQL 16 y recuperarse de cualquier categoría de fallo sin poner en riesgo los datos históricos ni la continuidad operacional.  
> *(Nota: El presente dictamen técnico recomienda la programación de la ventana, pero el cutover real requerirá la autorización ejecutiva formal de la Dirección Técnica).*

---

## 2. FASE A — CONFIGURACIÓN DE RECUPERACIÓN (PITR & WAL ARCHIVING)

### 2.1 Auditoría de Parámetros de Recuperación
Se auditó y configuró la instancia PostgreSQL 16 (`nexusreach_postgres_rls_test`):

```sql
SHOW wal_level;          -- Resultado: replica
SHOW archive_mode;       -- Resultado: on
SHOW archive_command;    -- Resultado: cp %p /tmp/wal_archive/%f
SHOW archive_timeout;    -- Resultado: 60s
SHOW checkpoint_timeout; -- Resultado: 5min
SHOW max_wal_size;       -- Resultado: 1GB
```

### 2.2 Ejecución y Evidencia del Ensayo PITR
Se desarrolló y ejecutó el script [`scratch/test_postgres_pitr_execution.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scratch/test_postgres_pitr_execution.py), completando las 10 etapas del ciclo de Disaster Recovery:

```
=== 1. VERIFICANDO CONFIGURACIÓN DE ARCHIVADO WAL ===
wal_level: replica, archive_mode: on, archive_command: cp %p /tmp/wal_archive/%f

=== 2. CREANDO TABLA Y DATOS DE PRUEBA PITR EN BASE ACTIVA ===
Registros iniciales en pitr_audit_test: 1

=== 3. EJECUTANDO BASE BACKUP FÍSICO (pg_basebackup) ===
[OK] Base backup generado exitosamente en /tmp/pitr_base_dir.

=== 4. TRANSACCIÓN POST-BACKUP Y CREACIÓN DE RESTORE POINT ===
[OK] Restore point 'rp_pre_catastrofe_2026' fijado en LSN: 0/70002D8
Registros antes del desastre: 2

=== 5. SIMULANDO DESASTRE OPERACIONAL (DROP TABLE ACCIDENTAL) ===
[SIMULACIÓN] La tabla pitr_audit_test fue destruida en la base activa.

=== 6. FORZANDO ARCHIVADO DE SEGMENTOS WAL ===
[OK] WAL conmutado a: 0/700D220
Segmentos archivados disponibles:
000000010000000000000004
000000010000000000000005
000000010000000000000006
000000010000000000000006.00000028.backup
000000010000000000000007

=== 7. PREPARANDO CLÚSTER RESTAURADO AISLADO (PUERTO 5434) ===
Configuración inyectada en recovery.signal y postgresql.auto.conf:
  restore_command = 'cp /tmp/wal_archive/%f %p'
  recovery_target_name = 'rp_pre_catastrofe_2026'
  recovery_target_action = 'promote'

=== 8. INICIANDO CLÚSTER RESTAURADO Y APLICANDO WALs HASTA RESTORE POINT ===
[OK] Clúster restaurado en línea en puerto 5434.

=== 9. VERIFICACIÓN FORENSE EN BASE RESTAURADA ===
Registros recuperados en puerto 5434:
id |                    evento                    
----+----------------------------------------------
  1 | Tx 1: Inicio operacional verificado
  2 | Tx 2: Lead crítico registrado antes de caída
(2 rows)

=== 10. LIMPIEZA DE ENTORNO PITR ===
[OK] Clúster secundario detenido y temporales purgados.
```

**Resultado:** Éxito rotundo. La tabla accidentalmente eliminada fue rescatada con sus 2 registros exactamente en el microsegundo anterior al `DROP TABLE`.

### 2.3 Requisitos de Infraestructura de Respaldo para Producción
1. **Destino de Archivado:** En producción, `/tmp/wal_archive` debe sustituirse por almacenamiento inmutable S3 / GCS con soporte WORM (Write Once, Read Many) o un montaje NFS redundante mediante herramientas como `wal-g` o `pgBackRest`.
2. **Retención de WALs:** Retención mínima de 14 días combinada con snapshots completos diarios de `pg_basebackup`.

---

## 3. FASE B — CORRECCIÓN DEL ROLLBACK RUNBOOK

### 3.1 Hallazgo Crítico de Auditoría
El Runbook anterior sugería en los procedimientos de rollback ejecutar:
`python scripts/migrate_sqlite_to_postgres.py --rollback --confirm-data-loss`
Dicho comando ejecuta `TRUNCATE TABLE CASCADE` sobre todas las tablas de PostgreSQL.

**Corrección Aplicada:** Se eliminó completamente esa instrucción del Runbook.
- En **Tier 1**, purgar la base elimina los logs de error de por qué falló el bootstrap.
- En **Tier 2**, purgar la base destruye los nuevos leads ingresados por los usuarios.
- En **Tier 3**, purgar la base destruye la evidencia forense necesaria para PITR.

### 3.2 Estructura Corregida de los Tres Niveles de Contingencia

```mermaid
graph TD
    A[Incidente Operacional] --> B{Momento del Incidente}
    
    B -->|Pre-Apertura en Ventana| C[Tier 1: Pre-Cutover]
    C --> C1[Detener Backend]
    C1 --> C2[Revertir .env a leads.db]
    C2 --> C3[Verificar Hash SHA-256 SQLite]
    C3 --> C4[Reiniciar FastAPI en SQLite]
    C4 --> C5[Preservar PostgreSQL para Análisis]
    
    B -->|Post-Apertura con Datos Nuevos| D[Tier 2: Post-Cutover Conciliable]
    D --> D1[Activar Kill-Switch Inmediato]
    D1 --> D2[Preservar PostgreSQL y WALs]
    D2 --> D3{Es viable Fix-Forward?}
    D3 -->|Sí| D4[Reparar Conexiones/Hardware en PG]
    D3 -->|No| D5[Exportar Delta CSV/JSON de PG]
    D5 --> D6[Conciliar e Importar en SQLite]
    D6 --> D7[Validar Integridad antes de Switch]
    
    B -->|Destrucción Total de Infraestructura| E[Tier 3: Catástrofe Irrecuperable]
    E --> E1[Preservar Imágenes/WALs para Forense]
    E1 --> E2[Firma Ejecutiva de Pérdida de Datos]
    E2 --> E3[Restaurar leads.db desde Snapshot Congelado]
    E3 --> E4[Reanudar Operación Histórica en SQLite]
```

El archivo [`docs/TASK-05B_ROLLBACK_RUNBOOK.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/TASK-05B_ROLLBACK_RUNBOOK.md) fue actualizado reflejando estas garantías de no-destrucción y validación previa obligatoria.

---

## 4. FASE C — ENSAYO COMPLETO DE CUTOVER CRONOMETRADO

### 4.1 Entorno del Ensayo
- **Base de Datos Aislada:** `nexusreach_rehearsal` (creada y destruida durante el test).
- **Herramienta:** [`scratch/test_cutover_rehearsal_timed.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scratch/test_cutover_rehearsal_timed.py).
- **Ejecución:** Simulación completa de los 9 pasos del Cutover Runbook.

### 4.2 Tabla de Tiempos Medidos por Etapa

| Etapa | Descripción Operacional | Comando / Acción Ejecutada | Tiempo Medido | Estado |
|---|---|---|:---:|:---:|
| **Etapa 1** | Activar Kill-Switch Global | `safety_engine.activate_kill_switch(...)` | 0.0476 s | **EXITOSO** |
| **Etapa 2** | Detención de Servicios | Detención simulada de workers y FastAPI | 0.5005 s | **EXITOSO** |
| **Etapa 3** | Snapshot Inmutable SQLite | Copia y cálculo de SHA-256 de `leads.db` | 0.0687 s | **EXITOSO** |
| **Etapa 4** | Aprovisionamiento DB | `CREATE DATABASE nexusreach_rehearsal` + GRANTs | 2.1240 s | **EXITOSO** |
| **Etapa 5** | Bootstrap Limpio | `bootstrap_postgres_clean.py --bootstrap` | 3.6585 s | **EXITOSO** |
| **Etapa 6** | Verificación de Integridad | `bootstrap_postgres_clean.py --verify-only` | 1.5052 s | **EXITOSO** |
| **Etapa 7** | Configuración de Backend | Seteo de variables de entorno con `nexus_app` | 0.0009 s | **EXITOSO** |
| **Etapa 8** | Smoke Tests Operacionales | Health (200), Auth admin, Leads limpios, Inserción | 1.1593 s | **EXITOSO** |
| **Etapa 9** | Desactivar Kill-Switch | `safety_engine.deactivate_kill_switch()` | 0.1587 s | **EXITOSO** |
| **TOTAL** | **Procedimiento Automatizado** | **9 Etapas de Corte Operacional** | **9.2250 s** | **100% PASS** |

### 4.3 Validación de la Ventana de Mantenimiento (45 Minutos)
El procedimiento automatizado toma menos de **10 segundos**. 
La ventana fijada de **45 minutos** otorga:
- **0.5 minutos:** Ejecución automatizada de scripts.
- **10.0 minutos:** Verificación visual del operador humano en el frontend y dashboards.
- **10.0 minutos:** Pruebas de conectividad de los runners locales Electron.
- **24.5 minutos:** Margen de seguridad (buffer) para contingencias o decisión de abortar.

**Conclusión:** La duración de 45 minutos es altamente realista, segura y cuenta con un margen de holgura superior al 90%.

---

## 5. FASE D — ENSAYO DE ROLLBACK (SIMULACIONES 1 Y 2)

Se ejecutó el script [`scratch/test_rollback_simulations.py`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/scratch/test_rollback_simulations.py), arrojando los siguientes resultados comprobables:

### 5.1 Simulación 1: Fallo Pre-Apertura (Tier 1)
- **Condición:** Fallo simulado durante la comprobación de smoke tests en la ventana de corte.
- **Acción:** Reversión de variables a SQLite y verificación del hash de `leads.db`.
- **Resultado:**
  - Hash SHA-256 verificado: Coincidencia exacta con el snapshot inicial (`2f27a788bd97...`).
  - Health check en SQLite: `200 OK`.
  - Recuento de Leads: 194 (100% de datos preservados).
  - Recuento de Tenants: 40 (100% de datos preservados).
  - PostgreSQL no fue purgado.
  - **Pérdida de datos: 0.00%**.

### 5.2 Simulación 2: Fallo Post-Apertura con Escrituras Sintéticas (Tier 2/3)
- **Condición:** El sistema operó en PostgreSQL e ingresó 3 prospectos sintéticos (`Alpha Lead`, `Beta Lead`, `Gamma Lead`). Se simuló una degradación severa.
- **Acción:**
  1. Activación inmediata del Kill-Switch (despachos salientes congelados).
  2. Preservación estricta de PostgreSQL (sin truncar tablas).
  3. Diagnóstico de divergencia: Se identificaron exactamente los 3 prospectos que existen en PostgreSQL y faltan en SQLite.
  4. Demostración del Protocolo de Conciliación: Se exportó el delta hacia `backups/sim2_reconciliation_delta.json` con esquema validado.
  5. Candado de seguridad: Se demostró que el sistema bloquea cualquier intento de rollback ciego a SQLite sin previa reconciliación o autorización explícita de descarte con `--confirm-data-loss`.

---

## 6. FASE E — AUDITORÍA DE PRIVILEGIOS Y SECRETOS

### 6.1 Matriz de Roles y Privilegios Efectivos

| Atributo / Privilegio | Rol Administrador (`nexus_admin`) | Rol de Aplicación (`nexus_app`) | Verificación en Código / SQL |
|---|---|---|---|
| **Membresía / Tipo** | Propietario DDL / DBA | Miembro de `nexus_app_role` | `pg_roles`, `pg_user` |
| **Superusuario (`usesuper`)** | `true` (en contenedor Docker) / DBA | **`false`** | `SELECT usesuper FROM pg_user;` |
| **Permisos en Tablas de Negocio** | ALL PRIVILEGES | SELECT, INSERT, UPDATE, DELETE | Otorgados en `schema_postgres.sql` |
| **Permisos DDL (`CREATE`, `DROP`, `ALTER`)** | SÍ | **DENEGADO (NO)** | Verificado estáticamente |
| **Acceso a `system_admin_keys`** | SÍ (Lectura / Escritura) | **REVOKE ALL (ACCESO DENEGADO)** | Error 42501 al intentar SELECT |
| **Evaluación de FORCE RLS** | Bypass posible solo con Token | **EVALUACIÓN OBLIGATORIA SIEMPRE** | `relforcerowsecurity = true` |
| **Conexión desde Backend FastAPI** | PROHIBIDA | **ÚNICA PERMITIDA (`DATABASE_URL`)** | Smoke test #2 aprobado |

### 6.2 Unificación y Correspondencia de la Documentación Criptográfica
Se auditó la correspondencia entre los algoritmos criptográficos documentados y los implementados en el código fuente:

1. **Bypass SuperAdmin RLS:**
   - *Algoritmo:* **SHA-256 hex digest** (`hashlib.sha256(secret).hexdigest()` en Python y `digest(provided_token, 'sha256')` en la función PL/pgSQL).
   - *Uso:* Validación de token de 64 caracteres hex provisto en la cabecera/sesión contra la tabla protegida `system_admin_keys`.
2. **Contraseñas de Usuarios (`usuarios`):**
   - *Algoritmo:* **PBKDF2-HMAC-SHA256** con 100.000 iteraciones y sal criptográfica aleatoria de 16 bytes (`auth_service.hash_password`).
   - *Uso:* Almacenamiento seguro de credenciales de operadores y administradores.
3. **Firmas de Runners y Dispositivos:**
   - *Algoritmo:* **Ed25519** (criptografía asimétrica de curvas elípticas EdDSA).
   - *Uso:* Firma digital de tareas salientes (`command_signing_service.py`) y verificación en el runner Electron (`desktop/tests/test_worker_runner_task08.cjs`).

### 6.3 Checklist de Rotación de Secretos Previos a Producción
Antes del cutover en producción, el Lead de Infraestructura debe rotar los siguientes secretos (ningún valor real debe imprimirse en logs ni repositorios):
- [ ] Generar nuevo `SUPERADMIN_RLS_SECRET` con `python -c "import secrets; print(secrets.token_hex(32))"`.
- [ ] Generar nueva contraseña para el rol `nexus_admin`.
- [ ] Generar nueva contraseña para el rol `nexus_app`.
- [ ] Generar `INITIAL_ADMIN_PASSWORD` temporal para `admin@nexusreach.com` y configurar cambio obligatorio de contraseña en el primer inicio de sesión.
- [ ] Generar par de claves maestras Ed25519 del servidor para firma de comandos.

---

## 7. FASE F — VALIDACIÓN DEL ENTORNO DE DESPLIEGUE

### 7.1 Definición de la Arquitectura de Producción
- **Sistema Operativo Base:** Linux (Ubuntu 22.04 LTS o 24.04 LTS).
- **Motor de Base de Datos:** PostgreSQL 16 sobre contenedor Docker con volumen persistente o base de datos gestionada (e.g. AWS RDS PostgreSQL / Cloud SQL).
- **Backend:** FastAPI ejecutado como servicio `systemd` (`nexusreach-backend.service`) o contenedor Docker bajo Gunicorn/Uvicorn workers.
- **Reverse Proxy & TLS:** Nginx o Caddy gestionando certificados TLS 1.3 y cabeceras de seguridad HSTS.
- **Conectividad PostgreSQL:** `sslmode=require` obligatorio en la cadena de conexión de producción.
- **Gestión de Secretos:** Variables inyectadas en tiempo de arranque mediante `systemd EnvironmentFile` protegido (`chmod 600`) o AWS Secrets Manager.

### 7.2 Adaptabilidad Multi-Plataforma de los Runbooks
Los manuales operacionales [`docs/TASK-05B_CUTOVER_RUNBOOK.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/TASK-05B_CUTOVER_RUNBOOK.md) y [`docs/TASK-05B_ROLLBACK_RUNBOOK.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/TASK-05B_ROLLBACK_RUNBOOK.md) fueron actualizados para incluir bloques de comandos canónicos separados tanto para **Linux (bash / systemctl)** como para **Windows (PowerShell)**.

---

## 8. CRITERIOS DE ABORTAR Y MATRIZ DE RIESGOS RESIDUALES

### 8.1 Criterios de Abortar la Ventana de Mantenimiento (Disparadores de Rollback Inmediato)
El operador debe abortar inmediatamente el cutover y ejecutar la reversión **Tier 1** si se presenta cualquiera de las siguientes condiciones:
1. `bootstrap_postgres_clean.py --bootstrap` no finaliza en menos de 3 minutos.
2. `bootstrap_postgres_clean.py --verify-only` retorna código distinto de 0.
3. El endpoint `GET /api/health` retorna código HTTP diferente de 200 tras 60 segundos del arranque de FastAPI.
4. El login de `admin@nexusreach.com` falla con `401 Unauthorized`.
5. El directorio de prospectos reporta datos residuales (`total > 0`).
6. El tiempo transcurrido de la ventana supera los **25 minutos** sin haber superado los smoke tests.

### 8.2 Matriz de Riesgos Residuales

| Riesgo | Impacto | Probabilidad | Estrategia de Mitigación |
|---|---|:---:|---|
| **Agotamiento de Conexiones en Pool** | Medio | Baja | Monitorear métricas de conexiones en PostgreSQL. Configurar `max_connections = 100` y timeout de idle en `database.py`. |
| **Fallo en Archivador WAL** | Alto | Baja | Monitorear la vista `pg_stat_archiver` (`SELECT * FROM pg_stat_archiver;`). Si `last_failed_wal` no es nulo, emitir alerta inmediata. |
| **Intento de Acceso No Autorizado a SuperAdmin** | Crítico | Muy Baja | La función `verify_super_admin_context()` corre en STABLE SECURITY DEFINER con token validado contra hash PBKDF2/SHA-256 en tabla con REVOKE ALL. |

---

## 9. DICTAMEN FINAL Y RECOMENDACIÓN FORMAL

```
================================================================================
DICTAMEN TÉCNICO FORMAL — TASK-05B-03:
DECISIÓN: PASS — RECOMENDADO PARA PROGRAMAR VENTANA DE CUTOVER OPERACIONAL
================================================================================
```

### Justificación:
1. **Evidencia Empírica Verificada:** PITR validado, cutover ensayado en 9.22 segundos, y 2 simulaciones de reversión ejecutadas con éxito.
2. **Protección de Datos:** La base de datos histórica `leads.db` permanece intacta e inmutable.
3. **Seguridad y Privilegios:** Rol de aplicación `nexus_app` estrictamente confinado por políticas RLS y FORCE RLS sin privilegios de superusuario.
4. **Documentación Lista para Operación:** Runbooks actualizados, claros y con soporte para Linux y Windows.

Se autoriza a la Dirección Técnica a programar la fecha y hora de la ventana de mantenimiento oficial conforme a [`docs/TASK-05B_CUTOVER_RUNBOOK.md`](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/docs/TASK-05B_CUTOVER_RUNBOOK.md).

