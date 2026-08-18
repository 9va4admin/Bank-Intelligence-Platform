"""
CTS Session Report — HTML → PDF renderer.

Production (Linux Docker): uses WeasyPrint (requires libgobject/Pango — installed
via Dockerfile: apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2).

Development (Windows / no GTK): falls back to xhtml2pdf (pure Python, no system
deps, slightly lower fidelity — acceptable for dev iteration).

Both paths produce a valid PDF byte stream starting with %PDF.
"""
from __future__ import annotations

import io

import structlog

log = structlog.get_logger()


def render_pdf(html: str) -> bytes:
    """Convert an HTML string to PDF bytes. Never raises — on total failure returns
    a minimal 1-page error PDF so callers can always write something to MinIO."""
    try:
        return _render_weasyprint(html)
    except Exception as e_wp:
        log.warning("pdf_renderer.weasyprint_unavailable", error=str(e_wp))
        try:
            return _render_xhtml2pdf(html)
        except Exception as e_xh:
            log.error("pdf_renderer.xhtml2pdf_failed", error=str(e_xh))
            return _fallback_pdf()


def _render_weasyprint(html: str) -> bytes:
    from weasyprint import HTML  # type: ignore
    buf = io.BytesIO()
    HTML(string=html).write_pdf(buf)
    return buf.getvalue()


def _render_xhtml2pdf(html: str) -> bytes:
    from xhtml2pdf import pisa  # type: ignore
    buf = io.BytesIO()
    result = pisa.CreatePDF(io.StringIO(html), dest=buf)
    if result.err:
        raise RuntimeError(f"xhtml2pdf error: {result.err}")
    return buf.getvalue()


def _fallback_pdf() -> bytes:
    # Minimal valid PDF — single page with error notice
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 72 770 Td (PDF generation failed) Tj ET\n"
        b"endstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n9\n%%EOF"
    )
    return body
