"""
Export Q&A pairs for human validation (Issue #228).

Goal: get the top 5000 *worst* Q&A pairs (by LLM score) for human review.

Pipeline:
  1. Fetch bot_to_asha_response (exclude empty, IDK, small_talk), optional time range.
  2. Randomly sample up to --sample-size pairs (default 5000) for cost control.
  3. LLM scores each (completeness, factual_accuracy, relevance); cumulative = sum.
  4. Sort by cumulative_score ascending (worst first), take --worst-n (default 5000).
  5. Export to Excel/CSV.

End goal: score ALL Q&A pairs and output the worst 5000. Use --score-all to skip
sampling and score every fetched pair (higher LLM cost).

The LLM judge is calibrated to be fair: direct factual answers score highly (8-10) even
if they don't include broader context. Use --use-web-search to get citations/links for
low-scoring pairs (DuckDuckGo, no API key required; pip install ddgs).

Usage:
  Quick export (no LLM, limit 50):
    python -m byoeb.scripts.export_validation_dump --limit 50 --no-llm -o test.xlsx
  Score ALL pairs, output worst 5000 (full pipeline for end goal):
    python -m byoeb.scripts.export_validation_dump --score-all --worst-n 5000 -o worst_5k.xlsx
  With web search citations for low scores (free, no API key):
    python -m byoeb.scripts.export_validation_dump --score-all --worst-n 5000 --use-web-search -o worst_5k.xlsx

Requires: MONGO_DB_CONNECTION_STRING (or app config), AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY for LLM.
Optional: pip install ddgs for --use-web-search citations (no API key).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Optional

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# Optional Langfuse tracing (pip install langfuse). Gracefully disabled if not installed or not configured.
try:
    from langfuse import Langfuse
    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False

# Try new package name first (ddgs), fallback to old name (duckduckgo_search) with warning suppression
try:
    from ddgs import DDGS
    HAS_DUCKDUCKGO = True
except ImportError:
    try:
        import warnings
        # Suppress the deprecation warning about package rename
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*duckduckgo_search.*renamed.*ddgs.*", category=RuntimeWarning)
            from duckduckgo_search import DDGS
        HAS_DUCKDUCKGO = True
    except ImportError:
        HAS_DUCKDUCKGO = False

# Ensure byoeb package is on path when run as script
_script_dir = Path(__file__).resolve().parent
_byoeb_root = _script_dir.parent
if str(_byoeb_root) not in sys.path:
    sys.path.insert(0, str(_byoeb_root))

from byoeb.models.message_category import MessageCategory

# Hardcoded default chat deployment for LLM judge (override with --llm-model or AZURE_OPENAI_CHAT_DEPLOYMENT)
DEFAULT_CHAT_DEPLOYMENT = "gpt-4o"
# Default score when LLM fails or returns invalid JSON (so row is not forced into "worst" set)
DEFAULT_FAILURE_SCORE = 30
# Default batch size for scoring multiple pairs per LLM call (reduces API calls and latency)
DEFAULT_BATCH_SIZE = 10
# Default number of parallel workers (concurrent LLM calls). Tune to your Azure OpenAI TPM/RPM quota.
DEFAULT_WORKERS = 8
# Only keep citations for pairs with cumulative_score <= this (low-scoring pairs). Clear citations for high scores.
CITATIONS_ONLY_BELOW_CUMULATIVE = 18
# Azure OpenAI pricing per 1M tokens (gpt-4o approximate)
LLM_COST_INPUT_PER_1M = 2.50
LLM_COST_OUTPUT_PER_1M = 10.0

# Few-shot examples for the judge prompt (good Q&A pairs)
JUDGE_GOOD_EXAMPLES = """
Example of a GOOD pair (score highly on all three dimensions):
Query: "What are the side effects of the Antara injection?"
Answer: "Women receiving the Antara injection may experience changes in menstrual bleeding patterns, such as light or irregular bleeding, or periods may stop after a year. Fertility may take 4-6 months to return after stopping the injection. Other side effects can include weight gain, abdominal discomfort, headaches, mood changes, dizziness, and reduced sex drive."
→ Complete, factually accurate, relevant.

Another GOOD pair (direct factual answer is sufficient - score 8-10):
Query: "What should be the height of a fifteen-month-old girl?"
Answer: "The ideal height for a fifteen-month-old girl is 77.5 cm."
→ Complete (directly answers the question), factually accurate, relevant. Score 8-10. A concise factual answer is sufficient; do NOT penalize for lacking "broader context" like growth variability unless the question explicitly asks for it.
"""


def _is_idk(text: str) -> bool:
    """Match IDK phrases (aligned with byoeb.utils.utils.is_idk)."""
    if not text or not isinstance(text, str):
        return False
    idks = [
        "idk",
        "i don't know",
        "i do not know",
        "i don't know the answer",
        "i do not know the answer to your question",
    ]
    return any(phrase in text.lower() for phrase in idks)


def _get_query_text(entry: dict) -> str:
    """Extract user query (English when available) from message_data."""
    reply_context = entry.get("reply_context") or {}
    additional = reply_context.get("additional_info") or {}
    text = (
        reply_context.get("reply_english_text")
        or additional.get("query_en")
        or reply_context.get("reply_source_text")
    )
    return (text or "").strip()


def _get_response_text(entry: dict) -> str:
    """Extract bot response text from message_data."""
    message_context = entry.get("message_context") or {}
    text = (
        message_context.get("message_english_text")
        or message_context.get("message_source_text")
    )
    return (text or "").strip()


def _get_query_source(entry: dict) -> str:
    """Extract reply_source_text for output column."""
    reply_context = entry.get("reply_context") or {}
    return (reply_context.get("reply_source_text") or "").strip()


def _get_response_source(entry: dict) -> str:
    """Extract message_source_text for output column."""
    message_context = entry.get("message_context") or {}
    return (message_context.get("message_source_text") or "").strip()


def _get_query_type(entry: dict) -> str:
    """Extract query_type from reply_context.additional_info."""
    reply_context = entry.get("reply_context") or {}
    additional = reply_context.get("additional_info") or {}
    qt = additional.get("query_type")
    return str(qt) if qt is not None else ""


def _is_context_lost_query(query: str) -> bool:
    """
    Detect queries where context is clearly lost, e.g. one-word pronouns like "this", "he", "she", "that".
    These are not useful for human validation on their own and should be excluded.
    """
    if not query or not isinstance(query, str):
        return False
    # Normalize: lowercase, strip whitespace and common surrounding punctuation/quotes
    normalized = query.strip().lower().strip(" \"'“”‘’.,!?-")
    if not normalized:
        return False
    # Only treat it as context-lost if it is exactly one of these pronouns/demonstratives
    context_lost_tokens = {"this", "he", "she", "that"}
    return normalized in context_lost_tokens


def _normalize_source_for_dedup(query_source: str) -> str:
    """
    Normalize source-language query for duplicate detection.
    Goal: treat minor differences like extra spaces or trailing punctuation
    ("?", "।", "!", ".", ",") as the same query.
    """
    if not query_source or not isinstance(query_source, str):
        return ""
    s = query_source.strip().lower()
    # Collapse internal whitespace
    s = " ".join(s.split())
    # Strip common trailing punctuation characters repeatedly
    trailing_punct = "?.!।,؛"
    while s and s[-1] in trailing_punct:
        s = s[:-1].rstrip()
    return s


def _filter_rows_for_validation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Apply post-processing filters before exporting for human validation:
      1. Drop rows where the English query has clearly lost context (e.g. just "this", "he", "she", "that").
      2. Drop duplicate queries in the source language based on normalized query_source
         (ignoring extra spaces and trailing punctuation), keeping the first occurrence.
    """
    if not rows:
        return rows

    # Step 1: filter context-lost queries
    filtered_rows: list[dict[str, Any]] = []
    context_lost_count = 0
    for row in rows:
        q = (row.get("query") or "").strip()
        if _is_context_lost_query(q):
            context_lost_count += 1
            continue
        filtered_rows.append(row)

    # Step 2: remove duplicates on normalized query_source (source language query)
    deduped_rows: list[dict[str, Any]] = []
    seen_query_sources: set[str] = set()
    duplicate_source_count = 0
    for row in filtered_rows:
        raw_qs = (row.get("query_source") or "").strip()
        norm_qs = _normalize_source_for_dedup(raw_qs)
        if norm_qs:
            if norm_qs in seen_query_sources:
                duplicate_source_count += 1
                continue
            seen_query_sources.add(norm_qs)
        deduped_rows.append(row)

    removed_total = context_lost_count + duplicate_source_count
    if removed_total:
        print(
            f"Post-filtering removed {removed_total} rows "
            f"({context_lost_count} context-lost queries, "
            f"{duplicate_source_count} duplicate source-language queries).",
            file=sys.stderr,
        )
    return deduped_rows


def _parse_date_or_timestamp(value: str) -> tuple[float, float]:
    """Parse --start or --end as YYYY-MM-DD (IST day boundaries) or Unix timestamp. Returns (start_ts, end_ts) for a single day or single timestamp."""
    try:
        # Try numeric Unix timestamp first
        ts = float(value)
        return (ts, ts)
    except ValueError:
        pass
    # Assume YYYY-MM-DD
    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    dt = datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=IST)
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=23, minute=59, second=59, microsecond=999_999)
    return (start.timestamp(), end.timestamp())


def _build_timestamp_range(start_arg: Optional[str], end_arg: Optional[str]) -> Optional[tuple[str, str]]:
    """Build (start_ts_str, end_ts_str) for MongoDB timestamp filter (string in asha_logs). Returns None if no range."""
    if not start_arg and not end_arg:
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    if start_arg and end_arg:
        try:
            start_dt = datetime.strptime(start_arg.strip(), "%Y-%m-%d").replace(tzinfo=IST).replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = datetime.strptime(end_arg.strip(), "%Y-%m-%d").replace(tzinfo=IST).replace(hour=23, minute=59, second=59, microsecond=999_999)
            start_ts = start_dt.timestamp()
            end_ts = end_dt.timestamp()
        except ValueError:
            start_ts = float(start_arg)
            end_ts = float(end_arg)
    elif start_arg:
        start_ts, _ = _parse_date_or_timestamp(start_arg)
        end_ts = 9999999999.0
    else:
        _, end_ts = _parse_date_or_timestamp(end_arg)
        start_ts = 0.0
    return (str(int(start_ts)), str(int(end_ts)))


async def fetch_validation_pairs(
    message_collection,
    start_arg: Optional[str] = None,
    end_arg: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Fetch bot_to_asha_response messages, extract Q&A and required columns.
    Exclude empty query/response and IDK responses. Return list of row dicts.
    """
    query: dict[str, Any] = {
        "message_data.message_category": MessageCategory.BOT_TO_USER_RESPONSE.value
    }
    ts_range = _build_timestamp_range(start_arg, end_arg)
    if ts_range:
        start_ts_str, end_ts_str = ts_range
        query["timestamp"] = {"$gte": start_ts_str, "$lte": end_ts_str}

    projection = {
        "_id": 0,
        "message_data.message_context": 1,
        "message_data.reply_context": 1,
        "message_data.incoming_timestamp": 1,
        "message_data.user.user_id": 1,
        "message_data.message_category": 1,
    }
    cursor = message_collection.find(query, projection).sort("message_data.incoming_timestamp", -1).max_time_ms(300_000)  # 5 min server-side timeout
    if limit:
        cursor = cursor.limit(limit)
    rows: list[dict[str, Any]] = []
    # Onboarding-related keywords to exclude.
    # Only filter when the query STARTS with the keyword (i.e. it's a command/intent, not a real health question
    # that merely mentions onboarding in context like "What is HB level for onboard ASHA?")
    ONBOARDING_START_KEYWORDS = [
        "onboard asha", "onboard-asha", "onboardasha",
        "onboard anm", "onboard-anm",
        "register asha", "register anm",
    ]

    def _is_onboarding_query(text: str) -> bool:
        lower = text.lower().strip()
        # Strip trailing punctuation/parenthetical so "Onboard ASHA (Accredited...)" still matches
        core = lower.split("(")[0].rstrip(" .,!?-").strip()
        return any(core == kw or core.startswith(kw + " ") or core.startswith(kw + ",") or core.startswith(kw + "-") for kw in ONBOARDING_START_KEYWORDS)

    skipped_empty = 0
    skipped_idk = 0
    skipped_small_talk = 0
    skipped_onboarding = 0
    async for doc in cursor:
        md = doc.get("message_data", {})
        query_text = _get_query_text(md)
        response_text = _get_response_text(md)
        if not query_text or not response_text:
            skipped_empty += 1
            continue
        if _is_idk(response_text):
            skipped_idk += 1
            continue
        query_type = _get_query_type(md)
        if query_type == "small_talk":
            skipped_small_talk += 1
            continue
        if _is_onboarding_query(query_text):
            skipped_onboarding += 1
            continue
        rows.append({
            "query": query_text,
            "response": response_text,
            "query_source": _get_query_source(md),
            "response_source": _get_response_source(md),
            "incoming_timestamp": md.get("incoming_timestamp"),
            "user_id": (md.get("user") or {}).get("user_id"),
            "query_type": query_type,
        })
    print(f"Fetched {len(rows)} Q&A pairs (skipped {skipped_empty} empty, {skipped_idk} IDK, {skipped_small_talk} small_talk, {skipped_onboarding} onboarding).", file=sys.stderr)
    return rows


def sample_rows(rows: list[dict], sample_size: int, seed: Optional[int]) -> list[dict]:
    """Return random sample of size sample_size (or all if fewer). Reproducible if seed is set."""
    if len(rows) <= sample_size:
        return rows
    rng = random.Random(seed)
    return rng.sample(rows, sample_size)


def _get_chat_deployment(args: argparse.Namespace) -> str:
    """Resolve chat deployment: --llm-model > env > hardcoded default."""
    return (
        (args.llm_model or "")
        or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or DEFAULT_CHAT_DEPLOYMENT
    )


async def _score_batch(client: Any, deployment: str, pairs: list[tuple[str, str]], use_web_search: bool = False) -> tuple[list[dict[str, Any]], int, int]:
    """
    Score multiple Q&A pairs in one LLM call with optional web search tool.
    Returns (list of score_dicts, prompt_tokens, completion_tokens).
    Each score_dict has completeness, factual_accuracy, relevance, cumulative_score, reason, citations.
    """
    pairs_text = "\n\n".join(
        f"Pair {i+1}:\nQuery: {json.dumps(q, ensure_ascii=False)}\nAnswer: {json.dumps(a, ensure_ascii=False)}"
        for i, (q, a) in enumerate(pairs)
    )
    prompt = f"""You are evaluating health-information bot called <asha_bot>. I will be giving question-answer pairs. Score each pair on three dimensions from 1 to 10 (1=worst, 10=best).

<asha_bot>
You are ASHA Saheli, an AI-powered WhatsApp chatbot from Khushi Baby. You help Indian Community Health Workers (ASHAs) by answering their questions about maternal health, child health, vaccinations, and rural health practices.

You provide:
- Instant, accurate responses using your health knowledge base
- Multilingual support (Hindi, Marathi, Telugu, English)
- Simple, easy-to-understand language
- Expert-verified answers when needed

You answer questions about ASHA work, health protocols, vaccination schedules, and maternal/child health. When you don't know something, you escalate to ANM experts for verification.

Your goal: Empower ASHAs with reliable health information to better serve their communities.
</asha_bot>
IMPORTANT: Be fair and practical. A direct, factual answer that correctly addresses the question is COMPLETE and should score highly (8-10). Do NOT penalize answers for lacking "broader context" unless the question explicitly asks for it. For example, if asked "What is the height of a 15-month-old girl?", the answer "77.5 cm" is complete and correct—you don't need to mention growth variability unless the question asks for it.

Criteria:
- Completeness (1-10): Does the answer fully address what the question asks? A direct factual answer is sufficient unless the question explicitly requests broader context, ranges, or additional information.
- Factual accuracy (1-10): Is the answer factually correct based on standard medical/health information?
- Relevance (1-10): Is the answer on-topic and relevant to the question?

{JUDGE_GOOD_EXAMPLES}

Now evaluate these {len(pairs)} pairs:

{pairs_text}

{"IMPORTANT: First, score all pairs and provide your scores in JSON format. Do NOT call web_search in this first response. After scoring, we will identify low-scoring pairs and search for those separately." if use_web_search else ""}

Respond with ONLY a JSON object (no markdown, no extra text) in this exact format:
{{"results": [{{"completeness": <1-10>, "factual_accuracy": <1-10>, "relevance": <1-10>, "reason": "<one-line explanation>", "citations": "", "citation_comment": ""}}, ...]}}
The "results" array must contain exactly {len(pairs)} objects, one per pair in order.
{"Leave citations and citation_comment empty for now. We will add them later for low-scoring pairs." if use_web_search else ""}
"""
    
    # Define web search tool if enabled
    tools = None
    if use_web_search:
        tools = [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for authoritative sources. You MUST call this for pairs you are giving a LOW score (completeness < 6 OR factual_accuracy < 6 OR relevance < 6, or cumulative <= 18) to find what is missing or incorrect. You will receive URLs and text snippets; read them, then add citations and a comment if after reading you still find the answer incomplete or inaccurate. Do NOT call for pairs you score 8-10 on all dimensions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant authoritative sources (e.g., medical guidelines, health information websites)"
                        },
                        "pair_index": {
                            "type": "integer",
                            "description": "Which pair (0-indexed) this search is for, so we can associate results correctly"
                        }
                    },
                    "required": ["query", "pair_index"]
                }
            }
        }]
    
    messages = [{"role": "user", "content": prompt}]
    total_prompt_tokens = 0
    total_completion_tokens = 0

    def _is_rate_limit_error(e: Exception) -> bool:
        err_str = str(e)
        return "429" in err_str or "RateLimit" in err_str or "rate_limit" in err_str.lower()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(max=16),
        retry=retry_if_exception(_is_rate_limit_error),
        before_sleep=lambda rs: print(f"      Rate limit hit, retrying in {rs.next_action.sleep:.0f}s (attempt {rs.attempt_number}/5)...", file=sys.stderr),
        reraise=True,
    )
    async def _call_with_retry(create_kwargs: dict) -> Any:
        return await client.chat.completions.create(**create_kwargs)

    try:
        max_iterations = 5  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            # Don't force JSON format on first iteration if tools are enabled (let LLM decide to use tools)
            # But force JSON on final iteration
            create_kwargs = {
                "model": deployment,
                "messages": messages,
            }
            # Phase 1: Score first without tools (if first iteration and web_search enabled)
            # Phase 2: Then search for low-scoring pairs
            if use_web_search and iteration == 1:
                # First iteration: score without tools, force JSON
                print(f"      Phase 1: Scoring {len(pairs)} pairs (iteration {iteration})...", file=sys.stderr)
                create_kwargs["response_format"] = {"type": "json_object"}
            elif use_web_search and iteration > 1:
                # Later iterations: enable tools for web search
                print(f"      Phase 2: Web search for low-scoring pairs (iteration {iteration})...", file=sys.stderr)
                create_kwargs["tools"] = tools
                create_kwargs["tool_choice"] = "auto"
                create_kwargs["response_format"] = {"type": "json_object"}
            else:
                create_kwargs["response_format"] = {"type": "json_object"}
            
            resp = await _call_with_retry(create_kwargs)
            
            usage = resp.usage
            total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            
            message = resp.choices[0].message
            
            # Check if LLM wants to call a function
            if message.tool_calls and use_web_search:
                # Add assistant message with tool calls
                messages.append(message)
                
                # Execute tool calls
                tool_results = []
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "web_search":
                        func_args: dict[str, Any] = {}
                        try:
                            func_args = json.loads(tool_call.function.arguments)
                            search_query = func_args.get("query", "")
                            pair_index = func_args.get("pair_index", 0)
                            search_result = _execute_web_search(search_query)
                            num_snippets = len(search_result.get("results", []))
                            num_urls = len(search_result.get("urls", []))
                            if search_result.get("error"):
                                print(f"    Web search for pair {pair_index}: error - {search_result.get('error')}", file=sys.stderr)
                            else:
                                print(f"    Web search for pair {pair_index}: found {num_urls} URLs, {num_snippets} snippets", file=sys.stderr)
                            tool_results.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": "web_search",
                                "content": json.dumps({
                                    "pair_index": pair_index,
                                    "urls": search_result.get("urls", []),
                                    "snippets": search_result.get("results", []),
                                    "error": search_result.get("error"),
                                }, ensure_ascii=False)
                            })
                        except Exception as e:
                            print(f"    Web search error for pair {func_args.get('pair_index', 'unknown')}: {str(e)[:100]}", file=sys.stderr)
                            tool_results.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": "web_search",
                                "content": json.dumps({"pair_index": func_args.get("pair_index", 0), "urls": [], "snippets": [], "error": str(e)})
                            })
                
                # Add tool results to messages
                messages.extend(tool_results)
                # Follow-up: read snippets, then add citations + comment based on what was read
                messages.append({
                    "role": "user",
                    "content": "You received web search results with URLs and text snippets for the pairs you searched. CRITICAL: Read each snippet carefully. For each pair where you searched (low-scoring pairs):\n1. Based on what you read in the snippets, determine what is missing or incorrect in the bot's answer.\n2. Add the relevant URLs to 'citations' (semicolon-separated).\n3. Write 'citation_comment' describing what is missing or incorrect, specifically referencing what you learned from the snippets (e.g. 'Missing: X according to source; source states Y instead of Z').\n\nIf the snippets confirm the bot answer is actually correct, note that in citation_comment but still include citations.\n\nNow provide your final evaluation as a JSON object with scores, reason, citations (for low-scoring pairs where you searched), and citation_comment (required whenever you add citations; must reference what you learned from the snippets)."
                })
                continue  # Continue conversation to get final response
            
            # Final response - parse JSON
            content = message.content
            if not content:
                raise ValueError("Empty response from LLM")
            
            data = json.loads(content)
            if not isinstance(data, dict) or "results" not in data:
                raise ValueError(f"Expected {{'results': [...]}}, got {type(data)}")
            
            results = data["results"]
            if len(results) != len(pairs):
                raise ValueError(f"Expected {len(pairs)} scores, got {len(results)}")
            
            # Phase 1 complete: We have scores. Now check if we need web search for low-scoring pairs
            low_score_pairs_needing_search = []
            for idx, r in enumerate(results):
                c = int(r.get("completeness", 5))
                f = int(r.get("factual_accuracy", 5))
                rel = int(r.get("relevance", 5))
                cumulative = c + f + rel
                citations = (r.get("citations") or "").strip()
                any_low = c < 6 or f < 6 or rel < 6
                if use_web_search and (any_low or cumulative <= CITATIONS_ONLY_BELOW_CUMULATIVE) and not citations:
                    low_score_pairs_needing_search.append((idx, pairs[idx], cumulative, r))
            
            # Phase 2: If there are low-scoring pairs, search for them
            if low_score_pairs_needing_search and use_web_search and iteration == 1:
                print(f"      Phase 1 complete: Scored all {len(pairs)} pairs. Found {len(low_score_pairs_needing_search)} low-scoring pairs (any dimension < 6 or cumulative <= {CITATIONS_ONLY_BELOW_CUMULATIVE}). Starting Phase 2: web search...", file=sys.stderr)
                # Add the current response as Phase 1 scores
                messages.append(message)
                # Create a prompt asking to search for these specific pairs, preserving their scores
                search_prompt_parts = []
                for idx, (q, a), cum_score, score_dict in low_score_pairs_needing_search:
                    search_prompt_parts.append(f"Pair {idx+1} (scores: completeness={score_dict.get('completeness')}, factual_accuracy={score_dict.get('factual_accuracy')}, relevance={score_dict.get('relevance')}, cumulative={cum_score}): Query: {json.dumps(q, ensure_ascii=False)[:150]}... Answer: {json.dumps(a, ensure_ascii=False)[:150]}...")
                messages.append({
                    "role": "user",
                    "content": f"Phase 1 complete: You scored all {len(pairs)} pairs. Now Phase 2: These {len(low_score_pairs_needing_search)} pairs have LOW scores (any dimension < 6 or cumulative <= {CITATIONS_ONLY_BELOW_CUMULATIVE}). You MUST call web_search for each of these pairs. Keep the same scores you already assigned, but add citations and citation_comment after reading the search results.\n\n" + "\n\n".join(search_prompt_parts) + f"\n\nCall web_search for these pairs, then provide your final JSON with the SAME scores but WITH citations and citation_comment for these low-scoring pairs."
                })
                continue  # Go back to get tool calls (Phase 2)
            
            score_dicts = []
            for idx, r in enumerate(results):
                c = int(r.get("completeness", 5))
                f = int(r.get("factual_accuracy", 5))
                rel = int(r.get("relevance", 5))
                c = max(1, min(10, c))
                f = max(1, min(10, f))
                rel = max(1, min(10, rel))
                cumulative = c + f + rel
                citations = (r.get("citations") or "").strip()
                citation_comment = (r.get("citation_comment") or "").strip()
                # Warn if low-scoring pair has no citations (when web search is enabled)
                any_low = c < 6 or f < 6 or rel < 6
                if use_web_search and (any_low or cumulative <= CITATIONS_ONLY_BELOW_CUMULATIVE) and not citations:
                    print(f"    WARNING: Pair {idx} has low score ({cumulative}) but no citations.", file=sys.stderr)
                score_dicts.append({
                    "completeness": c,
                    "factual_accuracy": f,
                    "relevance": rel,
                    "cumulative_score": cumulative,
                    "reason": (r.get("reason") or "").strip() or "No reason provided",
                    "citations": citations,
                    "citation_comment": citation_comment,
                })
            return (score_dicts, total_prompt_tokens, total_completion_tokens)
        
        # If we exit loop without returning, something went wrong
        raise ValueError(f"Exceeded max iterations ({max_iterations}) without final response")
        
    except Exception as e:
        # On failure, return default scores for all pairs in batch
        return (
            [{
                "completeness": 10,
                "factual_accuracy": 10,
                "relevance": 10,
                "cumulative_score": DEFAULT_FAILURE_SCORE,
                "reason": f"LLM failure: {str(e)[:50]}",
                "citations": "",
                "citation_comment": "",
            }] * len(pairs),
            total_prompt_tokens,
            total_completion_tokens,
        )



def _execute_web_search(search_query: str) -> dict[str, Any]:
    """
    Execute web search via DuckDuckGo (no API key). Returns dict with 'results' (list of {url, title, snippet}),
    'urls' (for backward compatibility), and 'error' if failed. Snippets let the LLM read the content.
    """
    if not HAS_DUCKDUCKGO:
        return {"urls": [], "results": [], "error": "Web search requires 'ddgs' or 'duckduckgo-search' (pip install ddgs)"}
    try:
        # DuckDuckGo text search: results have "href", "title", "body" (snippet)
        raw = list(DDGS().text(search_query, max_results=5))
        if not raw:
            return {"urls": [], "results": [], "error": "No web results found"}
        urls = []
        results = []
        for r in raw[:5]:
            u = r.get("href") or r.get("url")
            if not u or not isinstance(u, str) or not u.startswith("http"):
                continue
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            snippet = (title + ": " + body) if title and body else (body or title or "(no snippet)")
            urls.append(u)
            results.append({"url": u, "title": title, "snippet": snippet[:500]})  # cap snippet length
        return {"urls": urls, "results": results, "error": None}
    except Exception as e:
        return {"urls": [], "results": [], "error": f"Web search error: {str(e)[:80]}"}





def _langfuse_trace_batch(lf: Any, deployment: str, pairs: list[tuple[str, str]], score_dicts: list[dict]) -> None:
    """
    Send per-pair generation observations + scores to Langfuse.
    Our custom LLM judge already ran; this is tracing only.
    Each pair gets its own trace so it appears as a separate observation in Langfuse.
    """
    if lf is None:
        return
    try:
        for idx, ((query, response), score_dict) in enumerate(zip(pairs, score_dicts)):
            pair_trace_id = lf.create_trace_id()
            # Generation observation: input = query, output = bot response
            with lf.start_as_current_observation(
                as_type="generation",
                name="qa_pair_scoring",
                trace_context={"trace_id": pair_trace_id},
                model=deployment,
                input={"query": query},
                output=response,
                metadata={
                    "pair_index": idx,
                    "cumulative_score": score_dict.get("cumulative_score"),
                    "reason": score_dict.get("reason", ""),
                },
            ):
                pass  # observation closes automatically on exit
            # Log individual dimension scores to the trace
            c = score_dict.get("completeness", 0)
            f = score_dict.get("factual_accuracy", 0)
            rel = score_dict.get("relevance", 0)
            reason = score_dict.get("reason", "")
            lf.create_score(trace_id=pair_trace_id, name="completeness", value=c, data_type="NUMERIC", comment=reason)
            lf.create_score(trace_id=pair_trace_id, name="factual_accuracy", value=f, data_type="NUMERIC", comment=reason)
            lf.create_score(trace_id=pair_trace_id, name="relevance", value=rel, data_type="NUMERIC", comment=reason)
            lf.create_score(trace_id=pair_trace_id, name="cumulative_score", value=c + f + rel, data_type="NUMERIC", comment=reason)
        lf.flush()
    except Exception as e:
        print(f"    Langfuse trace error (non-fatal): {str(e)[:80]}", file=sys.stderr)


async def run_llm_judge(rows: list[dict], deployment: str, args: argparse.Namespace) -> list[dict]:
    """Score each row with LLM (async batched) and add score columns."""
    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        print("openai package not installed; skipping LLM judge. Use --no-llm to export without scoring.", file=sys.stderr)
        return rows
    api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not api_key or not endpoint:
        print("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT required for LLM judge. Use --no-llm to export without scoring.", file=sys.stderr)
        return rows

    import time

    client = AsyncAzureOpenAI(
        api_key=api_key,
        api_version=os.environ.get("OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=endpoint,
    )
    lf = Langfuse() if HAS_LANGFUSE else None
    if lf:
        host = os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        print(f"  Langfuse tracing enabled. Traces will appear at {host}", file=sys.stderr)

    total = len(rows)
    batch_size = args.batch_size
    concurrency = args.workers
    num_batches = (total + batch_size - 1) // batch_size
    print(f"  Scoring {total} pairs with LLM (deployment={deployment}, batch_size={batch_size}, concurrency={concurrency}, {num_batches} batches).", file=sys.stderr)

    use_web_search = args.use_web_search
    if use_web_search and not HAS_DUCKDUCKGO:
        print("  WARNING: --use-web-search enabled but 'ddgs' not installed (pip install ddgs). Web search disabled.", file=sys.stderr)
        use_web_search = False

    # Build all batches upfront
    batches = []
    for batch_idx in range(0, total, batch_size):
        batch = rows[batch_idx:batch_idx + batch_size]
        pairs = [(row["query"], row["response"]) for row in batch]
        batches.append((batch_idx, batch, pairs))

    failed = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    completed_count = 0
    t0 = time.perf_counter()
    log_interval = max(1, num_batches // 100)

    # Semaphore limits concurrent in-flight requests (rate limit friendly)
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_one_batch(batch_idx: int, batch: list, pairs: list) -> tuple:
        current_batch = (batch_idx // batch_size) + 1
        print(f"  [async] Starting batch {current_batch}/{num_batches} ({len(pairs)} pairs)...", file=sys.stderr)
        async with semaphore:
            score_dicts, pt, ct = await _score_batch(client, deployment, pairs, use_web_search=use_web_search)
        return (current_batch, batch_idx, batch, pairs, score_dicts, pt, ct)

    # Launch all batches concurrently; semaphore keeps in-flight count bounded
    tasks = [_process_one_batch(bi, b, p) for bi, b, p in batches]
    for coro in asyncio.as_completed(tasks):
        try:
            current_batch, batch_idx, batch, pairs, score_dicts, pt, ct = await coro
        except Exception as exc:
            score_dicts = [{
                "completeness": 10, "factual_accuracy": 10, "relevance": 10,
                "cumulative_score": DEFAULT_FAILURE_SCORE,
                "reason": f"LLM failure: {str(exc)[:50]}",
                "citations": "", "citation_comment": "",
            }]
            batch, pairs, pt, ct = [], [], 0, 0
            print(f"  ERROR: {exc}", file=sys.stderr)

        total_prompt_tokens += pt
        total_completion_tokens += ct
        completed_count += 1
        done = completed_count

        for row, score_dict in zip(batch, score_dicts):
            if score_dict.get("reason", "").startswith("LLM failure"):
                failed += 1
            row["completeness"] = score_dict["completeness"]
            row["factual_accuracy"] = score_dict["factual_accuracy"]
            row["relevance"] = score_dict["relevance"]
            row["cumulative_score"] = score_dict["cumulative_score"]
            row["reason"] = score_dict.get("reason", "")
            row["citations"] = score_dict.get("citations", "")
            row["citation_comment"] = score_dict.get("citation_comment", "")
            c, f, r = row.get("completeness", 10), row.get("factual_accuracy", 10), row.get("relevance", 10)
            all_high = c >= 6 and f >= 6 and r >= 6
            if use_web_search and all_high and row.get("cumulative_score", 0) > CITATIONS_ONLY_BELOW_CUMULATIVE:
                row["citations"] = ""
                row["citation_comment"] = ""

        _langfuse_trace_batch(lf, deployment, pairs, score_dicts)

        elapsed = time.perf_counter() - t0
        scored_so_far = min(done * batch_size, total)
        rate = scored_so_far / elapsed if elapsed > 0 else 0
        eta = (total - scored_so_far) / rate if rate > 0 else 0
        if done % log_interval == 0 or done == num_batches:
            print(f"  Batch {done}/{num_batches} done | {scored_so_far}/{total} pairs | {elapsed:.1f}s elapsed | ~{rate:.1f} pairs/s | ETA ~{eta/60:.1f}min", file=sys.stderr)
    elapsed_total = time.perf_counter() - t0
    total_tokens = total_prompt_tokens + total_completion_tokens
    cost_input = (total_prompt_tokens / 1_000_000) * LLM_COST_INPUT_PER_1M
    cost_output = (total_completion_tokens / 1_000_000) * LLM_COST_OUTPUT_PER_1M
    cost_total = cost_input + cost_output
    print(f"  Done. Scored {total} pairs in {elapsed_total:.1f}s. Failed: {failed}.", file=sys.stderr)
    print(f"  Cost: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion = {total_tokens:,} total tokens.", file=sys.stderr)
    print(f"  Estimated cost: ${cost_input:.4f} (input) + ${cost_output:.4f} (output) = ${cost_total:.4f} total.", file=sys.stderr)
    if use_web_search:
        pairs_with_citations = sum(1 for row in rows if row.get("citations", "").strip())
        print(f"  Web search: {pairs_with_citations}/{total} pairs have citations.", file=sys.stderr)
    if lf:
        try:
            lf.flush()
        except Exception:
            pass
    
    return rows


def apply_worst_n(rows: list[dict], worst_n: int, used_llm: bool) -> list[dict]:
    """Sort by cumulative_score ascending (worst first) and take worst_n. If no LLM, return as-is."""
    if not used_llm or not rows:
        return rows
    key = "cumulative_score"
    if key not in rows[0]:
        return rows
    sorted_rows = sorted(rows, key=lambda r: r[key])
    return sorted_rows[:worst_n]


async def main_async(args: argparse.Namespace) -> None:
    from byoeb.chat_app.configuration.config import app_config
    from byoeb.factory.mongo_db import MongoDBFactory, Scope

    db_provider = app_config["app"]["db_provider"]
    message_collection_name = app_config["databases"]["mongo_db"]["message_collection"]
    factory = MongoDBFactory(config=app_config, scope=Scope.SINGLETON.value)
    db = await factory.get(db_provider)
    message_collection = db.get_collection(message_collection_name)

    rows = await fetch_validation_pairs(
        message_collection,
        start_arg=args.start,
        end_arg=args.end,
        limit=args.limit,
    )
    if not rows:
        print("No Q&A pairs found.", file=sys.stderr)
        return

    if args.score_all:
        print(f"Scoring all {len(rows)} pairs (--score-all).", file=sys.stderr)
    else:
        rows = sample_rows(rows, args.sample_size, args.seed)
        print(f"Sampled {len(rows)} pairs for output/LLM.", file=sys.stderr)

    used_llm = not args.no_llm
    if used_llm:
        deployment = _get_chat_deployment(args)
        print(f"Running LLM judge (deployment={deployment})...", file=sys.stderr)
        rows = await run_llm_judge(rows, deployment, args)
        # Apply validation-specific filters before selecting the worst-N so that
        # the final sheet does not contain obvious context-lost queries or
        # exact duplicates in the source language.
        rows = _filter_rows_for_validation(rows)
        rows = apply_worst_n(rows, args.worst_n, used_llm=True)
    else:
        # Even without LLM scoring, still apply the same validation filters.
        rows = _filter_rows_for_validation(rows)
        rows = apply_worst_n(rows, args.worst_n, used_llm=False)

    if len(rows) < args.worst_n:
        # Help the operator satisfy the "~5000 queries" requirement when post-filters
        # remove some rows, by logging a clear hint instead of silently shrinking.
        print(
            f"NOTE: After filtering context-lost and duplicate source-language queries, "
            f"only {len(rows)} rows remain (requested worst-n={args.worst_n}). "
            f"Consider increasing --worst-n and/or --sample-size if you need ~{args.worst_n} rows in the final sheet.",
            file=sys.stderr,
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_columns = ["query", "response", "query_source", "response_source", "incoming_timestamp", "user_id", "query_type"]
    if used_llm and rows and "cumulative_score" in rows[0]:
        base_columns += ["completeness", "factual_accuracy", "relevance", "cumulative_score", "reason", "citations", "citation_comment"]

    import pandas as pd
    df = pd.DataFrame(rows)
    # Ensure column order
    for c in base_columns:
        if c not in df.columns and c in (rows[0] if rows else {}):
            df[c] = [r.get(c) for r in rows]
    df = df[[c for c in base_columns if c in df.columns]]

    if args.format in ("csv", "both"):
        csv_path = out_path.with_suffix(".csv") if args.format == "both" else out_path
        df.to_csv(csv_path, index=False, encoding="utf-8")
        print(f"Wrote {len(df)} rows to {csv_path}")
    if args.format in ("excel", "both"):
        excel_path = out_path.with_suffix(".xlsx") if args.format == "both" else out_path
        df.to_excel(excel_path, index=False, engine="openpyxl")
        print(f"Wrote {len(df)} rows to {excel_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Q&A pairs for human validation (filter, sample, optional LLM judge, Excel/CSV)."
    )
    parser.add_argument("--output", "-o", default="validation_dump.xlsx", help="Output path (default: validation_dump.xlsx)")
    parser.add_argument("--start", type=str, default=None, help="Start of time range (YYYY-MM-DD or Unix timestamp)")
    parser.add_argument("--end", type=str, default=None, help="End of time range (YYYY-MM-DD or Unix timestamp)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sampling")
    parser.add_argument("--limit", type=int, default=None, help="Max pairs to fetch (for testing)")
    parser.add_argument("--score-all", action="store_true", help="Score every fetched pair (no sampling). Use with --worst-n to get true worst 5000 from full DB. Higher LLM cost.")
    parser.add_argument("--sample-size", type=int, default=5000, help="Max random sample size to score (default: 5000). Ignored if --score-all.")
    parser.add_argument("--worst-n", type=int, default=5000, help="After LLM, how many worst-scoring rows to output (default: 5000).")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Number of pairs to score per LLM call (default: {DEFAULT_BATCH_SIZE}). Higher = faster but larger prompts.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Max concurrent async LLM calls (default: {DEFAULT_WORKERS}). Tune to your Azure OpenAI TPM/RPM quota.")
    parser.add_argument("--use-web-search", action="store_true", help="Enable web search for citations on low-scoring pairs (DuckDuckGo, no API key). Requires: pip install ddgs.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM judge; export sampled pairs only")
    parser.add_argument("--llm-model", type=str, default=None, help=f"Azure OpenAI chat deployment (default: {DEFAULT_CHAT_DEPLOYMENT})")
    parser.add_argument("--format", choices=["excel", "csv", "both"], default="excel", help="Output format (default: excel)")
    args = parser.parse_args()

    # Align env with cluster_idk_questions pattern
    if not os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_KEY"):
        os.environ["AZURE_OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_KEY"]
    if not os.environ.get("OPENAI_API_VERSION") and not os.environ.get("AZURE_OPENAI_API_VERSION"):
        os.environ["OPENAI_API_VERSION"] = "2024-02-15-preview"

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
