"""
Optional Langfuse integration for LLM call observability (Issue #217 Phase 4).

When LANGFUSE_SECRET_KEY (and LANGFUSE_PUBLIC_KEY) are set and the langfuse package
is installed, creates generations linked to the current OTEL trace. Otherwise no-ops.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Optional

from byoeb.observability.tracing import get_current_otel_trace_context

_logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None  # type: ignore[misc, assignment]


class _NoOpObservation:
    """No-op observation for when Langfuse is disabled."""

    def update(self, **kwargs: Any) -> None:
        pass

    def end(self) -> None:
        pass


class _NoOpLangfuseClient:
    """No-op client when Langfuse is not configured or not installed."""

    @contextmanager
    def observe_llm(
        self,
        name: str,
        model: str = "",
        input_data: Any = None,
    ):
        """Context manager that yields a no-op observation."""
        yield _NoOpObservation()

    def flush(self) -> None:
        pass


def get_langfuse_client():  # -> Union[Langfuse, _NoOpLangfuseClient]
    """
    Return a Langfuse client when configured, else a no-op client.

    Requires LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY. Optional LANGFUSE_HOST
    (defaults to https://cloud.langfuse.com). No-op when langfuse is not installed
    or keys are unset.
    """
    if Langfuse is None:
        return _NoOpLangfuseClient()
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    if not secret or not public:
        return _NoOpLangfuseClient()
    host = os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    try:
        return Langfuse(secret_key=secret, public_key=public, host=host)
    except Exception as e:
        _logger.warning("Langfuse client init failed: %s. Using no-op.", e)
        return _NoOpLangfuseClient()


# Lazy singleton for app use
_client: Optional[Any] = None


def get_langfuse() -> Any:
    """Return the singleton Langfuse client (real or no-op)."""
    global _client
    if _client is None:
        _client = get_langfuse_client()
    return _client


@contextmanager
def observe_llm(name: str, model: str = "", input_data: Any = None):
    """
    Context manager to record an LLM call in Langfuse when enabled, linked to current OTEL trace.

    Yields an observation object; call observation.update(output=..., usage=...) before exit.
    When Langfuse is disabled, the yielded object is a no-op.
    """
    client = get_langfuse()
    if isinstance(client, _NoOpLangfuseClient):
        yield _NoOpObservation()
        return
    trace_ctx = get_current_otel_trace_context()
    trace_context = trace_ctx or {}
    try:
        with client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model or "unknown",
            trace_context=trace_context,
            input=input_data,
        ) as obs:
            yield obs
    except Exception as e:
        _logger.debug("Langfuse observe_llm failed: %s", e)
        yield _NoOpObservation()
