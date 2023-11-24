"""Improve indexes usage.

Revision ID: 126601b69c78
Revises: b85c3e601de4
Create Date: 2023-11-23 13:42:47.554976

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "126601b69c78"
down_revision = "b85c3e601de4"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 126601b69c78."""
    # Drop old unique constraint for __reana.workflow and
    # create new one with better column order
    op.drop_constraint(
        "_user_workflow_run_uc", "workflow", schema="__reana", type_="unique"
    )
    op.create_unique_constraint(
        "_user_workflow_run_uc",
        "workflow",
        ["owner_id", "name", "run_number_major", "run_number_minor"],
        schema="__reana",
    )

    # Create new index on (workflow_uuid, created) of __reana.job
    op.create_index(
        "_workflow_uuid_created_desc_ix",
        "job",
        ["workflow_uuid", "created"],
        unique=False,
        schema="__reana",
    )

    # Create new index on (status) of __reana.workflow
    op.create_index(
        op.f("ix___reana_workflow_status"),
        "workflow",
        ["status"],
        unique=False,
        schema="__reana",
    )


def downgrade():
    """Downgrade to b85c3e601de4."""
    # Drop new index on __reana.workflow
    op.drop_index(
        op.f("ix___reana_workflow_status"), table_name="workflow", schema="__reana"
    )

    # Delete new index on __reana.job
    op.drop_index("_workflow_uuid_created_desc_ix", table_name="job", schema="__reana")

    # Drop new unique constraint for __reana.workflow and create previous one
    op.drop_constraint(
        "_user_workflow_run_uc", "workflow", schema="__reana", type_="unique"
    )
    op.create_unique_constraint(
        "_user_workflow_run_uc",
        "workflow",
        ["name", "owner_id", "run_number_major", "run_number_minor"],
        schema="__reana",
    )
