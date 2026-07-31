"""Wholesale governance cutover: retire CodePlane's hand-rolled decision schema.

The action-policy DECISION layer is delegated to ``traceforge.governance`` (rules,
protected paths, count/effect budget, reason-code trust) whose durable state lives
in a **separate** ``~/.codeplane/governance.db`` with TraceForge's own alembic — it
never touches CodePlane's ``alembic_version``. This migration removes the CodePlane
tables/columns that governance replaces:

* ``trail_nodes``: swap the CP verdict columns (``tier`` / ``reversible`` /
  ``contained`` / ``tier_reason``) for TraceForge's native governance fields
  (``recommended_action`` / ``reason_code`` / ``risk_score`` / ``risk_band`` /
  ``effect``). ``checkpoint_ref`` / ``rollback_status`` are enforcement product
  state and stay.
* ``policy_config``: add ``usd_ceilings_json`` (per-preset USD ceiling overlay
  enforced natively by ``JobSpendCeilingAssessor``) and correct the stale preset
  CHECK constraint left by 0041 (``'strict'`` → ``'locked'``).
* Drop ``path_rules`` / ``action_rules`` / ``cost_rules`` / ``trust_grants`` — the
  hand-rolled rule + pattern-trust tables (shipped empty; the 3 preset profiles
  now carry default behavior).

``mcp_server_configs`` and the vestigial ``approvals`` classification columns are
left untouched (out of scope for this wave).

Revision ID: 0056
Revises: 0055
"""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- trail_nodes: CP tier verdict -> TraceForge governance verdict ---
    with op.batch_alter_table("trail_nodes") as batch_op:
        batch_op.add_column(sa.Column("recommended_action", sa.String(12), nullable=True))
        batch_op.add_column(sa.Column("reason_code", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("risk_score", sa.Integer, nullable=True))
        batch_op.add_column(sa.Column("risk_band", sa.String(12), nullable=True))
        batch_op.add_column(sa.Column("effect", sa.String(12), nullable=True))
        batch_op.drop_column("tier")
        batch_op.drop_column("reversible")
        batch_op.drop_column("contained")
        batch_op.drop_column("tier_reason")

    # --- policy_config: add usd_ceilings_json + fix stale preset CHECK ---
    # SQLite cannot ALTER a CHECK constraint in place, so rebuild the singleton
    # table. Normalize any lingering 'strict' preset to 'locked' during the copy.
    op.execute("ALTER TABLE policy_config RENAME TO policy_config_old")
    op.create_table(
        "policy_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("preset", sa.String(20), nullable=False, server_default="supervised"),
        sa.Column("batch_window_seconds", sa.Float, nullable=False, server_default="5.0"),
        sa.Column("usd_ceilings_json", sa.Text, nullable=True),
        sa.CheckConstraint("id = 1", name="ck_policy_config_singleton"),
        sa.CheckConstraint(
            "preset IN ('autonomous', 'supervised', 'locked')",
            name="ck_policy_config_preset",
        ),
    )
    op.execute(
        "INSERT INTO policy_config (id, preset, batch_window_seconds, usd_ceilings_json) "
        "SELECT id, "
        "CASE WHEN preset = 'strict' THEN 'locked' ELSE preset END, "
        "batch_window_seconds, NULL "
        "FROM policy_config_old"
    )
    op.execute("DROP TABLE policy_config_old")

    # --- Drop retired rule + pattern-trust tables ---
    op.drop_table("trust_grants")
    op.drop_table("cost_rules")
    op.drop_table("action_rules")
    op.drop_table("path_rules")


def downgrade() -> None:
    # --- Recreate the retired rule + pattern-trust tables (0027 shapes) ---
    op.create_table(
        "path_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("path_pattern", sa.Text, nullable=False, unique=True),
        sa.Column("tier", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint("tier IN ('observe', 'checkpoint', 'gate')", name="ck_path_rules_tier"),
    )
    op.create_table(
        "action_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_pattern", sa.Text, nullable=False),
        sa.Column("tier", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint("tier IN ('observe', 'checkpoint', 'gate')", name="ck_action_rules_tier"),
    )
    op.create_table(
        "cost_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("promote_to", sa.String(12), nullable=False),
        sa.Column("threshold_value", sa.Float, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint("promote_to IN ('checkpoint', 'gate')", name="ck_cost_rules_promote"),
    )
    op.create_table(
        "trust_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("kinds_json", sa.Text, nullable=False),
        sa.Column("path_pattern", sa.Text, nullable=True),
        sa.Column("excludes_json", sa.Text, nullable=True),
        sa.Column("command_pattern", sa.Text, nullable=True),
        sa.Column("mcp_server", sa.Text, nullable=True),
        sa.Column("mcp_tool", sa.Text, nullable=True),
        sa.Column("expires_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )

    # --- policy_config: drop usd_ceilings_json + restore the 0027/0041 preset CHECK ---
    op.execute("ALTER TABLE policy_config RENAME TO policy_config_old")
    op.create_table(
        "policy_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("preset", sa.String(20), nullable=False, server_default="supervised"),
        sa.Column("batch_window_seconds", sa.Float, nullable=False, server_default="5.0"),
        sa.CheckConstraint("id = 1", name="ck_policy_config_singleton"),
        sa.CheckConstraint(
            "preset IN ('autonomous', 'supervised', 'strict')",
            name="ck_policy_config_preset",
        ),
    )
    op.execute(
        "INSERT INTO policy_config (id, preset, batch_window_seconds) "
        "SELECT id, "
        "CASE WHEN preset = 'locked' THEN 'strict' ELSE preset END, "
        "batch_window_seconds "
        "FROM policy_config_old"
    )
    op.execute("DROP TABLE policy_config_old")

    # --- trail_nodes: restore CP tier verdict columns ---
    with op.batch_alter_table("trail_nodes") as batch_op:
        batch_op.add_column(sa.Column("tier", sa.String(12), nullable=True))
        batch_op.add_column(sa.Column("reversible", sa.Boolean, nullable=True))
        batch_op.add_column(sa.Column("contained", sa.Boolean, nullable=True))
        batch_op.add_column(sa.Column("tier_reason", sa.Text, nullable=True))
        batch_op.drop_column("effect")
        batch_op.drop_column("risk_band")
        batch_op.drop_column("risk_score")
        batch_op.drop_column("reason_code")
        batch_op.drop_column("recommended_action")
