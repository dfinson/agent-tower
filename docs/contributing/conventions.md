# Conventions

## Backend

### API Routes

Route handlers must be thin:

```python
@router.post("/jobs")
async def create_job(body: CreateJobRequest, svc: JobService = Depends()):
    job = await svc.create_job(body)
    return job
```

No orchestration logic in routes — delegate everything to services.

### Database Access

Always go through repository classes:

```python
# ✅ Correct
job = await self.job_repo.get(job_id)

# ❌ Wrong — never use sessions directly in services
job = await session.execute(select(JobRow).where(JobRow.id == job_id))
```

### Agent SDK Isolation

Never import SDK types outside the adapter:

```python
# ✅ Correct — in copilot_adapter.py
from copilot_sdk import CopilotSession

# ❌ Wrong — in runtime_service.py
from copilot_sdk import CopilotSession  # SDK types must stay in adapter
```

### API Schemas

Pydantic models in `api_schemas.py` are the single source of truth for the API contract. All response models use the `CamelModel` base class for automatic camelCase serialization.

### Logging

Use `structlog` with structured context fields:

```python
import structlog
logger = structlog.get_logger()
logger.info("job_created", job_id=job.id, sdk=job.sdk)
```

### Domain Events

All runtime activity must be represented as domain events:

```python
event = DomainEvent(kind=DomainEventKind.job_created, job_id=job.id, payload={...})
await self.event_bus.publish(event)
```

## Frontend

### State Management

Components read from the Zustand store via selectors:

```typescript
// ✅ Correct
const jobs = useStore(selectJobs);

// ❌ Wrong — no local copies of store data
const [jobs, setJobs] = useState(store.getState().jobs);
```

### Type Imports

Import from `types.ts`, never from `schema.d.ts`:

```typescript
// ✅ Correct
import type { Job } from "../api/types";

// ❌ Wrong
import type { components } from "../api/schema";
```

### Large Lists

Lists that can grow large (logs, transcript entries) must use virtualized rendering:

```typescript
import { useVirtualizer } from "@tanstack/react-virtual";
```

## Commit Messages

Use [conventional commits](https://www.conventionalcommits.org/):

```
feat: add job creation endpoint
fix: handle worktree creation failure
docs: update spec section 14
test: add state machine transition tests
chore: update dependencies
```

## Python Environment

**Always use `uv`** — never use bare `pip`, `pip install`, or `python -m venv`:

```bash
uv sync              # install dependencies
uv add <package>     # add new dependency
uv run python ...    # run Python scripts
uv run pytest ...    # run tests
```
