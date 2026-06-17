---
name: cts-cheque-debug
description: Diagnose a stuck, failed, or anomalous CTS cheque processing workflow. Covers Temporal workflow inspection, vault miss diagnosis, IET breach risk assessment, and NGCH filing verification.
---

# Skill: Debug a CTS Cheque Processing Issue

## When to Use
User says: "cheque stuck", "workflow failed", "IET risk", "NGCH not filed", "vault miss", or provides an instrument_id / workflow_id.

## Diagnostic Tree

### Step 1 — Get Workflow State
Construct the workflow ID: `cts-{bank_id}-{instrument_id}`

Check Temporal:
```
# What to look for in Temporal UI or tctl:
temporal workflow describe --workflow-id cts-{bank_id}-{instrument_id}

States to interpret:
- RUNNING: still processing — check current activity and elapsed time
- FAILED: activity threw unhandled exception — check history for error
- TIMED_OUT: IET watchdog may have fired — check IETWatchdogWorkflow child
- COMPLETED: terminal state reached — check what state (STP_CONFIRM/RETURN/HUMAN_REVIEW)
- CANCELLED: manual intervention — check who cancelled and why
```

### Step 2 — IET Risk Assessment (CRITICAL — check this first)
```
Elapsed = now - instrument.received_at
IET limit = config.iet_minutes (default 180 min = 10,800 seconds)
Remaining = IET limit - Elapsed

IF remaining < 30 minutes: URGENT — escalate to ops_manager immediately
IF remaining < 5 minutes: CRITICAL — IETWatchdogWorkflow should have auto-filed
IF remaining < 0: IET BREACHED — check if emergency filing succeeded
```

### Step 3 — Activity-Level Diagnosis

**OCR Failed:**
- Check vLLM queue `cts-ocr` — is GOT-OCR2 model loaded?
- Check image quality in MinIO: `cts/{bank_id}/images/{instrument_id}`
- Retry count: OCR max 2 retries — if both failed, workflow routes to HUMAN_REVIEW

**Signature Verification Failed:**
- Vault key: `sig:{bank_id}:{sha256(account_number)}`
- Check Redis `redis-cts`: `GET sig:{bank_id}:{hash}`
- If vault miss: should have routed to HUMAN_REVIEW — verify this happened
- If vault hit but score low: check Siamese network — is model loaded on vLLM?

**CBS Check Timeout:**
- CBS unreachable is a graceful degradation path — should NOT cause IET breach
- Correct behavior: skip CBS balance check, continue with image-only processing
- If workflow is stuck waiting for CBS: CBS activity has no timeout configured — BUG

**NGCH Not Filed:**
- Check: was `ngch_filer` activity reached in workflow history?
- All NGCH submissions go through `modules/cts/workflows/activities/ngch_filer.py`
- NGCH filing max 3 retries with exponential backoff
- Check NGCH adapter logs for SFTP errors

**Stuck in HUMAN_REVIEW queue:**
- Check HumanReviewWorkflow: `cts-humanreview-{bank_id}-{instrument_id}`
- Timeout: 55 minutes maximum — after that, auto-returns
- Check: is ops_reviewer logged in and seeing the queue item?

### Step 4 — Audit Trail Verification
Every terminal state must have an AuditEvent in Immudb:
```sql
SELECT event_id, event_type, actor, created_at, payload->>'decision'
FROM immudb.cts_events
WHERE payload->>'instrument_id' = '{instrument_id}'
ORDER BY created_at;
```
If no audit event exists for a completed workflow: audit write failed — BUG

### Step 5 — Output Format
Report findings as:
```
INSTRUMENT: {instrument_id}
BANK: {bank_id}
IET STATUS: SAFE | AT RISK | BREACHED
WORKFLOW STATE: {state}
CURRENT ACTIVITY: {activity} (elapsed: {ms}ms)
ROOT CAUSE: {diagnosis}
RECOMMENDED ACTION: {action}
```
