"""
Tests for CTS Scanner SDK Integration (Panini, Canon).
RED phase — all tests must fail before implementation.

The scanner layer abstracts OEM-specific SDK differences behind a common interface.
It accepts raw image bytes from scanner hardware, validates CTS-2010 compliance,
and packages the result for the CTS processing pipeline.
"""
import pytest


# ── OEM enum ─────────────────────────────────────────────────────────────────

def test_scanner_oem_enum_values():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.PANINI
    assert ScannerOEM.CANON
    assert ScannerOEM.GENERIC   # fallback for other / unrecognised OEMs


def test_scanner_oem_display_names():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.PANINI.value  == 'PANINI'
    assert ScannerOEM.CANON.value   == 'CANON'
    assert ScannerOEM.GENERIC.value == 'GENERIC'


# ── ScanResult ───────────────────────────────────────────────────────────────

def test_scan_result_fields():
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    result = ScanResult(
        scan_id='SCAN-20260619-000001',
        oem=ScannerOEM.PANINI,
        scanner_model='Panini I:Deal',
        front_image=b'\xff\xd8\xff',      # JPEG magic bytes
        rear_image=b'\xff\xd8\xff',
        front_dpi=300,
        rear_dpi=300,
        front_file_size_kb=38.2,
        rear_file_size_kb=22.1,
        front_colour_depth=24,
        rear_colour_depth=24,
        micr_raw='⑆123456789⑆ 100001⑈ 012300⑉',
        bank_id='SVCB',
        operator_id='OPR-001',
    )
    assert result.scan_id == 'SCAN-20260619-000001'
    assert result.oem == ScannerOEM.PANINI
    assert result.front_image == b'\xff\xd8\xff'
    assert result.micr_raw.startswith('⑆')


def test_scan_result_has_images():
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    result = ScanResult(
        scan_id='SCAN-001', oem=ScannerOEM.CANON, scanner_model='Canon CR-190i',
        front_image=b'\x89PNG', rear_image=b'\xff\xd8\xff',
        front_dpi=300, rear_dpi=300, front_file_size_kb=40.0, rear_file_size_kb=20.0,
        front_colour_depth=24, rear_colour_depth=24,
        micr_raw='', bank_id='SVCB', operator_id='OPR-001',
    )
    assert result.has_front_image is True
    assert result.has_rear_image  is True


def test_scan_result_missing_image():
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    result = ScanResult(
        scan_id='SCAN-001', oem=ScannerOEM.PANINI, scanner_model='Panini I:Deal',
        front_image=b'', rear_image=b'\xff\xd8\xff',
        front_dpi=300, rear_dpi=300, front_file_size_kb=0.0, rear_file_size_kb=20.0,
        front_colour_depth=24, rear_colour_depth=24,
        micr_raw='', bank_id='SVCB', operator_id='OPR-001',
    )
    assert result.has_front_image is False
    assert result.has_rear_image  is True


# ── ScannerAdapter (abstract interface) ──────────────────────────────────────

def test_panini_adapter_name():
    from modules.cts.scanner.adapters import PaniniAdapter
    adapter = PaniniAdapter(scanner_model='Panini I:Deal', bank_id='SVCB', operator_id='OPR-001')
    assert adapter.oem.value == 'PANINI'
    assert 'Panini' in adapter.scanner_model


def test_canon_adapter_name():
    from modules.cts.scanner.adapters import CanonAdapter
    adapter = CanonAdapter(scanner_model='Canon CR-190i', bank_id='SVCB', operator_id='OPR-001')
    assert adapter.oem.value == 'CANON'
    assert 'Canon' in adapter.scanner_model


def test_panini_adapter_ingest_returns_scan_result():
    from modules.cts.scanner.adapters import PaniniAdapter
    from modules.cts.scanner.models import ScanResult, ScannerOEM

    adapter = PaniniAdapter(scanner_model='Panini I:Deal', bank_id='SVCB', operator_id='OPR-001')
    front_bytes = b'\xff\xd8\xff' + b'\x00' * 1000
    rear_bytes  = b'\xff\xd8\xff' + b'\x00' * 500
    result = adapter.ingest(
        front_image=front_bytes,
        rear_image=rear_bytes,
        front_dpi=300,
        rear_dpi=300,
        micr_raw='⑆123456789⑆ 100001⑈ 012300⑉',
    )
    assert isinstance(result, ScanResult)
    assert result.oem == ScannerOEM.PANINI
    assert result.front_dpi == 300
    assert result.scan_id.startswith('SCAN-')


def test_canon_adapter_ingest_returns_scan_result():
    from modules.cts.scanner.adapters import CanonAdapter
    from modules.cts.scanner.models import ScanResult, ScannerOEM

    adapter = CanonAdapter(scanner_model='Canon CR-190i', bank_id='SVCB', operator_id='OPR-001')
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 800,
        rear_image=b'\xff\xd8\xff'  + b'\x00' * 400,
        front_dpi=200,
        rear_dpi=200,
        micr_raw='',
    )
    assert isinstance(result, ScanResult)
    assert result.oem == ScannerOEM.CANON


def test_adapter_ingest_computes_file_size_kb():
    from modules.cts.scanner.adapters import PaniniAdapter

    adapter = PaniniAdapter(scanner_model='Panini I:Deal', bank_id='SVCB', operator_id='OPR-001')
    front_bytes = b'\x00' * 40_960   # 40 KB exactly
    result = adapter.ingest(
        front_image=front_bytes, rear_image=b'\x00' * 20_480,
        front_dpi=300, rear_dpi=300, micr_raw='',
    )
    assert result.front_file_size_kb == pytest.approx(40.0)
    assert result.rear_file_size_kb  == pytest.approx(20.0)


# ── MICR Parser ───────────────────────────────────────────────────────────────

def test_micr_parser_extracts_fields():
    from modules.cts.scanner.micr import MICRParser
    raw = '⑆123456789⑆ 100001⑈ 012345⑉'
    parsed = MICRParser.parse(raw)
    assert parsed['routing_number'] == '123456789'
    assert parsed['cheque_number']  == '100001'
    # PII rule: only last 4 digits of account stored — never full account number
    assert parsed['account_number_fragment'] == '2345'


def test_micr_parser_empty_returns_none_fields():
    from modules.cts.scanner.micr import MICRParser
    parsed = MICRParser.parse('')
    assert parsed['routing_number']          is None
    assert parsed['cheque_number']           is None
    assert parsed['account_number_fragment'] is None


def test_micr_parser_does_not_log_full_account():
    """MICRParser must never expose full account number — only fragment."""
    from modules.cts.scanner.micr import MICRParser
    raw = '⑆123456789⑆ 100001⑈ 012345678901⑉'   # long account number
    parsed = MICRParser.parse(raw)
    # account_number_fragment must be masked — not the full raw value
    if parsed['account_number_fragment'] is not None:
        assert len(parsed['account_number_fragment']) <= 4   # only last 4 stored


# ── ScanSessionManager ───────────────────────────────────────────────────────

def test_scan_session_manager_accumulates_scans():
    from modules.cts.scanner.session import ScanSessionManager
    from modules.cts.scanner.models import ScanResult, ScannerOEM

    mgr = ScanSessionManager(session_id='SES-0619-001', bank_id='SVCB')

    def make_result(scan_id):
        return ScanResult(
            scan_id=scan_id, oem=ScannerOEM.PANINI, scanner_model='Panini I:Deal',
            front_image=b'\xff\xd8', rear_image=b'\xff\xd8',
            front_dpi=300, rear_dpi=300, front_file_size_kb=38.0, rear_file_size_kb=22.0,
            front_colour_depth=24, rear_colour_depth=24,
            micr_raw='', bank_id='SVCB', operator_id='OPR-001',
        )

    mgr.add_scan(make_result('SCAN-001'))
    mgr.add_scan(make_result('SCAN-002'))
    assert mgr.scan_count == 2


def test_scan_session_manager_duplicate_scan_id_raises():
    from modules.cts.scanner.session import ScanSessionManager
    from modules.cts.scanner.models import ScanResult, ScannerOEM

    mgr = ScanSessionManager(session_id='SES-0619-001', bank_id='SVCB')
    result = ScanResult(
        scan_id='SCAN-001', oem=ScannerOEM.PANINI, scanner_model='Panini I:Deal',
        front_image=b'\xff\xd8', rear_image=b'\xff\xd8',
        front_dpi=300, rear_dpi=300, front_file_size_kb=38.0, rear_file_size_kb=22.0,
        front_colour_depth=24, rear_colour_depth=24,
        micr_raw='', bank_id='SVCB', operator_id='OPR-001',
    )
    mgr.add_scan(result)
    with pytest.raises(ValueError, match='duplicate'):
        mgr.add_scan(result)


# ── MICRParser.parse_ocr_text — vision-OCR text path ──────────────────────────
#
# Corrected 2026-09-24: this assumed a 23-digit layout (6 cheque number + 9
# sort code + 6 account number + 2 transaction code) since it was first
# written. Real Indian CTS-2010 MICR bands are 17 digits (6 + 9 + 2) — there
# is no account number field in MICR at all. The old 23-digit check silently
# rejected every real MICR OCR read (they are genuinely 17 digits), which in
# turn made modules/cts/workflows/cheque_workflow.py's STP multisignal rescue
# gate unsatisfiable on every real cheque, since it depended on this parser
# producing a usable account fragment that could never exist.

def test_parse_ocr_text_real_micr_with_trailing_transaction_code():
    from modules.cts.scanner.micr import MICRParser
    # real OCR read, KBL Lot 2 cheque 178655 (2026-09-24 live run) -- 6-digit
    # cheque number + 9-digit sort code + a variable-length transaction-code
    # tail that nothing downstream consumes.
    result = MICRParser.parse_ocr_text("178655 560052023 090525 29")
    assert result["cheque_number"] == "178655"
    assert result["bank_branch_code"] == "560052023"
    assert "account_number_fragment" not in result


def test_parse_ocr_text_strips_ocr_noise_between_groups():
    from modules.cts.scanner.micr import MICRParser
    # OCR vision models often substitute the real ⑆⑈⑉ delimiters with stray
    # letters/punctuation — must still resolve once digits are isolated.
    result = MICRParser.parse_ocr_text("II*216589**4110520031*250326**31")
    assert result["cheque_number"] == "216589"
    assert result["bank_branch_code"] == "411052003"


def test_parse_ocr_text_short_run_returns_none_not_guess():
    from modules.cts.scanner.micr import MICRParser
    # Fewer than 15 digits (cheque number + sort code) means genuine
    # corruption on the part that matters -- guessing positions would
    # fabricate data.
    result = MICRParser.parse_ocr_text("123456789")
    assert result["cheque_number"] is None
    assert result["bank_branch_code"] is None


def test_parse_ocr_text_empty_returns_none():
    from modules.cts.scanner.micr import MICRParser
    result = MICRParser.parse_ocr_text("")
    assert result["cheque_number"] is None
    assert result["bank_branch_code"] is None
