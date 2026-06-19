"""
CTS Reconciliation CSV Exporter.

Generates a downloadable reconciliation report per clearing session.
Filename: RECON_{IFSC}_{YYYYMMDD}_{SessionID}.csv
"""
from __future__ import annotations

import csv
import io

from modules.cts.reconciliation.models import SessionReconciliationReport


class ReconciliationExporter:
    @staticmethod
    def to_csv(report: SessionReconciliationReport) -> str:
        buf = io.StringIO()
        date_str = report.session_date.strftime('%Y-%m-%d')

        # Summary block
        buf.write(f'# ASTRA CTS Reconciliation Report\n')
        buf.write(f'# Bank IFSC: {report.bank_ifsc}\n')
        buf.write(f'# Session: {report.session_id}  Date: {date_str}\n')
        buf.write(f'# Total Items: {report.total_items}  '
                  f'Matched: {report.matched_count}  '
                  f'Unmatched: {report.unmatched_count}  '
                  f'Pending: {report.pending_count}  '
                  f'Match Rate: {report.match_rate}%\n')
        buf.write('#\n')

        writer = csv.writer(buf)
        writer.writerow([
            'InstrumentID', 'ChequeNumber', 'AccountSuffix',
            'NGCHStatus', 'CBSStatus',
            'NGCHAmountRange', 'CBSAmountRange',
            'ReconciliationStatus', 'OccurredAt', 'Detail',
        ])
        for item in report.items:
            writer.writerow([
                item.instrument_id,
                item.cheque_number,
                f'****{item.account_suffix}',
                item.ngch_status,
                item.cbs_status,
                item.ngch_amount_range,
                item.cbs_amount_range,
                item.reconciliation_status.value,
                item.occurred_at.isoformat(),
                item.detail or '',
            ])

        return buf.getvalue()

    @staticmethod
    def filename(report: SessionReconciliationReport) -> str:
        date_str = report.session_date.strftime('%Y%m%d')
        return f'RECON_{report.bank_ifsc}_{date_str}_{report.session_id}.csv'
