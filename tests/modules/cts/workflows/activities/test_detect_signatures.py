"""
TDD tests for modules/cts/workflows/activities/detect_signatures.py

RED phase — all tests must FAIL before implementation exists.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vllm_response(sig_count: int, bboxes: list, fraud_flags: list):
    """Build a minimal mock vLLM response with the expected JSON payload."""
    content = json.dumps({
        "signature_count": sig_count,
        "signature_bboxes": bboxes,
        "signature_fraud_flags": fraud_flags,
    })
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_input(instrument_id="INS-001", bank_id="test-bank", image_url="minio://bucket/chq.png"):
    from modules.cts.workflows.activities.detect_signatures import DetectSignaturesInput
    return DetectSignaturesInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        image_url=image_url,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectSignaturesPresent:
    @pytest.mark.asyncio
    async def test_single_signature_returns_present(self):
        """One signature detected → outcome=PRESENT, sig_count=1."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.95, 0.9]], [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "PRESENT"
        assert result.sig_count == 1
        assert result.sig_bboxes == [[0.6, 0.7, 0.95, 0.9]]
        assert result.fraud_flags == []
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_two_signatures_returns_present_count_two(self):
        """Two signatures → outcome=PRESENT, sig_count=2."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(2, [[0.1, 0.7, 0.4, 0.9], [0.6, 0.7, 0.9, 0.9]], [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "PRESENT"
        assert result.sig_count == 2

    @pytest.mark.asyncio
    async def test_zero_signatures_returns_absent(self):
        """No signature detected → outcome=ABSENT, sig_count=0."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(0, [], [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "ABSENT"
        assert result.sig_count == 0
        assert result.sig_bboxes == []
        assert result.degraded is False


class TestDetectSignaturesFraudFlags:
    @pytest.mark.asyncio
    async def test_fraud_flags_returned(self):
        """Fraud flags from LLM are forwarded on the result."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.95, 0.9]], ["OVERWRITTEN", "SMUDGED"])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert "OVERWRITTEN" in result.fraud_flags
        assert "SMUDGED" in result.fraud_flags

    @pytest.mark.asyncio
    async def test_fraud_flags_with_present_outcome(self):
        """Fraud flags do NOT change outcome to ABSENT — caller decides routing."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.95, 0.9]], ["FAINT_INK"])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "PRESENT"
        assert "FAINT_INK" in result.fraud_flags

    @pytest.mark.asyncio
    async def test_unknown_fraud_flags_passed_through(self):
        """Unrecognised flag strings from the LLM are forwarded without filtering."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.9, 0.9]], ["SOME_NEW_FLAG"])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert "SOME_NEW_FLAG" in result.fraud_flags


class TestDetectSignaturesDegradation:
    @pytest.mark.asyncio
    async def test_vllm_unavailable_returns_degraded(self):
        """vLLM down → outcome=DEGRADED, degraded=True, sig_count=0."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=Exception("vLLM timeout"))

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "DEGRADED"
        assert result.degraded is True
        assert result.sig_count == 0
        assert result.sig_bboxes == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_degraded(self):
        """LLM returns non-JSON → outcome=DEGRADED, degraded=True."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        msg = MagicMock()
        msg.content = "Sorry, I cannot process this image."
        choice = MagicMock()
        choice.message = msg
        response = MagicMock()
        response.choices = [choice]

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_no_vllm_client_returns_degraded(self):
        """No vllm_client injected → graceful degradation, never raises."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        result = await detect_signatures(_make_input(), vllm_client=None)

        assert result.outcome == "DEGRADED"
        assert result.degraded is True


class TestDetectSignaturesVllmCall:
    @pytest.mark.asyncio
    async def test_correct_queue_in_extra_body(self):
        """vLLM call must include explicit queue in extra_body — ai-inference.md rule."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.9, 0.9]], [])
        )

        await detect_signatures(_make_input(), vllm_client=client)

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert "queue" in call_kwargs["extra_body"]
        assert call_kwargs["extra_body"]["queue"] == "cts-vision-l1"

    @pytest.mark.asyncio
    async def test_explicit_timeout_set(self):
        """Timeout must be set explicitly — never rely on SDK default."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, [[0.6, 0.7, 0.9, 0.9]], [])
        )

        await detect_signatures(_make_input(), vllm_client=client)

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] > 0


class TestDetectSignaturesBboxes:
    @pytest.mark.asyncio
    async def test_bboxes_returned_in_result(self):
        """sig_bboxes in result matches the vLLM-returned coordinates."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        bboxes = [[0.6, 0.7, 0.95, 0.9]]
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, bboxes, [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.sig_bboxes == bboxes

    @pytest.mark.asyncio
    async def test_multiple_bboxes_returned(self):
        """Two signatures → two bbox entries in result."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        bboxes = [[0.1, 0.7, 0.4, 0.9], [0.6, 0.7, 0.9, 0.9]]
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(2, bboxes, [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert len(result.sig_bboxes) == 2
        assert result.sig_bboxes == bboxes

    @pytest.mark.asyncio
    async def test_malformed_bbox_entries_skipped(self):
        """Bbox entries that aren't 4-element lists are silently dropped."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        bboxes = [[0.6, 0.7, 0.95, 0.9], [0.1, 0.2], "bad"]   # 2 malformed
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(1, bboxes, [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.sig_bboxes == [[0.6, 0.7, 0.95, 0.9]]

    @pytest.mark.asyncio
    async def test_bboxes_empty_on_no_signature(self):
        """No signatures → sig_bboxes is empty list."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_vllm_response(0, [], [])
        )

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.sig_bboxes == []

    @pytest.mark.asyncio
    async def test_bboxes_empty_on_degraded(self):
        """vLLM failure → sig_bboxes is empty list, no partial data."""
        from modules.cts.workflows.activities.detect_signatures import detect_signatures

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

        result = await detect_signatures(_make_input(), vllm_client=client)

        assert result.sig_bboxes == []
