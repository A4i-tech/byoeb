"""
Release QA benchmark: run curated positive/negative questions against the bot
and report metrics for qualitative release comparison.

This script is for manual benchmarking only. Do NOT use it in GitHub Actions or
any CI pipeline to fail the build. It always exits 0.

Usage:
  From byoeb-v1/byoeb:
    poetry run python tests/integration/run_release_qa_benchmark.py
    poetry run python tests/integration/run_release_qa_benchmark.py --base-url http://127.0.0.1:8000
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
from typing import Any, Dict, List, Optional, Tuple, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError, field_validator

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


class BenchmarkItem(BaseModel):
    question: str
    expected: Literal["answered", "idk"]
    category: str = ""

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip()


def load_benchmark_set(path: Path) -> List[Dict[str, Any]]:
    """Load benchmark set from JSON and validate using pydantic."""
    try:
        items = TypeAdapter(list[BenchmarkItem]).validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise ValueError(f"Benchmark set is invalid: {e}") from e
    return [item.model_dump() for item in items]


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
        "--timeout",
        type=int,
        default=90,
        help="Timeout in seconds for each MCP call (default: 90)",
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

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    mode = "MCP (asha_chat)"
    if not args.quiet:
        print(f"Release QA Benchmark — {date_str}")
        print(f"Mode:        {mode}")
        print(f"Loaded {len(items)} items ({len(positive_items)} positive, {len(negative_items)} negative)")
        print(f"Base URL:    {base_url}")
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
        res = run_one_question_mcp(base_url, q, args.phone, timeout=args.timeout)
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
            if args.show_responses or True:
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
            "mode": "mcp",
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
