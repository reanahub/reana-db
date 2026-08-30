"""Add notifications table.

Revision ID: 8d19b60cc44f
Revises: 06dbbeef6d9b
Create Date: 2026-06-08 12:00:00
"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

revision = "8d19b60cc44f"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Create notifications table."""
    op.create_table(
        "notification",
        sa.Column("id_", sqlalchemy_utils.UUIDType(), nullable=False),
        sa.Column("user_id", sqlalchemy_utils.UUIDType(), nullable=False),
        sa.Column("type_", sa.String(length=255), nullable=False),
        sa.Column("payload", sqlalchemy_utils.JSONType(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=True),
        sa.Column("updated", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["__reana.user_.id_"],
            name=op.f("fk_notification_user_id_user_"),
        ),
        sa.PrimaryKeyConstraint("id_", name=op.f("pk_notification")),
        schema="__reana",
    )
    op.create_index(
        op.f("ix_notification_user_id"),
        "notification",
        ["user_id"],
        unique=False,
        schema="__reana",
    )
    op.create_index(
        "ix_notification_user_id_read_at",
        "notification",
        ["user_id", "read_at"],
        unique=False,
        schema="__reana",
    )


def downgrade():
    """Drop notifications table."""
    op.drop_index(
        "ix_notification_user_id_read_at",
        table_name="notification",
        schema="__reana",
    )
    op.drop_index(
        op.f("ix_notification_user_id"),
        table_name="notification",
        schema="__reana",
    )
    op.drop_table("notification", schema="__reana")
