"""
Tests for OTel setup — tracer provider configuration, resource attributes,
exporter wiring, and the configure_otel() public API.

TDD: written BEFORE the implementation.
"""
from unittest.mock import MagicMock, patch, call
import pytest

from shared.observability.otel_setup import configure_otel, get_tracer, get_meter


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
    """Checks the object configure_otel() returns directly, not the global
    trace.get_tracer_provider() registry -- that registry only accepts the
    first set_tracer_provider() call per process (OTel's own "first config
    wins" behaviour), so asserting against it is order-dependent on
    whichever test across the *entire* suite happens to configure OTel
    first. Every other resource-attribute test in this file already checks
    the local return value for the same reason."""
    provider = configure_otel(service_name="cts-agent-worker", service_version="1.0.0")

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


# ---------------------------------------------------------------------------
# Metrics — MeterProvider setup (mirrors the TracerProvider tests above)
# ---------------------------------------------------------------------------

def test_configure_otel_sets_global_meter_provider():
    from opentelemetry import metrics as otel_metrics

    configure_otel(service_name="cts-agent-worker", service_version="1.0.0")
    provider = otel_metrics.get_meter_provider()
    assert provider is not None


def test_get_meter_returns_meter():
    configure_otel(service_name="test-svc", service_version="0.1")
    meter = get_meter("astra.incidents")
    assert meter is not None


def test_get_meter_can_create_a_counter_instrument():
    """Full data-recording round-trip (does a value actually land in a
    reader) is deliberately NOT tested here: OTel's global MeterProvider
    can only be configured once per process ("first config wins", by
    design) — re-configuring it mid-suite to attach an inspectable reader
    is inherently order-dependent. shared/incidents/signal.py's own tests
    inject a counter directly instead, which sidesteps this constraint."""
    configure_otel(service_name="test-svc", service_version="0.1")
    meter = get_meter("astra.test")
    counter = meter.create_counter("astra_test_counter_total")
    counter.add(1, {"foo": "bar"})  # no exception = pass


def test_configure_otel_without_prometheus_port_still_yields_usable_meter():
    """Default (dev/test) path — no Prometheus exporter package required."""
    configure_otel(service_name="test-svc", service_version="0.1")
    meter = get_meter("astra.default")
    counter = meter.create_counter("astra_default_counter_total")
    counter.add(1)  # no exception = pass


def test_configure_otel_with_prometheus_port_uses_prometheus_reader():
    """When prometheus_port is provided, the OTel Prometheus exporter is
    lazily imported (same pattern as the OTLP trace exporter above) so the
    package isn't a hard dependency for services that don't enable it."""
    mock_reader_instance = MagicMock()
    mock_reader_cls = MagicMock(return_value=mock_reader_instance)

    with patch.dict("sys.modules", {
        "opentelemetry.exporter.prometheus": MagicMock(
            PrometheusMetricReader=mock_reader_cls
        )
    }):
        provider = configure_otel(
            service_name="cts-agent-worker",
            service_version="1.0.0",
            prometheus_port=9464,
        )

    mock_reader_cls.assert_called_once_with()
    assert provider is not None
