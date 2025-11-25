"""
Generate an Excel dump of all users whose preferred language is Hindi.

Usage:
    python byoeb-v1/byoeb/byoeb/scripts/export_hindi_users.py \
        --output data/hindi_users_dump.xlsx

Environment variables (must already be exported before running):
    - MONGO_DB_CONNECTION_STRING
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient


SCRIPTS_DIR = Path(__file__).resolve().parent
APP_ROOT = SCRIPTS_DIR.parent  # byoeb-v1/byoeb/byoeb
WORKSPACE_ROOT = SCRIPTS_DIR.parents[4]  # repository root

DEFAULT_OUTPUT = WORKSPACE_ROOT / "data" / "hindi_users_dump.xlsx"
APP_CONFIG_PATH = APP_ROOT / "chat_app" / "app_config.json"
DEFAULT_ENV_LOCATIONS: Iterable[Path] = (
    APP_ROOT / "keys.env",
    APP_ROOT.parent / "keys.env",
    WORKSPACE_ROOT / "keys.env",
)


def load_environment(env_file: Optional[Path]) -> bool:
    """Load environment variables from a .env file if provided."""
    candidate_paths = []
    if env_file:
        candidate_paths.append(env_file)
    candidate_paths.extend(DEFAULT_ENV_LOCATIONS)

    for path in candidate_paths:
        if path and path.exists():
            load_dotenv(path, override=False)
            return True

    if env_file:
        raise FileNotFoundError(f"Specified --env-file not found at {env_file}")
    return False


def resolve_db_metadata(
    db_name: Optional[str], collection: Optional[str]
) -> tuple[str, str]:
    """
    Determine database and collection names.

    If CLI arguments are missing, fall back to chat_app/app_config.json as the
    source of truth.
    """
    if db_name and collection:
        return db_name, collection

    if not APP_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"app_config.json not found at {APP_CONFIG_PATH}. "
            "Provide --db-name/--collection explicitly."
        )

    with open(APP_CONFIG_PATH, "r", encoding="utf-8") as fh:
        app_config = json.load(fh)

    mongo_cfg = app_config["databases"]["mongo_db"]
    resolved_db = db_name or mongo_cfg["database_name"]
    resolved_collection = collection or mongo_cfg["user_collection"]
    return resolved_db, resolved_collection


def get_connection_string(cli_value: Optional[str]) -> str:
    """Retrieve a Mongo connection string from CLI arg or environment."""
    conn = cli_value or os.getenv("MONGO_DB_CONNECTION_STRING")
    if not conn:
        raise RuntimeError(
            "Mongo connection string not found. "
            "Pass --connection-string or set MONGO_DB_CONNECTION_STRING."
        )
    return conn


def safe_date(ts: Any) -> Optional[str]:
    """Convert Unix timestamp (string/int) to ISO date string."""
    if ts is None:
        return None
    try:
        ts_int = int(ts)
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return dt.date().isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def fetch_users(collection, language: str) -> list[Dict[str, Any]]:
    """Fetch users for the requested language from Mongo."""
    cursor = collection.find(
        {"User.user_language": {"$regex": f"^{language}$", "$options": "i"}},
        {
            "_id": 1,
            "User.phone_number_id": 1,
            "User.user_id": 1,
            "User.user_language": 1,
            "User.user_location": 1,
            "User.created_timestamp": 1,
        },
    )
    return list(cursor)


def normalize_phone_number(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    phone = str(raw).strip()
    return phone[-10:]


def split_location(raw_location: Any) -> Dict[str, Optional[str]]:
    """
    Extract structured location columns.

    Expected keys: district (mandatory in data), block, sector, sub_center.
    Any extra keys are captured as a JSON string in location_other.
    """
    if not raw_location:
        return {
            "district": None,
            "block": None,
            "sector": None,
            "sub_center": None,
            "location_other": None,
        }

    location = raw_location
    if isinstance(raw_location, str):
        try:
            location = json.loads(raw_location)
        except Exception:
            location = {}

    district = None
    block = None
    sector = None
    sub_center = None
    extras = {}

    if isinstance(location, dict):
        for key, value in location.items():
            key_lower = key.lower()
            if key_lower == "district":
                district = value
            elif key_lower == "block":
                block = value
            elif key_lower == "sector":
                sector = value
            elif key_lower == "sub_center":
                sub_center = value
            else:
                extras[key] = value

    extras_json = json.dumps(extras, ensure_ascii=False) if extras else None
    return {
        "district": district,
        "block": block,
        "sector": sector,
        "sub_center": sub_center,
        "location_other": extras_json,
    }


def build_rows(documents: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Transform Mongo documents into flat rows for export."""
    rows: list[Dict[str, Any]] = []
    for doc in documents:
        user = doc.get("User", {})
        location_parts = split_location(user.get("user_location"))
        row = {
            "phone_number": normalize_phone_number(user.get("phone_number_id")),
            "user_id": user.get("user_id") or doc.get("_id"),
            "language": user.get("user_language"),
            "onboarding_timestamp": user.get("created_timestamp"),
            "onboarding_date": safe_date(user.get("created_timestamp")),
            **location_parts,
        }
        rows.append(row)
    return rows


def ensure_output_dir(path: Path) -> None:
    """Create parent directories for the output file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def export_to_excel(rows: list[Dict[str, Any]], output: Path) -> None:
    """Persist the rows as an Excel workbook."""
    ensure_output_dir(output)
    frame = pd.DataFrame(rows)
    frame.sort_values(by=["onboarding_date", "phone_number"], inplace=True, ignore_index=True)
    frame.to_excel(output, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export all onboarded users for a specific language (default: Hindi)."
    )
    parser.add_argument(
        "--language",
        default="hi",
        help="Language code to filter on (default: hi).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path to the output Excel file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--db-name",
        dest="db_name",
        help="Mongo database name. Defaults to chat_app/app_config.json value.",
    )
    parser.add_argument(
        "--collection",
        help="Mongo collection name. Defaults to chat_app/app_config.json value.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Path to keys.env (optional, defaults to repo-standard locations).",
    )
    parser.add_argument(
        "--connection-string",
        dest="connection_string",
        help="Mongo connection string. Overrides MONGO_DB_CONNECTION_STRING.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_environment(args.env_file)
    db_name, collection_name = resolve_db_metadata(args.db_name, args.collection)
    connection_string = get_connection_string(args.connection_string)

    client = MongoClient(connection_string)
    collection = client[db_name][collection_name]
    documents = fetch_users(collection, args.language)

    if not documents:
        print(f"No users found with language '{args.language}'.")
        return

    rows = build_rows(documents)
    export_to_excel(rows, args.output)

    print(
        f"Exported {len(rows)} users "
        f"with language '{args.language}' to '{args.output.resolve()}'"
    )


if __name__ == "__main__":
    main()
