"""
CTS Scanner Session Manager.

Tracks all ScanResults captured during a single clearing session.
Enforces no-duplicate scan IDs (idempotency guard before Temporal submission).
"""
from __future__ import annotations

from modules.cts.scanner.models import ScanResult


class ScanSessionManager:
    def __init__(self, session_id: str, bank_id: str) -> None:
        self._session_id = session_id
        self._bank_id    = bank_id
        self._scans: dict[str, ScanResult] = {}

    @property
    def scan_count(self) -> int:
        return len(self._scans)

    def add_scan(self, result: ScanResult) -> None:
        if result.scan_id in self._scans:
            raise ValueError(
                f"duplicate scan_id '{result.scan_id}' — already added to session {self._session_id}"
            )
        self._scans[result.scan_id] = result

    def list_scans(self) -> list[ScanResult]:
        return list(self._scans.values())

    def get_scan(self, scan_id: str) -> ScanResult | None:
        return self._scans.get(scan_id)
