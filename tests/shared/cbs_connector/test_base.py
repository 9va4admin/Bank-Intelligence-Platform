"""
Tests for CBSConnector abstract base and AccountInfo response schema.

TDD: written BEFORE the implementation.
"""
import pytest
from unittest.mock import AsyncMock

from shared.cbs_connector.base import CBSConnector, AccountInfo, AccountStatus
from shared.cbs_connector.exceptions import (
    CBSUnavailableError,
    AccountNotFoundError,
)


# ---------------------------------------------------------------------------
# AccountInfo schema
# ---------------------------------------------------------------------------

def test_account_info_constructs_with_required_fields():
    info = AccountInfo(
        account_number_hash="sha256abc",
        account_number_last4="4521",
        status=AccountStatus.ACTIVE,
        bank_id="test-bank",
    )
    assert info.status == AccountStatus.ACTIVE
    assert info.account_number_last4 == "4521"


def test_account_info_does_not_store_raw_account_number():
    """Raw account number must never appear in AccountInfo — only hash + last4."""
    info = AccountInfo(
        account_number_hash="sha256abc",
        account_number_last4="4521",
        status=AccountStatus.ACTIVE,
        bank_id="test-bank",
    )
    info_dict = info.model_dump()
    # No field should contain a raw account number
    assert "account_number" not in info_dict
    for key, val in info_dict.items():
        if isinstance(val, str) and len(val) > 10:
            assert key in ("account_number_hash",), \
                f"Field '{key}' might contain raw account number: {val[:4]}..."


def test_account_status_enum_has_expected_values():
    assert AccountStatus.ACTIVE in AccountStatus
    assert AccountStatus.FROZEN in AccountStatus
    assert AccountStatus.CLOSED in AccountStatus
    assert AccountStatus.DORMANT in AccountStatus
    assert AccountStatus.NPA in AccountStatus


def test_account_info_balance_is_optional():
    info = AccountInfo(
        account_number_hash="h",
        account_number_last4="1234",
        status=AccountStatus.ACTIVE,
        bank_id="test-bank",
    )
    assert info.available_balance is None


def test_account_info_frozen_has_no_balance():
    info = AccountInfo(
        account_number_hash="h",
        account_number_last4="1234",
        status=AccountStatus.FROZEN,
        bank_id="test-bank",
        available_balance=None,
    )
    assert info.status == AccountStatus.FROZEN


# ---------------------------------------------------------------------------
# Abstract interface — cannot be instantiated directly
# ---------------------------------------------------------------------------

def test_cbs_connector_is_abstract():
    with pytest.raises(TypeError):
        CBSConnector()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Finacle adapter — via concrete subclass stub
# ---------------------------------------------------------------------------

class _StubCBS(CBSConnector):
    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        if account_number == "notfound":
            raise AccountNotFoundError(account_number)
        if account_number == "error":
            raise CBSUnavailableError("CBS timeout")
        return AccountInfo(
            account_number_hash="stub-hash",
            account_number_last4=account_number[-4:],
            status=AccountStatus.ACTIVE,
            bank_id=bank_id,
            available_balance=100000.0,
        )

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        return [b"specimen1", b"specimen2"]


@pytest.mark.asyncio
async def test_stub_get_account_info_returns_account_info():
    cbs = _StubCBS()
    info = await cbs.get_account_info("1234567890", "test-bank")
    assert info.status == AccountStatus.ACTIVE
    assert info.available_balance == 100000.0


@pytest.mark.asyncio
async def test_stub_get_account_info_raises_not_found():
    cbs = _StubCBS()
    with pytest.raises(AccountNotFoundError):
        await cbs.get_account_info("notfound", "test-bank")


@pytest.mark.asyncio
async def test_stub_get_account_info_raises_unavailable():
    cbs = _StubCBS()
    with pytest.raises(CBSUnavailableError):
        await cbs.get_account_info("error", "test-bank")


@pytest.mark.asyncio
async def test_stub_get_signature_specimens_returns_bytes_list():
    cbs = _StubCBS()
    specimens = await cbs.get_signature_specimens("1234567890", "test-bank")
    assert len(specimens) == 2
    assert all(isinstance(s, bytes) for s in specimens)
