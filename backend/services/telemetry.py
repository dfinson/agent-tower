"""OTEL-native telemetry for CodePlane.

Provides OpenTelemetry instruments (counters, histograms, gauges) that agent
adapters call directly.  An in-process ``InMemoryMetricReader`` is always
active so the API can serve live telemetry with zero config.  An optional
OTLP exporter can be activated by setting ``OTEL_EXPORTER_ENDPOINT`` to push
to Grafana / Jaeger / Prometheus.

Adapters import the instruments and call them with standard OTEL attributes::

    from backend.services.telemetry import tokens_input, llm_duration, tracer

    attrs = {"job_id": jid, "sdk": "copilot", "model": "gpt-4o"}
    tokens_input.add(500, attrs)
    llm_duration.record(1200.0, {**attrs, "is_subagent": False})
"""

from __future__ import annotations

import os

try:
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _HAS_OTEL = True
except ImportError:  # pragma: no cover
    _HAS_OTEL = False

# ---------------------------------------------------------------------------
# Providers — always in-process; optionally export via OTLP.
# Created lazily by init_telemetry() so importing this module does not
# mutate global OTEL state as a side-effect.
# ---------------------------------------------------------------------------

if _HAS_OTEL:
    _memory_reader = InMemoryMetricReader()
    _span_exporter = InMemorySpanExporter()
else:  # pragma: no cover
    _memory_reader = None  # type: ignore[assignment]
    _span_exporter = None  # type: ignore[assignment]

_initialised = False
meter_provider: MeterProvider | None = None  # type: ignore[type-arg]
tracer_provider: TracerProvider | None = None  # type: ignore[type-arg]


def init_telemetry() -> None:
    """Configure OTEL providers and register them globally.

    Safe to call more than once — subsequent calls are no-ops.
    Must be called during application startup (e.g. from lifespan) before
    any telemetry instruments are used.
    """
    global _initialised, meter_provider, tracer_provider  # noqa: PLW0603

    if _initialised:
        return

    if not _HAS_OTEL:
        _initialised = True
        return

    metric_readers: list[MetricReader] = [_memory_reader]
    otlp_span_processor = None

    endpoint = os.environ.get("OTEL_EXPORTER_ENDPOINT", "")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # type: ignore[import-not-found]
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            metric_readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint)))
            otlp_span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        except ImportError:
            pass

    meter_provider = MeterProvider(metric_readers=metric_readers)
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
    if otlp_span_processor is not None:
        tracer_provider.add_span_processor(otlp_span_processor)

    metrics.set_meter_provider(meter_provider)
    trace.set_tracer_provider(tracer_provider)

    _initialised = True


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

if _HAS_OTEL:
    meter = metrics.get_meter("codeplane")
    tracer = trace.get_tracer("codeplane")
else:  # pragma: no cover
    from unittest.mock import MagicMock as _MagicMock

    meter = _MagicMock()
    tracer = _MagicMock()

# Counters (monotonic, incremented per event)
tokens_input = meter.create_counter("cp.tokens.input", unit="tokens", description="Input tokens consumed")
tokens_output = meter.create_counter("cp.tokens.output", unit="tokens", description="Output tokens produced")
tokens_cache_read = meter.create_counter("cp.tokens.cache_read", unit="tokens", description="Cache-read input tokens")
tokens_cache_write = meter.create_counter(
    "cp.tokens.cache_write", unit="tokens", description="Cache-write input tokens"
)
cost_usd = meter.create_counter("cp.cost", unit="USD", description="Cost in USD")
compactions_counter = meter.create_counter("cp.compactions", description="Context compaction events")
tokens_compacted = meter.create_counter(
    "cp.tokens.compacted", unit="tokens", description="Tokens reclaimed via compaction"
)
messages_counter = meter.create_counter("cp.messages", description="Messages exchanged")
premium_requests_counter = meter.create_counter("cp.premium_requests", description="Copilot premium requests consumed")
approvals_counter = meter.create_counter("cp.approvals", description="Approval requests")

# Histograms (latency distributions — auto p50/p95/p99)
llm_duration = meter.create_histogram("cp.llm.duration", unit="ms", description="LLM call duration")
tool_duration = meter.create_histogram("cp.tool.duration", unit="ms", description="Tool call duration")
approval_wait = meter.create_histogram("cp.approval.wait", unit="ms", description="Approval wait time")

# Gauges (point-in-time values)
context_tokens_gauge = meter.create_gauge("cp.context.tokens", description="Current context window token count")
context_window_gauge = meter.create_gauge("cp.context.window_size", description="Max context window size")
quota_used_gauge = meter.create_gauge("cp.quota.used", description="Copilot quota used requests")
quota_entitlement_gauge = meter.create_gauge("cp.quota.entitlement", description="Copilot quota entitlement")
quota_remaining_gauge = meter.create_gauge("cp.quota.remaining_pct", unit="%", description="Copilot quota remaining %")

# ---------------------------------------------------------------------------
# Per-job span tracking — root span per job for waterfall views
# ---------------------------------------------------------------------------

_job_spans: dict[str, "trace.Span"] = {}  # type: ignore[type-arg]

# Safety cap — prevent unbounded growth if end_job_span is never called
_JOB_SPANS_MAX = 200


def start_job_span(
    job_id: str,
    sdk: str,
    model: str = "",
    repo: str = "",
    branch: str = "",
) -> None:
    """Create a root span for a job run."""
    # Evict oldest entries if over the safety cap
    while len(_job_spans) >= _JOB_SPANS_MAX:
        oldest_key = next(iter(_job_spans))
        stale = _job_spans.pop(oldest_key)
        stale.end()
    span = tracer.start_span(
        "cp.job",
        attributes={
            "job_id": job_id,
            "sdk": sdk,
            "model": model,
            "repo": repo,
            "branch": branch,
        },
    )
    _job_spans[job_id] = span


def end_job_span(job_id: str) -> None:
    """End the root span for a job run."""
    span = _job_spans.pop(job_id, None)
    if span is not None:
        span.end()


# ---------------------------------------------------------------------------
# Public accessors for API layer
# ---------------------------------------------------------------------------


def get_memory_reader() -> InMemoryMetricReader | None:  # type: ignore[type-arg]
    """Return the in-memory metric reader for live API queries."""
    return _memory_reader


def get_span_exporter() -> InMemorySpanExporter | None:  # type: ignore[type-arg]
    """Return the in-memory span exporter for live trace queries."""
    return _span_exporter
