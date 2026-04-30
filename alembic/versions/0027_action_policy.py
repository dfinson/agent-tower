"""Action policy DB schema: presets, rules, trust grants, MCP server configs.

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Singleton policy config ---
    op.create_table(
        "policy_config",
        sa.Column("id", sa.Integer, primary_key=True, default=1),
        sa.Column("preset", sa.String(20), nullable=False, server_default="supervised"),
        sa.Column("batch_window_seconds", sa.Float, nullable=False, server_default="5.0"),
        sa.Column("daily_budget_usd", sa.Float, nullable=True),
        sa.CheckConstraint("id = 1", name="ck_policy_config_singleton"),
        sa.CheckConstraint(
            "preset IN ('autonomous', 'supervised', 'strict')",
            name="ck_policy_config_preset",
        ),
    )
    # Seed the singleton row
    op.execute(
        "INSERT INTO policy_config (id, preset, batch_window_seconds) "
        "VALUES (1, 'supervised', 5.0)"
    )

    # --- Path rules ---
    op.create_table(
        "path_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("path_pattern", sa.Text, nullable=False, unique=True),
        sa.Column(
            "tier", sa.String(12), nullable=False,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "tier IN ('observe', 'checkpoint', 'gate')",
            name="ck_path_rules_tier",
        ),
    )

    # --- Action rules ---
    op.create_table(
        "action_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_pattern", sa.Text, nullable=False),
        sa.Column(
            "tier", sa.String(12), nullable=False,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "tier IN ('observe', 'checkpoint', 'gate')",
            name="ck_action_rules_tier",
        ),
    )

    # --- Cost rules ---
    op.create_table(
        "cost_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column(
            "promote_to", sa.String(12), nullable=False,
        ),
        sa.Column("threshold_value", sa.Float, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "promote_to IN ('checkpoint', 'gate')",
            name="ck_cost_rules_promote",
        ),
    )

    # --- MCP server configs ---
    op.create_table(
        "mcp_server_configs",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("args_json", sa.Text, nullable=True),
        sa.Column("env_json", sa.Text, nullable=True),
        sa.Column("contained", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("reversible", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("trusted", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("tool_overrides_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    # --- Trust grants ---
    op.create_table(
        "trust_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("kinds_json", sa.Text, nullable=False),
        sa.Column("path_pattern", sa.Text, nullable=True),
        sa.Column("excludes_json", sa.Text, nullable=True),
        sa.Column("command_pattern", sa.Text, nullable=True),
        sa.Column("mcp_server", sa.Text, nullable=True),
        sa.Column("expires_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )

    # --- Trail node classification columns ---
    op.add_column("trail_nodes", sa.Column("tier", sa.String(12), nullable=True))
    op.add_column("trail_nodes", sa.Column("reversible", sa.Boolean, nullable=True))
    op.add_column("trail_nodes", sa.Column("contained", sa.Boolean, nullable=True))
    op.add_column("trail_nodes", sa.Column("tier_reason", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("checkpoint_ref", sa.String(80), nullable=True))
    op.add_column("trail_nodes", sa.Column("rollback_status", sa.String(20), nullable=True))

    # --- Extend approvals with batch + tier metadata ---
    op.add_column("approvals", sa.Column("batch_id", sa.String(36), nullable=True))
    op.add_column("approvals", sa.Column("tier", sa.String(12), nullable=True))
    op.add_column("approvals", sa.Column("reversible", sa.Boolean, nullable=True))
    op.add_column("approvals", sa.Column("contained", sa.Boolean, nullable=True))
    op.add_column("approvals", sa.Column("checkpoint_ref", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "checkpoint_ref")
    op.drop_column("approvals", "contained")
    op.drop_column("approvals", "reversible")
    op.drop_column("approvals", "tier")
    op.drop_column("approvals", "batch_id")
    op.drop_column("trail_nodes", "rollback_status")
    op.drop_column("trail_nodes", "checkpoint_ref")
    op.drop_column("trail_nodes", "tier_reason")
    op.drop_column("trail_nodes", "contained")
    op.drop_column("trail_nodes", "reversible")
    op.drop_column("trail_nodes", "tier")
    op.drop_table("trust_grants")
    op.drop_table("mcp_server_configs")
    op.drop_table("cost_rules")
    op.drop_table("action_rules")
    op.drop_table("path_rules")
    op.drop_table("policy_config")
