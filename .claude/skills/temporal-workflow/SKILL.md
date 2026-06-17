---
name: temporal-workflow
description: Design and implement a new Temporal workflow in ASTRA. Covers workflow skeleton, activity breakdown, retry policies, IET watchdog wiring (CTS), graceful degradation, and worker registration.
---

# Skill: Implement a New Temporal Workflow

## When to Use
User says: "add a new workflow", "implement {X} as a Temporal workflow", "create activity for {X}", or needs to wire a new business process into ASTRA's workflow engine.

---

## Step 1 — Classify the Workflow

Before writing any code, answer these four questions:

| Question | Answer determines |
|---|---|
| Is this CTS or EJ or Platform? | Which namespace, task queue, worker |
| Does it have a hard deadline? | Whether IETWatchdog child is needed |
| What are the terminal states? | How many audit events to plan for |
| Does it call external systems? | Which graceful degradation paths needed |

**CTS workflows** → `modules/cts/workflows/`
**EJ workflows** → `modules/ej/workflows/`
**Platform workflows** (audit, notification, bank onboarding) → `shared/`

---

## Step 2 — Define Activities First (Bottom-Up Design)

Each activity = one unit of work that can fail and retry independently.
Rule: if two things can fail independently, they are two activities.

```
Good activity boundaries:
✓ ocr_extract          — one AI call, own retry budget
✓ verify_signature     — one AI call, own retry budget
✓ check_cbs_balance    — one CBS call, short timeout
✓ file_to_ngch         — one NGCH submission, critical retry
✓ write_audit          — one Immudb write, unlimited retry

Bad activity boundaries:
✗ process_cheque       — does everything — can't retry selectively
✗ ocr_and_signature    — two AI calls in one — retry restarts both
```

Activity file location: `modules/{module}/workflows/activities/{name}.py`

```python
# Activity template
from temporalio import activity
from opentelemetry import trace
import structlog

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts")

@activity.defn
async def ocr_extract(input: OcrInput) -> OcrResult:
    with tracer.start_as_current_span("activity.ocr_extract") as span:
        span.set_attribute("bank_id", input.bank_id)
        span.set_attribute("instrument_id", input.instrument_id)

        log.info("ocr_extract.start",
                 bank_id=input.bank_id,
                 instrument_id=input.instrument_id)
        # ^ Never log account numbers, amounts, or customer names here

        # heartbeat for long-running activities (>10s)
        activity.heartbeat("starting OCR inference")

        result = await vllm_client.infer(
            queue="cts-ocr",           # always explicit queue — never default
            model="got-ocr2",
            image_url=input.image_url,
        )

        # Langfuse trace for every AI call
        langfuse.trace(
            name="ocr_extract",
            input={"instrument_id": input.instrument_id},
            output={"confidence": result.confidence},
        )

        span.set_attribute("ocr.confidence", result.confidence)
        return OcrResult(fields=result.fields, confidence=result.confidence)
```

---

## Step 3 — Write the Workflow Shell

```python
# Workflow template (CTS example)
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

# Import retry constants from rules — never define inline
from modules.cts.workflows.retry_policies import (
    AI_ACTIVITY_RETRY, NGCH_FILING_RETRY, CBS_RETRY, AUDIT_RETRY
)

@workflow.defn
class ChequeProcessingWorkflow:
    def __init__(self) -> None:
        self._current_state = "INITIALISED"
        self._review_decision: ReviewDecision | None = None

    @workflow.run
    async def run(self, input: ChequeWorkflowInput) -> ChequeDecision:

        # ── Step 1: IET Watchdog (CTS ONLY — spawn before anything else) ──
        watchdog_handle = await workflow.start_child_workflow(
            IETWatchdogWorkflow.run,
            args=[IETWatchdogInput(
                instrument_id=input.instrument_id,
                bank_id=input.bank_id,
                iet_deadline=input.iet_deadline,
            )],
            id=f"cts-iet-{input.bank_id}-{input.instrument_id}",
            parent_close_policy=ParentClosePolicy.ABANDON,
        )

        # ── Step 2: Activities in dependency order ────────────────────────
        self._current_state = "OCR_RUNNING"
        ocr_result = await workflow.execute_activity(
            ocr_extract,
            args=[OcrInput(bank_id=input.bank_id, instrument_id=input.instrument_id,
                           image_url=input.image_url)],
            retry_policy=AI_ACTIVITY_RETRY,
            start_to_close_timeout=timedelta(seconds=30),
        )

        self._current_state = "SIGNATURE_RUNNING"
        sig_result = await workflow.execute_activity(
            verify_signature,
            args=[SignatureInput(bank_id=input.bank_id,
                                 account_number_hash=input.account_number_hash,
                                 image_url=input.image_url)],
            retry_policy=AI_ACTIVITY_RETRY,
            start_to_close_timeout=timedelta(seconds=15),
        )

        # ── Step 3: CBS (graceful degradation if unreachable) ────────────
        self._current_state = "CBS_CHECK"
        try:
            cbs_result = await workflow.execute_activity(
                check_cbs_balance,
                args=[CbsInput(bank_id=input.bank_id,
                               account_number_hash=input.account_number_hash)],
                retry_policy=CBS_RETRY,
                start_to_close_timeout=timedelta(seconds=10),
            )
        except ActivityError:
            cbs_result = CbsResult(available=None, status="UNREACHABLE")

        # ── Step 4: Fraud scoring ─────────────────────────────────────────
        self._current_state = "FRAUD_SCORING"
        fraud_result = await workflow.execute_activity(
            score_fraud,
            args=[FraudInput(ocr=ocr_result, signature=sig_result, cbs=cbs_result,
                              bank_id=input.bank_id)],
            retry_policy=AI_ACTIVITY_RETRY,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # ── Step 5: Decision ─────────────────────────────────────────────
        self._current_state = "DECIDING"
        decision = await workflow.execute_activity(
            synthesise_decision,
            args=[DecisionInput(ocr=ocr_result, signature=sig_result,
                                fraud=fraud_result, cbs=cbs_result,
                                bank_id=input.bank_id)],
            start_to_close_timeout=timedelta(seconds=5),
        )

        # ── Step 6: Human Review path ─────────────────────────────────────
        if decision.outcome == "HUMAN_REVIEW":
            self._current_state = "HUMAN_REVIEW"
            decision = await workflow.execute_child_workflow(
                HumanReviewWorkflow.run,
                args=[HumanReviewInput(bank_id=input.bank_id,
                                       instrument_id=input.instrument_id,
                                       context_bundle=decision.context)],
                id=f"cts-humanreview-{input.bank_id}-{input.instrument_id}",
            )

        # ── Step 7: File to NGCH ──────────────────────────────────────────
        self._current_state = "NGCH_FILING"
        await workflow.execute_activity(
            file_to_ngch,
            args=[NgchInput(bank_id=input.bank_id,
                            instrument_id=input.instrument_id,
                            decision=decision)],
            retry_policy=NGCH_FILING_RETRY,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # ── Step 8: Audit (unlimited retry — must not be skipped) ────────
        self._current_state = "AUDIT_WRITE"
        await workflow.execute_activity(
            write_audit,
            args=[AuditInput(bank_id=input.bank_id,
                             instrument_id=input.instrument_id,
                             decision=decision, fraud=fraud_result)],
            retry_policy=AUDIT_RETRY,
            start_to_close_timeout=timedelta(seconds=15),
        )

        self._current_state = decision.outcome  # STP_CONFIRM / STP_RETURN / HUMAN_REVIEW
        return decision

    @workflow.signal
    async def receive_review_decision(self, decision: ReviewDecision) -> None:
        self._review_decision = decision

    @workflow.query
    def get_state(self) -> str:
        return self._current_state
```

---

## Step 4 — Register with Worker

```python
# In modules/cts/worker.py — add new workflow and its activities
worker = Worker(
    client,
    task_queue=f"cts-processing-{bank_id}",
    workflows=[
        ChequeProcessingWorkflow,
        IETWatchdogWorkflow,
        HumanReviewWorkflow,
        # ← add new workflow here
    ],
    activities=[
        ocr_extract,
        verify_signature,
        check_cbs_balance,
        score_fraud,
        synthesise_decision,
        file_to_ngch,
        write_audit,
        # ← add new activities here
    ],
)
```

---

## Step 5 — Tests Required (Before PR)

```python
# Every new workflow needs these four test scenarios:
# 1. Happy path — all activities succeed, correct terminal state
# 2. Activity failure + retry — activity fails N times then succeeds
# 3. Graceful degradation — external system unreachable, workflow completes
# 4. IET boundary (CTS only) — watchdog fires at T-30s, emergency filing succeeds

# Use Temporal's test environment — never test against live Temporal
from temporalio.testing import WorkflowEnvironment

async def test_cheque_workflow_happy_path():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="test-cts",
                          workflows=[ChequeProcessingWorkflow],
                          activities=mocked_activities):
            result = await env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                args=[test_input],
                id="test-cts-bank1-instr001",
                task_queue="test-cts",
            )
            assert result.outcome == "STP_CONFIRM"
```

---

## Step 6 — Checklist Before Merging

```
[ ] Workflow ID is deterministic (uses instrument_id / claim_id — not UUID4)
[ ] IETWatchdogWorkflow spawned first (CTS workflows only)
[ ] Every activity has explicit retry_policy from standard constants
[ ] Every activity has explicit start_to_close_timeout
[ ] CBS / external system activities have graceful degradation (try/except)
[ ] No asyncio.sleep() — using workflow.sleep() if needed
[ ] No datetime.now() — using workflow.now() if needed
[ ] OTel span in every activity function
[ ] Langfuse trace in every AI inference call
[ ] Audit write activity is last and uses AUDIT_RETRY (unlimited)
[ ] Worker registration updated in worker.py
[ ] All four test scenarios written and passing
[ ] /review-workflow run on the new file — all checks green
```
