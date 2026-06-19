"""
DiscrepancyExporter — produces CSV reports for CTS exception/discrepancy data.
Consumed by the frontend download endpoint and admin reports.
"""
import csv
import io

from .models import DiscrepancyReport


class DiscrepancyExporter:

    @staticmethod
    def to_csv(report: DiscrepancyReport) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)

        # Summary block
        writer.writerow(['# CTS Discrepancy / Exception Report'])
        writer.writerow(['# Bank IFSC', report.bank_ifsc])
        writer.writerow(['# Session ID', report.session_id])
        writer.writerow(['# Clearing Date', report.clearing_date.strftime('%Y-%m-%d')])
        writer.writerow(['# Generated At', report.generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')])
        writer.writerow(['# Total Instruments', report.total_instruments_processed])
        writer.writerow(['# Total Exceptions', report.total_exceptions])
        writer.writerow(['# Unresolved', report.unresolved_count])
        writer.writerow([])

        # Header row
        writer.writerow([
            'InstrumentID', 'ExceptionType', 'Label', 'Severity',
            'OccurredAt', 'Detail', 'Resolved', 'MarginSeconds',
        ])

        # Data rows
        for item in report.exceptions:
            writer.writerow([
                item.instrument_id,
                item.exception_type.code,
                item.exception_type.label,
                item.exception_type.severity,
                item.occurred_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
                item.detail,
                'Yes' if item.resolved else 'No',
                item.margin_seconds if item.margin_seconds is not None else '',
            ])

        return buf.getvalue()

    @staticmethod
    def filename(report: DiscrepancyReport) -> str:
        """Convention: DISC_{IFSC}_{YYYYMMDD}_{SessionID}.csv"""
        date_str = report.clearing_date.strftime('%Y%m%d')
        return f'DISC_{report.bank_ifsc}_{date_str}_{report.session_id}.csv'
