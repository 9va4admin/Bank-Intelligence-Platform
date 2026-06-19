# Stub — all tests live in test_endorsement.py (consolidated file).
from tests.modules.cts.endorsement.test_endorsement import (  # noqa: F401
    test_endorsement_template_fields,
    test_endorsement_template_is_frozen,
    test_endorsement_record_valid_suffix,
    test_endorsement_record_rejects_suffix_over_4_chars,
    test_endorsement_record_allows_short_suffix,
)
