"""Workflow sharing.

Revision ID: 4543cde7c9fb
Revises: 377cfbfccf75
Create Date: 2023-11-02 20:03:01.234086

"""
import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

# revision identifiers, used by Alembic.
revision = "4543cde7c9fb"
down_revision = "377cfbfccf75"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 4543cde7c9fb revision."""
    op.create_table(
        "user_workflow",
        sa.Column(
            "workflow_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False
        ),
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("access_type", sa.Enum("read", name="accesstype"), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["__reana.user_.id_"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["__reana.workflow.id_"],
        ),
        sa.PrimaryKeyConstraint("workflow_id", "user_id"),
        schema="__reana",
    )


def downgrade():
    """Downgrade to 377cfbfccf75 revision."""
    op.drop_table("user_workflow", schema="__reana")
    sa.Enum(name="accesstype").drop(op.get_bind())
