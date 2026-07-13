"""Add interactive-session and GitLab webhook secrets.

Revision ID: 5e5fab65889f
Revises: 25a9293c27cc
Create Date: 2026-06-11 10:30:00.000000

Maintenance-window note: this migration's unique constraint on ``user_``
(``gitlab_webhook_secret``) takes the same ``ACCESS EXCLUSIVE`` lock for its
build duration as the identity-columns migration immediately before it --
see that migration's note. On a large ``user_`` table, plan both together
during one maintenance window.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "5e5fab65889f"
down_revision = "25a9293c27cc"
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to 5e5fab65889f revision."""
    op.add_column(
        "interactive_session",
        sa.Column("session_secret", sa.LargeBinary(), nullable=True),
        schema="__reana",
    )
    op.add_column(
        "user_",
        sa.Column("gitlab_webhook_secret", sa.LargeBinary(), nullable=True),
        schema="__reana",
    )
    op.create_unique_constraint(
        "uq_user__gitlab_webhook_secret",
        "user_",
        ["gitlab_webhook_secret"],
        schema="__reana",
    )


def downgrade():
    """Downgrade to 25a9293c27cc revision."""
    op.drop_constraint(
        "uq_user__gitlab_webhook_secret", "user_", schema="__reana", type_="unique"
    )
    op.drop_column("user_", "gitlab_webhook_secret", schema="__reana")
    op.drop_column("interactive_session", "session_secret", schema="__reana")
