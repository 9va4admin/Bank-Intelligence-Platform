"""
TDD — scanner drop-folder mapper.

RED step: all tests fail until modules/cts/scanner/mapper.py is implemented.

Covers:
  - ScannerConfig Pydantic model validation
  - ScannedChequeInput canonical model
  - OEM enum expansion (DIGITAL_CHECK, MAGTEK, RDM, OPEX)
  - CSV (pipe, comma, tab) metadata parsing
  - XML metadata parsing
  - Field mapping (OEM field name → canonical)
  - Amount parsing: DECIMAL_COMMA, DECIMAL_DOT, INTEGER_PAISE (Indian format)
  - Date parsing via strptime pattern
  - Image path resolution per OEM naming pattern
  - Account number: HMAC-hashed, suffix stored — never plain
  - Missing required field → ScannerMappingError
  - Unknown image side code → ScannerMappingError
"""
from __future__ import annotations

import textwrap
from decimal import Decimal
from pathlib import Path

import pytest


# ── helpers ─────────────────────────────────────────────────────────────────

def _panini_cfg(tmp_path: Path, **overrides):
    from modules.cts.scanner.mapper import ScannerConfig, ScannerOEM

    defaults = dict(
        scanner_config_id="cfg-001",
        bank_id="test-bank",
        branch_id="branch-001",
        scanner_oem=ScannerOEM.PANINI,
        scanner_model="Panini Vision X",
        output_format="CSV_PIPE",
        date_format="%d%m%Y",
        amount_format="DECIMAL_COMMA",
        field_mapping={
            "MICR_DATA":    "micr_line",
            "AMT_FIGURES":  "amount_figures",
            "AMT_WORDS":    "amount_words",
            "PAYEE_NM":     "payee_name",
            "CHQ_DATE":     "cheque_date",
            "BATCH_ID":     "batch_id",
            "SEQ":          "sequence_in_batch",
            "ACCT_NO":      "account_number",
            "CONFIDENCE":   "oem_confidence",
        },
        image_naming_pattern="{batch_id}_{seq:04d}_{side}.tif",
        image_side_mapping={"F": "color_front", "G": "grey_front", "R": "rear"},
        drop_folder_path=str(tmp_path),
    )
    defaults.update(overrides)
    return ScannerConfig(**defaults)


def _digital_check_cfg(tmp_path: Path):
    from modules.cts.scanner.mapper import ScannerConfig, ScannerOEM

    return ScannerConfig(
        scanner_config_id="cfg-002",
        bank_id="test-bank",
        branch_id="branch-002",
        scanner_oem=ScannerOEM.DIGITAL_CHECK,
        scanner_model="TS240",
        output_format="XML",
        date_format="%Y-%m-%d",
        amount_format="DECIMAL_DOT",
        field_mapping={
            "MICRLine":     "micr_line",
            "AmountNum":    "amount_figures",
            "AmountWords":  "amount_words",
            "Payee":        "payee_name",
            "ChequeDate":   "cheque_date",
            "BatchID":      "batch_id",
            "Sequence":     "sequence_in_batch",
            "AccountNo":    "account_number",
        },
        image_naming_pattern="DCF{seq:06d}.tif|DCG{seq:06d}.tif|DCR{seq:06d}.tif",
        image_side_mapping={"color_front": "color_front", "grey_front": "grey_front", "rear": "rear"},
        drop_folder_path=str(tmp_path),
    )


def _magtek_cfg(tmp_path: Path):
    from modules.cts.scanner.mapper import ScannerConfig, ScannerOEM

    return ScannerConfig(
        scanner_config_id="cfg-003",
        bank_id="test-bank",
        branch_id="branch-003",
        scanner_oem=ScannerOEM.MAGTEK,
        scanner_model="Excella STX",
        output_format="CSV_COMMA",
        date_format="%d/%m/%Y",
        amount_format="INTEGER_PAISE",
        field_mapping={
            "micr":         "micr_line",
            "amount_paise": "amount_figures",
            "amt_words":    "amount_words",
            "payee":        "payee_name",
            "date":         "cheque_date",
            "batch":        "batch_id",
            "seq":          "sequence_in_batch",
            "account":      "account_number",
        },
        image_naming_pattern="{batch_id}_{seq:04d}_{side}.tif",
        image_side_mapping={"C": "color_front", "G": "grey_front", "B": "rear"},
        drop_folder_path=str(tmp_path),
    )


# ── ScannerOEM enum expansion ────────────────────────────────────────────────

def test_scanner_oem_has_digital_check():
    from modules.cts.scanner.mapper import ScannerOEM
    assert ScannerOEM.DIGITAL_CHECK == "DIGITAL_CHECK"


def test_scanner_oem_has_magtek():
    from modules.cts.scanner.mapper import ScannerOEM
    assert ScannerOEM.MAGTEK == "MAGTEK"


def test_scanner_oem_has_rdm():
    from modules.cts.scanner.mapper import ScannerOEM
    assert ScannerOEM.RDM == "RDM"


def test_scanner_oem_has_opex():
    from modules.cts.scanner.mapper import ScannerOEM
    assert ScannerOEM.OPEX == "OPEX"


# ── ScannerConfig Pydantic model ─────────────────────────────────────────────

def test_scanner_config_valid_instantiation(tmp_path):
    cfg = _panini_cfg(tmp_path)
    assert cfg.scanner_config_id == "cfg-001"
    assert cfg.bank_id == "test-bank"
    assert cfg.output_format == "CSV_PIPE"


def test_scanner_config_invalid_output_format(tmp_path):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _panini_cfg(tmp_path, output_format="YAML")


def test_scanner_config_invalid_amount_format(tmp_path):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _panini_cfg(tmp_path, amount_format="FLOAT")


# ── ScannedChequeInput model ─────────────────────────────────────────────────

def test_scanned_cheque_input_has_required_fields():
    from modules.cts.scanner.mapper import ScannedChequeInput
    # just check it's importable and has the key attributes
    import inspect
    fields = inspect.get_annotations(ScannedChequeInput, eval_str=True)
    assert "micr_line" in fields
    assert "account_number_hash" in fields
    assert "account_suffix" in fields
    assert "amount_figures" in fields
    assert "image_color_path" in fields
    assert "image_grey_path" in fields
    assert "image_rear_path" in fields


# ── Amount parsing ───────────────────────────────────────────────────────────

def test_amount_decimal_comma_indian_format(tmp_path):
    """1,23,456.00 (Indian lakh notation) → Decimal('123456.00')"""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    assert mapper._parse_amount("1,23,456.00") == Decimal("123456.00")


def test_amount_decimal_comma_plain(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    assert mapper._parse_amount("50000.00") == Decimal("50000.00")


def test_amount_decimal_dot_format(tmp_path):
    """Standard dot decimal — DECIMAL_DOT format."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_digital_check_cfg(tmp_path))
    assert mapper._parse_amount("123456.50") == Decimal("123456.50")


def test_amount_integer_paise(tmp_path):
    """INTEGER_PAISE: 12345600 paise → Decimal('123456.00')"""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_magtek_cfg(tmp_path))
    assert mapper._parse_amount("12345600") == Decimal("123456.00")


def test_amount_zero(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    assert mapper._parse_amount("0.00") == Decimal("0.00")


# ── Date parsing ─────────────────────────────────────────────────────────────

def test_date_parsing_ddmmyyyy(tmp_path):
    from datetime import date
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    assert mapper._parse_date("04072026") == date(2026, 7, 4)


def test_date_parsing_iso(tmp_path):
    from datetime import date
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_digital_check_cfg(tmp_path))
    assert mapper._parse_date("2026-07-04") == date(2026, 7, 4)


def test_date_parsing_ddslashmmslashyyyy(tmp_path):
    from datetime import date
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_magtek_cfg(tmp_path))
    assert mapper._parse_date("04/07/2026") == date(2026, 7, 4)


# ── Account masking ──────────────────────────────────────────────────────────

def test_account_is_hashed_not_stored_plain(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    hashed, suffix = mapper._process_account("1234567890123456")
    assert "1234567890123456" not in hashed    # never plain in hash
    assert suffix == "3456"
    assert len(hashed) == 64                   # SHA-256 hex digest length


def test_account_suffix_last_4(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    _, suffix = mapper._process_account("9876543210")
    assert suffix == "3210"


def test_account_hash_is_deterministic(tmp_path):
    """Same account + same bank_id → same hash. Salt is bank-specific."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    h1, _ = mapper._process_account("111122223333")
    h2, _ = mapper._process_account("111122223333")
    assert h1 == h2


def test_different_accounts_different_hashes(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper
    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    h1, _ = mapper._process_account("111122223333")
    h2, _ = mapper._process_account("444455556666")
    assert h1 != h2


# ── CSV parsing — Panini (pipe-delimited) ────────────────────────────────────

def test_parse_panini_csv_single_cheque(tmp_path):
    """Full round-trip: pipe CSV → ScannedChequeInput list."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    # Create image stubs so path resolution doesn't fail
    (tmp_path / "BATCH001_0001_F.tif").write_bytes(b"")
    (tmp_path / "BATCH001_0001_G.tif").write_bytes(b"")
    (tmp_path / "BATCH001_0001_R.tif").write_bytes(b"")

    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO|CONFIDENCE\n"
        "123456789012345|1,00,000.00|One Lakh|Nilesh Shah|04072026|BATCH001|1|9876543210|0.98\n"
    )
    meta_file = tmp_path / "BATCH001.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)

    assert len(results) == 1
    r = results[0]
    assert r.amount_figures == Decimal("100000.00")
    assert r.amount_words == "One Lakh"
    assert r.account_suffix == "3210"
    assert "9876543210" not in r.account_number_hash
    assert r.oem_confidence == pytest.approx(0.98)
    assert r.image_color_path == tmp_path / "BATCH001_0001_F.tif"
    assert r.image_grey_path  == tmp_path / "BATCH001_0001_G.tif"
    assert r.image_rear_path  == tmp_path / "BATCH001_0001_R.tif"


def test_parse_panini_csv_multiple_cheques(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    for i in range(1, 4):
        (tmp_path / f"BATCH002_{i:04d}_F.tif").write_bytes(b"")
        (tmp_path / f"BATCH002_{i:04d}_G.tif").write_bytes(b"")
        (tmp_path / f"BATCH002_{i:04d}_R.tif").write_bytes(b"")

    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"
        "111|50,000.00|Fifty Thousand|ABC|04072026|BATCH002|1|1111111111\n"
        "222|75,000.00|Seventy Five Thousand|DEF|04072026|BATCH002|2|2222222222\n"
        "333|25,000.00|Twenty Five Thousand|GHI|04072026|BATCH002|3|3333333333\n"
    )
    meta_file = tmp_path / "BATCH002.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)
    assert len(results) == 3
    assert results[0].sequence_in_batch == 1
    assert results[1].sequence_in_batch == 2
    assert results[2].sequence_in_batch == 3


# ── CSV parsing — Magtek (comma-delimited) ───────────────────────────────────

def test_parse_magtek_csv_paise_amount(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    (tmp_path / "MB001_0001_C.tif").write_bytes(b"")
    (tmp_path / "MB001_0001_G.tif").write_bytes(b"")
    (tmp_path / "MB001_0001_B.tif").write_bytes(b"")

    csv_content = (
        "micr,amount_paise,amt_words,payee,date,batch,seq,account\n"
        "111222333,5000000,Fifty Thousand,Test Corp,04/07/2026,MB001,1,4444444444\n"
    )
    meta_file = tmp_path / "MB001.csv"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_magtek_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)
    assert len(results) == 1
    assert results[0].amount_figures == Decimal("50000.00")


# ── XML parsing — Digital Check ─────────────────────────────────────────────

def test_parse_digital_check_xml(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    # Digital Check uses positional image files (explicit pattern with color_front/grey_front/rear)
    (tmp_path / "DCF000001.tif").write_bytes(b"")
    (tmp_path / "DCG000001.tif").write_bytes(b"")
    (tmp_path / "DCR000001.tif").write_bytes(b"")

    xml_content = textwrap.dedent("""\
        <?xml version="1.0"?>
        <Batch id="DC2026070401">
          <Item>
            <MICRLine>000100002000300004</MICRLine>
            <AmountNum>250000.00</AmountNum>
            <AmountWords>Two Lakh Fifty Thousand</AmountWords>
            <Payee>Rohan Mehta</Payee>
            <ChequeDate>2026-07-04</ChequeDate>
            <BatchID>DC2026070401</BatchID>
            <Sequence>1</Sequence>
            <AccountNo>5555555555</AccountNo>
          </Item>
        </Batch>
    """)
    meta_file = tmp_path / "DC2026070401.xml"
    meta_file.write_text(xml_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_digital_check_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)
    assert len(results) == 1
    r = results[0]
    assert r.amount_figures == Decimal("250000.00")
    assert r.account_suffix == "5555"


# ── Image path resolution ────────────────────────────────────────────────────

def test_image_paths_missing_raises_error(tmp_path):
    """If image files referenced in metadata do not exist → ScannerMappingError."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper, ScannerMappingError

    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"
        "111|10,000.00|Ten Thousand|XYZ|04072026|NOBATCH|1|1234567890\n"
    )
    meta_file = tmp_path / "NOBATCH.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    with pytest.raises(ScannerMappingError, match="image.*not found|missing"):
        mapper.parse_metadata_file(meta_file)


def test_unknown_image_side_code_raises_error(tmp_path):
    """OEM config has side code 'X' not in image_side_mapping → ScannerMappingError."""
    from modules.cts.scanner.mapper import ScannerConfig, ScannerOEM, ScannerDropFolderMapper, ScannerMappingError

    cfg = _panini_cfg(tmp_path, image_side_mapping={"F": "color_front"})  # missing G and R
    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"
        "111|10,000.00|Ten Thousand|XYZ|04072026|ERR001|1|1234567890\n"
    )
    meta_file = tmp_path / "ERR001.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    # Create only the color_front image — grey and rear missing from mapping
    (tmp_path / "ERR001_0001_F.tif").write_bytes(b"")

    mapper = ScannerDropFolderMapper(cfg)
    with pytest.raises(ScannerMappingError):
        mapper.parse_metadata_file(meta_file)


# ── Missing required field ───────────────────────────────────────────────────

def test_missing_required_field_raises_error(tmp_path):
    """CSV row missing 'AMT_FIGURES' (a required canonical field) → ScannerMappingError."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper, ScannerMappingError

    csv_content = (
        "MICR_DATA|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"  # no AMT_FIGURES header
        "111|One Lakh|XYZ|04072026|MISS001|1|1234567890\n"
    )
    meta_file = tmp_path / "MISS001.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    with pytest.raises(ScannerMappingError, match="amount_figures|required"):
        mapper.parse_metadata_file(meta_file)


def test_missing_micr_line_raises_error(tmp_path):
    from modules.cts.scanner.mapper import ScannerDropFolderMapper, ScannerMappingError

    csv_content = (
        "AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"  # no MICR_DATA
        "10,000.00|Ten Thousand|XYZ|04072026|MISS002|1|1234567890\n"
    )
    meta_file = tmp_path / "MISS002.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    with pytest.raises(ScannerMappingError, match="micr_line|required"):
        mapper.parse_metadata_file(meta_file)


# ── Scan ID format ───────────────────────────────────────────────────────────

def test_scan_id_format(tmp_path):
    """scan_id must follow SCAN-{YYYYMMDD}-{UUID[:8]} pattern."""
    import re
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    (tmp_path / "ID001_0001_F.tif").write_bytes(b"")
    (tmp_path / "ID001_0001_G.tif").write_bytes(b"")
    (tmp_path / "ID001_0001_R.tif").write_bytes(b"")

    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"
        "111|10,000.00|Ten Thousand|XYZ|04072026|ID001|1|1234567890\n"
    )
    meta_file = tmp_path / "ID001.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)
    assert re.match(r"^SCAN-\d{8}-[A-F0-9]{8}$", results[0].scan_id)


# ── oem_confidence is optional ───────────────────────────────────────────────

def test_oem_confidence_none_when_not_in_csv(tmp_path):
    """If scanner doesn't provide confidence (field absent from CSV) → None, not error."""
    from modules.cts.scanner.mapper import ScannerDropFolderMapper

    (tmp_path / "CONF001_0001_F.tif").write_bytes(b"")
    (tmp_path / "CONF001_0001_G.tif").write_bytes(b"")
    (tmp_path / "CONF001_0001_R.tif").write_bytes(b"")

    csv_content = (
        "MICR_DATA|AMT_FIGURES|AMT_WORDS|PAYEE_NM|CHQ_DATE|BATCH_ID|SEQ|ACCT_NO\n"
        "111|10,000.00|Ten Thousand|XYZ|04072026|CONF001|1|1234567890\n"
    )
    meta_file = tmp_path / "CONF001.dat"
    meta_file.write_text(csv_content, encoding="utf-8")

    mapper = ScannerDropFolderMapper(_panini_cfg(tmp_path))
    results = mapper.parse_metadata_file(meta_file)
    assert results[0].oem_confidence is None
