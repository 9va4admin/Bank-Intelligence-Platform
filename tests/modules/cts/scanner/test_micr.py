# Stub — all tests live in test_scanner.py (consolidated file).
from tests.modules.cts.scanner.test_scanner import (  # noqa: F401
    test_micr_parser_extracts_fields,
    test_micr_parser_empty_returns_none_fields,
    test_micr_parser_does_not_log_full_account,
)


def test_extract_account_last4_no_match_returns_none():
    """Covers line 67: _extract_account_last4 returns None when no match."""
    from modules.cts.scanner.micr import MICRParser
    # Raw string with no proper MICR amount/on-us delimiters → no match
    result = MICRParser._extract_account_last4("no delimiters here")
    assert result is None
