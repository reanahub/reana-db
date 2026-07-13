"""Add IdP identity to user.

Revision ID: 25a9293c27cc
Revises: 06dbbeef6d9b
Create Date: 2026-06-11 10:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "25a9293c27cc"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 25a9293c27cc revision."""
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
    op.create_unique_constraint(
        "uq_user__idp_identity",
        "user_",
        ["idp_issuer", "idp_subject"],
        schema="__reana",
    )


def downgrade():
    """Downgrade to 06dbbeef6d9b revision."""
    op.drop_constraint(
        "uq_user__idp_identity", "user_", schema="__reana", type_="unique"
    )
    op.drop_column("user_", "idp_subject", schema="__reana")
    op.drop_column("user_", "idp_issuer", schema="__reana")
