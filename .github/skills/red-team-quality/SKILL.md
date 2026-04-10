---
name: red-team-quality
description: >
  Comprehensive code quality and testing red-team skill. Use when asked to audit
  test coverage, find quality gaps, harden the codebase, or ensure tests are
  comprehensive and passing. Synthesized from Superpowers (145k★), ECC TDD/testing
  skills (149k★), and ECC verification-loop/security-review patterns.
---

# Red-Team Quality & Testing Skill

Comprehensive codebase quality enforcement synthesized from the most battle-tested
open-source agent skills (Superpowers, Everything Claude Code).

## When to Activate

- Auditing test coverage and finding untested code
- Red-teaming: adversarially finding bugs, edge cases, missing tests
- Pre-PR verification loops
- Hardening a codebase for production readiness

## Philosophy (from Superpowers)

- **Test-Driven Development** — Write tests first, always
- **Systematic over ad-hoc** — Process over guessing
- **Complexity reduction** — Simplicity as primary goal
- **Evidence over claims** — Verify before declaring success
- **YAGNI** — Don't add speculative features or tests for impossible scenarios

## Verification Loop (from ECC)

Run these phases in order after any significant change:

### Phase 1: Build Verification
```bash
# Backend
uv run python -c "import backend"
# Frontend
cd frontend && npm run build
```
If build fails, STOP and fix before continuing.

### Phase 2: Type Check
```bash
# Backend
uv run mypy backend/
# Frontend
cd frontend && npm run typecheck
```

### Phase 3: Lint Check
```bash
# Backend
uv run ruff check backend/
uv run ruff format --check backend/
# Frontend
cd frontend && npm run lint
```

### Phase 4: Test Suite
```bash
# Backend with coverage
uv run pytest --cov=backend --cov-report=term-missing --cov-fail-under=70
# Frontend
cd frontend && npm run test:coverage
```

### Phase 5: Security Scan
- No hardcoded secrets (API keys, tokens, passwords)
- All user inputs validated with schemas
- SQL queries parameterized (SQLAlchemy handles this)
- Error messages don't leak internals
- No sensitive data in logs

### Phase 6: Report
```
VERIFICATION REPORT
==================
Build:     [PASS/FAIL]
Types:     [PASS/FAIL]
Lint:      [PASS/FAIL]
Tests:     [PASS/FAIL] (X/Y passed, Z% coverage)
Security:  [PASS/FAIL]
Overall:   [READY/NOT READY]
```

## Red-Team Testing Checklist

### Coverage Gaps to Probe
For each untested service/module:
1. What are the happy-path behaviors? Write tests.
2. What are the error paths? Write tests.
3. What are the edge cases (empty input, None, boundary values)? Write tests.
4. What happens under concurrent access? Consider stress tests.

### Test Quality Rules
- **Test behavior, not implementation** — assert on outputs and side effects
- **One assertion focus per test** — test one logical thing
- **Descriptive names** — `test_job_transition_from_running_to_completed_updates_metrics`
- **AAA pattern** — Arrange, Act, Assert
- **Independent tests** — no shared mutable state between tests
- **Mock at boundaries only** — mock external services, not internal logic
- **Don't test the framework** — trust SQLAlchemy/FastAPI/React to work

### Security Testing (from ECC Security Review)
- Test authentication: unauthenticated requests return 401
- Test authorization: wrong-role requests return 403
- Test input validation: malformed data returns 400
- Test rate limiting if applicable
- Test that error responses don't leak stack traces

## Python Testing Patterns (for this repo)

### Fixture Pattern
```python
@pytest.fixture
def make_job():
    def _make(**overrides):
        defaults = {"id": "test-id", "status": "queued", ...}
        defaults.update(overrides)
        return Job(**defaults)
    return _make
```

### Async Service Test Pattern
```python
async def test_service_happy_path(service, mock_repo):
    mock_repo.get.return_value = some_object
    result = await service.do_thing("id")
    assert result.status == "done"
    mock_repo.get.assert_called_once_with("id")
```

### Integration Test Pattern
```python
async def test_api_endpoint(client):
    response = await client.post("/api/resource", json={"key": "value"})
    assert response.status_code == 201
    data = response.json()
    assert data["key"] == "value"
```

## Target Metrics
- Backend coverage: ≥70% (current CI threshold)
- All existing tests: passing (0 failures)
- Type checking: clean (mypy strict)
- Lint: clean (ruff)
- No skipped/disabled tests without documented reason
