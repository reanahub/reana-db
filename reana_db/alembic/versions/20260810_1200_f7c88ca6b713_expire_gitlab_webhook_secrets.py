"""Expire GitLab webhook secrets.

Revision ID: f7c88ca6b713
Revises: 972826f7f99f
Create Date: 2026-08-10 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f7c88ca6b713"
down_revision = "972826f7f99f"
branch_labels = None
depends_on = None


def upgrade():
    """Add the expiry of the delegated GitLab webhook capability."""
    op.add_column(
        "user_",
        sa.Column("gitlab_webhook_secret_expires_at", sa.DateTime(), nullable=True),
        schema="__reana",
    )


def downgrade():
    """Remove the GitLab webhook capability expiry."""
    op.drop_column("user_", "gitlab_webhook_secret_expires_at", schema="__reana")
