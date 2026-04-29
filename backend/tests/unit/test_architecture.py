"""Architectural boundary test: EventRepository import restrictions.

The trail subsystem is the canonical provenance authority. Only specific
modules are permitted to import EventRepository directly. All other services
must use TrailNodeRepository projections.
"""

from __future__ import annotations

import ast
import pathlib

# Modules that are ALLOWED to import EventRepository
ALLOWED_EVENT_REPO_CONSUMERS = {
    "backend/persistence/event_repo.py",
    "backend/services/trail/service.py",
    "backend/services/trail/node_builder.py",
    "backend/services/runtime_service.py",
    "backend/services/runtime_telemetry.py",
    # save_snapshot_to_disk still uses EventRepository (deferred migration)
    "backend/services/summarization_service.py",
    # Infrastructure wiring and API layers (not provenance consumers)
    "backend/di.py",
    "backend/lifespan.py",
    "backend/api/job_artifacts.py",
    "backend/services/job_service.py",
    "backend/services/sse_manager.py",
}


def test_event_repo_import_boundary():
    """No service outside the allowlist may import EventRepository."""
    violations: list[str] = []
    backend = pathlib.Path("backend")

    for py_file in backend.rglob("*.py"):
        rel = str(py_file).replace("\\", "/")
        if rel in ALLOWED_EVENT_REPO_CONSUMERS:
            continue
        # Skip test files — they can import whatever they need
        if "/tests/" in rel:
            continue

        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [a.name for a in node.names]
                if "event_repo" in module or "EventRepository" in names:
                    violations.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "event_repo" in alias.name:
                        violations.append(f"{rel}:{node.lineno}")

    assert not violations, (
        "EventRepository imported outside allowlist:\n"
        + "\n".join(f"  {v}" for v in sorted(violations))
    )
