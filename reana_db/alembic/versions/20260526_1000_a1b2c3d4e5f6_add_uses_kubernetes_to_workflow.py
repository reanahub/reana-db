"""Add uses_kubernetes column to workflow table.

Revision ID: a1b2c3d4e5f6
Revises: 06dbbeef6d9b
Create Date: 2026-05-26 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Add uses_kubernetes column to workflow table, defaulting to True."""
    op.add_column(
        "workflow",
        sa.Column(
            "uses_kubernetes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="__reana",
    )


def downgrade():
    """Remove uses_kubernetes column from workflow table."""
    op.drop_column("workflow", "uses_kubernetes", schema="__reana")
