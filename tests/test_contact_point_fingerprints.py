from uuid import uuid4

from funnel_crm.platform.contact_point_crypto import ContactPointKeyring


def test_contact_blind_indexes_are_scoped_and_stable_across_profiles() -> None:
    tenant_id = uuid4()
    keyring = ContactPointKeyring(
        active_key_id="v2",
        keys={"v1": b"o" * 32, "v2": b"n" * 32},
    )

    first = keyring.blind_indexes(
        tenant_id=tenant_id,
        channel="email",
        value=" Person@example.test ",
    )
    second = keyring.blind_indexes(
        tenant_id=tenant_id,
        channel="email",
        value="Person@example.test",
    )
    other_tenant = keyring.blind_indexes(
        tenant_id=uuid4(),
        channel="email",
        value="Person@example.test",
    )
    other_channel = keyring.blind_indexes(
        tenant_id=tenant_id,
        channel="phone",
        value="Person@example.test",
    )

    assert first == second
    assert set(first) == {"v1", "v2"}
    assert first["v1"] != first["v2"]
    assert first["v2"] != other_tenant["v2"]
    assert first["v2"] != other_channel["v2"]
    assert len(first["v2"]) == 32
