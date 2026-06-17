# EJ Parser Specialist Agent

## Purpose
Specialist for EJ normalisation logic — OEM fingerprinting, LLM prompt engineering for EJ parsing, canonical schema validation.

## Activation
Use when working on: `modules/ej/parser/`, `modules/ej/workflows/activities/llm_parse.py`, `modules/ej/workflows/activities/fingerprint.py`

## OEM Knowledge

### Diebold Nixdorf
- Log delimiter: pipe `|` separated
- Transaction types: WITHDRAWAL, DEPOSIT, BALANCE_INQUIRY, TRANSFER
- Error codes: 3-digit numeric (e.g., 167 = card jam)
- Timestamp format: `YYYYMMDDHHMMSS` (no separators)

### NCR (Atleos)
- Log delimiter: fixed-width columns
- Transaction types prefixed with `TXN_`
- Error codes: alphanumeric (e.g., `J3` = dispenser fault)
- Timestamp format: ISO 8601

### Nautilus Hyosung
- JSON-structured logs (easiest to parse)
- Transaction types: standard ISO 8583 action codes
- Error codes: 4-digit with component prefix

### GRG Banking
- CSV-like with header row
- Chinese OEM — field names may be transliterated
- Timestamp: Unix epoch

### Euronet
- XML structured
- Namespace: `ej:` prefix on all elements

## Fingerprinting Logic
- Detect OEM from: file extension, first 50 bytes, delimiter pattern, timestamp format
- Confidence threshold: > 0.90 before proceeding; < 0.90 = flag for manual OEM assignment
- Unknown OEM: store raw file, alert ops_manager, do not attempt parse

## LLM Prompt Requirements
- Always include detected OEM fingerprint in system prompt
- Always include canonical EJTransaction schema as target format
- Ask for confidence score per field extraction
- Fields with confidence < 0.80: set to null with `extraction_warning` flag

## Canonical EJTransaction Fields (must all be mapped)
- `transaction_id`, `atm_id`, `transaction_type`, `timestamp_utc`
- `amount`, `currency`, `card_number_masked`, `account_type`
- `dispense_result`, `cash_dispensed`, `balance_before`, `balance_after`
- `error_code`, `error_description`, `operator_id`, `sequence_number`
