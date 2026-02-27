"""
Optional Langfuse integration for LLM call observability (Issue #217 Phase 4).

Creates generation observations linked to the current OTEL trace.
When LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY are unset, Langfuse logs a
warning and operates as a no-op polyfill client automatically.
"""

import os
from contextlib import contextmanager
from typing import Any, Dict

from byoeb.observability.tracing import get_current_otel_trace_context

from langfuse import Langfuse

_client: Langfuse | None = None


def get_langfuse() -> Langfuse:
    """Return the singleton Langfuse client.

    tracing_enabled=False disables Langfuse's global OTEL span exporter so that
    only explicit observe_llm() calls are forwarded to Langfuse. Queue polling,
    cache, and other infrastructure spans are already covered by App Insights.
    """
    global _client
    if _client is None:
        _client = Langfuse(tracing_enabled=False)
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

    enriched_input: Dict[str, Any] = {
        "environment": env,
        "component": name,
    }

    if input_data is not None:
        if isinstance(input_data, dict):
            enriched_input.update(input_data)
        else:
            enriched_input["payload"] = input_data

    with get_langfuse().start_as_current_observation(
        as_type="generation",
        name=name,
        model=model or "unknown",
        trace_context=get_current_otel_trace_context(),
        input=enriched_input,
    ) as obs:
        yield obs
