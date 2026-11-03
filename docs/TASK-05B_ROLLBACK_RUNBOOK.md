# PROTOCOLO DE REVERSIÓN Y CONTINGENCIA OPERACIONAL (ROLLBACK RUNBOOK) — TASK-05B-03

**Proyecto:** NexusReach Pro  
**Documento:** `docs/TASK-05B_ROLLBACK_RUNBOOK.md`  
**Versión:** 2.0 (Auditoría Post-Rehearsal TASK-05B-03)  
**Estrategia:** Contingencia Determinista para Clean Bootstrap  
**Regla de Oro:** **NUNCA PURGAR NI TRUNCAR POSTGRESQL COMO ACCIÓN AUTOMÁTICA**. Toda evidencia forense, datos nuevos y logs WAL deben preservarse.

---

## 1. PRINCIPIO GENERAL Y ARQUITECTURA DE CONTINGENCIA

Bajo la estrategia de **Clean Bootstrap**:
- No existe migración de datos históricos entre SQLite y PostgreSQL.
- `leads.db` se conserva como un archivo inmutable de solo lectura congelado en el Paso 2 del Cutover.
- La contingencia técnica se divide en **tres niveles operacionales estrictos (Tier 1, Tier 2 y Tier 3)** según el momento de activación y el estado de los datos ingresados.

> **[HALLAZGO DE AUDITORÍA CRÍTICO - TASK-05B-03]**  
> El comando histórico `migrate_sqlite_to_postgres.py --rollback --confirm-data-loss` ejecutaba `TRUNCATE TABLE CASCADE` sobre las tablas de PostgreSQL.  
> **QUEDA PROHIBIDO SU USO EN LOS PROCEDIMIENTOS DE REVERSIÓN OPERACIONAL AUTOMÁTICA**.  
> Truncar la base elimina la evidencia forense de fallos en Tier 1 y destruye permanentemente los datos comerciales ingresados en Tier 2 y 3.

---

## 2. MATRIZ DE DECISIÓN DE REVERSIÓN (3 TIERS)

| Nivel | Escenario Operacional | Impacto en Datos | Estrategia de Retorno | Aprobación Requerida |
|---|---|---|---|---|
| **Tier 1: Pre-Apertura (Ventana)** | Fallo durante el bootstrap, verificación `--verify-only` fallida, o smoke tests fallidos antes de abrir acceso a usuarios. | **Cero Pérdida de Datos**. `leads.db` nunca fue modificada. | Reversión inmediata a SQLite. Apuntar `.env` a `leads.db` y reiniciar FastAPI. Preservar PostgreSQL para análisis post-mortem. | Lead de Infraestructura |
| **Tier 2: Post-Apertura Recuperable** | Degradación o fallo de PostgreSQL en las primeras horas tras apertura, con prospectos/secuencias nuevos ingresados. | Riesgo de divergencia de datos si se vuelve a SQLite. | **Fix-Forward prioritario en PostgreSQL**. Si la reversión a SQLite es obligatoria, ejecutar **Conciliación Bidireccional** antes del switch. | Lead Técnico + Lead Comercial |
| **Tier 3: Catástrofe Irrecuperable** | Destrucción física total o inaccesibilidad permanente del clúster PostgreSQL en producción. | Pérdida de datos ingresados en PostgreSQL desde el cutover si no hay WAL/réplica. | Preservar todos los backups y WALs. Reversión de emergencia a `leads.db` con autorización ejecutiva explícita. | CTO / Dirección General |

---

## 3. PROCEDIMIENTO DETALLADO POR NIVEL

### Tier 1: Reversión Inmediata Pre-Apertura (Ventana de Mantenimiento)

#### Condiciones de Disparo (Criterios de Abortar)
- `bootstrap_postgres_clean.py --bootstrap` falla por conectividad, sintaxis o timeout.
- `bootstrap_postgres_clean.py --verify-only` reporta conteos incorrectos o falta de RLS/FORCE RLS.
- `GET /api/health` o los Smoke Tests fallan en cualquier comprobación.
- El operador humano decide suspender la ventana antes de abrir el acceso a usuarios.

#### Pasos Operacionales
1. **Detener el Backend**:
   - En Linux: `sudo systemctl stop nexusreach-backend`
   - En Windows: Detener el proceso Uvicorn / script de inicio.
2. **Revertir Configuración en `.env` a SQLite**:
   ```ini
   # DB_ENGINE=postgres
   # DATABASE_URL=postgresql://...
   DB_ENGINE=sqlite
   SQLITE_DB_PATH=leads.db
   ```
3. **Verificar Integridad de `leads.db` contra el Snapshot**:
   - En Linux (bash):
     ```bash
     CURRENT=$(sha256sum leads.db | awk '{print $1}')
     FROZEN=$(cat backups/historical_sqlite_*/leads.db.sha256)
     if [ "$CURRENT" != "$FROZEN" ]; then
         echo "[ALERTA] Descuadre detectado. Restaurando leads.db desde snapshot congelado..."
         cp backups/historical_sqlite_*/leads.db leads.db
     fi
     ```
   - En Windows (PowerShell):
     ```powershell
     $CURRENT = (Get-FileHash "leads.db" -Algorithm SHA256).Hash
     $FROZEN = Get-Content "backups/historical_sqlite_*/leads.db.sha256"
     if ($CURRENT -ne $FROZEN) {
         Copy-Item "backups/historical_sqlite_*/leads.db" "leads.db" -Force
     }
     ```
4. **Preservar la Base PostgreSQL para Post-Mortem**:
   - **NO PURGAR NI TRUNCAR**. Mantener la base intacta para que los ingenieros puedan conectarse y revisar `system_logs`, `audit_logs` y el catálogo.
5. **Reiniciar Backend en SQLite y Validar**:
   - En Linux: `sudo systemctl start nexusreach-backend`
   - En Windows: Iniciar Uvicorn.
   - Comprobar salud: `curl -s http://localhost:8000/api/health` (debe retornar 200 OK).
   - Verificar integridad: `SELECT count(*) FROM leads;` (debe retornar exactamente 194).
6. **Desactivar Kill-Switch y Cancelar Ventana**:
   El sistema reanuda operaciones normales en SQLite con **cero pérdida de datos**.

---

### Tier 2: Contingencia Post-Apertura (Datos Creados en PostgreSQL)

#### Condiciones de Disparo
- El sistema ya está en producción con PostgreSQL limpio y los operadores han ingresado nuevos prospectos, listas y secuencias.
- Se presenta degradación severa de rendimiento, contención de bloqueos o indisponibilidad parcial.

#### Protocolo Fix-Forward (Estrategia Mandatoria Prioritaria)
1. **Congelar Despachos Inmediatamente (Kill-Switch)**:
   ```bash
   curl -X POST "http://localhost:8000/api/seguridad/kill-switch/activar?motivo=Contencion+PostgreSQL+Tier2" \
        -H "Authorization: Bearer <ADMIN_TOKEN>"
   ```
   Esto detiene las llamadas salientes y los runners Electron evitando despachos erróneos.
2. **Preservar la Base de Datos**:
   No reiniciar bruscamente ni truncar tablas.
3. **Diagnóstico y Reparación en PostgreSQL**:
   - Diagnosticar bloqueos: `SELECT * FROM pg_stat_activity WHERE state != 'idle';`
   - Escalar recursos de hardware (CPU/RAM).
   - Ajustar el pool de conexiones en `database.py`.
4. **Reanudación Fix-Forward**:
   Desactivar el Kill-Switch y continuar en PostgreSQL preservando el 100% de los datos generados.

#### Protocolo de Reversión con Conciliación (Si Fix-Forward es Inviable)
Si la Dirección Técnica determina que el regreso a SQLite es inevitable:
> **[CANDADO DE SEGURIDAD ESTRICTO]**  
> **QUEDA PROHIBIDO HACER ROLLBACK A SQLITE SIN ANTES EXTRAER Y VERIFICAR EL DELTA DE DATOS CREADOS EN POSTGRESQL**.

1. **Exportar el Delta de Nuevos Registros desde PostgreSQL**:
   ```sql
   -- Extraer prospectos creados desde el corte
   COPY (
       SELECT id, tenant_id, nombre, perfil_url, cargo_actual, empresa_dominio, created_at 
       FROM leads 
       WHERE created_at >= '<TIMESTAMP_CUTOVER>'
   ) TO '/tmp/delta_leads_post_cutover.csv' WITH CSV HEADER;
   ```
2. **Importar y Conciliar en SQLite**:
   Ejecutar script de importación para insertar los nuevos leads en `leads.db`.
3. **Validación de Integridad**:
   Confirmar que ningún prospecto ingresado en PostgreSQL quedó huérfano antes de cambiar `DB_ENGINE=sqlite`.

---

### Tier 3: Reversión Catastrófica de Emergencia

#### Condiciones de Disparo
- Pérdida física irreversible de la instancia PostgreSQL o corrupción total del almacenamiento.
- Decisión ejecutiva formal de abandonar PostgreSQL y reanudar inmediatamente en SQLite.

#### Protocolo de Ejecución
1. **Preservación Forense Inmediata**:
   - Si el disco o volumen sigue accesible, tomar una imagen completa o snapshot de `/var/lib/postgresql/data` y `/var/lib/postgresql/wal_archive` para permitir un futuro Point-in-Time Recovery (PITR).
   - **NO EJECUTAR COMANDOS DESTRUCTIVOS** en PostgreSQL.
2. **Autorización Ejecutiva Formal**:
   - El CTO y la Dirección deben firmar el **Registro de Aceptación de Pérdida de Datos**, especificando la ventana de tiempo afectada.
3. **Restaurar `leads.db` desde el Snapshot Congelado**:
   ```powershell
   Copy-Item "backups/historical_sqlite_<timestamp>/leads.db" "leads.db" -Force
   ```
4. **Reconfigurar `.env` para SQLite**:
   Restablecer `DB_ENGINE=sqlite` y `SQLITE_DB_PATH=leads.db`.
5. **Reiniciar Backend en SQLite**:
   Iniciar FastAPI y notificar a los operadores comerciales que la plataforma vuelve a operar con el estado histórico congelado.
