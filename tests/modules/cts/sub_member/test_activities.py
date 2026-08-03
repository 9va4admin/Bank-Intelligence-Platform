"""Tests for Sub-Member Temporal activities."""
import pytest
from unittest.mock import AsyncMock

from modules.cts.sub_member.activities import (
    notify_sub_member_return,
    emit_batch_ledger_update,
    check_return_rate_shield,
)


class TestNotifySubMemberReturn:
    @pytest.mark.asyncio
    async def test_returns_dict_with_notification_id(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="7890",
        )
        assert "notification_id" in result
        assert result["notification_id"].startswith("SMB-NOTIF-")

    @pytest.mark.asyncio
    async def test_tier_is_tier1_immediate(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="FUNDS_INSUFFICIENT",
            bucket="STP_RETURN",
            amount_range="₹[<1L]",
            cheque_number_suffix="1234",
        )
        assert result["tier"] == "TIER1_IMMEDIATE"

    @pytest.mark.asyncio
    async def test_template_is_return_immediate(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="DATE_MISSING",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="5678",
        )
        assert result["template"] == "RETURN_IMMEDIATE"

    @pytest.mark.asyncio
    async def test_status_is_queued(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="0001",
        )
        assert result["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_rejects_cheque_suffix_over_4_chars(self):
        with pytest.raises(ValueError, match="PII rule"):
            await notify_sub_member_return(
                instrument_id="CHQ-001",
                bank_id="BANK-001",
                sub_member_id="SMB-001",
                return_reason="SIGNATURE_MISMATCH",
                bucket="STP_RETURN",
                amount_range="₹[1L-5L]",
                cheque_number_suffix="12345",  # 5 chars — invalid
            )

    @pytest.mark.asyncio
    async def test_amount_range_preserved_in_result(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[5L-10L]",
            cheque_number_suffix="9999",
        )
        assert result["amount_range"] == "₹[5L-10L]"

    @pytest.mark.asyncio
    async def test_result_includes_bank_and_sub_member(self):
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-XYZ",
            sub_member_id="SMB-ABC",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="0001",
        )
        assert result["bank_id"] == "BANK-XYZ"
        assert result["sub_member_id"] == "SMB-ABC"

    @pytest.mark.asyncio
    async def test_publishes_via_injected_event_producer(self):
        mock_producer = AsyncMock()
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="7890",
            event_producer=mock_producer,
        )
        mock_producer.publish.assert_awaited_once()
        call_kwargs = mock_producer.publish.call_args.kwargs
        assert call_kwargs["topic"] == "cts.sub_member.return_notification"
        assert call_kwargs["payload"]["notification_id"] == result["notification_id"]
        assert result["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_degrades_when_publish_fails(self):
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock(side_effect=Exception("Kafka unreachable"))
        result = await notify_sub_member_return(
            instrument_id="CHQ-001",
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket="STP_RETURN",
            amount_range="₹[1L-5L]",
            cheque_number_suffix="7890",
            event_producer=mock_producer,
        )
        assert result["status"] == "PUBLISH_DEGRADED"
        assert result["notification_id"]  # still constructed


class TestEmitBatchLedgerUpdate:
    @pytest.mark.asyncio
    async def test_returns_ledger_updated_status(self):
        result = await emit_batch_ledger_update(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
            bucket="STP_RETURN",
        )
        assert result["status"] == "LEDGER_UPDATED"

    @pytest.mark.asyncio
    async def test_bucket_incremented_echoed_back(self):
        result = await emit_batch_ledger_update(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
            bucket="STP_PASS",
        )
        assert result["bucket_incremented"] == "STP_PASS"

    @pytest.mark.asyncio
    async def test_rejects_invalid_bucket(self):
        with pytest.raises(ValueError, match="Invalid bucket"):
            await emit_batch_ledger_update(
                bank_id="BANK-001",
                sub_member_id="SMB-001",
                session_date="2026-06-19",
                clearing_session="MORNING",
                bucket="UNKNOWN_BUCKET",
            )

    @pytest.mark.asyncio
    async def test_all_valid_buckets_accepted(self):
        valid = ["STP_PASS", "STP_RETURN", "EYEBALL", "FRAUD_HOLD", "IET_EMERGENCY"]
        for bucket in valid:
            result = await emit_batch_ledger_update(
                bank_id="BANK-001",
                sub_member_id="SMB-001",
                session_date="2026-06-19",
                clearing_session="MORNING",
                bucket=bucket,
            )
            assert result["bucket_incremented"] == bucket

    @pytest.mark.asyncio
    async def test_result_includes_updated_at(self):
        result = await emit_batch_ledger_update(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
            bucket="STP_RETURN",
        )
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_upserts_via_injected_db(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=None)
        result = await emit_batch_ledger_update(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
            bucket="STP_PASS",
            db=mock_db,
        )
        mock_db.execute.assert_awaited_once()
        sql, *params = mock_db.execute.call_args.args
        assert "stp_pass" in sql  # bucket-column allowlist resolved correctly
        assert params[0] == "BANK-001"
        assert result["status"] == "LEDGER_UPDATED"

    @pytest.mark.asyncio
    async def test_degrades_when_db_upsert_fails(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB unreachable"))
        result = await emit_batch_ledger_update(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
            bucket="STP_PASS",
            db=mock_db,
        )
        assert result["status"] == "LEDGER_UPDATE_DEGRADED"


class TestCheckReturnRateShield:
    @pytest.mark.asyncio
    async def test_returns_shield_status(self):
        result = await check_return_rate_shield(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        assert "shield_status" in result
        assert result["shield_status"] in ("SAFE", "SOFT_HOLD", "HARD_STOP")

    @pytest.mark.asyncio
    async def test_stub_returns_safe(self):
        result = await check_return_rate_shield(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        assert result["shield_status"] == "SAFE"

    @pytest.mark.asyncio
    async def test_action_required_false_when_safe(self):
        result = await check_return_rate_shield(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        assert result["action_required"] is False

    @pytest.mark.asyncio
    async def test_result_includes_checked_at(self):
        result = await check_return_rate_shield(
            bank_id="BANK-001",
            sub_member_id="SMB-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_result_echoes_input_ids(self):
        result = await check_return_rate_shield(
            bank_id="BANK-XYZ",
            sub_member_id="SMB-ABC",
            session_date="2026-06-19",
            clearing_session="AFTERNOON",
        )
        assert result["bank_id"] == "BANK-XYZ"
        assert result["sub_member_id"] == "SMB-ABC"
        assert result["clearing_session"] == "AFTERNOON"
