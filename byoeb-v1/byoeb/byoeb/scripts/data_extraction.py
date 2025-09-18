from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import pandas as pd
import json
import re

NEW_URI = "mongodb+srv://username:password@cluster-name.mongodb.net/?tls=true&authMechanism=SCRAM-SHA-256"
OLD_URI = "mongodb://username:password@host:port/?ssl=true&replicaSet=globaldb&retrywrites=false&maxIdleTimeMS=120000"

NEW_DB = "ashadb"
NEW_COLL = "ashausers"

OLD_DB = "llm-bot-database"
OLD_COLL = "users"

OUT_XLSX = "asha_user_mapping.xlsx"


def test_connection(uri: str, name: str):
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        print(f"Successfully connected to {name}")
        return client
    except ConnectionFailure as e:
        print(f"Failed to connect to {name}: {e}")
        return None


def normalize_msisdn(v):
    """add '91' if 10-digit"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    digits = re.sub(r"\D+", "", s)
    if not digits:
        return None
    if len(digits) == 10:
        digits = "91" + digits
    return digits

def to_iso_utc(v):
    """
    Return UTC ISO8601 ('YYYY-MM-DDTHH:MM:SSZ').

    Accepts:
      - Unix epoch in seconds / milliseconds / microseconds / nanoseconds
      - ISO strings / Mongo Date / pandas-friendly objects
    """
    if v is None:
        return None

    try:
        s = str(v).strip()
        if isinstance(v, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", s):
            n = float(s)
            n_abs = abs(n)
            # infer unit by magnitude
            if n_abs >= 1e18:
                n = n / 1e9
            elif n_abs >= 1e15:
                n = n / 1e6
            elif n_abs >= 1e12:
                n = n / 1e3
            ts = pd.to_datetime(n, unit="s", utc=True)
        else:
            ts = pd.to_datetime(v, utc=True, errors="coerce")

        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None

def as_text(v):
    if v is None:
        return None
    return str(v)


def fetch_old(old_client: MongoClient):
    cursor = old_client[OLD_DB][OLD_COLL].find({})
    rows, full_rows, scanned = [], [], 0

    for doc in cursor:
        scanned += 1
        full_rows.append({
            "doc_json": json.dumps(doc, default=str, ensure_ascii=False)
        })

        whatsapp_candidates = [
            doc.get("whatsapp_id"),
            doc.get("phone_number"),
            doc.get("mobile_number"),
        ]
        raw = next((c for c in whatsapp_candidates if c not in (None, "", "null", "None")), None)
        join_key = normalize_msisdn(raw)

        rows.append({
            "old_user_id": doc.get("user_id"),
            "whatsapp_id": raw,
            "timestamp": to_iso_utc(doc.get("timestamp")),
            "join_whatsapp": join_key, # not exported
            # keep extras only in memory; we'll drop before export
            "whatsapp_id_text": as_text(raw),
            "old_doc_id": doc.get("_id"),
        })

    print(f"Old users scanned: {scanned}; rows collected: {len(rows)}")
    df_join = pd.DataFrame(rows, columns=[
        "old_user_id", "whatsapp_id", "timestamp", "join_whatsapp", "whatsapp_id_text", "old_doc_id"
    ])
    df_full = pd.DataFrame(full_rows, columns=["doc_json"])
    return df_join, df_full


def fetch_new(new_client: MongoClient):
    cursor = new_client[NEW_DB][NEW_COLL].find({})
    rows, full_rows, scanned = [], [], 0

    for doc in cursor:
        scanned += 1
        full_rows.append({
            "doc_json": json.dumps(doc, default=str, ensure_ascii=False)
        })

        user = (doc.get("User") or {})
        loc = user.get("user_location") or {}
        district = None
        if isinstance(loc, dict):
            for k in ("district", "District", "district_name", "districtName"):
                if loc.get(k):
                    district = loc[k]
                    break

        phone_number_id = user.get("phone_number_id")
        created_ts = to_iso_utc(user.get("created_timestamp"))
        join_key = normalize_msisdn(phone_number_id)

        rows.append({
            "new_user_id": user.get("user_id"),
            "phone_number_id": phone_number_id,
            "created_timestamp": created_ts,
            "join_whatsapp": join_key, # not exported
            "test_user": bool(user.get("test_user", False)),
            "user_location": district,
            # keep extras only in memory; we'll drop before export
            "phone_number_id_text": as_text(phone_number_id),
            "new_doc_id": doc.get("_id"),
        })

    print(f"New users scanned: {scanned}; rows collected: {len(rows)}")
    df_join = pd.DataFrame(rows, columns=[
        "new_user_id", "phone_number_id", "created_timestamp", "join_whatsapp",
        "test_user", "user_location", "phone_number_id_text", "new_doc_id"
    ])
    df_full = pd.DataFrame(full_rows, columns=["doc_json"])
    return df_join, df_full


if __name__ == "__main__":
    new_client = test_connection(NEW_URI, "New System")
    old_client = test_connection(OLD_URI, "Old System")
    if not new_client or not old_client:
        raise SystemExit(2)

    try:
        print("New system DBs:", new_client.list_database_names())
        print("Old system DBs:", old_client.list_database_names())
    except Exception:
        pass

    df_old, df_old_full = fetch_old(old_client)
    df_new, df_new_full = fetch_new(new_client)

    df_merged = df_new.merge(
        df_old[["join_whatsapp", "old_user_id", "whatsapp_id", "timestamp"]],
        on="join_whatsapp",
        how="left",
        suffixes=("_new", "_old")
    )

    # Summaries & details of duplicates by RAW fields
    dupes_new_summary = (
        df_new.groupby(["phone_number_id"], dropna=False)
              .size().reset_index(name="count")
              .query("count > 1")
              .sort_values("count", ascending=False)
    )
    dupes_new_details = df_new[df_new["phone_number_id"].isin(dupes_new_summary["phone_number_id"])]

    dupes_old_summary = (
        df_old.groupby(["whatsapp_id"], dropna=False)
              .size().reset_index(name="count")
              .query("count > 1")
              .sort_values("count", ascending=False)
    )
    dupes_old_details = df_old[df_old["whatsapp_id"].isin(dupes_old_summary["whatsapp_id"])]

    # drop helper columns
    new_export = df_new.drop(columns=["phone_number_id_text", "join_whatsapp", "new_doc_id"], errors="ignore")
    old_export = df_old.drop(columns=["whatsapp_id_text", "join_whatsapp", "old_doc_id"], errors="ignore")

    merged_export = df_merged[
        [
            # do NOT include join_whatsapp or helper cols
            "new_user_id", "phone_number_id", "created_timestamp", "test_user", "user_location",
            "old_user_id", "whatsapp_id", "timestamp",
        ]
    ]

    dupes_new_details_export = dupes_new_details.drop(columns=["phone_number_id_text", "join_whatsapp", "new_doc_id"], errors="ignore")
    dupes_old_details_export = dupes_old_details.drop(columns=["whatsapp_id_text", "join_whatsapp", "old_doc_id"], errors="ignore")

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        # exports without helper cols
        new_export.to_excel(writer, sheet_name="new_join", index=False)
        old_export.to_excel(writer, sheet_name="old_join", index=False)

        # Merged export without helper cols
        merged_export.to_excel(writer, sheet_name="merged_on_join", index=False)

        # Duplicate summaries & details (raw-field-based, no helper cols)
        dupes_new_summary.to_excel(writer, sheet_name="dupes_new_summary", index=False)
        dupes_new_details_export.to_excel(writer, sheet_name="dupes_new_details", index=False)

        dupes_old_summary.to_excel(writer, sheet_name="dupes_old_summary", index=False)
        dupes_old_details_export.to_excel(writer, sheet_name="dupes_old_details", index=False)

        # FULL docs as JSON (all fields preserved)
        df_new_full.to_excel(writer, sheet_name="new_full", index=False)
        df_old_full.to_excel(writer, sheet_name="old_full", index=False)

    print(f"Wrote {OUT_XLSX}")
