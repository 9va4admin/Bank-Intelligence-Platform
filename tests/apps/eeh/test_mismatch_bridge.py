"""
Tests for apps/eeh/mismatch_bridge.py — MismatchKafkaBridge.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_bridge_constructs():
    from apps.eeh.mismatch_bridge import MismatchKafkaBridge
    redis = AsyncMock()
    bridge = MismatchKafkaBridge(redis=redis, bank_id="srcb")
    assert bridge._bank_id == "srcb"
    assert bridge._task is None


def test_bridge_with_sse_publisher():
    from apps.eeh.mismatch_bridge import MismatchKafkaBridge
    redis = AsyncMock()
    pub = MagicMock()
    bridge = MismatchKafkaBridge(redis=redis, bank_id="srcb", sse_publisher=pub)
    assert bridge._sse_publisher is pub


# ---------------------------------------------------------------------------
# _relay — branches on branch_id extraction
# ---------------------------------------------------------------------------

class TestRelay:
    @pytest.fixture()
    def bridge(self):
        from apps.eeh.mismatch_bridge import MismatchKafkaBridge
        redis = AsyncMock()
        pub = AsyncMock()
        return MismatchKafkaBridge(redis=redis, bank_id="srcb", sse_publisher=pub), pub

    def _msg(self, topic: str, value: dict):
        msg = MagicMock()
        msg.topic = topic
        msg.value = value
        msg.offset = 0
        return msg

    @pytest.mark.asyncio
    async def test_relay_uses_sse_publisher_when_available(self, bridge):
        b, pub = bridge
        msg = self._msg(
            topic="cts.mismatch.srcb.branch-001",
            value={
                "branch_id": "branch-001",
                "payload": {
                    "mismatch_id": "MM-001",
                    "branch_id": "branch-001",
                    "scan_id": "SCAN-001",
                    "instrument_id": "INS-001",
                    "scanner_amount": "50000.00",
                    "vision_amount": "51000.00",
                    "mismatch_fields": ["amount_figures"],
                    "payee_display": "R***",
                    "session_id": "SES-001",
                },
            },
        )
        await b._relay(msg)
        pub.publish_mismatch_hold.assert_awaited_once()
        call_kwargs = pub.publish_mismatch_hold.call_args.kwargs
        assert call_kwargs["branch_id"] == "branch-001"
        assert call_kwargs["item"]["mismatch_id"] == "MM-001"

    @pytest.mark.asyncio
    async def test_relay_extracts_branch_from_topic_when_not_in_payload(self, bridge):
        from apps.eeh.mismatch_bridge import MismatchKafkaBridge
        redis = AsyncMock()
        pub = AsyncMock()
        b = MismatchKafkaBridge(redis=redis, bank_id="srcb", sse_publisher=pub)

        msg = self._msg(
            topic="cts.mismatch.srcb.branch-xyz",
            value={"mismatch_id": "MM-002"},
        )
        await b._relay(msg)
        pub.publish_mismatch_hold.assert_awaited_once()
        call_kwargs = pub.publish_mismatch_hold.call_args.kwargs
        assert call_kwargs["branch_id"] == "branch-xyz"

    @pytest.mark.asyncio
    async def test_relay_fallback_to_redis_when_no_sse_publisher(self):
        from apps.eeh.mismatch_bridge import MismatchKafkaBridge
        redis = AsyncMock()
        b = MismatchKafkaBridge(redis=redis, bank_id="srcb", sse_publisher=None)

        msg = self._msg(
            topic="cts.mismatch.srcb.branch-001",
            value={"branch_id": "branch-001", "mismatch_id": "MM-003"},
        )
        await b._relay(msg)
        redis.publish.assert_awaited_once()
        channel_arg = redis.publish.call_args[0][0]
        assert "branch-001" in channel_arg

    @pytest.mark.asyncio
    async def test_relay_skips_message_with_no_branch_id(self, bridge):
        b, pub = bridge
        msg = self._msg(
            topic="cts.mismatch",  # too short — can't extract branch_id
            value={"mismatch_id": "MM-999"},
        )
        await b._relay(msg)
        pub.publish_mismatch_hold.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_relay_handles_exception_gracefully(self, bridge):
        b, pub = bridge
        pub.publish_mismatch_hold.side_effect = RuntimeError("redis down")
        msg = self._msg(
            topic="cts.mismatch.srcb.branch-001",
            value={"branch_id": "branch-001"},
        )
        # Must not propagate — per-message failure is isolated
        await b._relay(msg)


# ---------------------------------------------------------------------------
# stop() — graceful shutdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_before_start_is_safe():
    from apps.eeh.mismatch_bridge import MismatchKafkaBridge
    bridge = MismatchKafkaBridge(redis=AsyncMock(), bank_id="srcb")
    # Should not raise even if start() was never called
    await bridge.stop()


@pytest.mark.asyncio
async def test_stop_sets_event():
    from apps.eeh.mismatch_bridge import MismatchKafkaBridge
    bridge = MismatchKafkaBridge(redis=AsyncMock(), bank_id="srcb")
    assert not bridge._stop_event.is_set()
    await bridge.stop()
    assert bridge._stop_event.is_set()


# ---------------------------------------------------------------------------
# _run — degrades gracefully when aiokafka not installed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_degrades_without_aiokafka():
    from apps.eeh.mismatch_bridge import MismatchKafkaBridge
    bridge = MismatchKafkaBridge(redis=AsyncMock(), bank_id="srcb")
    # Simulate aiokafka not installed
    with patch.dict("sys.modules", {"aiokafka": None, "aiokafka.errors": None}):
        # _run should return without raising
        await bridge._run()
