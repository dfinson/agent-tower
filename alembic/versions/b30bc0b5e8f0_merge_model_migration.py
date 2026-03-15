"""merge_model_migration

Revision ID: b30bc0b5e8f0
Revises: 2bc3888114b0, c3d4e5f6a7b8
Create Date: 2026-03-15 17:53:20.217439

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b30bc0b5e8f0"
down_revision: str | Sequence[str] | None = ("2bc3888114b0", "c3d4e5f6a7b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
