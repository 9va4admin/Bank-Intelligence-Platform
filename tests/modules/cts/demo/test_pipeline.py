"""
Demo pipeline unit tests — TDD RED run before implementation exists.

Tests cover:
  - Session lifecycle (create, add items, retrieve)
  - Presentment pipeline: all items reach terminal state
  - Failure injection: some items rejected
  - Event emission: SSE events fire in expected order
  - NPCI grouping: accepted items grouped by drawee bank
  - Drawee pipeline: items reach CONFIRMED or RETURNED
  - CSV writers: include/exclude correct items, headers present
"""
import asyncio
import pytest

from modules.cts.demo.models import DemoItem, ItemStatus, SessionPhase, StepResult, StepStatus
from modules.cts.demo.pipeline import DemoPipeline
from modules.cts.demo.csv_writer import write_success_csv, write_failure_csv


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pipeline():
    return DemoPipeline()


@pytest.fixture
def session_id(pipeline):
    session = pipeline.create_session(bank_id="test-bank")
    return session.session_id


# ── session lifecycle ─────────────────────────────────────────────────────────

def test_create_session_returns_session(pipeline):
    session = pipeline.create_session(bank_id="test-bank")
    assert session.session_id
    assert session.bank_id == "test-bank"
    assert session.phase == SessionPhase.IDLE
    assert session.items == []


def test_add_items_populates_session(pipeline, session_id):
    pipeline.add_items(session_id, ["chq001.jpg", "chq002.jpg", "chq003.jpg"])
    session = pipeline.get_session(session_id)
    assert len(session.items) == 3
    assert session.items[0].filename == "chq001.jpg"
    assert session.items[0].status == ItemStatus.QUEUED


def test_get_session_returns_none_for_unknown(pipeline):
    assert pipeline.get_session("not-a-real-id") is None


def test_multiple_add_items_calls_accumulate(pipeline, session_id):
    pipeline.add_items(session_id, ["a.jpg", "b.jpg"])
    pipeline.add_items(session_id, ["c.jpg"])
    session = pipeline.get_session(session_id)
    assert len(session.items) == 3


# ── presentment pipeline ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_presentment_processes_all_items(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(5)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    for item in session.items:
        assert item.status in (ItemStatus.SUCCESS, ItemStatus.FAILED)
        assert item.decision is not None
        assert len(item.steps) > 0


@pytest.mark.asyncio
async def test_run_presentment_sets_phase(pipeline, session_id):
    pipeline.add_items(session_id, ["chq001.jpg"])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    assert session.phase == SessionPhase.NPCI_SIMULATION


@pytest.mark.asyncio
async def test_run_presentment_items_have_total_ms(pipeline, session_id):
    pipeline.add_items(session_id, ["chq001.jpg", "chq002.jpg"])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    for item in session.items:
        assert item.total_ms > 0


@pytest.mark.asyncio
async def test_presentment_some_items_fail(pipeline, session_id):
    # Feed 20 cheques — deterministic failure injection guarantees some fails
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(20)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    statuses = [it.status for it in session.items]
    assert ItemStatus.SUCCESS in statuses
    assert ItemStatus.FAILED in statuses


@pytest.mark.asyncio
async def test_accepted_items_get_drawee_bank(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(10)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    for item in session.items:
        if item.status == ItemStatus.SUCCESS:
            assert item.drawee_bank is not None


@pytest.mark.asyncio
async def test_failed_items_have_reject_reason(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(20)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    for item in session.items:
        if item.status == ItemStatus.FAILED:
            assert item.reject_reason is not None


# ── event emission ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_presentment_emits_events(pipeline, session_id):
    pipeline.add_items(session_id, ["chq001.jpg"])
    event_types: list[str] = []

    async def collect():
        async for line in pipeline.events(session_id):
            if line.startswith("event:"):
                # Each SSE chunk is "event: X\ndata: {...}\n\n" — split on the
                # first newline before the colon-split, or et ends up as
                # "X\ndata: {...}" (str.strip() only trims the edges, not the
                # embedded newline+data line in the middle) and never equals
                # any plain event-name string being compared against.
                et = line.split("\n", 1)[0].split(":", 1)[1].strip()
                event_types.append(et)
                # run_presentment() alone never sends the queue's closing
                # None sentinel (only run_drawee(), a later phase, does) —
                # so "done" never fires here. presentment_complete is the
                # actual last event this phase emits.
                if et == "presentment_complete":
                    break

    await asyncio.gather(
        pipeline.run_presentment(session_id),
        collect(),
    )

    assert "session_started" in event_types
    assert "item_started" in event_types
    assert any(e in event_types for e in ("step_complete", "step_failed"))
    assert "presentment_complete" in event_types


# ── NPCI grouping ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_npci_groups_populated_after_presentment(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(8)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    assert session.npci_output is not None
    for bank, item_ids in session.npci_output.items():
        assert len(item_ids) > 0


@pytest.mark.asyncio
async def test_npci_group_item_ids_match_accepted_items(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(8)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)

    all_accepted_ids = {it.item_id for it in session.items if it.status == ItemStatus.SUCCESS}
    grouped_ids = set()
    for ids in session.npci_output.values():
        grouped_ids.update(ids)

    assert grouped_ids == all_accepted_ids


# ── drawee pipeline ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_drawee_processes_bank_items(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(12)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    assert session.npci_output

    first_bank = next(iter(session.npci_output))
    await pipeline.run_drawee(session_id, first_bank)
    session = pipeline.get_session(session_id)

    assert len(session.drawee_items) > 0
    for item in session.drawee_items:
        assert item.status in (ItemStatus.SUCCESS, ItemStatus.FAILED)


@pytest.mark.asyncio
async def test_run_drawee_sets_phase_complete(pipeline, session_id):
    pipeline.add_items(session_id, [f"chq{i:03d}.jpg" for i in range(8)])
    await pipeline.run_presentment(session_id)
    session = pipeline.get_session(session_id)
    first_bank = next(iter(session.npci_output))
    await pipeline.run_drawee(session_id, first_bank)
    session = pipeline.get_session(session_id)
    assert session.phase == SessionPhase.COMPLETE


# ── CSV writers ───────────────────────────────────────────────────────────────

def _make_success_item() -> DemoItem:
    item = DemoItem(
        filename="chq001.jpg",
        status=ItemStatus.SUCCESS,
        decision="ACCEPTED",
        total_ms=1500,
    )
    item.extracted = {
        "payee": "ABC Enterprises",
        "amount_figures": "₹45,000",
        "date": "01-07-2026",
        "match_ok": True,
    }
    item.steps = [
        StepResult(
            step="ocr_micr",
            status=StepStatus.PASSED,
            duration_ms=600,
            data={"micr_line": "⑈800001⑆123456789⑉001234"},
        ),
        StepResult(
            step="lot_assignment",
            status=StepStatus.PASSED,
            duration_ms=100,
            data={"lot_id": "LOT-001", "lot_position": 1},
        ),
    ]
    return item


def _make_failed_item() -> DemoItem:
    item = DemoItem(
        filename="chq002.jpg",
        status=ItemStatus.FAILED,
        decision="REJECTED",
        reject_reason="AMOUNT_MISMATCH",
        total_ms=900,
    )
    item.steps = [
        StepResult(
            step="data_extraction",
            status=StepStatus.FAILED,
            duration_ms=400,
            detail="Amount figures ₹45,000 do not match words 'Forty Six Thousand Only'",
        ),
    ]
    return item


def test_write_success_csv_contains_accepted_items():
    items = [_make_success_item(), _make_failed_item()]
    csv_str = write_success_csv(items, phase="presentment")
    assert "chq001.jpg" in csv_str
    assert "chq002.jpg" not in csv_str


def test_write_success_csv_contains_payee_and_amount():
    items = [_make_success_item()]
    csv_str = write_success_csv(items, phase="presentment")
    assert "ABC Enterprises" in csv_str
    assert "₹45,000" in csv_str


def test_write_success_csv_has_header_row():
    csv_str = write_success_csv([], phase="presentment")
    lines = [ln for ln in csv_str.strip().split("\n") if ln]
    assert len(lines) == 1  # only header, no data rows
    assert "Filename" in lines[0]


def test_write_failure_csv_contains_failed_items():
    items = [_make_success_item(), _make_failed_item()]
    csv_str = write_failure_csv(items)
    assert "chq002.jpg" in csv_str
    assert "chq001.jpg" not in csv_str


def test_write_failure_csv_contains_reject_reason():
    items = [_make_failed_item()]
    csv_str = write_failure_csv(items)
    assert "AMOUNT_MISMATCH" in csv_str


def test_write_failure_csv_has_header_row():
    csv_str = write_failure_csv([])
    lines = [ln for ln in csv_str.strip().split("\n") if ln]
    assert len(lines) == 1
    assert "Reject_Reason" in lines[0]


def test_write_success_csv_drawee_phase():
    from modules.cts.demo.models import DemoItem, ItemStatus, StepResult, StepStatus
    item = DemoItem(filename="chq001.jpg", status=ItemStatus.SUCCESS, decision="CONFIRMED", total_ms=2100)
    item.extracted = {"payee": "XYZ Ltd", "amount_figures": "₹10,000", "date": "02-07-2026"}
    item.steps = [
        StepResult(step="signature_vault", status=StepStatus.PASSED, duration_ms=400,
                   data={"match_score": 0.94}),
        StepResult(step="fraud_score", status=StepStatus.PASSED, duration_ms=300,
                   data={"fraud_score": 0.07}),
    ]
    csv_str = write_success_csv([item], phase="drawee")
    assert "chq001.jpg" in csv_str
    assert "0.94" in csv_str
    assert "0.07" in csv_str
