# /review-workflow

Review a Temporal workflow file for ASTRA compliance.

## Usage
/review-workflow [file_path]

## What This Does
1. Reads the specified workflow file
2. Checks IET safety (for CTS workflows)
3. Verifies exactly-once guarantees (idempotent workflow IDs)
4. Confirms all terminal states emit audit events
5. Validates graceful degradation paths exist
6. Reports CRITICAL / HIGH / MEDIUM findings

## Invokes
Uses `cts-workflow-reviewer` agent for CTS workflows, general review for EJ/Platform workflows.
