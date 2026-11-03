"""
Servicio de Firma Criptográfica de Comandos y Gestión de Dispositivos (Workstream 5.1 - NexusReach Pro)

Este módulo implementa el canal de comandos seguro según las Directrices v1.3:
1. Firma digital Ed25519 de comandos salientes del backend hacia el cliente.
2. Canonicalización determinista de payloads JSON.
3. Prevención de repetición (Anti-Replay) mediante Nonce y TTL estricto (<= 120s).
4. Lista cerrada de acciones tipadas (Closed Action Enumeration).
5. Verificación de firmas de dispositivos para los resultados reportados.
6. Gestión de emparejamiento y revocación de dispositivos (Kill-Switch por dispositivo).
"""

import os
import json
import time
import uuid
import base64
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, Set

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from database import get_db

# ==============================================================================
# 1. CONSTANTES Y CONFIGURACIÓN CRIPTOGRÁFICA
# ==============================================================================

COMMAND_TTL_SECONDS = 120  # TTL máximo de 120 segundos

ALLOWED_ACTIONS: Set[str] = {
    "LI_VISIT_PROFILE",
    "LI_SEND_INVITE",
    "LI_SEND_MESSAGE",
    "LI_SYNC_CONNECTIONS",
    "LI_READ_CONTACT_INFO",
    "LI_ENRICH_PROFILE",
    "LI_EXTRACT_PROFILE",
    "WA_SEND_MESSAGE",
    "WA_CHECK_NUMBER",
    "ZOHO_FIND_LEAD",
    "ZOHO_UPSERT_LEAD",
    "ZOHO_SET_STATUS",
    "ZOHO_ADD_NOTE",
    "PAUSE",
    "RESUME"
}

KEYS_DIR = os.path.join(os.path.dirname(__file__), "storage", "keys")
SERVER_PRIVATE_KEY_PATH = os.path.join(KEYS_DIR, "server_signing_key.pem")
SERVER_PUBLIC_KEY_PATH = os.path.join(KEYS_DIR, "server_public_key.pem")

_server_private_key: Optional[ed25519.Ed25519PrivateKey] = None
_server_public_key: Optional[ed25519.Ed25519PublicKey] = None


def ensure_keys_directory():
    if not os.path.exists(KEYS_DIR):
        os.makedirs(KEYS_DIR, exist_ok=True)


def get_server_keypair() -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """
    Retorna la clave privada y pública del servidor.
    En entorno local/dev, las carga de archivo o las genera automáticamente en el directorio storage/keys.
    En producción en AWS, esta interfaz se desacopla hacia AWS KMS / CloudHSM.
    """
    global _server_private_key, _server_public_key
    if _server_private_key is not None and _server_public_key is not None:
        return _server_private_key, _server_public_key

    ensure_keys_directory()

    # Si existe variable de entorno con la clave privada (base64 raw 32 bytes)
    env_priv_b64 = os.getenv("SERVER_SIGNING_PRIVATE_KEY_B64", "").strip()
    if env_priv_b64:
        raw_priv = base64.b64decode(env_priv_b64)
        _server_private_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_priv)
        _server_public_key = _server_private_key.public_key()
        return _server_private_key, _server_public_key

    # Si existe archivo guardado
    if os.path.exists(SERVER_PRIVATE_KEY_PATH):
        with open(SERVER_PRIVATE_KEY_PATH, "rb") as f:
            _server_private_key = serialization.load_pem_private_key(f.read(), password=None)
            _server_public_key = _server_private_key.public_key()
            return _server_private_key, _server_public_key

    # Generar nuevo par de claves Ed25519 para el servidor
    _server_private_key = ed25519.Ed25519PrivateKey.generate()
    _server_public_key = _server_private_key.public_key()

    # Guardar en disco
    pem_priv = _server_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    pem_pub = _server_public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with open(SERVER_PRIVATE_KEY_PATH, "wb") as f:
        f.write(pem_priv)
    with open(SERVER_PUBLIC_KEY_PATH, "wb") as f:
        f.write(pem_pub)

    return _server_private_key, _server_public_key


def get_server_public_key_b64() -> str:
    """Retorna la clave pública raw de 32 bytes en base64 para fijar (pinning) en el cliente Electron."""
    _, pub_key = get_server_keypair()
    raw_pub = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw_pub).decode("utf-8")


# ==============================================================================
# 2. CANONICALIZACIÓN Y FIRMA DETERMINISTA
# ==============================================================================

def canonicalize_json(data: Dict[str, Any]) -> bytes:
    """
    Serializa un objeto JSON de manera canónica y determinista:
    - Claves ordenadas lexicográficamente
    - Separadores compactos sin espacios (',', ':')
    - Codificación en UTF-8 sin caracteres escapados innecesarios
    """
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def sign_command_payload(payload_dict: Dict[str, Any]) -> str:
    """Firma un payload canónico con la clave privada Ed25519 del servidor y retorna base64."""
    priv_key, _ = get_server_keypair()
    canonical_bytes = canonicalize_json(payload_dict)
    signature = priv_key.sign(canonical_bytes)
    return base64.b64encode(signature).decode("utf-8")


def verify_server_command_signature(command_payload: Dict[str, Any], signature_b64: str) -> bool:
    """Verifica si un comando fue firmado por la clave autorizada del servidor."""
    try:
        _, pub_key = get_server_keypair()
        clean_payload = {k: v for k, v in command_payload.items() if k != "signature"}
        canonical_bytes = canonicalize_json(clean_payload)
        sig_bytes = base64.b64decode(signature_b64)
        pub_key.verify(sig_bytes, canonical_bytes)
        return True
    except Exception:
        return False


def verify_device_signature(payload_dict: Dict[str, Any], signature_b64: str, device_public_key_b64: str) -> bool:
    """Verifica que el resultado reportado por el cliente haya sido firmado por la clave de su dispositivo."""
    try:
        pub_bytes = base64.b64decode(device_public_key_b64)
        sig_bytes = base64.b64decode(signature_b64)
        canonical_bytes = canonicalize_json(payload_dict)
        dev_pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        dev_pub_key.verify(sig_bytes, canonical_bytes)
        return True
    except Exception:
        return False


# ==============================================================================
# 3. GESTIÓN Y EMPAREJAMIENTO DE DISPOSITIVOS
# ==============================================================================

def register_device(
    device_id: str,
    tenant_id: str,
    public_key_ed25519: str,
    device_name: Optional[str] = None,
    client_version: Optional[str] = "1.0.0",
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Registra o actualiza un dispositivo local con su clave pública Ed25519."""
    if not device_id or not tenant_id or not public_key_ed25519:
        raise ValueError("device_id, tenant_id y public_key_ed25519 son obligatorios")

    # Política de versión mínima soportada (Workstream 5.11)
    import observability_service
    is_supported, version_msg = observability_service.check_client_version_support(client_version)
    if not is_supported:
        return {
            "ok": False,
            "error": "CLIENT_VERSION_DEPRECATED",
            "message": version_msg,
            "min_client_version": observability_service.MIN_CLIENT_VERSION,
            "download_url": "https://releases.nexusreach.io/desktop/"
        }

    # Validar formato base64 de la clave pública (32 bytes raw)
    try:
        raw_key = base64.b64decode(public_key_ed25519)
        if len(raw_key) != 32:
            raise ValueError(f"Longitud inválida de clave pública Ed25519: {len(raw_key)} bytes (requerido 32)")
        # Test construct public key
        ed25519.Ed25519PublicKey.from_public_bytes(raw_key)
    except Exception as e:
        raise ValueError(f"Clave pública Ed25519 inválida: {str(e)}")

    now_iso = datetime.now(timezone.utc).isoformat()
    d_name = device_name or f"Dispositivo {device_id[:8]}"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, tenant_id, status FROM devices WHERE id = ?", (device_id,))
        existing = cursor.fetchone()

        if existing:
            existing_tenant = existing["tenant_id"] if isinstance(existing, dict) else existing[1]
            status = existing["status"] if isinstance(existing, dict) else existing[2]
            if existing_tenant != tenant_id:
                raise PermissionError(
                    f"El dispositivo '{device_id}' ya está vinculado a otro tenant y no puede ser reasignado."
                )
            if status == "REVOKED":
                return {
                    "ok": False,
                    "error": "Dispositivo revocado por el administrador. Requiere desemparejar y generar nuevo par de claves.",
                    "status": "REVOKED"
                }

            cursor.execute("""
                UPDATE devices 
                SET device_name = ?, public_key_ed25519 = ?, client_version = ?, 
                    last_seen_at = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ?
            """, (d_name, public_key_ed25519, client_version, now_iso, now_iso, device_id, tenant_id))
        else:
            cursor.execute("""
                INSERT INTO devices (id, tenant_id, user_id, device_name, public_key_ed25519, status, client_version, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
            """, (device_id, tenant_id, user_id, d_name, public_key_ed25519, client_version, now_iso, now_iso, now_iso))

        conn.commit()

    return {
        "ok": True,
        "device_id": device_id,
        "status": "ACTIVE",
        "server_public_key": get_server_public_key_b64()
    }


def is_device_active(device_id: str, tenant_id: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Comprueba si un dispositivo está registrado y en estado ACTIVO.
    Retorna (es_activo, motivo, public_key).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        if tenant_id:
            cursor.execute("SELECT status, public_key_ed25519 FROM devices WHERE id = ? AND tenant_id = ?", (device_id, tenant_id))
        else:
            cursor.execute("SELECT status, public_key_ed25519 FROM devices WHERE id = ?", (device_id,))
        row = cursor.fetchone()
        if not row:
            return False, "Dispositivo no registrado o no emparejado", None
        status = row["status"] if isinstance(row, dict) else row[0]
        pub_key = row["public_key_ed25519"] if isinstance(row, dict) else row[1]
        if status == "REVOKED":
            return False, "Dispositivo revocado", pub_key
        return True, "Activo", pub_key


def revoke_device(device_id: str, tenant_id: Optional[str] = None) -> bool:
    """Revoca el acceso de un dispositivo impidiendo que acepte o reporte comandos."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        if tenant_id:
            cursor.execute("UPDATE devices SET status = 'REVOKED', updated_at = ? WHERE id = ? AND tenant_id = ?", (now_iso, device_id, tenant_id))
        else:
            cursor.execute("UPDATE devices SET status = 'REVOKED', updated_at = ? WHERE id = ?", (now_iso, device_id))
        conn.commit()
    return True


# ==============================================================================
# 4. CONSTRUCTOR Y DESPACHADOR DE COMANDOS FIRMADOS
# ==============================================================================

def create_signed_command(
    tenant_id: str,
    device_id: str,
    action: str,
    params: Dict[str, Any],
    ttl_seconds: int = COMMAND_TTL_SECONDS
) -> Dict[str, Any]:
    """
    Construye un comando canónico validado contra la lista cerrada, genera el Nonce y TTL,
    lo firma con Ed25519 y lo almacena en la tabla commands.
    """
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Acción '{action}' rechazada: no pertenece a la lista cerrada autorizada ({', '.join(sorted(ALLOWED_ACTIONS))})")

    # Verificar que el dispositivo no esté revocado
    active, reason, _ = is_device_active(device_id, tenant_id)
    if not active:
        raise PermissionError(f"No se puede emitir comando a dispositivo no activo ({device_id}): {reason}")

    command_id = str(uuid.uuid4())
    nonce = f"n_{secrets.token_hex(16)}"
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

    # Payload base sin la firma para canonicalizar
    payload_to_sign = {
        "command_id": command_id,
        "tenant_id": tenant_id,
        "device_id": device_id,
        "action": action,
        "params": params,
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at
    }

    # Firmar
    signature_b64 = sign_command_payload(payload_to_sign)

    full_command = {
        **payload_to_sign,
        "signature": signature_b64
    }

    # Persistir en BD
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO commands (id, tenant_id, device_id, action, params_json, nonce, issued_at, expires_at, signature, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DISPATCHED', ?)
        """, (command_id, tenant_id, device_id, action, json.dumps(params), nonce, issued_at, expires_at, signature_b64, issued_at))
        conn.commit()

    return full_command


def record_command_result(
    command_id: str,
    device_id: str,
    tenant_id: str,
    action: str,
    success: bool,
    result_data: Dict[str, Any],
    error_message: Optional[str] = "",
    device_signature: Optional[str] = None
) -> Dict[str, Any]:
    """
    Registra el resultado de un comando ejecutado por el dispositivo.
    Exige y verifica:
    1. Presencia de firma Ed25519 del dispositivo.
    2. Dispositivo registrado, ACTIVO y perteneciente al tenant.
    3. Comando existente, perteneciente al mismo tenant y dispositivo, y en estado DISPATCHED/ISSUED (anti-replay).
    4. Validez criptográfica de la firma Ed25519 sobre el payload canónico.
    5. Transición atómica de estado sin mutaciones parciales en caso de fallo.
    """
    if not command_id or not device_id or not tenant_id:
        return {
            "ok": False,
            "code": "MISSING_PARAMETERS",
            "http_status": 400,
            "error": "command_id, device_id y tenant_id son obligatorios"
        }

    if not device_signature or not isinstance(device_signature, str) or not device_signature.strip():
        return {
            "ok": False,
            "code": "MISSING_SIGNATURE",
            "http_status": 401,
            "error": "Firma criptográfica del dispositivo requerida (device_signature ausente)"
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    result_id = str(uuid.uuid4())

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Obtener clave y tenant del dispositivo para verificar identidad y firma
        cursor.execute("SELECT status, tenant_id, public_key_ed25519 FROM devices WHERE id = ?", (device_id,))
        dev_row = cursor.fetchone()
        if not dev_row:
            return {
                "ok": False,
                "code": "DEVICE_NOT_FOUND",
                "http_status": 403,
                "error": f"Dispositivo {device_id} no registrado"
            }

        status = dev_row["status"] if isinstance(dev_row, dict) else dev_row[0]
        dev_tenant = dev_row["tenant_id"] if isinstance(dev_row, dict) else dev_row[1]
        pub_key_b64 = dev_row["public_key_ed25519"] if isinstance(dev_row, dict) else dev_row[2]

        if dev_tenant != tenant_id:
            return {
                "ok": False,
                "code": "DEVICE_TENANT_MISMATCH",
                "http_status": 403,
                "error": "El dispositivo no pertenece al tenant autorizado para este comando"
            }

        if status == "REVOKED" or status != "ACTIVE":
            return {
                "ok": False,
                "code": "DEVICE_REVOKED",
                "http_status": 403,
                "error": "Dispositivo revocado o inactivo: resultado rechazado"
            }

        # 2. Verificar existencia, pertenencia y estado del comando (Anti-Replay)
        cursor.execute(
            "SELECT id, tenant_id, device_id, action, params_json, status FROM commands WHERE id = ?",
            (command_id,)
        )
        cmd_row = cursor.fetchone()
        if not cmd_row:
            return {
                "ok": False,
                "code": "COMMAND_NOT_FOUND",
                "http_status": 404,
                "error": f"Comando {command_id} inexistente"
            }

        cmd_tenant = cmd_row["tenant_id"] if isinstance(cmd_row, dict) else cmd_row[1]
        cmd_device = cmd_row["device_id"] if isinstance(cmd_row, dict) else cmd_row[2]
        cmd_action = cmd_row["action"] if isinstance(cmd_row, dict) else cmd_row[3]
        cmd_status = cmd_row["status"] if isinstance(cmd_row, dict) else cmd_row[5]

        if cmd_tenant != tenant_id:
            return {
                "ok": False,
                "code": "COMMAND_TENANT_MISMATCH",
                "http_status": 403,
                "error": "El comando pertenece a otro tenant"
            }

        if cmd_device != device_id:
            return {
                "ok": False,
                "code": "COMMAND_DEVICE_MISMATCH",
                "http_status": 403,
                "error": "El comando fue emitido para otro dispositivo"
            }

        if cmd_status not in ("DISPATCHED", "ISSUED"):
            return {
                "ok": False,
                "code": "COMMAND_ALREADY_PROCESSED",
                "http_status": 409,
                "error": f"Replay o reporte duplicado: el comando ya fue procesado (estado={cmd_status})"
            }

        # 3. Validar integridad y autenticidad de la firma Ed25519 del dispositivo
        report_payload = {
            "command_id": command_id,
            "device_id": device_id,
            "success": bool(success),
            "result": result_data if result_data is not None else {},
            "error": error_message or ""
        }
        if not verify_device_signature(report_payload, device_signature, pub_key_b64):
            return {
                "ok": False,
                "code": "INVALID_SIGNATURE",
                "http_status": 403,
                "error": "Firma del dispositivo inválida o adulterada"
            }

        # 4. Actualizar estado del comando de forma atómica (CAS sobre status)
        new_status = "EXECUTED" if success else "FAILED"
        cursor.execute(
            "UPDATE commands SET status = ? WHERE id = ? AND status IN ('DISPATCHED', 'ISSUED')",
            (new_status, command_id)
        )
        if cursor.rowcount != 1:
            return {
                "ok": False,
                "code": "COMMAND_ALREADY_PROCESSED",
                "http_status": 409,
                "error": "El comando ya fue procesado concurrentemente"
            }

        # 5. Insertar en command_results
        effective_action = cmd_action or action
        cursor.execute("""
            INSERT INTO command_results (id, command_id, device_id, tenant_id, action, success, result_json, error_message, device_signature, reported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (result_id, command_id, device_id, cmd_tenant, effective_action, 1 if success else 0, json.dumps(result_data or {}), error_message, device_signature, now_iso))

        # 6. Actualizar last_seen_at del dispositivo
        cursor.execute("UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, device_id))
        conn.commit()

    return {"ok": True, "result_id": result_id, "status": new_status}
