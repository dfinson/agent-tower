"""Persist TaskLink chain identity and Jira account email.

Revision ID: 0067
Revises: 0066
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_links",
        sa.Column("chain_root_id", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("credentials", sa.Column("email", sa.String(), nullable=True))

    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, project_id, repo_path, story_node_id, depends_on
                FROM task_links
                """
            )
        )
        .mappings()
        .all()
    )
    rows_by_id = {str(row["id"]): row for row in rows}
    rows_by_project: dict[str, list[sa.RowMapping]] = {}
    for row in rows:
        rows_by_project.setdefault(str(row["project_id"]), []).append(row)

    for project_rows in rows_by_project.values():
        rows_by_key = {
            f"{row['repo_path']}::{row['story_node_id']}": row
            for row in project_rows
            if row["story_node_id"] is not None
        }
        adjacency: dict[str, set[str]] = {
            str(row["id"]): set() for row in project_rows
        }
        for row in project_rows:
            row_id = str(row["id"])
            for dependency_key in json.loads(str(row["depends_on"] or "[]")):
                dependency = rows_by_key.get(dependency_key)
                if dependency is None:
                    continue
                dependency_id = str(dependency["id"])
                adjacency[row_id].add(dependency_id)
                adjacency[dependency_id].add(row_id)

        visited: set[str] = set()
        for row in project_rows:
            row_id = str(row["id"])
            if row_id in visited:
                continue
            stack = [row_id]
            component_ids: list[str] = []
            while stack:
                current_id = stack.pop()
                if current_id in visited:
                    continue
                visited.add(current_id)
                component_ids.append(current_id)
                stack.extend(adjacency[current_id] - visited)

            component_id_set = set(component_ids)
            roots = [
                component_id
                for component_id in component_ids
                if not any(
                    (
                        dependency := rows_by_key.get(dependency_key)
                    )
                    is not None
                    and str(dependency["id"]) in component_id_set
                    for dependency_key in json.loads(
                        str(rows_by_id[component_id]["depends_on"] or "[]")
                    )
                )
            ]
            chain_root_id = min(roots or component_ids)
            connection.execute(
                sa.text(
                    """
                    UPDATE task_links
                    SET chain_root_id = :chain_root_id
                    WHERE id IN :component_ids
                    """
                ).bindparams(
                    sa.bindparam("component_ids", expanding=True),
                ),
                {
                    "chain_root_id": chain_root_id,
                    "component_ids": component_ids,
                },
            )


def downgrade() -> None:
    op.drop_column("credentials", "email")
    op.drop_column("task_links", "chain_root_id")
