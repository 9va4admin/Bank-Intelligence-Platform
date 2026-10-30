"""Exceptions for the shared/sb_connector adapter layer."""
from shared.messages import get_message


class SBConnectorUnavailableError(RuntimeError):
    """SB connector cannot reach the upstream Sponsor Bank."""

    def __init__(self, sb_bank_id: str, connector_type: str, reason: str) -> None:
        self.sb_bank_id = sb_bank_id
        self.connector_type = connector_type
        self.reason = reason
        super().__init__(
            get_message("PLATFORM_SB_CONNECTOR_UNAVAILABLE_SB_BANK", sb_bank_id=sb_bank_id, connector_type=connector_type, reason=reason)
        )


class SBConnectorAuthError(SBConnectorUnavailableError):
    """Authentication/credential failure when contacting the SB."""

    def __init__(self, sb_bank_id: str, reason: str) -> None:
        super().__init__(sb_bank_id, "AUTH", reason)


class SBSubmissionRejectedError(RuntimeError):
    """SB accepted the connection but rejected the lot submission."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(get_message("PLATFORM_SB_REJECTED_SUBMISSION", error_code=error_code, message=message))
