"""Drop obsolete job cache table.

Revision ID: 5f4c2a91d8e7
Revises: 06dbbeef6d9b
Create Date: 2026-09-01 18:00:00.000000
"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

# revision identifiers, used by Alembic.
revision = "5f4c2a91d8e7"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def upgrade():
    """Drop the unused job cache table and all cached metadata."""
    op.drop_table("job_cache", schema="__reana")


def downgrade():
    """Restore the job cache table structure without discarded cache data."""
    op.create_table(
        "job_cache",
        sa.Column("created", sa.DateTime(), nullable=True),
        sa.Column("updated", sa.DateTime(), nullable=True),
        sa.Column("id_", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("job_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("parameters", sa.String(length=1024), nullable=True),
        sa.Column("result_path", sa.String(length=1024), nullable=True),
        sa.Column("workspace_hash", sa.String(length=1024), nullable=True),
        sa.Column(
            "access_times", sqlalchemy_utils.types.json.JSONType(), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["__reana.job.id_"],
            name=op.f("fk_job_cache_job_id_job"),
        ),
        sa.PrimaryKeyConstraint("id_", "job_id", name=op.f("pk_job_cache")),
        schema="__reana",
    )
