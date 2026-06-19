"""
Tests for CTS Endorsement — EndorsementTemplate, EndorsementRecord, EndorsementStamper,
BatchEndorsementProcessor.

TDD: RED phase — all tests must fail before implementation.
"""
import pytest
from datetime import datetime, timezone


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_template():
    from modules.cts.endorsement.models import EndorsementTemplate
    return EndorsementTemplate(
        bank_name='South View Co-operative Bank',
        branch_name='Fort Branch',
        bank_ifsc='SVCB0000001',
        endorsement_text="Payee's Account Credited. Received for Collection.",
    )


# ── EndorsementTemplate ───────────────────────────────────────────────────────

def test_endorsement_template_fields():
    tmpl = make_template()
    assert tmpl.bank_name  == 'South View Co-operative Bank'
    assert tmpl.bank_ifsc  == 'SVCB0000001'
    assert tmpl.branch_name == 'Fort Branch'
    assert "Payee's Account Credited" in tmpl.endorsement_text


def test_endorsement_template_is_frozen():
    from dataclasses import FrozenInstanceError
    tmpl = make_template()
    with pytest.raises(FrozenInstanceError):
        tmpl.bank_name = 'Other Bank'


# ── EndorsementRecord ─────────────────────────────────────────────────────────

def test_endorsement_record_valid_suffix():
    from modules.cts.endorsement.models import EndorsementRecord
    rec = EndorsementRecord(
        instrument_id='CHQ-IN-00201',
        account_suffix='4521',
        presentation_date=datetime.now(tz=timezone.utc),
        applied_at=datetime.now(tz=timezone.utc),
        template=make_template(),
    )
    assert rec.account_suffix == '4521'


def test_endorsement_record_rejects_suffix_over_4_chars():
    from modules.cts.endorsement.models import EndorsementRecord
    with pytest.raises(ValueError, match='4 characters'):
        EndorsementRecord(
            instrument_id='CHQ-IN-00201',
            account_suffix='12345',   # 5 chars — must be rejected
            presentation_date=datetime.now(tz=timezone.utc),
            applied_at=datetime.now(tz=timezone.utc),
            template=make_template(),
        )


def test_endorsement_record_allows_short_suffix():
    from modules.cts.endorsement.models import EndorsementRecord
    rec = EndorsementRecord(
        instrument_id='CHQ-IN-00201',
        account_suffix='21',   # 2 chars — allowed
        presentation_date=datetime.now(tz=timezone.utc),
        applied_at=datetime.now(tz=timezone.utc),
        template=make_template(),
    )
    assert rec.account_suffix == '21'


# ── EndorsementStamper ────────────────────────────────────────────────────────

def test_stamper_returns_record_with_correct_fields():
    from modules.cts.endorsement.stamper import EndorsementStamper
    stamper = EndorsementStamper(make_template())
    record, _ = stamper.stamp(
        instrument_id='CHQ-IN-00201',
        account_suffix='4521',
        rear_image_bytes=b'\xff\xd8\xff' + b'\x00' * 100,
    )
    assert record.instrument_id  == 'CHQ-IN-00201'
    assert record.account_suffix == '4521'
    assert record.template.bank_ifsc == 'SVCB0000001'


def test_stamper_applied_at_is_utc():
    from modules.cts.endorsement.stamper import EndorsementStamper
    stamper = EndorsementStamper(make_template())
    record, _ = stamper.stamp('CHQ-IN-00202', '7832', b'\xff\xd8\xff')
    assert record.applied_at.tzinfo is not None


def test_stamper_stamped_bytes_larger_than_original():
    from modules.cts.endorsement.stamper import EndorsementStamper
    stamper = EndorsementStamper(make_template())
    original = b'\xff\xd8\xff' + b'\x00' * 200
    _, stamped = stamper.stamp('CHQ-IN-00203', '2291', original)
    assert len(stamped) > len(original)


def test_stamper_stamped_bytes_start_with_original():
    from modules.cts.endorsement.stamper import EndorsementStamper
    stamper = EndorsementStamper(make_template())
    original = b'\xff\xd8\xff' + b'\x00' * 50
    _, stamped = stamper.stamp('CHQ-IN-00204', '6610', original)
    assert stamped[:len(original)] == original


def test_stamper_qr_data_contains_ifsc_and_instrument():
    from modules.cts.endorsement.stamper import EndorsementStamper
    stamper = EndorsementStamper(make_template())
    record, _ = stamper.stamp('CHQ-IN-00205', '3347', b'\xff\xd8\xff')
    qr = stamper.qr_data(record)
    assert 'SVCB0000001'   in qr
    assert 'CHQ-IN-00205'  in qr
    assert 'ASTRA-ENDORSE' in qr


# ── BatchEndorsementProcessor ─────────────────────────────────────────────────

def _make_items(count: int) -> list[tuple[str, str, bytes, bytes]]:
    return [
        (f'CHQ-IN-{i:05d}', str(i)[-4:].zfill(4), b'\xff\xd8\xff', b'\xff\xd8\xff')
        for i in range(1, count + 1)
    ]


def test_batch_processor_returns_correct_count():
    from modules.cts.endorsement.batch import BatchEndorsementProcessor
    proc = BatchEndorsementProcessor(make_template())
    records = proc.process(_make_items(5))
    assert len(records) == 5


def test_batch_processor_raises_on_duplicate_instrument_id():
    from modules.cts.endorsement.batch import BatchEndorsementProcessor
    proc = BatchEndorsementProcessor(make_template())
    items = _make_items(3)
    items.append(items[0])   # duplicate first item
    with pytest.raises(ValueError, match='Duplicate instrument_id'):
        proc.process(items)
