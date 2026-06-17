class ImmudbUnavailableError(RuntimeError):
    """Raised when immudb is unreachable or returns an unexpected error."""


class ImmudbVerificationError(RuntimeError):
    """Raised when a verified_get call returns verified=False (tamper detected)."""
