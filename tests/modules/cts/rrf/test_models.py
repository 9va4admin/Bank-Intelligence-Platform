# Stub — all tests live in test_rrf_generator.py (consolidated file).
from tests.modules.cts.rrf.test_rrf_generator import *  # noqa: F401,F403


class TestRBIReturnCodeFromUIReasonMissingBranches:
    """Cover lines 66, 68, 70, 72, 74, 76, 78, 80: from_ui_reason branches."""
    def test_dormant_account(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("account is dormant") == RBIReturnCode.ACCOUNT_CLOSED

    def test_post_dated(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("cheque is post-dated") == RBIReturnCode.CHEQUE_POST_DATED

    def test_mutilated(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("cheque is mutilated") == RBIReturnCode.CHEQUE_STALE_MUTILATED

    def test_payee_name_discrepancy(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("payee name discrepancy") == RBIReturnCode.PAYEE_ENDORSEMENT_REQUIRED

    def test_no_specimen(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("no specimen available") == RBIReturnCode.REFER_TO_DRAWER

    def test_payment_stopped(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("payment stopped by drawer") == RBIReturnCode.PAYMENT_STOPPED

    def test_micr_incorrect(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("micr line incorrect") == RBIReturnCode.MICR_INCORRECT

    def test_image_quality(self):
        from modules.cts.rrf.models import RBIReturnCode
        assert RBIReturnCode.from_ui_reason("poor image quality") == RBIReturnCode.IMAGE_POOR_QUALITY
