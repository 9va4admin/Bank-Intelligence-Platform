"""
Tests for get_signatory_data() across all three CBS connectors.

Covers:
  - Happy path: returns list[CBSSignatoryData] with specimen_images
  - AccountNotFoundError on 404
  - CBSUnavailableError on network failure
  - name_masked field is masked (P*** format) — never full name
  - Empty specimen_images handled gracefully (no crash)
  - operation_type included in result
"""
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.cbs_connector.base import CBSSignatoryData
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError


# ─── Finacle ────────────────────────────────────────────────────────────────

class TestFinacleGetSignatoryData:
    def _make_connector(self):
        from shared.cbs_connector.finacle import FinacleCBSConnector
        c = FinacleCBSConnector(base_url="http://finacle.internal", bank_id="kotak-mah")
        c._http = AsyncMock()
        c._ready = True
        return c

    def _mock_response(self, data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    @pytest.mark.asyncio
    async def test_happy_path_returns_signatory_data(self):
        img_b64 = base64.b64encode(b"fake_jpeg_bytes").decode()
        c = self._make_connector()
        c._http.get = AsyncMock(return_value=self._mock_response({
            "signatories": [{
                "signatoryId": "SIG-001",
                "role": "CFO",
                "nameMasked": "P***",
                "operationType": "J",
                "specimens": [{"imageBase64": img_b64}],
            }]
        }))
        result = await c.get_signatory_data("ACC001", "kotak-mah")
        assert len(result) == 1
        assert isinstance(result[0], CBSSignatoryData)
        assert result[0].signatory_id == "SIG-001"
        assert result[0].role == "CFO"
        assert result[0].name_masked == "P***"
        assert len(result[0].specimen_images) == 1
        assert result[0].specimen_images[0] == b"fake_jpeg_bytes"

    @pytest.mark.asyncio
    async def test_account_not_found_raises_error(self):
        c = self._make_connector()
        resp = self._mock_response({"error": "NOT_FOUND"}, status_code=404)
        c._http.get = AsyncMock(return_value=resp)
        with pytest.raises((AccountNotFoundError, CBSUnavailableError)):
            await c.get_signatory_data("ACC_MISSING", "kotak-mah")

    @pytest.mark.asyncio
    async def test_network_failure_raises_cbs_unavailable(self):
        c = self._make_connector()
        c._http.get = AsyncMock(side_effect=ConnectionError("timeout"))
        with pytest.raises(CBSUnavailableError):
            await c.get_signatory_data("ACC001", "kotak-mah")

    @pytest.mark.asyncio
    async def test_empty_specimen_list_handled_gracefully(self):
        c = self._make_connector()
        c._http.get = AsyncMock(return_value=self._mock_response({
            "signatories": [{
                "signatoryId": "SIG-001",
                "role": "CFO",
                "nameMasked": "P***",
                "operationType": "J",
                "specimens": [],  # no specimens
            }]
        }))
        result = await c.get_signatory_data("ACC001", "kotak-mah")
        assert len(result) == 1
        assert result[0].specimen_images == []

    @pytest.mark.asyncio
    async def test_name_masked_preserved_as_received(self):
        """name_masked comes from CBS already masked — connector must not re-mask."""
        img_b64 = base64.b64encode(b"img").decode()
        c = self._make_connector()
        c._http.get = AsyncMock(return_value=self._mock_response({
            "signatories": [{
                "signatoryId": "SIG-002",
                "role": "DIRECTOR",
                "nameMasked": "R***",
                "operationType": "L",
                "specimens": [{"imageBase64": img_b64}],
            }]
        }))
        result = await c.get_signatory_data("ACC001", "kotak-mah")
        assert result[0].name_masked == "R***"
        assert result[0].operation_type == "L"


# ─── BaNCS ──────────────────────────────────────────────────────────────────

class TestBaNCSGetSignatoryData:
    def _make_connector(self):
        from shared.cbs_connector.bancs import BaNCSCBSConnector
        c = BaNCSCBSConnector(base_url="http://bancs.internal", bank_id="sbi")
        c._http = AsyncMock()
        c._ready = True
        return c

    def _mock_response(self, data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    @pytest.mark.asyncio
    async def test_happy_path_returns_signatory_data(self):
        img_b64 = base64.b64encode(b"bancs_jpeg").decode()
        c = self._make_connector()
        c._http.post = AsyncMock(return_value=self._mock_response({
            "response": {
                "signatories": [{
                    "id": "SIG-B01",
                    "role": "TRUSTEE",
                    "displayName": "R***",
                    "opType": "T",
                    "images": [{"data": img_b64}],
                }]
            }
        }))
        result = await c.get_signatory_data("ACC_SBI_001", "sbi")
        assert len(result) == 1
        assert isinstance(result[0], CBSSignatoryData)
        assert result[0].signatory_id == "SIG-B01"
        assert b"bancs_jpeg" in result[0].specimen_images[0]

    @pytest.mark.asyncio
    async def test_network_failure_raises_cbs_unavailable(self):
        c = self._make_connector()
        c._http.post = AsyncMock(side_effect=ConnectionError("BaNCS timeout"))
        with pytest.raises(CBSUnavailableError):
            await c.get_signatory_data("ACC001", "sbi")

    @pytest.mark.asyncio
    async def test_empty_signatory_list_returns_empty(self):
        c = self._make_connector()
        c._http.post = AsyncMock(return_value=self._mock_response({
            "response": {"signatories": []}
        }))
        result = await c.get_signatory_data("ACC001", "sbi")
        assert result == []


# ─── FlexCube ───────────────────────────────────────────────────────────────

class TestFlexCubeGetSignatoryData:
    def _make_connector(self):
        from shared.cbs_connector.flexcube import FlexCubeCBSConnector
        c = FlexCubeCBSConnector(
            base_url="http://flexcube.internal/ws",
            bank_id="pnb",
        )
        c._soap_client = MagicMock()
        c._ready = True
        return c

    @pytest.mark.asyncio
    async def test_happy_path_returns_signatory_data(self):
        img_bytes = b"flexcube_tiff_image"
        c = self._make_connector()

        mock_response = MagicMock()
        mock_response.signatories = [MagicMock(
            signatoryId="SIG-F01",
            role="PARTNER",
            nameMasked="S***",
            operationType="P",
            specimenBlobs=[img_bytes],
        )]
        c._soap_client.service.getSignatories = MagicMock(return_value=mock_response)

        result = await c.get_signatory_data("ACC_PNB_001", "pnb")
        assert len(result) == 1
        assert isinstance(result[0], CBSSignatoryData)
        assert result[0].signatory_id == "SIG-F01"
        assert result[0].operation_type == "P"

    @pytest.mark.asyncio
    async def test_soap_fault_raises_cbs_unavailable(self):
        c = self._make_connector()
        c._soap_client.service.getSignatories = MagicMock(
            side_effect=Exception("SOAP Fault: Service unavailable")
        )
        with pytest.raises(CBSUnavailableError):
            await c.get_signatory_data("ACC001", "pnb")

    @pytest.mark.asyncio
    async def test_empty_blobs_handled_gracefully(self):
        c = self._make_connector()
        mock_response = MagicMock()
        mock_response.signatories = [MagicMock(
            signatoryId="SIG-F02",
            role="CFO",
            nameMasked="P***",
            operationType="J",
            specimenBlobs=[],
        )]
        c._soap_client.service.getSignatories = MagicMock(return_value=mock_response)
        result = await c.get_signatory_data("ACC001", "pnb")
        assert result[0].specimen_images == []
