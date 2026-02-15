"""Tests for field-level AES-256-GCM encryption."""

from __future__ import annotations

import base64
import os

import pytest

from src.security.encryption import ENCRYPTED_FIELDS, FieldEncryptor


@pytest.fixture
def encryptor() -> FieldEncryptor:
    """Create a FieldEncryptor with a random key."""
    return FieldEncryptor(os.urandom(32))


class TestFieldEncryptor:
    """Round-trip and edge-case tests for FieldEncryptor."""

    def test_encrypt_decrypt_round_trip(self, encryptor: FieldEncryptor) -> None:
        plaintext = "RSSMRA85M01H501Z"
        token = encryptor.encrypt(plaintext)
        assert token != plaintext
        assert encryptor.decrypt(token) == plaintext

    def test_different_nonces(self, encryptor: FieldEncryptor) -> None:
        """Two encryptions of the same plaintext should produce different ciphertexts."""
        plaintext = "same_value"
        t1 = encryptor.encrypt(plaintext)
        t2 = encryptor.encrypt(plaintext)
        assert t1 != t2
        # But both decrypt to the same value
        assert encryptor.decrypt(t1) == plaintext
        assert encryptor.decrypt(t2) == plaintext

    def test_unicode(self, encryptor: FieldEncryptor) -> None:
        plaintext = "€1.750,00 — caffè"
        assert encryptor.decrypt(encryptor.encrypt(plaintext)) == plaintext

    def test_empty_string(self, encryptor: FieldEncryptor) -> None:
        assert encryptor.decrypt(encryptor.encrypt("")) == ""

    def test_invalid_key_length(self) -> None:
        with pytest.raises(ValueError, match="32-byte"):
            FieldEncryptor(b"short")

    def test_invalid_token(self, encryptor: FieldEncryptor) -> None:
        with pytest.raises(ValueError, match="too short"):
            encryptor.decrypt(base64.b64encode(b"short").decode())

    def test_tampered_token(self, encryptor: FieldEncryptor) -> None:
        token = encryptor.encrypt("test")
        raw = bytearray(base64.b64decode(token))
        raw[-1] ^= 0xFF  # flip last byte
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(Exception):  # noqa: B017 — cryptography raises InvalidTag
            encryptor.decrypt(tampered)

    def test_wrong_key(self) -> None:
        enc1 = FieldEncryptor(os.urandom(32))
        enc2 = FieldEncryptor(os.urandom(32))
        token = enc1.encrypt("secret")
        with pytest.raises(Exception):  # noqa: B017
            enc2.decrypt(token)

    def test_should_encrypt(self, encryptor: FieldEncryptor) -> None:
        assert encryptor.should_encrypt("codice_fiscale") is True
        assert encryptor.should_encrypt("net_salary") is True
        assert encryptor.should_encrypt("age") is False
        assert encryptor.should_encrypt("employment_type") is False


class TestEncryptedFieldsList:
    """Verify the ENCRYPTED_FIELDS set covers expected PII."""

    def test_pii_fields_present(self) -> None:
        expected = {
            "codice_fiscale",
            "partita_iva",
            "phone_number",
            "net_salary",
            "gross_salary",
        }
        assert expected.issubset(ENCRYPTED_FIELDS)

    def test_non_pii_excluded(self) -> None:
        non_pii = {"age", "gender", "employment_type", "employer_category"}
        assert not non_pii.intersection(ENCRYPTED_FIELDS)
