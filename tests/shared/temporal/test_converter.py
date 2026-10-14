"""pydantic_data_converter must round-trip models containing date/datetime/Decimal.
Found by the real outward run: PostDatedHoldInput.release_date is a `date`; the encoder
could not serialise it ("Object of type date is not JSON serializable"), so the workflow
task failed and retried forever and the post-dated cheque was never held."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from shared.temporal.converter import pydantic_data_converter


class _M(BaseModel):
    d: date
    when: Optional[datetime] = None
    amount: Decimal = Decimal("0")
    nested: dict = {}


def _round_trip(value):
    pc = pydantic_data_converter.payload_converter
    payload = pc.to_payloads([value])
    return pc.from_payloads(payload, [type(value)])[0]


def test_model_with_date_round_trips():
    m = _M(d=date(2026, 10, 9), when=datetime(2026, 9, 21, 12, 30), amount=Decimal("45000.50"))
    assert _round_trip(m) == m


def test_plain_dict_and_primitives_still_work():
    pc = pydantic_data_converter.payload_converter
    assert pc.from_payloads(pc.to_payloads([{"a": 1, "b": [1, 2]}]), [dict])[0] == {"a": 1, "b": [1, 2]}
    assert pc.from_payloads(pc.to_payloads(["x"]), [str])[0] == "x"


def test_dataclass_with_date_field_round_trips():
    """Real worker failure: 'Failed converting field release_date on dataclass PostDatedHoldInput'."""
    from modules.cts.workflows.postdated_hold_workflow import PostDatedHoldInput
    v = PostDatedHoldInput(instrument_id="i", bank_id="kbl", release_date=date(2026, 10, 9),
                           original_workflow_data={"k": "v"})
    assert _round_trip(v) == v
