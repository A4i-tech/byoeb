import time
import uuid

import pytest
import requests


def _build_status_payload(*, username: str, phone_number_id: str, errors=None):
    username_slug = username.lower().replace(" ", "-")
    current_timestamp = str(int(time.time()))
    status = {
        "id": f"wamid.{username_slug}.{uuid.uuid4().hex}",
        "status": "sent",
        "timestamp": current_timestamp,
        "recipient_id": phone_number_id,
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
                                "display_phone_number": phone_number_id,
                                "phone_number_id": phone_number_id,
                            },
                            "statuses": [status],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_status_payload_without_errors_returns_success(envs, auth_me, auth_session):
    if not auth_me.phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")
    payload = _build_status_payload(username=auth_me.username, phone_number_id=str(auth_me.phone_number_id))
    response = auth_session.post(f"{envs.base_url}/receive", json=payload, timeout=15)
    assert response.status_code == 200


def test_status_payload_with_errors_returns_success(envs, auth_me, auth_session):
    if not auth_me.phone_number_id:
        pytest.skip("phone_number_id missing on /auth/me")
    errors = [
        {
            "code": 131000,
            "title": "Temporarily Unavailable",
            "message": "Upstream provider was not reachable",
        }
    ]
    payload = _build_status_payload(username=auth_me.username, phone_number_id=str(auth_me.phone_number_id), errors=errors)
    response = auth_session.post(f"{envs.base_url}/receive", json=payload, timeout=15)
    assert response.status_code == 200
