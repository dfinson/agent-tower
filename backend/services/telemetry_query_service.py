"""Service layer for job telemetry assembly.

Encapsulates the per-job telemetry query and response construction that
was previously inlined in the ``job_telemetry`` API handler — consistent
with the project convention that route handlers delegate to services.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from backend.models.api_schemas import (
    JobTelemetryResponse,
    TelemetryCostBucket,
    TelemetryCostDrivers,
    TelemetryFileAccess,
    TelemetryFileEntry,
    TelemetryFileStats,
    TelemetryLlmCall,
    TelemetryQuotaSnapshot,
    TelemetryReviewComplexity,
    TelemetryReviewSignals,
    TelemetryToolCall,
    TelemetryTurnEconomics,
)

if TYPE_CHECKING:
    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.job_repo import JobRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

log = structlog.get_logger()

# Review complexity thresholds — calibrated against historical job data:
# >500 diff lines ≈ top-10% by size, >20 turns ≈ extended sessions,
# >15 unique files ≈ cross-cutting changes.
_LARGE_DIFF_LINES = 500
_MANY_TURNS = 20
_MANY_FILES = 15


class TelemetryQueryService:
    """Assembles a ``JobTelemetryResponse`` from the persistence layer."""

    def __init__(
        self,
        cost_repo: CostAttributionRepository,
        file_repo: FileAccessRepository,
        job_repo: JobRepository,
        spans_repo: TelemetrySpansRepository,
        summary_repo: TelemetrySummaryRepository,
    ) -> None:
        self._cost_repo = cost_repo
        self._file_repo = file_repo
        self._job_repo = job_repo
        self._spans_repo = spans_repo
        self._summary_repo = summary_repo

    async def get_telemetry(self, job_id: str) -> JobTelemetryResponse:
        """Build the full telemetry response for *job_id*."""
        summary = await self._summary_repo.get(job_id)
        if summary is None:
            return JobTelemetryResponse(job_id=job_id, available=False)

        job_row = await self._job_repo.get(job_id)
        sdk = job_row.sdk if job_row else ""

        # Parse quota JSON if present
        quota_snapshots_raw = None
        if summary.get("quota_json"):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                quota_snapshots_raw = json.loads(summary["quota_json"])

        # Compute derived fields
        input_tok = summary.get("input_tokens", 0)
        output_tok = summary.get("output_tokens", 0)
        cache_read = summary.get("cache_read_tokens", 0)
        window_size = summary.get("context_window_size", 0)
        current_ctx = summary.get("current_context_tokens", 0)

        # Load span detail for tool/LLM call breakdowns
        spans = await self._spans_repo.list_for_job(job_id)
        attribution_rows = await self._cost_repo.for_job(job_id)
        file_stats = await self._file_repo.reread_stats(job_id)
        top_files = await self._file_repo.most_accessed_files(job_id=job_id)
        tool_calls: list[TelemetryToolCall] = []
        llm_calls: list[TelemetryLlmCall] = []
        for span in spans:
            attrs = span.get("attrs", {})
            if span.get("span_type") == "tool":
                edit_motivations = None
                if span.get("edit_motivations"):
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        edit_motivations = json.loads(span["edit_motivations"])
                tool_calls.append(
                    TelemetryToolCall(
                        name=span["name"],
                        duration_ms=float(span.get("duration_ms", 0)),
                        success=attrs.get("success", True),
                        offset_sec=float(span.get("started_at", 0)),
                        motivation_summary=span.get("motivation_summary"),
                        edit_motivations=edit_motivations,
                    )
                )
            elif span.get("span_type") == "llm":
                llm_calls.append(
                    TelemetryLlmCall(
                        model=span["name"],
                        input_tokens=attrs.get("input_tokens", 0),
                        output_tokens=attrs.get("output_tokens", 0),
                        cache_read_tokens=attrs.get("cache_read_tokens", 0),
                        cache_write_tokens=attrs.get("cache_write_tokens", 0),
                        cost=attrs.get("cost", 0),
                        duration_ms=float(span.get("duration_ms", 0)),
                        is_subagent=attrs.get("is_subagent", False),
                        offset_sec=float(span.get("started_at", 0)),
                        call_count=attrs.get("num_turns", 1),
                    )
                )

        grouped_dimensions: dict[str, list[TelemetryCostBucket]] = {}
        turn_curve: list[TelemetryCostBucket] = []
        for row in attribution_rows:
            bucket = TelemetryCostBucket(
                dimension=row.get("dimension", "unknown"),
                bucket=row.get("bucket", "unknown"),
                cost_usd=float(row.get("cost_usd", 0)),
                input_tokens=int(row.get("input_tokens", 0)),
                output_tokens=int(row.get("output_tokens", 0)),
                call_count=int(row.get("call_count", 0)),
            )
            dimension = str(row.get("dimension", "unknown"))
            grouped_dimensions.setdefault(dimension, []).append(bucket)
            if dimension == "turn":
                turn_curve.append(bucket)

        turn_curve.sort(key=lambda item: int(item.bucket) if item.bucket.isdigit() else 0)

        # Enrich turn curve with activity + tools from raw spans
        self._enrich_turn_curve(turn_curve, spans)

        # For running jobs, compute live duration from created_at instead of
        # the stored 0 which is only finalized when the job completes.
        duration_ms = summary.get("duration_ms", 0)
        if duration_ms == 0 and summary.get("status") == "running" and summary.get("created_at"):
            try:
                created = datetime.fromisoformat(summary["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                duration_ms = int((datetime.now(UTC) - created).total_seconds() * 1000)
            except (ValueError, TypeError):
                log.debug("live_duration_parse_failed", job_id=job_id, exc_info=True)

        # Review signals: test co-modifications
        test_co_mods = await self._spans_repo.test_co_modifications(job_id)

        # Review complexity tier
        signals: list[str] = []
        signal_details: dict[str, dict[str, int | float]] = {}
        diff_lines = int(summary.get("diff_lines_added", 0)) + int(
            summary.get("diff_lines_removed", 0)
        )
        total_turns = int(summary.get("total_turns", 0))
        unique_files = int(file_stats.get("unique_files", 0))
        if diff_lines > _LARGE_DIFF_LINES:
            signals.append("large_diff")
            signal_details["large_diff"] = {"value": diff_lines, "threshold": _LARGE_DIFF_LINES}
        if total_turns > _MANY_TURNS:
            signals.append("many_turns")
            signal_details["many_turns"] = {"value": total_turns, "threshold": _MANY_TURNS}
        if unique_files > _MANY_FILES:
            signals.append("many_files")
            signal_details["many_files"] = {"value": unique_files, "threshold": _MANY_FILES}
        tier = "quick" if not signals else ("deep" if len(signals) >= 3 else "standard")

        # Build quota snapshots if present
        quota_snapshots = None
        if quota_snapshots_raw is not None:
            quota_snapshots = {
                resource: TelemetryQuotaSnapshot(
                    used_requests=snap.get("used_requests", 0),
                    entitlement_requests=snap.get("entitlement_requests", 0),
                    remaining_percentage=snap.get("remaining_percentage", 0),
                    overage=snap.get("overage", 0),
                    overage_allowed=snap.get("overage_allowed", False),
                    is_unlimited=snap.get("is_unlimited", False),
                    reset_date=snap.get("reset_date", ""),
                )
                for resource, snap in quota_snapshots_raw.items()
                if isinstance(snap, dict)
            }

        return JobTelemetryResponse(
            available=True,
            job_id=job_id,
            sdk=sdk,
            model=summary.get("model", ""),
            main_model=summary.get("model", ""),
            duration_ms=duration_ms,
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=input_tok + output_tok + cache_read,
            cache_read_tokens=cache_read,
            cache_write_tokens=summary.get("cache_write_tokens", 0),
            total_cost=float(summary.get("total_cost_usd", 0)),
            context_window_size=window_size,
            current_context_tokens=current_ctx,
            context_utilization=(current_ctx / window_size) if window_size else 0,
            compactions=summary.get("compactions", 0),
            tokens_compacted=summary.get("tokens_compacted", 0),
            tool_call_count=summary.get("tool_call_count", 0),
            total_tool_duration_ms=summary.get("total_tool_duration_ms", 0),
            tool_calls=tool_calls,
            llm_call_count=summary.get("llm_call_count", 0),
            total_llm_duration_ms=summary.get("total_llm_duration_ms", 0),
            llm_calls=llm_calls,
            approval_count=summary.get("approval_count", 0),
            total_approval_wait_ms=summary.get("approval_wait_ms", 0),
            agent_messages=summary.get("agent_messages", 0),
            operator_messages=summary.get("operator_messages", 0),
            premium_requests=float(summary.get("premium_requests", 0)),
            cost_drivers=TelemetryCostDrivers(
                activity=grouped_dimensions.get("activity", []),
                phase=grouped_dimensions.get("phase", []),
                activity_phase=grouped_dimensions.get("activity_phase", []),
                edit_efficiency=grouped_dimensions.get("edit_efficiency", []),
            ),
            turn_economics=TelemetryTurnEconomics(
                total_turns=int(summary.get("total_turns", 0)),
                peak_turn_cost_usd=float(summary.get("peak_turn_cost_usd", 0)),
                avg_turn_cost_usd=float(summary.get("avg_turn_cost_usd", 0)),
                cost_first_half_usd=float(summary.get("cost_first_half_usd", 0)),
                cost_second_half_usd=float(summary.get("cost_second_half_usd", 0)),
                turn_curve=turn_curve,
            ),
            file_access=TelemetryFileAccess(
                stats=TelemetryFileStats(
                    total_accesses=int(file_stats.get("total_accesses") or 0),
                    unique_files=int(file_stats.get("unique_files") or 0),
                    total_reads=int(file_stats.get("total_reads") or 0),
                    total_writes=int(file_stats.get("total_writes") or 0),
                    reread_count=int(file_stats.get("reread_count") or 0),
                ),
                top_files=[
                    TelemetryFileEntry(
                        file_path=str(row.get("file_path", "")),
                        access_count=int(row.get("access_count", 0)),
                        read_count=int(row.get("read_count", 0)),
                        write_count=int(row.get("write_count", 0)),
                    )
                    for row in top_files
                ],
            ),
            quota_snapshots=quota_snapshots,
            review_signals=TelemetryReviewSignals(test_co_modifications=test_co_mods),
            review_complexity=TelemetryReviewComplexity(tier=tier, signals=signals, signal_details=signal_details),
        )

    @staticmethod
    def _enrich_turn_curve(turn_curve: list[TelemetryCostBucket], spans: list[dict]) -> None:
        """Annotate each turn bucket with intent and concrete actions."""
        import json as _json
        from backend.services.cost_attribution import _classify_turn_intent
        from backend.services.tool_classifier import classify_tool

        # Group tool spans by turn
        turns: dict[str, list[dict]] = {}
        for span in spans:
            if span.get("span_type") != "tool":
                continue
            turn = str(span.get("turn_number", ""))
            if turn:
                turns.setdefault(turn, []).append(span)

        def _short_path(p: str) -> str:
            """Strip worktree prefix, keep last 2 path segments."""
            if not p:
                return ""
            # Strip common worktree prefixes
            parts = p.replace("\\", "/").split("/")
            # Find last segment after .codeplane-worktrees/<job>/
            try:
                idx = next(i for i, seg in enumerate(parts) if seg == ".codeplane-worktrees")
                parts = parts[idx + 2:]  # skip worktrees/<job-name>
            except StopIteration:
                pass
            # Keep at most last 2 segments
            if len(parts) > 2:
                parts = parts[-2:]
            return "/".join(parts)

        def _short_cmd(cmd: str) -> str:
            """Extract first meaningful word from a shell command."""
            # Strip cd prefix
            c = cmd.strip()
            if c.startswith("cd ") and "&&" in c:
                c = c.split("&&", 1)[1].strip()
            # Get first word
            word = c.split()[0] if c.split() else c
            # Strip path from command name
            return word.split("/")[-1]

        for bucket in turn_curve:
            turn_spans = turns.get(bucket.bucket, [])
            if not turn_spans:
                bucket.activity = "communication"
                bucket.intent = None
                bucket.actions = []
                continue

            # Extract intent from report_intent spans (use last one as most specific)
            intent = None
            categories: list[str] = []
            shell_commands: list[str] = []
            actions: list[str] = []
            files_edited: list[str] = []
            files_read: list[str] = []
            commands_run: list[str] = []

            for span in turn_spans:
                name = span.get("name", "")
                cat = classify_tool(name)
                categories.append(cat)
                args_raw = span.get("tool_args_json")
                args: dict = {}
                if args_raw:
                    with contextlib.suppress(Exception):
                        args = _json.loads(args_raw)
                        if not isinstance(args, dict):
                            args = {}

                if name == "report_intent":
                    i = args.get("intent", "")
                    if i:
                        intent = i
                elif cat == "file_write":
                    path = args.get("file_path", args.get("path", span.get("tool_target", "")))
                    short = _short_path(path)
                    if short and short not in files_edited:
                        files_edited.append(short)
                elif cat in ("file_read", "search"):
                    path = args.get("file_path", args.get("path", span.get("tool_target", "")))
                    short = _short_path(path)
                    if short and short not in files_read and short not in files_edited:
                        files_read.append(short)
                elif cat == "shell":
                    cmd = args.get("command", args.get("cmd", ""))
                    if cmd:
                        shell_commands.append(cmd)
                        short = _short_cmd(cmd)
                        if short and short not in commands_run:
                            commands_run.append(short)

            # Build action summaries
            if files_edited:
                if len(files_edited) <= 3:
                    actions.append(f"edited {', '.join(files_edited)}")
                else:
                    actions.append(f"edited {', '.join(files_edited[:2])} +{len(files_edited)-2} more")
            if files_read:
                if len(files_read) <= 3:
                    actions.append(f"read {', '.join(files_read)}")
                else:
                    actions.append(f"read {len(files_read)} files")
            if commands_run:
                actions.append(f"ran {', '.join(commands_run[:3])}")

            # Classify activity
            context = {"tool_categories": categories, "shell_commands": shell_commands, "phase": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
            bucket.activity = _classify_turn_intent(context)
            bucket.intent = intent
            bucket.actions = actions
