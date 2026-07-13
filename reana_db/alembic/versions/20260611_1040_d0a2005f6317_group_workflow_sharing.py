"""Group workflow sharing.

Revision ID: d0a2005f6317
Revises: a6c2120d5b2b
Create Date: 2026-06-11 10:40:00.000000

"""

import sqlalchemy_utils
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d0a2005f6317"
down_revision = "a6c2120d5b2b"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to d0a2005f6317 revision."""
    op.create_table(
        "external_group",
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.Column("id_", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id_", name=op.f("pk_external_group")),
        sa.UniqueConstraint(
            "provider", "external_id", name="uq_external_group_provider_external_id"
        ),
        schema="__reana",
    )
    op.create_table(
        "user_group_membership",
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("group_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["__reana.user_.id_"],
            name=op.f("fk_user_group_membership_user_id_user_"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["__reana.external_group.id_"],
            name=op.f("fk_user_group_membership_group_id_external_group"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "group_id", name=op.f("pk_user_group_membership")
        ),
        schema="__reana",
    )
    op.create_index(
        "ix_user_group_membership_group_id",
        "user_group_membership",
        ["group_id"],
        schema="__reana",
    )
    op.create_table(
        "group_workflow",
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.Column(
            "workflow_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False
        ),
        sa.Column("group_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column(
            "access_type",
            postgresql.ENUM("read", name="accesstype", create_type=False),
            nullable=False,
        ),
        sa.Column("message", sa.String(length=5000), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["__reana.workflow.id_"],
            name=op.f("fk_group_workflow_workflow_id_workflow"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["__reana.external_group.id_"],
            name=op.f("fk_group_workflow_group_id_external_group"),
        ),
        sa.PrimaryKeyConstraint(
            "workflow_id", "group_id", name=op.f("pk_group_workflow")
        ),
        schema="__reana",
    )
    op.create_index(
        "ix_group_workflow_group_id",
        "group_workflow",
        ["group_id"],
        schema="__reana",
    )


def downgrade():
    """Downgrade to 25a9293c27cc revision."""
    op.drop_index(
        "ix_group_workflow_group_id", table_name="group_workflow", schema="__reana"
    )
    op.drop_table("group_workflow", schema="__reana")
    op.drop_index(
        "ix_user_group_membership_group_id",
        table_name="user_group_membership",
        schema="__reana",
    )
    op.drop_table("user_group_membership", schema="__reana")
    op.drop_table("external_group", schema="__reana")
