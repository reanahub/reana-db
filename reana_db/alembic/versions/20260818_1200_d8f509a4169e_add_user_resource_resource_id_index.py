"""Add index on user_resource(resource_id, user_id).

Revision ID: d8f509a4169e
Revises: f7c88ca6b713
Create Date: 2026-08-18 12:00:00.000000

Maintenance-window note: not built ``CONCURRENTLY`` (Alembic's ``env.py``
runs every migration inside one transaction here, and Postgres refuses
``CREATE INDEX CONCURRENTLY`` inside a transaction block), so this takes a
``SHARE`` lock on ``user_resource`` for the build's duration -- blocking
writes (quota updates) but not reads. On a large ``user_resource`` table,
run during a maintenance window or a low-write-traffic period.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d8f509a4169e"
down_revision = "f7c88ca6b713"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to d8f509a4169e.

    ``user_resource``'s only index is its composite primary key
    ``(user_id, resource_id)``, which a btree cannot seek on for the second
    column alone. The periodic CPU-quota maintenance job filters by
    ``resource_id`` (and, for the single-user path, also by ``user_id``),
    so without this index that query is a full table scan.
    """
    op.create_index(
        op.f("ix___reana_user_resource_resource_id"),
        "user_resource",
        ["resource_id", "user_id"],
        unique=False,
        schema="__reana",
    )


def downgrade():
    """Downgrade to f7c88ca6b713."""
    op.drop_index(
        op.f("ix___reana_user_resource_resource_id"),
        table_name="user_resource",
        schema="__reana",
    )
