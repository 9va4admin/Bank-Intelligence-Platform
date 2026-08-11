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
# EJ: ej-normalise-{bank_id}-{raw_log_hash}, ej-dispute-{bank_id}-{npci_claim_id}
```

## Retry Policies (Standard — use these, never invent your own)
```python
from temporalio.common import RetryPolicy
from datetime import timedelta

AI_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError", "IETBreachError"]
)

NGCH_FILING_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"]
)

CBS_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5
)

AUDIT_RETRY = RetryPolicy(
    maximum_attempts=None,   # unlimited — audit must succeed
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5)
)
```

## Activity Timeouts
```python
OCR_TIMEOUT = timedelta(seconds=30)
SIGNATURE_TIMEOUT = timedelta(seconds=15)
FRAUD_SCORE_TIMEOUT = timedelta(seconds=10)
LLM_VISION_TIMEOUT = timedelta(seconds=120)
LLM_REASONING_TIMEOUT = timedelta(seconds=180)
CBS_TIMEOUT = timedelta(seconds=10)
NGCH_TIMEOUT = timedelta(seconds=30)
AUDIT_TIMEOUT = timedelta(seconds=15)
```

## IET Watchdog Pattern (CTS — Non-Negotiable)
```python
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
```

## Graceful Degradation (Mandatory Fallback Paths)
Every activity calling an external system MUST have a fallback — never let it crash the workflow:
```python
try:
    balance = await workflow.execute_activity(
        check_cbs_balance, retry_policy=CBS_RETRY, start_to_close_timeout=CBS_TIMEOUT,
    )
except ActivityError:
    balance = CbsResult(available=None, status="UNREACHABLE")
    # Continue with image-only path — slightly higher human review rate, acceptable
```

## Signal and Query Patterns
```python
@workflow.signal
async def receive_review_decision(self, decision: ReviewDecision) -> None:
    self._review_decision = decision

@workflow.query
def get_processing_state(self) -> str:
    return self._current_state
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
    graceful_shutdown_timeout=timedelta(minutes=2),
)
# EJ workers follow same pattern with task_queue=f"ej-normalisation-{bank_id}" — never "cts-*"
```

## Forbidden Patterns
- `asyncio.sleep()` inside a workflow — use `await workflow.sleep()` (deterministic)
- `datetime.now()` inside a workflow — use `workflow.now()` (deterministic replay)
- `random.random()` inside a workflow — use `workflow.random()` (deterministic replay)
- Calling activities directly without retry policy (use standard retry constants above)
- Sharing a Temporal task queue between CTS and EJ workers
- Starting a workflow without a deterministic workflow ID (no UUID4 — use instrument_id)
- Catching `CancelledException` and suppressing it (Temporal cancellation must propagate)
