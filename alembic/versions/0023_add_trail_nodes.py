"""Add trail_nodes table for agent audit trail.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trail_nodes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("anchor_seq", sa.Integer, nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("deterministic_kind", sa.String(20), nullable=True),
        sa.Column("phase", sa.String(30), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrichment", sa.String(10), nullable=False, server_default="pending"),
        # Intent (populated by enrichment, nullable)
        sa.Column("intent", sa.Text, nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("outcome", sa.Text, nullable=True),
        # Anchors (populated deterministically)
        sa.Column("step_id", sa.String(36), nullable=True),
        sa.Column("span_ids", sa.Text, nullable=True),  # JSON array
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("files", sa.Text, nullable=True),  # JSON array
        sa.Column("start_sha", sa.String(40), nullable=True),
        sa.Column("end_sha", sa.String(40), nullable=True),
        # Edges
        sa.Column("supersedes", sa.String(36), nullable=True),
        sa.Column("tags", sa.Text, nullable=True),  # JSON array
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trail_nodes_job_id", "trail_nodes", ["job_id"])
    op.create_index("ix_trail_nodes_job_seq", "trail_nodes", ["job_id", "seq"])
    op.create_index("ix_trail_nodes_display_order", "trail_nodes", ["job_id", "anchor_seq", "seq"])
    op.create_index("ix_trail_nodes_parent", "trail_nodes", ["parent_id"])
    op.create_index("ix_trail_nodes_kind", "trail_nodes", ["job_id", "kind"])
    op.create_index("ix_trail_nodes_enrichment", "trail_nodes", ["job_id", "enrichment"])


def downgrade() -> None:
    op.drop_table("trail_nodes")
