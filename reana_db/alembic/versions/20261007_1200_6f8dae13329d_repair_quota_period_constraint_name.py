"""Repair the quota period constraint name on already-stamped databases.

Revision ID: 6f8dae13329d
Revises: a6c2120d5b2b
Create Date: 2026-10-07 12:00:00.000000

Revision ``06dbbeef6d9b`` created the ``user_resource`` quota period check
constraint under a double-prefixed name. The repair of that name was later
added to revision ``3f6c0d2a1b7e``, which some development databases had
already applied; those databases are stamped past it and never ran the
repair. It is not known whether all of them have since been rebuilt, so this
forward revision repeats the repair. It does nothing on databases whose
constraint already has the expected name.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "6f8dae13329d"
down_revision = "a6c2120d5b2b"
branch_labels = None
depends_on = None

_CORRECT = "ck_user_resource_quota_period_months_positive"
_HISTORICAL = (
    "ck_user_resource_ck_user_resource_quota_period_months_positive",
    "quota_period_months_positive",
)


def _constraint_names(connection):
    """Return the known quota period CHECK names found on the table."""
    rows = connection.execute(
        sa.text(
            "SELECT con.conname FROM pg_constraint AS con "
            "JOIN pg_class AS rel ON rel.oid = con.conrelid "
            "JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace "
            "WHERE ns.nspname = '__reana' AND rel.relname = 'user_resource' "
            "AND con.contype = 'c' AND con.conname IN :names"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": [_CORRECT, *_HISTORICAL]},
    ).fetchall()
    return {row[0] for row in rows}


def upgrade():
    """Converge every known constraint state on the expected name."""
    names = _constraint_names(op.get_bind())
    if _CORRECT not in names:
        source = next((name for name in _HISTORICAL if name in names), None)
        if source:
            op.execute(
                "ALTER TABLE __reana.user_resource RENAME CONSTRAINT "
                f'"{source}" TO "{_CORRECT}"'
            )
            names.discard(source)
        else:
            op.create_check_constraint(
                "quota_period_months_positive",
                "user_resource",
                "quota_period_months IS NULL OR quota_period_months > 0",
                schema="__reana",
            )
    for redundant in _HISTORICAL:
        if redundant in names:
            op.execute(
                "ALTER TABLE __reana.user_resource DROP CONSTRAINT "
                f'IF EXISTS "{redundant}"'
            )


def downgrade():
    """Leave the repaired constraint intact.

    This is a corrective revision: the ``06dbbeef6d9b`` downgrade removes
    the constraint together with the quota period columns.
    """
