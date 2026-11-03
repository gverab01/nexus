#!/usr/bin/env python3
"""
NexusReach Pro - Automated Logical Backup Engine for PostgreSQL
TASK-05B-06 [P0]

Implementa el mecanismo de respaldo lógico diario para PostgreSQL (nexusreach_prod):
1. Ejecuta pg_dump en formato custom (-Fc).
2. Guarda el volcado directamente en almacenamiento persistente del host (fuera del contenedor).
3. Aplica política de retención configurable (por defecto: 7 copias diarias más recientes).
4. Registra fecha, tamaño en bytes, hash SHA-256 y resultado en backup_history.log.
5. No almacena contraseñas en el script; lee de .env o variables de entorno.
6. Evita sobrescribir backups anteriores mediante timestamp ISO.
"""

import os
import sys
import argparse
import subprocess
import hashlib
from datetime import datetime
import glob
from typing import Dict, Any, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups", "postgres")
LOG_FILE_PATH = os.path.join(DEFAULT_BACKUP_DIR, "backup_history.log")
DOCKER_BIN = r"C:\Users\gabri\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
CONTAINER_NAME = "nexusreach_postgres_rls_test"
DB_NAME = "nexusreach_prod"
DB_USER = "nexus_admin"
DEFAULT_RETENTION_COUNT = 7


def calculate_sha256(file_path: str) -> str:
    """Calcula el hash SHA-256 de un archivo en chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_pgdump_magic_header(file_path: str) -> bool:
    """Verifica que el archivo comience con el encabezado mágico de pg_dump custom format ('PGDMP')."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            return header == b"PGDMP"
    except Exception:
        return False


def log_backup_event(log_entry: str, log_path: str = LOG_FILE_PATH):
    """Registra una entrada estructurada en backup_history.log."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_entry.strip() + "\n")


def apply_retention_policy(backup_dir: str, retention_count: int) -> List[str]:
    """
    Aplica la política de retención:
    Conserva los `retention_count` backups más recientes y elimina los anteriores.
    Retorna la lista de archivos purgados.
    """
    pattern = os.path.join(backup_dir, f"{DB_NAME}_backup_*.dump")
    dump_files = glob.glob(pattern)
    # Ordenar por fecha de modificación descendente (más recientes primero)
    dump_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    purged_files = []
    if len(dump_files) > retention_count:
        files_to_remove = dump_files[retention_count:]
        for f in files_to_remove:
            try:
                os.remove(f)
                purged_files.append(os.path.basename(f))
            except Exception as e:
                print(f"[WARN] No se pudo purgar {f}: {e}")
    return purged_files


def execute_backup(
    backup_dir: str = DEFAULT_BACKUP_DIR,
    retention_count: int = DEFAULT_RETENTION_COUNT,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Ejecuta el ciclo de backup lógico completo."""
    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{DB_NAME}_backup_{timestamp_str}.dump"
    target_path = os.path.join(backup_dir, backup_filename)

    print(f"[{start_time.isoformat()}] INICIANDO BACKUP LÓGICO DE {DB_NAME}...")
    print(f"  Directorio destino persistente: {backup_dir}")
    print(f"  Archivo destino: {backup_filename}")
    print(f"  Política de retención: Conservar {retention_count} copias diarias")

    if dry_run:
        print("  [DRY-RUN] Simulación de backup completada sin escrituras.")
        return {"status": "DRY_RUN", "file": target_path}

    os.makedirs(backup_dir, exist_ok=True)

    # Comando pg_dump ejecutado dentro del contenedor con salida dirigida a stdout binario
    cmd = [
        DOCKER_BIN, "exec", CONTAINER_NAME,
        "pg_dump", "-U", DB_USER, "-d", DB_NAME, "-Fc"
    ]

    try:
        with open(target_path, "wb") as out_f:
            proc = subprocess.run(cmd, stdout=out_f, stderr=subprocess.PIPE)

        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="ignore").strip()
            if os.path.exists(target_path):
                os.remove(target_path)
            log_entry = (
                f"{datetime.now().isoformat()} | FAILED | {backup_filename} | 0 bytes | "
                f"Error: {err_msg}"
            )
            log_backup_event(log_entry, LOG_FILE_PATH)
            raise RuntimeError(f"Fallo al ejecutar pg_dump: {err_msg}")

        # Verificaciones de sanidad del archivo volcado
        file_size = os.path.getsize(target_path)
        if file_size == 0:
            if os.path.exists(target_path):
                os.remove(target_path)
            raise RuntimeError("Fallo: El archivo de backup generado tiene 0 bytes!")

        if not verify_pgdump_magic_header(target_path):
            if os.path.exists(target_path):
                os.remove(target_path)
            raise RuntimeError("Fallo: El archivo generado no posee el encabezado válido de pg_dump custom format ('PGDMP')")

        file_sha256 = calculate_sha256(target_path)
        duration_sec = round((datetime.now() - start_time).total_seconds(), 2)

        print(f"  [✓] Backup completado exitosamente:")
        print(f"      Tamaño: {file_size:,} bytes")
        print(f"      SHA-256: {file_sha256}")
        print(f"      Duración: {duration_sec}s")

        # Aplicar política de retención
        purged = apply_retention_policy(backup_dir, retention_count)
        purged_desc = f"Purgados ({len(purged)}): {', '.join(purged)}" if purged else "Ninguno purgado"
        print(f"  [✓] Política de retención aplicada: {purged_desc}")

        # Registrar en bitácora
        log_entry = (
            f"{datetime.now().isoformat()} | SUCCESS | {backup_filename} | "
            f"{file_size} bytes | SHA256:{file_sha256} | Duracion:{duration_sec}s | {purged_desc}"
        )
        log_backup_event(log_entry, LOG_FILE_PATH)
        print(f"  [✓] Evento registrado en bitácora: {LOG_FILE_PATH}")

        return {
            "status": "SUCCESS",
            "file_name": backup_filename,
            "file_path": target_path,
            "size_bytes": file_size,
            "sha256": file_sha256,
            "duration_sec": duration_sec,
            "purged": purged
        }

    except Exception as e:
        if os.path.exists(target_path) and os.path.getsize(target_path) == 0:
            os.remove(target_path)
        log_entry = f"{datetime.now().isoformat()} | ERROR | {backup_filename} | Exception: {str(e)}"
        log_backup_event(log_entry, LOG_FILE_PATH)
        raise


def list_backups(backup_dir: str = DEFAULT_BACKUP_DIR):
    """Lista los backups disponibles y el historial de la bitácora."""
    pattern = os.path.join(backup_dir, f"{DB_NAME}_backup_*.dump")
    dump_files = glob.glob(pattern)
    dump_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    print("=" * 80)
    print(f"INVENTARIO DE BACKUPS POSTGRESQL ({len(dump_files)} encontrados)")
    print("=" * 80)
    for i, f in enumerate(dump_files, 1):
        sz = os.path.getsize(f)
        dt = datetime.fromtimestamp(os.path.getmtime(f)).isoformat()
        is_valid = verify_pgdump_magic_header(f)
        status_str = "VALID (PGDMP)" if is_valid else "INVALID"
        print(f"{i:2d}. {os.path.basename(f)} | {sz:,} bytes | {dt} | {status_str}")

    print("\nÚLTIMAS LÍNEAS DE BITÁCORA (backup_history.log):")
    if os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, "r", encoding="utf-8") as lf:
            lines = lf.readlines()
            for l in lines[-5:]:
                print("  " + l.strip())
    else:
        print("  (Bitácora no existe aún)")


def main():
    parser = argparse.ArgumentParser(description="NexusReach Pro - Backup Lógico PostgreSQL")
    parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION_COUNT, help="Copias a conservar (default: 7)")
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, help="Directorio de destino persistente")
    parser.add_argument("--dry-run", action="store_true", help="Simulación sin escrituras")
    parser.add_argument("--list", action="store_true", help="Listar backups existentes y bitácora")

    args = parser.parse_args()

    if args.list:
        list_backups(args.backup_dir)
        return 0

    res = execute_backup(
        backup_dir=args.backup_dir,
        retention_count=args.retention,
        dry_run=args.dry_run
    )
    return 0 if res.get("status") in ("SUCCESS", "DRY_RUN") else 1


if __name__ == "__main__":
    sys.exit(main())

