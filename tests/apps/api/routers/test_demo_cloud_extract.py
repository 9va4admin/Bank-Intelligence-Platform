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


def _fake_image_file():
    return {"file": ("cheque.png", io.BytesIO(b"fake-png-bytes"), "image/png")}


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
    def test_returns_503_when_token_fetch_fails(self):
        client = _authed_client()
        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(side_effect=Exception("Vault unreachable")),
        ):
            response = client.post("/v1/cts/demo/cloud-extract", files=_fake_image_file())
        assert response.status_code == 503


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
