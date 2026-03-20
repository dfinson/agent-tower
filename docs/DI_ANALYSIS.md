# Dependency Injection Library Analysis for CodePlane

## Executive Summary

CodePlane already uses a **well-structured manual DI approach** combining FastAPI's
built-in `Depends()`, constructor injection, and `app.state` singletons. This
document evaluates whether adopting a formal DI library would bring meaningful
improvements and, if so, which library best fits the project.

**Verdict:** Adopting a DI library is **not recommended at this time**. The
codebase is well-factored, the existing patterns are idiomatic FastAPI, and the
marginal benefits of a library do not justify the migration cost. Targeted
improvements to the existing patterns (documented in §6) would deliver most of the
same benefits at a fraction of the effort.

---

## Table of Contents

1. [Current State of Dependency Injection](#1-current-state-of-dependency-injection)
2. [Candidate Libraries](#2-candidate-libraries)
3. [Viability Assessment](#3-viability-assessment)
4. [Pros of Adopting a DI Library](#4-pros-of-adopting-a-di-library)
5. [Cons of Adopting a DI Library](#5-cons-of-adopting-a-di-library)
6. [Recommended Improvements Without a Library](#6-recommended-improvements-without-a-library)
7. [When to Reconsider](#7-when-to-reconsider)
8. [Conclusion](#8-conclusion)

---

## 1. Current State of Dependency Injection

CodePlane uses a **hybrid manual DI strategy** across three distinct patterns:

### 1.1 Pattern A: Lifespan-Wired Singletons (`app.state`)

Singleton services are instantiated once at startup in `backend/lifespan.py`
(`_wire_core_services`) and stored on `app.state`. Route handlers access them via
`request.app.state.<service>`.

```
lifespan.py → _wire_core_services(session_factory, event_bus, config)
  ├─ ApprovalService(session_factory)
  ├─ AdapterRegistry(approval_service, event_bus)
  ├─ GitService(config)
  ├─ DiffService(git_service, event_bus)
  ├─ PlatformRegistry(config.platforms)
  ├─ MergeService(git_service, event_bus, session_factory, ...)
  ├─ UtilitySessionService(model, max_pool_fn)
  ├─ SummarizationService(session_factory, utility_session)
  └─ RuntimeService(10 dependencies)
```

**14 services** are stored on `app.state`, accessed via `request.app.state.*`
in **30+ call sites** across route handlers.

### 1.2 Pattern B: FastAPI `Depends()` (Per-Request)

Per-request dependencies use FastAPI's `Depends()` mechanism. The database
session is the primary example:

```python
# backend/api/deps.py — placeholder
async def get_db_session() -> AsyncSession:
    raise NotImplementedError("Session factory not wired")

# Overridden at startup in lifespan.py
app.dependency_overrides[get_db_session] = _session_dep
```

Route-specific dependency functions compose per-request services:

```python
# backend/api/jobs.py
def _get_job_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    config: Annotated[CPLConfig, Depends(_get_config)],
    request: Request,
) -> JobService:
    return JobService.from_session(session, config, ...)
```

### 1.3 Pattern C: Factory Classmethods (`from_session`)

Services that need a database session provide a `from_session` classmethod that
encapsulates repository construction:

```python
# backend/services/job_service.py
@classmethod
def from_session(cls, session, config, *, git_service=None, naming_service=None):
    return cls(
        job_repo=JobRepository(session),
        event_repo=EventRepository(session),
        git_service=git_service or GitService(config),
        config=config,
        naming_service=naming_service,
    )
```

This keeps repository imports inside the service layer — route handlers never
import repository classes directly.

### 1.4 Additional Pattern: Module-Level State (Terminal)

One module (`backend/api/terminal.py`) uses module-level mutable state set
during lifespan startup. This is isolated and does not represent a broader
pattern.

### 1.5 Dependency Graph Summary

```
┌─ lifespan.py (startup orchestration)
│
├─ Database Layer
│  ├─ create_engine()             → AsyncEngine
│  └─ create_session_factory()    → async_sessionmaker
│
├─ Event Infrastructure
│  ├─ EventBus()                  (stateless pub/sub)
│  └─ SSEManager()                (connection registry)
│
├─ Core Services (singletons on app.state)
│  ├─ ApprovalService ← session_factory
│  ├─ AdapterRegistry ← approval_service, event_bus
│  ├─ GitService ← config
│  ├─ DiffService ← git_service, event_bus
│  ├─ PlatformRegistry ← config.platforms
│  ├─ MergeService ← git_service, event_bus, session_factory, config, ...
│  ├─ UtilitySessionService ← config.runtime.utility_model
│  ├─ SummarizationService ← session_factory, utility_session
│  └─ RuntimeService ← (10 dependencies — central orchestrator)
│
├─ Optional Services
│  ├─ TerminalService ← config values
│  ├─ VoiceService (lazy model loading)
│  ├─ RetentionService ← session_factory, config
│  └─ MCPServer ← session_factory, runtime, approval
│
└─ Per-Request Services (created by route handlers via Depends)
   ├─ AsyncSession ← Depends(get_db_session)
   ├─ JobService ← from_session(session, config, ...)
   └─ ArtifactService ← from_session(session)
```

### 1.6 Testing Patterns

- **Integration tests**: Full HTTP client against in-memory SQLite; services
  stored on `app.state` as `AsyncMock` objects; session dependency overridden via
  `app.dependency_overrides`.
- **Unit tests**: Direct constructor injection with real lightweight services
  or mocks; `monkeypatch` for config and module-level state.
- **Pain points**: Duplicated DB setup boilerplate across 8+ test files; mixed
  use of `monkeypatch` vs `dependency_overrides`; verbose mock construction.

---

## 2. Candidate Libraries

Four libraries were evaluated for fit with CodePlane's Python 3.11+/FastAPI/async
stack:

### 2.1 dependency-injector

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Very mature, widely used, well-documented |
| **Approach** | Declarative containers with typed providers (Factory, Singleton, Coroutine) |
| **FastAPI support** | Excellent — first-class `@inject` + `Depends()` integration |
| **Async** | Full async/await support |
| **Testing** | Provider `.override()` for clean test isolation |
| **Typing** | mypy plugin available |
| **Overhead** | Moderate boilerplate (container classes, provider declarations) |
| **Performance** | Cython-optimized resolution |

**How it would look in CodePlane:**

```python
# containers.py
class CoreContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    session_factory = providers.Dependency(instance_of=async_sessionmaker)
    event_bus = providers.Singleton(EventBus)
    approval_service = providers.Singleton(ApprovalService, session_factory=session_factory)
    adapter_registry = providers.Singleton(
        AdapterRegistry, approval_service=approval_service, event_bus=event_bus,
    )
    git_service = providers.Singleton(GitService, config=config)
    runtime_service = providers.Singleton(
        RuntimeService,
        session_factory=session_factory,
        event_bus=event_bus,
        adapter_registry=adapter_registry,
        # ... 7 more
    )
```

### 2.2 dishka

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Modern (2023+), growing community |
| **Approach** | Scoped providers (app / request / custom) with explicit finalization |
| **FastAPI support** | Official integration package |
| **Async** | Native async, no thread-pool fallbacks |
| **Testing** | Scope overrides, clean teardown |
| **Typing** | Designed for type-hint resolution |
| **Overhead** | Low boilerplate, functional-style provider definitions |
| **Performance** | Pure Python, fast resolution |

**How it would look in CodePlane:**

```python
# providers.py
from dishka import Provider, Scope, provide

class CoreProvider(Provider):
    @provide(scope=Scope.APP)
    def event_bus(self) -> EventBus:
        return EventBus()

    @provide(scope=Scope.APP)
    def approval_service(self, session_factory: async_sessionmaker) -> ApprovalService:
        return ApprovalService(session_factory=session_factory)

    @provide(scope=Scope.REQUEST)
    async def job_service(self, session: AsyncSession, config: CPLConfig) -> JobService:
        return JobService.from_session(session, config)
```

### 2.3 lagom

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Mid-tier, type-centered auto-wiring |
| **Approach** | Type-based container, auto-resolves constructor dependencies |
| **FastAPI support** | Community integration, not official |
| **Async** | Supported |
| **Overhead** | Minimal boilerplate |

### 2.4 python-inject

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Older, simple |
| **Approach** | Global configuration, service-locator style |
| **FastAPI support** | Weak |
| **Disqualifying** | Global mutable state; incompatible with CodePlane's test isolation patterns |

**python-inject and lagom are ruled out** — python-inject's global state is a
poor fit, and lagom's limited FastAPI integration and smaller ecosystem make it a
weak candidate when dependency-injector and dishka exist.

---

## 3. Viability Assessment

### 3.1 What a DI Library Would Replace

| Current Pattern | DI Library Equivalent | Migration Scope |
|----------------|----------------------|-----------------|
| `_wire_core_services()` in lifespan.py | Container/provider declarations | ~150 lines → container module |
| `app.state.*` access in routes | `@inject` decorator or `Depends()` | 30+ call sites in 8 route modules |
| `from_session()` classmethods | Request-scoped providers | 2 services (JobService, ArtifactService) |
| `Depends(get_db_session)` override | Session provider with scope | 1 placeholder + 1 override |
| Test `app.state` mocking | Provider `.override()` | 47 test files, ~200 mock sites |

### 3.2 Migration Effort Estimate

| Phase | Work | Estimate |
|-------|------|----------|
| Define container/providers | Declare all 14+ services | 1-2 days |
| Refactor lifespan.py | Replace `_wire_core_services` with container init | 0.5 day |
| Refactor route handlers | Replace `request.app.state.*` with injected params | 1-2 days |
| Refactor tests | Replace mock wiring with provider overrides | 2-3 days |
| Typing / CI fixes | Resolve mypy issues, fix broken tests | 1-2 days |
| **Total** | | **5-9 days** |

### 3.3 Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Tests break during migration | High | Incremental migration; run full suite after each module |
| Async lifecycle issues | Medium | Both dependency-injector and dishka support async well |
| Learning curve for contributors | Medium | Well-documented libraries reduce this |
| Library maintenance risk | Low | dependency-injector is mature; dishka is actively developed |
| Performance impact | Negligible | Resolution happens once at startup or per-request |

---

## 4. Pros of Adopting a DI Library

### 4.1 Centralized Dependency Graph

**Current:** The dependency graph is implicit — spread across `lifespan.py` (150
lines of manual wiring), route handler dependency functions, and `from_session()`
classmethods.

**With library:** A single container/provider module would declare the entire
graph in one place, making it immediately auditable.

### 4.2 Automatic Circular Dependency Detection

The current manual wiring silently allows circular dependencies that would only
surface at runtime. A DI container detects these at container construction time.

### 4.3 Cleaner Test Overrides

**Current test pattern (verbose):**
```python
application.state.runtime_service = mock_runtime_service
application.state.merge_service = mock_merge_service
application.state.approval_service = approval_service
# ... 10 more state assignments
# + monkeypatch for config in 5 modules
# + dependency_overrides for session
```

**With dependency-injector:**
```python
container.runtime_service.override(mock_runtime_service)
container.config.from_dict(test_config)
# All downstream dependencies automatically resolve to overrides
```

### 4.4 Scope Management

Request-scoped dependencies (sessions, per-request services) would be managed
declaratively rather than through the current `Depends()` + `from_session()`
combination. This eliminates the need for the `get_db_session` placeholder +
override pattern.

### 4.5 Self-Documenting Dependency Requirements

Constructor signatures already document what a service needs, but the container
makes the wiring between them explicit and statically verifiable.

---

## 5. Cons of Adopting a DI Library

### 5.1 Significant Migration Cost for Modest Gain

The codebase has **27 service files, 7 persistence files, 11 API files, and 47
test files**. Touching all of these for a DI migration is a large, high-risk
change that does not add user-facing value.

### 5.2 The Current Approach Already Works Well

- **Constructor injection** is used consistently in all service `__init__` methods
- **`lifespan.py`** is the single composition root (easy to find, easy to understand)
- **`from_session()` classmethods** cleanly encapsulate repository construction
- **`Depends()`** handles per-request dependencies idiomatically
- Tests can already mock any dependency via `app.state` assignment or `dependency_overrides`

The patterns are standard FastAPI — any Python/FastAPI developer joining the
project will immediately understand them.

### 5.3 Added Abstraction Layer

A DI library introduces its own concepts (containers, providers, scopes, wiring
decorators) that every contributor must learn. This overhead is justified in very
large projects with deep dependency graphs, but CodePlane's graph is moderate
(~14 singletons + 2 per-request services).

### 5.4 Typing Complexity

Both dependency-injector and dishka have their own typing systems that can
conflict with strict mypy configurations. CodePlane runs `mypy --strict`, which
may require additional type stubs or `# type: ignore` annotations.

### 5.5 Lock-In to Library Patterns

The current approach is framework-agnostic pure Python. A DI library would
couple the codebase to that library's decorator/container API, making future
framework changes harder.

### 5.6 RuntimeService Already Has 10 Dependencies

This is a design concern, not a DI concern. A DI library would make the 10
dependencies easier to wire but would mask the code smell. The real fix is to
decompose RuntimeService into smaller focused services — which is independent of
whether a DI library is used.

---

## 6. Recommended Improvements Without a Library

These targeted changes would resolve the existing pain points without the cost
of a full DI library migration:

### 6.1 Extract Shared Test Fixtures

**Problem:** Database setup code (engine + session factory + schema creation) is
duplicated across 8+ unit test files.

**Fix:** Create a shared `backend/tests/conftest.py` with reusable fixtures:

```python
# backend/tests/conftest.py
@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)

@pytest.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as sess:
        yield sess
```

### 6.2 Standardize Config Dependency

**Problem:** `load_config()` is called fresh on every request in routes,
and tests must monkeypatch it in 5+ modules separately.

**Fix:** Store config on `app.state` at startup (already done implicitly via
services that receive it) and create a single `Depends` function for it:

```python
# backend/api/deps.py
def get_config(request: Request) -> CPLConfig:
    return request.app.state.config

# In lifespan.py, add:
app.state.config = config
```

### 6.3 Move All Singleton Access to `Depends()` Functions

**Problem:** Route handlers access singletons via `request.app.state.*`
directly, which is untyped and not visible in function signatures.

**Fix:** Create typed dependency functions in `deps.py`:

```python
# backend/api/deps.py
def get_runtime_service(request: Request) -> RuntimeService:
    return request.app.state.runtime_service

def get_approval_service(request: Request) -> ApprovalService:
    return request.app.state.approval_service

# Usage in routes:
@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    runtime: Annotated[RuntimeService, Depends(get_runtime_service)],
):
    await runtime.cancel(job_id)
```

This makes dependencies explicit in function signatures, provides type safety,
and allows clean `dependency_overrides` in tests — no `monkeypatch` needed.

### 6.4 Create Test Data Factories

**Problem:** Three different patterns for seeding test data (manual row
insertion, helper functions, `seed_job` fixture).

**Fix:** Create a `backend/tests/factories.py` module:

```python
class JobFactory:
    @staticmethod
    async def create(
        session_factory: async_sessionmaker[AsyncSession],
        *,
        state: str = "running",
        **overrides: object,
    ) -> str:
        job_id = overrides.pop("job_id", f"job-{uuid4().hex[:8]}")
        async with session_factory() as session:
            session.add(JobRow(id=job_id, state=state, repo="/test/repo", ...))
            await session.commit()
        return job_id
```

### 6.5 Reduce RuntimeService Dependencies

**Problem:** RuntimeService takes 10 constructor arguments — a code smell
regardless of whether DI is manual or library-managed.

**Fix:** Group related services behind facade objects:

```python
@dataclass(frozen=True)
class JobCompletionServices:
    merge_service: MergeService
    diff_service: DiffService
    summarization_service: SummarizationService

# RuntimeService now takes fewer top-level dependencies
class RuntimeService:
    def __init__(
        self,
        session_factory,
        event_bus,
        adapter_registry,
        config,
        approval_service,
        completion: JobCompletionServices,
        platform_registry,
        utility_session,
    ): ...
```

---

## 7. When to Reconsider

Adopting a DI library would become worthwhile if:

1. **The service count doubles** (from ~14 to ~30+ singletons) — manual wiring
   in `lifespan.py` would become unwieldy.
2. **Multiple composition roots emerge** — e.g., a separate CLI entry point, a
   worker process, or a different API surface that needs the same services wired
   differently.
3. **Conditional service registration becomes complex** — if feature flags or
   environment-based toggling affects more than the current 3-4 optional services.
4. **Cross-cutting concerns multiply** — e.g., adding tracing, caching, or
   circuit-breaking decorators to many services would benefit from a container's
   decorator/interceptor support.

If any of these triggers occurs, **dishka** is the recommended first choice for
its modern API, native async support, and clean FastAPI integration. Fall back to
**dependency-injector** if deeper provider customization or Cython performance is
needed.

---

## 8. Conclusion

| Factor | Current Approach | With DI Library |
|--------|-----------------|-----------------|
| **Clarity** | ✅ Explicit, readable | ⚠️ Requires learning library concepts |
| **Type safety** | ✅ Full mypy --strict | ⚠️ May need type stubs/ignores |
| **Testability** | ✅ Good (with improvements from §6) | ✅ Slightly better override API |
| **Onboarding** | ✅ Standard FastAPI patterns | ⚠️ Library-specific patterns |
| **Maintainability** | ✅ 1 composition root (lifespan.py) | ✅ Declarative container |
| **Migration cost** | N/A | ❌ 5-9 days, high test risk |
| **Dependency graph visibility** | ⚠️ Implicit in lifespan.py | ✅ Declarative |

The codebase is at a **sweet spot** where manual DI is still manageable and
the investment in a library does not pay off. The targeted improvements in §6
would deliver 80% of the benefits of a DI library at 20% of the cost, without
adding a new dependency or requiring contributors to learn a new abstraction.

**Recommendation: Do not adopt a DI library now.** Instead, implement the
improvements in §6.1–§6.5 to address the existing pain points within the current
architecture.
