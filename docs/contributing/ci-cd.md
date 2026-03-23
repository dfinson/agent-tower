# CI/CD

CodePlane uses GitHub Actions for continuous integration and releases.

## CI Pipeline

Triggered on every push to `main` and every pull request.

### Jobs

The CI pipeline runs three parallel jobs:

#### Backend

1. Install dependencies (`uv sync`)
2. **Lint** — `ruff check backend/`
3. **Format check** — `ruff format --check backend/`
4. **Type check** — `mypy backend/`
5. **Test** — `pytest` with 70% coverage threshold
6. Upload coverage to Codecov (on main branch push)

#### Frontend

1. Install dependencies (`npm ci`)
2. **Lint** — `eslint src/`
3. **Type check** — `tsc --noEmit`
4. **Test** — `vitest` with coverage
5. Upload coverage to Codecov (on main branch push)

#### E2E (depends on Backend + Frontend passing)

1. Install all dependencies
2. Build frontend
3. Install Playwright + Chromium
4. Run Playwright E2E tests
5. Upload test report on failure (14-day retention)

### Concurrency

CI uses concurrency groups per branch/PR, cancelling in-progress runs when new commits are pushed.

## Releases

Releases are triggered by pushing a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow:

1. Installs all dependencies
2. Builds the frontend
3. Builds the Python package (`uv build`)
4. Creates a GitHub Release with auto-generated release notes
5. Attaches the built distribution files

## Pull Request Template

Every PR should include:

- **What** — Brief description of the change
- **Why** — Motivation and context
- **How** — Implementation approach
- **Testing** — How the change was tested
- **Checklist** — Lint, type check, and test confirmation
