# DiscrepancyReport model tests live in test_discrepancy_report.py.
# This file satisfies the TDD hook pairing requirement for models.py.
from tests.modules.cts.reports.test_discrepancy_report import (
    test_exception_item_requires_minimum_fields,
    test_exception_type_enum_has_required_types,
    test_exception_type_has_label_and_severity,
    test_exception_item_iet_near_breach_stores_margin,
    test_discrepancy_report_totals,
    test_discrepancy_report_detects_critical,
    test_discrepancy_report_counts_by_type,
)

__all__ = [
    'test_exception_item_requires_minimum_fields',
    'test_exception_type_enum_has_required_types',
    'test_exception_type_has_label_and_severity',
    'test_exception_item_iet_near_breach_stores_margin',
    'test_discrepancy_report_totals',
    'test_discrepancy_report_detects_critical',
    'test_discrepancy_report_counts_by_type',
]
