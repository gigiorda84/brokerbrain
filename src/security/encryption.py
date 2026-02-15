"""Field-level AES-256-GCM encryption for PII at rest.

Encrypts sensitive fields before DB storage and decrypts on read.
Uses 12-byte random nonces (96-bit, NIST recommended for GCM).
Stored format: base64(nonce || ciphertext || tag).

Usage:
    from src.security.encryption import field_encryptor

    encrypted = field_encryptor.encrypt("RSSMRA85M01H501Z")
    plaintext = field_encryptor.decrypt(encrypted)
"""

from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import settings

logger = logging.getLogger(__name__)

# Fields that MUST be encrypted at rest in ExtractedData.value
ENCRYPTED_FIELDS: frozenset[str] = frozenset({
    "codice_fiscale",
    "partita_iva",
    "phone_number",
    "net_salary",
    "gross_salary",
    "net_pension",
    "gross_pension",
    "reddito_imponibile",
    "monthly_installment",
    "residual_amount",
})

_NONCE_SIZE = 12  # 96-bit nonce for AES-GCM


class FieldEncryptor:
    """AES-256-GCM encryptor for individual database fields.

    Thread-safe and stateless (each encrypt call generates a fresh nonce).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            msg = f"AES-256 requires a 32-byte key, got {len(key)} bytes"
            raise ValueError(msg)
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string field. Returns base64(nonce + ciphertext + tag)."""
        nonce = os.urandom(_NONCE_SIZE)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Decrypt a base64-encoded encrypted field."""
        raw = base64.b64decode(token)
        if len(raw) < _NONCE_SIZE + 16:  # nonce + minimum GCM tag
            msg = "Invalid encrypted token: too short"
            raise ValueError(msg)
        nonce = raw[:_NONCE_SIZE]
        ct = raw[_NONCE_SIZE:]
        return self._aesgcm.decrypt(nonce, ct, None).decode("utf-8")

    def should_encrypt(self, field_name: str) -> bool:
        """Check if a field name requires encryption."""
        return field_name in ENCRYPTED_FIELDS


def _load_key() -> bytes:
    """Load the encryption key from settings (base64-encoded)."""
    raw = settings.security.encryption_key
    if not raw:
        logger.warning("ENCRYPTION_KEY not set — using a random ephemeral key (data won't survive restarts)")
        return os.urandom(32)
    try:
        key = base64.b64decode(raw)
    except Exception:
        logger.warning("ENCRYPTION_KEY is not valid base64 — using a random ephemeral key")
        return os.urandom(32)
    if len(key) != 32:
        logger.warning("ENCRYPTION_KEY decoded to %d bytes (expected 32) — using a random ephemeral key", len(key))
        return os.urandom(32)
    return key


# Module-level singleton — import this wherever encryption is needed.
field_encryptor = FieldEncryptor(_load_key())
