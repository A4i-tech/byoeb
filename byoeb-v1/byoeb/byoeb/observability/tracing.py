"""
OTEL tracing helpers for conversation flow (Issue #217).

- Shared tracer and span names for conversation steps.
- Trace context propagation: inject into queue payload (producer), parse and extract (consumer).
"""

import json
import logging
from typing import Any, Optional, Tuple

from opentelemetry import trace, context
from opentelemetry.propagate import inject, extract

from byoeb_core.models.byoeb.message_context import ByoebMessageContext


TRACER_NAME = "byoeb.conversation"
TRACER_VERSION = "0.1.0"

# Span name constants (conversation.<step>)
SPAN_RECEIVE = "conversation.receive"
SPAN_VALIDATE_CHANNEL = "conversation.validate_channel"
SPAN_GET_PRODUCER = "conversation.get_producer"
SPAN_APUBLISH_MESSAGE = "conversation.apublish_message"
SPAN_CONVERT_WHATSAPP = "conversation.convert_whatsapp_to_byoeb"
SPAN_DUPLICATE_CHECK = "conversation.duplicate_check"
SPAN_QUEUE_SEND = "conversation.queue_send"
SPAN_DB_WRITE = "conversation.db_write"
SPAN_CONSUME_MESSAGE = "conversation.consume_message"
SPAN_CREATE_CONVERSATIONS = "conversation.create_conversations"
# Phase 2: process / generate / send
SPAN_PROCESS_WORKFLOW = "conversation.process_workflow"
SPAN_AUDIO_TO_TEXT = "conversation.audio_to_text"
SPAN_QUERY_REWRITE = "conversation.query_rewrite"
SPAN_GENERATE_WORKFLOW = "conversation.generate_workflow"
SPAN_EMBEDDING = "conversation.embedding"
SPAN_CACHE_QUERY = "conversation.cache_query"
SPAN_GENERATE_ANSWER = "conversation.generate_answer"
SPAN_QUERY_EXPANSION = "conversation.query_expansion"
SPAN_NEEDS_CLARIFICATION = "conversation.needs_clarification"
SPAN_RELATED_QUESTIONS = "conversation.related_questions"
SPAN_SEND_WORKFLOW = "conversation.send_workflow"
SPAN_MARK_READ = "conversation.mark_read"
SPAN_CHANNEL_SEND = "conversation.channel_send"

# Wrapped payload keys
KEY_TRACE = "_trace"
KEY_BODY = "body"

_logger = logging.getLogger(__name__)


def get_conversation_tracer() -> trace.Tracer:
    """Return the tracer for conversation-flow spans."""
    return trace.get_tracer(TRACER_NAME, TRACER_VERSION)


def get_current_otel_trace_context() -> Optional[dict[str, str]]:
    """
    Return current OTEL trace context for linking Langfuse (or other backends).
    Returns {"trace_id": "32 hex", "parent_span_id": "16 hex"} or None if no active span.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return None
    span_ctx = span.get_span_context()
    if not span_ctx or span_ctx.trace_id == 0:
        return None
    return {
        "trace_id": format(span_ctx.trace_id, "032x"),
        "parent_span_id": format(span_ctx.span_id, "016x"),
    }


def inject_trace_context_into_payload(byoeb_message: ByoebMessageContext) -> str:
    """
    Build queue payload, injecting current OTEL trace context when available.

    - If there is an active trace context: returns JSON string of
      {"_trace": {traceparent, tracestate}, "body": "<byoeb_message JSON>"}.
    - Otherwise: returns byoeb_message.model_dump_json() (no wrapper) for backward compatibility.

    Call from producer before queue.send_message.
    """
    body_str = byoeb_message.model_dump_json()
    try:
        carrier: dict = {}
        inject(carrier)
        if not carrier:
            return body_str
        wrapped = {KEY_BODY: body_str, KEY_TRACE: carrier}
        return json.dumps(wrapped)
    except Exception as e:
        _logger.debug("Could not inject trace context into payload: %s. Sending unwrapped.", e)
        return body_str


def parse_queue_payload_and_extract_context(raw: str) -> Tuple[ByoebMessageContext, Optional[context.Context]]:
    """
    Parse a raw queue message and optionally extract trace context.

    - If payload is wrapped (has "body" and "_trace"): parse body as ByoebMessageContext,
      extract context from _trace, return (message, extracted_context).
    - Otherwise: treat raw as ByoebMessageContext JSON, return (message, None).

    Returns:
        (byoeb_message, optional_context). context is None when no _trace or extraction fails.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        _logger.warning("Queue payload is not valid JSON: %s", e)
        raise

    if not isinstance(parsed, dict):
        byoeb_message = ByoebMessageContext.model_validate(parsed)
        return byoeb_message, None

    if KEY_BODY in parsed and KEY_TRACE in parsed:
        body = parsed[KEY_BODY]
        carrier = parsed[KEY_TRACE]
        if isinstance(body, str):
            body_obj = json.loads(body)
        else:
            body_obj = body
        byoeb_message = ByoebMessageContext.model_validate(body_obj)
        try:
            ctx = extract(carrier)
            return byoeb_message, ctx
        except Exception as e:
            _logger.debug("Could not extract trace context from payload: %s", e)
            return byoeb_message, None

    # Legacy: entire payload is the message
    byoeb_message = ByoebMessageContext.model_validate(parsed)
    return byoeb_message, None
