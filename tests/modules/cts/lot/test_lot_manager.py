"""
Tests for CTS Lot / Batch Number Manager.

Lots are NGCH clearing submission units — they are scoped to a clearing session
slot (AM / PM / EVE on a given date), NOT to a scan session.

Lot number format: LOT_{IFSC}_{YYYYMMDD}_{SLOT}_{NN}
  e.g.  LOT_SVCB0000001_20260720_AM_01
Max instruments per lot: configurable, default 200 (NGCH limit).
"""
import pytest
from datetime import datetime, timezone


def test_lot_number_format():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    lot = mgr.create_lot()
    assert lot.lot_number.startswith('LOT_SVCB0000001_')
    assert '20260619' in lot.lot_number
    assert '_AM_' in lot.lot_number
    assert lot.lot_number.endswith('_01')


def test_lot_number_does_not_contain_session_id():
    """Lot number must not embed a scan session ID — that coupling is removed."""
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    lot = mgr.create_lot()
    # Old format contained 'SES-' — new format must not
    assert 'SES-' not in lot.lot_number


def test_second_lot_has_sequence_02():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    mgr.create_lot()
    lot2 = mgr.create_lot()
    assert lot2.lot_number.endswith('_02')


def test_lot_starts_empty():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    lot = mgr.create_lot()
    assert lot.instrument_count == 0
    assert lot.is_full is False


def test_assign_instrument_to_lot():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='PM',
        max_instruments_per_lot=5,
    )
    lot = mgr.create_lot()
    mgr.assign('CHQ-OUT-00001', lot.lot_number)
    mgr.assign('CHQ-OUT-00002', lot.lot_number)
    assert lot.instrument_count == 2


def test_lot_is_full_at_max():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=3,
    )
    lot = mgr.create_lot()
    for i in range(3):
        mgr.assign(f'CHQ-OUT-0000{i}', lot.lot_number)
    assert lot.is_full is True


def test_assign_to_unknown_lot_raises():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    with pytest.raises(KeyError):
        mgr.assign('CHQ-001', 'LOT_NONEXISTENT')


def test_get_lot_for_instrument():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='EVE',
        max_instruments_per_lot=200,
    )
    lot = mgr.create_lot()
    mgr.assign('CHQ-OUT-00001', lot.lot_number)
    found = mgr.get_lot_for_instrument('CHQ-OUT-00001')
    assert found == lot.lot_number


def test_get_lot_for_unassigned_instrument_returns_none():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    mgr.create_lot()
    result = mgr.get_lot_for_instrument('CHQ-NOT-ASSIGNED')
    assert result is None


def test_auto_assign_fills_lots_sequentially():
    """auto_assign picks the first non-full lot, or creates a new one."""
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=2,
    )
    lot_nums = [mgr.auto_assign(f'CHQ-OUT-{i:05d}') for i in range(5)]
    # instruments 0,1 → lot_01; instruments 2,3 → lot_02; instrument 4 → lot_03
    assert lot_nums[0] == lot_nums[1]       # both in lot 01
    assert lot_nums[1] != lot_nums[2]       # lot 01 full, lot 02 starts
    assert lot_nums[2] == lot_nums[3]       # both in lot 02
    assert lot_nums[3] != lot_nums[4]       # lot 02 full, lot 03 starts


def test_list_lots_returns_all_created():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='AM',
        max_instruments_per_lot=200,
    )
    mgr.create_lot()
    mgr.create_lot()
    mgr.create_lot()
    lots = mgr.list_lots()
    assert len(lots) == 3


def test_lot_summary_counts():
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        clearing_slot='PM',
        max_instruments_per_lot=10,
    )
    for i in range(7):
        mgr.auto_assign(f'CHQ-OUT-{i:05d}')
    summary = mgr.summary()
    assert summary['total_lots'] == 1
    assert summary['total_assigned'] == 7
    assert summary['unassigned'] == 0


def test_different_clearing_slots_same_date():
    """AM and PM slots on the same date produce different lot numbers."""
    from modules.cts.lot.manager import LotManager
    date = datetime(2026, 7, 20, tzinfo=timezone.utc)
    am_mgr = LotManager(bank_ifsc='SVCB0000001', clearing_date=date, clearing_slot='AM')
    pm_mgr = LotManager(bank_ifsc='SVCB0000001', clearing_date=date, clearing_slot='PM')
    am_lot = am_mgr.create_lot()
    pm_lot = pm_mgr.create_lot()
    assert '_AM_' in am_lot.lot_number
    assert '_PM_' in pm_lot.lot_number
    assert am_lot.lot_number != pm_lot.lot_number


def test_lot_number_format_eve_slot():
    """Evening slot produces correct lot number format."""
    from modules.cts.lot.manager import LotManager
    mgr = LotManager(
        bank_ifsc='HDFC0000001',
        clearing_date=datetime(2026, 7, 20, tzinfo=timezone.utc),
        clearing_slot='EVE',
        max_instruments_per_lot=200,
    )
    lot = mgr.create_lot()
    assert lot.lot_number == 'LOT_HDFC0000001_20260720_EVE_01'
