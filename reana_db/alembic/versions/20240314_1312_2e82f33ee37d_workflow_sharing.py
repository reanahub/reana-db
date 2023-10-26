"""Workflow sharing.

Revision ID: 2e82f33ee37d
Revises: eb5309f3d8ee
Create Date: 2024-03-14 13:12:01.029714

"""

import sqlalchemy_utils
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "2e82f33ee37d"
down_revision = "eb5309f3d8ee"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 2e82f33ee37d revision."""
    op.create_table(
        "user_workflow",
        sa.Column(
            "workflow_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False
        ),
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("access_type", sa.Enum("read", name="accesstype"), nullable=False),
        sa.Column("message", sa.String(length=5000), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["__reana.user_.id_"],
            name=op.f("fk_user_workflow_user_id_user_"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["__reana.workflow.id_"],
            name=op.f("fk_user_workflow_workflow_id_workflow"),
        ),
        sa.PrimaryKeyConstraint(
            "workflow_id", "user_id", name=op.f("pk_user_workflow")
        ),
        schema="__reana",
    )


def downgrade():
    """Downgrade to eb5309f3d8ee revision."""
    op.drop_table("user_workflow", schema="__reana")
    sa.Enum(name="accesstype").drop(op.get_bind())
