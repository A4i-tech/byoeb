import pandas as pd
import requests
import argparse
import ast
import asyncio
import re
from datetime import datetime, timezone
from typing import List, Optional

from byoeb.chat_app.configuration.dependency_setup import channel_client_factory
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb.services.chat import constants
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, MessageTypes
from byoeb_core.models.byoeb.user import User
from byoeb_integrations.channel.whatsapp.meta.async_whatsapp_client import StatusCode
from byoeb.constants.user_enums import LanguageCode, UserType
from byoeb.constants.onboarding_text import THANK_YOU_DICT


def clean_template_param(text: str) -> str:
    """Make template parameter safe for WhatsApp: no newlines/tabs, no 4+ spaces."""
    # Replace newlines/tabs with single space
    text = re.sub(r"[\r\n\t]+", " ", text)
    # Collapse multiple spaces to single
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


async def send_welcome_message(
    whatsapp_service: WhatsAppService,
    user: User,
    user_type: str,
    language: str
) -> bool:
    """
    Send a welcome template message to a newly onboarded user.
    
    Args:
        whatsapp_service: WhatsApp service instance
        user: User object
        user_type: User type (ASHA, ANM, etc.)
        language: User language code (en, hi, mr, te)
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        # Normalize and validate language code
        language = language.lower().strip() if language else LanguageCode.ENGLISH.value
        valid_languages = [lc.value for lc in LanguageCode]
        if language not in valid_languages:
            print(f"⚠️  Invalid language '{language}', defaulting to English")
            language = LanguageCode.ENGLISH.value
        
        # Get LanguageCode enum from string value
        lang_code = LanguageCode(language)
        mapped_user_type = UserType.ASHA.value if user_type and user_type.lower() == UserType.OTHERS.value else (user_type or UserType.ASHA.value)
        
        print(f"🔍 Looking for welcome text: user_type={mapped_user_type}, language={lang_code.value}")
        
        # Get welcome message from THANK_YOU_DICT
        welcome_text = THANK_YOU_DICT.get(mapped_user_type, {}).get(lang_code.value, "")
        
        if not welcome_text:
            # Fallback to English if language not found
            print(f"⚠️  No welcome text found for {mapped_user_type}/{lang_code.value}, using English fallback")
            welcome_text = THANK_YOU_DICT.get(mapped_user_type, {}).get(LanguageCode.ENGLISH.value, "Welcome! You have been successfully onboarded.")
        
        print(f"📄 Welcome text (first 50 chars): {welcome_text[:50]}...")
        
        # Clean and prepare template parameter
        template_parameters = [clean_template_param(welcome_text)]
        
        # Create timestamp
        ts = int(datetime.now(timezone.utc).timestamp())
        
        # Create ByoebMessageContext for WhatsApp template message
        byoeb_message = ByoebMessageContext(
            channel_type="whatsapp",
            message_category="onboarding_welcome",
            user=user,
            message_context=MessageContext(
                message_id=f"onboard-welcome-{user.user_id}",
                message_type=MessageTypes.TEMPLATE_TEXT.value,
                message_source_text=None,
                message_english_text=None,
                media_info=None,
                additional_info={
                    constants.TEMPLATE_NAME: "onboard_welcome_v2",
                    constants.TEMPLATE_LANGUAGE: lang_code.value,
                    constants.TEMPLATE_PARAMETERS: template_parameters,
                },
            ),
            reply_context=None,
            cross_conversation_id=None,
            cross_conversation_context=None,
            incoming_timestamp=ts,
            outgoing_timestamp=ts
        )
        
        # Prepare and send template message
        requests = whatsapp_service.prepare_requests(byoeb_message)
        if not requests:
            print(f"⚠️  Failed to prepare welcome message for user {user.phone_number_id}")
            return False
        
        # Find template request (should be the last one or the one with template type)
        template_request = None
        for req in requests:
            if req.get("type") == "template":
                template_request = req
                break
        
        if not template_request:
            print(f"⚠️  No template request found for user {user.phone_number_id}")
            return False
        
        # Send template message
        responses, message_ids = await whatsapp_service.send_requests([template_request])
        
        if len(responses) > 0 and int(responses[0].response_status.status) == StatusCode.SUCCESS.value:
            print(f"✅ Welcome message sent to {user.phone_number_id} (lang: {lang_code.value})")
            return True
        else:
            error_msg = responses[0].response_status.error if len(responses) > 0 else "Unknown error"
            print(f"❌ Failed to send welcome message to {user.phone_number_id}: {error_msg}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending welcome message to {user.phone_number_id}: {str(e)}")
        return False


async def send_welcome_messages_to_users(
    registered_users: List[dict],
    original_users_data: List[dict],
    url: str
) -> None:
    """
    Send welcome template messages to all registered users.
    
    Args:
        registered_users: List of user dictionaries from API response
        original_users_data: List of original user data from Excel (to get language/type)
        url: API base URL
    """
    if not registered_users:
        print("No users to send welcome messages to.")
        return
    
    # Create a mapping of phone_number_id to original user data
    original_data_map = {}
    for orig_user in original_users_data:
        phone = str(orig_user.get("phone_number_id", "")).strip()
        if phone:
            original_data_map[phone] = orig_user
    
    # Initialize WhatsApp service
    whatsapp_service = WhatsAppService(channel_client_factory)
    
    success_count = 0
    failure_count = 0
    
    print(f"\n📤 Sending welcome messages to {len(registered_users)} users...")
    
    for user_data in registered_users:
        try:
            # Handle nested User structure if present (API might return {"User": {...}})
            if "User" in user_data and isinstance(user_data["User"], dict):
                actual_user_data = user_data["User"]
            else:
                actual_user_data = user_data
            
            # Create User object from API response
            user = User(**actual_user_data)
            
            # Skip if user doesn't have required fields
            if not user.phone_number_id:
                print(f"⚠️  Skipping user {user.user_id}: missing phone_number_id")
                failure_count += 1
                continue
            
            # Get user type and language - prioritize original Excel data, then API response
            phone_key = str(user.phone_number_id).strip()
            original_data = original_data_map.get(phone_key, {})
            
            # Get user type - check original data first, then API response
            user_type = (
                original_data.get("user_type") or 
                user.user_type or 
                actual_user_data.get("user_type") or 
                UserType.ASHA.value
            )
            
            # Get language - prioritize original Excel data, then API response
            language = (
                original_data.get("user_language") or
                user.user_language or 
                actual_user_data.get("user_language")
            )
            
            if not language:
                language = LanguageCode.ENGLISH.value
                print(f"⚠️  No language found for user {user.phone_number_id}, defaulting to English")
            else:
                # Normalize language code (ensure it's lowercase and valid)
                language = str(language).lower().strip()
                # Validate it's a supported language code
                valid_languages = [lc.value for lc in LanguageCode]
                if language not in valid_languages:
                    print(f"⚠️  Invalid language code '{language}' for user {user.phone_number_id}, defaulting to English")
                    language = LanguageCode.ENGLISH.value
            
            print(f"📝 User {user.phone_number_id}: type={user_type}, language={language} (from original_data={original_data.get('user_language')}, user.user_language={user.user_language})")
            
            # Send welcome message
            success = await send_welcome_message(
                whatsapp_service=whatsapp_service,
                user=user,
                user_type=user_type,
                language=language
            )
            
            if success:
                success_count += 1
            else:
                failure_count += 1
                
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
            
        except Exception as e:
            print(f"❌ Error processing user {user_data.get('user_id', 'unknown')}: {str(e)}")
            failure_count += 1
    
    print(f"\n📊 Welcome message summary:")
    print(f"   ✅ Success: {success_count}")
    print(f"   ❌ Failed: {failure_count}")
    print(f"   📝 Total: {len(registered_users)}")


def main():
    parser = argparse.ArgumentParser(description="Upload users from Excel files.")
    parser.add_argument("--file", required=True, help="Input Excel file path.")
    parser.add_argument("--url", default="http://0.0.0.0:8000", help="API endpoint URL")
    parser.add_argument("--update", action="store_true", help="If set, update users using the API endpoint")
    parser.add_argument("--sheet", help="output sheet name")
    parser.add_argument("--skip-welcome", action="store_true", help="Skip sending welcome messages after registration")

    args = parser.parse_args()

    file_path = args.file
    df = pd.read_excel(file_path, header=0)
    
    # Handle different column name variations
    if "phone" in df.columns and "phone_number_id" not in df.columns:
        df["phone_number_id"] = df["phone"]
    if "location" in df.columns and "user_location" not in df.columns:
        df["user_location"] = df["location"]
    if "language" in df.columns and "user_language" not in df.columns:
        df["user_language"] = df["language"]
    
    df["phone_number_id"] = df["phone_number_id"].astype(str).apply(lambda x: "91" + x if len(x) == 10 else x)

    users_onboarded = df.to_dict(orient="records") 
    phone_numbers = []  
    for row in users_onboarded:
        # Remove columns that are not needed for registration (like user_id, onboarding_date)
        row.pop("user_id", None)
        row.pop("onboarding_date", None)
        
        # Convert date/timestamp objects to strings if present
        for key, value in list(row.items()):
            if isinstance(value, pd.Timestamp):
                row[key] = value.isoformat()
            elif hasattr(value, 'isoformat'):  # datetime objects
                row[key] = value.isoformat()
        
        # Handle user_location - ensure it has district field
        if "user_location" in row.keys() and row["user_location"]:
            if isinstance(row["user_location"], str):
                try:
                    row["user_location"] = ast.literal_eval(row["user_location"])
                except:
                    # If parsing fails, create a default location dict
                    row["user_location"] = {"district": "Unknown"}
        else:
            # If user_location is missing or empty, create a default one with district
            row["user_location"] = {"district": "Test District"}
        
        # Ensure district is present in user_location
        if not isinstance(row.get("user_location"), dict) or "district" not in row["user_location"]:
            if isinstance(row.get("user_location"), dict):
                row["user_location"]["district"] = "Test District"
            else:
                row["user_location"] = {"district": "Test District"}
        
        phone_numbers.append(row["phone_number_id"])

    response = requests.post(args.url + "/register_users", headers={"Content-Type": "application/json"}, json=users_onboarded)
    if response.status_code != 200:
        print(f"❌ Registration failed with status {response.status_code}")
        print(f"Response: {response.text}")
        try:
            error_details = response.json()
            print(f"Error details: {error_details}")
        except:
            pass
        response.raise_for_status()
    print("Successfully registered")
    
    # Get registered users from response
    registered_users = response.json() if isinstance(response.json(), list) else []
    
    # Debug: Print user data to verify language is in response
    if registered_users:
        print(f"\n🔍 Debug: API returned {len(registered_users)} user(s)")
        for idx, user_data in enumerate(registered_users):
            print(f"   User {idx+1}: phone={user_data.get('phone_number_id')}, language={user_data.get('user_language')}, type={user_data.get('user_type')}")
    
    # Send welcome messages to all registered users (unless --skip-welcome flag is set)
    if not args.skip_welcome and registered_users:
        try:
            # Pass original users_onboarded data to preserve language/type from Excel
            asyncio.run(send_welcome_messages_to_users(registered_users, users_onboarded, args.url))
        except Exception as e:
            print(f"⚠️  Error sending welcome messages: {str(e)}")
            print("   Continuing with other operations...")

    if args.update:
        update_response = requests.post(args.url + "/update_users", headers={"Content-Type": "application/json"}, json=users_onboarded)
        update_response.raise_for_status()
        print("Successfully updated")

    if args.sheet:
        response = requests.post(args.url + "/get_users", headers={"Accept": "application/json", "Content-Type": "application/json"}, json=phone_numbers)
        response.raise_for_status()
        users = response.json()
        print("Successfully extracted")

        df = pd.DataFrame([{
        	"user_id": user_data.get("user_id"),
        	"user_name": user_data.get("user_name"),
        	"phone": user_data.get("phone_number_id"),
        	"location": user_data.get("user_location"),
        	"user_type": user_data.get("user_type"),
        	"test_user": str(user_data.get("test_user")),
        	"onboarding_date": datetime.fromtimestamp(int(user_data.get("created_timestamp", 0))).date() if user_data.get("created_timestamp") else None,
		    "language":user_data.get("user_language")
        } for user_data in users])
        df.to_excel(args.sheet, index=False)


if __name__ == "__main__":
    main()