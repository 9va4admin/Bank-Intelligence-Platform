"""Load-test AI stubs — DEV ONLY. Replace the six AI-backed activities with instant,
fixed, clearly-labelled answers so a load test measures the pipeline and
infrastructure (Temporal, Kafka, Redis, YugabyteDB, ImmuDB), never AI speed.
Refuses to apply unless ASTRA_ENV=development."""
import pytest

from modules.cts.worker_activities import BoundCTSActivities

AI_NAMES = {"ocr_extract", "detect_alteration", "check_security_features",
            "detect_signatures", "verify_signature", "score_fraud"}


def _bound():
    return BoundCTSActivities(bank_id="kbl")


def test_refuses_outside_development(monkeypatch):
    from modules.cts.dev.load_test_activities import apply_load_test_stubs
    monkeypatch.setenv("ASTRA_ENV", "production")
    with pytest.raises(RuntimeError, match="development"):
        apply_load_test_stubs(_bound())


def test_only_ai_activities_are_replaced(monkeypatch):
    from modules.cts.dev.load_test_activities import apply_load_test_stubs
    monkeypatch.setenv("ASTRA_ENV", "development")
    real, stub = _bound(), apply_load_test_stubs(_bound())
    changed = {a.__name__ for a in stub.activity_list()
               if getattr(type(stub), a.__name__) is not getattr(BoundCTSActivities, a.__name__)}
    assert changed == AI_NAMES
    assert len(stub.activity_list()) == len(real.activity_list())


@pytest.mark.asyncio
async def test_stub_results_are_valid_models_and_labelled(monkeypatch):
    from modules.cts.dev.load_test_activities import apply_load_test_stubs
    monkeypatch.setenv("ASTRA_ENV", "development")
    s = apply_load_test_stubs(_bound())
    ocr = await s.ocr_extract(object())
    assert ocr.outcome == "PROCEED" and ocr.overall_confidence >= 0.95
    assert "LOAD-TEST-STUB" in ocr.ocr_engines_used
    assert (await s.detect_alteration(object())).alteration_detected is False
    assert (await s.check_security_features(object())).outcome == "PROCEED"
    d = await s.detect_signatures(object())
    assert d.outcome == "PRESENT" and d.sig_count == 1
    assert (await s.verify_signature(object())).outcome == "PROCEED"
    f = await s.score_fraud(object())
    assert 0.0 <= f.fraud_score <= 1.0 and f.shap_values
