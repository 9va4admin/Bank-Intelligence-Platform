"""Instrument IDs reach the system as arbitrary strings (scanner serials, scan ids), but several tables
(cts.agent_decisions, cts.human_review_items) key on a UUID column. Every persist call therefore failed
silently ('invalid UUID ...') and agent_decisions stayed EMPTY across all real runs. to_instrument_uuid
maps any id to a UUID deterministically, so the same instrument always gets the same row (idempotent)."""
import uuid

import pytest

from shared.utils.instrument_uuid import to_instrument_uuid


def test_real_uuid_is_returned_unchanged():
    u = "0b9c1f6e-7a3a-4a4a-8f3e-2f6a6f1c9d11"
    assert to_instrument_uuid("kbl", u) == uuid.UUID(u)


def test_arbitrary_string_maps_to_a_stable_uuid():
    a = to_instrument_uuid("kbl", "000787-c687")
    assert isinstance(a, uuid.UUID)
    assert a == to_instrument_uuid("kbl", "000787-c687")          # deterministic


def test_different_ids_and_different_banks_do_not_collide():
    assert to_instrument_uuid("kbl", "A") != to_instrument_uuid("kbl", "B")
    assert to_instrument_uuid("kbl", "A") != to_instrument_uuid("other", "A")


@pytest.mark.parametrize("bad", ["", None])
def test_empty_id_is_rejected(bad):
    with pytest.raises(ValueError):
        to_instrument_uuid("kbl", bad)
