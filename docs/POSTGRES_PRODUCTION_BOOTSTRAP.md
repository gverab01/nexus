# Inicialización y Bootstrap de Producción PostgreSQL
## NexusReach Pro — Guía de Operaciones, Referencia de Arquitectura y Hardening

**Documento:** `docs/POSTGRES_PRODUCTION_BOOTSTRAP.md`\
**Referencia Técnica:** TASK-05B-07 [P0] y TASK-05B-08 [P0]\
**Script Responsable:** `scripts/bootstrap_postgres_production.py`\
**Entorno de Destino:** PostgreSQL 16 (WSL2 / Docker / Bare Metal / VPS / Nube)

---

## 1. REGLA ABSOLUTA: PROTECCIÓN DE PRODUCCIÓN

> [!CAUTION]
> **NO EJECUTAR EL BOOTSTRAP PRODUCTIVO SIN AUTORIZACIÓN EXPRESA Y REVISIÓN HUMANA PREVIA.**
> Durante las tareas de auditoría y hardening:
> - NO ejecutar `--bootstrap` contra `nexusreach_prod`.
> - NO ejecutar `--dry-run` ni `--verify-only` contra `nexusreach_prod`.
> - NO modificar roles, contraseñas, hashes ni archivos `.env`.
> - NO mostrar secretos, credenciales ni DSN en consolas ni informes.

---

## 2. ARQUITECTURA DE SEGURIDAD Y HARDENING (TASK-05B-08)

### 2.1 Identidad de Conexión Estricta (Control P0.1)
El script exige terminantemente que la conexión se efectúe mediante el rol de aplicación con privilegios mínimos:
- **Rol permitido:** `nexus_app` (miembro del grupo `nexus_app_role`).
- **Atributos requeridos:** `rolsuper = False` y `rolbypassrls = False`.
- **Rechazo inmediato:** Cualquier conexión iniciada por `postgres`, `nexus_admin`, o cualquier usuario con atributo `SUPERUSER` o `BYPASSRLS` es **rechazada de inmediato** con código `1` (`EXIT_CONFIG`).
- **Eliminación de bypass:** Se eliminó por completo el flag `--allow-privileged-role` para impedir ejecuciones inseguras en las que PostgreSQL omitiría el motor RLS.

### 2.2 Validación Criptográfica SuperAdmin (Control P0.2)
- El acceso administrativo transaccional para la siembra inicial se autentica mediante la función de base de datos `public.verify_super_admin_context()` (definida con `SECURITY DEFINER`).
- Requiere inyectar `app.is_super_admin = 'true'` y `app.super_admin_token` a través del mecanismo oficial `database._configure_pg_context()`.
- Se eliminó cualquier excepción que omitiera la comprobación criptográfica cuando el usuario de sesión era administrador.
- Se valida que:
  1. El secreto `SUPERADMIN_RLS_SECRET` coincida criptográficamente con el hash registrado en `system_admin_keys`.
  2. Tokens falsos o ausentes sean rechazados (comportamiento *fail-closed* estricto).
  3. No se acepte el secreto público por defecto (`nexus_superadmin_secure_key_2026`).

### 2.3 Auditoría de Políticas RLS en Profundidad (Control P0.4)
El script inspecciona `pg_policies` para las tablas del bootstrap (`tenants`, `suscripciones`, `usuarios`, `audit_logs`) y valida:
- `cmd = 'ALL'` (la política cubre `SELECT`, `INSERT`, `UPDATE` y `DELETE`).
- `permissive = 'PERMISSIVE'`.
- Presencia obligatoria de la cláusula `USING` invocando `verify_super_admin_context()`.
- Presencia obligatoria de la cláusula `WITH CHECK` invocando `verify_super_admin_context()`.
- Reporta el estado de las 32 tablas con `ROW LEVEL SECURITY` y `FORCE ROW LEVEL SECURITY`.

### 2.4 Integridad Referencial en `audit_logs` (Control P0.5)
- La inserción en `audit_logs` utiliza el `id` real del usuario administrador creado (`usr_...`), garantizando consistencia y trazabilidad de acuerdo con el esquema y evitando valores hardcodeados incompatibles.

### 2.5 Clasificación Rigurosa de Estados en `assess_entity_state()` (Control P1.1)
- `ABSENT`: No existe tenant ni usuario. Listo para inicialización.
- `COMPLETE`: Existe exactamente 1 tenant raíz (`parent_tenant_id = NULL`), exactamente 1 suscripción inicial activa, y exactamente 1 usuario administrador con rol `COMPANY_ADMIN`, estado `ACTIVO` y `puesto_activo = 1`.
- `CONFLICT`: Se detecta cualquier inconsistencia (ej. más de una suscripción para el tenant, usuario huérfano, usuario asociado a otro tenant, tenant con rol erróneo). Ante `CONFLICT`, el script se detiene con código `2` (`EXIT_STATE_CONFLICT`) y **no realiza escrituras ni reparaciones destructivas**.

### 2.6 Fechas y Zonas Horarias (Control P1.2)
- Todas las fechas se generan utilizando `datetime.now().isoformat()` sin offset de zona horaria (naive), en estricta compatibilidad con `auth_service.py:create_account_full()` y `auth_service.py:authenticate_user()`.
- Se evita el problema de inconsistencia de tipos (`TypeError`) entre fechas naive y con zona horaria durante el cálculo de días de vigencia de suscripción.

---

## 3. VARIABLES DE ENTORNO REQUERIDAS

| Variable | Propósito | Requerido |
|---|---|:---:|
| `BOOTSTRAP_DATABASE_URL` | Cadena de conexión hacia PostgreSQL (rol `nexus_app`) | Sí |
| `SUPERADMIN_RLS_SECRET` | Token secreto de 64 caracteres hex | Sí |
| `BOOTSTRAP_ADMIN_PASSWORD` | Contraseña inicial segura del administrador (o `--admin-password-file`) | Sí |
| `BOOTSTRAP_TENANT_ID` | Identificador del tenant inicial (ej. `ten_primary`) | Sí |
| `BOOTSTRAP_TENANT_NAME` | Razón social de la organización | Sí |
| `BOOTSTRAP_ADMIN_EMAIL` | Correo electrónico del administrador | Sí |
| `BOOTSTRAP_ADMIN_NAME` | Nombre completo del administrador | Sí |
| `BOOTSTRAP_PERIODICITY` | `ANUAL` (365 días) o `MENSUAL` (30 días) | Sí |

---

## 4. MODOS DE OPERACIÓN Y COMANDOS

### 4.1 Modo Simulación (`--dry-run`)
Ejecuta la inspección de precondiciones, evalúa el estado actual y muestra el plan de operaciones dentro de una transacción `READ ONLY` de PostgreSQL. No escribe ningún dato.

```bash
python3 scripts/bootstrap_postgres_production.py --dry-run
```

### 4.2 Modo Verificación (`--verify-only`)
Audita las entidades existentes, sus relaciones, estados, reglas de negocio para login y el aislamiento RLS sin modificar datos.

```bash
python3 scripts/bootstrap_postgres_production.py --verify-only \
  --tenant-id "ten_primary" \
  --admin-email "admin@nexusreach.com"
```

### 4.3 Modo Inicialización Real (`--bootstrap`)
Ejecuta la siembra atómica protegida por un bloqueo consultivo (`pg_advisory_xact_lock`). Requiere la confirmación explícita del nombre de la base conectada mediante `--confirm-database nexusreach_prod`.

```bash
python3 scripts/bootstrap_postgres_production.py --bootstrap \
  --confirm-database nexusreach_prod
```

---

## 5. CÓDIGOS DE SALIDA

| Código | Macro | Significado |
|:---:|---|---|
| `0` | `EXIT_OK` | Éxito total o estado previamente inicializado verificado (idempotente). |
| `1` | `EXIT_CONFIG` | Configuración inválida, precondición no cumplida o rol privilegiado rechazado. |
| `2` | `EXIT_STATE_CONFLICT` | Conflicto de entidades o estado parcial detectado. No se altera la base. |
| `3` | `EXIT_VERIFICATION_FAILED` | Fallo en la verificación previa al commit (se revierte la transacción). |
| `4` | `EXIT_RUNTIME` | Error de ejecución en PostgreSQL (rollback completado). |

---

## 6. PROCEDIMIENTO DE RESPALDO Y CONTINGENCIA ANTES DE EJECUTAR EN PRODUCCIÓN

Antes de ejecutar `--bootstrap` en producción en una fase futura:
1. **Ejecutar respaldo binario completo:**
   ```bash
   python3 scripts/backup_postgres.py --output-dir /var/backups/nexusreach/pre_bootstrap
   ```
2. **Validar la integridad del respaldo:**
   ```bash
   python3 scripts/verify_backup_restoration.py --backup-file /var/backups/nexusreach/pre_bootstrap/<archivo>.dump
   ```
3. **Ejecutar `--dry-run` previo:**
   Confirmar que todas las precondiciones reporten `[OK]`.
4. **Ejecutar `--bootstrap`:**
   Verificar el código de retorno `0`.
5. **Ejecutar `--verify-only` posterior:**
   Confirmar el estado de las entidades y el aislamiento de tenants.
