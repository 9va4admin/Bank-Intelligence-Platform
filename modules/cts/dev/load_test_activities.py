"""
LOAD-TEST AI STUBS — DEV ONLY, NOT A REAL MODEL.

Replaces the six AI-backed activities (OCR, alteration, security features,
signature detect, signature verify, fraud score) with instant fixed answers so a
load test exercises everything ELSE for real: Temporal, Kafka, Redis, YugabyteDB,
ImmuDB, vaults, policy engine, CBS/NGCH stand-ins. Timings measured this way say
nothing about AI throughput or the 600 ms SLA. Refuses unless ASTRA_ENV=development.
"""
import os
from datetime import date

from temporalio import activity

from modules.cts.worker_activities import BoundCTSActivities
from modules.cts.workflows.activities.alteration import AlterationActivityResult
from modules.cts.workflows.activities.detect_signatures import DetectSignaturesResult
from modules.cts.workflows.activities.fraud import FraudActivityResult
from modules.cts.workflows.activities.ocr import OCRActivityResult
from modules.cts.workflows.activities.security_features import SecurityFeaturesResult
from modules.cts.workflows.activities.signature import SignatureActivityResult

STUB_LABEL = "LOAD-TEST-STUB"


class LoadTestBoundActivities(BoundCTSActivities):
    @activity.defn(name="ocr_extract")
    async def ocr_extract(self, inp, *a, **k):
        return OCRActivityResult(
            outcome="PROCEED", micr_line="000000 000000000 000000 00",
            amount_figures="10000.00", amount_words="Rupees Ten Thousand Only",
            date=date.today().strftime("%d/%m/%Y"), payee="LOAD TEST PAYEE",
            overall_confidence=0.99, cascade_level=0, ocr_engines_used=[STUB_LABEL],
        )

    @activity.defn(name="detect_alteration")
    async def detect_alteration(self, inp, *a, **k):
        return AlterationActivityResult(alteration_detected=False, model_version=STUB_LABEL)

    @activity.defn(name="check_security_features")
    async def check_security_features(self, inp):
        return SecurityFeaturesResult(outcome="PROCEED", features_detected={STUB_LABEL: True})

    @activity.defn(name="detect_signatures")
    async def detect_signatures(self, inp):
        return DetectSignaturesResult(outcome="PRESENT", sig_count=1,
                                      sig_bboxes=[[0.6, 0.6, 0.9, 0.8]], fraud_flags=[])

    @activity.defn(name="verify_signature")
    async def verify_signature(self, inp):
        return SignatureActivityResult(outcome="PROCEED", match_score=0.99, signatories_matched=1)

    @activity.defn(name="score_fraud")
    async def score_fraud(self, inp):
        return FraudActivityResult(fraud_score=0.05, shap_values={STUB_LABEL: 0.0},
                                   rationale="load-test stub — not a model output")


def apply_load_test_stubs(bound: BoundCTSActivities) -> LoadTestBoundActivities:
    if os.environ.get("ASTRA_ENV", "").lower() != "development":
        raise RuntimeError("load-test AI stubs may only run with ASTRA_ENV=development")
    stub = LoadTestBoundActivities.__new__(LoadTestBoundActivities)
    stub.__dict__.update(bound.__dict__)      # keep every real dependency
    return stub
