"""Add custom metrics and metrics chat tables.

Supports the chat-driven metrics composer: users ask natural language
questions about telemetry data, the system generates SQL queries,
executes them, and renders visualizations.  Users can pin results as
permanent dashboard tiles.

Revision ID: 0048
Revises: 0047
Create Date: 2026-05-14

"""

from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_metrics",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("sql", sa.Text, nullable=False),
        sa.Column("viz", sa.String, nullable=False),
        sa.Column("viz_config_json", sa.Text, nullable=True),
        sa.Column("period_relative", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("pin_dashboard", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("pin_job_panel", sa.Boolean, nullable=False, server_default="0"),
        # Alert
        sa.Column("alert_enabled", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("alert_op", sa.String, nullable=True),
        sa.Column("alert_value", sa.Float, nullable=True),
        sa.Column("alert_severity", sa.String, nullable=True),
        sa.Column("alert_cooldown_hours", sa.Integer, nullable=True, server_default="24"),
        # Display
        sa.Column("tile_size", sa.String, nullable=False, server_default="1x1"),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        # Context
        sa.Column("original_question", sa.Text, nullable=True),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    op.create_table(
        "metrics_chat_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("condensed_summary", sa.Text, nullable=True),
        sa.Column("viz_data_json", sa.Text, nullable=True),
        sa.Column("sql_queries_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "idx_chat_conversation", "metrics_chat_messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_chat_conversation", table_name="metrics_chat_messages")
    op.drop_table("metrics_chat_messages")
    op.drop_table("custom_metrics")
