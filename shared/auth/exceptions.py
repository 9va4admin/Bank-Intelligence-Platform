class AccessDeniedError(PermissionError):
    """Raised when a user lacks a required permission."""


class InsufficientZoneScopeError(PermissionError):
    """Raised when ops_reviewer attempts to access a clearing zone outside their scope."""


class BankIsolationError(PermissionError):
    """Raised when a user attempts to access data belonging to a different bank."""


class EngagementExpiredError(PermissionError):
    """Raised when an RBI examiner's time-limited engagement has expired."""
