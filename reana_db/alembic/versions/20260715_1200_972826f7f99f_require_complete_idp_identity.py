"""Require complete IdP identities.

Revision ID: 972826f7f99f
Revises: 5e5fab65889f
Create Date: 2026-07-15 12:00:00.000000

Maintenance-window note: ``create_check_constraint`` validates the new CHECK
against every existing row while holding an ``ACCESS EXCLUSIVE`` lock on
``user_`` -- a second full-table scan under exclusive lock immediately after
the pre-check ``SELECT count(*)`` above (which itself takes no lock beyond
an ordinary read). On a large ``user_`` table, run this during a maintenance
window, ideally alongside the two migrations immediately before it that also
lock ``user_``.
"""

# The literal name below is the bare/short constraint name, matching
# ``models.py``'s equivalent ``CheckConstraint(name="idp_identity_complete")``.
# It must NOT be pre-expanded: Alembic's migration context (as wired up in
# ``env.py``, which sets ``target_metadata = Base.metadata``) copies this
# repo's ``naming_convention`` onto the ad-hoc ``MetaData()`` that
# ``op.create_check_constraint`` builds its constraint against (see
# ``alembic.operations.schemaobj.SchemaObjects.metadata()``), so the
# convention DOES apply here -- confirmed empirically with a real
# ``MigrationContext``/``Operations`` run. Passing the already-expanded name
# (``"ck_user__idp_identity_complete"``) gets expanded a second time into
# the double-prefixed ``"ck_user__ck_user__idp_identity_complete"``; passing
# the bare name here lets the convention expand it exactly once, to
# ``"ck_user__idp_identity_complete"``, matching the ORM side.

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
    op.execute(
        "ALTER TABLE __reana.user_ "
        "DROP CONSTRAINT IF EXISTS ck_user__idp_identity_complete"
    )
