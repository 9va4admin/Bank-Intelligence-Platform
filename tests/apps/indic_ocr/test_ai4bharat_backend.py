"""
Tests for the AI4Bharat backend in apps/indic_ocr/main.py.

Covers:
  - _get_ai4bharat_reader(): lazy singleton, GPU→CPU fallback, missing source tree
  - _run_ocr(): ai4bharat happy path, inference error fallback, NotImplementedError fallback
  - /info endpoint: NOT_INSTALLED / READY_TO_LOAD / LOADED status strings
  - /ocr endpoint: ai4bharat backend query param is accepted end-to-end
"""

import importlib
import io
import sys
import types
from typing import Any
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_rgb_array(h: int = 32, w: int = 128) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _png_bytes(h: int = 32, w: int = 128) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(_make_rgb_array(h, w)).save(buf, format="PNG")
    return buf.getvalue()


def _a4b_bboxes(*texts_confs) -> list[dict]:
    """Build fake bbox dicts matching OneFourthLabs/Indic-OCR output format."""
    return [
        {"type": "text", "points": [[0, 0], [10, 0], [10, 5], [0, 5]],
         "text": t, "confidence": c}
        for t, c in texts_confs
    ]


# ── module reload fixture ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """Reset lazy singletons before each test to prevent cross-test pollution."""
    import apps.indic_ocr.main as m
    orig_paddle  = dict(m._paddle_ocr_pool)
    orig_easy    = m._easyocr_reader
    orig_a4b     = m._ai4bharat_reader
    yield
    m._paddle_ocr_pool   = orig_paddle
    m._easyocr_reader    = orig_easy
    m._ai4bharat_reader  = orig_a4b


@pytest.fixture()
def client():
    from apps.indic_ocr.main import app
    return TestClient(app)


# ── _get_ai4bharat_reader() ───────────────────────────────────────────────────

class TestGetAI4BharatReader:

    def test_raises_not_implemented_when_src_dir_missing(self):
        import apps.indic_ocr.main as m
        with patch("apps.indic_ocr.main.os.path.isdir", return_value=False):
            with pytest.raises(NotImplementedError, match="git clone"):
                m._get_ai4bharat_reader()

    def test_raises_not_implemented_when_package_not_importable(self, tmp_path):
        import apps.indic_ocr.main as m
        # src_dir exists but import fails
        src_dir = tmp_path / "ai4bharat_src"
        src_dir.mkdir()
        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True), \
             patch("apps.indic_ocr.main.os.path.dirname", return_value=str(tmp_path)), \
             patch.dict(sys.modules, {"indic_ocr": None,
                                      "indic_ocr.end2end": None,
                                      "indic_ocr.end2end.easy_ocr": None}):
            with pytest.raises(NotImplementedError, match="dependencies.txt"):
                m._get_ai4bharat_reader()

    def test_loads_with_gpu_first(self, tmp_path):
        import apps.indic_ocr.main as m

        mock_reader = MagicMock()
        mock_cls    = MagicMock(return_value=mock_reader)

        fake_module = types.ModuleType("indic_ocr.end2end.easy_ocr")
        fake_module.EasyOCR = mock_cls

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True), \
             patch("apps.indic_ocr.main.os.path.dirname", return_value=str(tmp_path)), \
             patch.dict(sys.modules, {
                 "indic_ocr": MagicMock(),
                 "indic_ocr.end2end": MagicMock(),
                 "indic_ocr.end2end.easy_ocr": fake_module,
             }):
            result = m._get_ai4bharat_reader()

        mock_cls.assert_called_once_with(langs=["hi", "en"], gpu=True)
        assert result is mock_reader

    def test_falls_back_to_cpu_when_gpu_raises(self, tmp_path):
        import apps.indic_ocr.main as m

        mock_cpu_reader = MagicMock()

        def gpu_fail_then_cpu(**kwargs):
            if kwargs.get("gpu"):
                raise RuntimeError("CUDA unavailable")
            return mock_cpu_reader

        mock_cls    = MagicMock(side_effect=gpu_fail_then_cpu)
        fake_module = types.ModuleType("indic_ocr.end2end.easy_ocr")
        fake_module.EasyOCR = mock_cls

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True), \
             patch("apps.indic_ocr.main.os.path.dirname", return_value=str(tmp_path)), \
             patch.dict(sys.modules, {
                 "indic_ocr": MagicMock(),
                 "indic_ocr.end2end": MagicMock(),
                 "indic_ocr.end2end.easy_ocr": fake_module,
             }):
            result = m._get_ai4bharat_reader()

        assert result is mock_cpu_reader
        assert mock_cls.call_count == 2
        mock_cls.assert_any_call(langs=["hi", "en"], gpu=False)

    def test_singleton_not_recreated_on_second_call(self, tmp_path):
        import apps.indic_ocr.main as m

        mock_reader = MagicMock()
        mock_cls    = MagicMock(return_value=mock_reader)
        fake_module = types.ModuleType("indic_ocr.end2end.easy_ocr")
        fake_module.EasyOCR = mock_cls

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True), \
             patch("apps.indic_ocr.main.os.path.dirname", return_value=str(tmp_path)), \
             patch.dict(sys.modules, {
                 "indic_ocr": MagicMock(),
                 "indic_ocr.end2end": MagicMock(),
                 "indic_ocr.end2end.easy_ocr": fake_module,
             }):
            r1 = m._get_ai4bharat_reader()
            r2 = m._get_ai4bharat_reader()

        assert r1 is r2
        mock_cls.assert_called_once()   # constructed only once


# ── _run_ocr() ai4bharat branch ───────────────────────────────────────────────

class TestRunOcrAI4Bharat:

    def _run(self, mock_reader, arr=None):
        import apps.indic_ocr.main as m
        m._ai4bharat_reader = mock_reader
        return m._run_ocr(arr if arr is not None else _make_rgb_array(),
                          m.BACKEND_AI4BHARAT, script="devanagari")

    def test_happy_path_returns_text_confidence_pairs(self):
        mock_reader = MagicMock()
        mock_reader.run.return_value = _a4b_bboxes(("राम", 0.91), ("कुमार", 0.87))

        pairs = self._run(mock_reader)

        assert pairs == [("राम", 0.91), ("कुमार", 0.87)]
        mock_reader.run.assert_called_once()

    def test_empty_bbox_list_returns_empty(self):
        mock_reader = MagicMock()
        mock_reader.run.return_value = []

        assert self._run(mock_reader) == []

    def test_bboxes_with_empty_text_are_filtered(self):
        mock_reader = MagicMock()
        mock_reader.run.return_value = _a4b_bboxes(("", 0.9), ("राम", 0.85))

        pairs = self._run(mock_reader)

        assert pairs == [("राम", 0.85)]

    def test_inference_exception_falls_back_to_paddle(self):
        import apps.indic_ocr.main as m

        mock_a4b = MagicMock()
        mock_a4b.run.side_effect = RuntimeError("inference exploded")

        mock_paddle = MagicMock()
        # PaddleOCR real return shape: [ [line, ...] ] where line = [bbox, (text, conf)]
        mock_paddle.ocr.return_value = [
            [[[[0, 0], [10, 0], [10, 5], [0, 5]], ("नमस्ते", 0.93)]]
        ]
        m._ai4bharat_reader = mock_a4b
        m._paddle_ocr_pool["hi"] = mock_paddle

        pairs = m._run_ocr(_make_rgb_array(), m.BACKEND_AI4BHARAT,
                            script="devanagari")

        assert pairs == [("नमस्ते", 0.93)]
        mock_paddle.ocr.assert_called_once()

    def test_not_implemented_falls_back_to_paddle(self, tmp_path):
        import apps.indic_ocr.main as m

        m._ai4bharat_reader = None   # force load attempt

        mock_paddle = MagicMock()
        mock_paddle.ocr.return_value = [
            [[[[0, 0], [10, 0], [10, 5], [0, 5]], ("नमस्ते", 0.92)]]
        ]
        m._paddle_ocr_pool["hi"] = mock_paddle

        # Patch only the os.path.isdir in the indic_ocr module namespace
        with patch("apps.indic_ocr.main.os.path.isdir", return_value=False):
            pairs = m._run_ocr(_make_rgb_array(), m.BACKEND_AI4BHARAT,
                               script="devanagari")

        assert pairs == [("नमस्ते", 0.92)]

    def test_confidence_cast_to_float(self):
        mock_reader = MagicMock()
        mock_reader.run.return_value = [
            {"type": "text", "points": [], "text": "राम", "confidence": "0.88"}
        ]
        pairs = self._run(mock_reader)
        assert pairs == [("राम", 0.88)]
        assert isinstance(pairs[0][1], float)


# ── /info endpoint ────────────────────────────────────────────────────────────

class TestInfoEndpoint:

    def test_not_installed_status_when_src_dir_missing(self, client):
        with patch("apps.indic_ocr.main.os.path.isdir", return_value=False):
            resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "NOT_INSTALLED" in data["ai4bharat_status"]
        assert data["loaded_ai4bharat"] is False

    def test_ready_to_load_status_when_src_dir_present_not_loaded(self, client):
        import apps.indic_ocr.main as m
        m._ai4bharat_reader = None

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True):
            resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "READY_TO_LOAD" in data["ai4bharat_status"]
        assert data["loaded_ai4bharat"] is False

    def test_loaded_status_when_reader_is_initialised(self, client):
        import apps.indic_ocr.main as m
        m._ai4bharat_reader = MagicMock()   # simulate loaded reader

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=True):
            resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "LOADED" in data["ai4bharat_status"]
        assert data["loaded_ai4bharat"] is True

    def test_info_includes_all_required_keys(self, client):
        resp = client.get("/info")
        keys = resp.json().keys()
        for k in ("service_default", "valid_backends", "supported_scripts",
                  "loaded_paddle", "loaded_easyocr", "loaded_ai4bharat",
                  "ai4bharat_status"):
            assert k in keys, f"missing key: {k}"


# ── /ocr endpoint: ai4bharat backend param accepted ──────────────────────────

class TestOcrEndpointAI4Bharat:

    def test_ocr_endpoint_accepts_ai4bharat_backend(self, client):
        import apps.indic_ocr.main as m

        mock_reader = MagicMock()
        mock_reader.run.return_value = _a4b_bboxes(("राम", 0.90))
        m._ai4bharat_reader = mock_reader

        resp = client.post(
            "/ocr?backend=ai4bharat&script=devanagari",
            files={"file": ("test.png", _png_bytes(), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backend"] == "ai4bharat"
        assert data["text"] == "राम"
        assert data["confidence"] == pytest.approx(0.90, abs=1e-4)

    def test_ocr_endpoint_falls_back_gracefully_when_a4b_not_installed(
        self, client
    ):
        import apps.indic_ocr.main as m
        m._ai4bharat_reader = None

        mock_paddle = MagicMock()
        mock_paddle.ocr.return_value = [
            [[[[0, 0], [10, 0], [10, 5], [0, 5]], ("नमस्ते", 0.88)]]
        ]
        m._paddle_ocr_pool["hi"] = mock_paddle

        with patch("apps.indic_ocr.main.os.path.isdir", return_value=False):
            resp = client.post(
                "/ocr?backend=ai4bharat&script=devanagari",
                files={"file": ("test.png", _png_bytes(), "image/png")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "नमस्ते"
        assert data["confidence"] == pytest.approx(0.88, abs=1e-4)

    def test_invalid_backend_returns_400(self, client):
        resp = client.post(
            "/ocr?backend=nonexistent",
            files={"file": ("test.png", _png_bytes(), "image/png")},
        )
        assert resp.status_code == 400
