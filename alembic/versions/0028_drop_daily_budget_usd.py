"""Drop unused daily_budget_usd column from policy_config."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("policy_config") as batch_op:
        batch_op.drop_column("daily_budget_usd")


def downgrade() -> None:
    with op.batch_alter_table("policy_config") as batch_op:
        batch_op.add_column(sa.Column("daily_budget_usd", sa.Float, nullable=True))
