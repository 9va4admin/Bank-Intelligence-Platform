# Stub — all tests live in test_scanner.py (consolidated file).
from tests.modules.cts.scanner.test_scanner import (  # noqa: F401
    test_micr_parser_extracts_fields,
    test_micr_parser_empty_returns_none_fields,
    test_micr_parser_does_not_log_full_account,
)
