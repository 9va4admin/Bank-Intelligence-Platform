"""TDD — Outward payee name check activity.

Validates the scenario: depositor presents a cheque made out to
"श्रीमती लता देशपांडे" → system checks if the depositor's name
(from their CBS account) is a match.

Also covers kiosk input and deposit-slip OCR in regional scripts.
"""
import pytest
from unittest.mock import AsyncMock, patch
from modules.cts.workflows.activities.outward_payee_check import (
    OutwardPayeeCheckInput,
    OutwardPayeeCheckResult,
    check_outward_payee,
)


class TestOutwardPayeeCheckInput:
    def test_construction(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="श्रीमती लता देशपांडे",
            cbs_account_holder_name="Lata Deshpande",
            script="devanagari",
            source="deposit_slip",
            instrument_id="INS-001",
            bank_id="saraswat",
        )
        assert inp.instrument_id == "INS-001"

    def test_source_values(self):
        for src in ("deposit_slip", "kiosk", "cheque_reverse"):
            inp = OutwardPayeeCheckInput(
                ocr_payee_name="Name",
                cbs_account_holder_name="Name",
                script=None,
                source=src,
                instrument_id="INS-001",
                bank_id="bank",
            )
            assert inp.source == src


class TestOutwardPayeeCheckActivity:
    @pytest.mark.asyncio
    async def test_hindi_name_matches_english(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="श्रीमती लता देशपांडे",
            cbs_account_holder_name="Lata Deshpande",
            script="devanagari",
            source="deposit_slip",
            instrument_id="INS-001",
            bank_id="saraswat",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.82,
            })
            result = await check_outward_payee(inp)

        assert result.decision in {"MATCH", "FUZZY"}
        assert result.instrument_id == "INS-001"

    @pytest.mark.asyncio
    async def test_exact_english_match(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="Sunita Sharma",
            cbs_account_holder_name="Sunita Sharma",
            script=None,
            source="kiosk",
            instrument_id="INS-002",
            bank_id="saraswat",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.82,
            })
            result = await check_outward_payee(inp)

        assert result.decision == "MATCH"

    @pytest.mark.asyncio
    async def test_mismatch_detected(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="Ramesh Kumar Sharma",
            cbs_account_holder_name="Sunita Patel",
            script=None,
            source="deposit_slip",
            instrument_id="INS-003",
            bank_id="saraswat",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.82,
            })
            result = await check_outward_payee(inp)

        assert result.decision == "MISMATCH"

    @pytest.mark.asyncio
    async def test_tamil_payee_from_deposit_slip(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="ரமேஷ் குமார்",
            cbs_account_holder_name="Ramesh Kumar",
            script="tamil",
            source="deposit_slip",
            instrument_id="INS-004",
            bank_id="federal-bank",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.75,
            })
            result = await check_outward_payee(inp)

        assert result.decision in {"MATCH", "FUZZY"}

    @pytest.mark.asyncio
    async def test_result_has_score(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="Lata Deshpande",
            cbs_account_holder_name="Lata Deshpande",
            script=None,
            source="kiosk",
            instrument_id="INS-005",
            bank_id="saraswat",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.82,
            })
            result = await check_outward_payee(inp)

        assert result.score is not None
        assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_result_type(self):
        inp = OutwardPayeeCheckInput(
            ocr_payee_name="Test Name",
            cbs_account_holder_name="Test Name",
            script=None,
            source="kiosk",
            instrument_id="INS-006",
            bank_id="bank",
        )
        with patch(
            "modules.cts.workflows.activities.outward_payee_check.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value={
                "payee_match_threshold": 0.82,
            })
            result = await check_outward_payee(inp)

        assert isinstance(result, OutwardPayeeCheckResult)
