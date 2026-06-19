# Stub — model tests live in test_compliance.py (consolidated).
# Satisfies pre-commit TDD pairing hook for models.py.
from tests.modules.cts.compliance.test_compliance import (  # noqa: F401
    test_instrument_compliance_record_pass,
    test_instrument_compliance_record_fail_low_dpi,
    test_instrument_compliance_record_fail_large_file,
    test_instrument_compliance_record_fail_low_micr,
    test_batch_certificate_all_pass,
    test_batch_certificate_fail_if_any_instrument_fails,
)
