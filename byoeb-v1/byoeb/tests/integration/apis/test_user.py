import pytest

def _phone_number_id(auth_env, auth_session):
    me = auth_session.get(f"{auth_env.base_url.rstrip('/')}/auth/me")
    me.raise_for_status()
    phone_number_id = me.json().get("phone_number_id")
    if not phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")
    return phone_number_id


def test_register_user_endpoint(auth_env, auth_session):
    phone_number_id = _phone_number_id(auth_env, auth_session)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": auth_env.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    response = auth_session.post(f"{auth_env.base_url}/register_users", json=payload)
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
    data = response.json()
    assert isinstance(data, list) and data
    assert data[0]["phone_number_id"] == phone_number_id


def test_get_users_endpoint(auth_env, auth_session):
    phone_number_id = _phone_number_id(auth_env, auth_session)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": auth_env.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{auth_env.base_url}/register_users", json=payload).raise_for_status()
    response = auth_session.post(f"{auth_env.base_url}/get_users", json=[phone_number_id])
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
    users = response.json()
    assert len(users) == 1
    assert users[0]["phone_number_id"] == phone_number_id
    assert users[0]["user_type"] == "asha"


def test_update_users_endpoint(auth_env, auth_session):
    phone_number_id = _phone_number_id(auth_env, auth_session)
    register_payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": auth_env.username,
            "test_user": False,
        }
    ]
    updated_name = f"{auth_env.username} Updated"
    update_payload = [
        {
            "phone_number_id": phone_number_id,
            "user_name": updated_name,
            "user_type": "anm",
            "test_user": True,
        }
    ]
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{auth_env.base_url}/register_users", json=register_payload).raise_for_status()
    response = auth_session.post(f"{auth_env.base_url}/update_users", json=update_payload)
    response.raise_for_status()
    updated = auth_session.post(f"{auth_env.base_url}/get_users", json=[phone_number_id])
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    updated.raise_for_status()
    user = updated.json()[0]
    assert user["user_name"] == updated_name
    assert user["user_type"] == "anm"
    assert user["test_user"] is True


def test_delete_users_endpoint(auth_env, auth_session):
    phone_number_id = _phone_number_id(auth_env, auth_session)
    payload = [
        {
            "phone_number_id": phone_number_id,
            "user_location": {"district": "Pytest District"},
            "user_type": "asha",
            "user_language": "en",
            "user_name": auth_env.username,
            "test_user": False,
        }
    ]
    auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    auth_session.post(f"{auth_env.base_url}/register_users", json=payload).raise_for_status()
    response = auth_session.delete(f"{auth_env.base_url}/delete_users", json=[phone_number_id])
    response.raise_for_status()
