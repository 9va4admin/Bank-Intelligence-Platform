"""The shipped starting list of risks to alerting itself. A bank gets these when it seeds its register, then gives each an owner and keeps them current.
Each entry is (key, category, likelihood 1-5, impact 1-5); the title and description are messages ALERT_RISK_<KEY>_TITLE and ALERT_RISK_<KEY>_DESC in the message registry."""

RISK_TEMPLATE: list[tuple[str, str, int, int]] = [
    ("EMAIL_OUTAGE", "vendor", 3, 4),
    ("WHATSAPP_TEMPLATE", "vendor", 3, 3),
    ("ONCALL_GAP", "process", 3, 5),
    ("AUDIT_DOWN", "security", 2, 5),
    ("SILENCE_LEFT_ON", "process", 3, 4),
    ("ESCALATION_NOBODY", "process", 2, 5),
    ("PUBLIC_MAIL", "security", 3, 3),
    ("ALERT_FATIGUE", "process", 4, 3),
    ("MONITOR_DEAD", "availability", 2, 5),
    ("CONTACT_STALE", "process", 3, 3),
]
