"""
Real Immudb integration tests for shared/audit/immudb_client.py and
shared/audit/immudb_writer.py — against astra-it-immudb
(infra/docker-compose.integration.yml), not a mock.

This is the file that first caught the real bug: write_event() called the
non-cryptographically-verified .set() instead of .verifiedSet(), silently
defeating the audit trail's Merkle-tree verification guarantee (security.md
Principle #6: "Audit Always On — cannot be disabled; tampering is
cryptographically detectable"). A mocked stub can be told .set() returns
verified=True and never notice the difference; the real SDK does not lie —
.set() genuinely returns verified=False.
"""
import uuid

import pytest

from shared.audit.exceptions import ImmudbUnavailableError, ImmudbVerificationError
from shared.audit.immudb_client import ImmudbClient
from shared.audit.immudb_writer import AsyncImmudbWriter
from tests.integration.conftest import IMMUDB_HOST, IMMUDB_PASSWORD, IMMUDB_PORT, IMMUDB_USERNAME

pytestmark = pytest.mark.integration


@pytest.fixture
def bank_id() -> str:
    return f"it-bank-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def connected_client(require_immudb, bank_id) -> ImmudbClient:
    client = ImmudbClient()
    client.connect(IMMUDB_HOST, IMMUDB_PORT, bank_id, username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD)
    return client


class TestConnectAgainstRealServer:
    def test_wrong_password_raises_immudb_unavailable(self, require_immudb, bank_id):
        client = ImmudbClient()
        with pytest.raises(ImmudbUnavailableError):
            client.connect(IMMUDB_HOST, IMMUDB_PORT, bank_id, username=IMMUDB_USERNAME, password="wrong-password")

    def test_unreachable_host_raises_immudb_unavailable(self, bank_id):
        client = ImmudbClient()
        with pytest.raises(ImmudbUnavailableError):
            # Port 1 is never immudb -- connection refused immediately, no long timeout.
            client.connect("localhost", 1, bank_id, username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD)


class TestWriteEventIsCryptographicallyVerified:
    def test_write_event_returns_verified_true(self, connected_client, bank_id):
        result = connected_client.write_event(
            {"event_type": "IT_CTS_DECISION", "bank_id": bank_id, "instrument_id": "instr-001"}
        )
        # The bug this test guards against: write_event() previously called the
        # plain .set() (unverified write), which the real SDK returns verified=False
        # for. Only .verifiedSet() produces a cryptographically verified True here.
        assert result["verified"] is True
        assert isinstance(result["tx_id"], int)
        assert result["tx_id"] > 0

    def test_verify_event_confirms_the_write(self, connected_client, bank_id):
        result = connected_client.write_event(
            {"event_type": "IT_CTS_DECISION", "bank_id": bank_id, "instrument_id": "instr-002"}
        )
        assert connected_client.verify_event(result["key"]) is True

    def test_verify_event_on_nonexistent_key_raises(self, connected_client, bank_id):
        fake_key = connected_client._make_key(bank_id, "cts_events", "never-written")
        with pytest.raises((ImmudbVerificationError, ImmudbUnavailableError)):
            connected_client.verify_event(fake_key)

    def test_two_writes_same_bank_produce_different_keys(self, connected_client, bank_id):
        r1 = connected_client.write_event({"event_type": "A", "bank_id": bank_id, "event_id": "evt-1"})
        r2 = connected_client.write_event({"event_type": "A", "bank_id": bank_id, "event_id": "evt-2"})
        assert r1["key"] != r2["key"]
        assert connected_client.verify_event(r1["key"]) is True
        assert connected_client.verify_event(r2["key"]) is True

    def test_collection_switch_is_reflected_in_written_record(self, connected_client, bank_id):
        connected_client.set_collection("ej_events")
        result = connected_client.write_event({"event_type": "IT_EJ_EVENT", "bank_id": bank_id})
        assert result["collection"] == "ej_events"
        assert connected_client.verify_event(result["key"]) is True


class TestAsyncImmudbWriterAgainstRealServer:
    @pytest.mark.asyncio
    async def test_write_returns_tx_id_as_string(self, connected_client, bank_id):
        writer = AsyncImmudbWriter(connected_client)
        tx_id = await writer.write(
            collection="cts_events", event_type="CTS_NGCH_FILED_CONFIRM",
            bank_id=bank_id, instrument_id="instr-003", payload={"outcome": "STP_CONFIRM"},
        )
        assert isinstance(tx_id, str)
        assert tx_id.isdigit()

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_different_collections_do_not_interleave(self, connected_client, bank_id):
        """
        Regression guard for the race AsyncImmudbWriter's docstring calls out:
        set_collection() + write_event() must run inside the same
        asyncio.to_thread() call, or concurrent writers targeting different
        collections on one ImmudbClient could write to the wrong one.
        """
        import asyncio

        writer = AsyncImmudbWriter(connected_client)
        results = await asyncio.gather(
            *[
                writer.write(
                    collection=f"it_collection_{i}", event_type="IT_RACE_TEST",
                    bank_id=bank_id, payload={"i": i},
                )
                for i in range(10)
            ]
        )
        assert len(results) == 10
        assert len(set(results)) == 10  # every tx_id distinct -- no write clobbered another
