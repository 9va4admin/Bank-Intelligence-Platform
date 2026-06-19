"""
CTS Lot / Batch Number Manager.

NGCH requires outward cheques to be grouped into numbered lots before submission.
Lot number format: LOT_{IFSC}_{YYYYMMDD}_{SessionID}_{NN}
Max instruments per lot: configurable via config_service (default 200 per NGCH limit).

Usage:
    mgr = LotManager(bank_ifsc='SVCB0000001', session_id='SES-0619-001',
                     session_date=..., max_instruments_per_lot=200)
    lot_number = mgr.auto_assign('CHQ-OUT-00001')
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Lot:
    lot_number: str
    max_instruments: int
    instrument_ids: list[str] = field(default_factory=list)

    @property
    def instrument_count(self) -> int:
        return len(self.instrument_ids)

    @property
    def is_full(self) -> bool:
        return self.instrument_count >= self.max_instruments


class LotManager:
    def __init__(
        self,
        bank_ifsc: str,
        session_id: str,
        session_date: datetime,
        max_instruments_per_lot: int = 200,
    ) -> None:
        self._bank_ifsc = bank_ifsc
        self._session_id = session_id
        self._date_str = session_date.strftime('%Y%m%d')
        self._max = max_instruments_per_lot
        self._lots: dict[str, Lot] = {}
        self._seq: int = 0
        self._instrument_lot_map: dict[str, str] = {}

    def _next_lot_number(self) -> str:
        self._seq += 1
        return f'LOT_{self._bank_ifsc}_{self._date_str}_{self._session_id}_{self._seq:02d}'

    def create_lot(self) -> Lot:
        lot_number = self._next_lot_number()
        lot = Lot(lot_number=lot_number, max_instruments=self._max)
        self._lots[lot_number] = lot
        return lot

    def assign(self, instrument_id: str, lot_number: str) -> None:
        if lot_number not in self._lots:
            raise KeyError(f"Lot '{lot_number}' does not exist")
        self._lots[lot_number].instrument_ids.append(instrument_id)
        self._instrument_lot_map[instrument_id] = lot_number

    def auto_assign(self, instrument_id: str) -> str:
        for lot in self._lots.values():
            if not lot.is_full:
                self.assign(instrument_id, lot.lot_number)
                return lot.lot_number
        lot = self.create_lot()
        self.assign(instrument_id, lot.lot_number)
        return lot.lot_number

    def get_lot_for_instrument(self, instrument_id: str) -> str | None:
        return self._instrument_lot_map.get(instrument_id)

    def list_lots(self) -> list[Lot]:
        return list(self._lots.values())

    def summary(self) -> dict:
        total_assigned = sum(lot.instrument_count for lot in self._lots.values())
        return {
            'total_lots': len(self._lots),
            'total_assigned': total_assigned,
            'unassigned': 0,
        }
