"""Compile monthly user-bot interaction logs for analysis.
Fetches data using the same logic as ASHA Logs page and generates Excel output.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
import pandas as pd
from dotenv import load_dotenv

# Add parent directory to path to import byoeb modules
script_dir = Path(__file__).parent
byoeb_package_dir = script_dir.parent
byoeb_parent_dir = byoeb_package_dir.parent
sys.path.insert(0, str(byoeb_parent_dir))

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
    
    if args.output:
        output_path = args.output
    else:
        month_str = start.strftime("%Y-%m")
        output_path = f"monthly_logs_{month_str}.xlsx"
    
    try:
        save_to_excel(df, output_path)
    except (OSError, RuntimeError) as e:
        print(f"Error saving file: {e}")
        sys.exit(1)
    
    print(f"\n{'='*SEPARATOR_LENGTH}")
    print(f"Compilation complete!")
    print(f"Output file: {output_path}")
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

