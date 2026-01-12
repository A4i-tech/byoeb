import pytest

def _phone_number_id(auth_me):
    phone_number_id = auth_me.phone_number_id
    if not phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")
    return phone_number_id


def test_register_user_endpoint(envs, auth_session, auth_me):
    phone_number_id = _phone_number_id(auth_me)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": envs.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    response = auth_session.post(f"{envs.base_url}/register_users", json=payload)
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
    data = response.json()
    assert isinstance(data, list) and data
    assert data[0]["phone_number_id"] == phone_number_id


def test_get_users_endpoint(envs, auth_session, auth_me):
    phone_number_id = _phone_number_id(auth_me)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": envs.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{envs.base_url}/register_users", json=payload).raise_for_status()
    response = auth_session.post(f"{envs.base_url}/get_users", json=[phone_number_id])
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
    users = response.json()
    assert len(users) == 1
    assert users[0]["phone_number_id"] == phone_number_id
    assert users[0]["user_type"] == "asha"


def test_update_users_endpoint(envs, auth_session, auth_me):
    phone_number_id = _phone_number_id(auth_me)
    register_payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": envs.username,
            "test_user": False,
        }
    ]
    updated_name = f"{envs.username} Updated"
    update_payload = [
        {
            "phone_number_id": phone_number_id,
            "user_name": updated_name,
            "user_type": "anm",
            "test_user": True,
        }
    ]
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{envs.base_url}/register_users", json=register_payload).raise_for_status()
    response = auth_session.post(f"{envs.base_url}/update_users", json=update_payload)
    response.raise_for_status()
    updated = auth_session.post(f"{envs.base_url}/get_users", json=[phone_number_id])
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    updated.raise_for_status()
    user = updated.json()[0]
    assert user["user_name"] == updated_name
    assert user["user_type"] == "anm"
    assert user["test_user"] is True


def test_delete_users_endpoint(envs, auth_session, auth_me):
    phone_number_id = _phone_number_id(auth_me)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": envs.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{envs.base_url}/register_users", json=payload).raise_for_status()
    response = auth_session.delete(f"{envs.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
