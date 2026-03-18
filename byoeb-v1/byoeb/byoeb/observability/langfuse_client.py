"""
Optional Langfuse integration for LLM call observability (Issue #217 Phase 4).

Creates generation observations linked to the current OTEL trace.
When LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY are unset, Langfuse logs a
warning and operates as a no-op polyfill client automatically.
"""

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict

from byoeb.observability.tracing import get_current_otel_trace_context

from langfuse import Langfuse

_client: Langfuse | None = None
_client_lock = threading.Lock()
logger = logging.getLogger(__name__)


def get_langfuse() -> Langfuse:
    """Return the singleton Langfuse client.

    Uses Langfuse's tracing configuration so OTEL spans from the app are
    exported to Langfuse for end‑to‑end tracing. Environment is derived from
    APP_ENV to keep Langfuse views aligned with our deployment environment.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                app_env = os.getenv("APP_ENV", "LOCAL")
                # Map our APP_ENV to Langfuse environment name (lowercase for consistency)
                lf_env = app_env.lower()
                # Newer Langfuse Python SDKs no longer accept an `environment` kwarg.
                # Instead, they read LANGFUSE_ENVIRONMENT from the process environment.
                os.environ.setdefault("LANGFUSE_ENVIRONMENT", lf_env)
                _client = Langfuse()
    return _client


@contextmanager
def observe_llm(name: str, model: str = "", input_data: Any = None):
    """
    Context manager to record an LLM call in Langfuse, linked to the current OTEL trace.

    Yields an observation object; call observation.update(output=..., usage=...) before exit.
    When Langfuse keys are unset, the client operates as a no-op polyfill automatically.
    """
    # Always tag environment / component metadata so observations can be filtered in Langfuse.
    env = os.getenv("APP_ENV", "LOCAL")
    logger.debug("observe_llm start: %s env=%s", name, env)

    enriched_input: Dict[str, Any] = {
        "environment": env,
        "component": name,
    }

    if input_data is not None:
        if isinstance(input_data, dict):
            enriched_input.update(input_data)
        else:
            enriched_input["payload"] = input_data

    client = get_langfuse()
    otel_ctx = get_current_otel_trace_context()
    otel_trace_id = otel_ctx.get("trace_id") if otel_ctx else None
    # "parent_span_id" is the *current* active OTEL span's ID; using it as
    # parent_observation_id nests the generation beneath it in Langfuse
    # (e.g. llm_translation_and_query_rewriting under conversation.query_rewrite).
    otel_span_id = otel_ctx.get("parent_span_id") if otel_ctx else None

    # Use the top-level client.generation() so we pass trace_id and
    # parent_observation_id directly.  This avoids calling client.trace() or
    # lf_trace.span() which would immediately ingest "Unnamed trace" / "Unnamed
    # span" entities that shadow the properly-named OTEL-exported observations.
    generation = client.generation(
        name=name,
        model=model or "unknown",
        input=enriched_input,
        trace_id=otel_trace_id,
        parent_observation_id=otel_span_id,
    )
    logger.debug(
        "observe_llm: created Langfuse generation '%s' under span=%s trace=%s",
        name, otel_span_id, otel_trace_id,
    )
    yield generation
