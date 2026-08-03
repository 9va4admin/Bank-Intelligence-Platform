"""
Image deskew utility — corrects scanner orientation skew using horizontal edge detection.

Detects the dominant skew angle from horizontal structure (MICR band, cheque border lines)
and rotates the image to canonical landscape orientation.

CPU-only (OpenCV) — no GPU, no vLLM. Typical runtime: <10ms on a 300 DPI cheque image.

Falls back to the original bytes if:
  - opencv-python is not installed
  - No dominant near-horizontal angle is found
  - The image bytes are corrupt or unreadable
  - The detected angle is outside max_angle_deg (portrait orientation, not mere skew)
"""
from __future__ import annotations

import io as _io
import logging
import math

log = logging.getLogger(__name__)


def deskew_image(image_bytes: bytes, max_angle_deg: float = 15.0) -> bytes:
    """
    Detect skew in a cheque image and rotate to canonical horizontal orientation.

    Uses Probabilistic Hough Transform on binarised edges to find the dominant
    near-horizontal line angle, then applies an affine rotation to correct it.

    Args:
        image_bytes:   Raw image bytes (JPEG / PNG / TIFF from MinIO or scanner).
        max_angle_deg: Maximum skew angle to correct (default 15°). Angles beyond
                       this range indicate portrait/mis-oriented images — those are
                       NOT corrected here (different problem, different fix).

    Returns:
        PNG bytes of the deskewed image, or the original bytes unchanged when
        no correction is needed or possible.
    """
    if not image_bytes:
        return image_bytes

    try:
        import cv2
        import numpy as np
    except ImportError:
        log.warning("deskew.opencv_unavailable — returning original image unchanged")
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150, apertureSize=3)

        # Probabilistic Hough — lines must span at least 25% of image width
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=math.pi / 180,
            threshold=80,
            minLineLength=max(50, img.shape[1] // 4),
            maxLineGap=20,
        )
        if lines is None or len(lines) == 0:
            return image_bytes

        angles: list[float] = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 != x1:
                angle_deg = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
                if abs(angle_deg) <= max_angle_deg:
                    angles.append(angle_deg)

        if not angles:
            return image_bytes

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.1:
            return image_bytes

        h, w = img.shape[:2]
        rot_matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), median_angle, scale=1.0)
        rotated = cv2.warpAffine(
            img, rot_matrix, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

        _, encoded = cv2.imencode(".png", rotated)
        return bytes(encoded)

    except Exception as exc:
        log.warning("deskew.correction_failed — returning original image", exc_info=exc)
        return image_bytes
