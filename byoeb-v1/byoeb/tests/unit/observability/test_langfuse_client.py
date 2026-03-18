"""
Unit tests for optional Langfuse client (Issue #217 Phase 4).

Covers: get_langfuse_client no-op when env unset; observe_llm no-op path.
"""

import os
import pytest
from unittest.mock import patch

from byoeb.observability.langfuse_client import (
    get_langfuse_client,
    get_langfuse,
    observe_llm,
    _NoOpLangfuseClient,
    _NoOpObservation,
)


class TestGetLangfuseClient:
    def test_no_env_returns_noop_client(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove Langfuse keys if present
            for key in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
                os.environ.pop(key, None)
            client = get_langfuse_client()
        assert isinstance(client, _NoOpLangfuseClient)

    def test_only_secret_set_returns_noop_client(self):
        with patch.dict(os.environ, {"LANGFUSE_SECRET_KEY": "sk-x"}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            client = get_langfuse_client()
        assert isinstance(client, _NoOpLangfuseClient)

    def test_noop_client_has_observe_llm_and_flush(self):
        client = get_langfuse_client()
        if isinstance(client, _NoOpLangfuseClient):
            assert hasattr(client, "observe_llm") and callable(getattr(client, "observe_llm"))
            assert hasattr(client, "flush") and callable(getattr(client, "flush"))


class TestObserveLlmNoOp:
    def test_observe_llm_yields_object_with_update(self):
        with observe_llm("test_llm", model="test") as obs:
            assert obs is not None
            obs.update(output="out", usage={"prompt_tokens": 1, "completion_tokens": 2})

    def test_observe_llm_exit_clean(self):
        with observe_llm("test") as obs:
            obs.update(output="x")
        # No exception

    def test_noop_observation_update_and_end_do_not_raise(self):
        noop = _NoOpObservation()
        noop.update(output="x", usage={})
        noop.end()


class TestGetLangfuseSingleton:
    def test_get_langfuse_returns_same_instance_when_called_twice(self):
        import byoeb.observability.langfuse_client as mod
        prev = getattr(mod, "_client", None)
        mod._client = None
        try:
            with patch.dict(os.environ, {}, clear=True):
                for key in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY"):
                    os.environ.pop(key, None)
                a = get_langfuse()
                b = get_langfuse()
                assert a is b
        finally:
            mod._client = prev
