"""Add notes column to approvals table.

Revision ID: 0047
Revises: 0046
Create Date: 2026-05-14

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "notes")
