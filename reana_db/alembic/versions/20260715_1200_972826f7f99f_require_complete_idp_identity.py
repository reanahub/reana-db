"""Require complete IdP identities.

Revision ID: 972826f7f99f
Revises: 5e5fab65889f
Create Date: 2026-07-15 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "972826f7f99f"
down_revision = "5e5fab65889f"
branch_labels = None
depends_on = None


def upgrade():
    """Require IdP issuer and subject to be set together."""
    connection = op.get_bind()
    partial_identity_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM __reana.user_ "
            "WHERE (idp_issuer IS NULL) <> (idp_subject IS NULL)"
        )
    ).scalar()
    if partial_identity_count:
        raise RuntimeError(
            "Cannot enforce complete IdP identities: found "
            f"{partial_identity_count} user row(s) with only idp_issuer or "
            "idp_subject set. Set both columns or clear both columns for these "
            "rows, then retry the migration."
        )

    op.create_check_constraint(
        "idp_identity_complete",
        "user_",
        "(idp_issuer IS NULL) = (idp_subject IS NULL)",
        schema="__reana",
    )


def downgrade():
    """Allow partial IdP identities."""
    op.drop_constraint(
        op.f("ck_user__idp_identity_complete"),
        "user_",
        type_="check",
        schema="__reana",
    )
