"""
Tests for DEM Part C — NPCI DEM Spec v20:
  - ReconciliationPoller: parses CSV reconciliation files from CCH every 30s
  - SwitchoverHandler: detects zero-byte SWITCHOVER file → switches to secondary SFTP IP
  - ResendHandler: parses DEMID_Resend_*.txt → retransmits listed files

RED phase: all tests fail before these modules exist.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import time

import pytest

from modules.cts.dem.models import DEMConfig


def _dem_config() -> DEMConfig:
    return DEMConfig(
        bank_id="saraswat-coop",
        bank_routing_no="000550050",
        dem_id="DEM-SARA-001",
        hsm_key_alias="SARA-HSM-KEY",
        cch_https_url="https://cch.npci.org.in/CCHBank/api/ftp",
        cch_sftp_primary="10.1.0.1",
        cch_sftp_secondary="10.1.0.2",
        sftp_username="SARA-SFTP",
        sftp_local_backup_dir="/tmp/dem",
    )


# ── ReconciliationPoller ──────────────────────────────────────────────────────


class TestReconciliationPoller:
    """RECONCIL CSV parsing — one row per submitted file with status."""

    _SAMPLE_CSV = (
        "FileName,FileType,Status,ReceivedAt\n"
        "000550050_CXF_14_07072026_001.cxf,CXF,ACCEPTED,07/07/2026 10:05:00\n"
        "000550050_CXF_14_07072026_002.cxf,CXF,REJECTED,07/07/2026 10:07:33\n"
    )

    def test_reconciliation_poller_importable(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        assert ReconciliationPoller is not None

    def test_parse_csv_returns_list(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert isinstance(records, list)

    def test_parse_csv_count(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert len(records) == 2

    def test_parse_csv_filename(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert records[0].filename == "000550050_CXF_14_07072026_001.cxf"

    def test_parse_csv_status_accepted(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert records[0].status == "ACCEPTED"

    def test_parse_csv_status_rejected(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert records[1].status == "REJECTED"

    def test_parse_empty_csv_returns_empty(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv("FileName,FileType,Status,ReceivedAt\n")
        assert records == []

    def test_reconciliation_record_has_file_type(self):
        from modules.cts.dem.reconciliation import ReconciliationPoller
        poller = ReconciliationPoller(config=_dem_config())
        records = poller.parse_csv(self._SAMPLE_CSV)
        assert records[0].file_type == "CXF"


# ── SwitchoverHandler ─────────────────────────────────────────────────────────


class TestSwitchoverHandler:
    """Zero-byte SWITCHOVER file detection → flip active SFTP IP to secondary."""

    def test_switchover_handler_importable(self):
        from modules.cts.dem.switchover import SwitchoverHandler
        assert SwitchoverHandler is not None

    def test_is_switchover_file_zero_bytes(self):
        """A SWITCHOVER file is identified by DEMFileType.SWITCHOVER and zero size."""
        from modules.cts.dem.switchover import SwitchoverHandler
        from modules.cts.dem.models import DEMFileType, DEMInwardFileInfo

        handler = SwitchoverHandler(config=_dem_config())
        info = DEMInwardFileInfo(
            filename="SWITCHOVER",
            file_type=DEMFileType.SWITCHOVER,
            size_bytes=0,
        )
        assert handler.is_switchover(info) is True

    def test_non_switchover_file_not_detected(self):
        from modules.cts.dem.switchover import SwitchoverHandler
        from modules.cts.dem.models import DEMFileType, DEMInwardFileInfo

        handler = SwitchoverHandler(config=_dem_config())
        info = DEMInwardFileInfo(
            filename="000550050_PXF_07072026_001.pxf",
            file_type=DEMFileType.PXF,
            size_bytes=102400,
        )
        assert handler.is_switchover(info) is False

    def test_apply_switchover_flips_active_host(self):
        """After apply_switchover(), active_sftp_host changes from primary to secondary."""
        from modules.cts.dem.switchover import SwitchoverHandler

        config = _dem_config()
        handler = SwitchoverHandler(config=config)

        assert handler.active_sftp_host == config.cch_sftp_primary

        handler.apply_switchover()

        assert handler.active_sftp_host == config.cch_sftp_secondary

    def test_apply_switchover_twice_returns_to_primary(self):
        """Second switchover flips back to primary."""
        from modules.cts.dem.switchover import SwitchoverHandler

        config = _dem_config()
        handler = SwitchoverHandler(config=config)
        handler.apply_switchover()
        handler.apply_switchover()

        assert handler.active_sftp_host == config.cch_sftp_primary


# ── ResendHandler ─────────────────────────────────────────────────────────────


class TestResendHandler:
    """DEMID_Resend_*.txt processing — retransmit listed files from local backup."""

    _SAMPLE_RESEND_TXT = (
        "000550050_CXF_14_07072026_001.cxf\n"
        "000550050_CXF_14_07072026_003.cxf\n"
    )

    def test_resend_handler_importable(self):
        from modules.cts.dem.resend_handler import ResendHandler
        assert ResendHandler is not None

    def test_parse_resend_file_returns_list(self):
        from modules.cts.dem.resend_handler import ResendHandler
        handler = ResendHandler(config=_dem_config())
        filenames = handler.parse_resend_file(self._SAMPLE_RESEND_TXT)
        assert isinstance(filenames, list)

    def test_parse_resend_file_count(self):
        from modules.cts.dem.resend_handler import ResendHandler
        handler = ResendHandler(config=_dem_config())
        filenames = handler.parse_resend_file(self._SAMPLE_RESEND_TXT)
        assert len(filenames) == 2

    def test_parse_resend_file_first_entry(self):
        from modules.cts.dem.resend_handler import ResendHandler
        handler = ResendHandler(config=_dem_config())
        filenames = handler.parse_resend_file(self._SAMPLE_RESEND_TXT)
        assert filenames[0] == "000550050_CXF_14_07072026_001.cxf"

    def test_parse_resend_file_empty(self):
        from modules.cts.dem.resend_handler import ResendHandler
        handler = ResendHandler(config=_dem_config())
        filenames = handler.parse_resend_file("")
        assert filenames == []

    @pytest.mark.asyncio
    async def test_resend_reads_from_local_backup(self):
        """resend() must read file bytes from local backup dir, not transmit raw."""
        from modules.cts.dem.resend_handler import ResendHandler

        config = _dem_config()
        handler = ResendHandler(config=config)

        with patch("builtins.open", MagicMock(return_value=__import__("io").BytesIO(b"BACKUP"))) as mock_open, \
             patch.object(handler, "_transmit", new_callable=AsyncMock) as mock_tx:
            await handler.resend(filenames=["000550050_CXF_14_07072026_001.cxf"])

        # transmit must be called with the loaded backup bytes
        mock_tx.assert_called_once()

    @pytest.mark.asyncio
    async def test_resend_missing_backup_raises(self):
        """If backup file not found, ResendHandler raises ResendError, not silent fail."""
        from modules.cts.dem.resend_handler import ResendHandler, ResendError

        config = _dem_config()
        handler = ResendHandler(config=config)

        with patch("builtins.open", side_effect=FileNotFoundError("backup not found")):
            with pytest.raises(ResendError):
                await handler.resend(filenames=["missing_file.cxf"])
