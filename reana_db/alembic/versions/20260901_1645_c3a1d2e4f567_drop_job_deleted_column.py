"""Drop unused Job deleted column.

Revision ID: c3a1d2e4f567
Revises: 06dbbeef6d9b
Create Date: 2026-09-01 16:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3a1d2e4f567"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to c3a1d2e4f567 revision."""
    op.drop_column("job", "deleted", schema="__reana")


def downgrade():
    """Downgrade to 06dbbeef6d9b revision."""
    op.add_column(
        "job",
        sa.Column("deleted", sa.Boolean(), nullable=True),
        schema="__reana",
    )
