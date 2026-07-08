"""
Tests for DEM HTTPS client — NPCI DEM Spec v20 §2 (Reqtype=RU/R/FL/A/W).

The DEMHTTPSClient wraps all CCH HTTPS POST interactions:
  Reqtype=RU  → outward upload intent (returns FileClearingType list + SFTP host)
  Reqtype=R   → confirm upload session (returns session_ref)
  Reqtype=FL  → file list query (returns DEMInwardFileInfo list)
  Reqtype=A   → acknowledgement after inward download (one per file)

All requests are form-encoded POST. All responses are key=value text lines.

RED phase: all tests fail before https_client.py exists.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.dem.models import DEMConfig, DEMEncryptionAlgo, DEMFileType, FileClearingType


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


def _ok_response(**kwargs) -> str:
    """Build a minimal success response body."""
    lines = ["StatusCode=00", "StatusDesc=Success"]
    lines.extend(f"{k}={v}" for k, v in kwargs.items())
    return "\n".join(lines) + "\n"


# ── DEMHTTPSClient.reqtype_ru ─────────────────────────────────────────────────


class TestReqtypeRU:
    """Reqtype=RU: upload intent — returns SFTP host + allowed clearing types."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    def _make_client(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        return DEMHTTPSClient(config=self.config)

    def test_returns_handshake_result(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        ru_response = _ok_response(
            SFTPHost="10.1.0.1",
            SFTPPort="22",
            FileClearingType="CXF_14,CXF_01",
            SessionRef="SES-TEST-001",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = ru_response
            result = asyncio.get_event_loop().run_until_complete(
                client.reqtype_ru(file_type=DEMFileType.CXF, clearing_type="14")
            )
        assert result is not None

    def test_sftp_host_in_result(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        ru_response = _ok_response(
            SFTPHost="10.1.0.1",
            SFTPPort="22",
            FileClearingType="CXF_14",
            SessionRef="SES-TEST-001",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = ru_response
            result = asyncio.get_event_loop().run_until_complete(
                client.reqtype_ru(file_type=DEMFileType.CXF, clearing_type="14")
            )
        assert result.sftp_host == "10.1.0.1"

    def test_sftp_port_in_result(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        ru_response = _ok_response(
            SFTPHost="10.1.0.1",
            SFTPPort="22",
            FileClearingType="CXF_01",
            SessionRef="SES-TEST-001",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = ru_response
            result = asyncio.get_event_loop().run_until_complete(
                client.reqtype_ru(file_type=DEMFileType.CXF, clearing_type="14")
            )
        assert result.sftp_port == 22

    def test_allowed_clearing_types_parsed(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        ru_response = _ok_response(
            SFTPHost="10.1.0.1",
            SFTPPort="22",
            FileClearingType="CXF_14,CXF_01",
            SessionRef="SES-TEST-001",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = ru_response
            result = asyncio.get_event_loop().run_until_complete(
                client.reqtype_ru(file_type=DEMFileType.CXF, clearing_type="14")
            )
        assert FileClearingType.CXF_14 in result.allowed_clearing_types
        assert FileClearingType.CXF_01 in result.allowed_clearing_types

    def test_non_zero_status_raises(self):
        from modules.cts.dem.https_client import DEMHTTPSClient, DEMHTTPSError
        import asyncio
        client = self._make_client()
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = "StatusCode=99\nStatusDesc=Session limit exceeded\n"
            with pytest.raises(DEMHTTPSError):
                asyncio.get_event_loop().run_until_complete(
                    client.reqtype_ru(file_type=DEMFileType.CXF, clearing_type="14")
                )


# ── DEMHTTPSClient.reqtype_fl ─────────────────────────────────────────────────


class TestReqtypeFL:
    """Reqtype=FL: inward file list query."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    def _make_client(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        return DEMHTTPSClient(config=self.config)

    def test_returns_list_of_file_info(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        fl_response = _ok_response(
            FileCount="2",
            File1="000550050_PXF_07072026_001.cxf",
            File1Type="PXF",
            File1Size="102400",
            File2="000550050_RF_07072026_001.rf",
            File2Type="RF",
            File2Size="4096",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fl_response
            result = asyncio.get_event_loop().run_until_complete(client.reqtype_fl())
        assert isinstance(result, list)

    def test_file_count_matches_response(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        fl_response = _ok_response(
            FileCount="2",
            File1="f1.pxf",
            File1Type="PXF",
            File1Size="1024",
            File2="f2.rf",
            File2Type="RF",
            File2Size="512",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fl_response
            result = asyncio.get_event_loop().run_until_complete(client.reqtype_fl())
        assert len(result) == 2

    def test_empty_file_list_returns_empty(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        fl_response = _ok_response(FileCount="0")
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fl_response
            result = asyncio.get_event_loop().run_until_complete(client.reqtype_fl())
        assert result == []

    def test_file_type_parsed(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        fl_response = _ok_response(
            FileCount="1",
            File1="f1.pxf",
            File1Type="PXF",
            File1Size="2048",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fl_response
            result = asyncio.get_event_loop().run_until_complete(client.reqtype_fl())
        assert result[0].file_type == DEMFileType.PXF

    def test_files_sorted_by_priority(self):
        """FL result must be sorted by inward download priority (PXF before RF)."""
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        # RF listed first in response, PXF second — but priority must sort PXF first
        fl_response = _ok_response(
            FileCount="2",
            File1="f1.rf",
            File1Type="RF",
            File1Size="512",
            File2="f2.pxf",
            File2Type="PXF",
            File2Size="2048",
        )
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fl_response
            result = asyncio.get_event_loop().run_until_complete(client.reqtype_fl())
        assert result[0].file_type == DEMFileType.PXF
        assert result[1].file_type == DEMFileType.RF


# ── DEMHTTPSClient.reqtype_a ──────────────────────────────────────────────────


class TestReqtypeA:
    """Reqtype=A: acknowledgement after inward file download."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    def _make_client(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        return DEMHTTPSClient(config=self.config)

    def test_ack_success_returns_true(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response()
            result = asyncio.get_event_loop().run_until_complete(
                client.reqtype_a(filename="000550050_PXF_07072026_001.cxf")
            )
        assert result is True

    def test_ack_failure_raises(self):
        from modules.cts.dem.https_client import DEMHTTPSClient, DEMHTTPSError
        import asyncio
        client = self._make_client()
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = "StatusCode=55\nStatusDesc=File not found\n"
            with pytest.raises(DEMHTTPSError):
                asyncio.get_event_loop().run_until_complete(
                    client.reqtype_a(filename="missing.pxf")
                )

    def test_post_called_with_reqtype_a(self):
        from modules.cts.dem.https_client import DEMHTTPSClient
        import asyncio
        client = self._make_client()
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response()
            asyncio.get_event_loop().run_until_complete(
                client.reqtype_a(filename="f1.pxf")
            )
        call_args = mock_post.call_args
        assert call_args is not None
        # The payload dict passed to _post must contain Reqtype=A
        payload = call_args[0][0] if call_args[0] else call_args[1].get("payload", {})
        assert payload.get("Reqtype") == "A"
