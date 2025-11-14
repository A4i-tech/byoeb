import os
import sys
import time
import uuid
import requests


BASE_URL = os.getenv("RECIEVE_URL")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
USER_NAME = os.getenv("USER_NAME", "byoeb-user")
if BASE_URL is None or PHONE_NUMBER_ID is None or USER_NAME is None:
    print("Environment variables are missing")
    sys.exit(1)

username_slug = USER_NAME.lower().replace(" ", "-")

def _build_status_payload(errors=None):
    current_timestamp = str(int(time.time()))
    status = {
        "id": f"wamid.{username_slug}.{uuid.uuid4().hex}",
        "status": "sent",
        "timestamp": current_timestamp,
        "recipient_id": PHONE_NUMBER_ID,
        "conversation": {
            "id": f"{username_slug}-conversation",
            "expiration_timestamp": current_timestamp,
            "origin": {"type": "service"},
        },
        "pricing": {
            "billable": False,
            "pricing_model": "PMP",
            "category": "service",
            "type": "free_customer_service",
        },
    }
    if errors is not None:
        status["errors"] = errors

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "211506508713627",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": PHONE_NUMBER_ID,
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "statuses": [status],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _post_status(payload: dict):
    response = requests.post(BASE_URL, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def test_status_payload_without_errors_returns_success():
    payload = _build_status_payload()
    response = _post_status(payload)
    assert response["status"] == "success"


def test_status_payload_with_errors_returns_success():
    errors = [
        {
            "code": 131000,
            "title": "Temporarily Unavailable",
            "message": "Upstream provider was not reachable",
        }
    ]
    payload = _build_status_payload(errors=errors)
    response = _post_status(payload)
    assert response["status"] == "success"
