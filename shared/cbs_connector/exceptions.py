from shared.messages import get_message
class CBSUnavailableError(RuntimeError):
    """Raised when the Core Banking System is unreachable or returns an unexpected error."""


class AccountNotFoundError(KeyError):
    """Raised when an account number does not exist in the CBS."""

    def __init__(self, account_number: str) -> None:
        # Never log the full account number — log only last 4 digits
        super().__init__(get_message("PLATFORM_ACCOUNT_ENDING_NOT_FOUND_IN", account_number=account_number[-4:]))
        self.account_last4 = account_number[-4:]
