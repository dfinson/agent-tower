"""Add diff_additions and diff_deletions to trail_nodes.

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trail_nodes", sa.Column("diff_additions", sa.Integer, nullable=True))
    op.add_column("trail_nodes", sa.Column("diff_deletions", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("trail_nodes", "diff_deletions")
    op.drop_column("trail_nodes", "diff_additions")
