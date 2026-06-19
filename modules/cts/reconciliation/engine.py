"""
CTS Automated Reconciliation Engine.

Matches NGCH-filed instrument records against CBS posting confirmations.
Emits a SessionReconciliationReport with per-item match status.
"""
from __future__ import annotations

from datetime import datetime, timezone

from modules.cts.reconciliation.models import (
    ReconciliationItem,
    ReconciliationStatus,
    SessionReconciliationReport,
)

# CBS statuses that mean "settlement complete"
_CBS_SETTLED = {'POSTED', 'CONFIRMED', 'DEBITED', 'CREDITED'}
# NGCH statuses that mean "filing complete"
_NGCH_SETTLED = {'CONFIRMED', 'RETURNED', 'ACCEPTED'}
# Statuses that mean "in flight — not yet settled"
_PENDING_STATUSES = {'PENDING', 'PROCESSING', 'QUEUED', 'FILED'}


class ReconciliationEngine:
    def reconcile(
        self,
        *,
        session_id:   str,
        bank_id:      str,
        bank_ifsc:    str,
        session_date: datetime,
        ngch_items:   list[dict],
        cbs_items:    list[dict],
    ) -> SessionReconciliationReport:
        ngch_map = {item['instrument_id']: item for item in ngch_items}
        cbs_map  = {item['instrument_id']: item for item in cbs_items}

        all_ids = set(ngch_map) | set(cbs_map)
        recon_items: list[ReconciliationItem] = []

        for instrument_id in sorted(all_ids):
            ngch = ngch_map.get(instrument_id)
            cbs  = cbs_map.get(instrument_id)
            recon_items.append(
                self._classify(instrument_id, session_id, bank_id, ngch, cbs, session_date)
            )

        return SessionReconciliationReport(
            session_id=session_id,
            bank_id=bank_id,
            bank_ifsc=bank_ifsc,
            session_date=session_date,
            items=recon_items,
        )

    def _classify(
        self,
        instrument_id: str,
        session_id:    str,
        bank_id:       str,
        ngch:          dict | None,
        cbs:           dict | None,
        occurred_at:   datetime,
    ) -> ReconciliationItem:
        ngch_status      = (ngch or {}).get('status', '')
        cbs_status       = (cbs  or {}).get('status', '')
        ngch_amount      = (ngch or {}).get('amount_range', '')
        cbs_amount       = (cbs  or {}).get('amount_range', '')

        if ngch and not cbs:
            status = ReconciliationStatus.NGCH_ONLY
            detail = 'NGCH record present; no CBS posting found'
        elif cbs and not ngch:
            status = ReconciliationStatus.CBS_ONLY
            detail = 'CBS posting present; no NGCH record found'
        elif ngch_status in _PENDING_STATUSES or cbs_status in _PENDING_STATUSES:
            status = ReconciliationStatus.PENDING
            detail = f'Settlement in progress (NGCH={ngch_status}, CBS={cbs_status})'
        elif ngch_amount and cbs_amount and ngch_amount != cbs_amount:
            status = ReconciliationStatus.AMOUNT_MISMATCH
            detail = f'Amount range differs: NGCH={ngch_amount} CBS={cbs_amount}'
        else:
            status = ReconciliationStatus.MATCHED
            detail = None

        return ReconciliationItem(
            instrument_id=instrument_id,
            session_id=session_id,
            bank_id=bank_id,
            cheque_number=(ngch or cbs or {}).get('cheque_number', ''),
            account_suffix=(ngch or cbs or {}).get('account_suffix', '0000'),
            ngch_status=ngch_status,
            cbs_status=cbs_status,
            ngch_amount_range=ngch_amount,
            cbs_amount_range=cbs_amount,
            reconciliation_status=status,
            occurred_at=occurred_at,
            detail=detail,
        )
