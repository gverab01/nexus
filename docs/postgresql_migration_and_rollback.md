# Procedimiento de Migración a PostgreSQL y Rollback (Workstream 5.3 [P0])
**NexusReach Pro - Directrices de Ingeniería v1.3**

---

## 1. Visión General de la Arquitectura
Para escalar de una instancia de desarrollo local SQLite a un entorno multi-tenant en AWS São Paulo (`sa-east-1`) con RDS PostgreSQL y KMS:
- Todas las tablas de datos de cliente incorporan la columna `tenant_id` y claves foráneas en cascada.
- **Row-Level Security (RLS)** habilitada en todas las tablas (`leads`, `secuencias`, `devices`, `commands`, `suppression_list`, `lead_activity`, `linkedin_accounts`, `consent_records`, etc.).
- Las sesiones de la aplicación fijan variables de entorno de transacción en PostgreSQL:
  ```sql
  SET LOCAL app.current_tenant_id = 'ten_xyz';
  SET LOCAL app.is_super_admin = 'false';
  ```
- Toda consulta sin contexto de tenant o con tenant distinto devuelve 0 filas por diseño a nivel de motor de base de datos.

---

## 2. Requisitos Previos
1. PostgreSQL 15+ desplegado (AWS RDS PostgreSQL en `sa-east-1` o base local).
2. Extensión `pgcrypto` activada:
   ```sql
   CREATE EXTENSION IF NOT EXISTS "pgcrypto";
   ```
3. Esquema aplicado desde [schema_postgres.sql](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/schema_postgres.sql):
   ```bash
   psql -d $DATABASE_URL -f schema_postgres.sql
   ```

---

## 3. Guía de Ejecución de Migración

### Paso 1: Simulación Previa (Dry-Run)
Verifica que las tablas de origen SQLite se lean correctamente y que la sintaxis de inserción sea válida sin modificar la base de datos de producción:
```bash
python scripts/migrate_sqlite_to_postgres.py --dry-run --target-url "$DATABASE_URL"
```

### Paso 2: Migración Efectiva
Ejecuta la copia tabla por tabla en orden topológico estricto de claves foráneas con cláusula `ON CONFLICT DO NOTHING`:
```bash
python scripts/migrate_sqlite_to_postgres.py --migrate --target-url "$DATABASE_URL"
```

### Paso 3: Verificación de Conteos Post-Migración
Compara fila por fila todas las tablas entre SQLite y PostgreSQL:
```bash
python scripts/migrate_sqlite_to_postgres.py --verify-only --target-url "$DATABASE_URL"
```

---

## 4. Plan de Rollback Inmediato
Si durante la ventana de migración se detectan anomalías de integridad, tiempos de respuesta o inconsistencias:

1. **Reversión de Tráfico de la Aplicación**:
   Desactivar `DATABASE_URL` del archivo `.env` o del gestor de configuración para que el backend vuelva automáticamente al archivo SQLite local `leads.db`.
2. **Limpieza de PostgreSQL (Truncate en Cascada)**:
   ```bash
   python scripts/migrate_sqlite_to_postgres.py --rollback --target-url "$DATABASE_URL"
   ```
3. **Verificación de Retorno Seguro**:
   Verificar que la instancia SQLite local continúa operando normalmente con:
   ```bash
   python -m unittest tests/test_signed_commands.py -v
   python -m unittest tests/test_zoho_bridge_and_dedup.py -v
   ```
