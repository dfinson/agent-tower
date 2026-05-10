---
title: "Cost Analytics Enhancements — Design Document"
description: "End-to-end design for 10 cost analytics improvements derived from competitive audit of CodeBurn, toktrack, aider-cost, and other OSS token-spend analysis tools."
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

This document specifies 10 enhancements to CodePlane's cost analytics subsystem.
Each item is traced from competitive research (primarily CodeBurn, toktrack,
aider-cost) through every layer: DB schema, Alembic migration, backend services,
API endpoints, Pydantic response models, frontend API client, and React UI
components.

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
| 3 | 9, 2, 12 | Cost-per-line, yield, and communication waste are independent query/analysis additions. |
| 4 | 4, 5, 10 | Repo grouping, budget tracking, and export are additive features with no upstream dependencies. |

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
