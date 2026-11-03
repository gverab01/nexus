#!/usr/bin/env python3
"""
NexusReach Pro - Bootstrap de Producción PostgreSQL (TASK-05B-07) [P0]

Inicializador específico para la instalación PostgreSQL de producción YA EXISTENTE.
Crea, de forma transaccional e idempotente:

  1. Tenant principal (tipo EMPRESA, estado ACTIVO, sin jerarquía).
  2. Suscripción inicial asociada (tabla `suscripciones`).
  3. Usuario administrador principal (rol COMPANY_ADMIN, hash oficial de auth_service).
  4. Configuraciones esenciales de seguridad ausentes en `configuracion_seguridad`.
  5. Registro de auditoría BOOTSTRAP_PRODUCCION.

Este script NO:
  - aplica schema_postgres.sql ni init_postgres_test_roles.sql,
  - crea / modifica / elimina roles, contraseñas o credenciales PostgreSQL,
  - genera, rota ni escribe SUPERADMIN_RLS_SECRET ni system_admin_keys,
  - deshabilita RLS ni modifica políticas,
  - actualiza o elimina registros existentes (nunca usa ON CONFLICT DO UPDATE),
  - imprime contraseñas, hashes, secretos ni cadenas de conexión.

Modelo de seguridad (ver docs/POSTGRES_PRODUCTION_BOOTSTRAP.md):
  - Conexión administrativa separada: BOOTSTRAP_DATABASE_URL (sin fallback a DATABASE_URL).
  - Rol recomendado: `nexus_app` (NOSUPERUSER, NOBYPASSRLS) + contexto SuperAdmin criptográfico
    establecido con el mecanismo oficial `database._configure_pg_context()` y validado por
    `verify_super_admin_context()` contra el hash de `system_admin_keys`.
  - Roles SUPERUSER/BYPASSRLS (p. ej. nexus_admin) solo con --allow-privileged-role.

Modos:
  --dry-run      Transacción READ ONLY: valida configuración, conexión, precondiciones y simula el plan.
  --bootstrap    Ejecuta la inicialización en UNA transacción. Requiere --confirm-database <nombre>.
  --verify-only  Transacción READ ONLY: verifica entidades, relaciones, autenticación, config y RLS.

Códigos de salida:
  0 = OK / ya inicializado, 1 = configuración o precondición inválida,
  2 = estado parcial o conflictivo detectado (no se modifica nada),
  3 = verificación fallida (en --bootstrap implica ROLLBACK completo), 4 = error inesperado (ROLLBACK).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ==============================================================================
# CONSTANTES
# ==============================================================================

SCRIPT_NAME = "bootstrap_postgres_production.py"
SCRIPT_VERSION = "1.0.0"
TASK_ID = "TASK-05B-07"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_STATE_CONFLICT = 2
EXIT_VERIFICATION_FAILED = 3
EXIT_RUNTIME = 4

# Variables de entorno
ENV_DSN = "BOOTSTRAP_DATABASE_URL"
ENV_ADMIN_PASSWORD = "BOOTSTRAP_ADMIN_PASSWORD"
ENV_TENANT_ID = "BOOTSTRAP_TENANT_ID"
ENV_TENANT_NAME = "BOOTSTRAP_TENANT_NAME"
ENV_ADMIN_EMAIL = "BOOTSTRAP_ADMIN_EMAIL"
ENV_ADMIN_NAME = "BOOTSTRAP_ADMIN_NAME"
ENV_PERIODICITY = "BOOTSTRAP_PERIODICITY"
ENV_SEATS = "BOOTSTRAP_SEATS"
ENV_UNIT_PRICE = "BOOTSTRAP_UNIT_PRICE"
ENV_SUPERADMIN_SECRET = "SUPERADMIN_RLS_SECRET"

PRODUCTION_DB_NAME = "nexusreach_prod"
APP_ROLE_NAME = "nexus_app"
ADVISORY_LOCK_KEY = "nexusreach:production_bootstrap"
MIN_SERVER_VERSION_NUM = 160000

# Secretos SuperAdmin públicamente conocidos (schema_postgres.sql / .env.example). Nunca válidos en producción.
KNOWN_INSECURE_SUPERADMIN_SECRETS = (
    "nexus_superadmin_secure_key_2026",
    "your_64_character_hex_secret_here",
)

# Modelo de dominio real (schema_postgres.sql + auth_service.create_account_full)
TENANT_TYPE = "EMPRESA"
TENANT_STATE = "ACTIVO"
ADMIN_ROLE = "COMPANY_ADMIN"
USER_STATE = "ACTIVO"
SUBSCRIPTION_STATE = "ACTIVA"
PERIODICITY_DAYS = {"MENSUAL": 30, "ANUAL": 365}
LOGIN_VALID_SUBSCRIPTION_STATES = ("ACTIVA", "EN_PRUEBA")  # auth_service.authenticate_user
DEFAULT_SEATS = 1            # DEFAULT de suscripciones.puestos_contratados
DEFAULT_UNIT_PRICE = "35.00"  # DEFAULT de suscripciones.precio_unitario_plataforma
MAX_SEATS = 10000
MAX_UNIT_PRICE = Decimal("99999999.99")  # NUMERIC(10,2)

TENANT_ID_RE = re.compile(r"^ten_[a-z0-9_]{3,60}$")
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

REQUIRED_TABLES = ("tenants", "suscripciones", "usuarios", "configuracion_seguridad", "audit_logs", "system_admin_keys")
VERIFY_FUNCTION = "public.verify_super_admin_context()"
CORE_RLS_POLICIES = {
    "tenants": "rls_tenants_policy",
    "suscripciones": "rls_suscripciones_policy",
    "usuarios": "rls_usuarios_policy",
    "audit_logs": "rls_audit_logs_policy",
}
WRITE_PRIVILEGES = (
    ("tenants", "SELECT"), ("tenants", "INSERT"),
    ("suscripciones", "SELECT"), ("suscripciones", "INSERT"),
    ("usuarios", "SELECT"), ("usuarios", "INSERT"),
    ("configuracion_seguridad", "SELECT"), ("configuracion_seguridad", "INSERT"),
    ("audit_logs", "INSERT"),
)
READ_PRIVILEGES = tuple(p for p in WRITE_PRIVILEGES if p[1] == "SELECT")

# Huellas SHA-256 (en minúsculas) de contraseñas débiles/por defecto ya presentes en el repositorio
# o de uso común. Se almacenan como huellas para no replicar credenciales en texto plano.
WEAK_PASSWORD_FINGERPRINTS = frozenset({
    "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "3ac40463b419a7de590185c7121f0bfbe411d6168699e8014f521b050b1d6653",
    "7e6e1f7bd27296e97d8494fc51cb3d19355b26e062e7c09a163d954213f41ab9",
    "f67e19cdc10d99530cc4240a26db43a82b44e64cc348858038af4a825485c634",
    "8783b2b689f91e025fe218ad321e256dce8d32c1f969b3ddbbc8b1ac58d1b36d",
    "7c3d4b31e62ecad4f49c5800d42fcc648656a9e2b7dce47b1e63b35c2681bda8",
    "d3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791",
    "1725165c9a0b3698a3d01016e0d8205155820b8d7f21835ca64c0f81c728d880",
    "564119c78d59e33225ae169ddbc382cf3f709e76ec7ea9ebbd3ceab57ceab200",
    "9a820f2234e6a1cd65b17245a66f7bc4ce8f6ccd5123c550615c920f0e5c5fca",
    "bfc8eb3ef77cda93e9608451240fb32dd90d5a103171df7b6eb604fa633c9b34",
    "5e5b477f5cb6377010b9b214b9c05d4786a5ea6d62fdce0a3a9944caef97c1ae",
    "b2e158aa418d04f75ae4c2c07a10b591f00595bfdbe66f127bcba71998ab22d9",
    "f9d95c47e65461ec2c200f6edc6958235b859ec754ccad8e0e6d34121262525c",
    "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
    "057ba03d6c44104863dc7361fe4578965d1887360f90a0895882e58a6248fc86",
    "2a33349e7e606a8ad2e30e3c84521f9377450cf09083e162e0a9b1480ce0f972",
})
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


@dataclass(frozen=True)
class SafetySetting:
    key: str
    default: str
    kind: str  # flag | time | positive_int | text
    description: str
    protection_flag: bool = False  # "0" desactiva una protección antibaneo


# Configuración esencial de seguridad (revisión de DEFAULT_SAFETY_CONFIG del bootstrap de pruebas).
# Los valores coinciden con los fallbacks del código en tiempo de ejecución (safety_engine.py, main.py,
# whatsapp_safety_engine.py) y con los defaults de database.py.
ESSENTIAL_SAFETY_CONFIG: Tuple[SafetySetting, ...] = (
    SafetySetting("kill_switch_activado", "0", "flag", "Freno de emergencia activo (0=normal, 1=bloqueo total)"),
    SafetySetting("kill_switch_motivo", "", "text", "Motivo del último disparo de freno de emergencia"),
    SafetySetting("horario_laboral_activo", "1", "flag", "Restringir actividad a horario laboral de oficina (0 o 1)", True),
    SafetySetting("horario_inicio", "09:00", "time", "Hora inicio laboral (HH:MM)"),
    SafetySetting("horario_fin", "18:00", "time", "Hora fin laboral (HH:MM)"),
    SafetySetting("pausas_antiban_activas", "1", "flag", "Pausas humanas estocásticas entre acciones (0 o 1)", True),
    SafetySetting("pausa_linkedin_min_seg", "180", "positive_int", "Pausa mínima entre acciones LinkedIn (segundos)"),
    SafetySetting("pausa_linkedin_max_seg", "360", "positive_int", "Pausa máxima entre acciones LinkedIn (segundos)"),
    SafetySetting("pausa_email_min_seg", "480", "positive_int", "Pausa mínima entre emails Google Workspace (segundos)"),
    SafetySetting("pausa_email_max_seg", "900", "positive_int", "Pausa máxima entre emails Google Workspace (segundos)"),
    SafetySetting("whatsapp_pausa_min_seg", "360", "positive_int", "Pausa mínima entre mensajes WhatsApp a contactos nuevos (segundos)"),
    SafetySetting("whatsapp_pausa_max_seg", "900", "positive_int", "Pausa máxima entre mensajes WhatsApp a contactos nuevos (segundos)"),
    SafetySetting("limites_diarios_activos", "1", "flag", "Control estricto de cuotas diarias de invitaciones (0 o 1)", True),
    SafetySetting("limite_linkedin_diario", "5", "positive_int", "Máximo de invitaciones LinkedIn al día"),
    SafetySetting("limite_email_workspace_diario", "15", "positive_int", "Máximo de correos Google Workspace al día (Warmup)"),
    SafetySetting("whatsapp_cuota_diaria", "15", "positive_int", "Máximo de conversaciones nuevas en WhatsApp Web al día"),
    SafetySetting("linkedin_warmup_activo", "1", "flag", "Rampa de calentamiento progresivo para invitaciones LinkedIn (1=sí, 0=no)", True),
)
SAFETY_PAIRS_MIN_MAX = (
    ("pausa_linkedin_min_seg", "pausa_linkedin_max_seg"),
    ("pausa_email_min_seg", "pausa_email_max_seg"),
    ("whatsapp_pausa_min_seg", "whatsapp_pausa_max_seg"),
)


# ==============================================================================
# ERRORES
# ==============================================================================

class BootstrapError(Exception):
    exit_code = EXIT_RUNTIME


class ConfigurationError(BootstrapError):
    exit_code = EXIT_CONFIG


class PreconditionError(BootstrapError):
    exit_code = EXIT_CONFIG


class StateConflictError(BootstrapError):
    exit_code = EXIT_STATE_CONFLICT


class VerificationError(BootstrapError):
    exit_code = EXIT_VERIFICATION_FAILED


# ==============================================================================
# LOGGING CON REDACCIÓN DE SECRETOS
# ==============================================================================

_DSN_PASSWORD_RE = re.compile(r"(://[^:/@\s]+):([^@\s]+)@")
_KV_PASSWORD_RE = re.compile(r"(password\s*=\s*)(\S+)", re.IGNORECASE)


class SecretRedactingFilter(logging.Filter):
    """Elimina de cada mensaje los secretos registrados y cualquier credencial embebida en DSN."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: List[str] = []

    def register(self, value: Optional[str]) -> None:
        if value and len(value) >= 4 and value not in self._secrets:
            self._secrets.append(value)
            self._secrets.sort(key=len, reverse=True)

    def redact(self, text: str) -> str:
        for s in self._secrets:
            if s in text:
                text = text.replace(s, "***")
        text = _DSN_PASSWORD_RE.sub(r"\1:***@", text)
        text = _KV_PASSWORD_RE.sub(r"\1***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        return True


def build_logger(stream=None) -> Tuple[logging.Logger, SecretRedactingFilter]:
    logger = logging.getLogger(f"nexusreach.bootstrap_production.{id(stream)}.{secrets.token_hex(4)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    redactor = SecretRedactingFilter()
    handler.addFilter(redactor)
    logger.addHandler(handler)
    return logger, redactor


def extract_dsn_password(dsn: str) -> Optional[str]:
    m = _DSN_PASSWORD_RE.search(dsn or "")
    if m:
        return m.group(2)
    m = _KV_PASSWORD_RE.search(dsn or "")
    return m.group(2) if m else None


# ==============================================================================
# PARÁMETROS Y VALIDACIÓN
# ==============================================================================

@dataclass
class BootstrapParams:
    tenant_id: str
    admin_email: str
    tenant_name: Optional[str] = None
    admin_name: Optional[str] = None
    periodicity: Optional[str] = None
    seats: int = DEFAULT_SEATS
    unit_price: Decimal = Decimal(DEFAULT_UNIT_PRICE)


def _pick(cli_value: Optional[str], environ: Mapping[str, str], env_name: str) -> Optional[str]:
    if cli_value is not None and str(cli_value).strip() != "":
        return str(cli_value)
    val = environ.get(env_name)
    if val is not None and val.strip() != "":
        return val
    return None


def _validate_text(label: str, value: Optional[str], errors: List[str], min_len: int = 2, max_len: int = 255) -> Optional[str]:
    if value is None:
        errors.append(f"{label} es obligatorio.")
        return None
    clean = value.strip()
    if len(clean) < min_len or len(clean) > max_len:
        errors.append(f"{label} debe tener entre {min_len} y {max_len} caracteres.")
    if CONTROL_CHARS_RE.search(clean):
        errors.append(f"{label} contiene caracteres de control no permitidos.")
    return clean


def normalize_email(value: str) -> str:
    return value.strip().lower()


def build_params(args: argparse.Namespace, environ: Mapping[str, str], mode: str) -> BootstrapParams:
    """Construye y valida los parámetros. CLI tiene prioridad sobre variables de entorno."""
    errors: List[str] = []

    tenant_id = _pick(args.tenant_id, environ, ENV_TENANT_ID)
    if tenant_id is None:
        errors.append(f"ID del tenant obligatorio (--tenant-id o {ENV_TENANT_ID}).")
    else:
        tenant_id = tenant_id.strip()
        if not TENANT_ID_RE.match(tenant_id):
            errors.append("ID del tenant inválido: formato requerido 'ten_' + [a-z0-9_]{3,60}.")

    email_raw = _pick(args.admin_email, environ, ENV_ADMIN_EMAIL)
    email = None
    if email_raw is None:
        errors.append(f"Email del administrador obligatorio (--admin-email o {ENV_ADMIN_EMAIL}).")
    else:
        email = normalize_email(email_raw)
        if len(email) > 255 or not EMAIL_RE.match(email):
            errors.append("Email del administrador con formato inválido.")

    params = BootstrapParams(tenant_id=tenant_id or "", admin_email=email or "")

    tenant_name = _pick(args.tenant_name, environ, ENV_TENANT_NAME)
    admin_name = _pick(args.admin_name, environ, ENV_ADMIN_NAME)
    periodicity = _pick(args.periodicity, environ, ENV_PERIODICITY)
    seats_raw = _pick(args.seats, environ, ENV_SEATS)
    price_raw = _pick(args.unit_price, environ, ENV_UNIT_PRICE)

    if mode in ("dry-run", "bootstrap"):
        params.tenant_name = _validate_text("Razón social del tenant (--tenant-name)", tenant_name, errors)
        params.admin_name = _validate_text("Nombre del administrador (--admin-name)", admin_name, errors)
        if periodicity is None:
            errors.append(
                f"Periodicidad obligatoria (--periodicity o {ENV_PERIODICITY}): MENSUAL (expira en 30 días) "
                "o ANUAL (expira en 365 días). Una suscripción vencida bloquea el inicio de sesión."
            )
        else:
            periodicity = periodicity.strip().upper()
            if periodicity not in PERIODICITY_DAYS:
                errors.append("Periodicidad inválida: valores permitidos MENSUAL, ANUAL.")
            params.periodicity = periodicity
    else:
        # verify-only: valores opcionales usados solo para comparar
        params.tenant_name = tenant_name.strip() if tenant_name else None
        params.admin_name = admin_name.strip() if admin_name else None
        params.periodicity = periodicity.strip().upper() if periodicity else None

    if seats_raw is not None:
        try:
            seats = int(str(seats_raw).strip())
            if seats < 1 or seats > MAX_SEATS:
                raise ValueError
            params.seats = seats
        except ValueError:
            errors.append(f"Puestos contratados inválidos: entero entre 1 y {MAX_SEATS}.")
    if price_raw is not None:
        try:
            price = Decimal(str(price_raw).strip()).quantize(Decimal("0.01"))
            if price < 0 or price > MAX_UNIT_PRICE:
                raise InvalidOperation
            params.unit_price = price
        except (InvalidOperation, ValueError):
            errors.append("Precio unitario inválido: decimal entre 0 y 99999999.99.")

    if errors:
        raise ConfigurationError("Parámetros inválidos:\n  - " + "\n  - ".join(errors))
    return params


def load_admin_password(password_file: Optional[str], environ: Mapping[str, str]) -> Optional[str]:
    """Obtiene la contraseña inicial desde archivo protegido (0600) o variable de entorno.
    Nunca se solicita interactivamente, nunca se genera y nunca se acepta como argumento CLI."""
    env_value = environ.get(ENV_ADMIN_PASSWORD)
    if password_file and env_value:
        raise ConfigurationError(
            f"Contraseña suministrada simultáneamente por --admin-password-file y {ENV_ADMIN_PASSWORD}. Use solo una fuente."
        )
    if password_file:
        try:
            st = os.stat(password_file)
        except OSError:
            raise ConfigurationError("No se puede acceder al archivo de contraseña indicado en --admin-password-file.")
        if not stat.S_ISREG(st.st_mode):
            raise ConfigurationError("--admin-password-file debe ser un archivo regular.")
        if os.name == "posix":
            if st.st_mode & 0o077:
                raise ConfigurationError(
                    "El archivo de contraseña es accesible por grupo u otros usuarios. Aplique 'chmod 600' antes de continuar."
                )
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
                raise ConfigurationError("El archivo de contraseña debe pertenecer al usuario que ejecuta el bootstrap.")
        with open(password_file, "r", encoding="utf-8") as fh:
            content = fh.read()
        content = content[:-2] if content.endswith("\r\n") else (content[:-1] if content.endswith("\n") else content)
        if "\n" in content or "\r" in content:
            raise ConfigurationError("El archivo de contraseña debe contener una única línea.")
        return content or None
    if env_value:
        return env_value
    return None


def validate_admin_password(password: str, email: str, tenant_id: str, superadmin_secret: Optional[str]) -> List[str]:
    """Política mínima para la contraseña inicial de producción. Los mensajes nunca incluyen la contraseña."""
    problems: List[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"longitud mínima {MIN_PASSWORD_LENGTH} caracteres")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"longitud máxima {MAX_PASSWORD_LENGTH} caracteres")
    if password != password.strip():
        problems.append("no debe comenzar ni terminar con espacios")
    if CONTROL_CHARS_RE.search(password):
        problems.append("no debe contener caracteres de control")
    classes = sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ))
    if classes < 3:
        problems.append("debe combinar al menos 3 de: minúsculas, mayúsculas, dígitos, símbolos")
    lowered = password.lower()
    if hashlib.sha256(lowered.encode("utf-8")).hexdigest() in WEAK_PASSWORD_FINGERPRINTS:
        problems.append("corresponde a una contraseña por defecto o conocida")
    local_part = email.split("@", 1)[0].lower() if email else ""
    if len(local_part) >= 4 and local_part in lowered:
        problems.append("no debe contener el usuario del email")
    if tenant_id and tenant_id.lower() in lowered:
        problems.append("no debe contener el ID del tenant")
    if superadmin_secret and password == superadmin_secret:
        problems.append("no debe coincidir con SUPERADMIN_RLS_SECRET")
    return problems


def validate_superadmin_secret(environ: Mapping[str, str]) -> str:
    secret = (environ.get(ENV_SUPERADMIN_SECRET) or "").strip()
    if not secret:
        raise ConfigurationError(
            f"{ENV_SUPERADMIN_SECRET} no está disponible en el entorno. Es necesario para autenticar el contexto "
            "SuperAdmin RLS (no se genera ni se modifica)."
        )
    if secret in KNOWN_INSECURE_SUPERADMIN_SECRETS:
        raise ConfigurationError(
            f"{ENV_SUPERADMIN_SECRET} corresponde a un valor por defecto públicamente conocido. Abortando."
        )
    return secret


# ==============================================================================
# CONFIGURACIÓN DE SEGURIDAD
# ==============================================================================

@dataclass
class ConfigAssessment:
    to_create: Dict[str, str] = field(default_factory=dict)
    kept: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _setting_format_error(setting: SafetySetting, value: Any) -> Optional[str]:
    if value is None:
        return "valor NULL"
    v = str(value)
    if setting.kind == "flag" and v not in ("0", "1"):
        return "debe ser '0' o '1'"
    if setting.kind == "time" and not TIME_RE.match(v):
        return "debe tener formato HH:MM"
    if setting.kind == "positive_int":
        if not v.isdigit() or int(v) <= 0:
            return "debe ser un entero positivo"
    return None


def assess_safety_config(existing: Mapping[str, Any]) -> ConfigAssessment:
    """Clasifica cada clave esencial: inexistente (crear), existente válida (conservar), inválida (detener).
    Nunca propone modificar un valor existente."""
    result = ConfigAssessment()
    for setting in ESSENTIAL_SAFETY_CONFIG:
        if setting.key not in existing:
            result.to_create[setting.key] = setting.default
            continue
        value = existing[setting.key]
        err = _setting_format_error(setting, value)
        if err:
            result.errors.append(f"'{setting.key}' existente es inválida: {err}.")
            continue
        result.kept[setting.key] = str(value)
        if setting.protection_flag and str(value) == "0":
            result.warnings.append(f"'{setting.key}' = '0' desactiva una protección antibaneo (se conserva sin cambios).")
        if setting.key == "kill_switch_activado" and str(value) == "1":
            result.warnings.append("'kill_switch_activado' = '1': el freno de emergencia está activo (se conserva).")

    effective = dict(result.kept)
    effective.update(result.to_create)
    try:
        if "horario_inicio" in effective and "horario_fin" in effective:
            if TIME_RE.match(effective["horario_inicio"]) and TIME_RE.match(effective["horario_fin"]):
                if effective["horario_inicio"] >= effective["horario_fin"]:
                    result.errors.append("'horario_inicio' debe ser anterior a 'horario_fin'.")
        for lo, hi in SAFETY_PAIRS_MIN_MAX:
            a, b = effective.get(lo), effective.get(hi)
            if a and b and a.isdigit() and b.isdigit() and int(a) > int(b):
                result.errors.append(f"'{lo}' ({a}) es mayor que '{hi}' ({b}).")
    except Exception:  # pragma: no cover - defensivo
        result.errors.append("No se pudo evaluar la coherencia de la configuración de seguridad.")
    return result


# ==============================================================================
# REPORTES
# ==============================================================================

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
_ICONS = {OK: "✓", WARN: "!", FAIL: "✕", SKIP: "-"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Report:
    title: str
    checks: List[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    def extend(self, other: "Report") -> None:
        self.checks.extend(other.checks)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def ok(self) -> bool:
        return not self.failures

    def emit(self, log: logging.Logger) -> None:
        log.info(f"\n[{self.title}]")
        for c in self.checks:
            suffix = f" — {c.detail}" if c.detail else ""
            log.info(f"  {_ICONS.get(c.status, '?')} [{c.status}] {c.name}{suffix}")


# ==============================================================================
# ACCESO A POSTGRESQL (gateway)
# ==============================================================================

class PostgresGateway:
    """Única capa que ejecuta SQL. Todas las sentencias son parametrizadas, se ejecutan en UNA
    transacción y no existe ningún método que escriba roles, políticas, esquema o system_admin_keys."""

    def __init__(self, conn, database_module, expected_secret: str) -> None:
        self._conn = conn
        self._db = database_module
        self._expected_secret = expected_secret

    @classmethod
    def connect(cls, dsn: str, read_only: bool, database_module, expected_secret: str) -> "PostgresGateway":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise ConfigurationError("Se requiere psycopg 3 (pip install 'psycopg[binary]').")
        conn = psycopg.connect(
            dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=10,
            application_name="nexusreach_bootstrap_production",
        )
        conn.read_only = bool(read_only)  # BEGIN READ ONLY en dry-run / verify-only
        gw = cls(conn, database_module, expected_secret)
        gw._exec("SELECT set_config('statement_timeout', '60s', true)")
        gw._exec("SELECT set_config('lock_timeout', '10s', true)")
        return gw

    # --- utilidades internas ---
    def _exec(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        return self._exec(sql, params).fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        return list(self._exec(sql, params).fetchall())

    # --- información del servidor y precondiciones ---
    def describe_target(self) -> str:
        info = getattr(self._conn, "info", None)
        if info is None:
            return "desconocido"
        return f"{info.host}:{info.port}/{info.dbname} (usuario {info.user})"

    def server_info(self) -> Dict[str, Any]:
        row = self._one(
            """
            SELECT current_database() AS db_name, current_user AS cur_user, session_user AS sess_user,
                   current_setting('server_version_num')::int AS server_version_num,
                   r.rolsuper AS is_superuser, r.rolbypassrls AS is_bypassrls
            FROM pg_roles r WHERE r.rolname = current_user
            """
        )
        return dict(row or {})

    def missing_objects(self) -> List[str]:
        rows = self._all(
            "SELECT t.name FROM unnest(%s::text[]) AS t(name) WHERE to_regclass('public.' || t.name) IS NULL",
            (list(REQUIRED_TABLES),),
        )
        missing = [r["name"] for r in rows]
        fn = self._one("SELECT to_regprocedure(%s) IS NOT NULL AS ok", (VERIFY_FUNCTION,))
        if not (fn and fn["ok"]):
            missing.append(VERIFY_FUNCTION)
        return missing

    def missing_privileges(self, required: Iterable[Tuple[str, str]], need_sequence: bool) -> List[str]:
        missing = []
        for table, priv in required:
            row = self._one("SELECT has_table_privilege(current_user, %s, %s) AS ok", (f"public.{table}", priv))
            if not row["ok"]:
                missing.append(f"{priv} ON {table}")
        row = self._one("SELECT has_function_privilege(current_user, %s, 'EXECUTE') AS ok", (VERIFY_FUNCTION,))
        if not row["ok"]:
            missing.append(f"EXECUTE ON {VERIFY_FUNCTION}")
        if need_sequence:
            seq = self._one("SELECT pg_get_serial_sequence('public.audit_logs', 'id') AS seq")
            if not seq or not seq["seq"]:
                missing.append("secuencia de audit_logs.id inexistente")
            else:
                row = self._one("SELECT has_sequence_privilege(current_user, %s, 'USAGE') AS ok", (seq["seq"],))
                if not row["ok"]:
                    missing.append("USAGE ON audit_logs_id_seq")
        return missing

    def rls_status(self, tables: Sequence[str]) -> Dict[str, Tuple[bool, bool]]:
        rows = self._all(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)
            """,
            (list(tables),),
        )
        return {r["relname"]: (bool(r["relrowsecurity"]), bool(r["relforcerowsecurity"])) for r in rows}

    def existing_policies(self, tables: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        rows = self._all(
            """
            SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = ANY(%s)
            """,
            (list(tables),),
        )
        return {f"{r['tablename']}.{r['policyname']}": dict(r) for r in rows}

    def rls_totals(self) -> Dict[str, int]:
        row = self._one(
            """
            SELECT count(*) FILTER (WHERE c.relrowsecurity AND c.relforcerowsecurity) AS forced,
                   count(*) AS total,
                   (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            """
        )
        return {k: int(v) for k, v in dict(row).items()}

    def role_attributes(self, role: str) -> Optional[Dict[str, Any]]:
        row = self._one("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = %s", (role,))
        return dict(row) if row else None

    def role_can_select(self, role: str, table: str) -> bool:
        row = self._one("SELECT has_table_privilege(%s, %s, 'SELECT') AS ok", (role, f"public.{table}"))
        return bool(row["ok"])

    # --- contexto RLS (mecanismo oficial de database.py) ---
    def activate_superadmin_context(self) -> None:
        # Asegurar que os.environ[SUPERADMIN_RLS_SECRET] coincida para database._configure_pg_context
        if self._db.get_superadmin_rls_secret() != self._expected_secret:
            os.environ[ENV_SUPERADMIN_SECRET] = self._expected_secret
            if self._db.get_superadmin_rls_secret() != self._expected_secret:
                raise ConfigurationError(
                    "database.get_superadmin_rls_secret() no coincide con el SUPERADMIN_RLS_SECRET validado. Abortando."
                )
        cur = self._conn.cursor()
        self._db._configure_pg_context(cur, is_super_admin=True)
        cur.execute("SELECT set_config('app.current_tenant_id', '', true)")

    def superadmin_context_valid(self) -> bool:
        row = self._one("SELECT public.verify_super_admin_context() AS ok")
        return bool(row["ok"])

    def probe_token(self, token: str) -> bool:
        """Comprueba si verify_super_admin_context() aceptaría `token`. Restaura el contexto oficial."""
        try:
            self._exec("SELECT set_config('app.super_admin_token', %s, true)", (token,))
            return self.superadmin_context_valid()
        finally:
            self.activate_superadmin_context()

    def probe_cross_tenant_isolation(self, tenant_a: str, tenant_b: str, user_a_id: str) -> Dict[str, Any]:
        """Ejecuta una prueba transaccional de aislamiento real entre dos tenants verificando USING y WITH CHECK."""
        report = {
            "a_cannot_see_b": True,
            "b_cannot_see_a": True,
            "anonymous_sees_zero": True,
            "insert_cross_tenant_blocked": True,
            "update_cross_tenant_blocked": True,
        }
        cur = self._conn.cursor()
        try:
            # 1. Sin tenant -> 0 filas
            self._db._configure_pg_context(cur, tenant_id=None, is_super_admin=False)
            cnt = self._one("SELECT count(*) AS c FROM usuarios WHERE id = %s", (user_a_id,))
            report["anonymous_sees_zero"] = (cnt["c"] == 0)

            # 2. Contexto Tenant B intentando ver usuario de Tenant A -> 0 filas
            self._db._configure_pg_context(cur, tenant_id=tenant_b, is_super_admin=False)
            cnt_b = self._one("SELECT count(*) AS c FROM usuarios WHERE id = %s", (user_a_id,))
            report["b_cannot_see_a"] = (cnt_b["c"] == 0)

            # 3. Contexto Tenant A viendo su propio usuario -> 1 fila
            self._db._configure_pg_context(cur, tenant_id=tenant_a, is_super_admin=False)
            cnt_a = self._one("SELECT count(*) AS c FROM usuarios WHERE id = %s", (user_a_id,))
            report["a_cannot_see_b"] = (cnt_a["c"] == 1)

            # 4. WITH CHECK: Tenant B intenta insertar un usuario con tenant_id = tenant_a
            self._db._configure_pg_context(cur, tenant_id=tenant_b, is_super_admin=False)
            dummy_uid = "usr_probe_" + secrets.token_hex(4)
            dummy_now = datetime.now().isoformat()
            try:
                # Intentar INSERT cruzado en savepoint
                self._exec("SAVEPOINT rls_insert_probe;")
                self._exec(
                    """
                    INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, created_at, updated_at)
                    VALUES (%s, %s, %s, 'Probe User', 'hash', 'salt', 'COMPANY_MEMBER', 1, 'ACTIVO', %s, %s);
                    """,
                    (dummy_uid, tenant_a, f"{dummy_uid}@test.local", dummy_now, dummy_now)
                )
                # Si llega aquí, la política WITH CHECK falló
                self._exec("ROLLBACK TO SAVEPOINT rls_insert_probe;")
                report["insert_cross_tenant_blocked"] = False
            except Exception:
                self._exec("ROLLBACK TO SAVEPOINT rls_insert_probe;")
                report["insert_cross_tenant_blocked"] = True

            # 5. WITH CHECK: Tenant A intenta cambiar su tenant_id a tenant_b
            self._db._configure_pg_context(cur, tenant_id=tenant_a, is_super_admin=False)
            try:
                self._exec("SAVEPOINT rls_update_probe;")
                self._exec("UPDATE usuarios SET tenant_id = %s WHERE id = %s;", (tenant_b, user_a_id))
                self._exec("ROLLBACK TO SAVEPOINT rls_update_probe;")
                report["update_cross_tenant_blocked"] = False
            except Exception:
                self._exec("ROLLBACK TO SAVEPOINT rls_update_probe;")
                report["update_cross_tenant_blocked"] = True

            return report
        finally:
            self.activate_superadmin_context()

    def try_acquire_lock(self) -> bool:
        row = self._one("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS ok", (ADVISORY_LOCK_KEY,))
        return bool(row["ok"])

    # --- lecturas de dominio ---
    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        row = self._one(
            "SELECT id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at FROM tenants WHERE id = %s",
            (tenant_id,),
        )
        return dict(row) if row else None

    def get_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._all(
            """
            SELECT id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma,
                   fecha_inicio, fecha_expiracion
            FROM suscripciones WHERE tenant_id = %s
            """,
            (tenant_id,),
        )]

    def find_users_by_email(self, email: str) -> List[Dict[str, Any]]:
        # Contiene password_hash/salt solo en memoria para verify_password(); jamás se registra.
        return [dict(r) for r in self._all(
            """
            SELECT id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado
            FROM usuarios WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        )]

    def count_active_seats(self, tenant_id: str) -> int:
        row = self._one(
            """
            SELECT count(*) AS total FROM usuarios
            WHERE puesto_activo = 1 AND estado = 'ACTIVO'
              AND (tenant_id = %s OR tenant_id IN (SELECT id FROM tenants WHERE parent_tenant_id = %s))
            """,
            (tenant_id, tenant_id),
        )
        return int(row["total"])

    def get_config(self, keys: Sequence[str]) -> Dict[str, Any]:
        rows = self._all("SELECT clave, valor FROM configuracion_seguridad WHERE clave = ANY(%s)", (list(keys),))
        return {r["clave"]: r["valor"] for r in rows}

    # --- escrituras (solo INSERT de entidades nuevas) ---
    def insert_tenant(self, row: Mapping[str, Any]) -> None:
        self._exec(
            """
            INSERT INTO tenants (id, parent_tenant_id, razon_social, tipo_tenant, estado, created_at, updated_at)
            VALUES (%s, NULL, %s, %s, %s, %s, %s)
            """,
            (row["id"], row["razon_social"], row["tipo_tenant"], row["estado"], row["created_at"], row["updated_at"]),
        )

    def insert_subscription(self, row: Mapping[str, Any]) -> None:
        self._exec(
            """
            INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados,
                                       precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (row["id"], row["tenant_id"], row["periodicidad"], row["estado"], row["puestos_contratados"],
             row["precio_unitario_plataforma"], row["fecha_inicio"], row["fecha_expiracion"],
             row["created_at"], row["updated_at"]),
        )

    def insert_user(self, row: Mapping[str, Any]) -> None:
        self._exec(
            """
            INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado,
                                  suscripcion_expira, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (row["id"], row["tenant_id"], row["email"], row["nombre"], row["password_hash"], row["salt"], row["rol"],
             row["puesto_activo"], row["estado"], row["suscripcion_expira"], row["created_at"], row["updated_at"]),
        )

    def insert_config_if_absent(self, key: str, value: str, description: str, now_iso: str) -> bool:
        cur = self._exec(
            """
            INSERT INTO configuracion_seguridad (clave, valor, descripcion, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (clave) DO NOTHING
            """,
            (key, value, description, now_iso),
        )
        return cur.rowcount == 1

    def insert_audit_log(self, row: Mapping[str, Any]) -> None:
        self._exec(
            """
            INSERT INTO audit_logs (tenant_id, usuario_id, accion, detalle_json, timestamp)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (row["tenant_id"], row["usuario_id"], row["accion"], row["detalle_json"], row["timestamp"]),
        )

    # --- transacción ---
    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ==============================================================================
# LÓGICA DE BOOTSTRAP
# ==============================================================================

def is_privileged(info: Mapping[str, Any]) -> bool:
    return bool(info.get("is_superuser")) or bool(info.get("is_bypassrls"))


def evaluate_preconditions(gw, info: Mapping[str, Any], mode: str, superadmin_secret: str) -> Report:
    """Precondiciones de seguridad y compatibilidad. Solo lecturas."""
    rep = Report("PRECONDICIONES")

    version = int(info.get("server_version_num") or 0)
    rep.add("PostgreSQL >= 16", OK if version >= MIN_SERVER_VERSION_NUM else FAIL, f"server_version_num={version}")

    missing = gw.missing_objects()
    if missing:
        rep.add("Objetos del esquema presentes", FAIL, "faltan: " + ", ".join(missing) + " (este script NO aplica el esquema)")
        return rep
    rep.add("Objetos del esquema presentes", OK, ", ".join(REQUIRED_TABLES) + f", {VERIFY_FUNCTION}")

    # P0.1 - Identidad de conexión estricta: rechazar superusuarios y roles con bypass RLS
    cur_user = info.get("cur_user")
    sess_user = info.get("sess_user")
    is_super = info.get("is_superuser")
    is_bypass = info.get("is_bypassrls")

    if is_super or is_bypass or cur_user in ("postgres", "nexus_admin") or sess_user in ("postgres", "nexus_admin"):
        detail = f"Conexión rechazada: cur_user='{cur_user}', sess_user='{sess_user}', SUPERUSER={is_super}, BYPASSRLS={is_bypass}. " \
                 f"El bootstrap productivo debe ejecutarse exclusivamente como '{APP_ROLE_NAME}'."
        rep.add("Rol de conexión con privilegios mínimos (P0.1)", FAIL, detail)
    else:
        rep.add("Rol de conexión con privilegios mínimos (P0.1)", OK, f"rol '{cur_user}' NOSUPERUSER NOBYPASSRLS (RLS activo)")

    required = WRITE_PRIVILEGES if mode in ("bootstrap", "dry-run") else READ_PRIVILEGES
    missing_priv = gw.missing_privileges(required, need_sequence=mode in ("bootstrap", "dry-run"))
    rep.add("Privilegios necesarios del rol de conexión", FAIL if missing_priv else OK,
            ("faltan: " + ", ".join(missing_priv)) if missing_priv else ", ".join(f"{p} {t}" for t, p in required))

    status = gw.rls_status(list(CORE_RLS_POLICIES))
    bad = [t for t in CORE_RLS_POLICIES if status.get(t) != (True, True)]
    rep.add("RLS + FORCE RLS en tablas del bootstrap", FAIL if bad else OK,
            ("sin protección: " + ", ".join(bad)) if bad else ", ".join(CORE_RLS_POLICIES))

    # P0.4 - Inspección profunda de pg_policies
    policies_map = gw.existing_policies(list(CORE_RLS_POLICIES))
    policy_issues = []
    for t, p in CORE_RLS_POLICIES.items():
        pol_key = f"{t}.{p}"
        pol = policies_map.get(pol_key)
        if not pol:
            policy_issues.append(f"ausente: {pol_key}")
        else:
            if pol.get("cmd") != "ALL":
                policy_issues.append(f"{pol_key} no es FOR ALL (cmd={pol.get('cmd')})")
            if str(pol.get("permissive")).upper() not in ("PERMISSIVE", "TRUE"):
                policy_issues.append(f"{pol_key} no es PERMISSIVE")
            qual = str(pol.get("qual") or "")
            if "verify_super_admin_context" not in qual:
                policy_issues.append(f"{pol_key} no invoca verify_super_admin_context() en USING")
            wchk = str(pol.get("with_check") or "")
            if "verify_super_admin_context" not in wchk:
                policy_issues.append(f"{pol_key} no invoca verify_super_admin_context() en WITH CHECK")

    rep.add("Políticas RLS del bootstrap registradas e íntegras (P0.4)", FAIL if policy_issues else OK,
            ("fallos de política: " + "; ".join(policy_issues)) if policy_issues else f"{len(CORE_RLS_POLICIES)} políticas auditadas (FOR ALL, USING + WITH CHECK)")

    totals = gw.rls_totals()
    rep.add("Inventario RLS (informativo)", OK,
            f"{totals['forced']}/{totals['total']} tablas con RLS+FORCE, {totals['policies']} políticas en 'public'")

    app_attrs = gw.role_attributes(APP_ROLE_NAME)
    if app_attrs is None:
        rep.add(f"Rol de aplicación '{APP_ROLE_NAME}' existe", FAIL, "no encontrado (este script NO crea roles)")
    else:
        unsafe = app_attrs.get("rolsuper") or app_attrs.get("rolbypassrls")
        rep.add(f"Rol '{APP_ROLE_NAME}' sin SUPERUSER/BYPASSRLS", FAIL if unsafe else OK,
                f"SUPERUSER={app_attrs.get('rolsuper')} BYPASSRLS={app_attrs.get('rolbypassrls')}")
        can_read = gw.role_can_select(APP_ROLE_NAME, "system_admin_keys")
        rep.add(f"'{APP_ROLE_NAME}' sin acceso a system_admin_keys", FAIL if can_read else OK,
                "SELECT concedido" if can_read else "SELECT denegado")

    # P0.2 - Validación criptográfica estricta sin excepciones para ningún session_user
    gw.activate_superadmin_context()
    valid = gw.superadmin_context_valid()
    rep.add("Contexto SuperAdmin criptográfico (P0.2)", OK if valid else FAIL,
            "SUPERADMIN_RLS_SECRET validado criptográficamente por verify_super_admin_context()" if valid
            else "SUPERADMIN_RLS_SECRET NO coincide con system_admin_keys (no se modifica ninguno de los dos)")

    default_accepted = any(gw.probe_token(t) for t in KNOWN_INSECURE_SUPERADMIN_SECRETS if t != superadmin_secret)
    rep.add("Hash SuperAdmin distinto del valor por defecto público", FAIL if default_accepted else OK,
            "system_admin_keys acepta un secreto público por defecto" if default_accepted else "secreto por defecto rechazado")

    # Comprobar fail-closed con token vacío o token erróneo
    fake_token_rejected = not gw.probe_token("fake_superadmin_token_for_hardening_audit_probe_99999")
    rep.add("Bypass fail-closed ante secreto incorrecto", OK if fake_token_rejected else FAIL,
            "token falso denegado correctamente" if fake_token_rejected else "token falso fue aceptado!")
    return rep


@dataclass
class EntityState:
    status: str  # ABSENT | COMPLETE | CONFLICT
    tenant: Optional[Dict[str, Any]]
    subscriptions: List[Dict[str, Any]]
    users: List[Dict[str, Any]]
    problems: List[str] = field(default_factory=list)

    @property
    def admin(self) -> Optional[Dict[str, Any]]:
        return self.users[0] if len(self.users) == 1 else None


def assess_entity_state(gw, tenant_id: str, email: str) -> EntityState:
    tenant = gw.get_tenant(tenant_id)
    subs = gw.get_subscriptions(tenant_id) if tenant else []
    users = gw.find_users_by_email(email)
    st = EntityState("CONFLICT", tenant, subs, users)

    if tenant is None and not users:
        st.status = "ABSENT"
        return st

    # P1.1: Clasificación rigurosa de CONFLICT
    if tenant is None and users:
        st.problems.append("El email solicitado ya está registrado y el tenant solicitado no existe (email duplicado o huérfano).")
    if tenant is not None and not users:
        st.problems.append("El tenant solicitado ya existe sin el administrador solicitado (tenant duplicado o estado parcial).")
    if len(users) > 1:
        st.problems.append(f"Existen {len(users)} usuarios con el mismo email (comparación sin mayúsculas).")
    if len(subs) > 1:
        st.problems.append(f"El tenant posee {len(subs)} suscripciones (se esperaba exactamente 1 suscripción inicial).")
    if tenant is not None and not subs:
        st.problems.append("El tenant existe pero no tiene ninguna suscripción asociada (estado parcial).")
    if tenant is not None and len(users) == 1:
        user = users[0]
        if user.get("tenant_id") != tenant_id:
            st.problems.append("El email solicitado pertenece a un usuario de otro tenant (o sin tenant).")
        if user.get("rol") != ADMIN_ROLE:
            st.problems.append(f"El usuario existente no tiene rol {ADMIN_ROLE} (rol actual: {user.get('rol')}).")
        if user.get("estado") != USER_STATE:
            st.problems.append(f"El usuario existente no está en estado {USER_STATE} (estado actual: {user.get('estado')}).")
        if user.get("puesto_activo") != 1:
            st.problems.append(f"El usuario existente tiene puesto_activo={user.get('puesto_activo')} (se requiere 1).")
    if tenant is not None:
        if tenant.get("tipo_tenant") != TENANT_TYPE:
            st.problems.append(f"El tenant existente tiene tipo_tenant='{tenant.get('tipo_tenant')}' (se requiere {TENANT_TYPE}).")
        if tenant.get("estado") != TENANT_STATE:
            st.problems.append(f"El tenant existente tiene estado='{tenant.get('estado')}' (se requiere {TENANT_STATE}).")
        if tenant.get("parent_tenant_id") is not None:
            st.problems.append(f"El tenant existente no es raíz (parent_tenant_id='{tenant.get('parent_tenant_id')}').")

    if not st.problems:
        st.status = "COMPLETE"
    return st


def _parse_iso(value: Any) -> Tuple[Optional[datetime], bool]:
    """Retorna (datetime naive local, tenía_zona_horaria)."""
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return None, False
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None), True
    return dt, False


def verify_entities(gw, info: Mapping[str, Any], params: BootstrapParams, *, password: Optional[str],
                    password_mismatch_is_error: bool, auth_module, now: Optional[datetime] = None) -> Report:
    """Verifica tenant, suscripción, administrador, relaciones, autenticación, configuración y aislamiento.
    No revela hashes ni secretos. No exige un número total de tenants/usuarios."""
    now = now or datetime.now()
    rep = Report("VERIFICACIÓN DE ENTIDADES")
    tid, email = params.tenant_id, params.admin_email

    tenant = gw.get_tenant(tid)
    if tenant is None:
        rep.add(f"Tenant '{tid}' existe", FAIL, "no encontrado")
        return rep
    rep.add(f"Tenant '{tid}' existe", OK)
    rep.add("Tenant tipo EMPRESA", OK if tenant.get("tipo_tenant") == TENANT_TYPE else FAIL, str(tenant.get("tipo_tenant")))
    rep.add("Tenant estado ACTIVO", OK if tenant.get("estado") == TENANT_STATE else FAIL, str(tenant.get("estado")))
    rep.add("Tenant sin tenant padre (raíz)", OK if tenant.get("parent_tenant_id") is None else FAIL,
            "parent_tenant_id NULL" if tenant.get("parent_tenant_id") is None else "tiene tenant padre")
    dates_ok = all(_parse_iso(tenant.get(k))[0] is not None for k in ("created_at", "updated_at"))
    rep.add("Tenant fechas ISO válidas", OK if dates_ok else FAIL)
    if params.tenant_name:
        same = (tenant.get("razon_social") or "").strip() == params.tenant_name.strip()
        rep.add("Razón social coincide con la solicitada", OK if same else WARN,
                "" if same else "difiere (no se modifica)")

    subs = gw.get_subscriptions(tid)
    if len(subs) != 1:
        rep.add("Suscripción asociada única", FAIL, f"encontradas: {len(subs)}")
        sub = None
    else:
        sub = subs[0]
        rep.add("Suscripción asociada única", OK, f"id={sub['id']}")
        rep.add("Suscripción vinculada al tenant", OK if sub.get("tenant_id") == tid else FAIL)
        estado = sub.get("estado")
        rep.add("Suscripción en estado válido para login", OK if estado in LOGIN_VALID_SUBSCRIPTION_STATES else FAIL, str(estado))
        rep.add("Periodicidad válida", OK if sub.get("periodicidad") in PERIODICITY_DAYS else FAIL, str(sub.get("periodicidad")))
        start, start_tz = _parse_iso(sub.get("fecha_inicio"))
        exp, exp_tz = _parse_iso(sub.get("fecha_expiracion"))
        if start is None or exp is None:
            rep.add("Fechas de suscripción válidas", FAIL, "formato ISO inválido")
        else:
            if exp_tz or start_tz:
                rep.add("Fechas de suscripción sin zona horaria", WARN,
                        "authenticate_user compara con datetime naive; con zona horaria omite el control de vencimiento")
            coherent = start <= now < exp
            rep.add("Suscripción vigente", OK if coherent else FAIL,
                    f"expira {exp.isoformat(timespec='minutes')}" if coherent else "fuera de vigencia")
            days_left = (exp - now).days
            if coherent and days_left < 15:
                rep.add("Margen de vigencia", WARN, f"quedan {days_left} días; al vencer se bloquea el login")
        seats = int(sub.get("puestos_contratados") or 0)
        used = gw.count_active_seats(tid)
        rep.add("Puestos contratados suficientes", OK if 1 <= used <= seats else (WARN if seats >= 1 else FAIL),
                f"{used}/{seats} en uso")

    users = gw.find_users_by_email(email)
    if len(users) != 1:
        rep.add(f"Administrador '{email}' único", FAIL, f"encontrados: {len(users)}")
        admin = None
    else:
        admin = users[0]
        rep.add(f"Administrador '{email}' único", OK, f"id={admin['id']}")
        rep.add("Administrador asociado al tenant", OK if admin.get("tenant_id") == tid else FAIL)
        rep.add(f"Administrador con rol {ADMIN_ROLE}", OK if admin.get("rol") == ADMIN_ROLE else FAIL, str(admin.get("rol")))
        rep.add("Administrador estado ACTIVO", OK if admin.get("estado") == USER_STATE else FAIL, str(admin.get("estado")))
        rep.add("Administrador con puesto activo", OK if admin.get("puesto_activo") == 1 else FAIL)
        rep.add("Email almacenado en minúsculas", OK if admin.get("email") == email else WARN)
        hash_ok = bool(HEX64_RE.match(str(admin.get("password_hash") or "")))
        salt_ok = bool(str(admin.get("salt") or "").strip())
        rep.add("Formato de hash compatible con auth_service (PBKDF2-SHA256 hex)", OK if (hash_ok and salt_ok) else FAIL)
        if password is not None:
            matches = bool(auth_module.verify_password(password, admin.get("salt") or "", admin.get("password_hash") or ""))
            if matches:
                rep.add("Contraseña suministrada verificada con auth_service.verify_password()", OK)
            else:
                rep.add("Contraseña suministrada verificada con auth_service.verify_password()",
                        FAIL if password_mismatch_is_error else WARN,
                        "no coincide" + ("" if password_mismatch_is_error else " (se conserva la contraseña existente)"))
        else:
            rep.add("Verificación de contraseña", SKIP, "no se suministró contraseña")

    # Elegibilidad de login (réplica de solo lectura de auth_service.authenticate_user)
    eligible = (
        admin is not None and sub is not None
        and admin.get("estado") != "BLOQUEADO" and admin.get("puesto_activo") == 1
        and admin.get("tenant_id") == tid and tenant.get("estado") == TENANT_STATE
        and sub.get("estado") in LOGIN_VALID_SUBSCRIPTION_STATES
        and (_parse_iso(sub.get("fecha_expiracion"))[0] or now) > now
    )
    rep.add("Administrador elegible para login (reglas de authenticate_user)", OK if eligible else FAIL)

    cfg = assess_safety_config(gw.get_config([s.key for s in ESSENTIAL_SAFETY_CONFIG]))
    rep.add("Configuración de seguridad: claves esenciales presentes", OK if not cfg.to_create else WARN,
            ("ausentes (se aplican fallbacks del código): " + ", ".join(cfg.to_create)) if cfg.to_create
            else f"{len(cfg.kept)} claves")
    for e in cfg.errors:
        rep.add("Configuración de seguridad válida", FAIL, e)
    for w in cfg.warnings:
        rep.add("Configuración de seguridad", WARN, w)

    # P0.3 - Aislamiento RLS efectivo sobre las entidades creadas
    if is_privileged(info):
        rep.add("Aislamiento RLS de las entidades (P0.3)", FAIL, "el rol de conexión es privilegiado e ignora RLS (SUPERUSER/BYPASSRLS)")
    else:
        uid = admin["id"] if admin else None
        iso_report = gw.probe_cross_tenant_isolation(
            tenant_a=tid,
            tenant_b="ten_isolated_probe_tenant_b",
            user_a_id=uid
        )
        rep.add("Sin contexto de tenant: 0 filas visibles (fail-closed)",
                OK if iso_report["anonymous_sees_zero"] else FAIL)
        rep.add("Tenant B no puede consultar usuarios de Tenant A",
                OK if iso_report["b_cannot_see_a"] else FAIL)
        rep.add("Tenant A puede consultar sus propios usuarios",
                OK if iso_report["a_cannot_see_b"] else FAIL)
        rep.add("Política WITH CHECK: rechaza INSERT cruzado de Tenant B a Tenant A",
                OK if iso_report["insert_cross_tenant_blocked"] else FAIL)
        rep.add("Política WITH CHECK: rechaza UPDATE cruzado transfiriendo tenant",
                OK if iso_report["update_cross_tenant_blocked"] else FAIL)
    return rep


def build_rows(params: BootstrapParams, password_hash: str, salt: str, now: datetime) -> Dict[str, Dict[str, Any]]:
    now_iso = now.isoformat()
    expires_iso = (now + timedelta(days=PERIODICITY_DAYS[params.periodicity])).isoformat()
    tenant = {
        "id": params.tenant_id, "razon_social": params.tenant_name, "tipo_tenant": TENANT_TYPE,
        "estado": TENANT_STATE, "created_at": now_iso, "updated_at": now_iso,
    }
    subscription = {
        "id": "sub_" + secrets.token_hex(8), "tenant_id": params.tenant_id, "periodicidad": params.periodicity,
        "estado": SUBSCRIPTION_STATE, "puestos_contratados": params.seats,
        "precio_unitario_plataforma": params.unit_price, "fecha_inicio": now_iso,
        "fecha_expiracion": expires_iso, "created_at": now_iso, "updated_at": now_iso,
    }
    user = {
        "id": "usr_" + secrets.token_hex(8), "tenant_id": params.tenant_id, "email": params.admin_email,
        "nombre": params.admin_name, "password_hash": password_hash, "salt": salt, "rol": ADMIN_ROLE,
        "puesto_activo": 1, "estado": USER_STATE, "suscripcion_expira": expires_iso,
        "created_at": now_iso, "updated_at": now_iso,
    }
    return {"tenant": tenant, "subscription": subscription, "user": user}


def log_plan(log: logging.Logger, params: BootstrapParams, state: EntityState, cfg: ConfigAssessment,
             now: datetime, simulated: bool) -> None:
    verb = "SIMULAR" if simulated else "EJECUTAR"
    log.info(f"\n[PLAN — {verb}]")
    if state.status == "ABSENT":
        exp = now + timedelta(days=PERIODICITY_DAYS[params.periodicity])
        log.info(f"  + CREAR tenant id={params.tenant_id} razon_social='{params.tenant_name}' tipo={TENANT_TYPE} estado={TENANT_STATE} parent=NULL")
        log.info(f"  + CREAR suscripción tenant={params.tenant_id} periodicidad={params.periodicity} estado={SUBSCRIPTION_STATE} "
                 f"puestos={params.seats} precio_unitario={params.unit_price} expira≈{exp.isoformat(timespec='minutes')}")
        log.info(f"  + CREAR usuario email={params.admin_email} nombre='{params.admin_name}' rol={ADMIN_ROLE} estado={USER_STATE} "
                 "puesto_activo=1 (hash PBKDF2 vía auth_service.hash_password)")
        log.info("  + CREAR audit_logs accion=BOOTSTRAP_PRODUCCION")
    else:
        log.info("  = Tenant, suscripción y administrador ya existen: se conservan sin cambios.")
    for k, v in cfg.to_create.items():
        log.info(f"  + CREAR configuracion_seguridad {k}='{v}'")
    for k, v in cfg.kept.items():
        log.info(f"  = CONSERVAR configuracion_seguridad {k}='{v}'")


# ==============================================================================
# ORQUESTACIÓN
# ==============================================================================

@dataclass
class RunOptions:
    mode: str  # dry-run | bootstrap | verify-only
    confirm_database: Optional[str] = None


def run_with_gateway(gw, opts: RunOptions, params: BootstrapParams, password: Optional[str], superadmin_secret: str,
                     log: logging.Logger, auth_module, now: Optional[datetime] = None) -> int:
    """Ejecuta el modo solicitado dentro de la transacción única del gateway. Nunca hace commit salvo en
    --bootstrap con verificación satisfactoria."""
    now = now or datetime.now()
    committed = False
    try:
        info = gw.server_info()
        db_name = info.get("db_name")
        log.info(f"Base de datos destino: {db_name} | rol: {info.get('cur_user')} | session_user: {info.get('sess_user')}")
        if db_name == PRODUCTION_DB_NAME:
            log.info("  >>> DESTINO IDENTIFICADO COMO BASE DE PRODUCCIÓN <<<")

        if opts.mode == "bootstrap":
            if not opts.confirm_database:
                raise ConfigurationError("--bootstrap requiere --confirm-database <nombre_de_la_base_destino>.")
            if opts.confirm_database != db_name:
                raise ConfigurationError(
                    f"--confirm-database '{opts.confirm_database}' no coincide con la base conectada '{db_name}'. Abortando."
                )

        pre = evaluate_preconditions(gw, info, opts.mode, superadmin_secret)
        pre.emit(log)
        if not pre.ok:
            raise PreconditionError(f"{len(pre.failures)} precondición(es) no satisfecha(s). No se realizó ningún cambio.")

        if opts.mode == "verify-only":
            rep = verify_entities(gw, info, params, password=password, password_mismatch_is_error=True,
                                  auth_module=auth_module, now=now)
            rep.emit(log)
            if not rep.ok:
                raise VerificationError(f"Verificación fallida: {len(rep.failures)} comprobación(es).")
            log.info("\n[OK] Verificación completada sin fallos.")
            return EXIT_OK

        if opts.mode == "bootstrap":
            if not gw.try_acquire_lock():
                raise PreconditionError("Otra ejecución del bootstrap mantiene el bloqueo consultivo. Abortando.")

        # Evaluación de estado (en --bootstrap, bajo bloqueo consultivo y dentro de la transacción)
        state = assess_entity_state(gw, params.tenant_id, params.admin_email)
        cfg = assess_safety_config(gw.get_config([s.key for s in ESSENTIAL_SAFETY_CONFIG]))
        log.info(f"\n[ESTADO] Entidades: {state.status}")
        for p in state.problems:
            log.info(f"  ✕ {p}")
        for w in cfg.warnings:
            log.info(f"  ! {w}")
        for e in cfg.errors:
            log.info(f"  ✕ {e}")

        if state.status == "CONFLICT":
            raise StateConflictError(
                "Estado parcial o conflictivo: no se crea, sobrescribe ni repara nada. Revise el procedimiento de recuperación."
            )
        if cfg.errors:
            raise PreconditionError("Configuración de seguridad existente inválida: se detiene la inicialización.")
        if state.status == "ABSENT":
            if password is None:
                raise ConfigurationError(
                    f"Contraseña inicial no configurada. Defina {ENV_ADMIN_PASSWORD} o --admin-password-file "
                    "(no se genera ninguna contraseña)."
                )
            problems = validate_admin_password(password, params.admin_email, params.tenant_id, superadmin_secret)
            if problems:
                raise ConfigurationError("Contraseña inicial insegura: " + "; ".join(problems) + ".")

        log_plan(log, params, state, cfg, now, simulated=(opts.mode == "dry-run"))

        if opts.mode == "dry-run":
            log.info("\n[DRY-RUN] Transacción READ ONLY: no se persistió ningún cambio.")
            return EXIT_OK

        if state.status == "COMPLETE" and not cfg.to_create:
            log.info("\n[IDEMPOTENTE] Estado ya inicializado: no hay cambios que aplicar.")
            rep = verify_entities(gw, info, params, password=password, password_mismatch_is_error=False,
                                  auth_module=auth_module, now=now)
            rep.emit(log)
            if not rep.ok:
                raise VerificationError("El estado existente no supera la verificación (no se modifica).")
            return EXIT_OK

        # --- ESCRITURA: transacción única ---
        rows = None
        if state.status == "ABSENT":
            pwd_hash, salt = auth_module.hash_password(password)
            rows = build_rows(params, pwd_hash, salt, now)
            gw.insert_tenant(rows["tenant"])
            gw.insert_subscription(rows["subscription"])
            gw.insert_user(rows["user"])

        created_keys = []
        desc = {s.key: s.description for s in ESSENTIAL_SAFETY_CONFIG}
        for key, value in cfg.to_create.items():
            if gw.insert_config_if_absent(key, value, desc[key], now.isoformat()):
                created_keys.append(key)
            else:
                raise StateConflictError(f"La clave '{key}' fue creada concurrentemente; se aborta sin sobrescribir.")

        gw.insert_audit_log({
            "tenant_id": params.tenant_id,
            "usuario_id": rows["user"]["id"] if rows else (admin["id"] if admin else None),
            "accion": "BOOTSTRAP_PRODUCCION",
            "detalle_json": json.dumps({
                "script": SCRIPT_NAME, "version": SCRIPT_VERSION, "task": TASK_ID,
                "entidades_creadas": state.status == "ABSENT",
                "admin_user_id": rows["user"]["id"] if rows else None,
                "subscription_id": rows["subscription"]["id"] if rows else None,
                "config_creada": created_keys,
            }, ensure_ascii=False),
            "timestamp": now.isoformat(),
        })

        # Verificación dentro de la misma transacción: si falla, ROLLBACK completo.
        rep = verify_entities(gw, info, params, password=password,
                              password_mismatch_is_error=(state.status == "ABSENT"),
                              auth_module=auth_module, now=now)
        rep.emit(log)
        if not rep.ok:
            raise VerificationError("La verificación previa al COMMIT falló: se revierte toda la transacción.")

        gw.commit()
        committed = True
        log.info("\n[OK] BOOTSTRAP DE PRODUCCIÓN CONFIRMADO (COMMIT ÚNICO).")
        if rows:
            log.info(f"  tenant_id={rows['tenant']['id']} subscription_id={rows['subscription']['id']} admin_user_id={rows['user']['id']}")
        log.info(f"  configuraciones creadas: {', '.join(created_keys) if created_keys else 'ninguna'}")
        return EXIT_OK
    finally:
        if not committed:
            try:
                gw.rollback()
            except Exception:
                pass


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NexusReach Pro - Bootstrap de producción PostgreSQL (TASK-05B-07 / TASK-05B-08). "
                    f"Conexión: {ENV_DSN}. Contraseña inicial: {ENV_ADMIN_PASSWORD} o --admin-password-file.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Inspecciona y simula en transacción READ ONLY")
    mode.add_argument("--bootstrap", action="store_true", help="Ejecuta la inicialización (requiere --confirm-database)")
    mode.add_argument("--verify-only", action="store_true", help="Verifica el estado en transacción READ ONLY")
    parser.add_argument("--tenant-id", help=f"ID del tenant principal (o {ENV_TENANT_ID})")
    parser.add_argument("--tenant-name", help=f"Razón social (o {ENV_TENANT_NAME})")
    parser.add_argument("--admin-email", help=f"Email del administrador (o {ENV_ADMIN_EMAIL})")
    parser.add_argument("--admin-name", help=f"Nombre del administrador (o {ENV_ADMIN_NAME})")
    parser.add_argument("--periodicity", help=f"MENSUAL | ANUAL (o {ENV_PERIODICITY}); obligatorio para crear")
    parser.add_argument("--seats", help=f"Puestos contratados (o {ENV_SEATS}; defecto {DEFAULT_SEATS})")
    parser.add_argument("--unit-price", help=f"Precio unitario plataforma (o {ENV_UNIT_PRICE}; defecto {DEFAULT_UNIT_PRICE})")
    parser.add_argument("--admin-password-file", help="Archivo 0600 con la contraseña inicial (una línea)")
    parser.add_argument("--confirm-database", help="Nombre exacto de la base destino (obligatorio con --bootstrap)")
    return parser.parse_args(argv)


def _import_project_modules():
    try:
        import database  # noqa: F401  (carga .env del proyecto vía python-dotenv si está instalado)
        import auth_service
    except Exception as exc:  # RuntimeError de configuración de database.py, ImportError, etc.
        raise ConfigurationError(f"No se pudieron cargar los módulos del proyecto (database/auth_service): {exc}")
    return database, auth_service


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None,
         gateway_factory: Optional[Callable[..., Any]] = None, stream=None,
         project_modules: Optional[Tuple[Any, Any]] = None, now: Optional[datetime] = None) -> int:
    args = parse_args(argv)
    log, redactor = build_logger(stream)
    mode = "dry-run" if args.dry_run else ("bootstrap" if args.bootstrap else "verify-only")
    gw = None
    try:
        database_module, auth_module = project_modules or _import_project_modules()
        env = os.environ if environ is None else environ

        redactor.register(env.get("PGPASSWORD"))
        dsn = (env.get(ENV_DSN) or "").strip()
        redactor.register(extract_dsn_password(dsn))
        superadmin_secret = validate_superadmin_secret(env)
        redactor.register(superadmin_secret)
        password = load_admin_password(args.admin_password_file, env)
        redactor.register(password)

        log.info("=" * 78)
        log.info(f"NEXUSREACH PRO — BOOTSTRAP DE PRODUCCIÓN POSTGRESQL ({TASK_ID}) v{SCRIPT_VERSION}")
        log.info("=" * 78)
        log.info(f"Modo: {mode}")

        if not dsn:
            raise ConfigurationError(
                f"{ENV_DSN} no está definida. Defina la conexión administrativa del bootstrap "
                "(no se usa DATABASE_URL como fallback)."
            )
        params = build_params(args, env, mode)
        if password is not None and mode in ("dry-run", "bootstrap"):
            problems = validate_admin_password(password, params.admin_email, params.tenant_id, superadmin_secret)
            if problems:
                raise ConfigurationError("Contraseña inicial insegura: " + "; ".join(problems) + ".")
        log.info(f"{ENV_DSN}: presente | {ENV_SUPERADMIN_SECRET}: presente | contraseña inicial: "
                 f"{'presente' if password else 'no suministrada'}")

        factory = gateway_factory or (lambda d, ro: PostgresGateway.connect(d, ro, database_module, superadmin_secret))
        gw = factory(dsn, mode != "bootstrap")
        if hasattr(gw, "describe_target"):
            log.info(f"Conexión: {gw.describe_target()}")
        opts = RunOptions(mode=mode, confirm_database=args.confirm_database)
        return run_with_gateway(gw, opts, params, password, superadmin_secret, log, auth_module, now=now)
    except BootstrapError as exc:
        log.info(f"\n[ERROR] {exc}")
        return exc.exit_code
    except Exception as exc:  # errores de conexión / SQL: mensaje redactado, sin traceback ni parámetros
        log.info(f"\n[ERROR INESPERADO] {type(exc).__name__}: {exc}")
        log.info("La transacción fue revertida. No se confirmó ningún cambio.")
        return EXIT_RUNTIME
    finally:
        if gw is not None and hasattr(gw, "close"):
            gw.close()


if __name__ == "__main__":
    sys.exit(main())
