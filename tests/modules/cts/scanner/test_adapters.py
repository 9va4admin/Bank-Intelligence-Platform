# Stub — all tests live in test_scanner.py (consolidated file).
from tests.modules.cts.scanner.test_scanner import (  # noqa: F401
    test_panini_adapter_name,
    test_canon_adapter_name,
    test_panini_adapter_ingest_returns_scan_result,
    test_canon_adapter_ingest_returns_scan_result,
    test_adapter_ingest_computes_file_size_kb,
)
