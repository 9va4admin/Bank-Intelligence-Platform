"""Send one test alert mail using exactly the settings the worker uses, and say plainly what is wrong if it fails.

    SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_SECURITY=starttls SMTP_USERNAME=you@gmail.com \
    ASTRA_SECRET_SMTP_PASSWORD=<gmail app password> BANK_ID=kbl ASTRA_SECRETS_BACKEND=env \
    python scripts/send_test_alert.py --to you@gmail.com

Without --to the recipients configured in alerts.email_recipients are used. Exit code 0 = the mail server accepted the message.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config.config_service import config_service  # noqa: E402
from shared.notifications.email_channel import EmailChannel  # noqa: E402
from shared.notifications.factory import read_smtp_settings  # noqa: E402


async def main(to: str | None) -> int:
    await config_service.initialise()
    bank_id = config_service.bank_id
    try:
        s = await read_smtp_settings(config_service)
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 2
    if s is None:
        print("FAILED: no mail server is configured. Set SMTP_HOST (and SMTP_PORT, SMTP_SECURITY, SMTP_USERNAME, the smtp.password secret).")
        return 2
    print(f"Mail server {s.host}:{s.port}, security {s.security}, login {'yes' if s.username else 'no'}, from {s.from_address}")

    recipients = [to] if to else []
    if not recipients:
        try:
            raw = await config_service.get("alerts.email_recipients")
            recipients = [x.strip() for x in str(raw).strip("[]").replace('"', "").split(",") if x.strip()]
        except Exception:  # noqa: BLE001
            recipients = []
    if not recipients:
        print("FAILED: no recipient. Pass --to, or set alerts.email_recipients.")
        return 2

    channel = EmailChannel(s.host, s.port, s.from_address, bank_id, username=s.username, password=s.password, security=s.security, ca_file=s.ca_file)
    try:
        channel.connect()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)
        hint = ""
        if "CERTIFICATE" in reason.upper():
            hint = " The server's certificate is not trusted; set SMTP_CA_FILE to the bank's CA certificate."
        elif "535" in reason or "authentication" in reason.lower():
            hint = " The login was refused; for Gmail use an app password, not the account password."
        print(f"FAILED: could not connect to the mail server: {reason}.{hint}")
        return 1

    for r in recipients:
        req = SimpleNamespace(recipient=r, template_id="PLATFORM_HEALTH_ALERT", notification_id="selftest",
                              context={"bank_id": bank_id, "severity": "INFO", "component": "self-test", "event_type": "TEST_ALERT",
                                       "message": "This is a test alert from ASTRA. If you can read it, alert email works."})
        try:
            await channel.send(req)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED: the server did not accept the message for {r}: {exc}")
            return 1
        print(f"sent to {r}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", help="recipient address (default: alerts.email_recipients)")
    sys.exit(asyncio.run(main(ap.parse_args().to)))
