---
title: "Cost Analytics Enhancements — Design Document"
description: "End-to-end design for 17 cost analytics improvements derived from competitive audit of CodeBurn, toktrack, aider-cost, and other OSS token-spend analysis tools."
author: CodePlane Team
ms.date: 2026-07-24
ms.topic: concept
keywords:
  - cost analytics
  - token spend
  - attribution
  - design
estimated_reading_time: 30
---

## Overview

This document specifies 17 enhancements to CodePlane's cost analytics subsystem.
Each item is traced from competitive research (primarily CodeBurn, toktrack,
aider-cost) through every layer: DB schema, Alembic migration, backend services,
API endpoints, Pydantic response models, frontend API client, and React UI
components.

Items 1–12 are derived from competitive analysis (CodeBurn, toktrack, aider-cost).
Items 13–18 are original CodePlane differentiators designed from a data-uniqueness
audit — breakdowns that no competitor can replicate because they require
CodePlane's unique telemetry (trail nodes, file access logs, execution phases,
resolution outcomes, per-span motivations).

### Source audit summary

| Project | License | Key insight adopted |
|---------|---------|---------------------|
| CodeBurn (`classifier.ts`) | MIT | `refineByKeywords` first-match-wins for intent sub-classification; `countRetries` edit→shell→edit pattern |
| CodeBurn (`compare-stats.ts`) | MIT | Per-model one-shot rate, retry rate, self-correction %, cost/edit, working-style metrics |
| CodeBurn (`yield.ts`) | MIT | Session→git-commit correlation for productive/reverted/abandoned yield |
| CodeBurn (`optimize.ts`) | MIT | Penalty-graded waste detectors with trend tracking (active/improving/resolved) |
| toktrack | MIT | Real-time budget burn-down with configurable monthly/daily limits |
| aider-cost | Apache-2.0 | Cost-per-line-of-code normalization, cache-write cost visibility |

### Existing CodePlane state

* **Attribution pipeline** (`cost_attribution.py`): 9-category `_classify_turn_intent` priority ladder, `_count_edit_retries`, dimensions: `activity`, `turn`, `phase`, `activity_phase`, `edit_efficiency`.
* **CostBucket**: `cost_usd`, `input_tokens`, `output_tokens`, `call_count` — no cache token fields.
* **Spans table**: already stores `cache_read_tokens`, `cache_write_tokens` per span — data exists, attribution ignores it.
* **TelemetrySummaryRow**: has `diff_lines_added`, `diff_lines_removed`, `total_cost_usd`.
* **Model comparison query**: joins `job_telemetry_summary` with `jobs` table, computes `cache_hit_rate`, `cost_per_turn`, `cost_per_tool_call` — but no one-shot/retry/self-correction metrics.
* **Statistical analysis** (`statistical_analysis.py`): 6 anomaly detectors writing to `cost_observations`.
* **BudgetCard** (`BudgetCard.tsx`): daily limit progress bar, quota % from Copilot, SDK breakdown.
* **Config** (`TelemetryConfig`): `claude_monthly_budget_usd`, `copilot_premium_entitlement`, `daily_spend_limit_usd`.

---

## Item 1 — Waste detection engine (Optimize)

### Problem

CodeBurn's `optimize` command is its highest-rated feature: deterministic
waste-pattern scanners that flag file re-reads, unused MCP servers, bloated
system prompts, uncapped bash output, ghost skills, and low read:edit ratios.
Each finding carries a penalty grade and trend status (active / improving /
resolved).

CodePlane's `statistical_analysis.py` runs seven detectors that write to
`cost_observations` and surface through the `ObservationsPanel`. But two gaps
remain: (a) the design doc never formalized these detectors as a cohesive
feature, and (b) several waste patterns from the research audit have no
equivalent detector.

### What CodeBurn does

`optimize.ts` runs waste detectors in sequence:

* `detectFileRereads`: flags files read repeatedly within a session
* `detectUnusedMCPServers`: compares configured servers against actual tool
  calls
* `detectBloatedSystemPrompt`: estimates CLAUDE.md / system prompt token cost
* `detectUncappedBashOutput`: flags shell commands returning massive output
* `detectGhostSkills`: finds skills configured but never invoked
* `detectLowReadEditRatio`: flags sessions with high reads but few edits

Each detector produces a penalty-graded finding with trend tracking
(active / improving / resolved).

### Architectural differences

CodePlane is a control plane, not a CLI scraper. It receives telemetry
post-hoc from agents and has no access to agent-side configuration files
(CLAUDE.md, MCP server lists, skill definitions). Three CodeBurn detectors
are inapplicable:

| CodeBurn detector | CodePlane applicability |
|-------------------|------------------------|
| Unused MCP servers | Not applicable: CodePlane does not know what MCP servers agents have configured |
| Bloated system prompt | Not applicable: system prompts are agent-side, not transmitted in telemetry |
| Ghost skills | Not applicable: skill configuration is agent-side |

The remaining patterns are either already implemented or constructible from
existing telemetry data.

### Design

#### Existing detectors (pre-design-doc, no changes needed)

These seven detectors already write to `cost_observations` via
`statistical_analysis.py`:

| Detector | Category | Source data |
|----------|----------|-------------|
| File re-read hotspots | `file_reread` | `file_access` table |
| Tool failure patterns | `tool_failure` | `telemetry_spans` |
| Turn cost escalation | `turn_escalation` | `job_telemetry_summary` |
| Retry waste | `retry_waste` | `telemetry_spans` |
| Compaction storms | `compaction_storm` | `job_telemetry_summary` |
| Cache efficiency regression | `cache_regression` | `job_telemetry_summary` |
| Communication waste (Item 12) | `communication_waste` | `job_cost_attribution` |

#### New detector A: unproductive exploration

Flag jobs where investigation is the dominant activity and the job produced
no merged or PR'd output. "I spent most of my budget reading code and the
job was discarded/failed" is a clear waste signal.

Category: `unproductive_exploration`

Source: `job_cost_attribution` (dimension=`activity`) joined with `jobs`
(resolution) and `job_telemetry_summary` (diff lines, total cost).

Trigger conditions (all must hold):

1. Investigation bucket holds the majority (>50%) of the job's total
   attribution cost. This is not an arbitrary threshold: majority means
   investigation was the single largest time sink.
2. The job's resolution is `discarded` or `failed` (no productive outcome).
3. The job's total cost exceeds the fleet median job cost (avoid flagging
   cheap exploratory jobs that aren't worth optimizing).

##### Backend — `statistical_analysis.py`

New function `_analyse_unproductive_exploration`:

```python
async def _analyse_unproductive_exploration(
    cost_repo: CostAttributionRepository,
    obs_repo: ObservationsRepository,
) -> int:
    """Flag jobs where investigation dominated cost and no code landed."""
    rows = await cost_repo.unproductive_exploration_jobs(period_days=14)
    if not rows:
        return 0

    total_waste = sum(r["investigation_cost"] for r in rows)
    await obs_repo.upsert(
        category="unproductive_exploration",
        severity="warning" if total_waste >= 5.0 else "info",
        title=(
            f"{len(rows)} jobs spent majority of cost investigating "
            f"but produced no merged output"
        ),
        detail=(
            f"These jobs spent {total_waste:.2f} USD on investigation/exploration "
            f"turns and ended as discarded or failed. Consider more targeted "
            f"prompts or breaking large exploration tasks into cheaper scoping "
            f"jobs before committing to full implementation."
        ),
        evidence={
            "flagged_jobs": [
                {
                    "job_id": r["job_id"],
                    "investigation_cost_usd": round(r["investigation_cost"], 4),
                    "total_cost_usd": round(r["total_cost"], 4),
                    "investigation_pct": round(r["investigation_pct"], 2),
                    "resolution": r["resolution"],
                    "diff_lines": r["diff_lines"],
                }
                for r in rows[:10]
            ],
            "total_waste_usd": round(total_waste, 4),
        },
        job_count=len(rows),
        total_waste_usd=total_waste,
    )
    return 1
```

##### Backend — `cost_attribution_repo.py`

New method `unproductive_exploration_jobs`:

```python
async def unproductive_exploration_jobs(
    self, period_days: int,
) -> list[dict[str, Any]]:
    """Jobs where investigation cost > 50% of total and outcome was
    discarded or failed."""
    result = await self._session.execute(
        text("""
            WITH job_activity AS (
                SELECT
                    a.job_id,
                    SUM(CASE WHEN a.bucket = 'investigation'
                        THEN a.cost_usd ELSE 0 END) AS investigation_cost,
                    SUM(a.cost_usd) AS total_cost
                FROM job_cost_attribution a
                JOIN jobs j ON j.id = a.job_id
                WHERE a.dimension = 'activity'
                    AND j.created_at >= datetime('now', :offset)
                GROUP BY a.job_id
            ),
            fleet_median AS (
                SELECT AVG(total_cost) AS median_cost
                FROM (
                    SELECT total_cost,
                        ROW_NUMBER() OVER (ORDER BY total_cost) AS rn,
                        COUNT(*) OVER () AS cnt
                    FROM job_activity
                )
                WHERE rn IN (cnt / 2, cnt / 2 + 1)
            )
            SELECT
                ja.job_id,
                ja.investigation_cost,
                ja.total_cost,
                ja.investigation_cost / ja.total_cost AS investigation_pct,
                j.resolution,
                COALESCE(t.diff_lines_added, 0)
                    + COALESCE(t.diff_lines_removed, 0) AS diff_lines
            FROM job_activity ja
            JOIN jobs j ON j.id = ja.job_id
            LEFT JOIN job_telemetry_summary t ON t.job_id = ja.job_id
            CROSS JOIN fleet_median fm
            WHERE ja.investigation_cost > ja.total_cost * 0.5
                AND j.resolution IN ('discarded', 'failed')
                AND ja.total_cost > fm.median_cost
            ORDER BY ja.investigation_cost DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### New detector B: high delegation overhead

Flag jobs where sub-agent delegation cost exceeds the parent job's direct
LLM cost. When sub-agents cost more than the parent, the delegation itself
may be wasteful (the parent spent tokens coordinating work that could have
been done directly).

Category: `delegation_overhead`

Source: `job_telemetry_summary.subagent_cost_usd` versus
`job_telemetry_summary.total_cost_usd - subagent_cost_usd` (direct cost).

Trigger: `subagent_cost_usd > total_cost_usd - subagent_cost_usd` (sub-agent
cost exceeds the parent's own spend) AND `subagent_cost_usd > 0` (job actually
used delegation).

##### Backend — `statistical_analysis.py`

New function `_analyse_delegation_overhead`:

```python
async def _analyse_delegation_overhead(
    summary_repo: TelemetryAnalyticsRepository,
    obs_repo: ObservationsRepository,
) -> int:
    """Flag jobs where sub-agent cost exceeds parent direct cost."""
    rows = await summary_repo.high_delegation_jobs(period_days=14)
    if not rows:
        return 0

    total_delegation_excess = sum(
        r["subagent_cost_usd"] - r["direct_cost_usd"] for r in rows
    )
    await obs_repo.upsert(
        category="delegation_overhead",
        severity="warning" if total_delegation_excess >= 5.0 else "info",
        title=(
            f"{len(rows)} jobs spent more on sub-agents than on direct work"
        ),
        detail=(
            f"These jobs delegated work to sub-agents that cost more than "
            f"the parent job's own LLM calls. Excess delegation cost: "
            f"${total_delegation_excess:.2f}. Consider whether the parent "
            f"could have done the work directly, or whether sub-agent prompts "
            f"need tightening."
        ),
        evidence={
            "flagged_jobs": [
                {
                    "job_id": r["job_id"],
                    "subagent_cost_usd": round(r["subagent_cost_usd"], 4),
                    "direct_cost_usd": round(r["direct_cost_usd"], 4),
                    "total_cost_usd": round(r["total_cost_usd"], 4),
                    "delegation_pct": round(
                        r["subagent_cost_usd"] / r["total_cost_usd"], 2,
                    ),
                }
                for r in rows[:10]
            ],
            "total_excess_usd": round(total_delegation_excess, 4),
        },
        job_count=len(rows),
        total_waste_usd=total_delegation_excess,
    )
    return 1
```

##### Backend — `telemetry_analytics_repo.py`

New method `high_delegation_jobs`:

```python
async def high_delegation_jobs(
    self, period_days: int,
) -> list[dict[str, Any]]:
    """Jobs where sub-agent cost exceeds the parent's direct cost."""
    result = await self._session.execute(
        text("""
            SELECT
                t.job_id,
                t.subagent_cost_usd,
                t.total_cost_usd - t.subagent_cost_usd AS direct_cost_usd,
                t.total_cost_usd
            FROM job_telemetry_summary t
            JOIN jobs j ON j.id = t.job_id
            WHERE j.created_at >= datetime('now', :offset)
                AND t.subagent_cost_usd > 0
                AND t.subagent_cost_usd
                    > t.total_cost_usd - t.subagent_cost_usd
            ORDER BY t.subagent_cost_usd DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### DB — no schema change

Both detectors query existing tables (`job_cost_attribution`,
`job_telemetry_summary`, `jobs`). No migration needed.

#### API — no endpoint change

Both detectors write to `cost_observations` via `ObservationsRepository.upsert`.
The existing `GET /analytics/observations` endpoint returns them automatically.

#### Frontend — `ObservationsPanel.tsx`

Add icon mappings for the new categories:

```typescript
const CATEGORY_ICONS: Record<string, LucideIcon> = {
  // ... existing ...
  unproductive_exploration: Search,
  delegation_overhead: GitFork,
};
```

No new component needed. Both observation types render through the existing
panel with severity coloring and dismiss functionality.

#### Integration — `statistical_analysis.py`

Add both detectors to `run_analysis`:

```python
count += await _analyse_unproductive_exploration(cost_repo, obs_repo)
count += await _analyse_delegation_overhead(summary_repo, obs_repo)
```

---

## Item 2 — Yield/ROI correlation

### Problem

CodeBurn correlates session timestamps with git commits to categorize cost as
productive (code merged), reverted, or abandoned. CodePlane already tracks
`resolution` on jobs (`merged`, `pr_created`, `discarded`, `failed`,
`cancelled`) but never surfaces cost-weighted outcome metrics.

### What CodeBurn does

`yield.ts` categorizes sessions:

* **productive**: session has commits that landed in main and were NOT reverted
* **reverted**: ≥50% of in-main commits were later reverted (scans `This reverts commit <sha>`)
* **abandoned**: no matching commits in main

CodeBurn scrapes git log because it has no job-level resolution state.
CodePlane already has this state — no git scraping needed.

### Design

#### DB — no schema change

Jobs table already has `resolution TEXT` (`merged`, `pr_created`, `discarded`,
`failed`, `cancelled`). `job_telemetry_summary` has `total_cost_usd`. The
join is trivial.

#### Backend — `analytics_service.py`

New method `yield_summary(period_days: int, repo: str | None) -> YieldSummary`:

```python
class YieldCategory(str, Enum):
    PRODUCTIVE = "productive"      # merged or pr_created
    ABANDONED = "abandoned"        # discarded
    FAILED = "failed"              # failed
    CANCELLED = "cancelled"        # cancelled

class YieldSummary(TypedDict):
    categories: list[YieldCategoryRow]
    cost_per_merge_usd: float      # total productive cost / merged count
    total_cost_usd: float
    total_jobs: int
```

SQL (delegated to `telemetry_analytics_repo.py`):

```sql
SELECT
    CASE
        WHEN j.resolution IN ('merged', 'pr_created') THEN 'productive'
        WHEN j.resolution = 'discarded' THEN 'abandoned'
        WHEN j.state = 'failed' THEN 'failed'
        ELSE 'cancelled'
    END AS yield_category,
    COUNT(*) AS job_count,
    COALESCE(SUM(t.total_cost_usd), 0) AS total_cost_usd,
    COALESCE(AVG(t.total_cost_usd), 0) AS avg_cost_usd
FROM jobs j
JOIN job_telemetry_summary t ON t.job_id = j.id
WHERE j.created_at >= datetime('now', :period_offset)
    AND j.state IN ('completed', 'failed', 'cancelled')
GROUP BY yield_category
```

`cost_per_merge_usd` = `SUM(cost WHERE resolution = 'merged') / COUNT(merged)`.
Falls back to 0 if no merges.

#### API — `api/analytics.py`

```
GET /analytics/yield?period=30&repo=<optional>
```

Response model `YieldResponse(CamelModel)`:

```python
class YieldCategoryRow(CamelModel):
    category: str           # productive | abandoned | failed | cancelled
    job_count: int
    total_cost_usd: float
    avg_cost_usd: float
    pct_of_total: float     # fraction of total_cost_usd

class YieldResponse(CamelModel):
    period: int
    categories: list[YieldCategoryRow]
    cost_per_merge_usd: float
    total_cost_usd: float
    total_jobs: int
```

#### Frontend — `client-analytics.ts`

```typescript
export interface YieldCategoryRow {
  category: string;
  jobCount: number;
  totalCostUsd: number;
  avgCostUsd: number;
  pctOfTotal: number;
}

export interface YieldResponse {
  period: number;
  categories: YieldCategoryRow[];
  costPerMergeUsd: number;
  totalCostUsd: number;
  totalJobs: number;
}

export function fetchYield(period = 30, repo?: string): Promise<YieldResponse> {
  const params = new URLSearchParams({ period: String(period) });
  if (repo) params.set("repo", repo);
  return request(`/analytics/yield?${params}`);
}
```

#### Frontend — new `YieldCard.tsx`

Donut chart (Recharts `PieChart`) showing cost distribution by yield category.
Color mapping: productive → green-500, abandoned → amber-500, failed → red-500,
cancelled → gray-400.

Headline KPI: **Cost per merge: $X.XX** displayed prominently above the chart.

Placed in `AnalyticsScreen.tsx` in the scorecard row alongside `BudgetCard` and
`ActivityCard`.

---

## Item 3 — Split implementation into feature_dev / refactoring / debugging

### Problem

CodePlane's `_classify_turn_intent` already identifies `implementation` turns
but doesn't sub-classify them. CodeBurn's `refineByKeywords` splits coding work
into `coding`, `debugging`, `feature`, `refactoring` using first-match-position
in the conversation text.

### What CodeBurn does

`classifier.ts` `refineByKeywords`:

* Regex keyword lists: `FEATURE_KEYWORDS` (add|create|implement|new|build|feature...),
  `DEBUG_KEYWORDS` (fix|bug|error|broken|failing|crash|debug...),
  `REFACTOR_KEYWORDS` (refactor|clean up|rename|reorganize|simplify...)
* `firstMatchingCategory()` finds the earliest regex match position in text
* Tie-break by candidate order: `[refactoring, feature, debugging]`

### Design

CodePlane has two signal sources unavailable to CodeBurn:

1. **`jobs.description`** — the user's original prompt (set at job creation)
2. **`jobs.motivation_summary`** — LLM-generated summary of what the agent did

We use `jobs.description` as the primary signal (it's the user's intent) and
fall back to `motivation_summary`.

#### DB — no schema change

The sub-classification writes to the existing `job_cost_attribution` table
with `dimension='activity'` and `bucket` values `feature_dev`, `refactoring`,
`debugging` instead of the blanket `implementation`.

#### Backend — `cost_attribution.py`

New function `_sub_classify_implementation`:

```python
import re

_FEATURE_RE = re.compile(
    r"\b(add|create|implement|new|build|feature|introduce|support|enable)\b",
    re.IGNORECASE,
)
_DEBUG_RE = re.compile(
    r"\b(fix|bug|error|broken|failing|crash|debug|issue|wrong|incorrect)\b",
    re.IGNORECASE,
)
_REFACTOR_RE = re.compile(
    r"\b(refactor|clean\s*up|rename|reorganize|simplify|restructure|extract|deduplicate)\b",
    re.IGNORECASE,
)

_SUB_CLASSIFIERS = [
    ("refactoring", _REFACTOR_RE),
    ("debugging", _DEBUG_RE),
    ("feature_dev", _FEATURE_RE),
]

def _sub_classify_implementation(description: str | None, motivation: str | None) -> str:
    """Sub-classify 'implementation' into feature_dev / debugging / refactoring.

    Uses CodeBurn's first-match-position approach: find the earliest regex
    match across all candidates; tie-break by candidate order (refactoring
    wins ties over debugging, debugging over feature_dev).
    """
    text = (description or "") + " " + (motivation or "")
    if not text.strip():
        return "implementation"

    best_pos = len(text) + 1
    best_label = "implementation"

    for label, pattern in _SUB_CLASSIFIERS:
        m = pattern.search(text)
        if m and m.start() < best_pos:
            best_pos = m.start()
            best_label = label

    return best_label
```

Integration point: in `_compute_attribution`, after
`activity = _classify_turn_intent(context)`, if `activity == "implementation"`:

```python
if activity == "implementation":
    activity = _sub_classify_implementation(job_description, job_motivation)
```

The `job_description` and `job_motivation` are loaded once at the top of
`_compute_attribution` from the `jobs` table:

```python
job_row = await session.execute(
    text("SELECT description, motivation_summary FROM jobs WHERE id = :jid"),
    {"jid": job_id},
)
job_info = job_row.mappings().first()
job_description = (job_info or {}).get("description")
job_motivation = (job_info or {}).get("motivation_summary")
```

#### API — no endpoint change

The existing `/analytics/cost-drivers` and `/analytics/cost-drivers/{job_id}`
endpoints return whatever buckets are in the `job_cost_attribution` table.
The new sub-buckets (`feature_dev`, `refactoring`, `debugging`) appear
automatically in the activity dimension.

#### Frontend — `FleetCostDriverInsights.tsx`

The existing component already renders activity rows dynamically from API data.
New buckets appear automatically. The only change is adding icons/colors:

```typescript
const ACTIVITY_COLORS: Record<string, string> = {
  // existing
  implementation: "text-blue-400",
  investigation: "text-cyan-400",
  verification: "text-green-400",
  // new sub-categories
  feature_dev: "text-blue-400",
  refactoring: "text-purple-400",
  debugging: "text-orange-400",
  // ...rest unchanged
};
```

And display labels:

```typescript
const ACTIVITY_LABELS: Record<string, string> = {
  feature_dev: "Feature Development",
  refactoring: "Refactoring",
  debugging: "Debugging",
  // ...
};
```

---

## Item 4 — Per-project/repo cost breakdown in activity dimension

### Problem

Cost drivers show activities across all repos but don't break down by repo.
When running agents across multiple projects, you can't see which repo
consumes the most "investigation" or "verification" budget.

### Design

#### DB — no schema change

The `job_cost_attribution` table can be joined with `jobs.repo` via `job_id`.
No new table or column needed.

#### Backend — `analytics_service.py` / `cost_attribution_repo.py`

New repo method `by_dimension_per_repo`:

```python
async def by_dimension_per_repo(
    self,
    dimension: str,
    period_days: int,
) -> list[dict[str, Any]]:
    """Activity cost broken down by repo."""
    result = await self._session.execute(
        text("""
            SELECT
                j.repo,
                a.bucket,
                SUM(a.cost_usd) AS cost_usd,
                SUM(a.input_tokens) AS input_tokens,
                SUM(a.output_tokens) AS output_tokens,
                SUM(a.call_count) AS call_count,
                COUNT(DISTINCT a.job_id) AS job_count
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = :dimension
                AND j.created_at >= datetime('now', :offset)
            GROUP BY j.repo, a.bucket
            ORDER BY cost_usd DESC
        """),
        {"dimension": dimension, "offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

New service method `cost_by_repo_activity(period_days, dimension="activity")`.

#### API — `api/analytics.py`

```
GET /analytics/cost-drivers?period=30&dimension=activity&group_by=repo
```

When `group_by=repo` is present, the response nests buckets under repo keys:

```python
class RepoCostDriversResponse(CamelModel):
    period: int
    dimension: str
    repos: list[RepoCostBreakdown]

class RepoCostBreakdown(CamelModel):
    repo: str
    total_cost_usd: float
    buckets: list[CostAttributionBucket]
```

The existing `/analytics/cost-drivers` endpoint gains an optional
`group_by: str | None = Query(None)` parameter. When `group_by="repo"`, it
returns `RepoCostDriversResponse` instead of `FleetCostDriversResponse`. Both
share the same URL path to avoid proliferating endpoints.

#### Frontend — `FleetCostDriverInsights.tsx`

Add a toggle/dropdown: **"Group by: None | Repository"**.

When grouped by repo, render a collapsible section per repo, each containing
its own activity rows. The repo header shows total cost. Sorted by total cost
descending.

---

## Item 5 — Subscription/budget plan tracking

### Problem

toktrack provides real-time budget burn-down with configurable monthly caps.
CodePlane has `claude_monthly_budget_usd`, `copilot_premium_entitlement`, and
`daily_spend_limit_usd` in config, and `BudgetCard` shows daily limit progress.
But there is no monthly burn-down tracking, no projected overshoot warnings,
and the monthly budget config field is not surfaced in the UI.

### Design

#### DB — no schema change

Monthly totals are computed from `job_telemetry_summary.total_cost_usd` with
`created_at` filtered to the current calendar month. No materialized table
needed — the data volume is small (jobs, not spans).

#### Backend — `telemetry_analytics_repo.py`

New method `monthly_burn`:

```python
async def monthly_burn(self) -> dict[str, Any]:
    """Current month spend, daily average, and projected month-end total."""
    result = await self._session.execute(
        text("""
            SELECT
                COALESCE(SUM(total_cost_usd), 0) AS month_spend,
                COUNT(DISTINCT date(created_at)) AS active_days,
                julianday('now') - julianday(
                    strftime('%Y-%m-01', 'now')
                ) + 1 AS days_elapsed
            FROM job_telemetry_summary
            WHERE created_at >= strftime('%Y-%m-01', 'now')
        """),
    )
    row = result.mappings().first()
    month_spend = float(row["month_spend"])
    days_elapsed = max(float(row["days_elapsed"]), 1)
    # Days in current month
    days_in_month_result = await self._session.execute(
        text("""
            SELECT julianday(
                strftime('%Y-%m-01', 'now', '+1 month')
            ) - julianday(
                strftime('%Y-%m-01', 'now')
            ) AS days_in_month
        """),
    )
    days_in_month = float(
        days_in_month_result.mappings().first()["days_in_month"]
    )
    daily_avg = month_spend / days_elapsed
    projected = daily_avg * days_in_month

    return {
        "month_spend_usd": month_spend,
        "days_elapsed": int(days_elapsed),
        "days_in_month": int(days_in_month),
        "daily_avg_usd": daily_avg,
        "projected_month_end_usd": projected,
    }
```

#### Backend — `analytics_service.py`

New method `budget_status`:

```python
async def budget_status(self) -> BudgetStatus:
    burn = await self._analytics_repo.monthly_burn()
    config = self._config.telemetry
    return BudgetStatus(
        month_spend_usd=burn["month_spend_usd"],
        monthly_budget_usd=config.claude_monthly_budget_usd,
        daily_spend_limit_usd=config.daily_spend_limit_usd,
        projected_month_end_usd=burn["projected_month_end_usd"],
        days_elapsed=burn["days_elapsed"],
        days_in_month=burn["days_in_month"],
        daily_avg_usd=burn["daily_avg_usd"],
        pct_used=burn["month_spend_usd"] / config.claude_monthly_budget_usd
            if config.claude_monthly_budget_usd > 0 else 0.0,
    )
```

#### API — extend scorecard

The existing `GET /analytics/scorecard` response gets new fields rather than
a new endpoint:

```python
class ScorecardResponse(CamelModel):
    # ... existing fields ...
    monthly_budget_usd: float = 0.0
    month_spend_usd: float = 0.0
    projected_month_end_usd: float = 0.0
    days_elapsed: int = 0
    days_in_month: int = 0
    daily_avg_usd: float = 0.0
    pct_monthly_budget_used: float = 0.0
```

#### Frontend — `BudgetCard.tsx`

Below the existing daily limit section, add a **Monthly Budget** section
(conditionally rendered when `monthlyBudgetUsd > 0`):

* Progress bar showing `monthSpendUsd / monthlyBudgetUsd`
* Projected month-end with warning if projection exceeds budget
* Daily average spend rate
* Color: green ≤60%, yellow 60-80%, red >80% of budget

Also add a projected-overshoot banner:

```
⚠ Projected month-end: $142.30 (exceeds $100.00 budget by 42%)
```

#### Frontend — `ScorecardResponse` type update

Add the new fields to the `ScorecardResponse` interface in
`client-analytics.ts`:

```typescript
export interface ScorecardResponse {
  // ... existing ...
  monthlyBudgetUsd: number;
  monthSpendUsd: number;
  projectedMonthEndUsd: number;
  daysElapsed: number;
  daysInMonth: number;
  dailyAvgUsd: number;
  pctMonthlyBudgetUsed: number;
}
```

---

## Item 6 — Compare mode: efficiency metrics per model

### Problem

CodeBurn's `compare-stats.ts` computes per-model: one-shot rate, retry rate,
self-correction %, cost/edit, and a working-style profile (delegation rate,
planning rate, avg tools/turn). CodePlane's `ModelComparison` shows
`cache_hit_rate`, `cost_per_turn`, `cost_per_tool_call` but lacks
edit-efficiency metrics per model.

### What CodeBurn does

`computeComparison()` compares two models across 7 metrics in 2 sections:

* **Performance**: One-shot rate (%), Retry rate, Self-correction (%)
* **Efficiency**: Cost/call, Cost/edit, Output tok/call, Cache hit rate (%)

`computeWorkingStyle()` adds delegation rate, planning rate, avg tools/turn.

### Design

#### DB — Alembic migration `0034`

Add per-model edit efficiency by extending `job_cost_attribution` with a
`model` column:

```python
"""0034 — add model column to job_cost_attribution"""

def upgrade():
    op.add_column(
        "job_cost_attribution",
        sa.Column("model", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_cost_attribution_model",
        "job_cost_attribution",
        ["model"],
    )
```

#### Backend — `cost_attribution.py`

When writing attribution rows, include the model from
`job_telemetry_summary.model`:

```python
model_row = await session.execute(
    text("SELECT model FROM job_telemetry_summary WHERE job_id = :jid"),
    {"jid": job_id},
)
job_model = (model_row.mappings().first() or {}).get("model", "")
```

Each attribution row dict gets `"model": job_model` before batch insert.
The `insert_batch` method passes the model column through.

#### Backend — `cost_attribution_repo.py`

New method `edit_efficiency_by_model`:

```python
async def edit_efficiency_by_model(
    self, period_days: int
) -> list[dict[str, Any]]:
    """Edit efficiency aggregated per model."""
    result = await self._session.execute(
        text("""
            SELECT
                a.model,
                SUM(a.call_count) AS edit_turns,
                SUM(a.input_tokens) AS one_shot_turns,
                SUM(a.output_tokens) AS retries,
                CASE WHEN SUM(a.call_count) > 0
                    THEN SUM(a.input_tokens) * 1.0 / SUM(a.call_count)
                    ELSE 0 END AS one_shot_rate,
                COUNT(DISTINCT a.job_id) AS job_count
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = 'edit_efficiency'
                AND j.created_at >= datetime('now', :offset)
                AND a.model IS NOT NULL AND a.model != ''
            GROUP BY a.model
            ORDER BY one_shot_rate DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### Backend — `analytics_service.py`

New method `model_efficiency(period_days) -> ModelEfficiencyResponse`.

#### API — `api/analytics.py`

```
GET /analytics/model-efficiency?period=30
```

Response:

```python
class ModelEfficiencyRow(CamelModel):
    model: str
    edit_turns: int
    one_shot_turns: int
    retries: int
    one_shot_rate: float          # 0.0–1.0
    retry_rate: float             # retries / edit_turns
    job_count: int

class ModelEfficiencyResponse(CamelModel):
    period: int
    models: list[ModelEfficiencyRow]
```

#### Frontend — extend `ModelComparison.tsx`

Add columns to the existing model comparison table:

| Column | Source |
|--------|--------|
| One-shot % | `oneShotRate * 100` |
| Retry rate | `retries / editTurns` |
| Edit turns | `editTurns` |

Data loaded from new `fetchModelEfficiency(period)` and merged client-side
by model name with existing `ModelComparisonRow` data.

New `fetchModelEfficiency` in `client-analytics.ts`:

```typescript
export interface ModelEfficiencyRow {
  model: string;
  editTurns: number;
  oneShotTurns: number;
  retries: number;
  oneShotRate: number;
  retryRate: number;
  jobCount: number;
}

export function fetchModelEfficiency(
  period = 30,
): Promise<{ period: number; models: ModelEfficiencyRow[] }> {
  return request(`/analytics/model-efficiency?period=${period}`);
}
```

---

## Item 7 — Cache efficiency by phase/activity

### Problem

CodePlane computes `cache_hit_rate` globally per model but doesn't break it
down by execution phase or activity. Investigation phases should have high
cache rates (re-reading context); implementation phases may not. This
granularity helps identify where cache warming strategies are effective.

### Design

#### DB — no schema change

Spans already have `cache_read_tokens`, `cache_write_tokens`, `input_tokens`,
and `execution_phase`. This is a query-layer addition.

#### Backend — `cost_attribution_repo.py`

New method `cache_efficiency_by_dimension`:

```python
async def cache_efficiency_by_dimension(
    self,
    dimension: str,   # "phase" or "activity"
    period_days: int,
) -> list[dict[str, Any]]:
    """Cache hit rate aggregated by phase or activity bucket."""
    if dimension == "phase":
        return await self._cache_by_phase(period_days)
    return await self._cache_by_activity(period_days)
```

For **phase**, query spans directly:

```sql
SELECT
    s.execution_phase AS bucket,
    SUM(s.input_tokens) AS total_input_tokens,
    SUM(s.cache_read_tokens) AS total_cache_read_tokens,
    SUM(s.cache_write_tokens) AS total_cache_write_tokens,
    CASE WHEN SUM(s.input_tokens) > 0
        THEN SUM(s.cache_read_tokens) * 1.0 / SUM(s.input_tokens)
        ELSE 0 END AS cache_hit_rate,
    COUNT(DISTINCT s.job_id) AS job_count
FROM telemetry_spans s
JOIN jobs j ON j.id = s.job_id
WHERE s.span_type = 'llm'
    AND j.created_at >= datetime('now', :offset)
    AND s.execution_phase IS NOT NULL
GROUP BY s.execution_phase
ORDER BY cache_hit_rate DESC
```

For **activity**, the attribution pipeline must propagate cache tokens (see
Item 8 below). Once Item 8 is implemented, this query reads from
`job_cost_attribution`:

```sql
SELECT
    a.bucket,
    SUM(a.input_tokens) AS total_input_tokens,
    SUM(a.cache_read_tokens) AS total_cache_read_tokens,
    SUM(a.cache_write_tokens) AS total_cache_write_tokens,
    CASE WHEN SUM(a.input_tokens) > 0
        THEN SUM(a.cache_read_tokens) * 1.0 / SUM(a.input_tokens)
        ELSE 0 END AS cache_hit_rate,
    COUNT(DISTINCT a.job_id) AS job_count
FROM job_cost_attribution a
JOIN jobs j ON j.id = a.job_id
WHERE a.dimension = 'activity'
    AND j.created_at >= datetime('now', :offset)
GROUP BY a.bucket
ORDER BY cache_hit_rate DESC
```

#### API — `api/analytics.py`

```
GET /analytics/cache-efficiency?period=30&dimension=phase
GET /analytics/cache-efficiency?period=30&dimension=activity
```

Response:

```python
class CacheEfficiencyRow(CamelModel):
    bucket: str
    total_input_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    cache_hit_rate: float
    job_count: int

class CacheEfficiencyResponse(CamelModel):
    period: int
    dimension: str
    buckets: list[CacheEfficiencyRow]
```

#### Frontend — new `CacheEfficiencyChart.tsx`

Horizontal bar chart (Recharts `BarChart`) with one bar per phase/activity
bucket. Each bar shows cache hit rate (0–100%).

Color-coded: ≥70% green, 40–70% yellow, <40% red.

Toggle between "By Phase" and "By Activity" tabs.

Placed in `AnalyticsScreen.tsx` below the model comparison section.

---

## Item 8 — Token-type cost disaggregation in attribution

### Problem

`CostBucket` only tracks `input_tokens` and `output_tokens`. Spans already
have `cache_read_tokens` and `cache_write_tokens`, but the attribution
pipeline ignores them. This means per-activity cache cost breakdowns are
impossible.

### Design

#### DB — Alembic migration `0034` (combined with Item 6)

Add `cache_read_tokens` and `cache_write_tokens` to `job_cost_attribution`:

```python
op.add_column(
    "job_cost_attribution",
    sa.Column("cache_read_tokens", sa.BigInteger(), server_default="0"),
)
op.add_column(
    "job_cost_attribution",
    sa.Column("cache_write_tokens", sa.BigInteger(), server_default="0"),
)
```

#### Backend — `cost_attribution.py`

Update `CostBucket`:

```python
class CostBucket(TypedDict):
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    call_count: int
```

Update `_zero_bucket`:

```python
def _zero_bucket() -> CostBucket:
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "call_count": 0,
    }
```

Update `_accumulate`:

```python
def _accumulate(
    bucket: CostBucket, cost: float, in_tok: int, out_tok: int,
    *, cache_read: int = 0, cache_write: int = 0, call_count: int = 1,
) -> None:
    bucket["cost_usd"] += float(cost or 0)
    bucket["input_tokens"] += int(in_tok or 0)
    bucket["output_tokens"] += int(out_tok or 0)
    bucket["cache_read_tokens"] += int(cache_read or 0)
    bucket["cache_write_tokens"] += int(cache_write or 0)
    bucket["call_count"] += int(call_count or 0)
```

In the span loop, read cache tokens from each span:

```python
cache_read = span.get("cache_read_tokens") or 0
cache_write = span.get("cache_write_tokens") or 0
```

And pass them through every `_accumulate` call.

#### Backend — `cost_attribution_repo.py`

Update `insert_batch` to include the new columns. The existing batch
insert uses dynamic column names from the row dicts, so adding new keys
to the dict is sufficient if using parameterized inserts. If using a fixed
column list, add `cache_read_tokens` and `cache_write_tokens`.

Update `by_dimension` and `fleet_summary` queries to select the new columns.

#### API — `api/analytics.py`

The existing `CostAttributionBucket` schema gains new optional fields:

```python
class CostAttributionBucket(CamelModel):
    # ... existing ...
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
```

All existing endpoints that return `CostAttributionBucket` automatically
include the new fields.

#### Frontend — `FleetCostDriverInsights.tsx`

In the expandable detail for each activity row, add cache token breakdown:

```
Input: 1.2M tokens | Output: 340K tokens
Cache read: 890K tokens | Cache write: 120K tokens
Cache hit rate: 74%
```

Update `CostAttributionBucket` type in `client-analytics.ts`:

```typescript
export interface CostAttributionBucket {
  // ... existing ...
  cache_read_tokens?: number;
  cache_write_tokens?: number;
}
```

---

## Item 9 — Cost-per-line-of-code metric

### Problem

aider-cost popularized cost-per-line as a normalization metric. CodePlane
already has `diff_lines_added`, `diff_lines_removed`, and `total_cost_usd`
per job — the arithmetic exists but is not computed or surfaced.

### Design

#### DB — no schema change

All data exists in `job_telemetry_summary`.

#### Backend — extend `model_comparison` query

Add `cost_per_diff_line` to the existing model comparison SQL:

```sql
CASE WHEN SUM(t.diff_lines_added + t.diff_lines_removed) > 0
    THEN SUM(t.total_cost_usd) / SUM(t.diff_lines_added + t.diff_lines_removed)
    ELSE 0 END AS cost_per_diff_line
```

This column already exists in the `CostByModelRow` TypedDict in
`domain.py` but is not computed in the `model_comparison` query. Add it.

#### Backend — extend scorecard

Add fleet-level cost-per-line to the scorecard response:

```python
# In scorecard computation:
total_cost = sum(b["total_cost_usd"] for b in budget_rows)
total_diff = await self._session.execute(
    text("""
        SELECT COALESCE(SUM(diff_lines_added + diff_lines_removed), 0)
        FROM job_telemetry_summary
        WHERE created_at >= datetime('now', :offset)
    """),
    {"offset": f"-{int(period_days)} days"},
)
total_diff_lines = total_diff.scalar() or 0
cost_per_line = total_cost / total_diff_lines if total_diff_lines > 0 else 0.0
```

#### API — response model updates

`ModelComparisonRow` gains:

```python
cost_per_diff_line: float = 0.0
```

`ScorecardResponse` gains:

```python
cost_per_diff_line: float = 0.0
total_diff_lines: int = 0
```

#### Frontend — `ModelComparison.tsx`

Add **$/line** column to the model comparison table.
Format: `$0.0012` (4 decimal places for small values).

#### Frontend — `BudgetCard.tsx` or new KPI row

Display fleet cost-per-line as a prominent metric:

```
$0.0015 / line of code  (12,340 lines changed)
```

---

## Item 10 — CSV/JSON export from analytics

### Problem

No way to export analytics data for external analysis, compliance reporting,
or team sharing.

### Design

#### Backend — `api/analytics.py`

New export endpoint:

```
GET /analytics/export?period=30&format=csv
GET /analytics/export?period=30&format=json
```

Query parameter `sections` (comma-separated, optional, defaults to all):
`overview`, `models`, `cost-drivers`, `yield`, `observations`.

Implementation:

```python
@router.get("/analytics/export")
async def export_analytics(
    period: int = 30,
    format: Literal["csv", "json"] = "csv",
    sections: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Export analytics data as CSV or JSON."""
    requested = set((sections or "overview,models,cost-drivers").split(","))

    data: dict[str, Any] = {}
    svc = AnalyticsService(session, config)

    if "overview" in requested:
        data["overview"] = await svc.overview(period)
    if "models" in requested:
        data["models"] = await svc.model_comparison(period)
    if "cost-drivers" in requested:
        data["cost_drivers"] = await svc.fleet_cost_summary(period)
    if "yield" in requested:
        data["yield"] = await svc.yield_summary(period)
    if "observations" in requested:
        data["observations"] = await svc.list_observations()

    if format == "json":
        return JSONResponse(content=data)

    # CSV: flatten each section into a sheet-like structure
    output = io.StringIO()
    for section_name, section_data in data.items():
        _write_csv_section(output, section_name, section_data)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="codeplane-analytics-{period}d.csv"'
        },
    )
```

The `_write_csv_section` helper flattens lists of dicts into rows with a
section header separator.

#### Frontend — `AnalyticsScreen.tsx`

Add an export button (download icon) to the analytics toolbar:

```tsx
<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="outline" size="sm">
      <Download size={14} />
      Export
    </Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent>
    <DropdownMenuItem onClick={() => exportAnalytics("csv")}>
      Download CSV
    </DropdownMenuItem>
    <DropdownMenuItem onClick={() => exportAnalytics("json")}>
      Download JSON
    </DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>
```

Implementation triggers a file download via `window.location.href` or
`fetch` + `Blob` + `URL.createObjectURL`:

```typescript
async function exportAnalytics(format: "csv" | "json") {
  const url = `/api/analytics/export?period=${period}&format=${format}`;
  const res = await fetch(url);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `codeplane-analytics.${format}`;
  a.click();
  URL.revokeObjectURL(a.href);
}
```

---

## Item 12 — Conversation category underweighted — flag waste

### Problem

CodeBurn flags sessions with high "conversation" or "brainstorming" activity
ratio as potential cost waste. CodePlane's `communication` activity bucket
captures this but the statistical analysis pipeline doesn't flag outliers.

### What CodeBurn does

`optimize.ts` `detectLowWorthSessions`: flags sessions where total cost is
above a threshold and the ratio of "productive" tools to total is below a
threshold. Assigns impact rating and computes trend (active/improving).

### Design

#### Backend — `statistical_analysis.py`

New detector `_analyse_communication_waste`:

```python
async def _analyse_communication_waste(
    self,
    attr_repo: CostAttributionRepository,
    period_days: int,
) -> list[Observation]:
    """Flag jobs where communication/reasoning cost exceeds a threshold
    fraction of total job cost."""
    rows = await attr_repo.communication_heavy_jobs(period_days)
    # rows: [{job_id, comm_cost, total_cost, comm_pct}, ...]

    flagged = [r for r in rows if r["comm_pct"] > 0.40 and r["total_cost"] > 0.50]

    if not flagged:
        return []

    total_waste = sum(r["comm_cost"] for r in flagged)
    return [Observation(
        category="communication_waste",
        severity="warning" if len(flagged) >= 3 else "info",
        title=f"{len(flagged)} jobs spent >40% of cost on communication/reasoning",
        detail=(
            f"These jobs spent {format_usd(total_waste)} on communication and "
            f"reasoning turns with no file edits or verification. This may "
            f"indicate unclear prompts, excessive back-and-forth, or tasks "
            f"that didn't need an agent."
        ),
        evidence={
            "flagged_jobs": [
                {
                    "job_id": r["job_id"],
                    "comm_cost_usd": round(r["comm_cost"], 4),
                    "total_cost_usd": round(r["total_cost"], 4),
                    "comm_pct": round(r["comm_pct"], 2),
                }
                for r in flagged[:10]  # cap evidence size
            ],
            "total_waste_usd": round(total_waste, 4),
        },
        job_count=len(flagged),
        total_waste_usd=total_waste,
    )]
```

#### Backend — `cost_attribution_repo.py`

New method `communication_heavy_jobs`:

```python
async def communication_heavy_jobs(
    self, period_days: int
) -> list[dict[str, Any]]:
    """Jobs where communication + reasoning cost > 40% of total."""
    result = await self._session.execute(
        text("""
            SELECT
                a.job_id,
                SUM(CASE WHEN a.bucket IN ('communication', 'reasoning')
                    THEN a.cost_usd ELSE 0 END) AS comm_cost,
                SUM(a.cost_usd) AS total_cost,
                CASE WHEN SUM(a.cost_usd) > 0
                    THEN SUM(CASE WHEN a.bucket IN ('communication', 'reasoning')
                        THEN a.cost_usd ELSE 0 END) / SUM(a.cost_usd)
                    ELSE 0 END AS comm_pct
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = 'activity'
                AND j.created_at >= datetime('now', :offset)
            GROUP BY a.job_id
            HAVING comm_pct > 0.30
            ORDER BY comm_cost DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### Integration

Add `_analyse_communication_waste` to the list of analysis passes in
`statistical_analysis.py`'s `run_analysis` method, alongside the existing
6 detectors.

#### API — no new endpoint

The existing `GET /analytics/observations` endpoint already returns all
observations. The new detector writes to the same `cost_observations` table
via `ObservationsRepository.upsert`.

#### Frontend — `ObservationsPanel.tsx`

The existing panel already renders observations from the API. The new
`communication_waste` category appears automatically. Add an icon mapping:

```typescript
const CATEGORY_ICONS: Record<string, LucideIcon> = {
  // ... existing ...
  communication_waste: MessageSquare,
};
```

---

## Item 13 — Hierarchical activity taxonomy (2-level treemap)

### Problem

The analytics dashboard shows 9+ flat activity buckets
(implementation/investigation/verification/git_ops/setup/delegation/overhead/
reasoning/communication plus sub-classifications feature_dev/debugging/
refactoring). Users scan a long list without understanding the high-level
picture: how much was *productive work* vs *preparatory work* vs *pure
overhead*?

No competitor surfaces a hierarchical breakdown. CodeBurn, toktrack, and
aider-cost all show flat lists. A two-level tree is immediately
comprehensible and unique to CodePlane.

### Design

#### Taxonomy

```
├── Productive Work
│   ├── Implementation
│   │   ├── Feature Development
│   │   ├── Debugging
│   │   └── Refactoring
│   ├── Verification
│   └── Git & Commit
├── Preparatory Work
│   ├── Investigation
│   ├── Setup
│   └── Reasoning
└── Overhead
    ├── Communication
    ├── Delegation (coordination cost only — sub-agent direct work is separate)
    ├── Compaction (context window management overhead)
    └── Bookkeeping
```

The top level collapses to three pillars. Each pillar expands to show
its constituent activity buckets with costs and percentages. Compaction
is surfaced from `job_telemetry_summary.tokens_compacted` — this overhead
is currently invisible in the activity breakdown.

#### Classification mapping

```python
_ACTIVITY_TO_PILLAR: dict[str, str] = {
    "implementation": "productive",
    "feature_dev": "productive",
    "debugging": "productive",
    "refactoring": "productive",
    "verification": "productive",
    "git_ops": "productive",
    "investigation": "preparatory",
    "setup": "preparatory",
    "reasoning": "preparatory",
    "communication": "overhead",
    "delegation": "overhead",
    "overhead": "overhead",
}
```

#### DB — no schema change

The hierarchy is a frontend-only grouping over the existing `activity`
dimension. No new attribution rows are written.

#### Backend — no change

The existing `GET /analytics/cost-drivers` and `GET /analytics/latency-drivers`
endpoints return ungrouped `activity` rows. The hierarchy is applied
client-side.

However, a **compaction cost estimate** is added to the scorecard. The
`analytics_service.py` method `scorecard()` is extended to include:

```python
# Compaction overhead: estimate re-ingestion cost from tokens_compacted
compaction_tokens = await summary_repo.sum_compacted_tokens(period_days)
compaction_cost_estimate = compaction_tokens * avg_input_cost_per_token
```

This provides a `compactionCostUsd` field the frontend uses for the
"Compaction" leaf in the overhead pillar.

##### Backend — `telemetry_analytics_repo.py`

New method:

```python
async def sum_compacted_tokens(self, period_days: int) -> int:
    """Total tokens compacted (re-ingested) across all jobs in the period."""
    result = await self._session.execute(
        text("""
            SELECT COALESCE(SUM(t.tokens_compacted), 0) AS total
            FROM job_telemetry_summary t
            JOIN jobs j ON j.id = t.job_id
            WHERE j.created_at >= datetime('now', :offset)
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return int(result.scalar() or 0)
```

#### API — extend `/analytics/scorecard`

Add `compaction_cost_usd: float` to `ScorecardResponse`.

#### Frontend — new `HierarchicalBreakdown.tsx`

A collapsible tree view or treemap visualization. Three top-level rows
(Productive / Preparatory / Overhead), each expandable to show child
buckets. Each row shows:

* Absolute cost (USD)
* Percentage of total
* Bar proportional to share

The component consumes the existing `activity` rows from `CostDriversData`
and groups them client-side using the mapping above.

Treemap mode (toggle): renders the same data as a nested rectangle chart
where area = cost. Productive work dominates visually when things are
healthy; overhead grows visually when there's waste.

---

## Item 14 — File-centric cost attribution (new dimension)

### Problem

All existing attribution dimensions describe *what the agent was doing*
(activity, phase, tool type) but none describe *what it was working on*.
The most natural question a developer asks is "which files are expensive
to maintain?" — and no tool answers it.

CodeBurn, aider-cost, and toktrack are all blind to file-level cost.
CodePlane uniquely stores `job_file_access_log` with `file_path`,
`turn_number`, and `byte_count` — the join to per-turn cost attribution
is direct.

### Design

#### Attribution strategy

Each turn's cost is attributed to the files that turn accessed (from
`job_file_access_log`). If a turn touched N files, the turn's cost is
split equally across those N files. This is a deliberate simplification
— proportional-by-bytes was considered but rejected because LLM cost
correlates with the number of distinct files reasoned about, not byte
volume.

Equal splitting avoids penalizing large files unfairly and is easy to
reason about: "this turn cost $0.30 and touched 3 files, so each file
gets $0.10."

#### DB — new table `job_file_cost`

A denormalized per-job file cost table, written during the attribution
pipeline alongside existing dimension rows.

```sql
CREATE TABLE job_file_cost (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    file_path   TEXT NOT NULL,
    cost_usd    REAL NOT NULL DEFAULT 0.0,
    read_cost   REAL NOT NULL DEFAULT 0.0,
    write_cost  REAL NOT NULL DEFAULT 0.0,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_file_cost_job ON job_file_cost(job_id);
CREATE INDEX idx_file_cost_path ON job_file_cost(file_path);
```

Columns:

* `cost_usd` — total cost attributed to this file in this job
* `read_cost` — portion of cost from turns that *read* this file
* `write_cost` — portion of cost from turns that *wrote* this file
* `turn_count` — how many turns interacted with this file

#### Alembic migration `0035`

```python
"""Add job_file_cost table for file-centric cost attribution."""

revision = "0035"
down_revision = "0034"

def upgrade():
    op.create_table(
        "job_file_cost",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("file_path", sa.String, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("read_cost", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("write_cost", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_file_cost_job", "job_file_cost", ["job_id"])
    op.create_index("idx_file_cost_path", "job_file_cost", ["file_path"])

def downgrade():
    op.drop_table("job_file_cost")
```

#### Backend — `cost_attribution.py`

After computing activity/turn/phase attribution rows, add a file cost
computation block:

```python
# --- File-centric cost attribution ---
file_access_rows = await file_repo.for_job(job_id)
if file_access_rows:
    # Group file accesses by turn
    files_by_turn: dict[int, list[dict]] = defaultdict(list)
    for fa in file_access_rows:
        turn = fa.get("turn_number")
        if turn is not None:
            files_by_turn[int(turn)].append(fa)

    # Attribute each turn's cost equally across its files
    file_costs: dict[str, dict] = defaultdict(
        lambda: {"cost_usd": 0.0, "read_cost": 0.0, "write_cost": 0.0, "turn_count": 0}
    )
    for turn_num, turn_files in files_by_turn.items():
        turn_cost = float(by_turn.get(turn_num, _zero_bucket())["cost_usd"])
        if turn_cost <= 0 or not turn_files:
            continue
        share = turn_cost / len(set(f["file_path"] for f in turn_files))
        seen_files = set()
        for fa in turn_files:
            fp = fa["file_path"]
            if fp not in seen_files:
                seen_files.add(fp)
                file_costs[fp]["cost_usd"] += share
                if fa.get("access_type") == "read":
                    file_costs[fp]["read_cost"] += share
                else:
                    file_costs[fp]["write_cost"] += share
                file_costs[fp]["turn_count"] += 1

    await file_cost_repo.insert_batch(job_id=job_id, rows=[
        {"file_path": fp, **data} for fp, data in file_costs.items()
    ])
```

#### Backend — new `FileCostRepository`

```python
class FileCostRepository(BaseRepository):
    """Read/write for per-job file cost attribution."""

    async def insert_batch(self, *, job_id: str, rows: list[dict]) -> None:
        await self._session.execute(
            text("DELETE FROM job_file_cost WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
        now = datetime.now(UTC).isoformat()
        for row in rows:
            await self._session.execute(
                text("""
                    INSERT INTO job_file_cost
                        (job_id, file_path, cost_usd, read_cost, write_cost,
                         turn_count, created_at)
                    VALUES
                        (:job_id, :file_path, :cost_usd, :read_cost, :write_cost,
                         :turn_count, :now)
                """),
                {"job_id": job_id, **row, "now": now},
            )
        await self._session.flush()

    async def for_job(self, job_id: str) -> list[dict]:
        result = await self._session.execute(
            text("""
                SELECT file_path, cost_usd, read_cost, write_cost, turn_count
                FROM job_file_cost
                WHERE job_id = :job_id
                ORDER BY cost_usd DESC
            """),
            {"job_id": job_id},
        )
        return [dict(r) for r in result.mappings().all()]

    async def fleet_top_files(
        self, *, period_days: int = 30, limit: int = 30
    ) -> list[dict]:
        """Most expensive files across all jobs in the period."""
        result = await self._session.execute(
            text("""
                SELECT
                    fc.file_path,
                    SUM(fc.cost_usd) AS total_cost_usd,
                    SUM(fc.read_cost) AS total_read_cost,
                    SUM(fc.write_cost) AS total_write_cost,
                    SUM(fc.turn_count) AS total_turns,
                    COUNT(DISTINCT fc.job_id) AS job_count
                FROM job_file_cost fc
                JOIN jobs j ON j.id = fc.job_id
                WHERE j.created_at >= datetime('now', :offset)
                GROUP BY fc.file_path
                ORDER BY total_cost_usd DESC
                LIMIT :limit
            """),
            {"offset": f"-{int(period_days)} days", "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]
```

#### API — new endpoint

```
GET /analytics/file-cost?period=30&limit=30
```

Returns:

```python
class FileCostEntry(CamelModel):
    file_path: str
    total_cost_usd: float
    total_read_cost: float
    total_write_cost: float
    total_turns: int
    job_count: int

class FileCostResponse(CamelModel):
    files: list[FileCostEntry]
    period_days: int
```

Also add per-job file cost to the existing `GET /analytics/cost-drivers/{job_id}`
response as `fileCost: list[FileCostEntry]`.

#### Frontend — new `FileCostBreakdown.tsx`

A sorted bar chart showing the top N most expensive files by total cost.
Each bar is stacked: read cost (blue) + write cost (green). Hover tooltip
shows turn count and job count.

The per-job view shows the same chart scoped to a single job, embedded in
the existing cost drivers expandable card.

---

## Item 15 — Outcome-weighted efficiency (cost × yield cross-tab)

### Problem

The yield card (Item 2) shows cost by resolution, and the cost drivers
show cost by activity — but they're separate views. The highest-value
question is the *intersection*: "When jobs fail, where does the money go?
Is it investigation (bad prompt scoping) or implementation (the agent
built the wrong thing)?"

No competitor can answer this because none have both per-turn activity
attribution AND per-job resolution. CodePlane has both.

### Design

#### DB — no schema change

The cross-tab is a join of `job_cost_attribution` (dimension=`activity`)
with `jobs.resolution`. No new tables or columns needed.

#### Backend — `analytics_service.py`

New method:

```python
async def outcome_cost_matrix(
    self, *, period_days: int = 30
) -> list[dict]:
    """Cost breakdown by activity × resolution.

    Returns rows like:
    {"activity": "investigation", "resolution": "failed", "cost_usd": 12.50, "job_count": 5}
    """
    result = await session.execute(
        text("""
            SELECT
                a.bucket AS activity,
                COALESCE(j.resolution, 'running') AS resolution,
                SUM(a.cost_usd) AS cost_usd,
                COUNT(DISTINCT a.job_id) AS job_count
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = 'activity'
                AND j.created_at >= datetime('now', :offset)
            GROUP BY a.bucket, j.resolution
            ORDER BY cost_usd DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### Backend — `cost_attribution_repo.py`

New method:

```python
async def cost_by_activity_and_resolution(
    self, *, period_days: int = 30
) -> list[dict[str, Any]]:
    """Cross-tab: cost by activity bucket × job resolution."""
    result = await self._session.execute(
        text("""
            SELECT
                a.bucket AS activity,
                COALESCE(j.resolution, 'running') AS resolution,
                ROUND(SUM(a.cost_usd), 6) AS cost_usd,
                SUM(a.input_tokens) AS input_tokens,
                SUM(a.output_tokens) AS output_tokens,
                COUNT(DISTINCT a.job_id) AS job_count
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = 'activity'
                AND j.created_at >= datetime('now', :offset)
            GROUP BY a.bucket, j.resolution
            ORDER BY cost_usd DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### API — new endpoint

```
GET /analytics/outcome-matrix?period=30
```

```python
class OutcomeMatrixCell(CamelModel):
    activity: str
    resolution: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    job_count: int

class OutcomeMatrixResponse(CamelModel):
    cells: list[OutcomeMatrixCell]
    period_days: int
    total_waste_usd: float  # sum of cost where resolution in (discarded, failed)
```

The `total_waste_usd` field is pre-computed for headline display.

#### Frontend — new `OutcomeMatrix.tsx`

A heatmap table with:

* **Rows**: activity buckets (investigation, implementation, verification, ...)
* **Columns**: resolution outcomes (merged, pr_created, discarded, failed, cancelled)
* **Cells**: colored by cost intensity (white → red gradient)
* **Cell content**: USD amount + job count

The discarded and failed columns are highlighted with a warning background.
Row and column totals are shown.

A toggle switches between absolute USD and percentage-of-column view
(answering "of failed-job cost, what percentage went to investigation?").

---

## Item 16 — Phase × activity heatmap

### Problem

The `activity_phase` compound dimension already exists in the attribution
pipeline (written as `"activity:phase"` bucket strings). But this data is
only used for narrow inline phase-distribution bars in the per-job cost
driver card. It's never surfaced as a standalone fleet-level analysis.

The question it answers is *temporal*: "When in the job lifecycle does each
activity happen?" Anomalous patterns are immediately visible:

* Heavy investigation during finalization → the agent is lost at the end
* Implementation during environment_setup → premature coding before context
* Verification only in post_completion → testing treated as afterthought

No competitor tracks execution phases at all.

### Design

#### DB — no schema change

The `activity_phase` dimension is already written to `job_cost_attribution`.
Fleet aggregation is a SQL `GROUP BY`.

#### Backend — `cost_attribution_repo.py`

New method:

```python
async def fleet_activity_phase_matrix(
    self, *, period_days: int = 30
) -> list[dict[str, Any]]:
    """Aggregate activity×phase cost across all jobs in the period."""
    result = await self._session.execute(
        text("""
            SELECT
                SUBSTR(a.bucket, 1, INSTR(a.bucket, ':') - 1) AS activity,
                SUBSTR(a.bucket, INSTR(a.bucket, ':') + 1) AS phase,
                ROUND(SUM(a.cost_usd), 6) AS cost_usd,
                SUM(a.input_tokens) AS input_tokens,
                SUM(a.output_tokens) AS output_tokens,
                SUM(a.call_count) AS call_count,
                COUNT(DISTINCT a.job_id) AS job_count
            FROM job_cost_attribution a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.dimension = 'activity_phase'
                AND a.bucket LIKE '%:%'
                AND j.created_at >= datetime('now', :offset)
            GROUP BY activity, phase
            ORDER BY cost_usd DESC
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    return [dict(r) for r in result.mappings().all()]
```

#### API — new endpoint

```
GET /analytics/activity-phase-matrix?period=30
```

```python
class ActivityPhaseCell(CamelModel):
    activity: str
    phase: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    call_count: int
    job_count: int

class ActivityPhaseMatrixResponse(CamelModel):
    cells: list[ActivityPhaseCell]
    period_days: int
```

#### Frontend — new `ActivityPhaseHeatmap.tsx`

A grid heatmap with:

* **Rows**: activity buckets (implementation, investigation, verification, ...)
* **Columns**: execution phases (environment_setup, agent_reasoning,
  verification, finalization, post_completion)
* **Cells**: colored by cost intensity (green → yellow → red gradient)
* **Cell content**: USD amount or percentage

Column headers use short labels: Setup, Active, Verify, Final, Post.
Row headers use the same `formatActivityBucket` helper from MetricsPanelTypes.

An "anomaly highlight" mode outlines cells that deviate from the expected
pattern (e.g., investigation cost in finalization phase exceeding a
fleet-relative threshold). The threshold is the cell's percentage of its
row total — if any non-primary phase exceeds 25% of the activity's total
cost, it's outlined in orange.

---

## Item 17 — Motivation-driven attribution (trail-enriched)

### Problem

All existing attribution classifies cost by *what tools were used*
(file_write → implementation, file_read → investigation). This answers
"how?" but not "why?" — the agent may read a file because the user
asked, because it got confused, or because it's recovering from an error.
These have the same tool fingerprint but different motivations and different
waste profiles.

CodePlane uniquely stores `edit_motivations` (JSON array per span),
`motivation_summary` (per span), and trail node `intent`/`rationale`
fields. No competitor has this data.

This is the highest-differentiation breakdown: classifying cost by the
agent's *reason for acting*, not just the action itself.

### Design

#### Motivation taxonomy

```
├── User-directed work    — edits/reads directly traceable to user prompt keywords
├── Agent exploration     — agent decided to investigate on its own initiative
├── Error recovery        — fixing the agent's own mistakes (retries, failed edits)
├── Test-driven iteration — changes triggered by test failures
├── Context gathering     — reading to understand before acting
└── Plan execution        — following a plan item the agent created
```

#### Classification logic

For each turn, the motivation is determined by examining trail node fields
in priority order:

```python
def _classify_motivation(
    turn_num: int,
    trail_nodes: list[dict],
    turn_context: TurnContext,
) -> str:
    """Classify a turn's motivation from trail node metadata."""
    nodes = [n for n in trail_nodes if n.get("turn_number") == turn_num]

    # Priority 1: Error recovery — is_retry or error_kind present
    if any(n.get("is_retry") or n.get("error_kind") for n in nodes):
        return "error_recovery"

    # Priority 2: Test-driven — shell commands include test runners
    # and the previous turn had a test failure
    shell_cmds = turn_context.get("shell_commands", [])
    if any(classify_shell_command(cmd) == "verification" for cmd in shell_cmds):
        return "test_driven_iteration"

    # Priority 3: Plan execution — trail node has plan_item_id
    if any(n.get("plan_item_id") for n in nodes):
        return "plan_execution"

    # Priority 4: User-directed — turn has no preceding agent turns
    # (first turn or immediately after user message)
    if turn_num <= 1:
        return "user_directed"

    # Priority 5: Context gathering — turn is pure reads, no writes
    cats = set(turn_context.get("tool_categories", []))
    if cats and not (cats & {"file_write", "git_write"}):
        return "context_gathering"

    # Default: agent exploration
    return "agent_exploration"
```

#### DB — no schema change

Motivation is written as a new `dimension = 'motivation'` in the existing
`job_cost_attribution` table. The bucket values are the 6 motivation
categories above.

For latency attribution, the same dimension is added to
`job_latency_attribution`.

#### Backend — `cost_attribution.py`

After computing existing dimensions, add motivation attribution:

```python
# --- Motivation dimension ---
trail_nodes = await trail_repo.get_by_job(job_id, limit=1000)
trail_list = [_trail_to_dict(n) for n in trail_nodes]

by_motivation: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
for turn_num, context in turn_contexts.items():
    motivation = _classify_motivation(turn_num, trail_list, context)
    turn_cost = float(context.get("cost_usd", 0.0) or 0.0)
    turn_in = int(context.get("input_tokens", 0) or 0)
    turn_out = int(context.get("output_tokens", 0) or 0)
    turn_cache_r = int(context.get("cache_read_tokens", 0) or 0)
    turn_cache_w = int(context.get("cache_write_tokens", 0) or 0)
    _accumulate(
        by_motivation[motivation], turn_cost, turn_in, turn_out,
        cache_read=turn_cache_r, cache_write=turn_cache_w, call_count=1,
    )

for bucket, data in by_motivation.items():
    rows.append({"dimension": "motivation", "bucket": bucket, "model": job_model, **data})
```

#### Backend — `latency_attribution.py`

Mirror the motivation dimension in the latency pipeline:

```python
by_motivation: dict[str, list[int]] = defaultdict(list)
motivation_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)

for turn_num, context in turn_contexts.items():
    motivation = _classify_motivation(turn_num, trail_list, context)
    by_motivation[motivation].extend(turn_durations.get(turn_num, []))
    motivation_intervals[motivation].extend(turn_span_intervals.get(turn_num, []))

_build_rows("motivation", by_motivation, motivation_intervals)
```

#### API — extend existing endpoints

Add `motivation` to the `CostDriversData` and `LatencyDriversData` types:

```python
class CostDriversData(CamelModel):
    activity: list[CostAttributionBucket] | None = None
    phase: list[CostAttributionBucket] | None = None
    activity_phase: list[CostAttributionBucket] | None = None
    edit_efficiency: list[CostAttributionBucket] | None = None
    motivation: list[CostAttributionBucket] | None = None  # new
```

The existing `GET /analytics/cost-drivers` and
`GET /analytics/cost-drivers/{job_id}` endpoints return motivation rows
automatically because they query `dimension IN ('activity', 'phase', ...)`
— add `'motivation'` to the filter.

Fleet-level endpoint `GET /analytics/cost-drivers` aggregates motivation
the same way it aggregates activity.

#### Frontend — new `MotivationBreakdown.tsx`

A horizontal stacked bar chart showing the 6 motivation buckets. Each
bucket has a distinct color:

* User-directed: blue
* Agent exploration: purple
* Error recovery: red
* Test-driven iteration: amber
* Context gathering: cyan
* Plan execution: green

The component is placed in the analytics screen alongside the existing
cost drivers card. A toggle switches between cost and latency views.

Label formatting and descriptions:

```typescript
const MOTIVATION_LABELS: Record<string, string> = {
  user_directed: "User-Directed",
  agent_exploration: "Agent Exploration",
  error_recovery: "Error Recovery",
  test_driven_iteration: "Test-Driven Iteration",
  context_gathering: "Context Gathering",
  plan_execution: "Plan Execution",
};

const MOTIVATION_DESCRIPTIONS: Record<string, string> = {
  user_directed: "Work directly responding to the user's prompt",
  agent_exploration: "Agent-initiated investigation or coding",
  error_recovery: "Fixing the agent's own mistakes — retries and error handling",
  test_driven_iteration: "Changes driven by test failures",
  context_gathering: "Reading and searching to build understanding",
  plan_execution: "Executing a plan item the agent created",
};
```

#### Coverage caveat

Motivation classification depends on trail node coverage. Jobs without
enriched trail nodes (older jobs, or jobs where enrichment failed) will
have all turns classified as `agent_exploration` (the default). The
frontend shows a "coverage: X% of jobs have motivation data" indicator
when motivation attribution is displayed, computed from
`trail_nodes.enrichment = 'done'` vs total job count.

---

## Item 18 — Simplified 3-bucket executive view

### Problem

The analytics screen shows 9+ activity categories, 5 phase categories,
multiple sub-classifications, and various derived metrics. For executive
or team-lead audiences, this is overwhelming. The fundamental question
is simple: "Is the AI spending my money well?"

A 3-bucket "traffic light" view answers this instantly. No existing tool
provides this level of simplification.

### Design

#### Taxonomy

| Bucket | Color | Includes | Meaning |
|--------|-------|----------|---------|
| **Building** | Green | implementation, feature_dev, debugging, refactoring, verification, git_ops | Directly productive work that creates or validates code |
| **Thinking** | Blue | investigation, reasoning, setup, communication, context_gathering, plan_execution | Preparatory or supportive work that enables building |
| **Wasted** | Red | retries (retry_cost_usd), failed tool calls (tool_failure_count), discarded/failed job cost, compaction overhead, file re-reads above threshold | Money spent without producing value |

#### Waste calculation

The "Wasted" bucket aggregates from multiple sources:

```python
async def executive_summary(
    self, *, period_days: int = 30
) -> dict:
    """3-bucket executive summary."""
    # 1. Get total cost by activity
    activity_rows = await attr_repo.fleet_cost_by_dimension(
        dimension="activity", period_days=period_days
    )
    building_activities = {
        "implementation", "feature_dev", "debugging", "refactoring",
        "verification", "git_ops",
    }
    thinking_activities = {
        "investigation", "reasoning", "setup", "communication",
    }

    building = sum(r["cost_usd"] for r in activity_rows if r["bucket"] in building_activities)
    thinking = sum(r["cost_usd"] for r in activity_rows if r["bucket"] in thinking_activities)

    # 2. Waste: retry cost + failed job cost + compaction overhead + re-read overhead
    summaries = await summary_repo.fleet_waste_metrics(period_days=period_days)
    retry_waste = summaries["total_retry_cost_usd"]
    failed_job_cost = summaries["failed_discarded_cost_usd"]
    compaction_waste = summaries["compaction_cost_estimate_usd"]
    reread_waste = summaries["reread_cost_estimate_usd"]

    wasted = retry_waste + failed_job_cost + compaction_waste + reread_waste

    # Subtract waste from building/thinking to avoid double-counting
    total = building + thinking + wasted

    return {
        "building_usd": building,
        "thinking_usd": thinking,
        "wasted_usd": wasted,
        "total_usd": total,
        "building_pct": round(building / total * 100, 1) if total > 0 else 0,
        "thinking_pct": round(thinking / total * 100, 1) if total > 0 else 0,
        "wasted_pct": round(wasted / total * 100, 1) if total > 0 else 0,
        "waste_breakdown": {
            "retry_usd": retry_waste,
            "failed_jobs_usd": failed_job_cost,
            "compaction_usd": compaction_waste,
            "rereads_usd": reread_waste,
        },
    }
```

#### Backend — `telemetry_analytics_repo.py`

New method:

```python
async def fleet_waste_metrics(
    self, *, period_days: int = 30
) -> dict[str, float]:
    """Aggregate waste-related metrics across the fleet."""
    result = await self._session.execute(
        text("""
            SELECT
                COALESCE(SUM(t.retry_cost_usd), 0) AS total_retry_cost_usd,
                COALESCE(SUM(
                    CASE WHEN j.resolution IN ('failed', 'discarded')
                    THEN t.total_cost_usd ELSE 0 END
                ), 0) AS failed_discarded_cost_usd,
                COALESCE(SUM(t.tokens_compacted), 0) AS total_tokens_compacted,
                COALESCE(SUM(
                    CASE WHEN t.file_reread_count > t.unique_files_read
                    THEN t.file_reread_count - t.unique_files_read ELSE 0 END
                ), 0) AS excess_rereads
            FROM job_telemetry_summary t
            JOIN jobs j ON j.id = t.job_id
            WHERE j.created_at >= datetime('now', :offset)
        """),
        {"offset": f"-{int(period_days)} days"},
    )
    row = result.mappings().first() or {}
    # Estimate compaction cost: re-ingesting tokens at avg input cost
    compaction_tokens = int(row.get("total_tokens_compacted", 0))
    # Use a conservative estimate: compaction re-sends context at input token rate
    # Actual rate depends on model; use fleet average from pricing
    avg_input_rate = 0.000003  # ~$3/1M tokens — conservative Claude Sonnet-class rate
    compaction_cost = compaction_tokens * avg_input_rate
    # Estimate re-read cost: each excess re-read wastes ~avg_turn_cost / 10
    # (reading is cheap relative to a full turn)
    excess_rereads = int(row.get("excess_rereads", 0))
    reread_cost = excess_rereads * 0.001  # placeholder — refined by per-model pricing

    return {
        "total_retry_cost_usd": float(row.get("total_retry_cost_usd", 0)),
        "failed_discarded_cost_usd": float(row.get("failed_discarded_cost_usd", 0)),
        "compaction_cost_estimate_usd": compaction_cost,
        "reread_cost_estimate_usd": reread_cost,
    }
```

**Note on estimated costs**: The compaction and re-read waste figures are
estimates, not exact costs. The compaction estimate uses a conservative
per-token rate. The re-read estimate uses a fixed per-read overhead. Both
are labeled as estimates in the UI. Future refinement: use the actual
model pricing from the `model` column on attribution rows and the
per-model rates from `tools/update_model_pricing.py`.

#### DB — no schema change

All data comes from existing columns on `job_telemetry_summary` and
`job_cost_attribution`.

#### API — new endpoint

```
GET /analytics/executive-summary?period=30
```

```python
class WasteBreakdown(CamelModel):
    retry_usd: float
    failed_jobs_usd: float
    compaction_usd: float
    rereads_usd: float

class ExecutiveSummaryResponse(CamelModel):
    building_usd: float
    thinking_usd: float
    wasted_usd: float
    total_usd: float
    building_pct: float
    thinking_pct: float
    wasted_pct: float
    waste_breakdown: WasteBreakdown
    period_days: int
```

#### Frontend — new `ExecutiveSummary.tsx`

A single donut chart with three segments:

* **Building** (green) — productive work
* **Thinking** (blue) — preparatory work
* **Wasted** (red) — money without value

Center of the donut shows total spend. Below the donut, each segment
shows its USD amount and percentage.

The "Wasted" segment is expandable: clicking it reveals the waste
breakdown (retries, failed jobs, compaction, re-reads) as a mini bar
chart.

This component is placed at the **top** of the analytics screen, before
all other cards, as the headline metric. It's the first thing users see.

---

## Alembic migration `0034` — combined schema changes

All schema changes from Items 6 and 8 are combined into a single migration:

```python
"""0034 — model column and cache token columns on job_cost_attribution."""

revision = "0034"
down_revision = "0033"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "job_cost_attribution",
        sa.Column("model", sa.String(), nullable=True),
    )
    op.add_column(
        "job_cost_attribution",
        sa.Column("cache_read_tokens", sa.BigInteger(), server_default="0"),
    )
    op.add_column(
        "job_cost_attribution",
        sa.Column("cache_write_tokens", sa.BigInteger(), server_default="0"),
    )
    op.create_index(
        "ix_cost_attribution_model",
        "job_cost_attribution",
        ["model"],
    )


def downgrade():
    op.drop_index("ix_cost_attribution_model")
    op.drop_column("job_cost_attribution", "cache_write_tokens")
    op.drop_column("job_cost_attribution", "cache_read_tokens")
    op.drop_column("job_cost_attribution", "model")
```

---

## Backfill — retrofitting existing data

### Why backfill is safe

`insert_batch` in `cost_attribution_repo.py` does `DELETE` + re-`INSERT`
for each job — it is fully idempotent. Re-running `compute_attribution` on
a job that already has attribution rows simply replaces them with enriched
versions that include the new columns and sub-classifications.

The raw source data (`telemetry_spans`, `jobs.description`,
`jobs.motivation_summary`, `job_telemetry_summary.model`) is immutable after
job completion. Nothing is lost or double-counted.

### What changes for existing rows

| Change | Source of truth for backfill | Affected rows |
|--------|----------------------------|---------------|
| `model` column (Item 6) | `job_telemetry_summary.model` joined via `job_id` | All attribution rows |
| `cache_read_tokens`, `cache_write_tokens` (Item 8) | `telemetry_spans.cache_read_tokens`, `.cache_write_tokens` | All attribution rows (currently 0) |
| `implementation` → `feature_dev`/`refactoring`/`debugging` (Item 3) | `jobs.description`, `jobs.motivation_summary` | Rows with `dimension='activity'` and `bucket='implementation'` |
| Edit efficiency per model (Item 6) | Re-computed from spans + model | Rows with `dimension='edit_efficiency'` |

Items 2, 4, 5, 7, 9, 10, 12 are query-layer or new-endpoint additions
that read from already-existing data — no backfill needed.

### Backfill strategy

A one-time management command re-runs the attribution pipeline for every
completed job that has telemetry spans.

#### CLI command — `backend/cli.py`

```python
@app.command()
def backfill_attribution(
    batch_size: int = typer.Option(50, help="Jobs per commit batch"),
    dry_run: bool = typer.Option(False, help="Count affected jobs without writing"),
):
    """Re-run cost attribution for all completed jobs.

    Safe to run multiple times — insert_batch is idempotent (delete + re-insert).
    Picks up new columns (model, cache tokens) and sub-classifications.
    """
    import asyncio
    asyncio.run(_backfill_attribution(batch_size, dry_run))


async def _backfill_attribution(batch_size: int, dry_run: bool):
    from backend.di import build_session_factory
    from backend.services.cost_attribution import compute_attribution

    session_factory = build_session_factory()

    async with session_factory() as session:
        # Find all jobs that have spans (i.e. completed jobs with telemetry)
        result = await session.execute(
            text("""
                SELECT DISTINCT s.job_id
                FROM telemetry_spans s
                JOIN jobs j ON j.id = s.job_id
                WHERE j.state IN ('completed', 'failed', 'cancelled')
                ORDER BY j.created_at DESC
            """),
        )
        job_ids = [r["job_id"] for r in result.mappings().all()]

    total = len(job_ids)
    if dry_run:
        print(f"Dry run: {total} jobs would be re-attributed")
        return

    print(f"Backfilling attribution for {total} jobs...")
    succeeded = 0
    failed = 0

    for i in range(0, total, batch_size):
        batch = job_ids[i : i + batch_size]
        async with session_factory() as session:
            for job_id in batch:
                try:
                    await compute_attribution(
                        session, job_id, session_factory=session_factory,
                    )
                    succeeded += 1
                except Exception as exc:
                    failed += 1
                    print(f"  FAIL {job_id}: {exc}")
            await session.commit()
        print(f"  [{i + len(batch)}/{total}] committed batch")

    print(f"Done. succeeded={succeeded} failed={failed}")
```

#### Running the backfill

After deploying the migration and updated `compute_attribution`:

```bash
# Dry run — see how many jobs will be affected
uv run python -m backend.cli backfill-attribution --dry-run

# Execute
uv run python -m backend.cli backfill-attribution --batch-size 50
```

#### Performance considerations

* Each job re-attribution reads its spans (typically tens to low hundreds of
  rows) and does one DELETE + N INSERTs. On SQLite this is fast.
* Batching by 50 jobs per commit keeps WAL size manageable.
* The command is resumable — re-running it after a partial failure simply
  re-processes all jobs (idempotent).
* For large instances (thousands of jobs), expect the backfill to take
  minutes, not hours. The pipeline does no LLM calls — it is pure
  SQL reads and writes.

#### Insert batch update

`insert_batch` must be updated to include the new columns. The INSERT
statement becomes:

```python
await self._session.execute(
    text("""
        INSERT INTO job_cost_attribution
            (job_id, dimension, bucket, cost_usd,
             input_tokens, output_tokens, call_count,
             cache_read_tokens, cache_write_tokens, model, created_at)
        VALUES
            (:job_id, :dimension, :bucket, :cost_usd,
             :input_tokens, :output_tokens, :call_count,
             :cache_read_tokens, :cache_write_tokens, :model, :now)
    """),
    {
        "job_id": job_id,
        "dimension": row.get("dimension", ""),
        "bucket": row.get("bucket", ""),
        "cost_usd": row.get("cost_usd", 0.0),
        "input_tokens": row.get("input_tokens", 0),
        "output_tokens": row.get("output_tokens", 0),
        "call_count": row.get("call_count", 0),
        "cache_read_tokens": row.get("cache_read_tokens", 0),
        "cache_write_tokens": row.get("cache_write_tokens", 0),
        "model": row.get("model"),
        "now": now,
    },
)
```

The single-row `insert` method gets the same column additions.

#### Verification

After backfill, verify with spot checks:

```sql
-- Confirm model column is populated
SELECT model, COUNT(*) FROM job_cost_attribution
WHERE model IS NOT NULL AND model != ''
GROUP BY model;

-- Confirm cache tokens are non-zero where expected
SELECT dimension, SUM(cache_read_tokens), SUM(cache_write_tokens)
FROM job_cost_attribution
GROUP BY dimension;

-- Confirm implementation is sub-classified
SELECT bucket, COUNT(*) FROM job_cost_attribution
WHERE dimension = 'activity'
  AND bucket IN ('implementation', 'feature_dev', 'refactoring', 'debugging')
GROUP BY bucket;
```

The `implementation` bucket should have zero rows after backfill (all
reclassified). If any remain, it means the job had no `description` or
`motivation_summary` to classify from — the fallback is to keep the
`implementation` label, which is correct.

---

## Implementation order

Items have dependencies. The recommended order:

| Phase | Items | Rationale |
|-------|-------|-----------|
| 1 | 8, 3 | Token disaggregation and sub-classification are attribution pipeline changes. Must land first because Items 6, 7 depend on the enriched data. |
| 1b | **Backfill** | Run `backfill-attribution` after Phase 1 deploys. Re-computes all historical attribution rows with cache tokens, model, and sub-classifications. Must complete before Phase 2 — model efficiency and cache efficiency queries read from the backfilled data. |
| 2 | 6, 7 | Model efficiency and cache efficiency depend on the `model` column (Item 6→migration) and cache tokens (Item 8). |
| 3 | 9, 2, 1, 12 | Cost-per-line, yield, waste detectors, and communication waste are independent query/analysis additions. Item 1 depends on attribution data from Phase 1b for the exploration detector. |
| 4 | 4, 5, 10, 13, 16 | Repo grouping, budget tracking, export, hierarchical taxonomy (frontend-only), and phase×activity heatmap (existing data). No upstream dependencies. |
| 5 | 14, 15, 18 | File-centric cost (new table + migration), outcome matrix, and executive summary. Item 14 requires migration 0035 and backfill. Items 15 and 18 are query-only over existing data. |
| 6 | 17 | Motivation-driven attribution depends on trail node enrichment coverage. Deploy after trail enrichment is mature. Requires backfill to populate the new `motivation` dimension for historical jobs. |

---

## Testing strategy

Each item must include:

* **Unit tests** for new service methods and repo queries (pytest, async fixtures)
* **Integration tests** for new/modified API endpoints (FastAPI `TestClient`)
* **Frontend tests** not required for data-display-only widgets; required for interactive components (export button, group-by toggle)

Test data: use the existing test fixtures in `backend/tests/conftest.py`.
Create spans/attribution rows with known values and assert computed metrics
match expectations.

---

## Files changed per item (summary)

| Item | Migration | `cost_attribution.py` | `cost_attribution_repo.py` | `analytics_service.py` | `api/analytics.py` | `schemas/telemetry.py` | FE client | FE component |
|------|-----------|----------------------|---------------------------|----------------------|-------------------|----------------------|-----------|-------------|
| 1 | — | — | `unproductive_exploration_jobs` | — | — | — | — | icon mapping in `ObservationsPanel` |
| 2 | — | — | — | `yield_summary` | `/yield` | `YieldResponse` | `fetchYield` | `YieldCard.tsx` |
| 3 | — | `_sub_classify_implementation` | — | — | — | — | — | color/label maps |
| 4 | — | — | `by_dimension_per_repo` | `cost_by_repo_activity` | extend `/cost-drivers` | `RepoCostDriversResponse` | update `fetchFleetCostDrivers` | extend `FleetCostDriverInsights` |
| 5 | — | — | — | `budget_status` | extend `/scorecard` | extend `ScorecardResponse` | update `ScorecardResponse` | extend `BudgetCard.tsx` |
| 6 | **0034** | add `model` to rows | `edit_efficiency_by_model` | `model_efficiency` | `/model-efficiency` | `ModelEfficiencyResponse` | `fetchModelEfficiency` | extend `ModelComparison.tsx` |
| 7 | — | — | `cache_efficiency_by_dimension` | `cache_efficiency` | `/cache-efficiency` | `CacheEfficiencyResponse` | `fetchCacheEfficiency` | `CacheEfficiencyChart.tsx` |
| 8 | **0034** | `CostBucket` + `_accumulate` | `insert_batch`, queries | — | — | extend `CostAttributionBucket` | update bucket type | extend detail rows |
| 9 | — | — | — | extend model_comparison | extend `/model-comparison`, `/scorecard` | extend response models | update types | add column, KPI |
| 10 | — | — | — | — | `/export` | — | `exportAnalytics` | export button |
| 12 | — | — | `communication_heavy_jobs` | — | — | — | — | icon mapping |
| 13 | — | — | — | extend `scorecard` (compaction cost) | extend `/scorecard` | extend `ScorecardResponse` | update types | `HierarchicalBreakdown.tsx` |
| 14 | **0035** | file cost attribution block | — | — | `/file-cost` | `FileCostResponse` | `fetchFileCost` | `FileCostBreakdown.tsx` |
| 15 | — | — | `cost_by_activity_and_resolution` | `outcome_cost_matrix` | `/outcome-matrix` | `OutcomeMatrixResponse` | `fetchOutcomeMatrix` | `OutcomeMatrix.tsx` |
| 16 | — | — | `fleet_activity_phase_matrix` | — | `/activity-phase-matrix` | `ActivityPhaseMatrixResponse` | `fetchActivityPhaseMatrix` | `ActivityPhaseHeatmap.tsx` |
| 17 | — | motivation dimension block | — | — | extend `/cost-drivers` | extend `CostDriversData` | update types | `MotivationBreakdown.tsx` |
| 18 | — | — | — | `executive_summary` | `/executive-summary` | `ExecutiveSummaryResponse` | `fetchExecutiveSummary` | `ExecutiveSummary.tsx` |
