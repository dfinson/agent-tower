"""Fix telemetry summary composite key for ON CONFLICT clause.

The model declares (job_id, session_kind) as composite PK but the
physical table only has job_id as PK because SQLite cannot alter PKs.
Recreate the table via batch_alter_operations so the PK is
``(job_id, session_kind)`` and the ON CONFLICT clause works.

Revision ID: 0050
Revises: 0049
Create Date: 2026-05-17

"""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the unique index if it was previously created (idempotent).
    with op.batch_alter_table("job_telemetry_summary") as batch_op:
        try:
            batch_op.drop_index("uq_telemetry_summary_job_session")
        except Exception:
            pass

    # Recreate the table with composite PK (job_id, session_kind).
    # batch_alter_table copies data, rebuilds with the new schema.
    naming = {"pk": "pk_%(table_name)s"}
    with op.batch_alter_table(
        "job_telemetry_summary",
        naming_convention=naming,
        recreate="always",
    ) as batch_op:
        batch_op.alter_column("job_id", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("session_kind", existing_type=sa.String(), nullable=False,
                              server_default="job")
        batch_op.create_primary_key("pk_job_telemetry_summary", ["job_id", "session_kind"])


def downgrade() -> None:
    naming = {"pk": "pk_%(table_name)s"}
    with op.batch_alter_table(
        "job_telemetry_summary",
        naming_convention=naming,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key("pk_job_telemetry_summary", ["job_id"])
