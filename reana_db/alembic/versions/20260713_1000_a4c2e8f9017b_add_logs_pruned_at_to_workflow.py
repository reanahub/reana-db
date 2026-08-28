"""Add logs_pruned_at to workflow.

Revision ID: a4c2e8f9017b
Revises: 06dbbeef6d9b
Create Date: 2026-07-13 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c2e8f9017b"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to a4c2e8f9017b revision."""
    op.add_column(
        "workflow",
        sa.Column("logs_pruned_at", sa.DateTime(timezone=True), nullable=True),
        schema="__reana",
    )
    op.create_index(
        op.f("ix___reana_workflow_service_workflow_id"),
        "workflow_service",
        ["workflow_id"],
        unique=False,
        schema="__reana",
    )
    op.create_index(
        op.f("ix___reana_service_logs_service_id"),
        "service_logs",
        ["service_id"],
        unique=False,
        schema="__reana",
    )
    op.create_index(
        "ix___reana_workflow_unpruned_logs",
        "workflow",
        ["id_"],
        unique=False,
        schema="__reana",
        postgresql_where=sa.text("logs_pruned_at IS NULL"),
    )


def downgrade():
    """Downgrade to 06dbbeef6d9b revision."""
    op.drop_index(
        "ix___reana_workflow_unpruned_logs",
        table_name="workflow",
        schema="__reana",
    )
    op.drop_index(
        op.f("ix___reana_service_logs_service_id"),
        table_name="service_logs",
        schema="__reana",
    )
    op.drop_index(
        op.f("ix___reana_workflow_service_workflow_id"),
        table_name="workflow_service",
        schema="__reana",
    )
    op.drop_column("workflow", "logs_pruned_at", schema="__reana")
