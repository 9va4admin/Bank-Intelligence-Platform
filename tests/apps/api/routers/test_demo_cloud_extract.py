"""
Tests for apps/api/routers/demo_cloud_extract.py — Cloud AI cheque extraction.

This endpoint is a deliberate, temporary exception to the platform's
zero-cloud-LLM rule (see the router's own module docstring) — these tests
verify it still behaves like every other route in the app on the things
that must never be relaxed: real auth required, real error handling,
Vault-backed credentials, never a raw crash on a bad upstream response.
"""
import io
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from unittest.mock import AsyncMock, MagicMock, patch

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


def _make_app():
    from apps.api.routers.demo_cloud_extract import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _authed_client():
    from apps.api.dependencies import require_user_context
    app = _make_app()
    app.dependency_overrides[require_user_context] = lambda: UserContext(
        user_id="u1", role=Role.OPS_REVIEWER, bank_id="test-bank",
        bank_type=BankType.SB, permission_level=PermissionLevel.EDIT,
    )
    return TestClient(app, raise_server_exceptions=False)


def _real_image_bytes(fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format=fmt)
    return buffer.getvalue()


def _fake_image_file():
    # Real, decodable PNG bytes -- both endpoints run every upload through
    # Pillow now (see _convert_to_png_bytes), so fixtures must be genuine
    # image data, not placeholder text, or every test would 422 before
    # ever reaching the (mocked) Hugging Face call.
    return {"file": ("cheque.png", io.BytesIO(_real_image_bytes("PNG")), "image/png")}


def _fake_tiff_file():
    return {"file": ("cheque.tif", io.BytesIO(_real_image_bytes("TIFF")), "image/tiff")}


def _fake_unreadable_file():
    return {"file": ("cheque.png", io.BytesIO(b"not-an-image-at-all"), "image/png")}


def _mock_hf_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


class TestAuth:
    def test_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())
        assert response.status_code == 401


class TestUnknownModel:
    def test_unknown_model_returns_422(self):
        client = _authed_client()
        response = client.post(
            "/v1/cts/demo/cloud-extract",
            files=_fake_image_file(),
            params={"model": "not-a-real-model"},
        )
        assert response.status_code == 422


class TestHfTokenUnavailable:
    def test_returns_503_when_vault_and_env_both_unavailable(self, monkeypatch):
        monkeypatch.delenv("ASTRA_DEMO_HF_TOKEN", raising=False)
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(side_effect=Exception("Vault unreachable")),
        ):
            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())
        assert response.status_code == 503


class TestHfTokenEnvFallback:
    def test_falls_back_to_env_var_when_vault_unavailable(self, monkeypatch):
        """Vault isn't running in bare local dev (see dev_auth_server.py) --
        ASTRA_DEMO_HF_TOKEN lets the demo work anyway. Real Vault is always
        tried first; this fallback only fires when Vault genuinely fails."""
        monkeypatch.setenv("ASTRA_DEMO_HF_TOKEN", "hf_env_fallback_token")
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(side_effect=Exception("Vault unreachable")),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(
                return_value=_mock_hf_response(json.dumps({"bank_name": "Env Fallback Bank"}))
            )
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        assert response.status_code == 200
        assert response.json()["bank_name"] == "Env Fallback Bank"
        # Confirm the fallback token was actually the one used.
        mock_openai_cls.assert_called_once_with(base_url="https://router.huggingface.co/v1", api_key="hf_env_fallback_token")

    def test_vault_token_preferred_over_env_when_both_available(self, monkeypatch):
        monkeypatch.setenv("ASTRA_DEMO_HF_TOKEN", "hf_env_fallback_token")
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_vault_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(
                return_value=_mock_hf_response(json.dumps({"bank_name": "X"}))
            )
            mock_openai_cls.return_value = client_inst

            client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        mock_openai_cls.assert_called_once_with(base_url="https://router.huggingface.co/v1", api_key="hf_vault_token")


class TestHappyPath:
    def test_returns_parsed_extraction(self):
        client = _authed_client()
        extraction = {
            "bank_name": "State Bank of India",
            "date": "01/07/2026",
            "payee_name": "M/s Sunshine Traders",
            "amount_words": "Ten Thousand Only",
            "amount_numeric": "10000",
            "is_amount_matching": True,
            "account_number": "00123456789",
            "ifsc_code": "SBIN0001234",
            "cheque_number": "000001",
            "micr_code": "400002001",
            "signature_present": True,
            "signature_name": "RAJESH KUMAR",
        }
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(
                return_value=_mock_hf_response(json.dumps(extraction))
            )
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        assert response.status_code == 200
        body = response.json()
        assert body["bank_name"] == "State Bank of India"
        assert body["is_amount_matching"] is True
        assert body["model_used"] == "qwen-72b"
        assert body["error"] is None

    def test_selected_model_forwarded_to_hf(self):
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            create_mock = AsyncMock(return_value=_mock_hf_response(json.dumps({"bank_name": "X"})))
            client_inst.chat.completions.create = create_mock
            mock_openai_cls.return_value = client_inst

            response = client.post(
                "/v1/cts/demo/cloud-extract",
                files=_fake_image_file(),
                params={"model": "gemma-27b"},
            )

        assert response.status_code == 200
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["model"] == "google/gemma-3-27b-it:featherless-ai"

    def test_strips_markdown_json_fence(self):
        client = _authed_client()
        fenced = "```json\n" + json.dumps({"bank_name": "Fenced Bank"}) + "\n```"
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(return_value=_mock_hf_response(fenced))
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        assert response.status_code == 200
        assert response.json()["bank_name"] == "Fenced Bank"


class TestHfCallFailure:
    def test_returns_502_when_hf_unreachable(self):
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(side_effect=Exception("HF down"))
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        assert response.status_code == 502

    def test_provider_rejection_surfaces_real_reason(self):
        """Regression: a model whose inference provider the account isn't
        authorized for (e.g. Qwen 72B routes through ovhcloud; a token valid
        for featherless-ai can still be rejected there) must not collapse
        into a generic 'unreachable' message -- the real HF rejection reason
        is exactly what a user needs to self-diagnose this."""
        import httpx
        import openai

        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            resp = httpx.Response(
                400, request=httpx.Request("POST", "https://router.huggingface.co/v1"),
                json={"error": "Not allowed to POST /ovhcloud/v1/chat/completions for provider ovhcloud"},
            )
            api_error = openai.APIStatusError(
                "Error code: 400 - {'error': 'Not allowed to POST /ovhcloud/v1/chat/completions for provider ovhcloud'}",
                response=resp, body=None,
            )
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(side_effect=api_error)
            mock_openai_cls.return_value = client_inst

            response = client.post(
                "/v1/cts/demo/cloud-extract", files=_fake_image_file(), params={"model": "qwen-72b"},
            )

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "qwen-72b" in detail
        assert "ovhcloud" in detail


class TestInvalidJsonResponse:
    def test_degrades_gracefully_never_crashes(self):
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            client_inst.chat.completions.create = AsyncMock(
                return_value=_mock_hf_response("not valid json at all")
            )
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())

        assert response.status_code == 200
        body = response.json()
        assert body["error"] == "INVALID_JSON_RETURNED"
        assert body["raw_response"] == "not valid json at all"


class TestTiffNormalisedBeforeSend:
    def test_tiff_upload_is_converted_to_png_before_reaching_hf(self):
        """Regression: browsers can't decode TIFF in <img>, and HF vision
        providers aren't guaranteed to accept it either even though the raw
        bytes are technically 'a valid image'. The data URL sent to the
        model must always be real PNG data, regardless of the source
        format the bank's scanner produced."""
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ), patch("openai.AsyncOpenAI") as mock_openai_cls:
            client_inst = AsyncMock()
            create_mock = AsyncMock(return_value=_mock_hf_response(json.dumps({"bank_name": "X"})))
            client_inst.chat.completions.create = create_mock
            mock_openai_cls.return_value = client_inst

            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_tiff_file())

        assert response.status_code == 200
        sent_url = create_mock.call_args.kwargs["messages"][0]["content"][1]["image_url"]["url"]
        assert sent_url.startswith("data:image/png;base64,")


class TestUnreadableFileRejected:
    def test_extract_returns_422_for_unreadable_file(self):
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="hf_fake_token"),
        ):
            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_unreadable_file())
        assert response.status_code == 422


class TestPreviewEndpoint:
    def test_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/cts/demo/cloud-extract/preview", files=_fake_image_file())
        assert response.status_code == 401

    def test_converts_png_upload_to_png(self):
        client = _authed_client()
        response = client.post("/v1/cts/demo/cloud-extract/preview", files=_fake_image_file())
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        decoded = Image.open(io.BytesIO(response.content))
        assert decoded.format == "PNG"
        decoded.load()

    def test_converts_tiff_upload_to_browser_renderable_png(self):
        """The exact regression this endpoint exists to fix: a TIFF scan
        (common for CTS-2010 archival cheque images) came back as PNG bytes
        that any browser can render in <img>, instead of the original TIFF
        that every mainstream browser fails to decode client-side."""
        client = _authed_client()
        response = client.post("/v1/cts/demo/cloud-extract/preview", files=_fake_tiff_file())
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        decoded = Image.open(io.BytesIO(response.content))
        assert decoded.format == "PNG"
        decoded.load()

    def test_returns_422_for_unreadable_file(self):
        client = _authed_client()
        response = client.post("/v1/cts/demo/cloud-extract/preview", files=_fake_unreadable_file())
        assert response.status_code == 422
