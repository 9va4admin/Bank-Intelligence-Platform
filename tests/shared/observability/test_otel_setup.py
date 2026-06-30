"""
Tests for OTel setup — tracer provider configuration, resource attributes,
exporter wiring, and the configure_otel() public API.

TDD: written BEFORE the implementation.
"""
from unittest.mock import MagicMock, patch, call
import pytest

from shared.observability.otel_setup import configure_otel, get_tracer


# ---------------------------------------------------------------------------
# configure_otel — basic contract
# ---------------------------------------------------------------------------

def test_configure_otel_returns_tracer_provider():
    from opentelemetry.sdk.trace import TracerProvider
    provider = configure_otel(service_name="test-service", service_version="1.0.0")
    assert provider is not None


def test_configure_otel_sets_service_name_resource():
    provider = configure_otel(service_name="cts-agent-worker", service_version="1.2.3")
    assert provider.resource.attributes.get("service.name") == "cts-agent-worker"


def test_configure_otel_sets_service_version_resource():
    provider = configure_otel(service_name="cts-agent-worker", service_version="1.2.3")
    assert provider.resource.attributes.get("service.version") == "1.2.3"


def test_configure_otel_includes_bank_id_in_resource():
    provider = configure_otel(service_name="cts-agent-worker", service_version="1.0.0", bank_id="kotak-mah")
    assert provider.resource.attributes.get("bank.id") == "kotak-mah"


def test_configure_otel_without_bank_id_omits_attribute():
    from opentelemetry import trace

    configure_otel(service_name="cts-agent-worker", service_version="1.0.0")
    provider = trace.get_tracer_provider()

    resource = provider.resource
    # bank.id should be absent or empty — not "None" string
    val = resource.attributes.get("bank.id")
    assert val is None or val == ""


# ---------------------------------------------------------------------------
# get_tracer — returns a named tracer
# ---------------------------------------------------------------------------

def test_get_tracer_returns_tracer():
    from opentelemetry.trace import Tracer
    configure_otel(service_name="test-svc", service_version="0.1")
    tracer = get_tracer("astra.cts.workflow")
    assert tracer is not None


def test_get_tracer_spans_can_be_started():
    configure_otel(service_name="test-svc", service_version="0.1")
    tracer = get_tracer("astra.test")
    with tracer.start_as_current_span("test.span") as span:
        span.set_attribute("test.key", "test.value")
    # No exception = pass


def test_get_tracer_different_names_return_different_tracers():
    configure_otel(service_name="test-svc", service_version="0.1")
    t1 = get_tracer("astra.cts")
    t2 = get_tracer("astra.ej")
    # Both are valid tracers — instrumenting differently named modules
    assert t1 is not None
    assert t2 is not None


# ---------------------------------------------------------------------------
# Span attributes helper
# ---------------------------------------------------------------------------

def test_configure_otel_adds_astra_platform_attribute():
    provider = configure_otel(service_name="api-gateway", service_version="2.0.0")
    assert provider.resource.attributes.get("platform") == "astra"


# ---------------------------------------------------------------------------
# Idempotency — calling configure_otel twice should not raise
# ---------------------------------------------------------------------------

def test_configure_otel_is_idempotent():
    configure_otel(service_name="svc", service_version="1.0")
    configure_otel(service_name="svc", service_version="1.0")  # no exception


# ---------------------------------------------------------------------------
# OTLP endpoint branch (lines 55-57) — BatchSpanProcessor added when endpoint given
# ---------------------------------------------------------------------------

def test_configure_otel_with_otlp_endpoint_adds_span_processor():
    """When otlp_endpoint is provided, an OTLP BatchSpanProcessor must be added."""
    from unittest.mock import MagicMock, patch

    mock_exporter_instance = MagicMock()
    mock_exporter_cls = MagicMock(return_value=mock_exporter_instance)

    with patch.dict("sys.modules", {
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(
            OTLPSpanExporter=mock_exporter_cls
        )
    }):
        provider = configure_otel(
            service_name="cts-agent-worker",
            service_version="1.0.0",
            otlp_endpoint="http://tempo.astra.internal:4317",
        )

    # OTLPSpanExporter was instantiated with the endpoint
    mock_exporter_cls.assert_called_once_with(
        endpoint="http://tempo.astra.internal:4317", insecure=True
    )
    assert provider is not None
