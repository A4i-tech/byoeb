"""
Release QA benchmark: run curated positive/negative questions against the bot
and report metrics for qualitative release comparison.

This script is for manual benchmarking only. Do NOT use it in GitHub Actions or
any CI pipeline to fail the build. It always exits 0.

Usage:
  From byoeb-v1/byoeb:
    poetry run python tests/integration/run_release_qa_benchmark.py
    poetry run python tests/integration/run_release_qa_benchmark.py --base-url http://127.0.0.1:8000
    poetry run python tests/integration/run_release_qa_benchmark.py --use-mcp   # MCP asha_chat instead of /receive
    poetry run python tests/integration/run_release_qa_benchmark.py --output benchmark_results.json

Requires:
  - Chat app running on base-url
  - Receive mode (default): message consumer running. MCP mode (--use-mcp): no consumer needed.
  - Test user registered (PHONE_NUMBER_ID)
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# Paths: script lives in tests/integration
_CURRENT_DIR = Path(__file__).resolve().parent
_BYOEB_ROOT = _CURRENT_DIR.parent.parent
if str(_BYOEB_ROOT) not in sys.path:
    sys.path.insert(0, str(_BYOEB_ROOT))

# Load keys.env so we see same env as chat app (e.g. MONGO_DB_CONNECTION_STRING)
_KEYS_ENV = _BYOEB_ROOT / "keys.env"
if _KEYS_ENV.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_KEYS_ENV, override=True)
    except ImportError:
        pass

DEFAULT_SET_PATH = _CURRENT_DIR / "release_qa_regression_set.json"
# Aligned with run_immunization_questions.py and test_already_onboarded.py:
# - Base URL: RECIEVE_URL or http://127.0.0.1:8000 (immunization uses 127.0.0.1; test_already_onboarded uses localhost:8000/receive)
# - Phone: PHONE_NUMBER_ID or 919000000001 (test_early_return_already_onboarded uses 917567071072)
# - User name: USER_NAME or "Test User"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_PHONE_NUMBER_ID = "919000000001"
USER_NAME = os.getenv("USER_NAME", "Test User")

# IDK detection: match both (1) template text and (2) app utils.is_idk() phrases
# so we correctly classify "I do not know the answer to your question" etc.
IDK_PHRASES = [
    "outside the scope of my current knowledge",
    "ask your ANM",
    "Please wait, ask your ANM",
    "i do not know the answer to your question",
    "i don't know the answer",
    "i do not know",
    "i don't know",
    "idk",
]
# Disambiguation: bot asks for clarification (not a full answer). Use API category and/or text fallback.
DISAMBIGUATION_CATEGORIES = ("text_disambiguation", "audio_disambiguation")
DISAMBIGUATION_PHRASES = [
    "which one are you interested in",
    "which one would",
    "i found some information related to",
    "i did not understand this question",
    "please rephrase or ask again",
]
RESPONSE_SNIPPET_LEN = 300  # chars to show when printing responses


def load_benchmark_set(path: Path) -> List[Dict[str, Any]]:
    """Load benchmark set from JSON. Each item: question, expected ('answered'|'idk'), optional category."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Benchmark set must be a JSON array of {question, expected, category?}")
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "question" not in item or "expected" not in item:
            raise ValueError(f"Item {i}: must have 'question' and 'expected'")
        q = str(item["question"]).strip()
        exp = str(item["expected"]).strip().lower()
        if exp not in ("answered", "idk"):
            raise ValueError(f"Item {i}: expected must be 'answered' or 'idk', got {item['expected']!r}")
        out.append({
            "question": q,
            "expected": exp,
            "category": item.get("category", ""),
        })
    return out


def create_text_message_payload(
    text: str,
    phone_number_id: str = DEFAULT_PHONE_NUMBER_ID,
    message_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Create WhatsApp webhook payload for a text message."""
    if message_id is None:
        message_id = f"wamid.test{int(time.time())}{phone_number_id}"
    if timestamp is None:
        timestamp = str(int(time.time()))
    return {
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
                                "phone_number_id": "183958451475612",
                            },
                            "contacts": [{"profile": {"name": USER_NAME}, "wa_id": phone_number_id}],
                            "messages": [
                                {
                                    "from": phone_number_id,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def get_bot_messages(base_url: str, timestamp: str, timeout: int = 10) -> List[Dict[str, Any]]:
    """Fetch bot messages after the given timestamp."""
    url = base_url.rstrip("/").replace("/receive", "") + "/get_bot_messages"
    url = f"{url}?timestamp={timestamp}"
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return [m for m in data if isinstance(m, dict)]
            if isinstance(data, dict):
                return [data]
        return []
    except Exception:
        return []


def wait_for_bot_response(
    base_url: str,
    user_timestamp: str,
    timeout: int = 45,
    poll_interval: int = 2,
) -> List[Dict[str, Any]]:
    """Wait until at least one bot message appears after user_timestamp."""
    start = time.time()
    while time.time() - start < timeout:
        all_msgs = get_bot_messages(base_url, user_timestamp)
        bot_msgs = []
        for m in all_msgs:
            if m.get("message_category") in (
                "bot_to_asha", "bot_to_asha_response", "bot_to_anm", "bot_to_anm_response",
                "bot_to_anm_verification", "bot_to_anm_consensus", "audio_idk", "text_idk",
                "audio_idk_reconfirmation", "text_disambiguation", "audio_disambiguation",
            ):
                bot_msgs.append(m)
            elif m.get("message_category") in ("asha_to_bot", "anm_to_bot", "user_to_bot"):
                continue
            elif m.get("outgoing_timestamp") not in (None, "None", ""):
                bot_msgs.append(m)
        if bot_msgs:
            valid_ts = [
                int(str(m["outgoing_timestamp"]))
                for m in bot_msgs
                if m.get("outgoing_timestamp") not in (None, "None", "")
            ]
            if valid_ts and max(valid_ts) > int(user_timestamp):
                return bot_msgs
        time.sleep(poll_interval)
    return []


def extract_response_text(bot_messages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """Concatenate message_source_text from bot messages; return (text, primary_message_category).
    primary_message_category is from the message with latest outgoing_timestamp that has text."""
    parts = []
    primary_category: Optional[str] = None
    best_ts: Optional[int] = None
    for m in bot_messages:
        ctx = m.get("message_context") or {}
        text = ctx.get("message_source_text") or ""
        if text:
            parts.append(text)
        ts = m.get("outgoing_timestamp")
        if ts is not None and ts not in ("None", ""):
            try:
                t = int(str(ts))
                if best_ts is None or t >= best_ts:
                    best_ts = t
                    if text:
                        primary_category = m.get("message_category")
            except (TypeError, ValueError):
                pass
    return " ".join(parts).strip(), primary_category


def is_idk_response(response_text: str) -> bool:
    """True if the response is the standard IDK (out of scope) message."""
    if not response_text:
        return False
    normalized = " ".join(response_text.split()).lower()
    return any(phrase.lower() in normalized for phrase in IDK_PHRASES)


def is_disambiguation_response(response_text: str, message_category: Optional[str]) -> bool:
    """True if the response is disambiguation (clarification request), not a full answer.
    Uses message_category from API when present; falls back to text phrases."""
    if message_category in DISAMBIGUATION_CATEGORIES:
        return True
    if not response_text:
        return False
    normalized = " ".join(response_text.split()).lower()
    return any(phrase in normalized for phrase in DISAMBIGUATION_PHRASES)


def snippet(text: str, max_len: int = RESPONSE_SNIPPET_LEN) -> str:
    """Return truncated text for display; normalize newlines."""
    if not text:
        return "(no response)"
    one_line = " ".join(text.split())
    return one_line[:max_len] + ("..." if len(one_line) > max_len else "")


def mask_mongo_connection_string(conn_str: Optional[str]) -> str:
    """Mask password in MongoDB connection string for safe console display."""
    if not conn_str or not conn_str.strip():
        return "(not set)"
    # mongodb://user:password@host or mongodb+srv://user:password@host
    masked = re.sub(r"(mongodb\+?srv?://[^:]+:)([^@]+)(@)", r"\1****\3", conn_str)
    if masked != conn_str:
        return masked
    # No password part matched; show scheme + host only (e.g. mongodb://host:27017)
    if len(conn_str) <= 60:
        return conn_str
    return conn_str[:60] + "..."


def run_one_question(
    base_url: str,
    question: str,
    phone_number_id: str,
    receive_timeout: int = 30,
    wait_timeout: int = 45,
) -> Dict[str, Any]:
    """Send one question to /receive, wait for bot response, return result with is_idk and status."""
    receive_url = base_url.rstrip("/")
    if not receive_url.endswith("/receive"):
        receive_url = receive_url + "/receive"
    timestamp = str(int(time.time()))
    payload = create_text_message_payload(question, phone_number_id=phone_number_id, timestamp=timestamp)
    result = {
        "question": question,
        "response_text": "",
        "is_idk": False,
        "is_disambiguation": False,
        "message_category": None,
        "status": "unknown",
        "error": None,
    }
    try:
        r = requests.post(
            receive_url, json=payload, headers={"Content-Type": "application/json"}, timeout=receive_timeout
        )
        result["receive_status_code"] = r.status_code
        if r.status_code != 200:
            result["status"] = "receive_failed"
            result["error"] = (r.text[:500] if r.text else "Non-200")
            return result
    except Exception as e:
        result["status"] = "receive_error"
        result["error"] = str(e)
        return result

    bot_messages = wait_for_bot_response(base_url, timestamp, timeout=wait_timeout)
    response_text, primary_category = extract_response_text(bot_messages)
    result["response_text"] = response_text[:2000] if response_text else ""
    result["message_category"] = primary_category
    result["is_disambiguation"] = is_disambiguation_response(response_text, primary_category)
    result["is_idk"] = (
        not result["is_disambiguation"]
        and (primary_category in ("text_idk", "audio_idk", "audio_idk_reconfirmation") or is_idk_response(response_text))
    )
    if not response_text:
        result["status"] = "no_response"
    elif result["is_disambiguation"]:
        result["status"] = "disambiguation"
    elif result["is_idk"]:
        result["status"] = "idk"
    else:
        result["status"] = "answered"
    return result


def run_one_question_mcp(
    base_url: str,
    question: str,
    phone_number_id: str,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Run one question via MCP asha_chat tool; return same result shape as run_one_question."""
    result = {
        "question": question,
        "response_text": "",
        "is_idk": False,
        "is_disambiguation": False,
        "message_category": None,
        "status": "unknown",
        "error": None,
    }
    mcp_url = base_url.rstrip("/") + "/mcp?phone_number=" + str(phone_number_id)

    async def _call_mcp() -> Dict[str, Any]:
        from fastmcp import Client
        async with Client(mcp_url) as client:
            r = await client.call_tool("asha_chat", {"message": question})
            return r

    async def _run_with_timeout():
        return await asyncio.wait_for(_call_mcp(), timeout=timeout)

    try:
        r = asyncio.run(_run_with_timeout())
    except asyncio.TimeoutError:
        result["status"] = "mcp_error"
        result["error"] = f"MCP call timed out after {timeout}s"
        return result
    except Exception as e:
        result["status"] = "mcp_error"
        result["error"] = str(e)
        return result

    data = r.data if hasattr(r, "data") else r
    if isinstance(data, dict):
        category = data.get("category")
        response_text = data.get("text") or ""
    else:
        category = getattr(data, "category", None)
        response_text = getattr(data, "text", "") or ""

    result["response_text"] = (response_text or "")[:2000]
    result["message_category"] = category
    result["is_disambiguation"] = category in DISAMBIGUATION_CATEGORIES or is_disambiguation_response(response_text, category)
    result["is_idk"] = (
        not result["is_disambiguation"]
        and (category in ("text_idk", "audio_idk", "audio_idk_reconfirmation") or is_idk_response(response_text))
    )
    if not response_text:
        result["status"] = "no_response"
    elif result["is_disambiguation"]:
        result["status"] = "disambiguation"
    elif result["is_idk"]:
        result["status"] = "idk"
    else:
        result["status"] = "answered"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run release QA benchmark: curated positive/negative questions, report metrics (always exit 0)."
    )
    parser.add_argument(
        "--set-path",
        type=Path,
        default=DEFAULT_SET_PATH,
        help=f"Path to benchmark JSON (default: {DEFAULT_SET_PATH})",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("RECIEVE_URL", DEFAULT_BASE_URL).replace("/receive", "").rstrip("/") or DEFAULT_BASE_URL,
        help="Base URL (e.g. http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--phone",
        default=os.getenv("PHONE_NUMBER_ID", DEFAULT_PHONE_NUMBER_ID),
        help="Phone number ID for test user",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Write results to JSON (optional; can include timestamp in filename)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between questions (default: 1.0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of questions to run (default: all)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print final summary, not per-question progress",
    )
    parser.add_argument(
        "--show-responses",
        action="store_true",
        help="Print a snippet of the bot response after each question (to verify evaluation)",
    )
    parser.add_argument(
        "--use-mcp",
        action="store_true",
        help="Use MCP asha_chat tool instead of /receive + get_bot_messages",
    )
    parser.add_argument(
        "--mcp-timeout",
        type=int,
        default=90,
        help="Timeout in seconds for each MCP call when using --use-mcp (default: 90)",
    )
    args = parser.parse_args()

    base_url = args.base_url
    if not base_url.startswith("http"):
        base_url = "http://" + base_url
    if base_url.endswith("/receive"):
        base_url = base_url.replace("/receive", "").rstrip("/")

    if not args.set_path.is_file():
        print(f"Benchmark set not found: {args.set_path}", file=sys.stderr)
        return 0  # still exit 0 per plan

    try:
        items = load_benchmark_set(args.set_path)
    except Exception as e:
        print(f"Failed to load benchmark set: {e}", file=sys.stderr)
        return 0

    if args.limit:
        items = items[: args.limit]

    positive_items = [x for x in items if x["expected"] == "answered"]
    negative_items = [x for x in items if x["expected"] == "idk"]

    base_normalized = base_url.rstrip("/")
    receive_url = base_normalized + "/receive" if not base_normalized.endswith("/receive") else base_normalized

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    mode = "MCP (asha_chat)" if args.use_mcp else "Receive (/receive + get_bot_messages)"
    if not args.quiet:
        print(f"Release QA Benchmark — {date_str}")
        print(f"Mode:        {mode}")
        print(f"Loaded {len(items)} items ({len(positive_items)} positive, {len(negative_items)} negative)")
        print(f"Base URL:    {base_url}")
        if not args.use_mcp:
            print(f"Receive URL: {receive_url}")
        print(f"PHONE_NUMBER_ID: {args.phone}")
        print(f"User name:   {USER_NAME}")
        db_conn = os.getenv("MONGO_DB_CONNECTION_STRING")
        print(f"Database (MONGO_DB_CONNECTION_STRING): {mask_mongo_connection_string(db_conn)}")
        print()

    results: List[Dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        q = item["question"]
        expected = item["expected"]
        if not args.quiet:
            print(f"[{i}/{len(items)}] {q[:70]}{'...' if len(q) > 70 else ''}")
        res = (
            run_one_question_mcp(base_url, q, args.phone, timeout=args.mcp_timeout)
            if args.use_mcp
            else run_one_question(base_url, q, args.phone)
        )
        res["expected"] = expected
        res["category"] = item.get("category", "")
        res["passed"] = (
            (expected == "answered" and res["status"] == "answered")
            or (expected == "idk" and res["status"] in ("idk", "disambiguation"))
        )
        results.append(res)
        if not args.quiet:
            actual = res["status"]
            mark = "✓" if res["passed"] else "✗"
            print(f"  -> {mark} expected={expected}, actual={actual}")
            if args.show_responses or args.use_mcp:
                print(f"     Bot: {snippet(res.get('response_text') or '')}")
        if i < len(items):
            time.sleep(args.delay)

    # Benchmark metrics
    pos_results = [r for r in results if r["expected"] == "answered"]
    neg_results = [r for r in results if r["expected"] == "idk"]
    pos_passed = sum(1 for r in pos_results if r["passed"])
    neg_passed = sum(1 for r in neg_results if r["passed"])
    pos_total = len(pos_results)
    neg_total = len(neg_results)
    pos_pct = (100.0 * pos_passed / pos_total) if pos_total else 0.0
    neg_pct = (100.0 * neg_passed / neg_total) if neg_total else 0.0
    disambiguation_count = sum(1 for r in results if r.get("status") == "disambiguation")

    # Summary
    print()
    print("---------------------------------")
    print(f"Positive (expected answered):  {pos_passed}/{pos_total} ({pos_pct:.1f}%)")
    for r in pos_results:
        if not r["passed"]:
            reason = r["status"]
            q_display = r["question"][:60] + "..." if len(r["question"]) > 60 else r["question"]
            print(f"  Mismatch: \"{q_display}\" -> got {reason}")
            print(f"    Bot: {snippet(r.get('response_text') or '')}")
    print(f"Negative (expected IDK):       {neg_passed}/{neg_total} ({neg_pct:.1f}%)")
    for r in neg_results:
        if not r["passed"]:
            q_display = r["question"][:60] + "..." if len(r["question"]) > 60 else r["question"]
            print(f"  Answered: \"{q_display}\"")
            print(f"    Bot: {snippet(r.get('response_text') or '')}")
    if disambiguation_count:
        print(f"Disambiguation (not full answer): {disambiguation_count} question(s)")
    print("---------------------------------")
    print("Run again after the next release and compare metrics to gauge progress.")
    print("Do not use this script in CI to fail the build.")
    print()

    # Optional JSON output
    if args.output:
        out_path = args.output
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "base_url": base_url,
            "mode": "mcp" if args.use_mcp else "receive",
            "summary": {
                "total": len(results),
                "positive_total": pos_total,
                "positive_passed": pos_passed,
                "positive_pct": round(pos_pct, 2),
                "negative_total": neg_total,
                "negative_passed": neg_passed,
                "negative_pct": round(neg_pct, 2),
                "disambiguation_count": disambiguation_count,
            },
            "results": [
                {
                    "question": r["question"],
                    "expected": r["expected"],
                    "category": r.get("category", ""),
                    "actual_status": r["status"],
                    "message_category": r.get("message_category"),
                    "is_disambiguation": r.get("is_disambiguation", False),
                    "passed": r["passed"],
                    "response_text": (r.get("response_text") or "")[:2000],
                }
                for r in results
            ],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        if not args.quiet:
            print(f"Results written to {out_path}")

    # Always exit 0 (benchmark only; do not fail CI)
    return 0


if __name__ == "__main__":
    sys.exit(main())
