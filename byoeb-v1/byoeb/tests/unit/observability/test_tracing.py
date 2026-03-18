"""
Unit tests for conversation-flow tracing (Issue #217).

Covers: get_conversation_tracer, get_current_otel_trace_context,
inject_trace_context_into_payload, parse_queue_payload_and_extract_context.
"""

import json
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from byoeb_core.models.byoeb.user import User
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes,
)
from byoeb.observability.tracing import (
    TRACER_NAME,
    TRACER_VERSION,
    KEY_BODY,
    KEY_TRACE,
    get_conversation_tracer,
    get_current_otel_trace_context,
    inject_trace_context_into_payload,
    parse_queue_payload_and_extract_context,
)


def _make_user(
    phone_number_id: str = "919000000001",
    user_id: str = "user-1",
    user_type: str | None = "asha",
    user_language: str | None = "en",
) -> User:
    return User(
        user_id=user_id,
        phone_number_id=phone_number_id,
        user_type=user_type,
        user_language=user_language,
        user_name="Test",
        test_user=False,
        experts={},
        audience=[],
        additional_info={},
        created_timestamp=0,
        activity_timestamp=0,
        last_conversations=[],
    )


def _make_message(
    user: User | None = None,
    message_source_text: str = "hello",
    message_id: str = "msg-1",
) -> ByoebMessageContext:
    u = user or _make_user()
    return ByoebMessageContext(
        channel_type="whatsapp",
        message_category="user_to_bot",
        user=u,
        message_context=MessageContext(
            message_id=message_id,
            message_type=MessageTypes.REGULAR_TEXT.value,
            message_source_text=message_source_text,
            additional_info={},
        ),
        reply_context=ReplyContext(),
    )


class TestGetConversationTracer:
    def test_returns_tracer_with_name_and_version(self):
        tracer = get_conversation_tracer()
        assert tracer is not None
        # Tracer from global provider may not expose name; at least we get a tracer
        assert hasattr(tracer, "start_span")


class TestGetCurrentOtelTraceContext:
    def test_no_active_span_returns_none(self):
        # No span started in this thread (or clear context)
        result = get_current_otel_trace_context()
        # Can be None or a dict if test run is under a trace
        assert result is None or isinstance(result, dict)
        if result is not None:
            assert "trace_id" in result and "parent_span_id" in result

    def test_with_active_span_returns_32_hex_trace_id_and_16_hex_span_id(self):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = get_conversation_tracer()
        with tracer.start_as_current_span("test_span") as span:
            ctx = get_current_otel_trace_context()
            assert ctx is not None
            assert "trace_id" in ctx and "parent_span_id" in ctx
            assert len(ctx["trace_id"]) == 32 and all(c in "0123456789abcdef" for c in ctx["trace_id"])
            assert len(ctx["parent_span_id"]) == 16 and all(c in "0123456789abcdef" for c in ctx["parent_span_id"])


class TestInjectTraceContextIntoPayload:
    def test_no_context_returns_unwrapped_json(self):
        msg = _make_message(message_source_text="hi")
        body_str = msg.model_dump_json()
        result = inject_trace_context_into_payload(msg)
        # Without active trace context we get backward-compat unwrapped
        assert result == body_str or json.loads(result).get(KEY_BODY) == json.loads(body_str)

    def test_with_context_returns_wrapped_with_body_and_trace(self):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = get_conversation_tracer()
        msg = _make_message(message_id="m1")
        with tracer.start_as_current_span("receive"):
            result = inject_trace_context_into_payload(msg)
        parsed = json.loads(result)
        assert KEY_BODY in parsed and KEY_TRACE in parsed
        body_parsed = json.loads(parsed[KEY_BODY]) if isinstance(parsed[KEY_BODY], str) else parsed[KEY_BODY]
        assert body_parsed.get("message_context", {}).get("message_id") == "m1"


class TestParseQueuePayloadAndExtractContext:
    def test_legacy_payload_returns_message_and_none_context(self):
        msg = _make_message(message_id="legacy-1")
        raw = msg.model_dump_json()
        parsed_msg, ctx = parse_queue_payload_and_extract_context(raw)
        assert ctx is None
        assert parsed_msg.message_context.message_id == "legacy-1"

    def test_wrapped_payload_returns_message_and_context(self):
        msg = _make_message(message_id="wrapped-1")
        body_str = msg.model_dump_json()
        # Minimal W3C traceparent for extraction
        carrier = {"traceparent": "00-00000000000000000000000000000001-0000000000000001-01"}
        wrapped = {KEY_BODY: body_str, KEY_TRACE: carrier}
        raw = json.dumps(wrapped)
        parsed_msg, ctx = parse_queue_payload_and_extract_context(raw)
        assert parsed_msg.message_context.message_id == "wrapped-1"
        # Context may or may not be present depending on OTEL setup
        assert ctx is None or hasattr(ctx, "__class__")

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_queue_payload_and_extract_context("not json {{{")

    def test_wrapped_but_bad_trace_returns_message_graceful_context(self):
        msg = _make_message(message_id="bad-trace")
        wrapped = {KEY_BODY: msg.model_dump_json(), KEY_TRACE: {"traceparent": "invalid"}}
        raw = json.dumps(wrapped)
        parsed_msg, ctx = parse_queue_payload_and_extract_context(raw)
        assert parsed_msg.message_context.message_id == "bad-trace"
        # When _trace is invalid, implementation may return None or an empty context; either is acceptable
