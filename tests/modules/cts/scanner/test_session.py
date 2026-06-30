# Stub — all tests live in test_scanner.py (consolidated file).
from tests.modules.cts.scanner.test_scanner import (  # noqa: F401
    test_scan_session_manager_accumulates_scans,
    test_scan_session_manager_duplicate_scan_id_raises,
)


def _make_scan(scan_id="s1"):
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    return ScanResult(
        scan_id=scan_id, oem=ScannerOEM.PANINI, scanner_model="IS360",
        front_image=b"f", rear_image=b"r", front_dpi=200, rear_dpi=200,
        front_file_size_kb=10.0, rear_file_size_kb=10.0,
        front_colour_depth=8, rear_colour_depth=8,
        micr_raw="raw", bank_id="test-bank", operator_id="op1",
    )


def test_list_scans_returns_all_added():
    """Covers line 30: list_scans returns list of values."""
    from modules.cts.scanner.session import ScanSessionManager
    mgr = ScanSessionManager("sess-001", "test-bank")
    mgr.add_scan(_make_scan("s1"))
    mgr.add_scan(_make_scan("s2"))
    scans = mgr.list_scans()
    assert len(scans) == 2


def test_get_scan_returns_none_for_missing_id():
    """Covers line 33: get_scan returns None when scan_id not found."""
    from modules.cts.scanner.session import ScanSessionManager
    mgr = ScanSessionManager("sess-002", "test-bank")
    result = mgr.get_scan("nonexistent-id")
    assert result is None
