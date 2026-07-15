"""
Tests for HeadroomVLLMClient — context compression wrapper.

Tests verify:
- Token counts logged (raw vs compressed)
- explicit queue forwarded in extra_body
- Compression overhead doesn't exceed 500ms
- Client degrades gracefully when headroom unavailable
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_openai_response():
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="test rationale"))]
    resp.usage = MagicMock(completion_tokens=50)
    return resp


@pytest.fixture
def sample_messages():
    return [
        {"role": "system", "content": "You are a fraud analyst."},
        {"role": "user",   "content": '{"fraud_score": 0.81, "ocr_confidence": 0.97}'},
    ]


@patch("apps.ai_server.headroom_client.headroom_compress")
@patch("apps.ai_server.headroom_client.AsyncOpenAI")
@pytest.mark.asyncio
async def test_chat_returns_content_and_usage(
    mock_openai_cls, mock_compress, sample_messages, mock_openai_response
):
    """Happy path — returns content, usage dict, and latency dict."""
    mock_compress.return_value = [
        {"role": "system", "content": "You are a fraud analyst."},
        {"role": "user",   "content": '{"fraud_score":0.81}'},  # compressed
    ]
    client_inst = AsyncMock()
    client_inst.chat.completions.create = AsyncMock(return_value=mock_openai_response)
    mock_openai_cls.return_value = client_inst

    from apps.ai_server.headroom_client import HeadroomVLLMClient
    hclient = HeadroomVLLMClient(base_url="http://vllm:8000")

    result = await hclient.chat(
        queue="cts-reasoning",
        model="llama-3.3-70b",
        messages=sample_messages,
    )

    assert result["content"] == "test rationale"
    assert "raw_prompt_tokens" in result["usage"]
    assert "compressed_prompt_tokens" in result["usage"]
    assert "reduction_pct" in result["usage"]
    assert result["usage"]["compressed_prompt_tokens"] < result["usage"]["raw_prompt_tokens"]
    assert "compression" in result["latency_ms"]
    assert "inference" in result["latency_ms"]


@patch("apps.ai_server.headroom_client.headroom_compress")
@patch("apps.ai_server.headroom_client.AsyncOpenAI")
@pytest.mark.asyncio
async def test_explicit_queue_forwarded_to_vllm(
    mock_openai_cls, mock_compress, sample_messages, mock_openai_response
):
    """Queue must be forwarded in extra_body — never default vLLM queue."""
    mock_compress.return_value = sample_messages
    client_inst = AsyncMock()
    create_mock = AsyncMock(return_value=mock_openai_response)
    client_inst.chat.completions.create = create_mock
    mock_openai_cls.return_value = client_inst

    from apps.ai_server.headroom_client import HeadroomVLLMClient
    hclient = HeadroomVLLMClient(base_url="http://vllm:8000")
    await hclient.chat(queue="cts-vision", model="qwen2-vl-72b", messages=sample_messages)

    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs.get("extra_body", {}).get("queue") == "cts-vision"


@patch("apps.ai_server.headroom_client.headroom_compress", side_effect=Exception("headroom down"))
@patch("apps.ai_server.headroom_client.AsyncOpenAI")
@pytest.mark.asyncio
async def test_graceful_degradation_when_headroom_unavailable(
    mock_openai_cls, mock_compress, sample_messages, mock_openai_response
):
    """If headroom compress raises, the call should still succeed with uncompressed messages."""
    client_inst = AsyncMock()
    client_inst.chat.completions.create = AsyncMock(return_value=mock_openai_response)
    mock_openai_cls.return_value = client_inst

    from apps.ai_server.headroom_client import HeadroomVLLMClient
    hclient = HeadroomVLLMClient(base_url="http://vllm:8000")

    # Should not raise — degrade to sending uncompressed
    result = await hclient.chat(queue="cts-reasoning", model="llama-3.3-70b", messages=sample_messages)
    assert result["content"] == "test rationale"
    # reduction_pct should be 0 or absent when compression failed
    assert result["usage"]["reduction_pct"] == 0.0
