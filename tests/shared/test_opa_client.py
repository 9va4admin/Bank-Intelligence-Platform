"""
Tests for shared/opa_client.py

OPA client — evaluates Layer 4 business policy rules via OPA decision API.
Used by decision.py to enforce bank-configurable Rego policies without code deploys.

Policy: infra/opa/policies/cts_routing.rego
Endpoint: POST /v1/data/astra/cts/routing
Input:  { "instrument_id", "bank_id", "cheque_type", "amount", "account_status",
          "is_first_clearing_day", "has_government_flag", "has_court_order_flag" }
Output: { "result": { "decision": "HUMAN_REVIEW" | "AUTO_RETURN" | "PROCEED",
                      "reason": "..." } }

OPA unavailable → safe default: return PROCEED (let existing gates handle it).
Never raises.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_input(
    instrument_id="INST001",
    bank_id="test-bank",
    cheque_type="STANDARD",
    amount=50000.0,
    account_status="ACTIVE",
    is_first_clearing_day=False,
    has_government_flag=False,
    has_court_order_flag=False,
):
    from shared.opa_client import OPAInput
    return OPAInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        cheque_type=cheque_type,
        amount=amount,
        account_status=account_status,
        is_first_clearing_day=is_first_clearing_day,
        has_government_flag=has_government_flag,
        has_court_order_flag=has_court_order_flag,
    )


class TestOPAInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.bank_id = "changed"

    def test_input_requires_instrument_id(self):
        from shared.opa_client import OPAInput
        with pytest.raises(Exception):
            OPAInput(bank_id="b", cheque_type="S", amount=1.0,
                     account_status="ACTIVE", is_first_clearing_day=False,
                     has_government_flag=False, has_court_order_flag=False)


class TestOPAResult:
    def test_result_is_frozen(self):
        from shared.opa_client import OPAResult
        r = OPAResult(decision="PROCEED", reason="all clear")
        with pytest.raises(Exception):
            r.decision = "changed"

    def test_result_valid_decisions(self):
        from shared.opa_client import OPAResult
        for d in ("PROCEED", "HUMAN_REVIEW", "AUTO_RETURN"):
            r = OPAResult(decision=d, reason="test")
            assert r.decision == d


class TestOPAClientDecide:
    @pytest.mark.asyncio
    async def test_government_cheque_returns_human_review(self):
        """OPA policy: government cheques always → HUMAN_REVIEW regardless of scores."""
        from shared.opa_client import OPAClient

        mock_response = {"result": {"decision": "HUMAN_REVIEW", "reason": "government_cheque"}}
        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input(has_government_flag=True))

        assert result.decision == "HUMAN_REVIEW"
        assert "government" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_court_order_returns_human_review(self):
        """OPA policy: court-order cheques always → HUMAN_REVIEW."""
        from shared.opa_client import OPAClient

        mock_response = {"result": {"decision": "HUMAN_REVIEW", "reason": "court_order"}}
        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input(has_court_order_flag=True))

        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_standard_cheque_returns_proceed(self):
        """Standard cheque with no policy triggers → PROCEED."""
        from shared.opa_client import OPAClient

        mock_response = {"result": {"decision": "PROCEED", "reason": "no_policy_match"}}
        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input())

        assert result.decision == "PROCEED"

    @pytest.mark.asyncio
    async def test_high_value_first_clearing_day_human_review(self):
        """OPA policy: very high-value cheque on first clearing day → HUMAN_REVIEW."""
        from shared.opa_client import OPAClient

        mock_response = {"result": {"decision": "HUMAN_REVIEW", "reason": "high_value_first_day"}}
        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input(amount=6000000, is_first_clearing_day=True))

        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_opa_unavailable_returns_proceed_safe_default(self):
        """OPA down → safe default PROCEED (existing decision gates still apply)."""
        from shared.opa_client import OPAClient

        http = AsyncMock()
        http.post.side_effect = Exception("Connection refused")
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input())

        assert result.decision == "PROCEED"
        assert "unavailable" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_opa_http_error_returns_proceed(self):
        """OPA returns 500 → safe default PROCEED."""
        from shared.opa_client import OPAClient

        http = AsyncMock()
        http.post.return_value = MagicMock(status_code=500, json=lambda: {})
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        result = await client.decide(_make_input())

        assert result.decision == "PROCEED"

    @pytest.mark.asyncio
    async def test_decide_never_raises(self):
        """OPA client must never propagate exceptions to callers."""
        from shared.opa_client import OPAClient

        http = AsyncMock()
        http.post.side_effect = RuntimeError("Unexpected crash")
        client = OPAClient(opa_url="http://opa:8181", http_client=http)

        result = await client.decide(_make_input())
        assert result is not None

    @pytest.mark.asyncio
    async def test_opa_request_includes_bank_id(self):
        """OPA request must include bank_id for multi-tenant policy evaluation."""
        from shared.opa_client import OPAClient

        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": {"decision": "PROCEED", "reason": "ok"}},
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        await client.decide(_make_input(bank_id="kotak-mah"))

        call_kwargs = http.post.call_args
        # Request body must contain bank_id
        body = call_kwargs[1].get("json", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert "kotak-mah" in str(body)

    @pytest.mark.asyncio
    async def test_opa_path_is_cts_routing(self):
        """OPA must be queried at the CTS routing policy path."""
        from shared.opa_client import OPAClient

        http = AsyncMock()
        http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": {"decision": "PROCEED", "reason": "ok"}},
        )
        client = OPAClient(opa_url="http://opa:8181", http_client=http)
        await client.decide(_make_input())

        call_args = http.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "cts" in url.lower() or "routing" in url.lower()
