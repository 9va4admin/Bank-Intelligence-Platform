# /write-tests

Generate pytest tests for a specified module or file.

## Usage
/write-tests [file_path]

## What This Does
1. Reads the target file
2. Identifies all functions/methods needing tests
3. For CTS activities: generates IET boundary tests, vault miss tests, graceful degradation tests
4. For EJ activities: generates OEM fingerprint tests, LLM parse validation tests
5. For API routes: generates auth, RBAC, and response schema tests
6. Places test file at `tests/{mirror_of_source_path}/test_{filename}.py`

## Invokes
Uses `test-writer` agent.

## Coverage Target
- CTS workflow activities: 95%+
- Everything else: 80%+
