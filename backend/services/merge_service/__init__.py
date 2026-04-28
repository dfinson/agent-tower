"""Post-completion merge-back orchestration (package)."""

from backend.services.merge_service._service import MergeService
from backend.services.merge_service._types import MergeResult, MergeStatus

__all__ = ["MergeResult", "MergeService", "MergeStatus"]
