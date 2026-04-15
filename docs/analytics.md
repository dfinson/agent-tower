---
hide:
  - navigation
---

# Analytics & Cost Tracking

CodePlane tracks every token, tool call, and dollar across all jobs — giving you fleet-wide visibility into what your coding agents cost and how they perform. Open the analytics dashboard with **Alt+A**.

<div class="screenshot-desktop" markdown>
![Analytics Dashboard](images/screenshots/desktop/analytics-dashboard.png)
</div>

<div class="screenshot-mobile" markdown>
![Analytics Dashboard — Mobile](images/screenshots/mobile/analytics-dashboard.png)
</div>

---

## Scorecard

The scorecard is the top-level summary. It shows per-SDK budget totals, job activity breakdown, and daily cost trends over a configurable period (7–365 days).

<div class="screenshot-desktop" markdown>
![Scorecard](images/screenshots/desktop/analytics-scorecard.png)
</div>

<div class="screenshot-mobile" markdown>
![Scorecard — Mobile](images/screenshots/mobile/analytics-scorecard.png)
</div>

- **Budget by SDK** — Total spend for each SDK (Copilot, Claude, etc.) with cost trends
- **Activity breakdown** — Jobs by resolution: running, merged, PR created, discarded, failed, cancelled
- **Copilot quota** — If you use Copilot, the scorecard tracks premium request consumption and alerts when quota exceeds 80%
- **Daily cost trend** — Area chart showing spend over time

!!! tip "Understanding costs"
    For subscription plans (like Claude Max or Copilot Business), CodePlane shows what the same usage **would cost at API rates**. This gives you a consistent cost metric for comparing models and optimizing agent behavior, even when you're on a flat-rate plan.

---

## Model Comparison

Compare models head-to-head on cost, speed, and outcomes.

<div class="screenshot-desktop" markdown>
![Model Comparison](images/screenshots/desktop/analytics-model-comparison.png)
</div>

<div class="screenshot-mobile" markdown>
![Model Comparison — Mobile](images/screenshots/mobile/analytics-model-comparison.png)
</div>

| Metric | Description |
|--------|-------------|
| **Avg Cost** | Average USD per job for each model |
| **Avg Duration** | Average job runtime |
| **Cost/min** | Spend efficiency — lower is better |
| **Cost/turn** | How much each agent turn costs on average |
| **Resolution rates** | Per-model breakdown of merged / PR'd / discarded / failed |

Filter by repository to compare model performance on specific codebases.

---

## Repository Breakdown

See which repos drive the most spend and activity.

<div class="screenshot-desktop" markdown>
![Repository Breakdown](images/screenshots/desktop/analytics-repo-breakdown.png)
</div>

<div class="screenshot-mobile" markdown>
![Repository Breakdown — Mobile](images/screenshots/mobile/analytics-repo-breakdown.png)
</div>

- Cost, job count, and token totals per repository
- Tool calls and average job duration
- Premium request consumption (Copilot)

---

## Tool Health

Monitor the reliability and latency of every tool your agents use.

<div class="screenshot-desktop" markdown>
![Tool Health](images/screenshots/desktop/analytics-tool-health.png)
</div>

<div class="screenshot-mobile" markdown>
![Tool Health — Mobile](images/screenshots/mobile/analytics-tool-health.png)
</div>

- **Call counts** — How often each tool is invoked
- **Failure rate** — Percentage of calls that errored (flagged when ≥20%, critical at ≥50%)
- **Latency** — Average, p50, p95, and p99 durations
- **Tool categories** — file_write, file_read, file_search, git, shell, browser, agent, system

---

## Cost Drivers

Identify which jobs, models, and repos contribute the most to your spend.

<div class="screenshot-desktop" markdown>
![Cost Drivers](images/screenshots/desktop/analytics-cost-drivers.png)
</div>

<div class="screenshot-mobile" markdown>
![Cost Drivers — Mobile](images/screenshots/mobile/analytics-cost-drivers.png)
</div>

---

## Token & Cache Metrics

Every job tracks token usage in detail:

- **Input tokens** and **output tokens** (separately)
- **Cache read tokens** and **cache write tokens** (prompt caching)
- **Cache hit rate** — percentage of input tokens served from cache
- Per-model and per-repo token aggregations

---

## Daily Spend Limit

Set a personal daily budget in your config:

```yaml
telemetry:
  daily_spend_limit_usd: 10.00
```

When configured, the Budget card shows a progress bar for today's spend vs. your limit. Warnings appear when you cross 80%.

---

## Observations (Smart Alerts)

CodePlane runs statistical analysis across your jobs to surface actionable cost observations:

| Detector | What it catches |
|----------|----------------|
| **File rereads** | Files read excessively across jobs (≥10 reads, ≥3 jobs, >10KB total) |
| **Tool failures** | Tools with ≥20% failure rate across ≥10 calls |
| **Turn escalation** | Jobs where 2nd-half cost is ≥2× 1st-half and ≥$0.50 |
| **Retry waste** | Tools retried ≥10% of the time |
| **Compaction storms** | Jobs with ≥5 context compactions |
| **Cache regression** | Cache hit rate drops ≥15pp vs. prior week |

Observations appear as alert banners at the top of the analytics page. Dismiss them individually once reviewed.

---

## CSV Export

Tables in the analytics dashboard (Jobs, Model Comparison) include a **CSV** button that exports the visible data for use in spreadsheets or external analysis tools.

---

## Hub Architecture (Future)

CodePlane is designed as a **personal-first** tool. Each instance runs locally with its own SQLite database. For teams that want aggregate visibility, a future **CodePlane Hub** will accept telemetry pushes from personal instances:

- Each instance has an auto-generated `instance_id` (in `telemetry` config)
- The `JobTelemetryReport` schema defines the per-job payload
- Instances push completed-job summaries to the Hub endpoint
- The Hub aggregates fleet-wide analytics without accessing source code

This is not yet implemented — the schema and instance ID are in place as foundations.
