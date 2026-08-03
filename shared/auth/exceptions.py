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


# Session / token exceptions

class SessionExpiredError(Exception):
    """The ASTRA session token has passed its expiry — client must re-authenticate."""


class InvalidSessionError(Exception):
    """Session token failed signature, issuer, structure, or algorithm validation."""


class CSRFValidationError(Exception):
    """CSRF token missing or does not match the session's bound token."""


class MFARequiredError(Exception):
    """Password verified but the session is not yet MFA-authenticated (step-up needed)."""


class MFANotEnrolledError(Exception):
    """User has no TOTP enrolled — enrolment must complete before a full session issues."""
