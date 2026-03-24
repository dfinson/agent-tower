# Frontend Architecture

The frontend is a React 18 + TypeScript application built with Vite, using Zustand for state management and SSE for real-time updates.

## Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 |
| Language | TypeScript (strict mode) |
| Build | Vite |
| State | Zustand |
| Styling | Tailwind CSS |
| Components | Radix UI (headless primitives) |
| Icons | Lucide React |
| Routing | React Router v7 |
| Terminal | xterm.js |
| Editor | Monaco Editor |
| Diff | react-diff-viewer |
| Voice | WaveSurfer.js |
| Virtualization | @tanstack/react-virtual |

## State Management

A single Zustand store (`src/store/index.ts`) holds all application state:

### Data Slices

| Slice | Type | Purpose |
|-------|------|---------|
| `jobs` | `Record<string, JobSummary>` | All loaded jobs |
| `approvals` | `Record<string, ApprovalRequest>` | Pending/resolved approvals |
| `logs` | `Record<string, LogLine[]>` | Logs per job (capped at 10k) |
| `transcript` | `Record<string, TranscriptEntry[]>` | Conversation per job (capped at 10k) |
| `diffs` | `Record<string, DiffFileModel[]>` | Changed files per job |
| `timelines` | `Record<string, TimelineEntry[]>` | Timeline events per job |
| `plans` | `Record<string, PlanStep[]>` | Agent plan steps per job |

### Selectors

Components read state via selectors, never maintaining local copies:

```typescript
const jobs = useStore(selectJobs);
const transcript = useStore(selectJobTranscript(jobId));
const activeJobs = useStore(selectActiveJobs());
```

## SSE Event Processing

The `useSSE` hook manages the SSE connection lifecycle:

1. Connects to `/api/events`
2. Parses incoming SSE frames
3. Dispatches to `dispatchSSEEvent()` in the Zustand store
4. Store updates trigger React re-renders

### Reconnection

Exponential backoff with jitter:

- 1s → 2s → 4s → 8s → ... → 30s max
- ±500ms random jitter
- Up to 20 attempts
- Resumes via `Last-Event-ID`

### Event Deduplication

Transcript updates are checked for exact match (timestamp + role + content) to prevent duplicates on reconnection.

## Type Generation

Frontend types are generated from the backend's OpenAPI schema:

```bash
npm run generate:api
# Produces src/api/schema.d.ts
```

Friendly aliases in `src/api/types.ts` wrap the generated types:

```typescript
// Always import from types.ts, never from schema.d.ts directly
import type { Job, ApprovalRequest } from "../api/types";
```

## Component Architecture

### Pages

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | `DashboardScreen` | Kanban board (desktop) / tab list (mobile) |
| `/jobs/new` | `JobCreationScreen` | Job creation form |
| `/jobs/:id` | `JobDetailScreen` | Tabbed job detail view |
| `/history` | `HistoryScreen` | Archived jobs browser |
| `/analytics` | `AnalyticsScreen` | Fleet-level analytics dashboard |
| `/settings` | `SettingsScreen` | Configuration UI |

### Responsive Design

All responsive behavior uses Tailwind breakpoints:

- `sm:` (640px) — Mobile breakpoint
- `md:` (768px) — Tablet breakpoint
- `lg:` (1024px) — Desktop breakpoint

The `useIsMobile()` hook detects viewports below 768px for component-level responsive logic.

### Global Components

- **NavMenuSlideout** — Hamburger menu with navigation links
- **TerminalDrawer** — Resizable terminal at bottom (`` Ctrl+` ``)
- **CommandPalette** — Search overlay (⌘K)
- **ConnectionStatusIndicator** — Real-time connection badge
