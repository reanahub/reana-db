"""Add user_resource quota period fields.

Revision ID: 06dbbeef6d9b
Revises: 3da4dd5d0b75
Create Date: 2026-03-20 09:47:20.025386
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "06dbbeef6d9b"
down_revision = "3da4dd5d0b75"
branch_labels = None
depends_on = None


def upgrade():
    """Add periodic quota columns to user_resource."""
    op.add_column(
        "user_resource",
        sa.Column("quota_period_months", sa.Integer(), nullable=True),
        schema="__reana",
    )
    op.add_column(
        "user_resource",
        sa.Column("quota_period_anchor_at", sa.DateTime(), nullable=True),
        schema="__reana",
    )
    op.add_column(
        "user_resource",
        sa.Column("quota_period_start_at", sa.DateTime(), nullable=True),
        schema="__reana",
    )


def downgrade():
    """Remove periodic quota columns from user_resource."""
    op.drop_column("user_resource", "quota_period_start_at", schema="__reana")
    op.drop_column("user_resource", "quota_period_anchor_at", schema="__reana")
    op.drop_column("user_resource", "quota_period_months", schema="__reana")
