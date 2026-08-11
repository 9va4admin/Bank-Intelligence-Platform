#!/usr/bin/env python3
"""
ASTRA Deployment Smoke Test
Verifies that a freshly deployed ASTRA stack is alive and accepting traffic.

Runs end-to-end:
  1. Health checks on all services
  2. ASTRA API readiness
  3. Login + JWT verification
  4. DB connectivity (via API health/ready endpoint)
  5. Kafka topics present
  6. MinIO bucket accessible
  7. Temporal namespace reachable
  8. Cheque scan submit (outward path) — verifies workflow starts

Usage:
  python scripts/smoke-test.py --base-url http://localhost:8010 \\
      --bank-id saraswat-coop \\
      --username admin@9va.in \\
      --password <password>

  # Against a bank's server IP:
  python scripts/smoke-test.py --base-url http://192.168.1.50:8010 \\
      --bank-id kotak-mah \\
      --username ops.test@kotak.internal \\
      --password <password>

  # Skip the scan submit test (no scanner image available):
  python scripts/smoke-test.py --base-url http://localhost:8010 \\
      --bank-id saraswat-coop --username admin@9va.in --password pw \\
      --skip-scan-submit

Exit codes:
  0 — all checks passed
  1 — one or more checks failed
"""

import argparse
import base64
import io
import json
import struct
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)

# ── Result tracking ───────────────────────────────────────────────────────────

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"
HEAD = "\033[96m"
RST  = "\033[0m"

results: list[dict] = []


def check(name: str, fn) -> bool:
    start = time.monotonic()
    try:
        fn()
        elapsed = (time.monotonic() - start) * 1000
        print(f"  {PASS} {name}  ({elapsed:.0f} ms)")
        results.append({"name": name, "status": "PASS", "ms": round(elapsed)})
        return True
    except AssertionError as e:
        elapsed = (time.monotonic() - start) * 1000
        print(f"  {FAIL} {name}  — {e}  ({elapsed:.0f} ms)")
        results.append({"name": name, "status": "FAIL", "reason": str(e), "ms": round(elapsed)})
        return False
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        print(f"  {FAIL} {name}  — {type(e).__name__}: {e}  ({elapsed:.0f} ms)")
        results.append({"name": name, "status": "FAIL", "reason": f"{type(e).__name__}: {e}", "ms": round(elapsed)})
        return False


def skip(name: str, reason: str):
    print(f"  {SKIP} {name}  — {reason}")
    results.append({"name": name, "status": "SKIP", "reason": reason})


# ── Minimal 1×1 white TIFF (for scan submit test) ────────────────────────────

def _make_minimal_tiff() -> bytes:
    """Returns a valid 1x1 white-pixel TIFF as bytes."""
    # IFD with the bare minimum tags for a bilevel TIFF
    # This is sufficient to pass ASTRA's image ingestion (actual processing happens in workflow)
    data = (
        b"II"            # little-endian
        + struct.pack("<H", 42)           # magic
        + struct.pack("<I", 8)            # offset to IFD
        # IFD: 7 entries
        + struct.pack("<H", 7)
        # ImageWidth=1 (SHORT, count=1, value=1)
        + struct.pack("<HHII", 256, 3, 1, 1)
        # ImageLength=1
        + struct.pack("<HHII", 257, 3, 1, 1)
        # BitsPerSample=8
        + struct.pack("<HHII", 258, 3, 1, 8)
        # Compression=1 (none)
        + struct.pack("<HHII", 259, 3, 1, 1)
        # PhotometricInterpretation=1 (BlackIsZero)
        + struct.pack("<HHII", 262, 3, 1, 1)
        # StripOffsets — points to pixel data after IFD (8 + 2 + 7*12 + 4 = 98)
        + struct.pack("<HHII", 273, 4, 1, 98)
        # StripByteCounts=1
        + struct.pack("<HHII", 279, 4, 1, 1)
        # Next IFD offset = 0 (end)
        + struct.pack("<I", 0)
        # Pixel data: 1 byte = 0xFF (white)
        + b"\xFF"
    )
    return data


# ── Tests ─────────────────────────────────────────────────────────────────────

class SmokeTest:
    def __init__(self, base_url: str, bank_id: str, username: str, password: str,
                 temporal_url: str, minio_url: str, skip_scan_submit: bool):
        self.base_url = base_url.rstrip("/")
        self.bank_id = bank_id
        self.username = username
        self.password = password
        self.temporal_url = temporal_url
        self.minio_url = minio_url
        self.skip_scan_submit = skip_scan_submit
        self.session = requests.Session()
        self.session.timeout = 10
        self.token: Optional[str] = None

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers["X-Bank-ID"] = self.bank_id
        return self.session.request(method, url, headers=headers, **kwargs)

    # ── Group 1: Service health ───────────────────────────────────────────────

    def test_api_liveness(self):
        r = self._api("GET", "/health/live")
        assert r.status_code == 200, f"status={r.status_code}"
        body = r.json()
        assert body.get("status") == "ok", f"body={body}"

    def test_api_readiness(self):
        r = self._api("GET", "/health/ready")
        assert r.status_code == 200, f"status={r.status_code} — services may not be up yet"
        body = r.json()
        assert body.get("status") == "ready", f"body={body}"
        # Surface individual check failures clearly
        checks = body.get("checks", {})
        failed = [k for k, v in checks.items() if not v]
        assert not failed, f"Unhealthy deps: {failed}"

    def test_temporal_ui(self):
        r = requests.get(f"{self.temporal_url}/api/v1/namespaces", timeout=10)
        assert r.status_code == 200, f"Temporal UI status={r.status_code}"
        namespaces = r.json().get("namespaces", [])
        names = [n.get("namespaceInfo", {}).get("name") for n in namespaces]
        assert "default" in names or len(namespaces) > 0, f"No namespaces found: {names}"

    def test_minio_health(self):
        r = requests.get(f"{self.minio_url}/minio/health/live", timeout=10)
        assert r.status_code == 200, f"MinIO health status={r.status_code}"

    # ── Group 2: Authentication ───────────────────────────────────────────────

    def test_login(self):
        r = self._api("POST", "/v1/auth/login", json={
            "username": self.username,
            "password": self.password,
            "bank_id": self.bank_id,
        })
        assert r.status_code == 200, f"Login failed: status={r.status_code} body={r.text[:300]}"
        body = r.json()
        assert "access_token" in body, f"No access_token in response: {body}"
        self.token = body["access_token"]
        assert len(self.token) > 50, "Token suspiciously short"

    def test_me_endpoint(self):
        assert self.token, "Login must pass first"
        r = self._api("GET", "/v1/auth/me")
        assert r.status_code == 200, f"status={r.status_code}"
        body = r.json()
        assert body.get("bank_id") == self.bank_id, f"bank_id mismatch: {body}"

    # ── Group 3: CTS connectivity ─────────────────────────────────────────────

    def test_cts_branch_list(self):
        assert self.token, "Login must pass first"
        r = self._api("GET", f"/v1/cts/admin/branches?bank_id={self.bank_id}&limit=1")
        assert r.status_code in (200, 403), f"Unexpected status: {r.status_code} {r.text[:200]}"
        # 403 = authenticated but insufficient role — connectivity confirmed

    def test_cts_inward_queue(self):
        assert self.token, "Login must pass first"
        r = self._api("GET", "/v1/cts/inward/queue?limit=1")
        assert r.status_code in (200, 403), f"Unexpected: {r.status_code} {r.text[:200]}"

    # ── Group 4: Scan submit (end-to-end outward path) ────────────────────────

    def test_upload_url_request(self) -> tuple[str, str, str, str]:
        """Requests pre-signed upload URLs — verifies MinIO and API wiring."""
        assert self.token, "Login must pass first"
        scan_id = f"SMOKE-TEST-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        r = self._api("POST", "/v1/cts/outward/scan/upload-url", json={
            "bank_id": self.bank_id,
            "scan_id": scan_id,
            "branch_ifsc": "SMOKE001001",
        })
        assert r.status_code == 200, f"upload-url failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert "front_presigned_url" in body, f"Missing front_presigned_url: {body}"
        assert "rear_presigned_url"  in body, f"Missing rear_presigned_url: {body}"
        return scan_id, body["front_presigned_url"], body["rear_presigned_url"], body.get("scan_id", scan_id)

    def test_scan_submit(self):
        """Full outward scan flow: upload images + submit → verify workflow_id returned."""
        assert self.token, "Login must pass first"

        scan_id, front_url, rear_url, server_scan_id = self.test_upload_url_request()

        tiff_bytes = _make_minimal_tiff()

        # Upload front image
        put_r = requests.put(front_url, data=tiff_bytes,
                             headers={"Content-Type": "image/tiff"}, timeout=30)
        assert put_r.status_code in (200, 201, 204), \
            f"Front image PUT failed: {put_r.status_code}"

        # Upload rear image
        put_r = requests.put(rear_url, data=tiff_bytes,
                             headers={"Content-Type": "image/tiff"}, timeout=30)
        assert put_r.status_code in (200, 201, 204), \
            f"Rear image PUT failed: {put_r.status_code}"

        # Submit scan
        r = self._api("POST", "/v1/cts/outward/scan/submit", json={
            "bank_id":       self.bank_id,
            "scan_id":       server_scan_id,
            "branch_ifsc":   "SMOKE001001",
            "session_id":    "SMOKE-SESSION-001",
            "micr_raw":      "000001 230016 1234567890  001",
            "cheque_number": "000001",
            "imprinter_stamped": False,
            "uv_scan_passed":    False,
            "_smoke_test":   True,   # tells API to create workflow in TEST mode
        })
        assert r.status_code in (200, 202), \
            f"Scan submit failed: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert "workflow_id" in body, f"No workflow_id in response: {body}"
        wf_id = body["workflow_id"]
        assert wf_id.startswith("cts-"), f"Unexpected workflow_id format: {wf_id}"

    # ── Run all ───────────────────────────────────────────────────────────────

    def run(self, skip_scan_submit: bool):
        section = lambda t: print(f"\n{HEAD}  {t}{RST}")

        section("Group 1 — Service Health")
        check("API liveness (/health/live)", self.test_api_liveness)
        check("API readiness (/health/ready — DB/Redis/Kafka/Vault)", self.test_api_readiness)
        check("Temporal UI reachable", self.test_temporal_ui)
        check("MinIO health", self.test_minio_health)

        section("Group 2 — Authentication")
        login_ok = check("Login → JWT issued", self.test_login)
        if login_ok:
            check("GET /v1/auth/me — JWT valid", self.test_me_endpoint)
        else:
            skip("GET /v1/auth/me", "Login failed")

        section("Group 3 — CTS Connectivity")
        if login_ok:
            check("Branch list endpoint reachable", self.test_cts_branch_list)
            check("Inward queue endpoint reachable", self.test_cts_inward_queue)
        else:
            skip("Branch list", "Login failed")
            skip("Inward queue", "Login failed")

        section("Group 4 — Outward Scan End-to-End")
        if not login_ok:
            skip("Pre-signed upload URL request", "Login failed")
            skip("Full scan submit → workflow_id", "Login failed")
        elif skip_scan_submit:
            skip("Pre-signed upload URL request", "--skip-scan-submit set")
            skip("Full scan submit → workflow_id", "--skip-scan-submit set")
        else:
            check("Pre-signed upload URL request", lambda: self.test_upload_url_request())
            check("Full scan submit → workflow_id returned", self.test_scan_submit)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="ASTRA deployment smoke test")
    ap.add_argument("--base-url",    default="http://localhost:8010", help="ASTRA API base URL")
    ap.add_argument("--bank-id",     required=True, help="Bank ID (e.g. saraswat-coop)")
    ap.add_argument("--username",    required=True, help="Test user email")
    ap.add_argument("--password",    required=True, help="Test user password")
    ap.add_argument("--temporal-url",default="http://localhost:18088", help="Temporal UI URL")
    ap.add_argument("--minio-url",   default="http://localhost:19091", help="MinIO URL")
    ap.add_argument("--skip-scan-submit", action="store_true",
                    help="Skip the scan submit test (no image needed, but end-to-end not verified)")
    ap.add_argument("--json-report", metavar="FILE",
                    help="Write JSON report to FILE")
    args = ap.parse_args()

    print()
    print(f"  {HEAD}ASTRA Deployment Smoke Test{RST}")
    print(f"  API     : {args.base_url}")
    print(f"  Bank    : {args.bank_id}")
    print(f"  User    : {args.username}")
    print(f"  Run at  : {datetime.now(timezone.utc).isoformat()}")

    t = SmokeTest(
        base_url=args.base_url,
        bank_id=args.bank_id,
        username=args.username,
        password=args.password,
        temporal_url=args.temporal_url,
        minio_url=args.minio_url,
        skip_scan_submit=args.skip_scan_submit,
    )
    t.run(args.skip_scan_submit)

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results)

    print()
    print("  " + "─" * 50)
    color = "\033[92m" if failed == 0 else "\033[91m"
    print(f"  {color}Results: {passed} passed, {failed} failed, {skipped} skipped / {total} total{RST}")

    if failed > 0:
        print()
        print("  Failed checks:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    ✗ {r['name']}")
                print(f"      {r.get('reason', '')}")

    # JSON report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bank_id": args.bank_id,
        "base_url": args.base_url,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "checks": results,
    }

    if args.json_report:
        Path(args.json_report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  Report written: {args.json_report}")

    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
