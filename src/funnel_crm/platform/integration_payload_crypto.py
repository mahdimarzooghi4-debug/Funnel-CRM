"""Authenticated encryption for durable product event payloads."""

from __future__ import annotations

import base64
import binascii
import json
import hmac
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
NONCE_BYTES = 12


class IntegrationPayloadCryptoError(Exception):
    """Raised when integration payload encryption or decryption is unavailable."""


@dataclass(frozen=True)
class IntegrationPayloadKeyring:
    """AES-256 keyring loaded from deployment-managed secret configuration."""

    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not KEY_ID_PATTERN.fullmatch(self.active_key_id):
            raise ValueError("invalid active integration payload key id")
        if self.active_key_id not in self.keys:
            raise ValueError("active integration payload key is missing")
        for key_id, key in self.keys.items():
            if not KEY_ID_PATTERN.fullmatch(key_id) or len(key) != 32:
                raise ValueError("integration payload keys must be valid 256-bit keys")

    @classmethod
    def from_environment(cls) -> "IntegrationPayloadKeyring":
        """Read base64-encoded key material from the deployment secret store."""
        raw = os.environ.get("FUNNEL_CRM_INTEGRATION_PAYLOAD_KEYRING")
        if not raw:
            raise IntegrationPayloadCryptoError(
                "integration payload encryption is not configured"
            )
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
        except (
            KeyError,
            TypeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise IntegrationPayloadCryptoError(
                "integration payload keyring is invalid"
            ) from exc

    def digest(
        self, canonical_event: bytes, *, key_id: str | None = None
    ) -> tuple[str, bytes]:
        """Return a keyed, domain-separated digest for idempotency checks."""
        selected_key_id = key_id or self.active_key_id
        key = self.keys.get(selected_key_id)
        if key is None:
            raise IntegrationPayloadCryptoError(
                "integration event digest key is unavailable"
            )
        digest = hmac.new(
            key,
            b"funnel-crm:integration-event-digest:v1:" + canonical_event,
            "sha256",
        ).digest()
        return selected_key_id, digest

    @staticmethod
    def _aad(
        *,
        tenant_id: UUID,
        event_id: UUID,
        source_product: str,
        event_type: str,
        contract_name: str,
        contract_version: int,
    ) -> bytes:
        return (
            "funnel-crm:integration-payload:v1:"
            f"{tenant_id}:{source_product}:{event_id}:"
            f"{event_type}:{contract_name}:{contract_version}"
        ).encode("utf-8")

    def encrypt(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        source_product: str,
        event_type: str,
        contract_name: str,
        contract_version: int,
        payload: dict[str, Any],
    ) -> tuple[str, bytes]:
        try:
            plaintext = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise IntegrationPayloadCryptoError(
                "integration payload is not valid JSON"
            ) from exc
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce,
            plaintext,
            self._aad(
                tenant_id=tenant_id,
                event_id=event_id,
                source_product=source_product,
                event_type=event_type,
                contract_name=contract_name,
                contract_version=contract_version,
            ),
        )
        return self.active_key_id, nonce + ciphertext

    def decrypt(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        source_product: str,
        event_type: str,
        contract_name: str,
        contract_version: int,
        key_id: str,
        ciphertext: bytes,
    ) -> dict[str, Any]:
        key = self.keys.get(key_id)
        if key is None or len(ciphertext) <= NONCE_BYTES:
            raise IntegrationPayloadCryptoError(
                "integration payload key or ciphertext is unavailable"
            )
        try:
            plaintext = AESGCM(key).decrypt(
                ciphertext[:NONCE_BYTES],
                ciphertext[NONCE_BYTES:],
                self._aad(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    source_product=source_product,
                    event_type=event_type,
                    contract_name=contract_name,
                    contract_version=contract_version,
                ),
            )
            payload = json.loads(plaintext)
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrationPayloadCryptoError(
                "integration payload integrity check failed"
            ) from exc
        if not isinstance(payload, dict):
            raise IntegrationPayloadCryptoError(
                "integration payload must be a JSON object"
            )
        return payload
