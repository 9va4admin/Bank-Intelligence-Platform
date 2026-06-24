"""
Tests for modules/cts/mcp/ngch_adapter.py

NGCHAdapter wraps NGCH's SFTP/API interface and exposes it as MCP tools
callable by CTS agents. NGCH = National Grid Cheque Hub (clearing grid).

Critical: No direct NGCH call is ever made outside this adapter.
Exactly-once semantics enforced by idempotency_key on every submission.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(bank_id="test-bank", http_client=None):
    from modules.cts.mcp.ngch_adapter import NGCHAdapter
    adapter = NGCHAdapter(bank_id=bank_id, base_url="https://ngch.internal/api")
    adapter._http = http_client or AsyncMock()
    adapter._ready = True
    return adapter


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestNGCHAdapterInit:
    def test_not_ready_before_connect(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        assert adapter._ready is False

    def test_connect_sets_ready(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        adapter.connect(http_client=AsyncMock())
        assert adapter._ready is True

    @pytest.mark.asyncio
    async def test_requires_connect_before_file_decision(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        with pytest.raises(RuntimeError, match="connect"):
            await adapter.file_decision("INST001", "CONFIRM", "wf-001")

    @pytest.mark.asyncio
    async def test_requires_connect_before_query_status(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        with pytest.raises(RuntimeError, match="connect"):
            await adapter.query_status("INST001")


# ---------------------------------------------------------------------------
# file_decision — the primary tool
# ---------------------------------------------------------------------------

class TestFileDecision:
    @pytest.mark.asyncio
    async def test_file_decision_posts_to_correct_url(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK123", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        await adapter.file_decision("INST001", "CONFIRM", "wf-001")
        call_url = mock_http.post.call_args[0][0]
        assert "/decisions" in call_url

    @pytest.mark.asyncio
    async def test_file_decision_includes_instrument_id(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK123", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        await adapter.file_decision("INST001", "CONFIRM", "wf-001")
        payload = mock_http.post.call_args[1].get("json") or mock_http.post.call_args[0][1]
        assert payload["instrument_id"] == "INST001"

    @pytest.mark.asyncio
    async def test_file_decision_includes_decision(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK123", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        await adapter.file_decision("INST001", "RETURN", "wf-001")
        payload = mock_http.post.call_args[1].get("json") or mock_http.post.call_args[0][1]
        assert payload["decision"] == "RETURN"

    @pytest.mark.asyncio
    async def test_file_decision_includes_idempotency_key(self):
        """Exactly-once: idempotency key is derived from workflow_id."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK123", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        await adapter.file_decision("INST001", "CONFIRM", "cts-bank-INST001")
        payload = mock_http.post.call_args[1].get("json") or mock_http.post.call_args[0][1]
        assert "idempotency_key" in payload
        assert payload["idempotency_key"] == "cts-bank-INST001"

    @pytest.mark.asyncio
    async def test_file_decision_includes_bank_id(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK123", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(bank_id="kotak", http_client=mock_http)

        await adapter.file_decision("INST001", "CONFIRM", "wf-001")
        payload = mock_http.post.call_args[1].get("json") or mock_http.post.call_args[0][1]
        assert payload["bank_id"] == "kotak"

    @pytest.mark.asyncio
    async def test_file_decision_returns_acknowledgement(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"acknowledgement_id": "ACK999", "status": "ACCEPTED"})
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        result = await adapter.file_decision("INST001", "CONFIRM", "wf-001")
        assert result["acknowledgement_id"] == "ACK999"

    @pytest.mark.asyncio
    async def test_file_decision_raises_on_http_error(self):
        from modules.cts.mcp.ngch_adapter import NGCHUnavailableError
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=Exception("503 Service Unavailable"))
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        with pytest.raises(NGCHUnavailableError):
            await adapter.file_decision("INST001", "CONFIRM", "wf-001")

    @pytest.mark.asyncio
    async def test_file_decision_raises_on_connection_error(self):
        from modules.cts.mcp.ngch_adapter import NGCHUnavailableError
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("NGCH unreachable"))
        adapter = _make_adapter(http_client=mock_http)

        with pytest.raises(NGCHUnavailableError):
            await adapter.file_decision("INST001", "CONFIRM", "wf-001")

    @pytest.mark.asyncio
    async def test_file_decision_raises_on_duplicate(self):
        """409 Conflict = duplicate filing attempt."""
        from modules.cts.mcp.ngch_adapter import DuplicateFilingError
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        with pytest.raises(DuplicateFilingError):
            await adapter.file_decision("INST001", "CONFIRM", "wf-001")

    @pytest.mark.asyncio
    async def test_file_decision_only_accepts_valid_decisions(self):
        """NGCH only accepts CONFIRM or RETURN — reject others at adapter layer."""
        adapter = _make_adapter()
        with pytest.raises(ValueError, match="decision"):
            await adapter.file_decision("INST001", "AUTO_APPROVE", "wf-001")


# ---------------------------------------------------------------------------
# query_status
# ---------------------------------------------------------------------------

class TestQueryStatus:
    @pytest.mark.asyncio
    async def test_query_status_calls_correct_url(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"status": "ACCEPTED", "instrument_id": "INST001"})
        mock_http.get = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        await adapter.query_status("INST001")
        call_url = mock_http.get.call_args[0][0]
        assert "INST001" in call_url

    @pytest.mark.asyncio
    async def test_query_status_returns_status(self):
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"status": "ACCEPTED", "instrument_id": "INST001"})
        mock_http.get = AsyncMock(return_value=mock_response)
        adapter = _make_adapter(http_client=mock_http)

        result = await adapter.query_status("INST001")
        assert result["status"] == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_query_status_raises_on_failure(self):
        from modules.cts.mcp.ngch_adapter import NGCHUnavailableError
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=Exception("connection lost"))
        adapter = _make_adapter(http_client=mock_http)

        with pytest.raises(NGCHUnavailableError):
            await adapter.query_status("INST001")


# ---------------------------------------------------------------------------
# MCP tool list
# ---------------------------------------------------------------------------

class TestMCPTools:
    def test_list_tools_returns_expected_tool_names(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert "file_decision" in tool_names
        assert "query_status" in tool_names

    def test_each_tool_has_description(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        for tool in adapter.list_tools():
            assert "description" in tool
            assert tool["description"]

    def test_each_tool_has_input_schema(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="b", base_url="https://ngch.internal/api")
        for tool in adapter.list_tools():
            assert "inputSchema" in tool


class TestNGCHAdapterConnectFallback:
    def test_connect_without_http_client_imports_httpx(self, monkeypatch):
        """Covers lines 34-35: connect() with no http_client → imports httpx, creates AsyncClient."""
        import sys
        from unittest.mock import MagicMock
        from modules.cts.mcp.ngch_adapter import NGCHAdapter

        fake_httpx = MagicMock()
        fake_client = MagicMock()
        fake_httpx.AsyncClient.return_value = fake_client
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

        adapter = NGCHAdapter(bank_id="test-bank", base_url="https://ngch.internal/api")
        adapter.connect()

        assert adapter._ready is True
        fake_httpx.AsyncClient.assert_called_once_with(timeout=30.0)
        assert adapter._http is fake_client
