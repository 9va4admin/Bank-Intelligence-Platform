---
name: ej-oem-parse
description: Diagnose EJ parsing failures, unknown OEM fingerprints, and low-confidence field extractions. Covers OEM detection, LLM prompt construction, and canonical schema validation.
---

# Skill: Debug or Build an EJ OEM Parser

## When to Use
User says: "EJ parse failed", "unknown OEM", "low confidence extraction", "new ATM OEM to support", or provides a raw EJ log excerpt.

## OEM Detection — Quick Reference

| OEM | File Extension | Delimiter | Timestamp Format | Identifier Pattern |
|---|---|---|---|---|
| Diebold Nixdorf | `.ej`, `.log` | pipe `\|` | `YYYYMMDDHHMMSS` | `DIEBOLD` or `DN` in header |
| NCR / Atleos | `.ejl`, `.tnl` | fixed-width | ISO 8601 | `NCR` or `TN` prefix on types |
| Nautilus Hyosung | `.json`, `.ej` | JSON | ISO 8601 | `{"oem":"NH"` in first 100 bytes |
| GRG Banking | `.csv`, `.ej` | comma | Unix epoch | Chinese field names, `GRG` header |
| Euronet | `.xml` | XML | ISO 8601 | `<ej:` namespace prefix |
| Unknown | any | — | — | Confidence < 0.90 → flag, do not parse |

## Diagnosing a Parse Failure

### Step 1 — Check Fingerprint Confidence
```python
# In EJRawLog record:
fingerprint_result = {
    "oem": "diebold",
    "confidence": 0.94,      # must be > 0.90 to proceed
    "detected_by": "header_pattern"
}
# If confidence < 0.90: STOP — route to manual OEM assignment
# Do NOT attempt LLM parse on uncertain OEM — garbage in, garbage out
```

### Step 2 — Check LLM Extraction Confidence
Each field in EJCanonicalRecord has an extraction confidence:
```json
{
  "transaction_id": {"value": "TXN20240617001", "confidence": 0.98},
  "amount": {"value": 5000, "confidence": 0.72},   ← below 0.80 threshold
  "dispense_result": {"value": null, "confidence": 0.0, "extraction_warning": "field_not_found"}
}
```
Fields with confidence < 0.80: set to null, flag record for human review.
Overall record: if > 3 fields below threshold → reject entire record, store as PARSE_FAILED.

### Step 3 — Construct Correct LLM Prompt
The prompt MUST include all three components:

```python
system_prompt = f"""
You are parsing an ATM Electronic Journal log.
OEM: {fingerprint.oem}  (confidence: {fingerprint.confidence})
Delimiter: {oem_config.delimiter}
Timestamp format: {oem_config.timestamp_format}

Extract the following canonical fields. For each field, provide a confidence score 0.0-1.0.
If a field cannot be found or is ambiguous, set value to null and confidence to 0.0.

Target schema:
{json.dumps(EJTransaction.model_json_schema(), indent=2)}
"""

user_prompt = f"""
Raw log excerpt (first 2000 characters):
{raw_log[:2000]}

Respond in JSON matching the target schema exactly. Include confidence scores.
"""
```

### Step 4 — Adding Support for a New OEM
1. Add OEM to fingerprint detection in `modules/ej/workflows/activities/fingerprint.py`
2. Add OEM config to `ej-parser-specialist` agent's OEM Knowledge section
3. Add at least 3 sample log files to `tests/ej/fixtures/oem/{oem_name}/`
4. Write unit tests covering: fingerprint detection, full parse, edge cases (empty fields, error codes)
5. Validate extraction accuracy > 98% on sample files before merging
6. Update `ej-oem-parse` skill's OEM Detection table

### Step 5 — Canonical Schema Validation Failures
If `validate_schema` activity fails after LLM parse:
- `transaction_id`: must be non-null (reject if missing)
- `atm_id`: must match known ATM in `ej.atms` table (reject if not found)
- `timestamp_utc`: must be valid ISO 8601, must be within last 90 days
- `transaction_type`: must be in allowed enum values
- `amount`: if present, must be positive integer (paise/cents)

Schema validation failure → store as `PARSE_FAILED` with error detail → alert ops_manager
