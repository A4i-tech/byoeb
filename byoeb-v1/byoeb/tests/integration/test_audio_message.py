import base64
import os
import sys
from pathlib import Path

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.message_category import MessageCategory
import pytest
import requests

from byoeb_core.models.byoeb.user import User
from fastmcp import Client


BASE_URL = os.getenv("RECIEVE_URL")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
USER_NAME = os.getenv("USER_NAME", "byoeb-user")
if BASE_URL is None or PHONE_NUMBER_ID is None or USER_NAME is None:
    print("Environment variables are missing")
    sys.exit(1)

BASE_URL = BASE_URL.replace("/receive", "")

def _user(lang: LanguageCode) -> User:
    requests.delete(f"{BASE_URL}/delete_users", json=[PHONE_NUMBER_ID]).raise_for_status()
    response = requests.post(f"{BASE_URL}/register_users", json=[{
        "phone_number_id": PHONE_NUMBER_ID,
        "user_location": {"district": "Pytest District"},
        "user_type": "asha",
        "user_language": lang.value,
        "user_name": USER_NAME,
        "test_user": True,
    }])
    response.raise_for_status()

    data = response.json()
    return User(**data[0])


@pytest.mark.parametrize(("lang", "audio_file"), [
    (LanguageCode.ENGLISH, "english.ogg"),
    (LanguageCode.HINDI, "hindi.ogg"),
])
async def test_audio_message(lang: LanguageCode, audio_file: str):
    path = Path(__file__).resolve().parent / "resources" / audio_file
    with path.open("rb") as f:
        data = base64.b64encode(f.read())

    user = _user(lang)
    async with Client(BASE_URL + "/mcp?phone_number=" + user.phone_number_id) as client:
        response = await client.call_tool("asha_chat", {"message": {"data": data, "mime_type": "audio/ogg"}})

    assert response.data.category == MessageCategory.BOT_TO_USER_RESPONSE.value  # ensure it is not IDK