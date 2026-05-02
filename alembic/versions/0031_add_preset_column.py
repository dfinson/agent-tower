"""Add preset column to jobs table, replacing permission_mode.

The new action policy system uses presets (autonomous/supervised/strict) instead
of the old permission_mode (full_auto/observe_only/review_and_approve).  This
migration adds the preset column and backfills it from existing permission_mode
values.  The permission_mode column is kept for backward compatibility with
older code paths but is no longer the source of truth.
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

# Old permission_mode → new preset mapping
_MODE_TO_PRESET = {
    "full_auto": "autonomous",
    "observe_only": "strict",
    "review_and_approve": "supervised",
    # Legacy names from pre-0014 migration
    "auto": "autonomous",
    "read_only": "strict",
    "approval_required": "supervised",
}


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column("preset", sa.String(), nullable=True),
        )

    # Backfill preset from permission_mode
    conn = op.get_bind()
    jobs = conn.execute(sa.text("SELECT id, permission_mode FROM jobs WHERE preset IS NULL"))
    for row in jobs:
        preset = _MODE_TO_PRESET.get(row[1], "supervised")
        conn.execute(
            sa.text("UPDATE jobs SET preset = :preset WHERE id = :id"),
            {"preset": preset, "id": row[0]},
        )

    # Set default for any remaining NULLs and make non-nullable
    conn.execute(sa.text("UPDATE jobs SET preset = 'supervised' WHERE preset IS NULL"))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("preset", nullable=False, server_default="supervised")


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("preset")
