"""Action policy router — central decision point for every agent action.

classify → check trust → decide (observe / checkpoint / gate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from backend.services.action_policy.batcher import BatchResolution, BatchResult
from backend.services.action_policy.classifier import (
    Action,
    Classification,
    CostContext,
    RepoPolicy,
    Tier,
    classify,
)

if TYPE_CHECKING:
    from backend.services.action_policy.batcher import ApprovalBatcher
    from backend.services.action_policy.checkpoint_service import CheckpointService
    from backend.services.action_policy.trust_store import TrustStore

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of routing an action through the policy engine."""

    tier: Tier
    proceed: bool
    checkpoint_ref: str | None = None
    batch_id: str | None = None
    trusted: bool = False
    classification: Classification | None = None


class PolicyRouter:
    """Central routing function: classify → check trust → decide."""

    def __init__(
        self,
        checkpoint_service: CheckpointService,
        trust_store: TrustStore,
        batcher: ApprovalBatcher,
    ) -> None:
        self._checkpoint = checkpoint_service
        self._trust = trust_store
        self._batcher = batcher

    async def route(
        self,
        action: Action,
        policy: RepoPolicy,
        *,
        cwd: str | None = None,
        cost: CostContext | None = None,
    ) -> Decision:
        """Route an action through classification → trust → approval.

        Returns a Decision indicating whether the action can proceed.
        For gate-tier actions without trust coverage, this blocks until
        the operator resolves the batch.
        """
        classification = classify(action, policy, cost=cost)
        tier = classification.tier

        # 1. Observe: no interruption
        if tier == Tier.observe:
            return Decision(
                tier=tier,
                proceed=True,
                classification=classification,
            )

        # 2. Checkpoint: create savepoint, then proceed
        if tier == Tier.checkpoint:
            checkpoint_ref = None
            if cwd:
                checkpoint_ref = await self._checkpoint.create(
                    action.job_id or "",
                    classification.reason,
                    cwd=cwd,
                )
            return Decision(
                tier=tier,
                proceed=True,
                checkpoint_ref=checkpoint_ref,
                classification=classification,
            )

        # 3. Gate tier: check trust grants
        if self._trust.covers(action):
            checkpoint_ref = None
            if cwd:
                checkpoint_ref = await self._checkpoint.create(
                    action.job_id or "",
                    classification.reason,
                    cwd=cwd,
                )
            log.debug("gate_bypassed_by_trust", action_kind=action.kind)
            return Decision(
                tier=tier,
                proceed=True,
                checkpoint_ref=checkpoint_ref,
                trusted=True,
                classification=classification,
            )

        # 4. Gate tier, no trust: checkpoint + submit to batcher, block
        checkpoint_ref = None
        if cwd:
            checkpoint_ref = await self._checkpoint.create(
                action.job_id or "",
                classification.reason,
                cwd=cwd,
            )

        result: BatchResult = await self._batcher.submit_and_wait(
            action.job_id or "",
            action,
            classification,
            checkpoint_ref or "",
        )

        proceed = result.resolution in (BatchResolution.approved, BatchResolution.partial)
        return Decision(
            tier=tier,
            proceed=proceed,
            checkpoint_ref=checkpoint_ref,
            batch_id=None,  # batch_id tracked by batcher
            classification=classification,
        )

    def cleanup_job(self, job_id: str) -> None:
        """Clean up router state for a completed/failed job."""
        self._checkpoint.cleanup_job(job_id)
        self._batcher.cleanup_job(job_id)
