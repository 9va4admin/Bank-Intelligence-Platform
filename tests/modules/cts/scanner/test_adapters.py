# Stub — all tests live in test_scanner.py (consolidated file).
from tests.modules.cts.scanner.test_scanner import (  # noqa: F401
    test_panini_adapter_name,
    test_canon_adapter_name,
    test_panini_adapter_ingest_returns_scan_result,
    test_canon_adapter_ingest_returns_scan_result,
    test_adapter_ingest_computes_file_size_kb,
)


def test_generic_adapter_oem_property():
    """Covers line 87: GenericAdapter.oem property."""
    from modules.cts.scanner.adapters import GenericAdapter, ScannerOEM
    a = GenericAdapter(scanner_model="unknown-model", bank_id="test-bank", operator_id="op1")
    assert a.oem == ScannerOEM.GENERIC


def test_get_adapter_panini():
    """Covers lines 92-98: get_adapter factory returns PaniniAdapter for PANINI."""
    from modules.cts.scanner.adapters import get_adapter, PaniniAdapter
    a = get_adapter("PANINI", "IS-360", "test-bank", "op1")
    assert isinstance(a, PaniniAdapter)


def test_get_adapter_unknown_returns_generic():
    """Covers lines 97-98: get_adapter factory fallback to GenericAdapter."""
    from modules.cts.scanner.adapters import get_adapter, GenericAdapter
    a = get_adapter("FUJIFILM", "X100", "test-bank", "op1")
    assert isinstance(a, GenericAdapter)
