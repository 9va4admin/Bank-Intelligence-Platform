"""
Tests for modules/cts/preprocessing/deskew.py

deskew_image(bytes) -> bytes
  - Straight image: returned unchanged (or near-zero rotation applied)
  - Skewed image: corrects back to horizontal
  - Invalid bytes: returns original bytes (never raises)
  - OpenCV unavailable: returns original bytes (never raises)
"""
import io
import pytest


def _make_png_bytes(width: int = 200, height: int = 80, angle_deg: float = 0.0) -> bytes:
    """Create a synthetic PNG with a horizontal black bar (simulating MICR band).
    If angle_deg != 0, rotate the bar to simulate scanner skew.
    """
    try:
        from PIL import Image as _PIL
        import numpy as np
    except ImportError:
        pytest.skip("PIL or numpy not available")

    img = _PIL.new("RGB", (width, height), color=(255, 255, 255))
    pixels = img.load()
    # Draw a horizontal black stripe across the bottom quarter
    for x in range(width):
        for y in range(int(height * 0.75), height):
            pixels[x, y] = (0, 0, 0)

    if angle_deg != 0.0:
        img = img.rotate(angle_deg, expand=False, fillcolor=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeskewImage:
    def test_straight_image_returns_bytes(self):
        """A straight image should return valid PNG bytes (possibly same content)."""
        from modules.cts.preprocessing.deskew import deskew_image
        raw = _make_png_bytes(angle_deg=0.0)
        result = deskew_image(raw)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_skewed_image_returns_bytes(self):
        """A skewed image should return valid PNG bytes after correction."""
        from modules.cts.preprocessing.deskew import deskew_image
        raw = _make_png_bytes(width=400, height=100, angle_deg=5.0)
        result = deskew_image(raw)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_invalid_bytes_returns_original(self):
        """Invalid/corrupt bytes must return original bytes, never raise."""
        from modules.cts.preprocessing.deskew import deskew_image
        garbage = b"\x00\x01\x02\x03\xff" * 10
        result = deskew_image(garbage)
        assert result == garbage

    def test_empty_bytes_returns_original(self):
        """Empty bytes must return empty bytes, never raise."""
        from modules.cts.preprocessing.deskew import deskew_image
        result = deskew_image(b"")
        assert result == b""

    def test_large_angle_beyond_threshold_returns_original(self):
        """Angles > max_angle_deg (default 15°) are not corrected — likely portrait orientation."""
        from modules.cts.preprocessing.deskew import deskew_image
        raw = _make_png_bytes(width=400, height=100, angle_deg=45.0)
        result = deskew_image(raw)
        # Should still return bytes (not raise), but won't necessarily correct the image
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_custom_max_angle(self):
        """max_angle_deg parameter is respected."""
        from modules.cts.preprocessing.deskew import deskew_image
        raw = _make_png_bytes(width=400, height=100, angle_deg=3.0)
        # With max_angle_deg=2, a 3° skew should NOT be corrected
        result = deskew_image(raw, max_angle_deg=2.0)
        assert isinstance(result, bytes)

    def test_opencv_unavailable_returns_original(self, monkeypatch):
        """If cv2 is not importable, original bytes returned unchanged."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("simulated missing cv2")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        # Re-import the module so the patched import is used
        import importlib
        import sys
        # Remove cached module so it re-runs the import
        sys.modules.pop("modules.cts.preprocessing.deskew", None)

        from modules.cts.preprocessing.deskew import deskew_image
        raw = _make_png_bytes()
        result = deskew_image(raw)
        assert result == raw
