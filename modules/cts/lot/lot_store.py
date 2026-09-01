"""
LotStore — CTS-2010 NGCH file builder.

Reads accepted instruments for a sealed lot from cts.outward_scan_events
(for instrument_ids) + cts.cheque_instruments (for field values), assembles
a CTS-2010 compliant CXF XML file, uploads to MinIO, and returns the object
key and SHA-256 checksum.

Usage:
    store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")
    file_path, sha256 = await store.build_ngch_file(
        lot_number="LOT_SVCB0000002_20260901_AM_01",
        bank_id="saraswat-coop",
        bank_ifsc="SVCB0000002",
        session_id="SES-SVCB-20260901-001",
        clearing_date="2026-09-01",
    )
"""
from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from datetime import timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger()


class LotStore:
    """
    Dependency-injected at worker startup.  `db_pool` is an asyncpg pool;
    `minio_client` is a minio.Minio instance (sync — called in executor or
    directly since XML assembly is fast and upload latency dominates).
    """

    def __init__(
        self,
        *,
        db_pool: Any,
        minio_client: Any,
        bucket: str = "astra-cts",
    ) -> None:
        self._db = db_pool
        self._minio = minio_client
        self._bucket = bucket

    # ------------------------------------------------------------------
    # Public API (called from build_ngch_file activity)
    # ------------------------------------------------------------------

    async def build_ngch_file(
        self,
        lot_number: str,
        bank_id: str,
        bank_ifsc: str,
        session_id: str,
        clearing_date: str,
    ) -> tuple[str, str]:
        """
        Returns (minio_object_key, sha256_hex_of_xml_bytes).

        Empty lot → uploads a zero-item CXF (NGCH will reject it; upstream
        callers should validate instrument_count > 0 before filing).
        """
        instrument_ids = await self._fetch_lot_instrument_ids(bank_id, lot_number)
        instruments = await self._fetch_instrument_details(bank_id, instrument_ids) if instrument_ids else []

        xml_bytes = self._build_cxf_xml(
            lot_number=lot_number,
            bank_ifsc=bank_ifsc,
            clearing_date=clearing_date,
            instruments=instruments,
        )

        checksum = hashlib.sha256(xml_bytes).hexdigest()
        object_key = f"cts/ngch/{bank_id}/{lot_number}/ngch_file.xml"

        self._upload(object_key, xml_bytes)

        log.info(
            "lot_store.ngch_file_built",
            lot_number=lot_number,
            bank_id=bank_id,
            instrument_count=len(instruments),
            object_key=object_key,
            checksum_prefix=checksum[:8],
        )
        return object_key, checksum

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _fetch_lot_instrument_ids(self, bank_id: str, lot_number: str) -> list[str]:
        """Returns instrument_ids for ACCEPTED events in this lot."""
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT instrument_id
                FROM cts.outward_scan_events
                WHERE lot_id = $1
                  AND bank_id = $2
                  AND outcome = 'ACCEPTED'
                  AND instrument_id IS NOT NULL
                ORDER BY scanned_at
                """,
                lot_number,
                bank_id,
            )
        return [r["instrument_id"] for r in rows]

    async def _fetch_instrument_details(self, bank_id: str, instrument_ids: list[str]) -> list[dict]:
        """Fetches non-PII cheque fields needed for CXF assembly."""
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    instrument_id,
                    cheque_number,
                    micr_code,
                    drawee_ifsc,
                    presenting_ifsc,
                    amount_paise,
                    cheque_date::TEXT AS cheque_date,
                    account_last4
                FROM cts.cheque_instruments
                WHERE instrument_id = ANY($1)
                  AND bank_id = $2
                """,
                instrument_ids,
                bank_id,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # CXF XML builder (CTS-2010 compliant structure)
    # ------------------------------------------------------------------

    def _build_cxf_xml(
        self,
        lot_number: str,
        bank_ifsc: str,
        clearing_date: str,
        instruments: list[dict],
    ) -> bytes:
        """
        Builds a CTS-2010 CXF (Cheque Exchange Format) XML file.

        Structure matches the NPCI/NGCH prescribed schema:
          <CXF version="2.0">
            <BatchHeader> ... </BatchHeader>
            <Items>
              <Item seq="N"> ... </Item>
            </Items>
          </CXF>

        Amount is in paise (integer) as required by NGCH.
        No PII is included — account_number is excluded; only
        non-PII cheque fields flow through.
        """
        root = ET.Element("CXF", {"version": "2.0"})

        header = ET.SubElement(root, "BatchHeader")
        ET.SubElement(header, "InstitutionCode").text = bank_ifsc
        ET.SubElement(header, "BatchNumber").text = lot_number
        ET.SubElement(header, "BatchDate").text = clearing_date
        ET.SubElement(header, "ItemCount").text = str(len(instruments))

        items = ET.SubElement(root, "Items")
        for seq, instr in enumerate(instruments, start=1):
            item = ET.SubElement(items, "Item", {"seq": str(seq)})
            ET.SubElement(item, "MICR").text = instr.get("micr_code", "")
            ET.SubElement(item, "ChequeNumber").text = instr.get("cheque_number", "")
            ET.SubElement(item, "DraweeIFSC").text = instr.get("drawee_ifsc", "")
            ET.SubElement(item, "PresentingIFSC").text = instr.get("presenting_ifsc", "")
            ET.SubElement(item, "AmountPaise").text = str(instr.get("amount_paise", 0))
            ET.SubElement(item, "ChequeDate").text = str(instr.get("cheque_date", ""))

        tree = ET.ElementTree(root)
        buf = io.BytesIO()
        tree.write(buf, encoding="utf-8", xml_declaration=True)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # MinIO upload (sync — minio-py is synchronous)
    # ------------------------------------------------------------------

    def _upload(self, object_key: str, data: bytes) -> None:
        self._minio.put_object(
            self._bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type="application/xml",
        )
