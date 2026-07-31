"""TraceForge classification engine seam (P2).

Builds CodePlane's overlaid TraceForge classification engine once and exposes it
to the governance pipelines. The overlay is merged on top of TraceForge's
built-in defaults and passed explicitly as ``engine=`` to every governance
pipeline, so classification is deterministic regardless of process cwd and never
mutates TraceForge's global default engine.

The former ``derive_properties`` projection (TraceForge classification →
CodePlane ``(reversible, contained)``) was retired in the P5 wholesale governance
adoption: governance now classifies each event **natively** inside the pipeline
via this same engine (``GovernancePipeline.enrich_event``), so there is no
CodePlane-side projection to maintain.
"""

from __future__ import annotations

import functools
from pathlib import Path

from traceforge.classify.config import ClassificationEngine, load_config

_OVERLAY_PATH = Path(__file__).parent / "data" / "traceforge_overlay.yaml"


@functools.lru_cache(maxsize=1)
def _engine() -> ClassificationEngine:
    """Build (once) the CodePlane-overlaid classification engine."""
    return ClassificationEngine(load_config(_OVERLAY_PATH, merge_defaults=True))


def tf_engine() -> ClassificationEngine:
    """CodePlane-overlaid classification engine feeding the governance pipelines.

    This is the P2 classification seam: a single shared engine wired into every
    per-preset :class:`~traceforge.governance.GovernancePipeline`.
    """
    return _engine()
