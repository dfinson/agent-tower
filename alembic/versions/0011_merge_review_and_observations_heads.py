"""Merge review-state and cost-observation migration heads.

Revision ID: 0011_merge_review_and_observations_heads
Revises: 0008_review_completed_states, 0010_observations
Create Date: 2026-03-26

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "0011_merge_review_and_observations_heads"
down_revision: Union[tuple[str, str], None] = (
    "0008_review_completed_states",
    "0010_observations",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass