"""Add compute_backends column to workflow table.

Revision ID: 8f24fcf45930
Revises: 06dbbeef6d9b
Create Date: 2026-06-12 11:50:43.150654
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8f24fcf45930"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Add compute_backends column to workflow table, defaulting to Kubernetes.

    The server-side default backfills existing rows on upgrade so that they do
    not depend on the Python-side default at insert time.
    """
    op.add_column(
        "workflow",
        sa.Column(
            "compute_backends",
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['kubernetes']"),
        ),
        schema="__reana",
    )


def downgrade():
    """Remove compute_backends column from workflow table."""
    op.drop_column("workflow", "compute_backends", schema="__reana")
