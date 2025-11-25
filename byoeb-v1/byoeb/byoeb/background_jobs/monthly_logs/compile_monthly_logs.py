"""
Monthly log compilation background job.

This job compiles ASHA and ANM logs for the previous month and writes them to Google Sheets.
It runs automatically on the 1st of each month at a specified time.
"""
import asyncio
import os
import sys
import yaml
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.chat_app.configuration.config import app_config

# Load environment variables from keys.env before importing database classes
# This ensures COSMOS_DB_CONNECTION_STRING and other env vars are available
current_file = Path(__file__).resolve()

def find_upwards(start_path: Path, target: str, is_dir: bool = False) -> Optional[Path]:
    """Search upwards from start_path for a file or directory named target."""
    for parent in [start_path] + list(start_path.parents):
        candidate = parent / target
        if (candidate.is_dir() if is_dir else candidate.is_file()):
            return candidate
    return None

# Preferred: APP_PATH environment variable
workspace_root_for_env = None
keys_env_path = None
app_path_env = os.getenv("APP_PATH", "").strip()
if app_path_env:
    potential_root = Path(app_path_env).resolve()
    candidate = potential_root / "keys.env"
    if candidate.exists():
        workspace_root_for_env = potential_root
        keys_env_path = candidate

# Fallback: search upwards from current file for keys.env
if keys_env_path is None:
    located_keys = find_upwards(current_file.parent, "keys.env")
    if located_keys:
        keys_env_path = located_keys.resolve()
        workspace_root_for_env = keys_env_path.parent

env_loaded = False
if keys_env_path and keys_env_path.exists():
    load_dotenv(keys_env_path, override=True)
    env_loaded = True
    print(f"✓ Loaded environment variables from {keys_env_path}")
else:
    print("⚠ Warning: keys.env not found. Database connection may fail.")

if env_loaded:
    if os.getenv("COSMOS_DB_CONNECTION_STRING"):
        print("✓ Verified COSMOS_DB_CONNECTION_STRING is loaded")
    else:
        print("⚠ Warning: COSMOS_DB_CONNECTION_STRING not found after loading keys.env")

# Add legacy src path for database classes and utils
# Use the same workspace root where we found keys.env
# keys.env was found at workspace_root_for_env/keys.env, so src should be at workspace_root_for_env/src
app_path = os.getenv("APP_PATH", "").strip()
if app_path:
    workspace_root = Path(app_path).resolve()
elif workspace_root_for_env is not None:
    workspace_root = workspace_root_for_env.resolve()
else:
    # Fallback: go up from current file
    workspace_root = current_file.parent

# Locate src directory by walking upwards if necessary
legacy_src_path = find_upwards(workspace_root, "src", is_dir=True)
if legacy_src_path is None:
    # Try from current file
    legacy_src_path = find_upwards(current_file.parent, "src", is_dir=True)
    if legacy_src_path:
        workspace_root = legacy_src_path.parent
else:
    workspace_root = legacy_src_path.parent

# Ensure we found src
if legacy_src_path:
    legacy_src_path = legacy_src_path.resolve()
    print(f"Workspace root (src parent): {workspace_root}")
    print(f"Using src path: {legacy_src_path}")
else:
    keys_env_location = keys_env_path if keys_env_path else "Unknown"
    raise FileNotFoundError(
        "Could not find src directory.\n"
        f"  Workspace root candidate: {workspace_root}\n"
        f"  File location: {current_file}\n"
        f"  keys.env was found at: {keys_env_location}"
    )

# Debug: print paths
print(f"Workspace root: {workspace_root}")
print(f"Looking for src at: {legacy_src_path}")
print(f"src exists: {legacy_src_path.exists()}")

if str(legacy_src_path) not in sys.path:
    sys.path.insert(0, str(legacy_src_path))
    print(f"✓ Added {legacy_src_path} to sys.path")

# Import legacy database classes
from database import UserDB, UserConvDB, BotConvDB, ExpertConvDB

IST = ZoneInfo("Asia/Kolkata")
# Initialize logger after potential env loading (to avoid issues)
if 'logger' not in locals():
    _logger = AppInsightsLogHandler.getLogger("monthly_logs")

# Try to import utils for Google Sheets (optional)
try:
    import utils
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    _logger.warning("Google Sheets utils not available. Will use Excel files instead.")

# Constants
ASHA_LOGS_RANGE_NAME = 'ASHA logs'
ANM_LOGS_RANGE_NAME = 'ANM logs'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_previous_month_range() -> Tuple[datetime, datetime]:
    """
    Calculate the start and end datetime for the previous month in IST timezone.
    
    Returns:
        tuple: (start_datetime, end_datetime) for the previous month
    """
    now_ist = datetime.now(IST)
    
    # Get first day of current month
    first_day_current = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Get first day of previous month
    if now_ist.month == 1:
        # January -> previous month is December of previous year
        start_date = first_day_current.replace(year=now_ist.year - 1, month=12)
    else:
        start_date = first_day_current.replace(month=now_ist.month - 1)
    
    # End date is the first day of current month (exclusive)
    end_date = first_day_current
    
    _logger.info(
        f"Calculated previous month range: {start_date} to {end_date}",
        extra={AppInsightsLogHandler.DETAILS: {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "Asia/Kolkata"
        }}
    )
    
    return start_date, end_date


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml file."""
    app_path = os.getenv("APP_PATH", "").strip()
    if app_path:
        config_path = Path(app_path) / "config.yaml"
    else:
        config_path = workspace_root / "config.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path}")
    
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    return config


def get_spreadsheet_id() -> str:
    """Get spreadsheet ID from environment variable or config."""
    spreadsheet_id = os.getenv('SPREADSHEET_ID', '').strip()
    if not spreadsheet_id:
        # Fallback to config.yaml
        config = load_config()
        spreadsheet_id = config.get('SPREADSHEET_ID', '').strip()
    
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID not found in environment variables or config.yaml")
    
    return spreadsheet_id


def get_local_path() -> str:
    """Get local app path from environment variable."""
    local_path = os.getenv("APP_PATH", "").strip()
    if not local_path:
        # Fallback to workspace root
        local_path = str(workspace_root)
    
    return local_path


async def compile_asha_logs(
    user_db: UserDB,
    user_conv_db: UserConvDB,
    bot_conv_db: BotConvDB,
    expert_conv_db: ExpertConvDB,
    start_date: datetime,
    end_date: datetime,
    users_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Compile ASHA logs for the specified date range.
    
    Args:
        user_db: User database instance
        user_conv_db: User conversation database instance
        bot_conv_db: Bot conversation database instance
        expert_conv_db: Expert conversation database instance
        start_date: Start datetime for the range
        end_date: End datetime for the range
        users_df: DataFrame of valid users (non-test users)
        
    Returns:
        DataFrame with compiled ASHA logs
    """
    _logger.info("Starting ASHA logs compilation", extra={AppInsightsLogHandler.DETAILS: {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }})
    
    # Convert datetime to pandas Timestamp for query
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    
    # Get all queries in the date range (run in thread pool since it's sync)
    all_queries = await asyncio.to_thread(
        user_conv_db.get_all_queries_in_duration,
        start_ts,
        end_ts
    )
    
    user_conv_df = pd.DataFrame(all_queries)
    
    if user_conv_df.empty:
        _logger.warning("No user conversations found in date range")
        return pd.DataFrame()
    
    # Filter out onboarding responses and test users
    user_conv_df = user_conv_df[user_conv_df['message_type'] != 'onboarding_response']
    user_conv_df.sort_values('message_timestamp', inplace=True, ascending=False)
    user_conv_df = user_conv_df[user_conv_df['user_id'].isin(users_df['user_id'])]
    
    # Rename columns for user conversations
    user_conv_rename = {
        'message_id': 'transaction_message_id',
        'message_source_lang': 'query_source_lang',
        'message_english': 'query_english',
        'source_language': 'query_language',
        'audio_blob_path': 'query_audio_blob_path',
        'message_timestamp': 'query_timestamp',
        'message_type': 'query_message_type'
    }
    user_conv_df.rename(columns=user_conv_rename, inplace=True)
    
    # Filter feedback responses (after renaming)
    feedback_responses = user_conv_df[user_conv_df['query_message_type'] == 'feedback_response']
    user_conv_df = user_conv_df[user_conv_df['query_message_type'] != 'feedback_response']
    
    # Filter onboard-asha (after renaming to query_source_lang)
    user_conv_df = user_conv_df[user_conv_df['query_source_lang'] != 'onboard-asha']
    
    # Get bot responses (query_response type)
    query_responses = await asyncio.to_thread(
        bot_conv_db.find_all,
        message_type='query_response'
    )
    query_responses_df = pd.DataFrame(list(query_responses))
    
    # Rename bot response columns
    bot_conv_rename = {
        'message_source_lang': 'response_source_lang',
        'message_language': 'response_language',
        'message_english': 'response_english',
        'message_timestamp': 'response_timestamp',
    }
    query_responses_df.rename(columns=bot_conv_rename, inplace=True)
    
    # Merge user queries with bot responses
    user_conv_df = user_conv_df.merge(
        query_responses_df,
        on='transaction_message_id',
        how='left'
    )
    
    # Handle empty audio responses
    empty_audio_responses = await asyncio.to_thread(
        bot_conv_db.find_all,
        message_type='empty_audio_response'
    )
    empty_audio_responses_df = pd.DataFrame(list(empty_audio_responses))
    
    if not empty_audio_responses_df.empty:
        user_conv_df['response_english'] = user_conv_df.apply(
            lambda x: 'empty_audio_response' 
            if x['transaction_message_id'] in empty_audio_responses_df['transaction_message_id'].values 
            else x['response_english'],
            axis=1
        )
    
    # Get expert consensus responses (first fetch for merging)
    expert_consensus_responses = await asyncio.to_thread(
        expert_conv_db.find_all,
        message_type='consensus_response'
    )
    expert_consensus_responses_df = pd.DataFrame(list(expert_consensus_responses))
    
    # Filter to only include valid users
    expert_consensus_responses_df = expert_consensus_responses_df[
        expert_consensus_responses_df['user_id'].isin(users_df['user_id'])
    ]
    
    # Create expert consensus response column as list of tuples
    if not expert_consensus_responses_df.empty:
        expert_consensus_responses_df_for_merge = expert_consensus_responses_df.copy()
        expert_consensus_responses_df_for_merge['expert_consensus_response'] = expert_consensus_responses_df_for_merge.apply(
            lambda x: (x['user_id'], x['message'], x['message_timestamp']),
            axis=1
        )
        expert_consensus_responses_df_for_merge = expert_consensus_responses_df_for_merge.groupby('transaction_message_id')['expert_consensus_response'].apply(list).reset_index()
        
        # Merge with user conversation dataframe
        user_conv_df = user_conv_df.merge(
            expert_consensus_responses_df_for_merge,
            on='transaction_message_id',
            how='left'
        )
        
        # Keep original expert_consensus_responses_df for cited messages extraction
        # (This matches the original code which fetches it again)
    
    # Get consensus responses from bot
    consensus_responses = await asyncio.to_thread(
        bot_conv_db.find_all,
        message_type='query_consensus_response'
    )
    consensus_responses_df = pd.DataFrame(list(consensus_responses))
    consensus_responses_df = consensus_responses_df[
        consensus_responses_df['receiver_id'].isin(users_df['user_id'])
    ]
    
    if not consensus_responses_df.empty:
        consensus_rename = {
            'message_source_lang': 'consensus_response_source_lang',
            'message_language': 'consensus_response_language',
            'message_english': 'consensus_response_english',
            'message_timestamp': 'consensus_response_timestamp',
            'citations': 'consensus_citations',
        }
        consensus_responses_df.rename(columns=consensus_rename, inplace=True)
        
        # Merge consensus responses
        user_conv_df = user_conv_df.merge(
            consensus_responses_df,
            on='transaction_message_id',
            how='left'
        )
        
        # Extract cited messages
        # Use the expert_consensus_responses_df from earlier (already filtered by users_df)
        # If it doesn't exist, create an empty dataframe
        if 'expert_consensus_responses_df' not in locals() or expert_consensus_responses_df.empty:
            expert_consensus_responses_df = pd.DataFrame()
        
        def extract_cited_messages(citations, expert_df=expert_consensus_responses_df):
            if pd.isna(citations) or citations == '':
                return None
            citations = str(citations).strip()
            citations = citations.replace('expert_consensus: ', '')
            citation_ids = citations.split(', ')
            
            if expert_df.empty:
                return None
            
            # Find cited messages in expert consensus responses
            cited_rows = expert_df[expert_df['message_id'].isin(citation_ids)]
            
            if cited_rows.empty:
                return None
            
            cited_messages = cited_rows.apply(
                lambda x: (x['user_id'], x['message'], x['message_timestamp']),
                axis=1
            ).tolist()
            return cited_messages
        
        user_conv_df['cited_messages'] = user_conv_df['consensus_citations'].apply(
            lambda x: extract_cited_messages(x, expert_consensus_responses_df)
        )
    
    # Select columns to save
    columns_to_save = [
        'user_id', 'query_source_lang', 'query_english', 'query_message_type',
        'query_type', 'query_timestamp', 'response_source_lang', 'response_english',
        'citations', 'expert_consensus_response', 'consensus_response_source_lang',
        'consensus_response_english', 'cited_messages', 'consensus_response_timestamp'
    ]
    
    # Filter to only existing columns
    columns_to_save = [col for col in columns_to_save if col in user_conv_df.columns]
    final_asha_df = user_conv_df[columns_to_save].copy()
    
    # Convert timestamp columns to IST string format
    for col in final_asha_df.columns:
        if 'timestamp' in col:
            final_asha_df[col] = pd.to_datetime(final_asha_df[col], errors='coerce')
            final_asha_df[col] = final_asha_df[col].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
            final_asha_df[col] = final_asha_df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Rename columns for final output
    final_rename = {
        'user_id': 'ASHA User ID',
        'query_message_type': 'Query Input Type',
        'query_source_lang': 'Query in Source Language (Hindi/Hinglish)',
        'query_english': 'Query in English (to GPT)',
        'query_type': 'Query Type',
        'query_timestamp': 'Query Timestamp',
        'response_source_lang': 'ASHABot Response in Source Language (Hindi/Hinglish)',
        'response_english': 'ASHABot Response in English',
        'response_timestamp': 'ASHABot Response Timestamp',
        'citations': 'Citations',
        'expert_consensus_response': 'ANM Responses',
        'consensus_response_source_lang': 'ASHABot Final Consensus Response in Source Language (Hindi/Hinglish)',
        'consensus_response_english': 'ASHABot Final Consensus Response in English',
        'cited_messages': 'ASHABot Final Consensus Citations',
        'consensus_response_timestamp': 'ASHABot Final Consensus Response Timestamp'
    }
    
    final_asha_df = final_asha_df.rename(columns=final_rename)
    
    # Convert all columns to string and fill NaN
    final_asha_df = final_asha_df.astype(str)
    final_asha_df = final_asha_df.fillna('')
    
    _logger.info(
        f"Compiled {len(final_asha_df)} ASHA log entries",
        extra={AppInsightsLogHandler.DETAILS: {"row_count": len(final_asha_df)}}
    )
    
    return final_asha_df


async def compile_anm_logs(
    expert_conv_db: ExpertConvDB,
    user_conv_df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime,
    users_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Compile ANM logs for the specified date range.
    
    Args:
        expert_conv_db: Expert conversation database instance
        user_conv_df: User conversation dataframe (for joining with queries)
        start_date: Start datetime for the range
        end_date: End datetime for the range
        users_df: DataFrame of valid users (non-test users)
        
    Returns:
        DataFrame with compiled ANM logs
    """
    _logger.info("Starting ANM logs compilation", extra={AppInsightsLogHandler.DETAILS: {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }})
    
    # Convert datetime to pandas Timestamp for query
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    
    # Get ANM responses in date range
    anm_responses = await asyncio.to_thread(
        expert_conv_db.find_all_with_duration,
        'consensus_response',
        start_ts,
        end_ts
    )
    anm_responses_df = pd.DataFrame(anm_responses)
    
    if anm_responses_df.empty:
        _logger.warning("No ANM responses found in date range")
        return pd.DataFrame()
    
    # Filter to only valid users
    anm_responses_df = anm_responses_df[anm_responses_df['user_id'].isin(users_df['user_id'])]
    anm_responses_df = anm_responses_df[~anm_responses_df['user_id'].isna()]
    
    # Select and rename columns
    anm_responses_df = anm_responses_df[[
        'user_id', 'message', 'message_type', 'message_timestamp', 'transaction_message_id'
    ]]
    anm_responses_df = anm_responses_df.rename(columns={
        'user_id': 'anm_user_id',
        'message': 'anm_message',
        'message_type': 'anm_message_type',
        'message_timestamp': 'anm_message_timestamp',
    })
    
    # Sort by timestamp descending
    anm_responses_df.sort_values('anm_message_timestamp', inplace=True, ascending=False)
    
    # Get ASHA query information for joining
    asha_query_df = user_conv_df[[
        'user_id', 'transaction_message_id', 'query_source_lang', 'query_english',
        'query_type', 'query_message_type', 'query_timestamp'
    ]]
    
    # Merge ANM responses with ASHA queries
    final_anm_df = anm_responses_df.merge(
        asha_query_df,
        on='transaction_message_id',
        how='left'
    )
    
    # Drop rows where query_source_lang is NaN
    final_anm_df = final_anm_df[~final_anm_df['query_source_lang'].isna()]
    
    # Rename columns for final output
    final_anm_df = final_anm_df.rename(columns={
        'user_id': 'ANM User ID',
        'query_source_lang': 'ASHA Query Source Language',
        'query_english': 'ASHA Query English',
        'query_type': 'ASHA Query Type',
        'query_message_type': 'ASHA Query Input Type',
        'query_timestamp': 'ASHA Query Timestamp',
        'anm_message': 'ANM Response',
        'anm_message_timestamp': 'ANM Response Timestamp'
    })
    
    # Select final columns
    final_anm_df = final_anm_df[[
        'ANM User ID', 'ASHA Query Source Language', 'ANM Response',
        'ANM Response Timestamp', 'ASHA Query English', 'ASHA Query Type',
        'ASHA Query Input Type', 'ASHA Query Timestamp'
    ]]
    
    # Convert timestamp columns to IST string format
    for col in final_anm_df.columns:
        if 'timestamp' in col.lower():
            final_anm_df[col] = pd.to_datetime(final_anm_df[col], errors='coerce')
            final_anm_df[col] = final_anm_df[col].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
            final_anm_df[col] = final_anm_df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Convert all columns to string and fill NaN
    final_anm_df = final_anm_df.astype(str)
    final_anm_df = final_anm_df.fillna('')
    
    _logger.info(
        f"Compiled {len(final_anm_df)} ANM log entries",
        extra={AppInsightsLogHandler.DETAILS: {"row_count": len(final_anm_df)}}
    )
    
    return final_anm_df


async def write_to_excel(
    asha_df: pd.DataFrame,
    anm_df: pd.DataFrame,
    output_path: Optional[str] = None
) -> str:
    """
    Write compiled logs to Excel file.
    
    Args:
        asha_df: DataFrame with ASHA logs
        anm_df: DataFrame with ANM logs
        output_path: Optional path for output file. If not provided, uses default location.
        
    Returns:
        Path to the created Excel file
    """
    if output_path is None:
        # Generate filename with current date
        now = datetime.now(IST)
        filename = f"monthly_logs_{now.strftime('%Y_%m')}.xlsx"
        local_path = get_local_path()
        output_path = str(Path(local_path) / filename)
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    _logger.info("Writing logs to Excel file", extra={AppInsightsLogHandler.DETAILS: {
        "asha_rows": len(asha_df),
        "anm_rows": len(anm_df),
        "output_path": str(output_path)
    }})
    
    # Write to Excel with multiple sheets
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        if not asha_df.empty:
            asha_df.to_excel(writer, sheet_name=ASHA_LOGS_RANGE_NAME, index=False)
        else:
            # Create empty sheet with headers if no data
            pd.DataFrame(columns=asha_df.columns if not asha_df.empty else []).to_excel(
                writer, sheet_name=ASHA_LOGS_RANGE_NAME, index=False
            )
        
        if not anm_df.empty:
            anm_df.to_excel(writer, sheet_name=ANM_LOGS_RANGE_NAME, index=False)
        else:
            # Create empty sheet with headers if no data
            pd.DataFrame(columns=anm_df.columns if not anm_df.empty else []).to_excel(
                writer, sheet_name=ANM_LOGS_RANGE_NAME, index=False
            )
    
    _logger.info(f"Successfully wrote logs to Excel file: {output_path}")
    return str(output_path)


async def write_to_google_sheets(
    asha_df: pd.DataFrame,
    anm_df: pd.DataFrame,
    spreadsheet_id: str,
    local_path: str
) -> None:
    """
    Write compiled logs to Google Sheets (optional, requires Google Sheets API).
    
    Args:
        asha_df: DataFrame with ASHA logs
        anm_df: DataFrame with ANM logs
        spreadsheet_id: Google Sheets spreadsheet ID
        local_path: Local path for credentials
    """
    if not GOOGLE_SHEETS_AVAILABLE:
        raise ImportError("Google Sheets utils not available. Use write_to_excel instead.")
    
    _logger.info("Writing logs to Google Sheets", extra={AppInsightsLogHandler.DETAILS: {
        "asha_rows": len(asha_df),
        "anm_rows": len(anm_df),
        "spreadsheet_id": spreadsheet_id
    }})
    
    # Delete existing rows (run in thread pool since utils functions are sync)
    if not asha_df.empty:
        await asyncio.to_thread(
            utils.delete_rows,
            SCOPES, spreadsheet_id, ASHA_LOGS_RANGE_NAME, local_path, 1, len(asha_df) + 1
        )
    
    if not anm_df.empty:
        await asyncio.to_thread(
            utils.delete_rows,
            SCOPES, spreadsheet_id, ANM_LOGS_RANGE_NAME, local_path, 1, len(anm_df) + 1
        )
    
    # Add headers
    if not asha_df.empty:
        await asyncio.to_thread(
            utils.add_headers,
            SCOPES, spreadsheet_id, ASHA_LOGS_RANGE_NAME, asha_df.columns.tolist(), local_path
        )
    
    if not anm_df.empty:
        await asyncio.to_thread(
            utils.add_headers,
            SCOPES, spreadsheet_id, ANM_LOGS_RANGE_NAME, anm_df.columns.tolist(), local_path
        )
    
    # Append rows
    if not asha_df.empty:
        await asyncio.to_thread(
            utils.append_rows,
            SCOPES, spreadsheet_id, ASHA_LOGS_RANGE_NAME, asha_df, local_path
        )
    
    if not anm_df.empty:
        await asyncio.to_thread(
            utils.append_rows,
            SCOPES, spreadsheet_id, ANM_LOGS_RANGE_NAME, anm_df, local_path
        )
    
    _logger.info("Successfully wrote logs to Google Sheets")


async def main() -> None:
    """
    Main function to compile monthly logs.
    This function is called by the scheduler.
    """
    try:
        _logger.info("Starting monthly log compilation job")
        
        # Get date range for previous month
        start_date, end_date = get_previous_month_range()
        
        # Load configuration
        config = load_config()
        
        # Initialize database connections (run in thread pool since they're sync)
        user_db = await asyncio.to_thread(UserDB, config)
        user_conv_db = await asyncio.to_thread(UserConvDB, config)
        bot_conv_db = await asyncio.to_thread(BotConvDB, config)
        expert_conv_db = await asyncio.to_thread(ExpertConvDB, config)
        
        # Get all users and filter out test users
        users = await asyncio.to_thread(user_db.get_all_users)
        users_df = pd.DataFrame(users)
        users_df = users_df[users_df['test_user'] != True]
        
        _logger.info(
            f"Found {len(users_df)} non-test users",
            extra={AppInsightsLogHandler.DETAILS: {"user_count": len(users_df)}}
        )
        
        # Compile ASHA logs
        asha_df = await compile_asha_logs(
            user_db, user_conv_db, bot_conv_db, expert_conv_db,
            start_date, end_date, users_df
        )
        
        # Get user conversation dataframe for ANM logs (needed for joining)
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        all_queries = await asyncio.to_thread(
            user_conv_db.get_all_queries_in_duration,
            start_ts,
            end_ts
        )
        user_conv_df = pd.DataFrame(all_queries)
        user_conv_df = user_conv_df[user_conv_df['message_type'] != 'onboarding_response']
        user_conv_df = user_conv_df[user_conv_df['user_id'].isin(users_df['user_id'])]
        user_conv_df = user_conv_df[user_conv_df['query_source_lang'] != 'onboard-asha']
        user_conv_df.rename(columns={
            'message_id': 'transaction_message_id',
            'message_source_lang': 'query_source_lang',
            'message_english': 'query_english',
            'source_language': 'query_language',
            'message_timestamp': 'query_timestamp',
            'message_type': 'query_message_type'
        }, inplace=True)
        
        # Compile ANM logs
        anm_df = await compile_anm_logs(
            expert_conv_db, user_conv_df, start_date, end_date, users_df
        )
        
        # Write to output (Excel by default, Google Sheets if configured)
        output_method = os.getenv("MONTHLY_LOGS_OUTPUT", "excel").lower()
        output_location = None
        
        if output_method == "google_sheets" and GOOGLE_SHEETS_AVAILABLE:
            spreadsheet_id = get_spreadsheet_id()
            local_path = get_local_path()
            await write_to_google_sheets(asha_df, anm_df, spreadsheet_id, local_path)
            output_location = f"Google Sheets (ID: {spreadsheet_id})"
        else:
            # Default to Excel
            if output_method == "google_sheets" and not GOOGLE_SHEETS_AVAILABLE:
                _logger.warning("Google Sheets requested but not available. Using Excel instead.")
            
            output_path = await write_to_excel(asha_df, anm_df)
            output_location = output_path
        
        _logger.info(
            "Monthly log compilation completed successfully",
            extra={AppInsightsLogHandler.DETAILS: {
                "asha_rows": len(asha_df),
                "anm_rows": len(anm_df),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "output_location": output_location
            }}
        )
        
    except Exception as e:
        _logger.exception(
            f"Error in monthly log compilation: {str(e)}",
            extra={AppInsightsLogHandler.DETAILS: {"error": str(e)}}
        )
        raise


# Wrapper function for scheduler
async def run():
    """Wrapper function for scheduler to call without arguments."""
    await main()


if __name__ == "__main__":
    asyncio.run(main())

