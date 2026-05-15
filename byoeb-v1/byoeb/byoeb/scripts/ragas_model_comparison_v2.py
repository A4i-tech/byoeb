"""
RAGAS Model Comparison v2 — proper Langfuse Datasets → Runs view
Issue: A4i-tech/.github#184

Key difference from v1:
  Uses item.run(run_name=...) context manager per dataset item.
  This links each trace to the Langfuse Dataset Run, giving a
  side-by-side comparison table under Datasets → ragas-model-comparison-v1 → Runs.
  (v1 used free-floating traces; scores showed in Scores page only, not Runs view.)

RAGAS Model Comparison: gpt-4o-mini vs gpt-4.1-mini

Pipeline:
  1. Load 581 expert-annotated Q&A pairs from "Review Completed" sheet.
  2. For each model (gpt-4o-mini, gpt-4.1-mini):
     a. Retrieve top-k chunks from Azure Search (HYBRID) per question.
     b. Call OpenAI with the same prompt template the bot uses.
     c. Collect (question, answer, contexts, ground_truth).
  3. Run RAGAS metrics: context_precision, context_recall, faithfulness, answer_correctness.
  4. Create Langfuse Dataset + log one run per model.
  5. Print comparison table.

Required env vars (set in keys.env or shell):
  OPENAI_API_KEY                   - OpenAI key for generation
  AZURE_SEARCH_SERVICE_NAME        - e.g. byoebstage-search
  AZURE_SEARCH_INDEX_NAME          - e.g. byoebstage-doc-index-latest
  AZURE_SEARCH_API_KEY             - Azure Cognitive Search admin key
  LANGFUSE_SECRET_KEY              - Langfuse secret key
  LANGFUSE_PUBLIC_KEY              - Langfuse public key

Optional env vars:
  LANGFUSE_HOST                    - defaults to https://cloud.langfuse.com
  RAGAS_MODELS                     - comma-separated models (default: gpt-4o-mini,gpt-4.1-mini,gpt-5-mini)
  RAGAS_DATASET_NAME               - Langfuse dataset name (default: ragas-model-comparison-v1)
  RAGAS_EVAL_LIMIT                 - max IDK rows to evaluate (default: all)
  PROD_SAMPLE_SIZE                 - production rows to sample (default: 500)
  EXCEL_PATH                       - path to annotated xlsx
  PROD_JSON_PATH                   - path to production messages JSON

Usage:
  cd byoeb-v1/byoeb
  python -m byoeb.scripts.ragas_model_comparison
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BYOEB_ROOT = _SCRIPT_DIR.parent

EXCEL_DEFAULT_PATH = Path(os.environ.get(
    "EXCEL_PATH",
    str(Path.home() / "Downloads" / "A4I-ASHABot-IDK.Cleaned (2).xlsx")
))
PROD_JSON_PATH = Path(os.environ.get(
    "PROD_JSON_PATH",
    str(Path.home() / "Downloads" / "ashadb_prod_restored1.ashamessages.json")
))
PROD_SAMPLE_SIZE = int(os.environ.get("PROD_SAMPLE_SIZE", "500"))
EVAL_LIMIT: Optional[int] = int(os.environ["RAGAS_EVAL_LIMIT"]) if os.environ.get("RAGAS_EVAL_LIMIT") else None

# ---------------------------------------------------------------------------
# Credentials — read from environment (no hardcoded values)
# ---------------------------------------------------------------------------
_OPENAI_API_KEY       = os.environ.get("OPENAI_API_KEY", "")
_AZURE_SEARCH_KEY     = os.environ.get("AZURE_SEARCH_API_KEY", "")
_AZURE_SEARCH_SERVICE = os.environ.get("AZURE_SEARCH_SERVICE_NAME", "")
_AZURE_SEARCH_INDEX   = os.environ.get("AZURE_SEARCH_INDEX_NAME", "")
_LANGFUSE_SECRET      = os.environ.get("LANGFUSE_SECRET_KEY", "")
_LANGFUSE_PUBLIC      = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_LANGFUSE_HOST        = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

_models_env = os.environ.get("RAGAS_MODELS", "gpt-4o-mini,gpt-4.1-mini,gpt-5-mini")
MODELS = [m.strip() for m in _models_env.split(",") if m.strip()]

_MODELS_NO_TEMPERATURE = frozenset({"gpt-5-mini", "gpt-5-nano", "gpt-5"})

LANGFUSE_DATASET_NAME = os.environ.get("RAGAS_DATASET_NAME", "ragas-model-comparison-v1")

# ---------------------------------------------------------------------------
# Bot prompt template (from bot_config.json)
# ---------------------------------------------------------------------------
_BOT_CONFIG_PATH = _BYOEB_ROOT / "chat_app" / "bot_config.json"

def _load_bot_config() -> dict:
    with open(_BOT_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def _build_system_prompt(cfg: dict) -> str:
    sp = cfg["llm_response"]["answer_prompts"]["system_prompt"]
    return (
        sp["task_description"]
        + "\n\n"
        + sp["response_generate"]
        + "\n\n"
        + sp["response_translate"]["en"]   # English eval — no translation needed
        + "\n\n"
        + sp["output"]
    )

# ---------------------------------------------------------------------------
# Azure Vector Search — retrieval only (no indexing)
# ---------------------------------------------------------------------------
def _build_vector_store():
    from azure.core.credentials import AzureKeyCredential
    from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore

    service_name = _AZURE_SEARCH_SERVICE
    index_name   = _AZURE_SEARCH_INDEX
    api_key      = _AZURE_SEARCH_KEY

    # Stub embedding function — only used for upsert, not retrieval
    class _StubEmbed:
        async def aget_text_embedding(self, text: str) -> list[float]:
            raise NotImplementedError("Eval script is retrieval-only")

    return AzureVectorStore(
        service_name=service_name,
        index_name=index_name,
        embedding_function=_StubEmbed(),
        credential=AzureKeyCredential(api_key),
    )

async def retrieve_chunks(vector_store, query: str, k: int = 3) -> list[dict]:
    """Retrieve top-k chunks via HYBRID search. Returns list of {text, source, similarity}."""
    from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorSearchType
    chunks = await vector_store.retrieve_top_k_chunks(
        text=query,
        k=k,
        search_type=AzureVectorSearchType.HYBRID.value,
        select=["id", "text", "metadata"],
        vector_field="text_vector_3072",
    )
    return [
        {
            "text": c.text or "",
            "source": (c.metadata.source if c.metadata else None) or "",
            "similarity": c.similarity,
        }
        for c in chunks
    ]

# ---------------------------------------------------------------------------
# Prompt formatting (mirrors generate.py)
# ---------------------------------------------------------------------------
def _chunks_to_kb_topics(chunks: list[dict], is_updated: bool) -> str:
    filtered = [c for c in chunks if ("KB Updated" in c["source"]) == is_updated]
    if not filtered:
        return ""
    return "\n".join(
        f"<chunk_{i}>\n"
        f"<score>{c['similarity']:.2f}</score>\n"
        f"<text>{c['text']}</text>\n"
        f"<search_type>hybrid</search_type>\n"
        f"</chunk_{i}>"
        for i, c in enumerate(filtered)
    )

def _build_user_prompt(cfg: dict, query: str, chunks: list[dict]) -> str:
    template = cfg["llm_response"]["answer_prompts"]["user_prompt"]
    raw_kb = _chunks_to_kb_topics(chunks, is_updated=False)
    new_kb = _chunks_to_kb_topics(chunks, is_updated=True)
    return (
        template
        .replace("<QUERY_TYPE>", "asha_work_related")
        .replace("<QUERY_EN_ADDCONTEXT>", query)
        .replace("<RAW_KB>", raw_kb)
        .replace("<NEW_KB>", new_kb)
    )

def _parse_response(text: str) -> str:
    """Extract <response_en> or <response_idk> from LLM output."""
    idk_match = re.search(r"<response_idk\s*>(.*?)</response_idk\s*>", text, re.DOTALL | re.IGNORECASE)
    if idk_match:
        return idk_match.group(1).strip()
    en_match = re.search(r"<response_en\s*>(.*?)</response_en\s*>", text, re.DOTALL | re.IGNORECASE)
    if en_match:
        return en_match.group(1).strip()
    return text.strip()  # fallback: return raw

# ---------------------------------------------------------------------------
# Model pricing — USD per 1M tokens (matches OpenAI pricing page directly)
# Source: https://openai.com/api/pricing  2026-05-08
# Columns: input / cached_input / output
# ---------------------------------------------------------------------------
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini":       {"input": 0.150,  "cached_input": 0.075,  "output": 0.600},
    "gpt-4.1-mini":      {"input": 0.400,  "cached_input": 0.100,  "output": 1.600},
    "gpt-4.1-nano":      {"input": 0.100,  "cached_input": 0.025,  "output": 0.400},
    "gpt-5-mini":        {"input": 0.250,  "cached_input": 0.030,  "output": 2.000},
    "gpt-5-nano":        {"input": 0.050,  "cached_input": 0.005,  "output": 0.400},
    "gpt-4o":            {"input": 2.500,  "cached_input": 1.250,  "output": 10.000},
    "gpt-4o-2024-08-06": {"input": 2.500,  "cached_input": 1.250,  "output": 10.000},
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> dict[str, float]:
    """Return cost_details dict for Langfuse (USD). Pricing per 1M tokens."""
    prices      = _MODEL_PRICING.get(model, _MODEL_PRICING["gpt-4o-mini"])
    uncached    = max(input_tokens - cached_tokens, 0)
    input_cost  = (uncached    / 1_000_000) * prices["input"]
    cached_cost = (cached_tokens / 1_000_000) * prices["cached_input"]
    output_cost = (output_tokens / 1_000_000) * prices["output"]
    total       = input_cost + cached_cost + output_cost
    return {"input": input_cost + cached_cost, "output": output_cost, "total": total}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def generate_answer(
    openai_client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    lf_client=None,
    lf_metadata: dict | None = None,
) -> str:
    """Call OpenAI and optionally log as a Langfuse generation (with real latency + token counts)."""
    import datetime

    t_start = datetime.datetime.now(datetime.timezone.utc)
    create_kwargs: dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    if model not in _MODELS_NO_TEMPERATURE:
        create_kwargs["temperature"] = 0.0
    resp = openai_client.chat.completions.create(**create_kwargs)
    t_end = datetime.datetime.now(datetime.timezone.utc)

    raw_output = resp.choices[0].message.content or ""
    parsed = _parse_response(raw_output)

    # Log to Langfuse with real latency + token counts + explicit cost (Langfuse 3.x API)
    if lf_client is not None:
        usage      = resp.usage
        in_tok     = usage.prompt_tokens                                          if usage else 0
        out_tok    = usage.completion_tokens                                      if usage else 0
        cached_tok = getattr(usage.prompt_tokens_details, "cached_tokens", 0)    if usage else 0
        # Must call .end() — start_observation without end() never flushes tokens/cost
        gen_span = lf_client.start_observation(
            as_type="generation",
            name="rag-generation",
            model=model,
            input=[
                {"role": "system", "content": system_prompt[:200] + "..."},
                {"role": "user", "content": user_prompt[:500] + "..."},
            ],
            output=raw_output,
            model_parameters={"temperature": 0.0} if model not in _MODELS_NO_TEMPERATURE else {},
            usage_details={"input": in_tok, "output": out_tok, "cache_read_input_tokens": cached_tok},
            cost_details=_calc_cost(model, in_tok, out_tok, cached_tok),
            metadata=lf_metadata or {},
        )
        if gen_span is not None:
            gen_span.end()

    return parsed

# ---------------------------------------------------------------------------
# Dataset loading — two sources
# ---------------------------------------------------------------------------
def load_excel_rows(path: Path, limit: Optional[int] = None) -> list[dict]:
    """IDK expert-annotated dataset (Excel). ground_truth = Ideal Answer."""
    df = pd.read_excel(path, sheet_name="Review Completed", engine="openpyxl")
    df = df.dropna(subset=["Query In English", "Ideal Answer"])
    df = df[df["Ideal Answer"].str.strip() != ""]
    rows = []
    for r in df[["Query In English", "Ideal Answer", "Category", "Risk Classification", "Cause"]].to_dict("records"):
        rows.append({
            "Query In English":   r["Query In English"],
            "Ideal Answer":       r["Ideal Answer"],
            "Category":           str(r.get("Category", "")),
            "Risk Classification": str(r.get("Risk Classification", "")),
            "Cause":              str(r.get("Cause", "")),
            "source":             "idk_annotated",
        })
    if limit is not None:
        rows = rows[:limit]
    print(f"Excel (IDK): {len(rows)} rows")
    return rows


def load_production_rows(json_path: Path, sample_size: int = 500, seed: int = 42) -> list[dict]:
    """
    Sample good non-IDK Q&A pairs from production messages JSON.
    ground_truth = production bot answer (gpt-4o-mini on prod).
    Filters: bot_to_asha_response, regular_text/audio, no IDK signals,
             answer >= 100 chars, question >= 15 chars, deduped by question.
    """
    import random, statistics
    if not json_path.exists():
        print(f"[WARN] Production JSON not found: {json_path} — skipping")
        return []

    print(f"Loading production JSON ({json_path.name})...")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    idk_kws = [
        "i do not know", "idk", "i don't know", "cannot answer", "unable to answer",
        "not able to answer", "i am not sure", "not within my knowledge",
        "no information", "cannot provide", "outside my knowledge",
    ]
    seen_q: set[str] = set()
    pool: list[dict] = []

    for rec in data:
        md = rec.get("message_data", {})
        if (md.get("message_category") or "") != "bot_to_asha_response":
            continue
        mc = md.get("message_context", {})
        rc = md.get("reply_context", {})
        if (rc.get("reply_type") or "") not in ("regular_text", "regular_audio"):
            continue

        answer_en   = (mc.get("message_english_text") or "").strip()
        question_en = (rc.get("reply_english_text") or "").strip()
        if not answer_en or not question_en:
            continue

        q_key = question_en.lower()[:100]
        if q_key in seen_q:
            continue
        seen_q.add(q_key)

        if any(kw in answer_en.lower() for kw in idk_kws):
            continue
        if len(answer_en) < 100 or len(question_en) < 15:
            continue

        pool.append({
            "Query In English":   question_en,
            "Ideal Answer":       answer_en,   # production bot answer = reference
            "Category":           "production",
            "Risk Classification": "unknown",
            "Cause":              "",
            "source":             "production",
        })

    random.seed(seed)
    sampled = random.sample(pool, min(sample_size, len(pool)))
    print(f"Production: sampled {len(sampled)} from pool of {len(pool)}")
    return sampled


def load_eval_dataset(
    excel_path: Path,
    json_path: Path,
    excel_limit: Optional[int] = None,
    prod_sample: int = 500,
) -> list[dict]:
    """Combine both sources. excel_limit applies only to IDK rows."""
    excel_rows = load_excel_rows(excel_path, limit=excel_limit)
    prod_rows  = load_production_rows(json_path, sample_size=prod_sample)
    all_rows   = excel_rows + prod_rows
    print(f"Total eval rows: {len(all_rows)} ({len(excel_rows)} IDK + {len(prod_rows)} production)")
    return all_rows

# ---------------------------------------------------------------------------
# Langfuse dataset management (v2: always sync full dataset, return item map)
# ---------------------------------------------------------------------------
def setup_langfuse_dataset(lf, rows: list[dict]) -> dict[str, Any]:
    """
    Create (or reuse) Langfuse dataset.
    Always ensures all rows are present as dataset items.
    Returns dict: question_text -> DatasetItem (for item.run() linking).
    """
    try:
        lf.get_dataset(LANGFUSE_DATASET_NAME)
        print(f"Reusing existing Langfuse dataset '{LANGFUSE_DATASET_NAME}'")
    except Exception:
        lf.create_dataset(
            name=LANGFUSE_DATASET_NAME,
            description="Expert-annotated ASHABot eval set for RAGAS model comparison",
        )
        print(f"Created Langfuse dataset '{LANGFUSE_DATASET_NAME}'")

    dataset = lf.get_dataset(LANGFUSE_DATASET_NAME)
    existing_questions = {item.input["question"] for item in dataset.items}

    missing = [r for r in rows if r["Query In English"] not in existing_questions]
    if missing:
        print(f"Adding {len(missing)} new items to dataset...")
        src_label = {"idk_annotated": "Expert-annotated IDK", "production": "Production (bot answer)"}
        for row in missing:
            raw_src = row.get("source", "unknown")
            lf.create_dataset_item(
                dataset_name=LANGFUSE_DATASET_NAME,
                input={
                    "question":            row["Query In English"],
                    "category":            str(row.get("Category", "")),
                    "risk_classification": str(row.get("Risk Classification", "")),
                    "cause":               str(row.get("Cause", "")),
                    "source":              raw_src,
                },
                expected_output=row["Ideal Answer"],
                metadata={
                    "source_type":  raw_src,                          # "production" | "idk_annotated"
                    "source_label": src_label.get(raw_src, raw_src),  # human-readable
                },
            )
        lf.flush()
        dataset = lf.get_dataset(LANGFUSE_DATASET_NAME)
    else:
        print(f"Dataset already has all {len(dataset.items)} items.")

    # Backfill metadata for items created before this fix (missing source_type)
    src_label = {"idk_annotated": "Expert-annotated IDK", "production": "Production (bot answer)"}
    backfill_count = 0
    for item in dataset.items:
        if not (item.metadata or {}).get("source_type"):
            raw_src = (item.input or {}).get("source", "unknown")
            try:
                lf.api.dataset_items.create(
                    id=item.id,
                    dataset_name=LANGFUSE_DATASET_NAME,
                    input=item.input,
                    expected_output=item.expected_output,
                    metadata={
                        "source_type":  raw_src,
                        "source_label": src_label.get(raw_src, raw_src),
                    },
                    status="ACTIVE",
                )
                backfill_count += 1
            except Exception:
                pass  # item update via upsert may not be available in all SDK versions
    if backfill_count:
        print(f"Backfilled source_type metadata on {backfill_count} existing items.")
        lf.flush()
        dataset = lf.get_dataset(LANGFUSE_DATASET_NAME)

    # Build lookup: question -> DatasetItem
    return {item.input["question"]: item for item in dataset.items}


# Concurrency limit for generation — keeps proxy happy
_GEN_CONCURRENCY = int(os.environ.get("GEN_CONCURRENCY", "2"))

# ---------------------------------------------------------------------------
# Core eval loop (v2: concurrent generation + dataset-run linked traces)
# ---------------------------------------------------------------------------
async def _process_row(
    row: dict,
    model: str,
    vector_store,
    openai_client: OpenAI,
    system_prompt: str,
    bot_config: dict,
    semaphore: asyncio.Semaphore,
    lf_client=None,
    lf_item_map: dict | None = None,
) -> dict:
    """Process a single row: retrieve + generate. Runs concurrently up to semaphore limit."""
    async with semaphore:
        question     = row["Query In English"]
        ground_truth = row["Ideal Answer"]
        category     = str(row.get("Category", ""))
        risk         = str(row.get("Risk Classification", ""))
        source       = str(row.get("source", "unknown"))

        chunks = await retrieve_chunks(vector_store, question, k=3)
        contexts = [c["text"] for c in chunks if c["text"]]
        user_prompt = _build_user_prompt(bot_config, question, chunks)

        trace_id = None
        answer = ""
        try:
            dataset_item = lf_item_map.get(question) if lf_item_map else None

            if dataset_item is not None:
                with dataset_item.run(
                    run_name=f"ragas-{model}",
                    run_metadata={"model": model, "category": category, "risk_classification": risk, "source": source},
                    run_description=f"RAGAS eval run for {model}",
                ):
                    # Set trace input so it appears in Langfuse Traces → Input column
                    lf_client.update_current_span(input={
                        "question": question,
                        "model": model,
                        "source": source,
                        "category": category,
                    })
                    answer = generate_answer(
                        openai_client, model, system_prompt, user_prompt,
                        lf_client=lf_client,
                        lf_metadata={"model": model, "category": category, "risk_classification": risk, "source": source},
                    )
                    lf_client.update_current_span(output={"answer": answer})
                    trace_id = lf_client.get_current_trace_id()
            elif lf_client is not None:
                with lf_client.start_as_current_span(
                    name="ragas-eval",
                    input={"question": question, "model": model, "source": source, "category": category},
                    metadata={"model": model, "category": category, "risk_classification": risk, "source": source},
                ):
                    answer = generate_answer(
                        openai_client, model, system_prompt, user_prompt,
                        lf_client=lf_client,
                        lf_metadata={"model": model, "category": category, "risk_classification": risk, "source": source},
                    )
                    lf_client.update_current_span(output={"answer": answer})
                    trace_id = lf_client.get_current_trace_id()
            else:
                answer = generate_answer(openai_client, model, system_prompt, user_prompt)
        except Exception as e:
            print(f"  [WARN] {question[:60]!r}: {e}")

        return {
            "question":            question,
            "answer":              answer,
            "contexts":            contexts,
            "ground_truth":        ground_truth,
            "category":            category,
            "risk_classification": risk,
            "source":              source,
            "_trace_id":           trace_id,
        }


async def run_model_eval(
    model: str,
    rows: list[dict],
    vector_store,
    openai_client: OpenAI,
    system_prompt: str,
    bot_config: dict,
    lf_client=None,
    lf_item_map: dict | None = None,
) -> list[dict]:
    """
    Concurrent retrieval+generation for all rows (up to GEN_CONCURRENCY=8 at once).
    Linked to Langfuse Dataset Run via item.run() for Datasets -> Runs view.
    """
    print(f"\n--- Running RAG pipeline for model: {model} (concurrency={_GEN_CONCURRENCY}) ---")
    t0 = time.perf_counter()
    semaphore = asyncio.Semaphore(_GEN_CONCURRENCY)

    tasks = [
        _process_row(row, model, vector_store, openai_client, system_prompt,
                     bot_config, semaphore, lf_client, lf_item_map)
        for row in rows
    ]
    eval_rows = await asyncio.gather(*tasks)
    eval_rows = list(eval_rows)

    elapsed = time.perf_counter() - t0
    print(f"  [{model}] {len(eval_rows)}/{len(rows)} done ({elapsed:.0f}s)")

    if lf_client is not None:
        lf_client.flush()

    return eval_rows

# ---------------------------------------------------------------------------
# RAGAS evaluation
# ---------------------------------------------------------------------------
_RAGAS_CHUNK_SIZE = int(os.environ.get("RAGAS_CHUNK_SIZE", "5"))

def run_ragas(eval_rows: list[dict], model: str, lf_client, lf_dataset, openai_key: str) -> dict[str, float]:
    """
    Chunk-based RAGAS evaluation.
    Evaluates RAGAS_CHUNK_SIZE rows at once (default 20) — RAGAS internal max_workers=4
    parallelises within each chunk for speed. After each chunk, scores are immediately
    logged to Langfuse so the UI updates every ~4-5 min instead of waiting hours.
    """
    try:
        import warnings
        import httpx
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from ragas import evaluate
        from ragas.metrics import ContextPrecision, ContextRecall, Faithfulness, AnswerCorrectness
        from ragas.llms import llm_factory
        from ragas.embeddings import embedding_factory
        from datasets import Dataset
        from ragas.run_config import RunConfig
    except ImportError as e:
        print(f"Missing dependency: {e}. Run: pip install ragas datasets")
        return {}

    print(f"\n--- RAGAS evaluation for {model} (chunk={_RAGAS_CHUNK_SIZE}, max_workers=4) ---")

    from openai import OpenAI as _OpenAI, AsyncOpenAI as _AsyncOpenAI
    _oai_sync  = _OpenAI(api_key=openai_key, organization=None, http_client=httpx.Client(verify=False))
    _oai_async = _AsyncOpenAI(api_key=openai_key, organization=None, http_client=httpx.AsyncClient(verify=False))

    ragas_llm        = llm_factory("gpt-4o-mini", client=_oai_sync, max_tokens=4096)
    ragas_embeddings = embedding_factory("openai", model="text-embedding-3-small", client=_oai_async)

    m_cp = ContextPrecision();   m_cp.llm = ragas_llm
    m_cr = ContextRecall();      m_cr.llm = ragas_llm
    m_f  = Faithfulness();       m_f.llm  = ragas_llm
    m_ac = AnswerCorrectness();  m_ac.llm = ragas_llm; m_ac.embeddings = ragas_embeddings
    metrics     = [m_cp, m_cr, m_f, m_ac]
    metric_cols = ["context_precision", "context_recall", "faithfulness", "answer_correctness"]

    # max_workers=4: RAGAS parallelises across rows within the chunk
    run_cfg = RunConfig(timeout=300, max_workers=4, max_retries=3)

    all_scores: list[dict] = []
    scored = 0
    chunks = [eval_rows[i:i+_RAGAS_CHUNK_SIZE] for i in range(0, len(eval_rows), _RAGAS_CHUNK_SIZE)]

    for chunk_idx, chunk in enumerate(chunks):
        start = chunk_idx * _RAGAS_CHUNK_SIZE
        print(f"  [{model}] chunk {chunk_idx+1}/{len(chunks)} (rows {start+1}-{start+len(chunk)})...", flush=True)

        ds = Dataset.from_list([{
            "question":     r["question"],
            "answer":       r["answer"],
            "contexts":     r["contexts"],
            "ground_truth": r["ground_truth"],
        } for r in chunk])

        try:
            result   = evaluate(dataset=ds, metrics=metrics, run_config=run_cfg)
            scores_df = result.to_pandas()
        except Exception as e:
            print(f"  [{model}] chunk {chunk_idx+1} error: {e}", flush=True)
            all_scores.extend([{} for _ in chunk])
            continue

        # Log scores per row immediately after chunk completes
        for row, row_scores_tuple in zip(chunk, scores_df.itertuples()):
            row_scores = {m: float(getattr(row_scores_tuple, m, float("nan"))) for m in metric_cols}
            all_scores.append(row_scores)

            trace_id = row.get("_trace_id")
            if lf_client and trace_id:
                for metric, val in row_scores.items():
                    if val == val:  # skip NaN
                        lf_client.create_score(
                            trace_id=trace_id,
                            name=metric,
                            value=val,
                            data_type="NUMERIC",
                            comment=f"model={model}",
                        )
                scored += 1
        lf_client.flush()

        # Print chunk averages
        chunk_avgs = {m: scores_df[m].mean() for m in metric_cols if m in scores_df.columns}
        print(f"  [{model}] chunk {chunk_idx+1} done | " +
              " ".join(f"{m[:2]}={v:.3f}" for m, v in chunk_avgs.items()), flush=True)

    print(f"  [{model}] all chunks done. Scored {scored}/{len(eval_rows)} rows in Langfuse.")

    averages = {}
    for m in metric_cols:
        vals = [s[m] for s in all_scores if m in s and s[m] == s[m]]
        averages[m] = sum(vals) / len(vals) if vals else float("nan")

    return averages

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    # Validate required env vars
    _required = {
        "OPENAI_API_KEY":            _OPENAI_API_KEY,
        "AZURE_SEARCH_SERVICE_NAME": _AZURE_SEARCH_SERVICE,
        "AZURE_SEARCH_INDEX_NAME":   _AZURE_SEARCH_INDEX,
        "AZURE_SEARCH_API_KEY":      _AZURE_SEARCH_KEY,
    }
    missing = [k for k, v in _required.items() if not v]
    if missing:
        sys.exit(f"ERROR: missing required env vars: {', '.join(missing)}")

    openai_key      = _OPENAI_API_KEY
    langfuse_secret = _LANGFUSE_SECRET
    langfuse_public = _LANGFUSE_PUBLIC

    # Load dataset: IDK-annotated (Excel) + production good answers (JSON)
    # EVAL_LIMIT caps IDK rows only; PROD_SAMPLE_SIZE controls production sample
    rows = load_eval_dataset(
        excel_path=EXCEL_DEFAULT_PATH,
        json_path=PROD_JSON_PATH,
        excel_limit=EVAL_LIMIT,
        prod_sample=PROD_SAMPLE_SIZE,  # always load prod; EVAL_LIMIT=0 = 0 IDK rows only
    )

    # Load bot config + prompts
    bot_cfg = _load_bot_config()
    system_prompt = _build_system_prompt(bot_cfg)

    # Init clients — disable SSL verify for corporate proxy; explicitly clear org to avoid mismatch
    import httpx as _httpx
    openai_client = OpenAI(
        api_key=openai_key,
        organization=None,
        http_client=_httpx.Client(verify=False),
    )
    vector_store = _build_vector_store()

    # Langfuse
    lf = None
    lf_dataset = None
    if langfuse_secret and langfuse_public:
        import httpx
        from langfuse import Langfuse
        lf_host = _LANGFUSE_HOST
        # Self-hosted Langfuse may use self-signed cert — disable SSL verify for non-cloud hosts
        ssl_verify = lf_host == "https://cloud.langfuse.com"
        lf = Langfuse(
            secret_key=langfuse_secret,
            public_key=langfuse_public,
            host=lf_host,
            httpx_client=httpx.Client(verify=ssl_verify),
        )
        # v2: returns dict{question -> DatasetItem} for item.run() linking
        lf_item_map = setup_langfuse_dataset(lf, rows)
    else:
        print("LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY not set — skipping Langfuse logging.")
        lf_item_map = None

    # --- Step 1: generation — sequential per model (Azure Search shared, throttles if concurrent) ---
    # Within each model: rows run concurrently up to GEN_CONCURRENCY
    all_eval_rows: dict[str, list[dict]] = {}
    print("\n=== Phase 1: Generation (sequential per model, concurrent rows) ===")
    for model in MODELS:
        all_eval_rows[model] = await run_model_eval(
            model=model,
            rows=rows,
            vector_store=vector_store,
            openai_client=openai_client,
            system_prompt=system_prompt,
            bot_config=bot_cfg,
            lf_client=lf,
            lf_item_map=lf_item_map,
        )

    # --- Step 2: run RAGAS sequentially per model (avoids 8 concurrent proxy calls → fewer timeouts) ---
    import concurrent.futures
    all_results: dict[str, dict[str, float]] = {}
    print("\n=== Phase 2: RAGAS evaluation (sequential per model, chunk=5) ===")
    loop = asyncio.get_event_loop()
    for model in MODELS:
        all_results[model] = await loop.run_in_executor(
            None,  # default threadpool
            run_ragas,
            all_eval_rows[model], model, lf, None, openai_key,
        )

    # --- Build comparison data ---
    import datetime, math
    metric_cols = ["context_precision", "context_recall", "faithfulness", "answer_correctness"]
    metric_labels = {
        "context_precision":   "Context Precision",
        "context_recall":      "Context Recall",
        "faithfulness":        "Faithfulness",
        "answer_correctness":  "Answer Correctness",
    }
    m0, m1 = MODELS[0], MODELS[1]

    def _delta_str(v0: float, v1: float) -> str:
        if math.isnan(v0) or math.isnan(v1):
            return "N/A"
        d = v1 - v0
        arrow = "^" if d > 0.005 else ("v" if d < -0.005 else "~")
        return f"{arrow} {d:+.4f}"

    def _winner(v0: float, v1: float) -> str:
        if math.isnan(v0) or math.isnan(v1):
            return "-"
        if v1 > v0 + 0.005:
            return m1
        if v0 > v1 + 0.005:
            return m0
        return "TIE"

    # --- Terminal: side-by-side ---
    W = 80
    print("\n" + "=" * W)
    print(f"  RAGAS COMPARISON:  {m0}  vs  {m1}")
    print(f"  Rows evaluated: {len(list(all_eval_rows.values())[0])}  |  Date: {datetime.date.today()}")
    print("=" * W)
    hdr = f"  {'Metric':<22}  {'gpt-4o-mini':>11}  {'gpt-4.1-mini':>12}  {'Delta':>10}  {'Winner':<14}"
    print(hdr)
    print("  " + "-" * (W - 2))
    for mc in metric_cols:
        v0 = all_results[m0].get(mc, float("nan"))
        v1 = all_results[m1].get(mc, float("nan"))
        ds = _delta_str(v0, v1)
        wn = _winner(v0, v1)
        v0s = f"{v0:.4f}" if not math.isnan(v0) else "  N/A"
        v1s = f"{v1:.4f}" if not math.isnan(v1) else "  N/A"
        print(f"  {metric_labels[mc]:<22}  {v0s:>11}  {v1s:>12}  {ds:>10}  {wn:<14}")
    print("=" * W)

    # Verdict
    wins = sum(1 for mc in metric_cols
               if _winner(all_results[m0].get(mc, float("nan")),
                          all_results[m1].get(mc, float("nan"))) == m1)
    ties = sum(1 for mc in metric_cols
               if _winner(all_results[m0].get(mc, float("nan")),
                          all_results[m1].get(mc, float("nan"))) == "TIE")
    verdict = "GO  -- gpt-4.1-mini >= gpt-4o-mini" if wins + ties == len(metric_cols) else \
              f"REVIEW -- gpt-4.1-mini wins {wins}/{len(metric_cols)} metrics"
    print(f"\n  Verdict: {verdict}")
    print("=" * W)

    # --- Risk-stratified breakdown (answer_correctness only) ---
    print(f"\n  Answer Correctness by Risk Classification")
    print("  " + "-" * 60)
    risk_results: dict[str, dict[str, float]] = {}
    for risk in ["Very High", "High", "Limited"]:
        row_counts = {model: len([r for r in all_eval_rows[model] if r.get("risk_classification") == risk])
                      for model in MODELS}
        if all(c == 0 for c in row_counts.values()):
            continue
        print(f"\n  [{risk}]")
        risk_results[risk] = {}
        for model in MODELS:
            subset = [r for r in all_eval_rows[model] if r.get("risk_classification") == risk]
            if not subset:
                print(f"    {model:<14}: no rows")
                risk_results[risk][model] = float("nan")
                continue
            try:
                import warnings, httpx
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                from ragas import evaluate
                from ragas.metrics import AnswerCorrectness
                from ragas.llms import llm_factory
                from ragas.embeddings import embedding_factory
                from openai import OpenAI as _OpenAI, AsyncOpenAI as _AsyncOpenAI
                from datasets import Dataset
                _oai_sync  = _OpenAI(api_key=openai_key, organization=None, http_client=httpx.Client(verify=False))
                _oai_async = _AsyncOpenAI(api_key=openai_key, organization=None, http_client=httpx.AsyncClient(verify=False))
                _llm = llm_factory("gpt-4o-mini", client=_oai_sync)
                _emb = embedding_factory("openai", model="text-embedding-3-small", client=_oai_async)
                _m_ac = AnswerCorrectness(); _m_ac.llm = _llm; _m_ac.embeddings = _emb
                ds = Dataset.from_list([
                    {"question": r["question"], "answer": r["answer"],
                     "contexts": r["contexts"], "ground_truth": r["ground_truth"]}
                    for r in subset
                ])
                res = evaluate(ds, metrics=[_m_ac])
                avg = res.to_pandas()["answer_correctness"].mean()
                risk_results[risk][model] = avg
                print(f"    {model:<14}: {avg:.4f}  (n={len(subset)})")
            except Exception as e:
                print(f"    {model:<14}: error ({e})")
                risk_results[risk][model] = float("nan")
        # mini delta for this risk tier
        rv0 = risk_results[risk].get(m0, float("nan"))
        rv1 = risk_results[risk].get(m1, float("nan"))
        print(f"    {'Delta':<14}: {_delta_str(rv0, rv1)}  ({_winner(rv0, rv1)})")
    print("  " + "-" * 60)

    # --- Category breakdown (answer_correctness) ---
    categories = sorted({r.get("category", "") for r in all_eval_rows[m0] if r.get("category", "") not in ("", "nan")})
    if categories:
        print(f"\n  Answer Correctness by Category")
        print("  " + "-" * 60)
        cat_header = f"  {'Category':<25}  {'gpt-4o-mini':>11}  {'gpt-4.1-mini':>12}  {'Delta':>10}  n"
        print(cat_header)
        for cat in categories:
            cat_vals = {}
            for model in MODELS:
                subset = [r for r in all_eval_rows[model] if r.get("category", "") == cat]
                if not subset:
                    cat_vals[model] = float("nan")
                    continue
                # use pre-computed per-row scores from RAGAS results if available
                # fallback: use mean of rows that had scores
                cat_vals[model] = float("nan")  # placeholder — full scores not re-run per category
            n = len([r for r in all_eval_rows[m0] if r.get("category", "") == cat])
            cv0 = cat_vals[m0]; cv1 = cat_vals[m1]
            v0s = f"{cv0:.4f}" if not math.isnan(cv0) else "   N/A"
            v1s = f"{cv1:.4f}" if not math.isnan(cv1) else "   N/A"
            print(f"  {cat:<25}  {v0s:>11}  {v1s:>12}  {'N/A':>10}  {n}")
        print("  " + "-" * 60)

    # --- Save markdown report ---
    _save_markdown_report(all_results, all_eval_rows, metric_cols, metric_labels,
                          risk_results, openai_key)

    print("\nDone. View full results in Langfuse -> Datasets -> ragas-model-comparison-v1 -> Runs")


def _save_markdown_report(
    all_results: dict,
    all_eval_rows: dict,
    metric_cols: list,
    metric_labels: dict,
    risk_results: dict,
    openai_key: str,
) -> None:
    import datetime, math

    m0, m1 = MODELS[0], MODELS[1]
    n_rows = len(list(all_eval_rows.values())[0])
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path = _SCRIPT_DIR / f"ragas_comparison_{datetime.date.today()}.md"

    def _delta(v0: float, v1: float) -> str:
        if math.isnan(v0) or math.isnan(v1):
            return "N/A"
        d = v1 - v0
        arrow = "+" if d > 0.005 else ("-" if d < -0.005 else "~")
        return f"{arrow}{abs(d):.4f}"

    def _winner(v0: float, v1: float) -> str:
        if math.isnan(v0) or math.isnan(v1):
            return "-"
        if v1 > v0 + 0.005:
            return f"**{m1}**"
        if v0 > v1 + 0.005:
            return f"**{m0}**"
        return "TIE"

    wins = sum(1 for mc in metric_cols
               if _winner(all_results[m0].get(mc, float("nan")),
                          all_results[m1].get(mc, float("nan"))) == f"**{m1}**")
    ties = sum(1 for mc in metric_cols
               if _winner(all_results[m0].get(mc, float("nan")),
                          all_results[m1].get(mc, float("nan"))) == "TIE")
    verdict = "**GO** - `gpt-4.1-mini` performs >= `gpt-4o-mini` on all metrics" \
        if wins + ties == len(metric_cols) else \
        f"**REVIEW** - `gpt-4.1-mini` wins {wins}/{len(metric_cols)} metrics; check regressions below"

    lines = [
        f"# RAGAS Model Comparison Report",
        f"",
        f"**Date:** {ts}  ",
        f"**Rows evaluated:** {n_rows}  ",
        f"**Dataset:** A4I-ASHABot-IDK.Cleaned.xlsx — sheet \"Review Completed\"  ",
        f"**Langfuse dataset:** `{LANGFUSE_DATASET_NAME}`  ",
        f"**Issue:** A4i-tech/.github#184  ",
        f"",
        f"---",
        f"",
        f"## Verdict",
        f"",
        f"{verdict}",
        f"",
        f"---",
        f"",
        f"## Overall Metrics",
        f"",
        f"| Metric | `{m0}` | `{m1}` | Delta | Winner |",
        f"|--------|--------|---------|-------|--------|",
    ]

    for mc in metric_cols:
        v0 = all_results[m0].get(mc, float("nan"))
        v1 = all_results[m1].get(mc, float("nan"))
        v0s = f"{v0:.4f}" if not math.isnan(v0) else "N/A"
        v1s = f"{v1:.4f}" if not math.isnan(v1) else "N/A"
        lines.append(f"| {metric_labels[mc]} | {v0s} | {v1s} | {_delta(v0, v1)} | {_winner(v0, v1)} |")

    lines += [
        f"",
        f"> **Delta** = `{m1}` minus `{m0}`. Positive = improvement.",
        f"",
        f"---",
        f"",
        f"## Metric Descriptions",
        f"",
        f"| Metric | What it measures |",
        f"|--------|-----------------|",
        f"| Context Precision | Are retrieved chunks relevant to the question? |",
        f"| Context Recall | Do chunks contain enough info to answer correctly? |",
        f"| Faithfulness | Is the generated answer grounded in the retrieved chunks? |",
        f"| Answer Correctness | Does the answer match the expert ground truth? *(key metric)* |",
        f"",
        f"---",
        f"",
        f"## Answer Correctness by Risk Classification",
        f"",
        f"| Risk Tier | `{m0}` | `{m1}` | Delta | Winner |",
        f"|-----------|--------|---------|-------|--------|",
    ]

    for risk, scores in risk_results.items():
        rv0 = scores.get(m0, float("nan"))
        rv1 = scores.get(m1, float("nan"))
        rv0s = f"{rv0:.4f}" if not math.isnan(rv0) else "N/A"
        rv1s = f"{rv1:.4f}" if not math.isnan(rv1) else "N/A"
        n = len([r for r in all_eval_rows[m0] if r.get("risk_classification") == risk])
        lines.append(f"| {risk} (n={n}) | {rv0s} | {rv1s} | {_delta(rv0, rv1)} | {_winner(rv0, rv1)} |")

    if not risk_results:
        lines.append(f"| *(no rows with risk labels in this run)* | - | - | - | - |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Go / No-Go Criteria",
        f"",
        f"Proceed with migration if `gpt-4.1-mini` scores >= `gpt-4o-mini` across all metrics,",
        f"or any regression is within acceptable tolerance (< 0.01 drop).",
        f"",
        f"| Criterion | Pass? |",
        f"|-----------|-------|",
    ]

    for mc in metric_cols:
        v0 = all_results[m0].get(mc, float("nan"))
        v1 = all_results[m1].get(mc, float("nan"))
        if math.isnan(v0) or math.isnan(v1):
            status = "N/A"
        elif v1 >= v0 - 0.01:
            status = "YES"
        else:
            status = f"NO (regression: {v1 - v0:+.4f})"
        lines.append(f"| {metric_labels[mc]} >= baseline - 0.01 | {status} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Next Steps",
        f"",
        f"- [ ] Review regression details in Langfuse -> Datasets -> `{LANGFUSE_DATASET_NAME}` -> Runs",
        f"- [ ] Phase 2: update `compile_monthly_logs.py`, `compile_monthly_logs_idk_categorization.py`",
        f"- [ ] Phase 2: update `test_llms_openai.py`, `test_llms_azure_openai.py`",
        f"- [ ] Phase 3: create `gpt-4.1-mini` deployment in Azure OpenAI Studio",
        f"",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report saved: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
