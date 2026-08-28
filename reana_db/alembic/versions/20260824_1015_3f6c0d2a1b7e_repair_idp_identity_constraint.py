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
_QUOTA_CORRECT = "ck_user_resource_quota_period_months_positive"
_QUOTA_DOUBLE_PREFIXED = (
    "ck_user_resource_ck_user_resource_quota_period_months_positive"
)
_QUOTA_LITERAL = "quota_period_months_positive"


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


def _quota_constraint_names(connection):
    """Return relevant CHECK names scoped to ``__reana.user_resource``."""
    rows = connection.execute(
        sa.text(
            "SELECT con.conname FROM pg_constraint AS con "
            "JOIN pg_class AS rel ON rel.oid = con.conrelid "
            "JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace "
            "WHERE ns.nspname = :schema AND rel.relname = :table "
            "AND con.contype = 'c' "
            "AND con.conname IN (:correct, :double_prefixed, :literal)"
        ),
        {
            "schema": "__reana",
            "table": "user_resource",
            "correct": _QUOTA_CORRECT,
            "double_prefixed": _QUOTA_DOUBLE_PREFIXED,
            "literal": _QUOTA_LITERAL,
        },
    ).fetchall()
    return {row[0] for row in rows}


def _repair_quota_constraint():
    """Converge stamped quota constraints without editing their history."""
    names = _quota_constraint_names(op.get_bind())
    if _QUOTA_CORRECT in names:
        for redundant in (_QUOTA_DOUBLE_PREFIXED, _QUOTA_LITERAL):
            if redundant in names:
                op.execute(
                    "ALTER TABLE __reana.user_resource DROP CONSTRAINT "
                    f'IF EXISTS "{redundant}"'
                )
        return
    source = next(
        (name for name in (_QUOTA_DOUBLE_PREFIXED, _QUOTA_LITERAL) if name in names),
        None,
    )
    if source:
        op.execute(
            "ALTER TABLE __reana.user_resource RENAME CONSTRAINT "
            f'"{source}" TO "{_QUOTA_CORRECT}"'
        )
        for redundant in (_QUOTA_DOUBLE_PREFIXED, _QUOTA_LITERAL):
            if redundant != source and redundant in names:
                op.execute(
                    "ALTER TABLE __reana.user_resource DROP CONSTRAINT "
                    f'IF EXISTS "{redundant}"'
                )
        return
    op.create_check_constraint(
        "quota_period_months_positive",
        "user_resource",
        "quota_period_months IS NULL OR quota_period_months > 0",
        schema="__reana",
    )


def upgrade():
    """Converge every known stamped state on the ORM's constraint name."""
    _repair_quota_constraint()
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
