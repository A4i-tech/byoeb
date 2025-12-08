"""Compile monthly user-bot interaction logs for analysis.
Fetches data using the same logic as ASHA Logs page and generates Excel output.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from zoneinfo import ZoneInfo
import pandas as pd
from dotenv import load_dotenv
import os
import json
import tiktoken
from openai import OpenAI

# Add parent directory to path to import byoeb modules
script_dir = Path(__file__).parent
byoeb_package_dir = script_dir.parent
byoeb_parent_dir = byoeb_package_dir.parent
sys.path.insert(0, str(byoeb_parent_dir))

repo_root = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) >= 4 else byoeb_parent_dir
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from src.utils import get_llm_response  # type: ignore
except Exception:
    get_llm_response = None

from byoeb.background_jobs.daily_logs.asha_logs import fetch_daily_logs

# Constants
IST = ZoneInfo("Asia/Kolkata")
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_DATE_FORMAT = "%d-%m-%Y"
SEPARATOR_LENGTH = 60


def locate_keys() -> Path: 
    candidates = [
        Path("keys.env"),
        Path("../../keys.env"),
        Path("byoeb-v1/byoeb/keys.env"),
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError("keys.env not found. Set APP_PATH or run from repo root.")


def get_month_range(year: int, month: int) -> Tuple[datetime, datetime]:
    """Get start and end datetime for a given month in IST timezone."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=IST)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=IST)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=IST)
    return start, end


def month_range(args) -> Tuple[datetime, datetime]:
    """Parse month range from arguments or use defaults."""
    if args.month and args.year:
        return get_month_range(args.year, args.month)
    elif args.start and args.end:
        try:
            start = datetime.strptime(args.start, DATE_FORMAT).replace(tzinfo=IST)
            end = datetime.strptime(args.end, DATE_FORMAT).replace(tzinfo=IST)
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use {DATE_FORMAT}. Error: {e}")
        
        if start >= end:
            raise ValueError("Start date must be before end date.")
        
        return start, end
    elif args.start or args.end:
        raise ValueError("Provide both --start and --end, or neither.")
    else:
        now = datetime.now(IST)
        end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if end.month == 1:
            start = end.replace(year=end.year - 1, month=12)
        else:
            start = end.replace(month=end.month - 1)
    return start, end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile monthly ASHA bot interaction logs for analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze last month (default)
  python compile_monthly_logs.py
  
  # Analyze specific month
  python compile_monthly_logs.py --year 2024 --month 11
  
  # Analyze custom date range
  python compile_monthly_logs.py --start 2024-11-01 --end 2024-12-01
        """
    )
    parser.add_argument(
        "--year", 
        type=int, 
        help="Year for monthly analysis (e.g., 2024). Use with --month."
    )
    parser.add_argument(
        "--month", 
        type=int, 
        choices=range(1, 13), 
        metavar="[1-12]",
        help="Month for analysis (1-12). Use with --year."
    )
    parser.add_argument(
        "--start", 
        type=str, 
        help="Start date (inclusive) YYYY-MM-DD. Use with --end."
    )
    parser.add_argument(
        "--end", 
        type=str, 
        help="End date (exclusive) YYYY-MM-DD. Use with --start."
    )
    parser.add_argument(
        "--output", 
        type=str, 
        help="Output Excel file path (default: monthly_logs_YYYY-MM.xlsx)"
    )
    parser.add_argument(
        "--llm-report",
        action="store_true",
        help="Generate LLM-based executive summary with token/cost estimates."
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="gpt-4o-mini",
        help="Model for LLM summary (default: gpt-4o-mini)."
    )
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=300,
        help="Max completion tokens for LLM summary (default: 300)."
    )
    parser.add_argument(
        "--llm-temperature",
        type=float,
        default=0.2,
        help="Temperature for LLM summary (default: 0.2)."
    )
    return parser.parse_args()


async def fetch_monthly_logs(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch logs for the specified date range using the same logic as ASHA Logs page."""
    start_ts = str(start.timestamp())
    end_ts = str(end.timestamp())
    
    print(f"Fetching logs from {start.strftime(DATETIME_FORMAT)} to {end.strftime(DATETIME_FORMAT)} (IST)...")
    
    try:
        df = await fetch_daily_logs(start_timestamp=start_ts, end_timestamp=end_ts)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        raise
    
    if df.empty:
        print("No messages found in the selected range.")
        return df
    
    print(f"Fetched {len(df)} log entries.")
    return df


def filter_test_users(df: pd.DataFrame) -> pd.DataFrame:
    """Filter out test users from the dataframe."""
    if df.empty:
        return df
    
    if 'test_user' not in df.columns:
        print("Warning: 'test_user' column not found. Skipping test user filter.")
        return df
    
    initial_count = len(df)
    df_filtered = df[df['test_user'] != True].copy()
    filtered_count = len(df_filtered)
    removed_count = initial_count - filtered_count
    
    if removed_count > 0:
        print(f"Filtered out {removed_count} test user entries. Remaining: {filtered_count}")
    else:
        print(f"No test users found. Total entries: {filtered_count}")
    
    return df_filtered


def filter_by_log_date(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    """Filter dataframe to only include logs from the specified month based on log_date."""
    if df.empty:
        return df
    
    if 'log_date' not in df.columns:
        print("Warning: 'log_date' column not found. Skipping log_date filter.")
        return df
    
    def parse_log_date(date_str) -> Optional[datetime]:
        """Parse log_date string to datetime object."""
        if pd.isna(date_str) or date_str is None:
            return None
        try:
            return datetime.strptime(str(date_str), LOG_DATE_FORMAT).replace(tzinfo=IST)
        except (ValueError, TypeError):
            return None
    
    df['log_date_parsed'] = df['log_date'].apply(parse_log_date)
    mask = (df['log_date_parsed'] >= start) & (df['log_date_parsed'] < end)
    df_filtered = df[mask].copy()
    df_filtered = df_filtered.drop(columns=['log_date_parsed'])
    
    initial_count = len(df)
    filtered_count = len(df_filtered)
    removed_count = initial_count - filtered_count
    
    if removed_count > 0:
        print(f"Filtered by log_date: removed {removed_count} entries outside month range. Remaining: {filtered_count}")
    
    return df_filtered


def categorize_idk_cause(row: pd.Series) -> str:
    """Categorize the cause of an IDK response.
    
    Categories:
    - Missing details: Incomplete input (short queries, missing context)
    - Query misinterpretation: Bot categorized wrongly
    - Domain knowledge gaps: Valid ASHA queries not answered
    """
    query_text = str(row.get('query_en', '') or '').lower().strip()
    query_source = str(row.get('query_source', '') or '').lower().strip()
    query_type = str(row.get('query_type', '') or '').lower()
    rewritten_query = str(row.get('rewritten_query', '') or '').lower().strip()
    
    # Use the most complete query text available
    primary_query = query_text if query_text and len(query_text) > len(query_source) else query_source
    if not primary_query or primary_query == 'nan':
        primary_query = rewritten_query
    
    # Missing details: very short queries (< 5 chars or < 2 words) or single words
    if len(primary_query) < 5:
        return "Missing details"
    
    word_count = len(primary_query.split())
    if word_count < 2:
        return "Missing details"
    
    # Missing details: queries that are just names or single unclear words
    if word_count == 1 and primary_query not in ['what', 'how', 'when', 'where', 'why', 'who']:
        # Check if it's a common name or unclear term
        unclear_terms = ['chotte', 'vashmita', 'pakil', 'satul', 'kan', 'kai', 'tan', 'niji']
        if primary_query in unclear_terms:
            return "Missing details"
    
    # Query misinterpretation: query_type doesn't match query content or rewritten query differs significantly
    if query_type and rewritten_query and primary_query:
        if query_type not in primary_query and query_type not in rewritten_query:
            if len(rewritten_query) > len(primary_query) * 1.5:  # Significant rewriting suggests misinterpretation
                return "Query misinterpretation"
    
    # Default to domain knowledge gaps (valid ASHA queries not answered)
    return "Domain knowledge gaps"


def categorize_asha_theme(row: pd.Series) -> str:
    """Categorize ASHA-related IDK queries into themes.
    
    Themes: maternal care, child health, payments, workload, supplies, training, 
    technical/administrative, general health, other
    """
    # Get all query text fields and combine
    query_text = str(row.get('query_en', '') or '').lower()
    query_source = str(row.get('query_source', '') or '').lower()
    rewritten_query = str(row.get('rewritten_query', '') or '').lower()
    combined_text = f"{query_text} {query_source} {rewritten_query}"
    
    # Check for very short or unclear queries first (likely missing details)
    if len(query_text.strip()) < 5 or len(query_source.strip()) < 5:
        if not any(word in combined_text for word in ['weight', 'height', 'age', 'blood', 'pressure', 'sugar']):
            return "Other"
    
    # Maternal care keywords (expanded)
    maternal_keywords = ['pregnancy', 'pregnant', 'delivery', 'childbirth', 'antenatal', 
                        'postnatal', 'post-natal', 'maternal', 'breastfeeding', 'breast feeding',
                        'lactation', 'prenatal', 'pre-natal', 'maternity', 'obstetric',
                        'gynecolog', 'gynaecolog', 'menstrual', 'period', 'contraception']
    if any(keyword in combined_text for keyword in maternal_keywords):
        return "Maternal care"
    
    # Child health keywords (new category - weight, height, growth, development)
    child_health_keywords = ['child weight', 'child height', 'child age', 'child growth',
                            'weight of child', 'height of child', 'age of child',
                            'normal weight', 'normal height', 'child development',
                            'vaccination', 'immunization', 'vaccine', 'immunize',
                            'newborn', 'infant', 'toddler', 'baby weight', 'baby height',
                            'teenager weight', 'teenager height', 'adolescent']
    if any(keyword in combined_text for keyword in child_health_keywords):
        return "Child health"
    
    # General health keywords (new category - blood pressure, sugar, vitals, etc.)
    general_health_keywords = ['blood pressure', 'bp', 'sugar level', 'blood sugar', 'glucose',
                              'breathing rate', 'respiratory rate', 'pulse', 'heart rate',
                              'blood volume', 'normal range', 'vital sign', 'vitals',
                              'vitamin', 'deficiency', 'health check', 'medical check']
    if any(keyword in combined_text for keyword in general_health_keywords):
        return "General health"
    
    # Technical/Administrative keywords (new category - IDs, registration, app issues)
    technical_keywords = ['abha', 'aura id', 'aadhaar', 'registration', 'register',
                         'nct card', 'nct', 'onboard', 'onboarding', 'app', 'application',
                         'eshuchi', 'stopped working', 'not working', 'technical',
                         'account', 'id creation', 'create id', 'family head', 'survey']
    if any(keyword in combined_text for keyword in technical_keywords):
        return "Technical/Administrative"
    
    # Payments keywords (expanded)
    payment_keywords = ['payment', 'salary', 'wage', 'money', 'incentive', 'remuneration', 
                       'compensation', 'allowance', 'fund', 'financial', 'rupee', 'rs.',
                       'rs ', 'rupees', 'income', 'earn', 'paid']
    if any(keyword in combined_text for keyword in payment_keywords):
        return "Payments"
    
    # Workload keywords (expanded)
    workload_keywords = ['workload', 'work load', 'too much', 'overwork', 'busy', 
                        'schedule', 'hours', 'duty', 'responsibility', 'task',
                        'too many', 'excessive', 'overload', 'stress', 'pressure at work']
    if any(keyword in combined_text for keyword in workload_keywords):
        return "Workload"
    
    # Supplies keywords (expanded)
    supply_keywords = ['supply', 'supplies', 'equipment', 'material', 'stock', 'inventory',
                       'medicine', 'drug', 'tablet', 'kit', 'tool', 'resource',
                       'cuff', 'blood pressure cuff', 'medical equipment', 'device']
    if any(keyword in combined_text for keyword in supply_keywords):
        return "Supplies"
    
    # Training keywords (expanded)
    training_keywords = ['training', 'learn', 'course', 'workshop', 'education', 'skill',
                        'knowledge', 'guidance', 'instruction', 'teach', 'how to',
                        'learn how', 'training program', 'capacity building']
    if any(keyword in combined_text for keyword in training_keywords):
        return "Training"
    
    return "Other"


def analyze_response_times(df: pd.DataFrame) -> dict:
    """Analyze response times: calculate statistics and identify patterns."""
    if df.empty:
        return {
            'total_queries': 0,
            'valid_responses': 0,
            'statistics': {},
            'patterns': {},
            'response_time_data': pd.DataFrame()
        }
    
    # Create a copy for analysis
    analysis_df = df.copy()
    
    # Calculate response time in seconds
    # Filter out rows with missing timestamps
    valid_mask = (
        analysis_df['incoming_timestamp'].notna() & 
        analysis_df['outgoing_timestamp'].notna() &
        (analysis_df['incoming_timestamp'] > 0) &
        (analysis_df['outgoing_timestamp'] > 0)
    )
    
    valid_df = analysis_df[valid_mask].copy()
    
    if valid_df.empty:
        return {
            'total_queries': len(df),
            'valid_responses': 0,
            'statistics': {},
            'patterns': {},
            'response_time_data': pd.DataFrame()
        }
    
    # Calculate response time (outgoing - incoming) in seconds
    valid_df['response_time_seconds'] = valid_df['outgoing_timestamp'] - valid_df['incoming_timestamp']
    
    # Filter out negative or unrealistic response times (more than 1 hour = 3600 seconds)
    # Negative times indicate data issues, very long times might be outliers
    valid_df = valid_df[
        (valid_df['response_time_seconds'] >= 0) & 
        (valid_df['response_time_seconds'] <= 3600)
    ].copy()
    
    if valid_df.empty:
        return {
            'total_queries': len(df),
            'valid_responses': 0,
            'statistics': {},
            'patterns': {},
            'response_time_data': pd.DataFrame()
        }
    
    # Calculate statistics
    response_times = valid_df['response_time_seconds']
    mean_rt = response_times.mean()
    median_rt = response_times.median()
    p95_rt = response_times.quantile(0.95)
    p90_rt = response_times.quantile(0.90)
    p75_rt = response_times.quantile(0.75)
    min_rt = response_times.min()
    max_rt = response_times.max()
    
    statistics = {
        'mean': round(mean_rt, 2),
        'median': round(median_rt, 2),
        'p95': round(p95_rt, 2),
        'p90': round(p90_rt, 2),
        'p75': round(p75_rt, 2),
        'min': round(min_rt, 2),
        'max': round(max_rt, 2),
        'count': len(valid_df)
    }
    
    # Analyze patterns by different dimensions
    patterns = {}
    
    # Helper function for p95 calculation
    def calc_p95(series):
        return series.quantile(0.95)
    
    # Pattern by query_type
    if 'query_type' in valid_df.columns:
        query_type_stats = valid_df.groupby('query_type')['response_time_seconds'].agg([
            'count', 'mean', 'median', calc_p95
        ]).round(2)
        query_type_stats.columns = ['count', 'mean', 'median', 'p95']
        query_type_stats = query_type_stats.sort_values('mean', ascending=False)
        patterns['by_query_type'] = query_type_stats.to_dict('index')
    
    # Pattern by message_category
    if 'message_category' in valid_df.columns:
        category_stats = valid_df.groupby('message_category')['response_time_seconds'].agg([
            'count', 'mean', 'median', calc_p95
        ]).round(2)
        category_stats.columns = ['count', 'mean', 'median', 'p95']
        category_stats = category_stats.sort_values('mean', ascending=False)
        patterns['by_message_category'] = category_stats.to_dict('index')
    
    # Pattern by user_language
    if 'user_language' in valid_df.columns:
        language_stats = valid_df.groupby('user_language')['response_time_seconds'].agg([
            'count', 'mean', 'median', calc_p95
        ]).round(2)
        language_stats.columns = ['count', 'mean', 'median', 'p95']
        language_stats = language_stats.sort_values('mean', ascending=False)
        patterns['by_language'] = language_stats.to_dict('index')
    
    # Pattern by district (only if meaningful - at least 10 queries per district)
    if 'district' in valid_df.columns:
        district_counts = valid_df['district'].value_counts()
        significant_districts = district_counts[district_counts >= 10].index
        if len(significant_districts) > 0:
            district_df = valid_df[valid_df['district'].isin(significant_districts)]
            district_stats = district_df.groupby('district')['response_time_seconds'].agg([
                'count', 'mean', 'median', calc_p95
            ]).round(2)
            district_stats.columns = ['count', 'mean', 'median', 'p95']
            district_stats = district_stats.sort_values('mean', ascending=False)
            patterns['by_district'] = district_stats.to_dict('index')
    
    # Pattern by message_type
    if 'message_type' in valid_df.columns:
        message_type_stats = valid_df.groupby('message_type')['response_time_seconds'].agg([
            'count', 'mean', 'median', calc_p95
        ]).round(2)
        message_type_stats.columns = ['count', 'mean', 'median', 'p95']
        message_type_stats = message_type_stats.sort_values('mean', ascending=False)
        patterns['by_message_type'] = message_type_stats.to_dict('index')
    
    # Create response time distribution data for export
    response_time_data = valid_df[[
        'user_id', 'phone_number_id', 'log_date', 'message_category', 
        'query_type', 'user_language', 'district', 'message_type',
        'incoming_timestamp', 'outgoing_timestamp', 'response_time_seconds'
    ]].copy()
    
    return {
        'total_queries': len(df),
        'valid_responses': len(valid_df),
        'statistics': statistics,
        'patterns': patterns,
        'response_time_data': response_time_data
    }


def analyze_idk(df: pd.DataFrame) -> dict:
    """Analyze IDK queries: count percentage, categorize causes, and bucket ASHA themes."""
    if df.empty:
        return {
            'total_queries': 0,
            'idk_count': 0,
            'idk_percentage': 0.0,
            'causes': {},
            'asha_themes': {},
            'breakdowns': {},
            'idk_queries': pd.DataFrame()
        }
    
    total_queries = len(df)
    
    # Identify IDK queries (audio_idk or text_idk)
    idk_mask = df['message_category'].isin(['audio_idk', 'text_idk'])
    idk_df = df[idk_mask].copy()
    idk_count = len(idk_df)
    
    if idk_count == 0:
        return {
            'total_queries': total_queries,
            'idk_count': 0,
            'idk_percentage': 0.0,
            'causes': {},
            'asha_themes': {},
            'breakdowns': {},
            'idk_queries': pd.DataFrame()
        }
    
    idk_percentage = (idk_count / total_queries) * 100
    
    # Categorize causes
    idk_df['idk_cause'] = idk_df.apply(categorize_idk_cause, axis=1)
    causes = idk_df['idk_cause'].value_counts().to_dict()
    causes_percentage = {cause: (count / idk_count) * 100 for cause, count in causes.items()}
    
    # Categorize ASHA themes (only for domain knowledge gaps)
    domain_gaps_df = idk_df[idk_df['idk_cause'] == 'Domain knowledge gaps'].copy()
    if not domain_gaps_df.empty:
        domain_gaps_df['asha_theme'] = domain_gaps_df.apply(categorize_asha_theme, axis=1)
        asha_themes = domain_gaps_df['asha_theme'].value_counts().to_dict()
        asha_themes_percentage = {theme: (count / len(domain_gaps_df)) * 100 for theme, count in asha_themes.items()}
    else:
        asha_themes = {}
        asha_themes_percentage = {}
    
    # Add theme column to all IDK queries
    idk_df['asha_theme'] = idk_df.apply(categorize_asha_theme, axis=1)
    
    # Create IDK queries dump with relevant columns
    idk_queries_dump = idk_df[[
        'user_id', 'phone_number_id', 'log_date', 'message_category',
        'query_source', 'query_en', 'rewritten_query', 'idk_cause', 'asha_theme'
    ]].copy()
    
    # Breakdowns by language and geography (only if meaningful differences)
    breakdowns = {}
    
    # Breakdown by language
    if 'user_language' in df.columns:
        lang_breakdown = []
        for lang in df['user_language'].dropna().unique():
            lang_df = df[df['user_language'] == lang]
            lang_total = len(lang_df)
            lang_idk = len(lang_df[lang_df['message_category'].isin(['audio_idk', 'text_idk'])])
            if lang_total > 0:
                lang_idk_pct = (lang_idk / lang_total) * 100
                lang_breakdown.append({
                    'language': lang,
                    'total_queries': lang_total,
                    'idk_count': lang_idk,
                    'idk_percentage': round(lang_idk_pct, 2)
                })
        
        if lang_breakdown:
            # Check for meaningful differences (>10% variation)
            idk_percentages = [b['idk_percentage'] for b in lang_breakdown]
            if len(idk_percentages) > 1:
                max_pct = max(idk_percentages)
                min_pct = min(idk_percentages)
                if max_pct > 0 and (max_pct - min_pct) / max_pct > 0.1:  # >10% relative difference
                    breakdowns['by_language'] = sorted(lang_breakdown, key=lambda x: x['idk_percentage'], reverse=True)
    
    # Breakdown by district
    if 'district' in df.columns:
        district_breakdown = []
        district_counts = df['district'].dropna().value_counts()
        # Only include districts with at least 50 queries for statistical significance
        significant_districts = district_counts[district_counts >= 50].index
        
        for district in significant_districts:
            district_df = df[df['district'] == district]
            district_total = len(district_df)
            district_idk = len(district_df[district_df['message_category'].isin(['audio_idk', 'text_idk'])])
            if district_total > 0:
                district_idk_pct = (district_idk / district_total) * 100
                district_breakdown.append({
                    'district': district,
                    'total_queries': district_total,
                    'idk_count': district_idk,
                    'idk_percentage': round(district_idk_pct, 2)
                })
        
        if district_breakdown:
            # Check for meaningful differences (>10% variation)
            idk_percentages = [b['idk_percentage'] for b in district_breakdown]
            if len(idk_percentages) > 1:
                max_pct = max(idk_percentages)
                min_pct = min(idk_percentages)
                if max_pct > 0 and (max_pct - min_pct) / max_pct > 0.1:  # >10% relative difference
                    breakdowns['by_district'] = sorted(district_breakdown, key=lambda x: x['idk_percentage'], reverse=True)
    
    # Breakdown by block
    if 'block' in df.columns:
        block_breakdown = []
        block_counts = df['block'].dropna().value_counts()
        # Only include blocks with at least 30 queries for statistical significance
        significant_blocks = block_counts[block_counts >= 30].index
        
        for block in significant_blocks:
            block_df = df[df['block'] == block]
            block_total = len(block_df)
            block_idk = len(block_df[block_df['message_category'].isin(['audio_idk', 'text_idk'])])
            if block_total > 0:
                block_idk_pct = (block_idk / block_total) * 100
                block_breakdown.append({
                    'block': block,
                    'total_queries': block_total,
                    'idk_count': block_idk,
                    'idk_percentage': round(block_idk_pct, 2)
                })
        
        if block_breakdown:
            # Check for meaningful differences (>10% variation)
            idk_percentages = [b['idk_percentage'] for b in block_breakdown]
            if len(idk_percentages) > 1:
                max_pct = max(idk_percentages)
                min_pct = min(idk_percentages)
                if max_pct > 0 and (max_pct - min_pct) / max_pct > 0.1:  # >10% relative difference
                    breakdowns['by_block'] = sorted(block_breakdown, key=lambda x: x['idk_percentage'], reverse=True)
    
    # Breakdown by sector
    if 'sector' in df.columns:
        sector_breakdown = []
        sector_counts = df['sector'].dropna().value_counts()
        # Only include sectors with at least 20 queries for statistical significance
        significant_sectors = sector_counts[sector_counts >= 20].index
        
        for sector in significant_sectors:
            sector_df = df[df['sector'] == sector]
            sector_total = len(sector_df)
            sector_idk = len(sector_df[sector_df['message_category'].isin(['audio_idk', 'text_idk'])])
            if sector_total > 0:
                sector_idk_pct = (sector_idk / sector_total) * 100
                sector_breakdown.append({
                    'sector': sector,
                    'total_queries': sector_total,
                    'idk_count': sector_idk,
                    'idk_percentage': round(sector_idk_pct, 2)
                })
        
        if sector_breakdown:
            # Check for meaningful differences (>10% variation)
            idk_percentages = [b['idk_percentage'] for b in sector_breakdown]
            if len(idk_percentages) > 1:
                max_pct = max(idk_percentages)
                min_pct = min(idk_percentages)
                if max_pct > 0 and (max_pct - min_pct) / max_pct > 0.1:  # >10% relative difference
                    breakdowns['by_sector'] = sorted(sector_breakdown, key=lambda x: x['idk_percentage'], reverse=True)
    
    return {
        'total_queries': total_queries,
        'idk_count': idk_count,
        'idk_percentage': round(idk_percentage, 2),
        'causes': causes,
        'causes_percentage': causes_percentage,
        'asha_themes': asha_themes,
        'asha_themes_percentage': asha_themes_percentage,
        'breakdowns': breakdowns,
        'idk_queries': idk_queries_dump
    }


def generate_summary_insights(idk_analysis: dict, response_time_analysis: dict, month_str: str) -> str:
    """Generate executive summary insights (≤100 words) with key findings."""
    insights = []
    
    # Insight 1: Overall IDK rate
    idk_pct = idk_analysis['idk_percentage']
    total_queries = idk_analysis['total_queries']
    idk_count = idk_analysis['idk_count']
    
    if idk_count > 0:
        insights.append(f"IDK rate: {idk_pct}% ({idk_count:,}/{total_queries:,} queries).")
    
    # Insight 2: Top IDK cause
    if idk_analysis['causes']:
        top_cause = max(idk_analysis['causes'].items(), key=lambda x: x[1])
        cause_pct = idk_analysis['causes_percentage'][top_cause[0]]
        insights.append(f"Primary cause: {top_cause[0]} ({cause_pct:.1f}% of IDKs).")
    
    # Insight 3: Top ASHA IDK theme (if domain knowledge gaps exist)
    if idk_analysis['asha_themes']:
        top_theme = max(idk_analysis['asha_themes'].items(), key=lambda x: x[1])
        theme_pct = idk_analysis['asha_themes_percentage'][top_theme[0]]
        insights.append(f"Top ASHA theme: {top_theme[0]} ({theme_pct:.1f}% of domain gaps).")
    
    # Insight 4: Language or geographic pattern (if significant)
    breakdowns = idk_analysis.get('breakdowns', {})
    if 'by_language' in breakdowns and len(breakdowns['by_language']) > 1:
        highest_lang = breakdowns['by_language'][0]
        lowest_lang = breakdowns['by_language'][-1]
        if highest_lang['idk_percentage'] > lowest_lang['idk_percentage'] * 1.2:  # >20% difference
            insights.append(f"Language gap: {highest_lang['language']} has {highest_lang['idk_percentage']:.1f}% IDK vs {lowest_lang['language']} at {lowest_lang['idk_percentage']:.1f}%.")
    
    if 'by_district' in breakdowns and len(breakdowns['by_district']) > 0:
        highest_district = breakdowns['by_district'][0]
        insights.append(f"Highest IDK district: {highest_district['district']} ({highest_district['idk_percentage']:.1f}%).")
    
    # Insight 5: Response time (if available)
    if response_time_analysis.get('valid_responses', 0) > 0:
        stats = response_time_analysis['statistics']
        insights.append(f"Avg response time: {stats['mean']:.1f}s (median: {stats['median']:.1f}s, P95: {stats['p95']:.1f}s).")
    
    # Combine insights into executive summary
    summary = " ".join(insights)
    
    # Ensure it's ≤100 words
    words = summary.split()
    if len(words) > 100:
        summary = " ".join(words[:100]) + "..."
    
    return summary


def format_asha_idk_buckets(idk_analysis: dict) -> str:
    """Format ASHA IDK bucket distribution as a readable string."""
    if not idk_analysis.get('asha_themes'):
        return "No ASHA IDK themes identified."
    
    lines = []
    for theme, count in sorted(idk_analysis['asha_themes'].items(), key=lambda x: x[1], reverse=True):
        percentage = idk_analysis['asha_themes_percentage'][theme]
        lines.append(f"  • {theme}: {percentage:.1f}% ({count:,} queries)")
    
    return "\n".join(lines)


def format_markdown_table(headers: list, rows: list[dict]) -> str:
    """Render a simple markdown table."""
    if not rows:
        return "No data available."
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |"
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def build_markdown_report(
    month_str: str,
    summary_insights: str,
    idk_analysis: dict,
    response_time_analysis: dict,
    llm_usage: Optional[dict] = None,
    llm_summary: Optional[str] = None
) -> str:
    """Build a detailed markdown report for IDK and response time analyses."""
    sections: list[str] = []

    # Executive summary
    sections.append(f"# Executive Summary ({month_str})")
    sections.append("")
    sections.append(llm_summary or summary_insights)
    sections.append("")

    # LLM usage
    if llm_usage:
        sections.append("## LLM Token/Cost Estimate")
        sections.append(
            f"- Model: {llm_usage.get('model', '-')}\n"
            f"- Prompt tokens: {llm_usage.get('prompt_tokens', 0)}\n"
            f"- Completion tokens: {llm_usage.get('completion_tokens', 0)}\n"
            f"- Total tokens: {llm_usage.get('total_tokens', 0)}\n"
            f"- Estimated cost: ${llm_usage.get('estimated_cost', 0):.4f}"
        )
        sections.append("")

    # IDK overview
    sections.append("## IDK Overview")
    sections.append(f"- Total queries: {idk_analysis.get('total_queries', 0):,}")
    sections.append(f"- IDK queries: {idk_analysis.get('idk_count', 0):,} ({idk_analysis.get('idk_percentage', 0):.1f}%)")
    sections.append("")

    # IDK causes
    causes = idk_analysis.get('causes', {}) or {}
    causes_pct = idk_analysis.get('causes_percentage', {}) or {}
    if causes:
        rows = [
            {
                "Cause": name,
                "Count": f"{count:,}",
                "% of IDK": f"{causes_pct.get(name, 0):.1f}%"
            }
            for name, count in sorted(causes.items(), key=lambda x: x[1], reverse=True)
        ]
        sections.append("### IDK Causes")
        sections.append(format_markdown_table(["Cause", "Count", "% of IDK"], rows))
        sections.append("")

    # ASHA IDK buckets
    themes = idk_analysis.get('asha_themes', {}) or {}
    themes_pct = idk_analysis.get('asha_themes_percentage', {}) or {}
    if themes:
        rows = [
            {
                "Theme": name,
                "Count": f"{count:,}",
                "% of Domain Gaps": f"{themes_pct.get(name, 0):.1f}%"
            }
            for name, count in sorted(themes.items(), key=lambda x: x[1], reverse=True)
        ]
        sections.append("### ASHA IDK Buckets")
        sections.append(format_markdown_table(["Theme", "Count", "% of Domain Gaps"], rows))
        sections.append("")

    # Breakdowns
    breakdowns = idk_analysis.get('breakdowns', {}) or {}

    if breakdowns.get('by_language'):
        rows = [
            {
                "Language": b["language"],
                "IDK %": f"{b['idk_percentage']:.1f}%",
                "IDK/Total": f"{b['idk_count']:,}/{b['total_queries']:,}"
            }
            for b in breakdowns["by_language"]
        ]
        sections.append("### IDK Breakdown by Language")
        sections.append(format_markdown_table(["Language", "IDK %", "IDK/Total"], rows))
        sections.append("")

    if breakdowns.get('by_district'):
        rows = [
            {
                "District": b["district"],
                "IDK %": f"{b['idk_percentage']:.1f}%",
                "IDK/Total": f"{b['idk_count']:,}/{b['total_queries']:,}"
            }
            for b in breakdowns["by_district"][:10]
        ]
        sections.append("### IDK Breakdown by District (top 10)")
        sections.append(format_markdown_table(["District", "IDK %", "IDK/Total"], rows))
        sections.append("")

    if breakdowns.get('by_block'):
        rows = [
            {
                "Block": b["block"],
                "IDK %": f"{b['idk_percentage']:.1f}%",
                "IDK/Total": f"{b['idk_count']:,}/{b['total_queries']:,}"
            }
            for b in breakdowns["by_block"][:10]
        ]
        sections.append("### IDK Breakdown by Block (top 10)")
        sections.append(format_markdown_table(["Block", "IDK %", "IDK/Total"], rows))
        sections.append("")

    if breakdowns.get('by_sector'):
        rows = [
            {
                "Sector": b["sector"],
                "IDK %": f"{b['idk_percentage']:.1f}%",
                "IDK/Total": f"{b['idk_count']:,}/{b['total_queries']:,}"
            }
            for b in breakdowns["by_sector"][:10]
        ]
        sections.append("### IDK Breakdown by Sector (top 10)")
        sections.append(format_markdown_table(["Sector", "IDK %", "IDK/Total"], rows))
        sections.append("")

    # Response time summary
    rt_stats = response_time_analysis.get('statistics', {}) or {}
    sections.append("## Response Time Summary")
    if rt_stats:
        sections.append(
            f"- Mean: {rt_stats.get('mean', 0):.1f}s; Median: {rt_stats.get('median', 0):.1f}s; "
            f"P95: {rt_stats.get('p95', 0):.1f}s; P90: {rt_stats.get('p90', 0):.1f}s; "
            f"P75: {rt_stats.get('p75', 0):.1f}s; Min: {rt_stats.get('min', 0):.1f}s; Max: {rt_stats.get('max', 0):.1f}s; "
            f"Samples: {rt_stats.get('count', 0):,}"
        )
    else:
        sections.append("- No valid response-time samples.")
    sections.append("")

    # Response time patterns
    patterns = response_time_analysis.get('patterns', {}) or {}

    def add_pattern(title: str, key: str):
        if key in patterns and patterns[key]:
            rows = []
            for name, stat in patterns[key].items():
                rows.append({
                    "Group": name if name else "(blank)",
                    "Mean": f"{stat.get('mean', 0):.1f}s",
                    "Median": f"{stat.get('median', 0):.1f}s",
                    "P95": f"{stat.get('p95', 0):.1f}s",
                    "Count": stat.get('count', 0)
                })
            if rows:
                sections.append(f"### Response Time by {title}")
                sections.append(format_markdown_table(["Group", "Mean", "Median", "P95", "Count"], rows))
                sections.append("")

    add_pattern("Query Type", "by_query_type")
    add_pattern("Message Category", "by_message_category")
    add_pattern("Language", "by_language")
    add_pattern("District", "by_district")
    add_pattern("Message Type", "by_message_type")

    return "\n".join(sections)


def build_llm_prompt(month_str: str, idk_analysis: dict, response_time_analysis: dict) -> List[Dict[str, str]]:
    """Construct a concise prompt for the LLM executive summary."""
    idk_pct = idk_analysis.get("idk_percentage", 0)
    idk_count = idk_analysis.get("idk_count", 0)
    total_q = idk_analysis.get("total_queries", 0)
    themes_pct = idk_analysis.get("asha_themes_percentage", {}) or {}
    top_themes = sorted(themes_pct.items(), key=lambda x: x[1], reverse=True)[:5]

    rt_stats = response_time_analysis.get("statistics", {}) or {}

    def fmt_top_themes():
        if not top_themes:
            return "None"
        return ", ".join([f"{k} {v:.1f}%" for k, v in top_themes])

    return [
        {
            "role": "system",
            "content": (
                "You are a concise analytics assistant. "
                "Write an executive summary in <=100 words, 3-5 crisp insights. "
                "Focus on IDK rates, top themes, language/geo gaps, and response times. "
                "Be direct and non-repetitive."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Month: {month_str}\n"
                f"Total queries: {total_q}\n"
                f"IDK: {idk_count} ({idk_pct:.1f}%)\n"
                f"Top IDK themes: {fmt_top_themes()}\n"
                f"Response times (s): mean {rt_stats.get('mean', 0)}, median {rt_stats.get('median', 0)}, "
                f"p95 {rt_stats.get('p95', 0)}\n"
                "Provide 3-5 bullet-like sentences (but as a short paragraph) "
                "covering: IDK rate, biggest themes, any notable language/geo gaps (if known), "
                "and response-time headline."
            ),
        },
    ]


def estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost based on simple per-1k pricing map."""
    pricing = {
        "gpt-4o-mini": {"in": 0.000150, "out": 0.000600},
        "gpt-4o-2024-08-06": {"in": 0.0025, "out": 0.01},
    }
    price = pricing.get(model, pricing["gpt-4o-mini"])
    return (prompt_tokens * price["in"] + completion_tokens * price["out"]) / 1000


def generate_llm_summary(
    month_str: str,
    idk_analysis: dict,
    response_time_analysis: dict,
    model: str,
    temperature: float,
    max_tokens: int
) -> Tuple[Optional[str], Optional[dict]]:
    """Generate LLM summary with token/cost usage."""
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        if not client.api_key:
            print("Warning: OPENAI_API_KEY not set. Skipping LLM summary.")
            return None, None
        messages = build_llm_prompt(month_str, idk_analysis, response_time_analysis)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content.strip()
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if hasattr(usage, "prompt_tokens") else 0
        completion_tokens = usage.completion_tokens if hasattr(usage, "completion_tokens") else 0
        total_tokens = usage.total_tokens if hasattr(usage, "total_tokens") else prompt_tokens + completion_tokens
        estimated_cost = estimate_llm_cost(model, prompt_tokens, completion_tokens)
        llm_usage = {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": estimated_cost,
        }
        return text, llm_usage
    except Exception as e:
        print(f"Warning: LLM summary failed: {e}")
        return None, None


def save_to_excel(df: pd.DataFrame, output_path: str) -> None:
    """Save dataframe to Excel file."""
    if df.empty:
        print("Warning: No data to save. Creating empty Excel file.")
    
    output_path_obj = Path(output_path).resolve()
    output_dir = output_path_obj.parent
    
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Failed to create output directory {output_dir}: {e}")
    
    try:
        df.to_excel(str(output_path_obj), index=False)
        print(f"Saved {len(df)} rows to {output_path_obj}")
    except Exception as e:
        raise RuntimeError(f"Failed to save Excel file to {output_path_obj}: {e}")


async def main() -> None:
    """Main function to orchestrate the monthly logs compilation."""
    args = parse_args()
    
    if args.month and not args.year:
        print("Error: --month requires --year to be specified.")
        sys.exit(1)
    if args.year and not args.month:
        print("Error: --year requires --month to be specified.")
        sys.exit(1)
    
    try:
        start, end = month_range(args)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print(f"Monthly Logs Compilation")
    print(f"{'='*SEPARATOR_LENGTH}")
    print(f"Date Range: {start.strftime(DATE_FORMAT)} to {end.strftime(DATE_FORMAT)} (IST)")
    print(f"{'='*SEPARATOR_LENGTH}\n")
    
    try:
        df = await fetch_monthly_logs(start, end)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        sys.exit(1)
    
    if df.empty:
        print("No data to process. Exiting.")
        sys.exit(0)
    
    df = filter_test_users(df)
    df = filter_by_log_date(df, start, end)
    
    if df.empty:
        print("No data remaining after filtering. Exiting.")
        sys.exit(0)
    
    # Perform IDK Analysis
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print("IDK Analysis")
    print(f"{'='*SEPARATOR_LENGTH}")
    
    idk_analysis = analyze_idk(df)
    
    print(f"Total queries: {idk_analysis['total_queries']}")
    print(f"IDK queries: {idk_analysis['idk_count']} ({idk_analysis['idk_percentage']}%)")
    
    if idk_analysis['idk_count'] > 0:
        print(f"\nIDK Causes:")
        for cause, count in idk_analysis['causes'].items():
            percentage = idk_analysis['causes_percentage'][cause]
            print(f"  - {cause}: {count} ({percentage:.1f}%)")
        
        if idk_analysis['asha_themes']:
            print(f"\nASHA IDK Themes (Domain Knowledge Gaps):")
            for theme, count in idk_analysis['asha_themes'].items():
                percentage = idk_analysis['asha_themes_percentage'][theme]
                print(f"  - {theme}: {count} ({percentage:.1f}%)")
        
        # Show breakdowns if they exist and show meaningful differences
        breakdowns = idk_analysis.get('breakdowns', {})
        
        if 'by_language' in breakdowns:
            print("\nIDK Patterns")
            print(f"\nIDK Breakdown by Language:")
            for lang_data in breakdowns['by_language']:
                print(f"  - {lang_data['language']}: {lang_data['idk_percentage']:.1f}% "
                      f"({lang_data['idk_count']}/{lang_data['total_queries']} queries)")
        
        if 'by_district' in breakdowns:
            print(f"\nIDK Breakdown by District (top 10):")
            for district_data in breakdowns['by_district'][:10]:
                print(f"  - {district_data['district']}: {district_data['idk_percentage']:.1f}% "
                      f"({district_data['idk_count']}/{district_data['total_queries']} queries)")
        
        if 'by_block' in breakdowns:
            print(f"\nIDK Breakdown by Block (top 10):")
            for block_data in breakdowns['by_block'][:10]:
                print(f"  - {block_data['block']}: {block_data['idk_percentage']:.1f}% "
                      f"({block_data['idk_count']}/{block_data['total_queries']} queries)")
        
        if 'by_sector' in breakdowns:
            print(f"\nIDK Breakdown by Sector (top 10):")
            for sector_data in breakdowns['by_sector'][:10]:
                print(f"  - {sector_data['sector']}: {sector_data['idk_percentage']:.1f}% "
                      f"({sector_data['idk_count']}/{sector_data['total_queries']} queries)")
    
    # Perform Response Time Analysis
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print("Response Time Analysis")
    print(f"{'='*SEPARATOR_LENGTH}")
    
    response_time_analysis = analyze_response_times(df)
    
    print(f"Total queries: {response_time_analysis['total_queries']}")
    print(f"Valid responses (with timestamps): {response_time_analysis['valid_responses']}")
    
    if response_time_analysis['valid_responses'] > 0:
        stats = response_time_analysis['statistics']
        print(f"\nResponse Time Statistics (seconds):")
        print(f"  Mean: {stats['mean']}s")
        print(f"  Median: {stats['median']}s")
        print(f"  P95: {stats['p95']}s")
        print(f"  P90: {stats['p90']}s")
        print(f"  P75: {stats['p75']}s")
        print(f"  Min: {stats['min']}s")
        print(f"  Max: {stats['max']}s")
        
        patterns = response_time_analysis['patterns']
        
        # Show patterns by query_type
        if 'by_query_type' in patterns and patterns['by_query_type']:
            print(f"\nResponse Times by Query Type (slowest first):")
            for query_type, stats_dict in list(patterns['by_query_type'].items())[:10]:  # Top 10
                print(f"  - {query_type}: mean={stats_dict['mean']}s, median={stats_dict['median']}s, "
                      f"p95={stats_dict['p95']}s (count={stats_dict['count']})")
        
        # Show patterns by message_category
        if 'by_message_category' in patterns and patterns['by_message_category']:
            print(f"\nResponse Times by Message Category (slowest first):")
            for category, stats_dict in patterns['by_message_category'].items():
                print(f"  - {category}: mean={stats_dict['mean']}s, median={stats_dict['median']}s, "
                      f"p95={stats_dict['p95']}s (count={stats_dict['count']})")
        
        # Show patterns by language (if meaningful differences)
        if 'by_language' in patterns and patterns['by_language']:
            lang_stats = patterns['by_language']
            if len(lang_stats) > 1:
                # Check if there's meaningful difference (more than 10% variation)
                mean_times = [s['mean'] for s in lang_stats.values()]
                if max(mean_times) / min(mean_times) > 1.1:
                    print(f"\nResponse Times by Language (slowest first):")
                    for language, stats_dict in lang_stats.items():
                        print(f"  - {language}: mean={stats_dict['mean']}s, median={stats_dict['median']}s, "
                              f"p95={stats_dict['p95']}s (count={stats_dict['count']})")
        
        # Show patterns by district (if meaningful differences)
        if 'by_district' in patterns and patterns['by_district']:
            district_stats = patterns['by_district']
            if len(district_stats) > 1:
                mean_times = [s['mean'] for s in district_stats.values()]
                if max(mean_times) / min(mean_times) > 1.1:
                    print(f"\nResponse Times by District (slowest first, top 10):")
                    for district, stats_dict in list(district_stats.items())[:10]:
                        print(f"  - {district}: mean={stats_dict['mean']}s, median={stats_dict['median']}s, "
                              f"p95={stats_dict['p95']}s (count={stats_dict['count']})")
    
    # Generate and display summary insights
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print("Summary Insights")
    print(f"{'='*SEPARATOR_LENGTH}")
    
    month_str = start.strftime("%Y-%m")
    summary_insights = generate_summary_insights(idk_analysis, response_time_analysis, month_str)
    asha_buckets = format_asha_idk_buckets(idk_analysis)

    llm_summary = None
    llm_usage = None
    if args.llm_report:
        llm_summary, llm_usage = generate_llm_summary(
            month_str=month_str,
            idk_analysis=idk_analysis,
            response_time_analysis=response_time_analysis,
            model=args.llm_model,
            temperature=args.llm_temperature,
            max_tokens=args.llm_max_tokens,
        )
        if llm_usage:
            print("\nLLM Summary Token/Cost Estimate:")
            print(f"  Model: {llm_usage['model']}")
            print(f"  Prompt tokens: {llm_usage['prompt_tokens']}")
            print(f"  Completion tokens: {llm_usage['completion_tokens']}")
            print(f"  Total tokens: {llm_usage['total_tokens']}")
            print(f"  Estimated cost: ${llm_usage['estimated_cost']:.4f}")

    print(f"\nExecutive Summary ({month_str}):")
    print(f"{llm_summary or summary_insights}")
    print(f"\nASHA IDK Bucket Distribution:")
    print(asha_buckets)
    
    # Note: Month-over-month comparison would require loading previous month's data
    # This can be implemented later when historical data is available
    print(f"\nNote: Month-over-month comparison requires previous month's analysis data.")
    
    # Determine output paths
    if args.output:
        base_output_path = Path(args.output)
        output_path = str(base_output_path)
        idk_output_path = str(base_output_path.parent / f"{base_output_path.stem}_idk_queries{base_output_path.suffix}")
        response_time_output_path = str(base_output_path.parent / f"{base_output_path.stem}_response_times{base_output_path.suffix}")
        summary_output_path = str(base_output_path.parent / f"{base_output_path.stem}_summary.md")
    else:
        month_str = start.strftime("%Y-%m")
        output_path = f"monthly_logs_{month_str}.xlsx"
        idk_output_path = f"monthly_logs_{month_str}_idk_queries.xlsx"
        response_time_output_path = f"monthly_logs_{month_str}_response_times.xlsx"
        summary_output_path = f"monthly_logs_{month_str}_summary.md"
        summary_output_path = f"monthly_logs_{month_str}_summary.md"
    
    # Save main logs
    try:
        save_to_excel(df, output_path)
    except (OSError, RuntimeError) as e:
        print(f"Error saving file: {e}")
        sys.exit(1)
    
    # Save IDK queries dump
    if not idk_analysis['idk_queries'].empty:
        try:
            save_to_excel(idk_analysis['idk_queries'], idk_output_path)
        except (OSError, RuntimeError) as e:
            print(f"Warning: Failed to save IDK queries dump: {e}")
    
    # Save response time data
    if not response_time_analysis['response_time_data'].empty:
        try:
            save_to_excel(response_time_analysis['response_time_data'], response_time_output_path)
        except (OSError, RuntimeError) as e:
            print(f"Warning: Failed to save response time data: {e}")

    # Save markdown summary (executive + detailed tables)
    try:
        summary_md = build_markdown_report(
            month_str,
            summary_insights,
            idk_analysis,
            response_time_analysis,
            llm_usage=llm_usage,
            llm_summary=llm_summary
        )
        Path(summary_output_path).write_text(summary_md, encoding="utf-8")
        print(f"Summary markdown: {summary_output_path}")
    except Exception as e:
        print(f"Warning: Failed to save summary markdown: {e}")
    
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print(f"Compilation complete!")
    print(f"Output file: {output_path}")
    if not idk_analysis['idk_queries'].empty:
        print(f"IDK queries dump: {idk_output_path}")
    if not response_time_analysis['response_time_data'].empty:
        print(f"Response time data: {response_time_output_path}")
    print(f"Total rows: {len(df)}")
    print(f"{'='*SEPARATOR_LENGTH}")


if __name__ == "__main__":
    try:
        load_dotenv(locate_keys(), override=True)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
        sys.exit(130)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

