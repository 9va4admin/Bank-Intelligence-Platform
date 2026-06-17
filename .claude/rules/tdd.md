# Test-Driven Development Rules (Red → Green → Refactor)

## The Absolute Sequence — No Exceptions

```
STEP 1 — Write the test (it must FAIL)
  Create tests/path/to/test_<module>.py
  Run: pytest tests/path/to/test_<module>.py
  CONFIRM: at least one test shows FAILED or ERROR in red output
  If ALL tests pass at this point → you wrote tests for code that already exists.
  That is not TDD. Stop. Delete the implementation. Start over.

STEP 2 — Write the minimum implementation to make it pass (GREEN)
  Create or edit the implementation file
  Run: pytest tests/path/to/test_<module>.py
  CONFIRM: all tests show PASSED in green output

STEP 3 — Refactor (CLEAN)
  Clean up code without changing behaviour
  Run: pytest tests/path/to/test_<module>.py
  CONFIRM: still all green after refactor

STEP 4 — Commit
  Commit BOTH test and implementation together in one commit
  Commit message must include test coverage count:
    feat(shared/audit): immudb client with write and verify — 14 tests, 100% coverage
```

---

## What This Means for Claude Code (AI Sessions)

Claude MUST follow this sequence for every new file:

```
1. Write test file → Run pytest → Confirm RED → (only then proceed)
2. Write implementation → Run pytest → Confirm GREEN → (only then commit)
3. Never write implementation first and tests after
4. Never commit without running pytest and showing output in the session
5. Never claim "tests pass" without running them — show the actual output
```

The pre-commit hook (Check 9) enforces pairing at commit time.
But RED-first is enforced by Claude's session behaviour — the hook cannot see order within a session.

---

## Test File Naming and Location

```
Implementation file               → Test file (mandatory)
─────────────────────────────────────────────────────────
shared/audit/immudb_client.py     → tests/shared/audit/test_immudb_client.py
shared/auth/rbac.py               → tests/shared/auth/test_rbac.py
shared/config/config_service.py   → tests/shared/config/test_config_service.py
modules/cts/vaults/sig_vault.py   → tests/modules/cts/vaults/test_sig_vault.py
modules/cts/workflows/cheque*.py  → tests/modules/cts/workflows/test_cheque*.py
modules/ej/parser/llm_parser.py   → tests/modules/ej/parser/test_llm_parser.py
apps/api/routers/cts.py           → tests/apps/api/routers/test_cts.py
edge/ej-agent/main.go             → edge/ej-agent/main_test.go  (Go convention)
```

Rule: test path mirrors implementation path exactly, with `tests/` prefix and `test_` file prefix.

---

## Coverage Minimums (Enforced by CI)

| Area | Minimum Coverage | Rationale |
|---|---|---|
| `modules/cts/workflows/activities/` | 95% | IET critical path — every branch must be tested |
| `modules/cts/vaults/` | 95% | Vault miss routing is a safety invariant |
| `modules/cts/workflows/` | 95% | Temporal workflow logic — exactly-once |
| `shared/config/` | 90% | Every service depends on this |
| `shared/auth/` | 90% | RBAC bypass = security incident |
| `shared/audit/` | 90% | Audit trail loss = compliance failure |
| `modules/ej/` | 85% | LLM paths have inherent variance |
| `apps/api/routers/` | 80% | Integration-tested separately |
| Overall project | 80% | Enforced by `pytest --cov-fail-under=80` in CI |

---

## Mandatory Test Scenarios Per Component Type

### Every Temporal Activity
```
[ ] Happy path — returns expected result
[ ] External service unavailable — degrades gracefully (never crashes workflow)
[ ] Timeout — activity raises TimeoutError correctly
[ ] Retry path — idempotent on second call with same input
[ ] IET boundary — if applicable, test at T-31s and T-29s
```

### Every Vault Operation (CTS signature vault, PPS vault)
```
[ ] Cache hit — does not call Redis
[ ] Cache miss — calls Redis, stores result
[ ] Vault miss (key not found) — routes to HUMAN_REVIEW, never AUTO_RETURN
[ ] Vault stale/error — routes to HUMAN_REVIEW, never AUTO_RETURN
[ ] Correct hashed key format — never raw account number
```

### Every Config Service Call
```
[ ] Value present — returns correct type (float not str)
[ ] Value absent — raises ConfigKeyNotFoundError
[ ] Cache hit — does not call DB
[ ] OPA unavailable — raises OPAUnavailableError (caller tests HUMAN_REVIEW default)
```

### Every API Route
```
[ ] Happy path — correct response schema
[ ] Unauthenticated — returns 401
[ ] Wrong role — returns 403
[ ] Invalid input — returns 422 with error_code
[ ] Rate limit exceeded — returns 429
```

### Every AI Activity
```
[ ] Model returns high-confidence result — proceeds to next step
[ ] Model returns low-confidence result — routes to human review
[ ] Model unavailable (vLLM down) — degrades gracefully
[ ] SHAP values computed and present in result
[ ] No hardcoded threshold — config_service.get() is called
```

---

## What a Failing Test Output Must Look Like (RED confirmation)

```
$ pytest tests/shared/audit/test_immudb_client.py -v

FAILED tests/shared/audit/test_immudb_client.py::test_write_event_calls_immudb
  ModuleNotFoundError: No module named 'shared.audit.immudb_client'
  — OR —
  ImportError: cannot import name 'ImmudbClient'
  — OR —
  AssertionError: Expected call not made

1 failed, 0 passed in 0.03s
```

This output is the proof that TDD was followed. Claude must paste this output in the session before writing any implementation.

---

## What Is NOT Acceptable

```
✗ Writing implementation then writing tests to match it — that is test-after, not TDD
✗ Writing tests that only test the happy path — must test error paths too
✗ Mocking everything so tests never touch real logic — mocks only for external I/O
✗ Skipping the RED step because "obviously it will fail" — run it, show the output
✗ Committing a test file with all tests marked @pytest.mark.skip
✗ Writing assert True or assert 1 == 1 as placeholder tests
✗ Coverage via __init__.py imports — every line of logic must have a test assertion
```

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Test file must exist alongside implementation | pre-commit Check 9: new `.py` outside `tests/` requires paired `tests/.*/test_*.py` | Commit blocked |
| Coverage minimums per module | CI `pytest --cov-fail-under` per module (separate pytest run per coverage tier) | PR merge blocked |
| CTS activities at 95% | CI `test-cts-critical` stage (separate from main test run) | PR merge blocked |
| RED step confirmed before implementation | Claude session rule: must run pytest and show FAILED output before writing impl | Session-time enforcement |
| No skip markers in committed tests | pre-commit Check 10: `@pytest.mark.skip` in staged test files = blocked | Commit blocked |
| Tests mirror implementation path | CI lint: `infra/ci-checks/check-test-pairing.sh` verifies 1:1 mapping | PR merge blocked |
