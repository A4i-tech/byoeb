import base64
from pathlib import Path

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.message_category import MessageCategory
import pytest

from byoeb_core.models.byoeb.user import User
from fastmcp import Client


def _user(base_url: str, phone_number_id: str, username: str, lang: LanguageCode, auth_session) -> User:
    auth_session.delete(f"{base_url}/delete_users", json=[phone_number_id]).raise_for_status()
    response = auth_session.post(f"{base_url}/register_users", json=[{
        "phone_number_id": phone_number_id,
        "user_location": {"district": "Pytest District"},
        "user_type": "asha",
        "user_language": lang.value,
        "user_name": username,
        "test_user": True,
    }])
    response.raise_for_status()

    data = response.json()
    return User(**data[0])


@pytest.mark.parametrize(("lang", "audio_file"), [
    (LanguageCode.ENGLISH, "english.ogg"),
    (LanguageCode.HINDI, "hindi.ogg"),
])
async def test_audio_message(lang: LanguageCode, audio_file: str, auth_env, auth_access_token, auth_session):
    me = auth_session.get(f"{auth_env.base_url.rstrip('/')}/auth/me")
    me.raise_for_status()
    phone_number_id = me.json().get("phone_number_id")
    if not phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")
    path = Path(__file__).resolve().parent / "resources" / audio_file
    with path.open("rb") as f:
        data = base64.b64encode(f.read())

    _user(auth_env.base_url, phone_number_id, auth_env.username, lang, auth_session)
    async with Client(f"{auth_env.base_url.rstrip('/')}/mcp", auth=auth_access_token) as client:
        response = await client.call_tool("asha_chat", {"message": {"data": data, "mime_type": "audio/ogg"}})

    assert response.data.category == MessageCategory.BOT_TO_USER_RESPONSE.value  # ensure it is not IDK
