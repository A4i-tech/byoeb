import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
from collections import Counter, defaultdict
import pandas as pd
import re

from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.chat_app.configuration.config import app_config
from byoeb.chat_app.configuration.dependency_setup import get_leaderboard_service, user_db_service, message_db_service
from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory

IST = ZoneInfo("Asia/Kolkata")

# Azure App Insights Loggers
run_logger = AppInsightsLogHandler.getLogger("leaderboard_run")
send_logger = AppInsightsLogHandler.getLogger("leaderboard_send")

# TEST MODE: Set to True to send only to your test phone number
# Set to False to send to all users (production mode)
TEST_MODE_SEND_TO_ME_ONLY = False  # Set to True for testing, False for production

# Your test phone number (read from keys.env using PHONE_NUMBER_ID)
TEST_PHONE_NUMBER = os.getenv("PHONE_NUMBER_ID") if TEST_MODE_SEND_TO_ME_ONLY else None

def validate_and_format_phone_number(phone: str) -> Optional[str]:
    """
    Validate and format phone number for WhatsApp.
    
    Args:
        phone: Phone number in any format
        
    Returns:
        Formatted phone number (digits only, 11-13 digits) or None if invalid
        
    Examples:
        "917567071072" -> "917567071072"
        "+91 75670 71072" -> "917567071072"
        "07567071072" -> None (missing country code)
    """
    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', phone)
    
    # Check length (WhatsApp requires 11-13 digits with country code)
    if len(digits_only) < 11 or len(digits_only) > 13:
        print(f"⚠️  Invalid phone number length: {phone} -> {digits_only} ({len(digits_only)} digits)")
        print(f"   Expected: 11-13 digits (country code + number)")
        return None
    
    # Common validation: India numbers should start with 91
    if digits_only.startswith('91') and len(digits_only) == 12:
        return digits_only
    elif len(digits_only) == 10:
        # Missing country code for India
        print(f"⚠️  Phone number missing country code: {phone}")
        print(f"   Adding India country code (91)...")
        return "91" + digits_only
    elif len(digits_only) >= 11:
        return digits_only
    
    return None

def print_delivery_troubleshooting(phone: str, message_id: str, status: str):
    """
    Print troubleshooting information for message delivery issues.
    """
    phone_digits = re.sub(r'\D', '', phone)
    phone_length = len(phone_digits)
    
    print(f"\n🔍 TROUBLESHOOTING for {phone}:")
    print(f"   Message ID: {message_id}")
    print(f"   API Status: {status}")
    print(f"\n   Common reasons messages aren't delivered:")
    print(f"   1. Phone number not registered with WhatsApp")
    print(f"      → Verify {phone} has WhatsApp installed and active")
    print(f"   2. Phone number format issue")
    print(f"      → Current format: {phone} ({phone_length} digits)")
    print(f"      → Should be: country code + number (11-13 digits, no + or spaces)")
    print(f"   3. Template not fully approved")
    print(f"      → Check WhatsApp Business Manager for template status")
    print(f"   4. Delivery delay")
    print(f"      → Template messages can take 1-5 minutes to deliver")
    print(f"   5. Number not in business contact list")
    print(f"      → Some accounts require numbers to be added first")
    print(f"   6. Check WhatsApp Business Manager")
    print(f"      → Go to Message Templates → View delivery reports")
    print(f"      → Look for message ID: {message_id}")
    print(f"\n   Next steps:")
    print(f"   - Wait 5-10 minutes and check WhatsApp again")
    print(f"   - Verify phone number format is correct")
    print(f"   - Check if template is fully approved (not just 'Active')")
    print(f"   - Try sending to a number that previously received messages")

def get_user_district(user) -> Optional[str]:
    """
    Extract district from user object.
    
    Args:
        user: User object (can be None, dict, or object with user_location attribute)
        
    Returns:
        Optional[str]: District name or None if not found/unknown
    """
    if not user:
        return None
    loc = getattr(user, "user_location", None) or {}
    if isinstance(loc, dict):
        dist = loc.get("district") or loc.get("District")
    else:
        dist = getattr(loc, "district", None) or getattr(loc, "District", None)
    if dist:
        dist_str = str(dist).strip()
        if dist_str.lower() not in ["unknown", "none", ""]:
            return dist_str
    return None

def get_user_block(user) -> Optional[str]:
    """
    Extract block from user object.
    
    Args:
        user: User object (can be None, dict, or object with user_location attribute)
        
    Returns:
        Optional[str]: Block name or None if not found/unknown
    """
    if not user:
        return None
    loc = getattr(user, "user_location", None) or {}
    if isinstance(loc, dict):
        block = loc.get("block") or loc.get("Block")
    else:
        block = getattr(loc, "block", None) or getattr(loc, "Block", None)
    if block:
        block_str = str(block).strip()
        if block_str.lower() not in ["unknown", "none", ""]:
            return block_str
    return None

def has_location_info(user) -> bool:
    """
    Check if user has valid district and block information.
    
    Args:
        user: User object
        
    Returns:
        bool: True if user has both district and block, False otherwise
    """
    district = get_user_district(user)
    block = get_user_block(user)
    return district is not None and block is not None

def get_type_indicator_translation(is_block_leaderboard: bool, user_language: str = "en") -> str:
    """
    Get translated type indicator ("Blocks" or "Districts") based on user language.
    
    Args:
        is_block_leaderboard: If True, returns "Blocks" translation, otherwise "Districts" translation
        user_language: User's language code (en, hi, mr, te)
        
    Returns:
        Translated string for "Blocks" or "Districts"
    """
    # Translation dictionary for "Blocks" and "Districts"
    translations = {
        "en": {
            "blocks": "Blocks",
            "districts": "Districts"
        },
        "hi": {
            "blocks": "ब्लॉक",
            "districts": "जिले"
        },
        "mr": {
            "blocks": "ब्लॉक",
            "districts": "जिल्हे"
        },
        "te": {
            "blocks": "బ్లాక్‌లు",
            "districts": "జిల్లాలు"
        }
    }
    
    # Default to English if language not found
    lang_dict = translations.get(user_language, translations["en"])
    
    if is_block_leaderboard:
        return lang_dict["blocks"]
    else:
        return lang_dict["districts"]

def get_prefix_translation(is_block_leaderboard: bool, user_language: str = "en") -> str:
    """
    Get translated prefix ("Block " or "District " with space) based on user language.
    Used for prefixing names in parameters 1, 4, 7.
    
    Args:
        is_block_leaderboard: If True, returns "Block " translation, otherwise "District " translation
        user_language: User's language code (en, hi, mr, te)
        
    Returns:
        Translated string for "Block " or "District " (with trailing space)
    """
    # Translation dictionary for "Block " and "District " (singular with space)
    translations = {
        "en": {
            "block": "Block ",
            "district": "District "
        },
        "hi": {
            "block": "ब्लॉक ",
            "district": "जिला "
        },
        "mr": {
            "block": "ब्लॉक ",
            "district": "जिल्हा "
        },
        "te": {
            "block": "బ్లాక్ ",
            "district": "జిల్లా "
        }
    }
    
    # Default to English if language not found
    lang_dict = translations.get(user_language, translations["en"])
    
    if is_block_leaderboard:
        return lang_dict["block"]
    else:
        return lang_dict["district"]

async def fetch_phone_numbers_for_asha_and_test_users() -> List[str]:
    """
    Retrieves phone numbers for all ASHA workers and test users from the database.

    Returns:
        List[str]: Phone numbers of ASHA workers and test users
    """
    # Selection (all vs test-only) is controlled inside the service function
    # Use service layer; service internally respects TEST_USERS_ONLY env flag
    return await user_db_service.fetch_phone_numbers_for_asha_and_test_users()

async def build_district_leaderboard_last_week_ist(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard of districts based on message activity from the previous week in IST timezone.
    
    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        
    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    leaderboard_service = await get_leaderboard_service()
    # Use week strategy explicitly - addressing review comment #5
    week_strategy = TimeWindowFactory.create_strategy('week')
    return await leaderboard_service.build_district_leaderboard(message_categories, processing_batch_size, week_strategy)

async def build_district_leaderboard_with_strategy(
    strategy_type: str,
    message_categories: Optional[List[str]] = None,
    processing_batch_size: int = 1000,
    **strategy_kwargs
) -> pd.DataFrame:
    """
    Builds a leaderboard using a specific time window strategy.

    Args:
        strategy_type: Type of strategy ('week', 'month', 'year', 'custom')
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        **strategy_kwargs: Additional arguments for strategy creation (e.g., days_back for custom)

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    leaderboard_service = await get_leaderboard_service()
    strategy = TimeWindowFactory.create_strategy(strategy_type, **strategy_kwargs)
    return await leaderboard_service.build_district_leaderboard(message_categories, processing_batch_size, strategy)

async def build_monthly_leaderboard(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for the previous month.

    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('month', message_categories, processing_batch_size)

async def build_yearly_leaderboard(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for the previous year.

    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('year', message_categories, processing_batch_size)

async def build_custom_leaderboard(days_back: int, message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for a custom time period.

    Args:
        days_back: Number of days to look back
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('custom', message_categories, processing_batch_size, days_back=days_back)

async def build_block_leaderboard_for_district(
    district: str,
    message_categories: Optional[List[str]] = None,
    processing_batch_size: int = 1000
) -> pd.DataFrame:
    """
    Builds a leaderboard of top 3 blocks within a specific district based on message activity from the previous week.
    
    Args:
        district: District name to filter blocks by
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        
    Returns:
        pd.DataFrame: Sorted leaderboard with top 3 blocks in the district
    """
    week_strategy = TimeWindowFactory.create_strategy('week')
    start_timestamp, end_timestamp = week_strategy.calculate_window()
    
    # Get repository instances from message_db_service
    repository_factory = await message_db_service._get_repository_factory()
    message_repository = await repository_factory.get_message_repository()
    
    # Define projection for required fields only
    required_fields_only = {"_id": 0, "message_data.user.user_id": 1, "message_data.incoming_timestamp": 1}
    
    # Get messages using repository
    message_iterator = await message_repository.find_messages_by_time_range(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        message_categories=message_categories,
        projection=required_fields_only
    )
    message_documents = [doc async for doc in message_iterator]
    
    # Sort messages by timestamp (descending)
    message_documents.sort(key=lambda x: x.get("message_data", {}).get("incoming_timestamp", 0), reverse=True)
    
    if not user_db_service:
        raise ValueError("user_db_service must be provided for leaderboard functionality")
    
    user_objects_cache = {}
    block_message_counts = Counter()
    block_unique_users = defaultdict(set)
    block_first_message_timestamp = {}
    block_last_message_timestamp = {}
    
    # Normalize district name for comparison (case-insensitive)
    district_normalized = district.strip().lower()
    
    # Process messages in batches
    for i in range(0, len(message_documents), processing_batch_size):
        message_batch = message_documents[i:i + processing_batch_size]
        
        await user_db_service.hydrate_users(message_batch, user_objects_cache)
        
        for message_document in message_batch:
            message_data = message_document.get("message_data", {})
            user_id = message_data.get("user", {}).get("user_id")
            message_timestamp = message_data.get("incoming_timestamp")
            
            if not isinstance(message_timestamp, int) or message_timestamp < start_timestamp or message_timestamp > end_timestamp:
                continue
            
            user_object = user_objects_cache.get(user_id)
            user_district = get_user_district(user_object)
            user_block = get_user_block(user_object)
            
            # Only process if user is in the specified district and has block info
            if not user_district or not user_block:
                continue
            
            if user_district.strip().lower() != district_normalized:
                continue
            
            block_message_counts[user_block] += 1
            if user_id:
                block_unique_users[user_block].add(user_id)
            
            block_first_message_timestamp[user_block] = min(block_first_message_timestamp.get(user_block, message_timestamp), message_timestamp)
            block_last_message_timestamp[user_block] = max(block_last_message_timestamp.get(user_block, message_timestamp), message_timestamp)
    
    leaderboard_rows = [
        {
            "block": block_name,
            "message_count": message_count,
            "unique_users": len(block_unique_users[block_name]),
            "first_seen": datetime.fromtimestamp(block_first_message_timestamp[block_name]).strftime("%d-%m-%Y %H:%M:%S"),
            "last_seen": datetime.fromtimestamp(block_last_message_timestamp[block_name]).strftime("%d-%m-%Y %H:%M:%S")
        }
        for block_name, message_count in block_message_counts.items()
    ]
    
    if not leaderboard_rows:
        return pd.DataFrame(
            columns=["block", "message_count", "unique_users", "first_seen", "last_seen"]
        )
    
    # Sort by message_count and unique_users, then take top 3
    df = pd.DataFrame(leaderboard_rows).sort_values(by=["message_count", "unique_users"], ascending=False, ignore_index=True)
    return df.head(3)

async def format_leaderboard_as_template_parameters(
    top3_df: pd.DataFrame, 
    is_block_leaderboard: bool = False,
    user_language: str = "en"
) -> List[str]:
    """
    Format leaderboard data as template parameters for WhatsApp template message.
    
    Args:
        top3_df: DataFrame with leaderboard data (either districts or blocks)
        is_block_leaderboard: If True, expects 'block' column, otherwise expects 'district' column
        user_language: User's language code (en, hi, mr, te) for translating type indicator
    
    Returns:
        List of parameters for the template (includes translated type as last parameter: "Blocks" or "Districts")
    """
    # Determine the type indicator (plural, translated based on user language)
    type_indicator = get_type_indicator_translation(is_block_leaderboard, user_language)
    
    # Get translated prefix for names
    prefix = get_prefix_translation(is_block_leaderboard, user_language)
    
    # Always return 10 parameters (3 items * 3 fields + 1 type indicator)
    parameters = []
    name_col = 'block' if is_block_leaderboard else 'district'
    # prefix is already set above with translation
    
    # Add parameters for existing items
    for idx, row in top3_df.iterrows():
        raw_name = str(row[name_col]).strip() if pd.notna(row[name_col]) else "N/A"
        
        # Add translated prefix: "Block " for blocks, "District " for districts
        if raw_name and raw_name != "N/A":
            name = prefix + raw_name
        else:
            name = "N/A"
        
        message_count = str(int(row['message_count'])) if pd.notna(row['message_count']) else "0"
        unique_users = str(int(row['unique_users'])) if pd.notna(row['unique_users']) else "0"
        
        # Ensure no empty strings or None values
        parameters.append(name if name else "N/A")
        parameters.append(message_count if message_count else "0")
        parameters.append(unique_users if unique_users else "0")
    
    # If less than 3 items, pad with placeholder values
    # WhatsApp requires all parameters to be non-empty strings
    # Use "N/A" for missing names and "0" for missing counts
    while len(parameters) < 9:
        if len(parameters) % 3 == 0:  # Name position (0, 3, 6)
            parameters.append("N/A")
        else:  # Count or users position (1, 2, 4, 5, 7, 8)
            parameters.append("0")
    
    # Add 10th parameter: type indicator ("Blocks" or "Districts" - translated based on user language)
    parameters.append(type_indicator)
    
    # Validate: ensure exactly 10 parameters, all non-empty strings
    assert len(parameters) == 10, f"Expected 10 parameters, got {len(parameters)}"
    assert all(isinstance(p, str) and len(p) > 0 for p in parameters), \
        f"All parameters must be non-empty strings. Got: {parameters}"
    
    return parameters[:10]  # Ensure exactly 10 parameters (3 items * 3 fields + 1 type)

async def send_leaderboard_template_messages(
    phone_numbers: List[str],
    top3_df: pd.DataFrame,
    user_db_service,
    message_db_service
):
    """
    Send leaderboard messages as WhatsApp template messages to all users.
    
    NOTE: This function ONLY READS from the database (no modifications).
    It uses: find_messages_by_time_range, get_users, hydrate_users - all read-only operations.
    
    Sends 10 parameters: 3 items × (name, message_count, unique_users) + type indicator
    """
    from byoeb.chat_app.configuration.dependency_setup import channel_client_factory
    from byoeb.services.channel.whatsapp import WhatsAppService
    from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, ReplyContext, MessageTypes
    from byoeb_core.models.byoeb.user import User
    from byoeb.services.chat import constants
    import hashlib
    
    whatsapp_service = WhatsAppService(channel_client_factory)
    
    # Get user information for all phone numbers
    user_ids = [hashlib.md5(phone.encode()).hexdigest() for phone in phone_numbers]
    users = await user_db_service.get_users(user_ids)
    user_map = {user.phone_number_id: user for user in users if user}
    
    # Pre-calculate block leaderboards for all unique districts to avoid recalculating
    # This is much more efficient than calculating for each user individually
    unique_districts = set()
    for user in users:
        if user and has_location_info(user):
            district = get_user_district(user)
            if district:
                unique_districts.add(district.strip().lower())
    
    print(f"\n📊 Pre-calculating block leaderboards for {len(unique_districts)} unique districts...")
    run_logger.info("Pre-calculating block leaderboards", extra={AppInsightsLogHandler.DETAILS: {
        "context": "pre_calculate_block_leaderboards",
        "unique_districts_count": len(unique_districts),
        "districts": list(unique_districts)
    }})
    
    block_leaderboard_cache = {}
    for district in unique_districts:
        try:
            print(f"   Calculating block leaderboard for district: {district}")
            block_df = await build_block_leaderboard_for_district(
                district=district,
                message_categories=None,
                processing_batch_size=1000
            )
            block_leaderboard_cache[district] = block_df
            print(f"   ✅ Found {len(block_df)} blocks for {district}")
            run_logger.info(f"Block leaderboard calculated for district", extra={AppInsightsLogHandler.DETAILS: {
                "context": "build_block_leaderboard",
                "district": district,
                "blocks_found": len(block_df)
            }})
        except Exception as e:
            print(f"   ⚠️  Error building block leaderboard for {district}: {e}")
            block_leaderboard_cache[district] = None  # Cache None to avoid retrying
            run_logger.error(f"Error building block leaderboard for district", extra={AppInsightsLogHandler.DETAILS: {
                "context": "build_block_leaderboard_error",
                "district": district,
                "error": str(e)
            }})
    
    successful_districts = len([v for v in block_leaderboard_cache.values() if v is not None])
    print(f"✅ Block leaderboard cache ready with {successful_districts} districts\n")
    run_logger.info("Block leaderboard cache ready", extra={AppInsightsLogHandler.DETAILS: {
        "context": "block_leaderboard_cache_ready",
        "successful_districts": successful_districts,
        "total_districts": len(unique_districts)
    }})
    
    results = []
    for phone in phone_numbers:
        try:
            # Validate and format phone number
            formatted_phone = validate_and_format_phone_number(phone)
            if not formatted_phone:
                print(f"❌ Invalid phone number format: {phone}")
                send_logger.warning("Invalid phone number format", extra={AppInsightsLogHandler.DETAILS: {
                    "context": "validate_phone_number",
                    "phone": phone,
                    "user_id": user.user_id if user else None
                }})
                results.append({
                    "phone": phone,
                    "status": "error",
                    "message": "Invalid phone number format"
                })
                continue
            
            if formatted_phone != phone:
                print(f"📞 Phone number formatted: {phone} → {formatted_phone}")
                phone = formatted_phone  # Use formatted version
            
            # Get user language, default to 'en' if user not found
            user = user_map.get(phone)
            user_language = user.user_language if user and user.user_language else 'en'
            
            # Determine which leaderboard to use for this user
            # If user has district and block info, show top 3 blocks in their district
            # Otherwise, show global top 3 districts
            user_has_location = has_location_info(user)
            is_block_leaderboard = False
            user_leaderboard_df = top3_df  # Default to global districts
            
            if user_has_location:
                user_district = get_user_district(user)
                if user_district:
                    district_key = user_district.strip().lower()
                    # Use cached block leaderboard if available
                    if district_key in block_leaderboard_cache:
                        cached_block_df = block_leaderboard_cache[district_key]
                        if cached_block_df is not None and len(cached_block_df) > 0:
                            user_leaderboard_df = cached_block_df
                            is_block_leaderboard = True
                            print(f"📍 User {phone} → Using cached block leaderboard for district {user_district} ({len(cached_block_df)} blocks)")
                            send_logger.debug("Using block leaderboard for user", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "user_block_leaderboard",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "district": user_district,
                                "blocks_count": len(cached_block_df)
                            }})
                        else:
                            print(f"📍 User {phone} → No blocks found for district {user_district}, using global leaderboard")
                            send_logger.debug("No blocks found, using global leaderboard", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "user_fallback_global",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "district": user_district,
                                "reason": "no_blocks_found"
                            }})
                    else:
                        print(f"📍 User {phone} → District {user_district} not in cache, using global leaderboard")
                        send_logger.debug("District not in cache, using global leaderboard", extra={AppInsightsLogHandler.DETAILS: {
                            "context": "user_fallback_global",
                            "phone": phone,
                            "user_id": user.user_id if user else None,
                            "district": user_district,
                            "reason": "not_in_cache"
                        }})
                else:
                    print(f"📍 User {phone} → Has location info but no district, using global leaderboard")
                    send_logger.debug("User has location but no district", extra={AppInsightsLogHandler.DETAILS: {
                        "context": "user_fallback_global",
                        "phone": phone,
                        "user_id": user.user_id if user else None,
                        "reason": "no_district"
                    }})
            else:
                print(f"📍 User {phone} → No location info, using global district leaderboard")
                send_logger.debug("User has no location info", extra={AppInsightsLogHandler.DETAILS: {
                    "context": "user_fallback_global",
                    "phone": phone,
                    "user_id": user.user_id if user else None,
                    "reason": "no_location_info"
                }})
            
            # Format template parameters based on user's leaderboard
            template_parameters = await format_leaderboard_as_template_parameters(
                user_leaderboard_df, 
                is_block_leaderboard=is_block_leaderboard,
                user_language=user_language
            )
            
            # Validate template parameters before sending (always expect 10 parameters)
            if not template_parameters or len(template_parameters) != 10:
                print(f"❌ ERROR: Invalid template parameters for {phone}")
                print(f"   Expected 10 parameters, got: {len(template_parameters) if template_parameters else 0}")
                print(f"   Parameters: {template_parameters}")
                continue
            
            # Ensure all parameters are non-empty strings (no None or empty values)
            validated_parameters = []
            for i, param in enumerate(template_parameters):
                if param is None:
                    print(f"⚠️  WARNING: Parameter {i+1} is None, replacing with 'N/A'")
                    validated_parameters.append("N/A")
                elif not isinstance(param, str):
                    validated_parameters.append(str(param) if param else "N/A")
                elif len(param.strip()) == 0:
                    print(f"⚠️  WARNING: Parameter {i+1} is empty, replacing with 'N/A'")
                    validated_parameters.append("N/A")
                else:
                    validated_parameters.append(param.strip())
            
            template_parameters = validated_parameters
            
            # Build a text representation of the leaderboard (for logging/fallback)
            # Last parameter is the translated type indicator ("Blocks" or "Districts")
            type_indicator = template_parameters[-1] if len(template_parameters) > 0 else get_type_indicator_translation(is_block_leaderboard, user_language)
            
            # Build leaderboard text: 10 parameters (9 data + 1 type)
            if type_indicator in ["Block", "ब्लॉक", "బ్లాక్"]:  # Block indicators
                leaderboard_text = "📊 Top 3 Blocks in Your District with Highest Interactions:\n\n"
            else:
                leaderboard_text = "📊 Top 3 Districts with Highest Interactions:\n\n"
            
            for i in range(0, 9, 3):
                item = template_parameters[i]
                count = template_parameters[i+1]
                users = template_parameters[i+2]
                if item != "N/A":
                    leaderboard_text += f"{i//3 + 1}) {item}: {count} messages from {users} users\n"
            
            # Create ByoebMessageContext with template information
            # Following the consensus pattern: create with REGULAR_TEXT and text fields,
            # then prepare_requests will create both text and template requests
            byoeb_message = ByoebMessageContext(
                channel_type="whatsapp",
                message_category="leaderboard",
                user=User(
                    user_id=user.user_id if user else hashlib.md5(phone.encode()).hexdigest(),
                    user_type=user.user_type if user else "asha",
                    user_language=user_language,
                    phone_number_id=phone,
                    test_user=user.test_user if user else False,
                ),
                message_context=MessageContext(
                    message_id=f"leaderboard-{phone}-{int(datetime.now(timezone.utc).timestamp())}",
                    message_type=MessageTypes.REGULAR_TEXT.value,  # Start with REGULAR_TEXT like consensus does
                    message_source_text=leaderboard_text,  # Set text fields (like consensus does)
                    message_english_text=leaderboard_text,  # Set text fields (like consensus does)
                    additional_info={
                        constants.TEMPLATE_NAME: "leaderboardv2",
                        constants.TEMPLATE_LANGUAGE: user_language,
                        constants.TEMPLATE_PARAMETERS: template_parameters
                    }
                ),
                reply_context=None,
                cross_conversation_id=None,
                cross_conversation_context=None,
                incoming_timestamp=int(datetime.now(timezone.utc).timestamp()),
                outgoing_timestamp=int(datetime.now(timezone.utc).timestamp())
            )
            
            # Prepare requests - this will create both text and template requests (like consensus does)
            requests = whatsapp_service.prepare_requests(byoeb_message)
            
            # Debug: Show what requests were generated
            print(f"\n🔍 DEBUG: Generated {len(requests)} request(s) for {phone}")
            for i, req in enumerate(requests):
                req_type = req.get("type", "unknown")
                print(f"   Request {i}: type={req_type}")
                if req_type == "template":
                    print(f"      Template name: {req.get('template', {}).get('name', 'N/A')}")
                    print(f"      Template language: {req.get('template', {}).get('language', {}).get('code', 'N/A')}")
            
            # Select only the template request
            # prepare_requests returns: [text_message, template_message] when both are present
            # But we should find it by type, not by index, to be more robust
            template_request = None
            for req in requests:
                if req.get("type") == "template":
                    template_request = req
                    break
            
            if not template_request:
                print(f"❌ ERROR: No template request found in {len(requests)} request(s) for {phone}")
                print(f"   Request types: {[req.get('type', 'unknown') for req in requests]}")
                continue
            
            # Change message type to TEMPLATE_TEXT (like consensus does for inactive users)
            byoeb_message.message_context.message_type = MessageTypes.TEMPLATE_TEXT.value
            
            # Verify template request is correct
            if template_request:
                print(f"\n📤 Preparing to send template to {phone} (lang: {user_language})")
                print(f"   Template: {constants.TEMPLATE_NAME}={byoeb_message.message_context.additional_info[constants.TEMPLATE_NAME]}")
                print(f"   Parameters ({len(template_parameters)}): {template_parameters}")
                print(f"   Parameter validation: All parameters are non-empty strings: {all(isinstance(p, str) and len(p) > 0 for p in template_parameters)}")
                print(f"   Using 10 parameters: 3 items × (name, count, users) + type indicator")
                
                # Log the exact payload being sent (for debugging)
                print(f"\n   📋 WhatsApp API Payload:")
                print(f"      {json.dumps(template_request, indent=6)}")
                
                # Send only the template request (like consensus does for inactive users)
                responses, message_ids = await whatsapp_service.send_requests([template_request])
                
                # Check response status
                if responses and len(responses) > 0:
                    response = responses[0]
                    status = response.response_status.status if hasattr(response, 'response_status') else 'unknown'
                    error = response.response_status.error if hasattr(response, 'response_status') and hasattr(response.response_status, 'error') else None
                    message_id = message_ids[0] if message_ids else None
                    
                    print(f"   Response Status: {status}")
                    if error and error != 'None':
                        print(f"   ⚠️  Error: {error}")
                    if message_id:
                        print(f"   Message ID: {message_id}")
                    
                    # Check message status
                    if hasattr(response, 'messages') and response.messages:
                        msg_status = response.messages[0].message_status if hasattr(response.messages[0], 'message_status') else 'unknown'
                        print(f"   Message Status: {msg_status}")
                        
                        # Check if message was actually accepted
                        if msg_status == 'accepted':
                            print(f"✅ Template message accepted by WhatsApp API for {phone}")
                            print(f"   ⏳ Delivery may take 1-5 minutes")
                            print(f"   📱 Please check your WhatsApp after a few minutes")
                            send_logger.info("Leaderboard message accepted by WhatsApp API", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "message_accepted",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "message_id": message_id,
                                "language": user_language,
                                "is_block_leaderboard": is_block_leaderboard,
                                "whatsapp_status": status
                            }})
                            # Print troubleshooting info
                            if message_id:
                                print_delivery_troubleshooting(phone, message_id, status)
                        elif msg_status == 'sent':
                            print(f"✅ Template message sent to {phone}")
                            send_logger.info("Leaderboard message sent", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "message_sent",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "message_id": message_id,
                                "language": user_language
                            }})
                        elif msg_status == 'delivered':
                            print(f"✅✅ Message delivered to {phone}!")
                            send_logger.info("Leaderboard message delivered", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "message_delivered",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "message_id": message_id,
                                "language": user_language
                            }})
                        elif msg_status == 'read':
                            print(f"✅✅✅ Message read by {phone}!")
                            send_logger.info("Leaderboard message read", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "message_read",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "message_id": message_id,
                                "language": user_language
                            }})
                        else:
                            print(f"⚠️  Message status: {msg_status} (may indicate delivery issue)")
                            send_logger.warning("Leaderboard message status issue", extra={AppInsightsLogHandler.DETAILS: {
                                "context": "message_status_warning",
                                "phone": phone,
                                "user_id": user.user_id if user else None,
                                "message_id": message_id,
                                "message_status": msg_status,
                                "whatsapp_status": status,
                                "error": error
                            }})
                            if message_id:
                                print_delivery_troubleshooting(phone, message_id, status)
                    
                    results.append({
                        "phone": phone,
                        "status": "success" if status == "200" else "warning",
                        "message_id": message_id,
                        "language": user_language,
                        "whatsapp_status": status,
                        "message_status": msg_status if 'msg_status' in locals() else None,
                        "error": error if error and error != 'None' else None
                    })
                else:
                    print(f"❌ No response received from WhatsApp API for {phone}")
                    send_logger.error("No response from WhatsApp API", extra={AppInsightsLogHandler.DETAILS: {
                        "context": "no_whatsapp_response",
                        "phone": phone,
                        "user_id": user.user_id if user else None,
                        "language": user_language
                    }})
                    results.append({
                        "phone": phone,
                        "status": "error",
                        "message": "No response from WhatsApp API"
                    })
            else:
                print(f"❌ Failed to prepare template request for {phone}")
                send_logger.error("Failed to prepare template request", extra={AppInsightsLogHandler.DETAILS: {
                    "context": "prepare_request_failed",
                    "phone": phone,
                    "user_id": user.user_id if user else None,
                    "language": user_language
                }})
                results.append({
                    "phone": phone,
                    "status": "error",
                    "message": "Failed to prepare request"
                })
        except Exception as e:
            print(f"❌ Error sending to {phone}: {str(e)}")
            send_logger.error("Error sending leaderboard message", extra={AppInsightsLogHandler.DETAILS: {
                "context": "send_error",
                "phone": phone,
                "user_id": user.user_id if user else None,
                "error": str(e),
                "language": user_language if 'user_language' in locals() else None
            }})
            results.append({
                "phone": phone,
                "status": "error",
                "message": str(e)
            })
    
    return results

async def main():
    run_logger.info("Starting leaderboard job", extra={AppInsightsLogHandler.DETAILS: {
        "context": "leaderboard_job_start",
        "test_mode": TEST_MODE_SEND_TO_ME_ONLY,
        "test_phone": TEST_PHONE_NUMBER if TEST_MODE_SEND_TO_ME_ONLY else None
    }})
    
    # Build global district leaderboard (used as fallback for users without location info)
    leaderboard_df = await build_district_leaderboard_last_week_ist()
    top3_df = leaderboard_df.head(3)
    print("\nTop 3 Districts (Global - used for users without location info):\n", top3_df.to_string(index=False))
    
    run_logger.info("Global district leaderboard built", extra={AppInsightsLogHandler.DETAILS: {
        "context": "build_global_leaderboard",
        "total_districts": len(leaderboard_df),
        "top3_districts": top3_df.to_dict('records') if len(top3_df) > 0 else []
    }})

    # Display what will be sent (sample for global leaderboard)
    # Note: In actual sending, each user gets their own language-specific translation
    template_params = await format_leaderboard_as_template_parameters(top3_df, user_language="en")
    print(f"\nSample Template Parameters (Global Districts, English): {template_params}")
    print(f"   Note: 10th parameter will be translated based on each user's language")
    print(f"Template Name: leaderboardv2")
    print(f"\n📌 PERSONALIZATION LOGIC:")
    print(f"   - Users WITH district & block info → Top 3 blocks in their district")
    print(f"   - Users WITHOUT location info → Top 3 districts (global)")
    print(f"📊 Using 10 parameters: 3 items × (name, count, users) + type indicator")
    
    # TEST MODE: Send only to your test phone number
    if TEST_MODE_SEND_TO_ME_ONLY:
        if not TEST_PHONE_NUMBER:
            print(f"\n❌ ERROR: TEST_MODE_SEND_TO_ME_ONLY is True but PHONE_NUMBER_ID is not set in keys.env")
            print(f"   Please add PHONE_NUMBER_ID=your_phone_number to your keys.env file")
            return
        
        print(f"\n🧪 TEST MODE: Sending template message only to {TEST_PHONE_NUMBER}")
        print(f"   ✅ SAFETY CHECK: TEST_MODE_SEND_TO_ME_ONLY = True")
        print(f"   ✅ Only 1 recipient will receive the message")
        test_phone_numbers = [TEST_PHONE_NUMBER]
        results = await send_leaderboard_template_messages(
            test_phone_numbers, 
            top3_df, 
            user_db_service, 
            message_db_service
        )
        success_count = sum(1 for r in results if r.get("status") == "success")
        failure_count = len(results) - success_count
        print(f"\n✅ Successfully sent {success_count} out of {len(results)} messages")
        print(f"\n⚠️  TEST MODE ACTIVE: Only sent to test phone number")
        print(f"   To enable production mode, set TEST_MODE_SEND_TO_ME_ONLY = False")
        
        run_logger.info("Leaderboard job completed (test mode)", extra={AppInsightsLogHandler.DETAILS: {
            "context": "leaderboard_job_complete",
            "mode": "test",
            "total_recipients": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "test_phone": TEST_PHONE_NUMBER
        }})
    else:
        # PRODUCTION MODE: Send to all users (actual sending)
        print(f"\n⚠️  WARNING: PRODUCTION MODE ACTIVE!")
        print(f"   TEST_MODE_SEND_TO_ME_ONLY = False")
        print(f"   Messages will be sent to ALL users")
        phone_numbers = await fetch_phone_numbers_for_asha_and_test_users()
        print(f"Total recipients found: {len(phone_numbers)}")
        print(f"\n🚀 PRODUCTION MODE: Sending template messages to {len(phone_numbers)} users")
        results = await send_leaderboard_template_messages(
            phone_numbers, 
            top3_df, 
            user_db_service, 
            message_db_service
        )
        success_count = sum(1 for r in results if r.get("status") == "success")
        failure_count = len(results) - success_count
        print(f"\n✅ Successfully sent {success_count} out of {len(results)} messages")
        
        run_logger.info("Leaderboard job completed (production mode)", extra={AppInsightsLogHandler.DETAILS: {
            "context": "leaderboard_job_complete",
            "mode": "production",
            "total_recipients": len(results),
            "success_count": success_count,
            "failure_count": failure_count
        }})

if __name__ == "__main__":
    asyncio.run(main())
