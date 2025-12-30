"""
Integration test for early return of already onboarded users.

This test verifies that when an already onboarded user sends onboarding messages
(in any language), the system correctly responds with "You are already registered
with the system" message instead of processing it through LLM/vector store.

This script:
1. Registers user using API endpoints (/delete_users + /register_users) for each test
2. Sends POST requests to http://localhost:8000/receive
3. Tests various onboarding message variations across languages
4. Tests normal questions to ensure normal flow works

Usage:
    python -m pytest tests/integration/test_early_return_already_onboarded.py
    or
    python tests/integration/test_early_return_already_onboarded.py
"""

import asyncio
import json
import os
import sys
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
import requests
from dotenv import load_dotenv
import pytest

# Add the byoeb directory to the path (adjust for tests/integration location)
# This allows importing 'byoeb' module when running the script directly
current_file_dir = os.path.dirname(os.path.abspath(__file__))
# Go up from tests/integration/ to byoeb-v1/byoeb/ (project root)
byoeb_root = os.path.abspath(os.path.join(current_file_dir, '..', '..'))
# Add the root directory to path so 'byoeb' module can be imported
if byoeb_root not in sys.path:
    sys.path.insert(0, byoeb_root)

# Load environment variables
environment_path = os.path.join(byoeb_root, 'keys.env')
if os.path.exists(environment_path):
    load_dotenv(environment_path, override=True)

# Import LanguageCode for parametrization
from byoeb.constants.user_enums import LanguageCode

# Test configuration
ENDPOINT_URL = os.getenv("RECIEVE_URL", "http://localhost:8000/receive")
TEST_PHONE_NUMBER = os.getenv("PHONE_NUMBER_ID", "917567071072")
TEST_USER_ID = None  # Will be fetched from database

# Language codes
LANGUAGES = {
    "hi": "Hindi",
    "mr": "Marathi",
    "te": "Telugu",
    "en": "English"
}

# Onboarding messages to test
ONBOARDING_MESSAGES = {
    "en": [
        "onboard-asha",
        "onboard asha",
        "ONBOARD ASHA",
        "Onboard Asha",
        "onboard-ASHA"
    ],
    "hi": [
        "में एक आशा हूँ और मुझे आशा सहेली बोट से जुड़ना है"
    ],
    "mr": [
        "मी आशा आहे आणि मला आशा सहेली बॉटमध्ये सामील व्हायचे आहे"
    ],
    "te": [
        "నేను ఆశాను మరియు ఆశా సహేలి బాట్‌లో చేరాలనుకుంటున్నాను"
    ]
}

# Normal questions to test (to ensure normal flow works)
NORMAL_QUESTIONS = {
    "en": "what is antra injection?",
    "hi": "antra injection क्या है?",
    "mr": "antra injection म्हणजे काय?",
    "te": "antra injection అంటే ఏమిటి?"
}

# Global storage for test results
test_results = {
    "test_timestamp": datetime.now().isoformat(),
    "test_phone_number": TEST_PHONE_NUMBER,
    "endpoint_url": ENDPOINT_URL,
    "results": []
}

# Track registered languages to avoid duplicate registrations
_registered_languages = set()


async def find_user_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """Find user by phone number."""
    try:
        response = requests.post(ENDPOINT_URL.replace("/receive", "/get_users"), json=[phone_number])
        response.raise_for_status()
        users = response.json()
        if users and len(users) > 0:
            return users[0]
        return None
    except Exception as e:
        print(f"⚠️  Could not fetch user: {e}")
        return None


def register_user_with_language(language: str) -> bool:
    """Register user with the specified language using API endpoints.
    
    This function ensures the user is registered only once per language,
    avoiding duplicate registrations for the same language.
    
    Args:
        language: Language code to register the user with
        
    Returns:
        True if registration was successful or already registered, False otherwise
    """
    # Check if already registered for this language
    if language in _registered_languages:
        print(f"ℹ️  User already registered with language {language} ({LANGUAGES.get(language, language)}). Skipping registration.")
        return True
    
    print(f"🔄 Registering user with language {language}...")
    try:
        requests.delete(ENDPOINT_URL.replace("/receive", "/delete_users"), json=[TEST_PHONE_NUMBER]).raise_for_status()
        requests.post(ENDPOINT_URL.replace("/receive", "/register_users"), json=[{
            "phone_number_id": TEST_PHONE_NUMBER,
            "user_location": {"district": "Jaipur"},
            "user_type": "asha",
            "user_language": language,
            "user_name": "Test User",
            "test_user": True
        }]).raise_for_status()
        _registered_languages.add(language)
        print(f"✅ User registered with language {language} ({LANGUAGES.get(language, language)})")
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not register user. Continuing anyway... ({e})")
        return False


def create_whatsapp_payload(message_body: str, phone_number: str = TEST_PHONE_NUMBER) -> Dict[str, Any]:
    """Create WhatsApp webhook payload."""
    timestamp = str(int(time.time()))
    message_id = f"wamid.test{timestamp}{phone_number}"
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "211506508713627",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "919001386867",
                                "phone_number_id": "183958451475612"
                            },
                            "contacts": [
                                {
                                    "profile": {
                                        "name": "Test User"
                                    },
                                    "wa_id": phone_number
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone_number,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "text": {
                                        "body": message_body
                                    },
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }
    
    return payload


def send_request(payload: Dict[str, Any]) -> requests.Response:
    """Send POST request to the endpoint."""
    try:
        response = requests.post(
            ENDPOINT_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None


def get_bot_messages(timestamp: str) -> List[Dict[str, Any]]:
    """Get bot messages after a given timestamp."""
    try:
        # Convert timestamp to int for the API
        timestamp_int = int(timestamp)
        url = ENDPOINT_URL.replace("receive", "get_bot_messages") + f"?timestamp={timestamp_int}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            result = response.json()
            # Ensure result is a list of dictionaries
            if isinstance(result, list):
                return [m for m in result if isinstance(m, dict)]
            elif isinstance(result, dict):
                return [result]
            return []
        else:
            print(f"⚠️  get_bot_messages returned status {response.status_code}: {response.text[:200]}")
        return []
    except Exception as e:
        print(f"⚠️  Could not fetch bot messages: {e}")
        import traceback
        traceback.print_exc()
        return []


def wait_for_bot_response(user_timestamp: str, timeout: int = 30) -> List[Dict[str, Any]]:
    """Wait for bot response after user message timestamp."""
    # Bot message categories (messages FROM bot TO user)
    BOT_MESSAGE_CATEGORIES = {
        "bot_to_asha", "bot_to_asha_response", "bot_to_anm", "bot_to_anm_response",
        "bot_to_anm_verification", "bot_to_anm_consensus", "audio_idk", "text_idk",
        "audio_idk_reconfirmation"
    }
    
    user_timestamp_int = int(user_timestamp)
    start_time = time.time()
    attempt = 0
    debug_printed = False
    
    while time.time() - start_time < timeout:
        attempt += 1
        all_messages = get_bot_messages(user_timestamp)
        
        # Debug: Print message structure on first attempt if no messages found
        if attempt == 1 and len(all_messages) == 0:
            print(f"   🔍 Debug: No messages returned from API for timestamp {user_timestamp_int}")
        elif attempt == 1 and not debug_printed and len(all_messages) > 0:
            # Print structure of first message for debugging
            first_msg = all_messages[0]
            print(f"   🔍 Debug: First message keys: {list(first_msg.keys())}")
            print(f"   🔍 Debug: message_category: {first_msg.get('message_category', 'N/A')}")
            print(f"   🔍 Debug: outgoing_timestamp: {first_msg.get('outgoing_timestamp', 'N/A')}")
            debug_printed = True
        
        # Filter to only bot messages (exclude user messages)
        bot_messages = []
        for m in all_messages:
            if not isinstance(m, dict):
                continue
            # Check message_category at top level
            msg_category = m.get("message_category", "")
            # Also check reply_context.message_category if available
            reply_ctx = m.get("reply_context", {})
            if isinstance(reply_ctx, dict):
                reply_category = reply_ctx.get("message_category", "")
            else:
                reply_category = ""
            
            # Include if it's a bot message category
            if msg_category in BOT_MESSAGE_CATEGORIES or reply_category in BOT_MESSAGE_CATEGORIES:
                bot_messages.append(m)
            # Exclude user messages
            elif msg_category in {"asha_to_bot", "anm_to_bot", "user_to_bot"}:
                continue  # Skip user messages
            # If category is unclear but has outgoing_timestamp, assume it's a bot message
            elif m.get("outgoing_timestamp") not in (None, "None", ""):
                bot_messages.append(m)
        
        if bot_messages:
            valid_timestamps = []
            for m in bot_messages:
                outgoing_ts = m.get("outgoing_timestamp")
                if outgoing_ts not in (None, "None", ""):
                    try:
                        valid_timestamps.append(int(str(outgoing_ts)))
                    except (ValueError, TypeError):
                        pass
            
            if valid_timestamps:
                max_timestamp = max(valid_timestamps)
                if max_timestamp > user_timestamp_int:
                    print(f"   ✅ Found {len(bot_messages)} bot response(s) after {attempt} attempt(s), {int(time.time() - start_time)}s elapsed")
                    return bot_messages
            else:
                if attempt % 5 == 0:  # Print every 5th attempt
                    print(f"   ⏳ Waiting... (attempt {attempt}, {len(bot_messages)} bot messages found but no valid timestamps)")
        else:
            if attempt % 5 == 0:  # Print every 5th attempt
                elapsed = int(time.time() - start_time)
                total_msgs = len(all_messages) if isinstance(all_messages, list) else 0
                # Debug: Show sample message categories if available
                if total_msgs > 0 and attempt == 5:
                    sample_categories = [m.get("message_category", "N/A") for m in all_messages[:3]]
                    print(f"   ⏳ Waiting... (attempt {attempt}, {elapsed}s elapsed, {total_msgs} total messages, 0 bot messages)")
                    print(f"   🔍 Debug: Sample message categories: {sample_categories}")
                else:
                    print(f"   ⏳ Waiting... (attempt {attempt}, {elapsed}s elapsed, {total_msgs} total messages, 0 bot messages)")
        time.sleep(2)
    
    print(f"   ⚠️  Timeout after {timeout}s - no bot response received")
    # Final debug: Show what we got
    final_messages = get_bot_messages(user_timestamp)
    if final_messages:
        print(f"   🔍 Debug: Final check - {len(final_messages)} messages found")
        for i, msg in enumerate(final_messages[:3], 1):
            print(f"   🔍 Debug: Message {i} - category: {msg.get('message_category', 'N/A')}, outgoing_ts: {msg.get('outgoing_timestamp', 'N/A')}")
    return []


def print_response_summary(message: str, response: requests.Response, language: str):
    """Print a summary of the response."""
    print(f"\n{'='*80}")
    print(f"📝 Message: {message}")
    print(f"🌐 Language: {language} ({LANGUAGES.get(language, language)})")
    print(f"{'='*80}")
    
    if response is None:
        print("❌ No response received")
        return
    
    print(f"📊 Status Code: {response.status_code}")
    
    try:
        response_data = response.json()
        print(f"📄 Response: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
    except:
        print(f"📄 Response Text: {response.text[:500]}")
    
    print(f"{'='*80}\n")


def store_test_result(
    test_type: str,
    language: str,
    message: str,
    message_id: str,
    timestamp: str,
    endpoint_response: Optional[requests.Response],
    bot_responses: List[Dict[str, Any]] = None
):
    """Store test result for later validation."""
    result = {
        "test_type": test_type,  # "onboarding" or "normal"
        "language": language,
        "language_name": LANGUAGES.get(language, language),
        "user_message": message,
        "message_id": message_id,
        "timestamp": timestamp,
        "endpoint_status_code": endpoint_response.status_code if endpoint_response else None,
        "endpoint_response": endpoint_response.text[:500] if endpoint_response else None,
        "bot_responses": bot_responses or [],
        "response_texts": []
    }
    
    # Extract response texts from bot responses
    for bot_msg in (bot_responses or []):
        response_text = bot_msg.get("message_context", {}).get("message_source_text", "")
        if response_text:
            result["response_texts"].append(response_text)
    
    test_results["results"].append(result)
    return result


@pytest.mark.parametrize("language", [lang.value for lang in LanguageCode])
async def test_onboarding_messages(language: str):
    """Test onboarding messages for a specific language."""
    print(f"\n{'#'*80}")
    print(f"🧪 Testing Onboarding Messages for {LANGUAGES.get(language, language)} ({language})")
    print(f"{'#'*80}\n")
    
    # Register user with the specified language using API endpoints (only once per language)
    register_user_with_language(language)
    
    # Wait a bit for registration to propagate
    await asyncio.sleep(1)
    
    # Test each onboarding message
    messages = ONBOARDING_MESSAGES.get(language, [])
    if not messages:
        print(f"⚠️  No onboarding messages defined for language {language}")
        return
    
    for message in messages:
        payload = create_whatsapp_payload(message)
        message_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
        timestamp = payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"]
        
        print(f"\n📤 Sending: '{message}'")
        response = send_request(payload)
        print_response_summary(message, response, language)
        
        # Wait for bot response
        print("⏳ Waiting for bot response...")
        await asyncio.sleep(5)  # Give server more time to process and store message
        bot_responses = wait_for_bot_response(timestamp, timeout=45)
        
        # Store result
        result = store_test_result(
            test_type="onboarding",
            language=language,
            message=message,
            message_id=message_id,
            timestamp=timestamp,
            endpoint_response=response,
            bot_responses=bot_responses
        )
        
        if bot_responses:
            print(f"✅ Received {len(bot_responses)} bot response(s)")
            for i, bot_msg in enumerate(bot_responses, 1):
                response_text = bot_msg.get("message_context", {}).get("message_source_text", "")[:200]
                print(f"   Response {i}: {response_text}...")
        else:
            print("⚠️  No bot responses received")
        
        # Wait between requests to avoid overwhelming the server
        await asyncio.sleep(2)


@pytest.mark.parametrize("language", [lang.value for lang in LanguageCode])
async def test_normal_question(language: str):
    """Test a normal question to ensure normal flow works."""
    print(f"\n{'#'*80}")
    print(f"🧪 Testing Normal Question for {LANGUAGES.get(language, language)} ({language})")
    print(f"{'#'*80}\n")
    
    # Register user with the specified language using API endpoints (only once per language)
    register_user_with_language(language)
    
    # Wait a bit for registration to propagate
    await asyncio.sleep(1)
    
    # Test normal question
    message = NORMAL_QUESTIONS.get(language, NORMAL_QUESTIONS["en"])
    payload = create_whatsapp_payload(message)
    message_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    timestamp = payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"]
    
    print(f"\n📤 Sending: '{message}'")
    response = send_request(payload)
    print_response_summary(message, response, language)
    
    # Wait for bot response
    print("⏳ Waiting for bot response...")
    await asyncio.sleep(5)  # Give server more time to process and store message
    bot_responses = wait_for_bot_response(timestamp, timeout=45)
    
    # Store result
    result = store_test_result(
        test_type="normal",
        language=language,
        message=message,
        message_id=message_id,
        timestamp=timestamp,
        endpoint_response=response,
        bot_responses=bot_responses
    )
    
    if bot_responses:
        print(f"✅ Received {len(bot_responses)} bot response(s)")
        for i, bot_msg in enumerate(bot_responses, 1):
            response_text = bot_msg.get("message_context", {}).get("message_source_text", "")[:200]
            print(f"   Response {i}: {response_text}...")
    else:
        print("⚠️  No bot responses received")
    
    # Wait between requests
    await asyncio.sleep(2)


async def verify_user_exists():
    """Verify that the test user exists in the database."""
    print("🔍 Verifying test user exists in database...")
    user_doc = await find_user_by_phone(TEST_PHONE_NUMBER)
    
    if user_doc:
        # Handle both API response format and potential nested User structure
        if isinstance(user_doc, dict):
            user_data = user_doc.get("User", user_doc)
            print(f"✅ User found:")
            print(f"   - User ID: {user_doc.get('_id', 'N/A')}")
            print(f"   - Phone: {user_data.get('phone_number_id', 'N/A')}")
            print(f"   - Language: {user_data.get('user_language', 'N/A')}")
            print(f"   - User Type: {user_data.get('user_type', 'N/A')}")
        return True
    else:
        print(f"ℹ️  User with phone number {TEST_PHONE_NUMBER} not found")
        print(f"   Tests will register the user automatically")
        return False


async def main():
    """Main test function."""
    print("="*80)
    print("🚀 Starting Early Return Test for Already Onboarded Users")
    print("="*80)
    
    # Verify endpoint is accessible
    print(f"\n🔍 Checking if endpoint is accessible: {ENDPOINT_URL}")
    try:
        response = requests.get(ENDPOINT_URL.replace("/receive", "/"), timeout=5)
        print(f"✅ Endpoint is accessible (status: {response.status_code})")
    except:
        print(f"⚠️  Warning: Could not verify endpoint accessibility. Make sure server is running.")
    
    # Verify user exists (optional - tests will register user if needed)
    user_exists = await verify_user_exists()
    if not user_exists:
        print("\nℹ️  Test user not found. Tests will register the user automatically.")
    
    print("\n" + "="*80)
    print("Starting Tests...")
    print("="*80)
    
    # Test for each language
    languages_to_test = ["en", "hi", "mr", "te"]
    
    for lang in languages_to_test:
        # Test onboarding messages
        await test_onboarding_messages(lang)
        
        # Test normal question
        await test_normal_question(lang)
        
        print(f"\n✅ Completed tests for {LANGUAGES.get(lang, lang)}")
        print("\n" + "-"*80 + "\n")
    
    print("="*80)
    print("✅ All tests completed!")
    print("="*80)
    
    # Generate validation report
    generate_validation_report()


def validate_onboarding_responses() -> Dict[str, Any]:
    """Validate that onboarding responses contain 'already registered' message."""
    validation_results = {
        "total_onboarding_tests": 0,
        "passed": 0,
        "failed": 0,
        "details": []
    }
    
    # Expected indicators for "already registered" message in different languages
    already_registered_indicators = {
        "en": ["already registered", "registered with the system"],
        "hi": ["पहले से ही पंजीकृत", "पंजीकृत"],
        "mr": ["आधीच नोंदणीकृत", "नोंदणीकृत"],
        "te": ["నమోదు చేయబడ్డారు", "నమోదు"]
    }
    
    for result in test_results["results"]:
        if result["test_type"] != "onboarding":
            continue
        
        validation_results["total_onboarding_tests"] += 1
        language = result["language"]
        response_texts = " ".join(result["response_texts"]).lower()
        
        # Check for expected indicators
        indicators = already_registered_indicators.get(language, already_registered_indicators["en"])
        found_indicator = any(ind.lower() in response_texts for ind in indicators)
        
        validation = {
            "language": language,
            "message": result["user_message"],
            "has_response": len(result["response_texts"]) > 0,
            "found_already_registered": found_indicator,
            "response_texts": result["response_texts"],
            "status": "PASS" if found_indicator else "FAIL"
        }
        
        if found_indicator:
            validation_results["passed"] += 1
        else:
            validation_results["failed"] += 1
        
        validation_results["details"].append(validation)
    
    return validation_results


def generate_validation_report():
    """Generate and save validation report."""
    print("\n" + "="*80)
    print("📊 Generating Validation Report")
    print("="*80)
    
    # Validate onboarding responses
    validation = validate_onboarding_responses()
    
    print(f"\n📈 Onboarding Response Validation:")
    print(f"   Total tests: {validation['total_onboarding_tests']}")
    print(f"   ✅ Passed: {validation['passed']}")
    print(f"   ❌ Failed: {validation['failed']}")
    
    if validation["failed"] > 0:
        print(f"\n❌ Failed Tests:")
        for detail in validation["details"]:
            if detail["status"] == "FAIL":
                print(f"   - {detail['language']}: '{detail['message']}'")
                if detail["has_response"]:
                    print(f"     Response: {detail['response_texts'][0][:100]}...")
                else:
                    print(f"     No response received")
    
    # Save results to JSON file
    output_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path = os.path.join(os.path.dirname(__file__), output_file)
    
    report = {
        "test_summary": {
            "total_tests": len(test_results["results"]),
            "onboarding_tests": validation["total_onboarding_tests"],
            "normal_tests": len([r for r in test_results["results"] if r["test_type"] == "normal"]),
            "validation_passed": validation["passed"],
            "validation_failed": validation["failed"]
        },
        "validation_results": validation,
        "all_test_results": test_results
    }
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to: {output_path}")
    except Exception as e:
        print(f"\n⚠️  Could not save results to file: {e}")
    
    # Print summary table
    print(f"\n📋 Test Results Summary:")
    print(f"{'Language':<12} {'Type':<12} {'Message':<40} {'Status':<10} {'Has Response'}")
    print("-" * 100)
    for result in test_results["results"]:
        lang = result["language"]
        msg_type = result["test_type"]
        msg = result["user_message"][:38] + ".." if len(result["user_message"]) > 40 else result["user_message"]
        has_resp = "✅" if result["response_texts"] else "❌"
        
        # Determine status
        if msg_type == "onboarding":
            validation_detail = next((v for v in validation["details"] 
                                     if v["message"] == result["user_message"]), None)
            status = validation_detail["status"] if validation_detail else "UNKNOWN"
        else:
            status = "OK" if has_resp == "✅" else "NO_RESP"
        
        print(f"{lang:<12} {msg_type:<12} {msg:<40} {status:<10} {has_resp}")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    asyncio.run(main())

