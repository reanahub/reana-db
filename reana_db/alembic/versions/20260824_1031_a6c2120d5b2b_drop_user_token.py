"""Drop the legacy user_token table.

Revision ID: a6c2120d5b2b
Revises: e940248e5165
Create Date: 2026-08-24 10:31:00.000000

The pre-OIDC opaque REANA access-token workflow (request/approve/revoke) has
no live caller anywhere in the platform: authentication is entirely OIDC/JWT
now. Dropped outright rather than kept as a dead compatibility surface --
pre-existing account continuity for installations upgrading from an
opaque-token release is handled by email-based identity linking
(``REANA_AUTH_EMAIL_LINKING_ENABLED``), not by preserving legacy tokens.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a6c2120d5b2b"
down_revision = "e940248e5165"
branch_labels = None
depends_on = None


def upgrade():
    """Drop the legacy user_token table and its enum types."""
    op.drop_table("user_token", schema="__reana")
    sa.Enum(name="usertokenstatus").drop(op.get_bind())
    sa.Enum(name="usertokentype").drop(op.get_bind())


def downgrade():
    """Refuse to imply that deleted opaque credential rows are recoverable."""
    raise RuntimeError(
        "Migration a6c2120d5b2b is irreversible: legacy opaque user tokens "
        "were intentionally deleted and cannot be restored. Restore a database "
        "backup instead of downgrading across this revision."
    )
