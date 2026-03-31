"""
Creates generation observations linked to the current OTEL trace.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict

from byoeb.observability.tracing import get_current_otel_trace_context

from langfuse import Langfuse

_client = Langfuse(environment=os.getenv("APP_ENV", "LOCAL").lower())
logger = logging.getLogger(__name__)


@contextmanager
def observe_llm(name: str, model: str = "", input_data: Any = None):
    """
    Context manager to record an LLM call in Langfuse, linked to the current OTEL trace.

    Yields an observation object; call observation.update(output=..., usage=...) before exit.
    When Langfuse keys are unset, the client operates as a no-op polyfill automatically.
    """
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

    with _client.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model or "unknown",
        trace_context=get_current_otel_trace_context(),
        input=enriched_input,
    ) as obs:
        yield obs
