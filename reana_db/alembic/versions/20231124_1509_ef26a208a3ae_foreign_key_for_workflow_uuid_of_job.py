"""Foreign key for workflow_uuid of Job.

Revision ID: ef26a208a3ae
Revises: 126601b69c78
Create Date: 2023-11-24 15:09:49.671968

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ef26a208a3ae"
down_revision = "126601b69c78"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to ef26a208a3ae."""
    op.alter_column(
        "job",
        "workflow_uuid",
        existing_type=postgresql.UUID(),
        nullable=False,
        schema="__reana",
    )
    op.create_foreign_key(
        "_job_workflow_uuid_fk",
        "job",
        "workflow",
        ["workflow_uuid"],
        ["id_"],
        source_schema="__reana",
        referent_schema="__reana",
    )


def downgrade():
    """Downgrade to 126601b69c78."""
    op.drop_constraint(
        "_job_workflow_uuid_fk", "job", schema="__reana", type_="foreignkey"
    )
    op.alter_column(
        "job",
        "workflow_uuid",
        existing_type=postgresql.UUID(),
        nullable=True,
        schema="__reana",
    )
