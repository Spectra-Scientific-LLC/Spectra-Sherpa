"""Personal credentials persist encrypted and never cross authenticated users."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from spectra_sherpa.app.api.v1.routes import api_keys, synthesis
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.api_key import APIKeyCreate
from spectra_sherpa.app.services.encryption import decrypt_value


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["local", "demo", "pro", "hybrid_server", "org"])
async def test_personal_hitran_key_lifecycle(test_session, test_user, monkeypatch, profile):
    monkeypatch.setattr(api_keys, "app_config", SimpleNamespace(site_profile=profile))
    monkeypatch.setattr(
        api_keys, "get_demo_policy", lambda: SimpleNamespace(disabled_capabilities={"api_key_management"})
    )
    other = User(username=f"other-{profile}")
    test_session.add(other)
    await test_session.commit()
    seen = []

    async def validate(key):
        seen.append(key)

    monkeypatch.setattr(api_keys.synthesis_service, "validate_hitran_api_key", validate)
    for user, key in ((test_user, "owner-key"), (other, "other-key")):
        result = await api_keys.set_api_key(APIKeyCreate(service_name="hitran", key=key), test_session, user)
        assert result == {"status": "stored"}
    records = (await test_session.execute(select(APIKey))).scalars().all()
    assert len(records) == 2
    assert all(row.key_encrypted not in {"owner-key", "other-key"} for row in records)
    test_session.expire_all()
    # Re-read durable ciphertext; encryption key persists independently of the request.
    records = (await test_session.execute(select(APIKey))).scalars().all()
    assert {decrypt_value(row.key_encrypted) for row in records} == {"owner-key", "other-key"}
    await test_session.refresh(test_user)
    await test_session.refresh(other)
    for user in (test_user, other):
        listed = await api_keys.list_api_keys(test_session, user)
        assert [item.service_name for item in listed] == ["hitran"]
        assert "key_encrypted" not in listed[0].model_dump()
        await api_keys.validate_hitran_api_key(api_keys._HitranKeyValidateRequest(), test_session, user)
    assert seen == ["owner-key", "other-key"]
    assert await synthesis._stored_api_key(test_session, other, "hitran") == "other-key"
    await api_keys.set_api_key(APIKeyCreate(service_name="hitran", key="replacement"), test_session, test_user)
    assert await synthesis._stored_api_key(test_session, test_user, "hitran") == "replacement"
    test_session.add(APIKey(user_id=None, service_name="hitran", key_encrypted=records[0].key_encrypted))
    await test_session.commit()
    await api_keys.delete_api_key("hitran", test_session, test_user)
    assert await synthesis._stored_api_key(test_session, test_user, "hitran") is None
    assert await synthesis._stored_api_key(test_session, other, "hitran") == "other-key"
    with pytest.raises(api_keys.HTTPException) as error:
        await api_keys.validate_hitran_api_key(api_keys._HitranKeyValidateRequest(), test_session, test_user)
    assert error.value.status_code == 400
    assert seen == ["owner-key", "other-key"]
