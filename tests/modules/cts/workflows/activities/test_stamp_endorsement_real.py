"""stamp_endorsement against the REAL processor/stamper/renderer (fake lot store only)."""
import io
import pytest
from PIL import Image

from modules.cts.workflows.activities.batch_endorsement_activities import StampEndorsementInput, stamp_endorsement


def _img():
    b = io.BytesIO(); Image.new("RGB", (800, 400), "white").save(b, "TIFF"); return b.getvalue()


class Store:
    def __init__(self, items): self.items, self.saved = items, {}
    async def endorsement_context(self, bank_id, lot): return {"bank_name": "Karnatak Bank Ltd", "branch_name": "Main"}
    async def fetch_instrument_images(self, lot, bank): return self.items
    async def store_endorsed_rear(self, bank, iid, data): self.saved[iid] = data; return "k"


@pytest.mark.asyncio
async def test_stamps_and_stores_every_instrument():
    st = Store([("u1", "3051", _img(), _img()), ("u2", "4411", _img(), _img())])
    res = await stamp_endorsement(StampEndorsementInput(lot_number="L", bank_id="kbl", bank_ifsc="KARB0000001",
                                                        instrument_ids=["u1", "u2"]), lot_store=st)
    assert (res.endorsed_count, res.failed_count) == (2, 0)
    assert set(st.saved) == {"u1", "u2"} and Image.open(io.BytesIO(st.saved["u1"])).size == (800, 400)


@pytest.mark.asyncio
async def test_undecodable_rear_counts_as_failed_not_crash():
    st = Store([("u1", "3051", _img(), b"not-an-image")])
    res = await stamp_endorsement(StampEndorsementInput(lot_number="L", bank_id="kbl", bank_ifsc="KARB0000001",
                                                        instrument_ids=["u1"]), lot_store=st)
    assert (res.endorsed_count, res.failed_count, res.failed_instrument_ids) == (0, 1, ["u1"])
