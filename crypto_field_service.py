"""
Servicio de Cifrado a Nivel de Campo (Field-Level Encryption)
NexusReach Pro Directrices de Ingeniería v1.3 - Workstream 5.3 & 5.4 [P0]

Cifra teléfonos, correos y datos sensibles de negocio en reposo utilizando
claves derivadas criptográficamente por tenant (AES-256-CBC/Fernet con HMAC-SHA256).
"""

import os
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

KEYS_DIR = os.path.join(os.path.dirname(__file__), "storage", "keys")
MASTER_KEY_FILE = os.path.join(KEYS_DIR, "field_encryption_master.key")
PREFIX = "enc:v1:"

_master_key_cache: Optional[bytes] = None


def _get_master_key() -> bytes:
    """Obtiene o genera la clave maestra de cifrado del servidor."""
    global _master_key_cache
    if _master_key_cache is not None:
        return _master_key_cache

    env_key = os.getenv("NEXUSREACH_FIELD_MASTER_KEY")
    if env_key:
        _master_key_cache = env_key.encode("utf-8") if isinstance(env_key, str) else env_key
        return _master_key_cache

    if os.path.exists(MASTER_KEY_FILE):
        with open(MASTER_KEY_FILE, "rb") as f:
            _master_key_cache = f.read().strip()
            return _master_key_cache

    os.makedirs(KEYS_DIR, exist_ok=True)
    generated = Fernet.generate_key()
    with open(MASTER_KEY_FILE, "wb") as f:
        f.write(generated)
    _master_key_cache = generated
    return _master_key_cache


def _derive_tenant_fernet(tenant_id: str) -> Fernet:
    """
    Deriva una subclave criptográfica única de 32 bytes para el tenant usando HKDF
    a partir de la clave maestra y el ID del tenant como salt/info.
    """
    master = _get_master_key()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode("utf-8"),
        info=b"nexusreach_tenant_field_encryption"
    )
    derived_bytes = hkdf.derive(master)
    fernet_key = base64.urlsafe_b64encode(derived_bytes)
    return Fernet(fernet_key)


def encrypt_field(plaintext: Optional[str], tenant_id: str) -> Optional[str]:
    """
    Cifra un valor de texto sensible para un tenant específico.
    Si ya está cifrado o es vacío, lo devuelve seguro.
    """
    if plaintext is None or plaintext == "":
        return plaintext
    if plaintext.startswith(PREFIX):
        return plaintext

    f = _derive_tenant_fernet(tenant_id)
    token = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{PREFIX}{token}"


def decrypt_field(ciphertext: Optional[str], tenant_id: str) -> Optional[str]:
    """
    Descifra un valor cifrado a nivel de campo para el tenant correspondiente.
    Si no tiene el prefijo de cifrado (datos heredados en texto plano), retorna el texto tal cual.
    """
    if ciphertext is None or ciphertext == "":
        return ciphertext
    if not ciphertext.startswith(PREFIX):
        return ciphertext

    token = ciphertext[len(PREFIX):]
    try:
        f = _derive_tenant_fernet(tenant_id)
        decrypted_bytes = f.decrypt(token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        # Si falló la clave (ej. intento de acceso desde otro tenant), levantar PermissionError
        raise PermissionError(f"Aislamiento de cifrado violado o clave de tenant inválida: {e}")
