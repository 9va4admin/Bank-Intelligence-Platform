class VaultUnavailableError(RuntimeError):
    """Raised when HashiCorp Vault cannot be reached or returns an error."""


class ConfigKeyNotFoundError(KeyError):
    """Raised when a config key does not exist for this bank_id."""


class OPAUnavailableError(RuntimeError):
    """Raised when OPA decision API cannot be reached."""
