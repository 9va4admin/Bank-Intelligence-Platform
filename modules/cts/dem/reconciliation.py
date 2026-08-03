"""
DEM Reconciliation Poller — NPCI DEM Spec v20 §2.d.

CCH makes a RECONCIL CSV file available every 30 seconds.
Banks download it via SFTP (file type RECONCIL in the FL response)
and parse it to confirm which submitted files were accepted vs rejected.

CSV format (DEM spec):
  FileName,FileType,Status,ReceivedAt
  000550050_CXF_14_07072026_001.cxf,CXF,ACCEPTED,07/07/2026 10:05:00
  000550050_CXF_14_07072026_002.cxf,CXF,REJECTED,07/07/2026 10:07:33
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import List

from modules.cts.dem.models import DEMConfig


@dataclass
class ReconciliationRecord:
    filename: str
    file_type: str
    status: str
    received_at: str


class ReconciliationPoller:
    """Parses RECONCIL CSV content returned by CCH."""

    def __init__(self, config: DEMConfig) -> None:
        self._config = config

    def parse_csv(self, csv_text: str) -> List[ReconciliationRecord]:
        """Parse CCH reconciliation CSV into a list of ReconciliationRecord.

        Returns empty list if no data rows (only header present or empty string).
        """
        records: List[ReconciliationRecord] = []
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            filename = row.get("FileName", "").strip()
            if not filename:
                continue
            records.append(ReconciliationRecord(
                filename=filename,
                file_type=row.get("FileType", "").strip(),
                status=row.get("Status", "").strip(),
                received_at=row.get("ReceivedAt", "").strip(),
            ))
        return records
