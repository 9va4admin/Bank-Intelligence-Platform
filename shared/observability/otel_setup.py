"""
OpenTelemetry setup for all ASTRA services.

Call configure_otel() once in each service's lifespan startup — before any
span is emitted. Never call at module import level (breaks testing).

Usage:
    from shared.observability.otel_setup import configure_otel, get_tracer

    # In FastAPI lifespan or Temporal worker main():
    configure_otel(service_name="cts-agent-worker", service_version="1.3.2", bank_id=bank_id)

    # In any module that emits spans:
    tracer = get_tracer("astra.cts.workflow")
    with tracer.start_as_current_span("activity.ocr_extract") as span:
        span.set_attribute("bank_id", bank_id)
"""
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_otel(
    service_name: str,
    service_version: str,
    bank_id: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
) -> TracerProvider:
    """
    Initialise the global TracerProvider for this process.

    In production, OTLP exporter sends spans to the Tempo collector.
    In development/tests, a no-op (non-exporting) provider is used unless
    otlp_endpoint is explicitly provided.

    Idempotent — safe to call multiple times (subsequent calls are no-ops if
    the provider type is already set).
    """
    attributes: dict = {
        "service.name": service_name,
        "service.version": service_version,
        "platform": "astra",
    }
    if bank_id:
        attributes["bank.id"] = bank_id

    resource = Resource.create(attributes)
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        # Import here — avoid hard dependency when OTLP exporter not installed
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[import]
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> trace.Tracer:
    """Return a named tracer from the globally configured provider."""
    return trace.get_tracer(name)
