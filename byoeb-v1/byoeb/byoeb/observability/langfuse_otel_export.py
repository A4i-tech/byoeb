"""
Register an OTLP span exporter to Langfuse so conversation-flow OTEL spans
(conversation.process_workflow, conversation.query_rewrite, etc.) appear in
Langfuse alongside SDK-reported generations, giving the full trace hierarchy.

Only runs when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
Must be called after the global TracerProvider is set (e.g. after Azure Monitor).
"""

import base64
import logging
import os

logger = logging.getLogger(__name__)


def setup_langfuse_otel_export() -> None:
    """
    If Langfuse keys are set, add an OTLP span exporter to the global
    TracerProvider so our OTEL spans are sent to Langfuse and the trace
    tree (process_workflow → query_rewrite → llm_translation_..., etc.) is visible.
    """
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        logger.debug("Langfuse OTLP export skipped: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY unset.")
        return

    base_url = (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    ).rstrip("/")
    # OTLP traces endpoint: Langfuse expects /api/public/otel/v1/traces
    endpoint = f"{base_url}/api/public/otel"
    auth_string = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_string}",
        "x-langfuse-ingestion-version": "4",
    }

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning("Langfuse OTLP export skipped: missing dependency %s", e)
        return

    # Suppress noisy ERROR logs from the OTLP exporter when the endpoint returns
    # a non-2xx (e.g. 404 on local Langfuse instances without OTLP support).
    logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.CRITICAL)

    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    processor = BatchSpanProcessor(exporter)
    provider = trace.get_tracer_provider()

    if isinstance(provider, TracerProvider) and hasattr(provider, "add_span_processor"):
        try:
            provider.add_span_processor(processor)
            logger.info("Langfuse OTLP trace export enabled: endpoint=%s", endpoint)
        except Exception as e:
            logger.warning("Langfuse OTLP export setup failed: %s", e)
        return

    # No SDK TracerProvider yet (e.g. local dev without Azure): create one so spans reach Langfuse
    try:
        resource = Resource.create({"service.name": "byoeb"})
        new_provider = TracerProvider(resource=resource)
        new_provider.add_span_processor(processor)
        trace.set_tracer_provider(new_provider)
        logger.info("Langfuse OTLP trace export enabled (new TracerProvider): endpoint=%s", endpoint)
    except Exception as e:
        logger.warning("Langfuse OTLP export setup failed: %s", e)
