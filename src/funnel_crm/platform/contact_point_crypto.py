"""Authenticated encryption for customer contact values using an injected keyring."""

from __future__ import annotations

import base64
import binascii
import json
import hashlib
import hmac
import unicodedata
import os
import re
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
NONCE_BYTES = 12


class ContactPointCryptoError(Exception):
    """Raised when contact data cannot be safely encrypted or decrypted."""


@dataclass(frozen=True)
class ContactPointKeyring:
    """In-memory keyring; key material must come from deployment secret storage."""

    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not KEY_ID_PATTERN.fullmatch(self.active_key_id):
            raise ValueError("invalid active contact key id")
        if self.active_key_id not in self.keys:
            raise ValueError("active contact key is missing")
        for key_id, key in self.keys.items():
            if not KEY_ID_PATTERN.fullmatch(key_id) or len(key) != 32:
                raise ValueError("contact keys must have valid ids and 256-bit values")

    @classmethod
    def from_environment(cls) -> "ContactPointKeyring":
        """Read a JSON keyring whose base64 values are supplied as a secret."""
        raw = os.environ.get("FUNNEL_CRM_CONTACT_KEYRING")
        if not raw:
            raise ContactPointCryptoError("contact-point encryption is not configured")
        try:
            payload = json.loads(raw)
            active_key_id = payload["active_key_id"]
            encoded_keys = payload["keys"]
            if not isinstance(active_key_id, str) or not isinstance(encoded_keys, dict):
                raise ValueError("invalid keyring shape")
            keys = {
                key_id: base64.b64decode(encoded, validate=True)
                for key_id, encoded in encoded_keys.items()
                if isinstance(key_id, str) and isinstance(encoded, str)
            }
            if len(keys) != len(encoded_keys):
                raise ValueError("invalid keyring entries")
            return cls(active_key_id=active_key_id, keys=keys)
        except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
            raise ContactPointCryptoError("contact-point keyring is invalid") from exc

    @staticmethod
    def _aad(
        tenant_id: UUID,
        profile_id: UUID,
        channel: str,
    ) -> bytes:
        return f"funnel-crm:contact-point:v1:{tenant_id}:{profile_id}:{channel}".encode()

    def encrypt(
        self,
        *,
        tenant_id: UUID,
        profile_id: UUID,
        channel: str,
        value: str,
    ) -> tuple[str, bytes]:
        if not value:
            raise ContactPointCryptoError("contact-point value must not be empty")
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce,
            value.encode("utf-8"),
            self._aad(tenant_id, profile_id, channel),
        )
        return self.active_key_id, nonce + ciphertext

    def decrypt(
        self,
        *,
        tenant_id: UUID,
        profile_id: UUID,
        channel: str,
        key_id: str,
        ciphertext: bytes,
    ) -> str:
        key = self.keys.get(key_id)
        if key is None or len(ciphertext) <= NONCE_BYTES:
            raise ContactPointCryptoError("contact-point key or ciphertext is unavailable")
        try:
            plaintext = AESGCM(key).decrypt(
                ciphertext[:NONCE_BYTES],
                ciphertext[NONCE_BYTES:],
                self._aad(tenant_id, profile_id, channel),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ContactPointCryptoError("contact-point data integrity check failed") from exc

    @staticmethod
    def _normalized_match_value(value: str) -> bytes:
        normalized = unicodedata.normalize("NFC", value).strip()
        if not normalized:
            raise ContactPointCryptoError("contact-point value must not be empty")
        return normalized.encode("utf-8")

    def blind_indexes(
        self,
        *,
        tenant_id: UUID,
        channel: str,
        value: str,
    ) -> dict[str, bytes]:
        """Return tenant/channel-bound HMACs for retained encryption key versions.

        Derived keys separate matching from AES-GCM encryption. Retaining prior
        key versions lets duplicate checks find values indexed before rotation.
        """
        normalized = self._normalized_match_value(value)
        indexes: dict[str, bytes] = {}
        for key_id, key in self.keys.items():
            context = f"funnel-crm:contact-match:v1:{tenant_id}:{channel}:{key_id}".encode()
            derived_key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=context,
            ).derive(key)
            indexes[key_id] = hmac.new(
                derived_key, normalized, hashlib.sha256
            ).digest()
        return indexes
