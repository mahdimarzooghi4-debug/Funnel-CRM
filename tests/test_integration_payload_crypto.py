from __future__ import annotations

from uuid import uuid4

import pytest

from funnel_crm.platform.integration_payload_crypto import (
    IntegrationPayloadCryptoError,
    IntegrationPayloadKeyring,
)


def test_payload_round_trip_binds_ciphertext_to_tenant_and_event() -> None:
    keyring = IntegrationPayloadKeyring(
        active_key_id="v1", keys={"v1": b"k" * 32}
    )
    fields = {
        "tenant_id": uuid4(),
        "event_id": uuid4(),
        "source_product": "funnel.store",
        "event_type": "order.created",
        "contract_name": "commerce.order",
        "contract_version": 1,
    }
    payload = {"customer": {"email": "person@example.test"}, "total": 1250}

    key_id, ciphertext = keyring.encrypt(**fields, payload=payload)

    assert b"person@example.test" not in ciphertext
    assert keyring.decrypt(**fields, key_id=key_id, ciphertext=ciphertext) == payload

    with pytest.raises(IntegrationPayloadCryptoError):
        keyring.decrypt(
            **{**fields, "tenant_id": uuid4()},
            key_id=key_id,
            ciphertext=ciphertext,
        )
    with pytest.raises(IntegrationPayloadCryptoError):
        keyring.decrypt(
            **fields,
            key_id=key_id,
            ciphertext=ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]),
        )


def test_payload_keyring_requires_valid_256_bit_keys() -> None:
    with pytest.raises(ValueError):
        IntegrationPayloadKeyring(active_key_id="missing", keys={"v1": b"k" * 32})
    with pytest.raises(ValueError):
        IntegrationPayloadKeyring(active_key_id="v1", keys={"v1": b"short"})
