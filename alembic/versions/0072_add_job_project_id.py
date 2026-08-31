"""Add immutable Project ownership to jobs.

A Job can never exist without an owning Project (AD-5) — ``project_id`` is
NOT NULL. Any job whose repo cannot be unambiguously attributed to exactly
one Project during backfill is deleted rather than left dangling: there are
no production users yet, so an orphaned job has no real-world value and
carrying "project_id may be null" complexity forward across the whole
codebase is a worse outcome than dropping a few unattributable dev rows.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from types import SimpleNamespace

import sqlalchemy as sa

from alembic import op
from backend.services.project.repo_membership import resolve_matching_project_id

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _backfill_job_project_ids() -> None:
    conn = op.get_bind()
    project_rows = [
        SimpleNamespace(**row) for row in conn.execute(sa.text("SELECT id, repo_paths FROM projects")).mappings()
    ]
    jobs = conn.execute(sa.text("SELECT id, repo FROM jobs WHERE project_id IS NULL")).mappings().all()
    updates = []
    for job in jobs:
        project_id = resolve_matching_project_id(job["repo"], project_rows)
        if project_id is not None:
            updates.append({"job_id": job["id"], "project_id": project_id})
    if updates:
        conn.execute(
            sa.text("UPDATE jobs SET project_id = :project_id WHERE id = :job_id"),
            updates,
        )
    # Jobs whose repo has zero or ambiguous (>1) owning Projects cannot be
    # attributed — delete them rather than leave project_id NULL.
    conn.execute(sa.text("DELETE FROM jobs WHERE project_id IS NULL"))


def upgrade() -> None:
    if not _has_column("jobs", "project_id"):
        with op.batch_alter_table("jobs", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_jobs_project_id_projects",
                "projects",
                ["project_id"],
                ["id"],
            )
    _backfill_job_project_ids()
    with op.batch_alter_table("jobs", recreate="always") as batch_op:
        batch_op.alter_column("project_id", nullable=False)


def downgrade() -> None:
    if _has_column("jobs", "project_id"):
        with op.batch_alter_table("jobs", recreate="always") as batch_op:
            batch_op.drop_column("project_id")
