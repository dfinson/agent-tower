"""Merge 0012_add_parent_job_id and 0012_error_kind heads.

Revision ID: 0013_merge_parent_job_and_error_kind
Revises: 0012_add_parent_job_id, 0012_error_kind
Create Date: 2026-03-27

"""

from typing import Sequence, Union


revision: str = "0013_merge_parent_job_and_error_kind"
down_revision: tuple = ("0012_add_parent_job_id", "0012_error_kind")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
