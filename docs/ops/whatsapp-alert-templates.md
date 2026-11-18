# WhatsApp alert templates: what to submit to Meta

WhatsApp Business only sends **pre-approved templates**. ASTRA's alert messages use the two below; submit them in the bank's WhatsApp Business Manager (category **Utility**, language **English**). Approval is Meta's decision and normally takes minutes to a couple of days.

The template names and the order of the parameters are fixed by ASTRA (`shared/notifications/whatsapp_channel.py`); the wording below is what Meta needs to see. Meta rejects a template that starts or ends with a parameter, so each has fixed text on both sides.

## astra_platform_health_alert

Body:

```
ASTRA alert ({{1}}) on {{2}}: {{3}} Please open ASTRA to acknowledge.
```

| Parameter | Meaning | Example |
|---|---|---|
| {{1}} | severity | P0 |
| {{2}} | component | redis |
| {{3}} | what happened (one line, cut to the configured length) | redis is not responding (3 failed checks in a row) |

## astra_platform_health_recovered

Body:

```
ASTRA: {{1}} is back to normal after {{2}}. {{3}} No action is needed.
```

| Parameter | Meaning | Example |
|---|---|---|
| {{1}} | component | redis |
| {{2}} | how long it was down | 4m |
| {{3}} | summary | redis is responding again after 4m down. |

## Turning it on

1. Get both templates approved (above).
2. Deployment settings: `WHATSAPP_API_URL`, `WHATSAPP_PHONE_NUMBER_ID`, and the secret `whatsapp.access_token` (Vault in production).
3. In the Admin console (Layer 3): `alerts.whatsapp_recipients` (phone numbers in international format) and, if wanted, `alerts.whatsapp_min_priority` (default P0 only).
4. Each recipient must have agreed to receive WhatsApp messages; record that consent before adding the number.
5. Send a test: `python scripts/send_test_alert.py` covers email; for WhatsApp, raise a test alert from the Go-Live checklist once that screen exists, or use the alert test endpoint planned for Phase 2.

ASTRA cleans every parameter before sending (one line, no tabs or runs of spaces, cut to `alerting.message_max_chars`), because Meta rejects parameters that contain line breaks.
