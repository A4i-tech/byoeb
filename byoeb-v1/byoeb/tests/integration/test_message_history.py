import os
import sys

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


@pytest.mark.parametrize(("lang", "messages"), [
    (LanguageCode.ENGLISH, ("what is antara injection?", "what are its side effects?", "how often is it given?")),
    (LanguageCode.HINDI, ("अंतरा इंजेक्शन क्या है?", "इसके दुष्प्रभाव क्या हैं?", "यह कितनी बार दिया जाता है?")),
    (LanguageCode.MARATHI, ("अंतरा इंजेक्शन म्हणजे काय?", "त्याचे दुष्परिणाम काय आहेत?", "ते किती वेळा दिले जाते?")),
    (LanguageCode.TELUGU, ("అంతర ఇంజెక్షన్ అంటే ఏమిటి?", "దాని దుష్ప్రభావాలు ఏమిటి?", "అది ఎంత తరచుగా ఇవ్వబడుతుంది?")),
])
async def test_conversation_history_is_captured(lang: LanguageCode, messages: tuple[str]):
    user = _user(lang)
    histories = []
    async with Client(BASE_URL + "/mcp?phone_number=" + user.phone_number_id) as client:
        for message in messages:
            response = await client.call_tool("asha_chat", {"message": message, "features": ["history"]})
            assert response.data.category == MessageCategory.BOT_TO_USER_RESPONSE.value  # ensure it is not IDK

            history = next((v for k, v in response.data.additional_info if k == "Conversation history"))
            histories.append(history)

    for i, history in enumerate(histories[1:], 1):
        assert history[-1].startswith("query%d: %s" % (i, messages[i - 1]))