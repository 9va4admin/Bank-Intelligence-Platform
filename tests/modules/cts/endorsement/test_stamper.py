# Stub — all tests live in test_endorsement.py (consolidated file).
from tests.modules.cts.endorsement.test_endorsement import (  # noqa: F401
    test_stamper_returns_record_with_correct_fields,
    test_stamper_applied_at_is_utc,
    test_stamper_stamped_bytes_larger_than_original,
    test_stamper_stamped_bytes_start_with_original,
    test_stamper_qr_data_contains_ifsc_and_instrument,
)
