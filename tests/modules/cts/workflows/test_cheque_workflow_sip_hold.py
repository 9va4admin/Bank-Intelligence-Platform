"""ChequeProcessingWorkflow: buckets and the SIP hold.

A cheque the SYSTEM decided (STP confirm / return) is held for a reviewer only when routing is on, a reviewer connected
to its SIP bucket is logged in, there is enough time before the IET, and the cheque is not sub-member tagged. If nobody
acts the system's own decision is filed; if a reviewer acts, theirs is. Cheques that need a human carry their bucket."""
import asyncio
import time
import uuid

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from tests.modules.cts.workflows.test_cheque_workflow_inward_ocr import (
    _BASE_ACTIVITIES, _dget, _ocr_fake_hrq, _ocr_fake_proceed,
)

BANK = "saraswat-coop"
CFG = {"stp_mode": "FULL_STP", "bucket_routing_enabled": True, "sip_review_timeout_minutes": 15,
       "sip_iet_guard_minutes": 10, "bucket_priority": ["HVC", "CA", "IP", "FCC", "LVC"]}


@pytest_asyncio.fixture()
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


class Rec:
    def __init__(self):
        self.filed, self.queued, self.classified, self.hold_checks = [], [], [], []


def _activities(rec, *, bucket="SIP_SUCCESS", hold=True, classify_raises=False, hold_raises=False):
    @activity.defn(name="file_to_ngch")
    async def file_to_ngch(inp):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
        rec.filed.append(_dget(inp, "decision"))
        return NGCHFilerResult(acknowledgement_id="ACK", status="ACCEPTED", filed_decision=_dget(inp, "decision"))

    @activity.defn(name="push_to_review_queue")
    async def push_to_review_queue(inp):
        rec.queued.append({k: _dget(inp, k) for k in ("bucket", "system_decision", "review_timeout_minutes")})

    @activity.defn(name="classify_bucket")
    async def classify_bucket(inp):
        rec.classified.append(inp)
        if classify_raises:
            raise RuntimeError("classification down")
        return {"bucket": bucket, "matched": [], "degraded": []}

    @activity.defn(name="sip_hold_check")
    async def sip_hold_check(inp):
        rec.hold_checks.append(inp)
        if hold_raises:
            raise RuntimeError("check down")
        return {"hold": hold, "reason": None}

    base = [a for a in _BASE_ACTIVITIES
            if a.__temporal_activity_definition.name not in {"file_to_ngch", "push_to_review_queue"}]
    return [*base, file_to_ngch, push_to_review_queue, classify_bucket, sip_hold_check]


async def _run(env, rec, ocr, *, cfg=None, iet_in=3 * 3600, smb_id=None, wait_child=False, signal=None, **act_kw):
    from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow, ChequeWorkflowInput
    from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow
    from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow, ReviewDecision
    from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

    tq = f"tq-sip-{uuid.uuid4()}"
    iid = f"SIP-{uuid.uuid4().hex[:8]}"
    from modules.cts.queue_tier import humanreview_task_queue_for_tier
    acts = _activities(rec, **act_kw)
    # The review workflow runs on its own task queue, so it needs its own worker.
    async with Worker(env.client, task_queue=humanreview_task_queue_for_tier(BANK, "standard"),
                      workflows=[HumanReviewWorkflow], activities=acts, workflow_runner=UnsandboxedWorkflowRunner()),             Worker(env.client, task_queue=tq,
                   workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, FeedbackEmitWorkflow],
                   activities=[ocr, *acts], workflow_runner=UnsandboxedWorkflowRunner()):
        result = await env.client.execute_workflow(
            ChequeProcessingWorkflow.run,
            ChequeWorkflowInput(instrument_id=iid, bank_id=BANK, image_url="minio://cts/inward/x.tiff",
                                account_number="12340000005678", cheque_number="000099", presented_amount=75000.0,
                                presented_payee="Suresh Patil", iet_deadline=time.time() + iet_in, ngch_ifsc="SRCB0000001",
                                smb_id=smb_id, cts_config=cfg or CFG),
            id=f"cts-{BANK}-{iid}", task_queue=tq)
        child = None
        if wait_child:
            handle = env.client.get_workflow_handle(f"cts-humanreview-{BANK}-{iid}")
            if signal:
                await handle.signal(HumanReviewWorkflow.receive_decision,
                                    ReviewDecision(action=signal, reason="checked", reviewer_id="alice", decided_at=time.time()))
            if signal:
                child = await handle.result()
            else:
                # The timeout path itself is covered against the real review workflow in test_human_review_workflow;
                # here we only need to see that the hold started with the right input, then stop the child.
                for _ in range(100):
                    if rec.queued:
                        break
                    await asyncio.sleep(0.1)
                await handle.terminate("test finished")
        return result, child


# --- hold ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_system_confirm_is_held_for_a_reviewer_and_not_filed_by_the_parent(env):
    rec = Rec()
    result, _ = await _run(env, rec, _ocr_fake_proceed, wait_child=True)
    assert result.decision == "STP_CONFIRM" and "sip_hold" in result.rationale
    assert rec.queued == [{"bucket": "SIP_SUCCESS", "system_decision": "CONFIRM", "review_timeout_minutes": 15}]
    assert rec.filed == []                                           # the parent did NOT file it; the review workflow will


@pytest.mark.asyncio
async def test_a_reviewer_can_overrule_the_system_decision(env):
    rec = Rec()
    _, child = await _run(env, rec, _ocr_fake_proceed, wait_child=True, signal="RETURN")
    assert rec.filed == ["RETURN"] and child["outcome"] == "REVIEWER_RETURNED"


@pytest.mark.asyncio
async def test_the_hold_never_outlasts_the_iet_guard(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_proceed, iet_in=20 * 60, wait_child=True)       # 20 min left, 10 min guard
    assert rec.queued[0]["review_timeout_minutes"] == 10


# --- no hold ------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_active_subscriber_means_the_system_decision_is_filed_straight_away(env):
    rec = Rec()
    result, _ = await _run(env, rec, _ocr_fake_proceed, hold=False)
    assert result.decision == "STP_CONFIRM" and rec.filed == ["CONFIRM"] and rec.queued == []


@pytest.mark.asyncio
async def test_routing_off_never_classifies_or_holds(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_proceed, cfg={"stp_mode": "FULL_STP"})
    assert rec.filed == ["CONFIRM"] and rec.classified == [] and rec.hold_checks == []


@pytest.mark.asyncio
async def test_too_close_to_the_iet_the_decision_is_filed_not_held(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_proceed, iet_in=8 * 60)                          # 8 min left < 10 min guard
    assert rec.filed == ["CONFIRM"] and rec.queued == []


@pytest.mark.asyncio
async def test_sub_member_cheques_are_not_held(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_proceed, smb_id="smb-1")
    assert rec.filed == ["CONFIRM"] and rec.queued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"classify_raises": True}, {"hold_raises": True}])
async def test_a_failing_bucket_or_hold_check_never_delays_or_changes_the_filing(env, kw):
    rec = Rec()
    result, _ = await _run(env, rec, _ocr_fake_proceed, **kw)
    assert result.decision == "STP_CONFIRM" and rec.filed == ["CONFIRM"] and rec.queued == []


@pytest.mark.asyncio
async def test_a_non_sip_bucket_answer_is_not_held(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_proceed, bucket="HVC")
    assert rec.filed == ["CONFIRM"] and rec.queued == []


# --- human-review bucket ------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_cheque_needing_a_human_carries_its_bucket_to_the_review_queue(env):
    rec = Rec()
    result, child = await _run(env, rec, _ocr_fake_hrq, bucket="HVC", wait_child=True, signal="CONFIRM")
    assert result.decision == "HUMAN_REVIEW"
    assert rec.queued[0]["bucket"] == "HVC" and rec.queued[0]["system_decision"] is None
    assert rec.classified[0]["needs_human"] is True


@pytest.mark.asyncio
async def test_if_classification_fails_a_human_review_item_still_queues_without_a_bucket(env):
    rec = Rec()
    await _run(env, rec, _ocr_fake_hrq, classify_raises=True, wait_child=True, signal="CONFIRM")
    assert rec.queued[0]["bucket"] is None


# --- maker-checker settings reach the review workflow -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_human_review_item_carries_the_maker_checker_settings(env):
    captured = []

    from temporalio import activity as _act

    rec = Rec()
    acts = _activities(rec)
    # replace the recording push with one that also keeps the maker-checker fields
    acts = [a for a in acts if a.__temporal_activity_definition.name != "push_to_review_queue"]

    @_act.defn(name="push_to_review_queue")
    async def push_full(inp):
        captured.append({k: _dget(inp, k) for k in ("maker_checker", "checker_timeout_minutes", "iet_guard_minutes")})

    from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow, ChequeWorkflowInput
    from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow
    from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
    from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
    from modules.cts.queue_tier import humanreview_task_queue_for_tier

    tq, iid = f"tq-mc-{uuid.uuid4()}", f"MC-{uuid.uuid4().hex[:8]}"
    cfg = {**CFG, "bucket_routing_enabled": False, "maker_checker_enabled": True, "checker_review_timeout_minutes": 12,
           "sip_iet_guard_minutes": 7}
    async with Worker(env.client, task_queue=humanreview_task_queue_for_tier(BANK, "standard"), workflows=[HumanReviewWorkflow],
                      activities=[*acts, push_full], workflow_runner=UnsandboxedWorkflowRunner()), \
            Worker(env.client, task_queue=tq, workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, FeedbackEmitWorkflow],
                   activities=[_ocr_fake_hrq, *acts, push_full], workflow_runner=UnsandboxedWorkflowRunner()):
        await env.client.execute_workflow(
            ChequeProcessingWorkflow.run,
            ChequeWorkflowInput(instrument_id=iid, bank_id=BANK, image_url="minio://cts/inward/x.tiff",
                                account_number="12340000005678", cheque_number="000099", presented_amount=75000.0,
                                presented_payee="Suresh Patil", iet_deadline=time.time() + 3 * 3600, ngch_ifsc="SRCB0000001",
                                cts_config=cfg),
            id=f"cts-{BANK}-{iid}", task_queue=tq)
        for _ in range(100):
            if captured:
                break
            await asyncio.sleep(0.1)
        await env.client.get_workflow_handle(f"cts-humanreview-{BANK}-{iid}").terminate("done")
    assert captured[0] == {"maker_checker": True, "checker_timeout_minutes": 12, "iet_guard_minutes": 7}
