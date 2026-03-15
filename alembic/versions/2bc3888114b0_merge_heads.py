"""merge_heads

Revision ID: 2bc3888114b0
Revises: a3c7e1f2d4b6, d2e3f4a5b6c7
Create Date: 2026-03-15 17:23:41.167827

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "2bc3888114b0"
down_revision: str | Sequence[str] | None = ("a3c7e1f2d4b6", "d2e3f4a5b6c7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
