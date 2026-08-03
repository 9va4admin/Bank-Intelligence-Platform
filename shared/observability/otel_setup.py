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

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_otel(
    service_name: str,
    service_version: str,
    bank_id: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
    prometheus_port: Optional[int] = None,
) -> TracerProvider:
    """
    Initialise the global TracerProvider and MeterProvider for this process.

    In production, OTLP exporter sends spans to the Tempo collector.
    In development/tests, a no-op (non-exporting) provider is used unless
    otlp_endpoint is explicitly provided.

    Metrics mirror the same shape: prometheus_port enables the OTel
    Prometheus exporter (scraped per microservices.md's /metrics endpoint
    convention); otherwise an in-memory reader backs the meter so every
    emit_incident_signal() call still has somewhere real to land in
    dev/test, without requiring a running Prometheus.

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

    if prometheus_port:
        # Import here — avoid hard dependency when the Prometheus exporter
        # package isn't installed, matching the OTLP exporter above.
        from opentelemetry.exporter.prometheus import PrometheusMetricReader  # type: ignore[import]
        metric_reader = PrometheusMetricReader()
    else:
        metric_reader = InMemoryMetricReader()

    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    return provider


def get_tracer(name: str) -> trace.Tracer:
    """Return a named tracer from the globally configured provider."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Return a named meter from the globally configured provider."""
    return metrics.get_meter(name)
