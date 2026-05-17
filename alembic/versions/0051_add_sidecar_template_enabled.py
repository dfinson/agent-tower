"""Add enabled column to sidecar_templates.

Allows users to disable individual sidecar templates without deleting them.
Existing templates default to enabled (1).

Revision ID: 0051
Revises: 0050
Create Date: 2026-05-17

"""

from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sidecar_templates") as batch_op:
        batch_op.add_column(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    with op.batch_alter_table("sidecar_templates") as batch_op:
        batch_op.drop_column("enabled")
