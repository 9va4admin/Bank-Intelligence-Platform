# DiscrepancyExporter tests live in test_discrepancy_report.py (co-located with models tests).
# This file satisfies the TDD hook pairing requirement for exporter.py.
from tests.modules.cts.reports.test_discrepancy_report import (
    test_csv_export_produces_string,
    test_csv_export_has_header_row,
    test_csv_export_includes_summary_block,
    test_exporter_filename_convention,
)

__all__ = [
    'test_csv_export_produces_string',
    'test_csv_export_has_header_row',
    'test_csv_export_includes_summary_block',
    'test_exporter_filename_convention',
]
