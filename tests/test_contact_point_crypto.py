import base64
import json
from uuid import uuid4

import pytest

from funnel_crm.platform.contact_point_crypto import (
    ContactPointCryptoError,
    ContactPointKeyring,
)


def test_contact_point_value_round_trips_and_ciphertext_is_randomized() -> None:
    tenant_id, profile_id = uuid4(), uuid4()
    keyring = ContactPointKeyring(active_key_id="k1", keys={"k1": b"x" * 32})

    first_key_id, first = keyring.encrypt(
        tenant_id=tenant_id,
        profile_id=profile_id,
        channel="email",
        value="person@example.test",
    )
    second_key_id, second = keyring.encrypt(
        tenant_id=tenant_id,
        profile_id=profile_id,
        channel="email",
        value="person@example.test",
    )

    assert first_key_id == second_key_id == "k1"
    assert first != second
    assert b"person@example.test" not in first
    assert keyring.decrypt(
        tenant_id=tenant_id,
        profile_id=profile_id,
        channel="email",
        key_id=first_key_id,
        ciphertext=first,
    ) == "person@example.test"


def test_contact_point_associated_data_prevents_reassignment_or_channel_change() -> None:
    tenant_id, profile_id = uuid4(), uuid4()
    keyring = ContactPointKeyring(active_key_id="key-a", keys={"key-a": b"a" * 32})
    key_id, ciphertext = keyring.encrypt(
        tenant_id=tenant_id,
        profile_id=profile_id,
        channel="phone",
        value="+1-555-0100",
    )

    for changed in (
        {"tenant_id": uuid4(), "profile_id": profile_id, "channel": "phone"},
        {"tenant_id": tenant_id, "profile_id": uuid4(), "channel": "phone"},
        {"tenant_id": tenant_id, "profile_id": profile_id, "channel": "email"},
    ):
        with pytest.raises(ContactPointCryptoError):
            keyring.decrypt(
                **changed,
                key_id=key_id,
                ciphertext=ciphertext,
            )


def test_contact_point_keyring_validates_secret_configuration(monkeypatch) -> None:
    monkeypatch.delenv("FUNNEL_CRM_CONTACT_KEYRING", raising=False)
    with pytest.raises(ContactPointCryptoError):
        ContactPointKeyring.from_environment()

    monkeypatch.setenv(
        "FUNNEL_CRM_CONTACT_KEYRING",
        json.dumps(
            {
                "active_key_id": "v1",
                "keys": {"v1": base64.b64encode(b"k" * 32).decode("ascii")},
            }
        ),
    )
    keyring = ContactPointKeyring.from_environment()
    assert keyring.active_key_id == "v1"

    monkeypatch.setenv(
        "FUNNEL_CRM_CONTACT_KEYRING",
        json.dumps({"active_key_id": "missing", "keys": {"v1": "bad"}}),
    )
    with pytest.raises(ContactPointCryptoError):
        ContactPointKeyring.from_environment()
