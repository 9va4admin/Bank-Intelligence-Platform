"""
Tests for modules/msv/enrollment/account_enroller.py

Covers:
  - Happy path: 3 specimens enrolled, result ENROLLED
  - Idempotent: second call returns SKIPPED (already enrolled)
  - CBS empty: result FAILED with error_reason
  - Image bytes not stored in result
  - Partial CBS data (some specimens missing) handled
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.msv.enrollment.account_enroller import AccountEnroller, EnrollmentResult


def _make_cbs_connector(specimens: list[bytes] | None = None):
    """Return a mock CBS connector."""
    if specimens is None:
        specimens = [b"img_0", b"img_1", b"img_2"]

    connector = MagicMock()

    from shared.cbs_connector.base import CBSSignatoryData
    sig_data = [
        CBSSignatoryData(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_images=specimens,
            operation_type="J",
        )
    ]
    connector.get_signatory_data = AsyncMock(return_value=sig_data)
    return connector


def _make_embedding_model(dim: int = 512):
    model = MagicMock()
    model.embed = AsyncMock(return_value=[0.1] * dim)
    return model


def _make_registry():
    registry = MagicMock()
    registry.store = AsyncMock(return_value=None)
    registry._hash_account = AsyncMock(return_value="hashed_account_abc")
    return registry


def _make_progress_tracker(enrolled: bool = False):
    tracker = MagicMock()
    tracker.is_enrolled = AsyncMock(return_value=enrolled)
    tracker.mark_enrolled = AsyncMock(return_value=None)
    tracker.mark_failed = AsyncMock(return_value=None)
    return tracker


class TestAccountEnroller:
    @pytest.mark.asyncio
    async def test_happy_path_enrolls_3_specimens(self):
        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector([b"img_0", b"img_1", b"img_2"]),
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "ENROLLED"
        assert result.specimens_enrolled == 3

    @pytest.mark.asyncio
    async def test_idempotent_second_call_returns_skipped(self):
        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector(),
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=True),  # already enrolled
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "SKIPPED"
        assert result.specimens_enrolled == 0

    @pytest.mark.asyncio
    async def test_cbs_empty_returns_failed(self):
        connector = MagicMock()
        connector.get_signatory_data = AsyncMock(return_value=[])

        enroller = AccountEnroller(
            cbs_connector=connector,
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "FAILED"
        assert result.error_reason is not None

    @pytest.mark.asyncio
    async def test_cbs_unavailable_returns_failed(self):
        from shared.cbs_connector.exceptions import CBSUnavailableError
        connector = MagicMock()
        connector.get_signatory_data = AsyncMock(side_effect=CBSUnavailableError("CBS down"))

        enroller = AccountEnroller(
            cbs_connector=connector,
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "FAILED"
        assert "CBS" in (result.error_reason or "").upper() or result.error_reason is not None

    @pytest.mark.asyncio
    async def test_image_bytes_not_in_result(self):
        """EnrollmentResult must not contain any image bytes."""
        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector([b"secret_sig_image"]),
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        # result should be an EnrollmentResult with no bytes fields
        result_dict = result.model_dump()
        for v in result_dict.values():
            assert not isinstance(v, bytes), f"Image bytes leaked into result: {v!r}"

    @pytest.mark.asyncio
    async def test_account_hash_in_result_not_raw_number(self):
        """Result.account_hash must not be the raw account number."""
        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector(),
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        raw_account = "1234567890"
        result = await enroller.enroll("kotak-mah", raw_account, "J", "batch-001")
        assert result.account_hash != raw_account

    @pytest.mark.asyncio
    async def test_partial_specimens_enrolled_available(self):
        """1 of 3 expected specimens available → enrolls 1, no crash."""
        specimens = [b"img_0"]  # only 1 specimen available
        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector(specimens),
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "ENROLLED"
        assert result.specimens_enrolled == 1

    @pytest.mark.asyncio
    async def test_embedding_model_unavailable_marks_failed(self):
        from modules.msv.ai.embedding_model import EmbeddingModelUnavailableError
        model = MagicMock()
        model.embed = AsyncMock(side_effect=EmbeddingModelUnavailableError("vLLM down"))

        enroller = AccountEnroller(
            cbs_connector=_make_cbs_connector(),
            embedding_model=model,
            registry=_make_registry(),
            progress_tracker=_make_progress_tracker(enrolled=False),
        )
        result = await enroller.enroll("kotak-mah", "1234567890", "J", "batch-001")
        assert result.status == "FAILED"
