"""
ASTRA CTS 10K×2 Scale Test — 10,000 inward + 10,000 outward cheques via Temporal.

All workflows start with execution_timeout so no cheque can get stuck forever.
Starts all 20,000 workflows concurrently, then polls for completion in batches.

Usage:
    python scratchpad/scale_test_10k.py --bank-id saraswat-coop
    python scratchpad/scale_test_10k.py --bank-id saraswat-coop --inward 100 --outward 100
    python scratchpad/scale_test_10k.py --bank-id saraswat-coop --dry-run

Prerequisites:
    1. Temporal running:  temporal server start-dev --ui-port 8233 --port 7233
       (or dev:  py -m temporalio.testing ... see ASTRA dev setup)
    2. Worker running:    python -m modules.cts.worker --bank-id saraswat-coop
    3. API server:        uvicorn apps.api.main:app --port 8080
"""
from __future__ import annotations

import asyncio
import argparse
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── configuration ──────────────────────────────────────────────────────────────

TEMPORAL_ADDRESS = "localhost:17233"
NAMESPACE = "default"
API_BASE = "http://localhost:8080"

INWARD_WORKFLOW_NAME  = "ChequeProcessingWorkflow"
OUTWARD_WORKFLOW_NAME = "OutwardScanWorkflow"

# execution_timeout: inward = 4h (IET window + buffer), outward = 24h (clearing session)
INWARD_EXEC_TIMEOUT  = timedelta(hours=4)
OUTWARD_EXEC_TIMEOUT = timedelta(hours=24)

# How often to poll status (seconds)
POLL_INTERVAL_S = 5
# Max total wait time for all workflows to finish
MAX_WAIT_S = 3600  # 1 hour


# ── helpers ────────────────────────────────────────────────────────────────────

def _inward_input(bank_id: str, idx: int) -> dict:
    instrument_id = f"INW-SCALE-{int(time.time())}-{idx:05d}"
    return {
        "instrument_id": instrument_id,
        "bank_id": bank_id,
        "account_number": f"91120000{idx:05d}",
        "ifsc": "SBIN0000001",
        "amount": 50000.0 + (idx % 10) * 10000,
        "cheque_number": f"{500000 + idx}",
        "micr_code": "400002001",
        "payee_name": f"Test Payee {idx}",
        "drawer_name": f"Test Drawer {idx}",
        "date_on_cheque": "20-08-2026",
        "image_path": f"minio://cts-images/scale/INW-{idx:05d}.tif",
        "iet_deadline": (datetime.now(tz=timezone.utc) + timedelta(hours=3)).isoformat(),
        "smb_id": None,
        "session_id": f"SESS-SCALE-{int(time.time())}",
    }


def _outward_input(bank_id: str, idx: int) -> dict:
    instrument_id = f"OUT-SCALE-{int(time.time())}-{idx:05d}"
    return {
        "instrument_id": instrument_id,
        "bank_id": bank_id,
        "account_number": f"91120001{idx:05d}",
        "ifsc": "SBIN0000001",
        "amount": 75000.0 + (idx % 8) * 5000,
        "cheque_number": f"{600000 + idx}",
        "micr_code": "400002001",
        "payee_name": f"Out Payee {idx}",
        "drawer_name": f"Out Drawer {idx}",
        "date_on_cheque": "20-08-2026",
        "image_path": f"minio://cts-images/scale/OUT-{idx:05d}.tif",
        "session_id": f"SESS-SCALE-OUT-{int(time.time())}",
        "bank_ifsc": "SARB0000001",
    }


async def start_all(
    client,
    bank_id: str,
    n_inward: int,
    n_outward: int,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    """Fire all workflow starts concurrently. Returns (inward_ids, outward_ids)."""
    from temporalio.client import WorkflowAlreadyStartedError

    ts = int(time.time())
    task_queue = f"cts-processing-{bank_id}"
    inward_ids: list[str] = []
    outward_ids: list[str] = []

    if dry_run:
        print(f"[DRY-RUN] Would start {n_inward} inward + {n_outward} outward workflows")
        return (
            [f"cts-{bank_id}-INW-SCALE-{ts}-{i:05d}" for i in range(n_inward)],
            [f"cts-{bank_id}-OUT-SCALE-{ts}-{i:05d}" for i in range(n_outward)],
        )

    async def start_inward(idx: int) -> Optional[str]:
        inp = _inward_input(bank_id, idx)
        wf_id = f"cts-{bank_id}-{inp['instrument_id']}"
        try:
            await client.start_workflow(
                INWARD_WORKFLOW_NAME,
                inp,
                id=wf_id,
                task_queue=task_queue,
                execution_timeout=INWARD_EXEC_TIMEOUT,
            )
            return wf_id
        except WorkflowAlreadyStartedError:
            return wf_id  # idempotent — already running, count it
        except Exception as e:
            print(f"  WARN: Failed to start inward {idx}: {e}", flush=True)
            return None

    async def start_outward(idx: int) -> Optional[str]:
        inp = _outward_input(bank_id, idx)
        wf_id = f"cts-{bank_id}-{inp['instrument_id']}"
        try:
            await client.start_workflow(
                OUTWARD_WORKFLOW_NAME,
                inp,
                id=wf_id,
                task_queue=task_queue,
                execution_timeout=OUTWARD_EXEC_TIMEOUT,
            )
            return wf_id
        except WorkflowAlreadyStartedError:
            return wf_id
        except Exception as e:
            print(f"  WARN: Failed to start outward {idx}: {e}", flush=True)
            return None

    print(f"Starting {n_inward} inward workflows...", flush=True)
    t0 = time.perf_counter()
    inward_tasks = [start_inward(i) for i in range(n_inward)]
    results = await asyncio.gather(*inward_tasks)
    inward_ids = [r for r in results if r]
    print(f"  → {len(inward_ids)}/{n_inward} inward started in {time.perf_counter()-t0:.1f}s", flush=True)

    print(f"Starting {n_outward} outward workflows...", flush=True)
    t0 = time.perf_counter()
    outward_tasks = [start_outward(i) for i in range(n_outward)]
    results = await asyncio.gather(*outward_tasks)
    outward_ids = [r for r in results if r]
    print(f"  → {len(outward_ids)}/{n_outward} outward started in {time.perf_counter()-t0:.1f}s", flush=True)

    return inward_ids, outward_ids


async def poll_until_done(
    client,
    all_ids: list[str],
    label: str,
    dry_run: bool,
) -> dict:
    """Poll workflow statuses until all are terminal or MAX_WAIT_S exceeded."""
    from temporalio.client import WorkflowExecutionStatus

    if dry_run:
        print(f"[DRY-RUN] Skipping poll for {len(all_ids)} {label} workflows")
        return {"completed": 0, "failed": 0, "timeout": 0, "running": len(all_ids), "total": len(all_ids)}

    terminal = {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    }

    done: dict[str, str] = {}  # wf_id → status name
    deadline = time.time() + MAX_WAIT_S
    total = len(all_ids)

    while time.time() < deadline:
        pending = [wid for wid in all_ids if wid not in done]
        if not pending:
            break

        batch_size = 50
        for i in range(0, len(pending), batch_size):
            chunk = pending[i:i + batch_size]
            handles = [client.get_workflow_handle(wid) for wid in chunk]
            descs = await asyncio.gather(*[h.describe() for h in handles], return_exceptions=True)
            for wid, desc in zip(chunk, descs):
                if isinstance(desc, Exception):
                    continue
                if desc.status in terminal:
                    done[wid] = desc.status.name

        completed = sum(1 for s in done.values() if s == "COMPLETED")
        failed = sum(1 for s in done.values() if s in ("FAILED", "CANCELED", "TERMINATED"))
        timed_out = sum(1 for s in done.values() if s == "TIMED_OUT")
        still_running = total - len(done)

        print(
            f"  [{label}] done={len(done)}/{total} "
            f"OK={completed} FAIL={failed} TIMEOUT={timed_out} RUNNING={still_running}",
            flush=True,
        )

        if len(done) >= total:
            break
        await asyncio.sleep(POLL_INTERVAL_S)

    completed = sum(1 for s in done.values() if s == "COMPLETED")
    failed = sum(1 for s in done.values() if s in ("FAILED", "CANCELED", "TERMINATED"))
    timed_out = sum(1 for s in done.values() if s == "TIMED_OUT")
    still_running = total - len(done)

    return {
        "completed": completed,
        "failed": failed,
        "timeout": timed_out,
        "running": still_running,
        "total": total,
    }


async def run(bank_id: str, n_inward: int, n_outward: int, dry_run: bool) -> None:
    try:
        from temporalio.client import Client
        from shared.temporal.converter import pydantic_data_converter
    except ImportError:
        print("ERROR: temporalio not installed. Run: pip install temporalio", flush=True)
        sys.exit(1)

    print(f"Connecting to Temporal at {TEMPORAL_ADDRESS}...", flush=True)
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=NAMESPACE, data_converter=pydantic_data_converter,
    )
    print(f"Connected. Starting scale test: {n_inward} inward + {n_outward} outward", flush=True)

    test_start = time.perf_counter()

    inward_ids, outward_ids = await start_all(client, bank_id, n_inward, n_outward, dry_run)

    print(f"\nPolling inward workflows...", flush=True)
    inward_result = await poll_until_done(client, inward_ids, "INWARD", dry_run)

    print(f"\nPolling outward workflows...", flush=True)
    outward_result = await poll_until_done(client, outward_ids, "OUTWARD", dry_run)

    elapsed = time.perf_counter() - test_start

    print("\n" + "=" * 70, flush=True)
    print("SCALE TEST RESULTS", flush=True)
    print("=" * 70, flush=True)
    print(f"Total elapsed:  {elapsed:.1f}s ({elapsed/60:.1f}min)", flush=True)
    print(f"", flush=True)
    print(f"INWARD  ({n_inward}):", flush=True)
    print(f"  COMPLETED: {inward_result['completed']}", flush=True)
    print(f"  FAILED:    {inward_result['failed']}", flush=True)
    print(f"  TIMED_OUT: {inward_result['timeout']}", flush=True)
    print(f"  RUNNING:   {inward_result['running']}", flush=True)
    print(f"", flush=True)
    print(f"OUTWARD ({n_outward}):", flush=True)
    print(f"  COMPLETED: {outward_result['completed']}", flush=True)
    print(f"  FAILED:    {outward_result['failed']}", flush=True)
    print(f"  TIMED_OUT: {outward_result['timeout']}", flush=True)
    print(f"  RUNNING:   {outward_result['running']}", flush=True)
    print(f"", flush=True)

    total_ok = inward_result['completed'] + outward_result['completed']
    total_all = n_inward + n_outward
    success_pct = total_ok / total_all * 100 if total_all > 0 else 0
    print(f"OVERALL: {total_ok}/{total_all} completed ({success_pct:.1f}%)", flush=True)

    report = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "bank_id": bank_id,
        "elapsed_s": round(elapsed, 2),
        "inward": inward_result,
        "outward": outward_result,
        "success_pct": round(success_pct, 2),
        "dry_run": dry_run,
    }
    report_path = f"scratchpad/scale_test_result_{int(time.time())}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="ASTRA CTS 10K×2 Scale Test")
    parser.add_argument("--bank-id", required=True)
    parser.add_argument("--inward", type=int, default=10000, help="Number of inward cheques (default 10000)")
    parser.add_argument("--outward", type=int, default=10000, help="Number of outward cheques (default 10000)")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't start workflows")
    args = parser.parse_args()

    asyncio.run(run(args.bank_id, args.inward, args.outward, args.dry_run))


if __name__ == "__main__":
    main()
