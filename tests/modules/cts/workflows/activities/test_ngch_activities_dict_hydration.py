"""Real live-run bug: build_and_upload_ngch_files raised 'dict' object has no attribute 'bank_id' — the
Temporal worker delivered a plain dict instead of the typed model (activities with DI-injected extra params
lose the type hint the pydantic converter needs), the same class of bug already fixed elsewhere in this
codebase (e.g. persist_outward_instrument.py) with a defensive `isinstance(inp, dict)` hydration at the top
of the activity body."""
import pytest

from modules.cts.workflows.activities.ngch_submission_activities import (
    ConfirmAcknowledgementInput, SubmitToNGCHInput, confirm_acknowledgement, submit_to_ngch,
)


@pytest.mark.asyncio
async def test_submit_to_ngch_accepts_a_plain_dict():
    inp = SubmitToNGCHInput(lot_number="L-1", bank_id="kbl", bank_ifsc="KARB0000001", file_path="cxf/L-1",
                            checksum_sha256="", instrument_count=3).model_dump()
    res = await submit_to_ngch(inp)
    assert res.submitted in (True, False)


@pytest.mark.asyncio
async def test_confirm_acknowledgement_accepts_a_plain_dict():
    inp = ConfirmAcknowledgementInput(lot_number="L-1", bank_id="kbl", ngch_reference="NGCH-1").model_dump()
    res = await confirm_acknowledgement(inp)
    assert res.acknowledged in (True, False)


@pytest.mark.asyncio
async def test_build_and_upload_ngch_files_accepts_a_plain_dict(monkeypatch):
    from modules.cts.workflows.activities import ngch_lot_assembly_activity as mod
    inp = mod.FetchAndBuildInput(bank_id="kbl", lot_number="L-1", session_id="s", clearing_date="2026-09-21",
                                 bank_ifsc="KARB0000001").model_dump()
    with pytest.raises(Exception) as ei:
        await mod.build_and_upload_ngch_files(inp)
    # must fail for a REAL reason (no db_pool / no instruments) — never AttributeError on a dict
    assert not isinstance(ei.value, AttributeError)
