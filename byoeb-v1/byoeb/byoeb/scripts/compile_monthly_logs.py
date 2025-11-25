"""Inspect staging ashadb collections relevant to monthly log analysis."""

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pymongo import MongoClient

IST = ZoneInfo("Asia/Kolkata")


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


def load_connection_string() -> str:
    load_dotenv(locate_keys(), override=True)
    conn = os.getenv("MONGO_DB_CONNECTION_STRING")
    if not conn:
        raise RuntimeError("Missing MONGO_DB_CONNECTION_STRING in keys.env")
    return conn


def month_range(args) -> Tuple[datetime, datetime]:
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=IST)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=IST)
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
    parser = argparse.ArgumentParser(description="Preview staging ASHA bot data.")
    parser.add_argument("--start", type=str, help="Start date (inclusive) YYYY-MM-DD.")
    parser.add_argument("--end", type=str, help="End date (exclusive) YYYY-MM-DD.")
    parser.add_argument("--sample", type=int, default=5, help="Rows to show (default 5).")
    return parser.parse_args()


def fetch_users(collection) -> Dict[str, Dict]:
    projection = {
        "_id": 0,
        "User.user_id": 1,
        "User.phone_number_id": 1,
        "User.user_language": 1,
        "User.user_location": 1,
        "User.user_type": 1,
        "User.test_user": 1,
        "User.created_timestamp": 1,
    }
    users = {}
    for doc in collection.find({}, projection):
        user = doc.get("User", {})
        user_id = user.get("user_id")
        if user_id:
            users[user_id] = user
    return users


def fetch_messages(collection, start_ts: float, end_ts: float):
    query = {
        "message_data.incoming_timestamp": {"$gte": start_ts, "$lt": end_ts},
        "message_data.message_category": {"$ne": "onboarding_response"},
    }
    projection = {
        "_id": 0,
        "message_data.user.user_id": 1,
        "message_data.message_context.message_id": 1,
        "message_data.message_context.message_source_text": 1,
        "message_data.message_context.message_type": 1,
        "message_data.message_context.message_english_text": 1,
        "message_data.reply_context.reply_english_text": 1,
        "message_data.reply_context.reply_source_text": 1,
        "message_data.message_category": 1,
        "message_data.incoming_timestamp": 1,
    }
    return list(collection.find(query, projection).sort("message_data.incoming_timestamp", -1))


def main():
    args = parse_args()
    start, end = month_range(args)
    start_ts = start.timestamp()
    end_ts = end.timestamp()

    client = MongoClient(load_connection_string())
    db = client["ashadb"]

    users_map = fetch_users(db["ashausers"])
    messages = fetch_messages(db["ashamessages"], start_ts, end_ts)
    if not messages:
        print("No messages in selected range.")
        return

    sample_n = max(1, args.sample)
    print(f"\nShowing {sample_n} messages between {start} and {end} (IST):\n")
    for msg in messages[:sample_n]:
        md = msg["message_data"]
        user_id = md["user"].get("user_id")
        user = users_map.get(user_id, {})
        print(
            f"- user_id={user_id}, phone_id={user.get('phone_number_id')}, "
            f"lang={user.get('user_language')}, category={md.get('message_category')}, "
            f"source={md['message_context'].get('message_source_text')}, "
            f"text={md['message_context'].get('message_english_text')!r}"
        )


if __name__ == "__main__":
    main()

