class AccessDeniedError(PermissionError):
    """Raised when a user lacks a required permission."""


class InsufficientZoneScopeError(PermissionError):
    """Raised when ops_reviewer attempts to access a clearing zone outside their scope."""


class BankIsolationError(PermissionError):
    """Raised when a user attempts to access data belonging to a different bank of the same type."""


class EngagementExpiredError(PermissionError):
    """Raised when an RBI examiner's time-limited engagement has expired."""


class TenantIsolationError(PermissionError):
    """
    Raised when a user crosses the SB↔SMB tenant boundary.
    SMB users cannot access SB data or other SMBs' data — ever.
    SB users cannot impersonate SMB users.
    """


class PermissionLevelError(PermissionError):
    """
    Raised when a user's permission level (ADMIN/EDIT/READ_ONLY) is
    insufficient for the requested operation within their own tenant.
    """


# Auth connector exceptions

class AuthenticationError(Exception):
    """Wrong credentials or inactive account — safe message surfaced to caller."""


class AccountLockedError(AuthenticationError):
    """Account is locked due to too many failed attempts."""


class AuthorizationError(Exception):
    """User authenticated but has no mapped ASTRA role (e.g. AD group not in group_role_map)."""


class LDAPServerUnreachableError(Exception):
    """LDAP/AD server could not be contacted (socket error, TLS failure)."""


class AuthConnectorConfigError(Exception):
    """Invalid or missing auth connector configuration (raised at factory build time)."""
