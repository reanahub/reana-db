"""Foreign key for workflow_uuid of Job.

Revision ID: 86435bb00714
Revises: eb5309f3d8ee
Create Date: 2024-05-31 09:59:18.951074

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "86435bb00714"
down_revision = "eb5309f3d8ee"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 86435bb00714."""
    job_table = sa.sql.table(
        "job",
        sa.sql.column("id_"),
        sa.sql.column("workflow_uuid"),
        schema="__reana",
    )
    job_cache_table = sa.sql.table(
        "job_cache",
        sa.sql.column("job_id"),
        schema="__reana",
    )
    workflow_table = sa.sql.table(
        "workflow",
        sa.sql.column("id_"),
        schema="__reana",
    )

    # 1. delete jobs which refer to non-existing workflows
    #     1a. disable foreign key checks, so that we can delete jobs even if they
    #         are still referenced in the `job_cache` table
    op.execute(
        sa.text(
            "ALTER TABLE __reana.job_cache "
            "ALTER CONSTRAINT fk_job_cache_job_id_job DEFERRABLE"
        )
    )
    op.execute(sa.text("SET CONSTRAINTS __reana.fk_job_cache_job_id_job DEFERRED"))
    #     1b. delete jobs from `job` table
    op.execute(
        job_table.delete().where(
            job_table.c.workflow_uuid.notin_(sa.select([workflow_table.c.id_]))
        )
    )
    #     1c. delete rows in `job_cache` that reference deleted jobs
    op.execute(
        job_cache_table.delete().where(
            job_cache_table.c.job_id.notin_(sa.select([job_table.c.id_]))
        )
    )
    #     1d. enable foreign key checks
    op.execute(sa.text("SET CONSTRAINTS __reana.fk_job_cache_job_id_job IMMEDIATE"))
    op.execute(
        sa.text(
            "ALTER TABLE __reana.job_cache "
            "ALTER CONSTRAINT fk_job_cache_job_id_job NOT DEFERRABLE"
        )
    )

    # 2. alter column to make it non-nullable
    op.alter_column(
        "job",
        "workflow_uuid",
        existing_type=postgresql.UUID(),
        nullable=False,
        schema="__reana",
    )

    # 3. create foreign key constraint
    op.create_foreign_key(
        "fk_job_workflow_uuid_workflow",
        "job",
        "workflow",
        ["workflow_uuid"],
        ["id_"],
        source_schema="__reana",
        referent_schema="__reana",
    )


def downgrade():
    """Downgrade to eb5309f3d8ee."""
    op.drop_constraint(
        "fk_job_workflow_uuid_workflow", "job", schema="__reana", type_="foreignkey"
    )
    op.alter_column(
        "job",
        "workflow_uuid",
        existing_type=postgresql.UUID(),
        nullable=True,
        schema="__reana",
    )
