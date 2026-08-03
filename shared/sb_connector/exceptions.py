"""Exceptions for the shared/sb_connector adapter layer."""


class SBConnectorUnavailableError(RuntimeError):
    """SB connector cannot reach the upstream Sponsor Bank."""

    def __init__(self, sb_bank_id: str, connector_type: str, reason: str) -> None:
        self.sb_bank_id = sb_bank_id
        self.connector_type = connector_type
        self.reason = reason
        super().__init__(
            f"SB connector unavailable — sb_bank_id={sb_bank_id} "
            f"connector={connector_type}: {reason}"
        )


class SBConnectorAuthError(SBConnectorUnavailableError):
    """Authentication/credential failure when contacting the SB."""

    def __init__(self, sb_bank_id: str, reason: str) -> None:
        super().__init__(sb_bank_id, "AUTH", reason)


class SBSubmissionRejectedError(RuntimeError):
    """SB accepted the connection but rejected the lot submission."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(f"SB rejected submission [{error_code}]: {message}")
