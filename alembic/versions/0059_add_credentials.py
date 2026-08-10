"""Add credentials and tracker_links tables (Story 3.1, AD-6).

``credentials`` is a global, Project-independent table for registered
integration accounts (provider, label, base_url, PAT encrypted at rest by the
application, never in this migration or in plaintext). ``tracker_links`` is
added as the referential-integrity anchor Story 3.1's delete-blocked-while-
referenced rule needs (AC2); ``project_id`` is a plain string column, not a
foreign key, since the Project entity does not exist yet. No data is attached
to ``tracker_links`` by this story — that is Story 3.2's scope.

Revision ID: 0059
Revises: 0058
"""

import sqlalchemy as sa

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "tracker_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("credential_id", sa.String(), sa.ForeignKey("credentials.id"), nullable=False),
        sa.Column("external_ref", sa.String(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_tracker_links_credential_id", "tracker_links", ["credential_id"])


def downgrade() -> None:
    op.drop_index("ix_tracker_links_credential_id", table_name="tracker_links")
    op.drop_table("tracker_links")
    op.drop_table("credentials")
