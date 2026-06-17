# Temporal Workflow Rules (ASTRA Standard)

## Fundamental Constraints
- Every cheque processing path starts with `ChequeProcessingWorkflow` — no exceptions
- `IETWatchdogWorkflow` MUST be spawned as a child workflow before any processing begins
- Workflow IDs must be deterministic and idempotent: `cts-{bank_id}-{instrument_id}`
- No direct activity calls from application code — always via workflow context
- Temporal is the only retry mechanism — no manual retry loops in activities

## Workflow ID Patterns (Idempotency)
```python
# CTS workflows
workflow_id = f"cts-{bank_id}-{instrument_id}"
iet_watchdog_id = f"cts-iet-{bank_id}-{instrument_id}"
human_review_id = f"cts-humanreview-{bank_id}-{instrument_id}"
vault_sync_id = f"cts-vaultsync-{bank_id}-{date}"

# EJ workflows
workflow_id = f"ej-normalise-{bank_id}-{raw_log_hash}"
dispute_id = f"ej-dispute-{bank_id}-{npci_claim_id}"

# Rule: if the same workflow_id is submitted twice, Temporal deduplicates it.
# This is the exactly-once guarantee — never bypass it.
```

## Retry Policies (Standard — use these, never invent your own)
```python
from temporalio.common import RetryPolicy
from datetime import timedelta

# OCR, signature verification, fraud scoring (fast AI inference)
AI_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError", "IETBreachError"]
)

# NGCH filing (critical — 3 retries, exponential backoff)
NGCH_FILING_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"]
)

# CBS queries (network-dependent — generous timeout, fast retry)
CBS_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5
)

# Audit writes (must succeed — unlimited retries, write fails = don't proceed)
AUDIT_RETRY = RetryPolicy(
    maximum_attempts=None,   # unlimited
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5)
)
```

## Activity Timeouts
```python
# Every activity must have an explicit start-to-close timeout
# Never rely on Temporal's default (10 seconds — too short for AI inference)

OCR_TIMEOUT = timedelta(seconds=30)          # GOT-OCR2 on GPU
SIGNATURE_TIMEOUT = timedelta(seconds=15)    # Siamese network inference
FRAUD_SCORE_TIMEOUT = timedelta(seconds=10)  # XGBoost — fast
LLM_VISION_TIMEOUT = timedelta(seconds=120)  # Qwen2-VL 72B — slow
LLM_REASONING_TIMEOUT = timedelta(seconds=180)  # Llama 3.3 70B
CBS_TIMEOUT = timedelta(seconds=10)          # CBS must not block critical path
NGCH_TIMEOUT = timedelta(seconds=30)         # SFTP filing
AUDIT_TIMEOUT = timedelta(seconds=15)        # Immudb write
```

## IET Watchdog Pattern (CTS — Non-Negotiable)
```python
# In ChequeProcessingWorkflow.__init__ or run() — FIRST thing before any activity:
@workflow.run
async def run(self, input: ChequeWorkflowInput) -> ChequeDecision:
    # 1. Start IET watchdog FIRST — before any other activity
    watchdog = await workflow.start_child_workflow(
        IETWatchdogWorkflow.run,
        args=[IETWatchdogInput(
            instrument_id=input.instrument_id,
            bank_id=input.bank_id,
            iet_deadline=input.iet_deadline,
        )],
        id=f"cts-iet-{input.bank_id}-{input.instrument_id}",
        parent_close_policy=ParentClosePolicy.ABANDON,  # watchdog survives parent failure
    )

    # 2. Now proceed with processing activities...
    # If watchdog fires (T-30s), it files directly to NGCH and sets a flag
    # Parent workflow checks this flag before filing to avoid duplicate
```

## Graceful Degradation (Mandatory Fallback Paths)
Every activity that calls an external system MUST have a graceful degradation path:
```python
# Pattern: try → degrade → never breach IET
try:
    balance = await workflow.execute_activity(
        check_cbs_balance,
        retry_policy=CBS_RETRY,
        start_to_close_timeout=CBS_TIMEOUT,
    )
except ActivityError:
    # CBS unreachable — degrade gracefully, do NOT fail the workflow
    balance = CbsResult(available=None, status="UNREACHABLE")
    # Processing continues with image-only path
    # Outcome: slightly higher human review rate — acceptable

# What is NEVER acceptable:
# - Raising an unhandled exception that kills the workflow
# - Silently returning a wrong value (e.g. balance=0 on CBS timeout)
# - Waiting indefinitely for CBS (must have timeout)
```

## Signal and Query Patterns
```python
# Human review decision arrives as a Temporal signal:
@workflow.signal
async def receive_review_decision(self, decision: ReviewDecision) -> None:
    self._review_decision = decision

# IET watchdog can query parent's current state:
@workflow.query
def get_processing_state(self) -> str:
    return self._current_state  # OCR_COMPLETE, FRAUD_SCORED, etc.
```

## Worker Configuration
```python
# CTS workers: only poll CTS task queues — NEVER cross-module
worker = Worker(
    client,
    task_queue=f"cts-processing-{bank_id}",   # never "ej-*"
    workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow],
    activities=[ocr_extract, verify_signature, score_fraud, file_to_ngch, write_audit],
    max_concurrent_workflow_tasks=100,
    max_concurrent_activities=200,
    graceful_shutdown_timeout=timedelta(minutes=2),  # drain before pod stops
)

# EJ workers: only poll EJ task queues — NEVER cross-module
worker = Worker(
    client,
    task_queue=f"ej-normalisation-{bank_id}",  # never "cts-*"
    workflows=[EJNormalisationWorkflow, DisputeResolutionWorkflow],
    ...
)
```

## Forbidden Patterns
- `asyncio.sleep()` inside a workflow — use `await workflow.sleep()` (deterministic)
- `datetime.now()` inside a workflow — use `workflow.now()` (deterministic replay)
- `random.random()` inside a workflow — use `workflow.random()` (deterministic replay)
- Calling activities directly without retry policy (use standard retry constants above)
- Sharing a Temporal task queue between CTS and EJ workers
- Starting a workflow without a deterministic workflow ID (no UUID4 — use instrument_id)
- Catching `CancelledException` and suppressing it (Temporal cancellation must propagate)

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| IETWatchdogWorkflow spawned before any activity | `cts-workflow-reviewer` agent checklist item 2 | PR merge (CRITICAL) |
| No asyncio.sleep inside workflows | Semgrep rule `astra-no-sleep-in-workflow` (pattern: asyncio.sleep in workflows/) | PR merge (CI SAST) |
| No datetime.now() inside workflows | Semgrep rule `astra-no-datetime-now-in-workflow` | PR merge (CI SAST) |
| Standard retry constants used | `cts-workflow-reviewer` agent verifies no inline RetryPolicy dicts | PR merge |
| Workflow IDs follow cts-{bank_id}-{instrument_id} pattern | `cts-workflow-reviewer` agent checklist item 3 | PR merge |
| Graceful degradation: CBS miss → degrade not crash | `cts-workflow-reviewer` agent checklist item 4 | PR merge |
