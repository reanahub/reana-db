"""Repair IdP identity constraint names on already-stamped databases.

Revision ID: 3f6c0d2a1b7e
Revises: 8ae7b67c2d41
Create Date: 2026-08-24 10:15:00.000000

Some development deployments applied revision ``972826f7f99f`` while its
already-expanded constraint name was expanded a second time by Alembic's
naming convention.  Editing that old revision cannot repair a database whose
Alembic stamp is already past it, so compatibility belongs in this new,
forward revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "3f6c0d2a1b7e"
down_revision = "8ae7b67c2d41"
branch_labels = None
depends_on = None

_CORRECT = "ck_user__idp_identity_complete"
_DOUBLE_PREFIXED = "ck_user__ck_user__idp_identity_complete"
_LITERAL = "idp_identity_complete"


def _constraint_names(connection):
    """Return relevant CHECK names scoped to ``__reana.user_`` only."""
    rows = connection.execute(
        sa.text(
            "SELECT con.conname "
            "FROM pg_constraint AS con "
            "JOIN pg_class AS rel ON rel.oid = con.conrelid "
            "JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace "
            "WHERE ns.nspname = :schema "
            "AND rel.relname = :table "
            "AND con.contype = 'c' "
            "AND con.conname IN (:correct, :double_prefixed, :literal)"
        ),
        {
            "schema": "__reana",
            "table": "user_",
            "correct": _CORRECT,
            "double_prefixed": _DOUBLE_PREFIXED,
            "literal": _LITERAL,
        },
    ).fetchall()
    return {row[0] for row in rows}


def _drop(name):
    """Drop one known compatibility constraint name."""
    op.execute(f'ALTER TABLE __reana.user_ DROP CONSTRAINT IF EXISTS "{name}"')


def upgrade():
    """Converge every known stamped state on the ORM's constraint name."""
    names = _constraint_names(op.get_bind())
    if _CORRECT in names:
        for redundant in (_DOUBLE_PREFIXED, _LITERAL):
            if redundant in names:
                _drop(redundant)
        return

    source = next(
        (name for name in (_DOUBLE_PREFIXED, _LITERAL) if name in names), None
    )
    if source:
        op.execute(
            f'ALTER TABLE __reana.user_ RENAME CONSTRAINT "{source}" TO "{_CORRECT}"'
        )
        for redundant in (_DOUBLE_PREFIXED, _LITERAL):
            if redundant != source and redundant in names:
                _drop(redundant)
        return

    op.create_check_constraint(
        "idp_identity_complete",
        "user_",
        "(idp_issuer IS NULL) = (idp_subject IS NULL)",
        schema="__reana",
    )


def downgrade():
    """Leave the repaired constraint intact.

    This is a corrective revision, not schema ownership: the earlier
    ``972826f7f99f`` downgrade removes the constraint when downgrading past
    the feature that introduced it.
    """
