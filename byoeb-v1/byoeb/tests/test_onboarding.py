"""
Integration test for WhatsApp onboarding flow.

This test verifies the complete onboarding process by sending a series
of messages and verifying bot responses at each step.
"""
import json
import os
import time
import uuid
from typing import Dict, List, Optional

import pytest
import requests


# Configuration from environment variables
BASE_URL = os.getenv("RECIEVE_URL")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
USER_NAME = os.getenv("USER_NAME")

# Constants
WAIT_INTERVAL_SECONDS = 5
LAST_STEP_INDEX = 4  # Step index for the final question step (index 4 = 5th step)

# Expected message content patterns for context extraction
STEP_CONTEXT_PATTERNS = {
    0: "language",
    1: "Who are you",
    2: "Researchers",
    4: "pregnancy",
}


def get_current_timestamp() -> str:
    """Get current Unix timestamp as string."""
    return str(int(time.time()))


def generate_message_id() -> str:
    """Generate a unique WhatsApp message ID."""
    return f"wamid.{uuid.uuid4().hex}"


def create_base_contact() -> Dict:
    """Create base contact structure for payloads."""
    return {
        "profile": {"name": USER_NAME},
        "wa_id": PHONE_NUMBER_ID,
    }


def create_base_metadata() -> Dict:
    """Create base metadata structure for payloads."""
    return {
              "display_phone_number": "919001386867",
        "phone_number_id": "183958451475612",
    }


def get_api_headers() -> Dict[str, str]:
    """Get standard API request headers."""
    return {
        "accept": "application/json",
        "Content-Type": "application/json",
    }


def create_text_message_payload(
    message_text: str, timestamp: str = "", context_id: Optional[str] = None
) -> Dict:
    """Create a text message payload."""
    message = {
                "from": PHONE_NUMBER_ID,
                "id": "",
        "timestamp": timestamp,
        "text": {"body": message_text},
        "type": "text",
    }
    if context_id:
        message["context"] = {"from": "183958451475612", "id": context_id}
    return message


def create_interactive_message_payload(
    interaction_type: str,
    interaction_id: str,
    interaction_title: str,
    timestamp: str,
    context_id: Optional[str] = None,
) -> Dict:
    """Create an interactive message payload (list_reply or button_reply)."""
    message = {
                "from": PHONE_NUMBER_ID,
                "id": "",
        "timestamp": timestamp,
        "context": {"from": "183958451475612", "id": ""},
                "type": "interactive",
                "interactive": {
            "type": interaction_type,
            f"{interaction_type}": {
                "id": interaction_id,
                "title": interaction_title,
                "description": "",
            },
        },
    }
    if context_id:
        message["context"]["id"] = context_id
    return message


def create_whatsapp_payload(message: Dict) -> Dict:
    """Create complete WhatsApp Business API payload structure."""
    return {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "211506508713627",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                            "metadata": create_base_metadata(),
                            "contacts": [create_base_contact()],
                            "messages": [message],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


# Onboarding flow payloads
ONBOARDING_PAYLOADS = [
    # Step 0: Initial greeting "hi"
    create_whatsapp_payload(create_text_message_payload("hi")),
    # Step 1: Language selection - English
    create_whatsapp_payload(
        create_interactive_message_payload("list_reply", "English", "English", "")
    ),
    # Step 2: User type selection - Others
    create_whatsapp_payload(
        create_interactive_message_payload("button_reply", "others", "Others", "")
    ),
    # Step 3: Confirmation - Yes
    create_whatsapp_payload(
        create_interactive_message_payload("button_reply", "yes", "Yes", "")
    ),
    # Step 4: Question about antra injection
    create_whatsapp_payload(create_text_message_payload("What is a antra injection?")),
]


def get_delete_users_url() -> str:
    """Get the delete users API URL."""
    return BASE_URL.replace("receive", "delete_users")


def get_get_users_url() -> str:
    """Get the get users API URL."""
    return BASE_URL.replace("receive", "get_users")


def get_bot_messages_url(timestamp: str) -> str:
    """Get the bot messages API URL with timestamp."""
    return BASE_URL.replace("receive", f"get_bot_messages?timestamp={timestamp}")


def extract_valid_timestamps(bot_messages: List[Dict]) -> List[int]:
    """Extract valid outgoing timestamps from bot messages."""
    valid_timestamps = []
    for message in bot_messages:
        outgoing_timestamp = message.get("outgoing_timestamp")
        if outgoing_timestamp not in (None, "None", ""):
            valid_timestamps.append(int(str(outgoing_timestamp)))
    return valid_timestamps


def wait_for_bot_response(
    message_url: str, user_message_timestamp: str, max_wait_seconds: int = 60
) -> List[Dict]:
    """
    Wait for bot response by polling the messages endpoint.

    Args:
        message_url: URL to check for bot messages
        user_message_timestamp: Timestamp of the user message we're waiting for response to
        max_wait_seconds: Maximum time to wait (default 60 seconds)

    Returns:
        List of bot messages
    """
    user_timestamp_int = int(user_message_timestamp)
    start_time = time.time()

    while True:
        response = requests.get(message_url)
        response.raise_for_status()
        bot_messages = response.json()

        valid_timestamps = extract_valid_timestamps(bot_messages)
        max_timestamp = max(valid_timestamps) if valid_timestamps else 0

        if max_timestamp >= user_timestamp_int:
            print("Bot response received.")
            return bot_messages

        if time.time() - start_time > max_wait_seconds:
            raise TimeoutError(
                f"Timeout waiting for bot response after {max_wait_seconds} seconds"
            )

        print("Checking for new bot messages...")
        print(f"max_timestamp in while: {max_timestamp}")
        time.sleep(WAIT_INTERVAL_SECONDS)


def extract_context_id_from_response(
    bot_messages: List[Dict], user_message_id: str, user_message_timestamp: str, step: int
) -> Optional[str]:
    """
    Extract context ID from bot response based on step-specific patterns.

    Args:
        bot_messages: List of bot messages
        user_message_id: ID of the user message
        user_message_timestamp: Timestamp of the user message
        step: Current step index

    Returns:
        Context ID if found, None otherwise
    """
    user_timestamp_int = int(user_message_timestamp)
    expected_pattern = STEP_CONTEXT_PATTERNS.get(step)

    for message in bot_messages:
        reply_context = message.get("reply_context", {})
        message_context = message.get("message_context", {})
        outgoing_timestamp = message.get("outgoing_timestamp")

        # Check if this message is a reply to our user message
        if (
            reply_context.get("reply_id") == user_message_id
            and outgoing_timestamp is not None
            and int(str(outgoing_timestamp)) > user_timestamp_int
        ):
            message_text = message_context.get("message_source_text", "")

            # Check for expected pattern in message text
            if expected_pattern and expected_pattern in message_text:
                return message_context.get("message_id")

    return None


def delete_test_user() -> None:
    """Delete the test user before starting the onboarding flow."""
    delete_url = get_delete_users_url()
    headers = get_api_headers()
    data = [PHONE_NUMBER_ID] 

    response = requests.delete(delete_url, headers=headers, data=json.dumps(data))
    response.raise_for_status()
    print(f"Delete user response: {response.status_code} {response.text}")


def verify_user_created() -> None:
    """Verify that the user was created successfully after onboarding."""
    get_url = get_get_users_url()
    headers = get_api_headers()
    data = [PHONE_NUMBER_ID]

    response = requests.get(get_url, headers=headers, data=json.dumps(data))
    response.raise_for_status()
    users = response.json()
    assert len(users) == 1, f"Expected 1 user, but found {len(users)}"


@pytest.mark.integration
def test_whatsapp_onboarding_flow():
    """
    Test the complete WhatsApp onboarding flow.

    This test:
    1. Deletes any existing test user
    2. Sends a series of messages through the onboarding flow
    3. Waits for and verifies bot responses at each step
    4. Verifies that the user was created successfully
    """
    print("Starting onboarding flow test...")

    # Clean up: Delete existing user
    delete_test_user()

    context_id = None
    message_ids = []

    # Process each step in the onboarding flow
    for step_index, payload_template in enumerate(ONBOARDING_PAYLOADS):
        # Create a copy of the payload and update it with dynamic values
        payload = json.loads(json.dumps(payload_template))  # Deep copy
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]

        # Generate unique message ID and timestamp
        message_id = generate_message_id()
        timestamp = get_current_timestamp()
        message_ids.append(message_id)

        message["id"] = message_id
        message["timestamp"] = timestamp

        # Add context ID for interactive messages (except step 0 and step 4)
        if step_index > 0 and step_index != LAST_STEP_INDEX:
            if "context" in message:
                message["context"]["id"] = context_id
            print(f"context_id: {context_id}")

        print(f"-------------------------STEP {step_index + 1}-------------------------")

        # Send the message
        response = requests.post(BASE_URL, json=payload)
        print(f"Payload: {payload}")

        # Wait for bot response (except for the last two steps)
        # Original logic: step < len(ONBOARDING_PAYLOADS) - 2
        if step_index < len(ONBOARDING_PAYLOADS) - 2:
            message_url = get_bot_messages_url(timestamp)
            # Get initial bot messages to check timestamp
            initial_response = requests.get(message_url)
            initial_response.raise_for_status()
            initial_bot_messages = initial_response.json()
            valid_timestamps = extract_valid_timestamps(initial_bot_messages)
            max_timestamp = max(valid_timestamps) if valid_timestamps else 0
            print(f"max_timestamp: {max_timestamp}, msg timestamp: {timestamp}")
            print("Waiting for bot response...")
            bot_messages = wait_for_bot_response(message_url, timestamp)

            # Extract context ID from bot response for next step
            context_id = extract_context_id_from_response(
                bot_messages, message_id, timestamp, step_index
            )

        # Verify the response was successful
        print(f"Step {step_index + 1} response: {response.json()}")
        assert response.status_code == 200, f"Step {step_index + 1} failed with status {response.status_code}"

    # Final verification: Check that user was created
    verify_user_created()
