"""add idp data to user.

Revision ID: 48294850c570
Revises: 3da4dd5d0b75
Create Date: 2025-08-13 10:01:02.408799

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "48294850c570"
down_revision = "3da4dd5d0b75"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 48294850c570 revision."""
    op.add_column(
        "user_",
        sa.Column("idp_issuer", sa.String(length=255), nullable=True),
        schema="__reana",
    )
    op.add_column(
        "user_",
        sa.Column("idp_subject", sa.String(length=255), nullable=True),
        schema="__reana",
    )


def downgrade():
    """Downgrade to 3da4dd5d0b75 revision."""
    op.drop_column("user_", "idp_subject", schema="__reana")
    op.drop_column("user_", "idp_issuer", schema="__reana")
