class EventBusUnavailableError(RuntimeError):
    """Raised when Kafka is unreachable or a produce/consume call fails."""


class UnknownSchemaVersionError(ValueError):
    """Raised by a consumer when an event envelope carries an unrecognised schema_version."""
