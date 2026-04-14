"""Drop old user_resource quota period anchor column.

Revision ID: 8f2d4e5a4d2c
Revises: 06dbbeef6d9b
Create Date: 2026-04-14 15:35:00.000000
"""

import calendar
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8f2d4e5a4d2c"
down_revision = "06dbbeef6d9b"
branch_labels = None
depends_on = None


def _add_months(dt, months):
    """Add whole months to a datetime while preserving time of day."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _get_current_quota_period_start_at(account_created_at, quota_period_months):
    """Derive the active quota window start from the account creation time."""
    if not account_created_at or not quota_period_months:
        return None

    now = datetime.utcnow()
    period_start_at = account_created_at
    while now >= _add_months(period_start_at, quota_period_months):
        period_start_at = _add_months(period_start_at, quota_period_months)
    return period_start_at


def upgrade():
    """Derive active quota windows and drop the legacy anchor column."""
    connection = op.get_bind()
    rows = connection.execute(sa.text("""
                SELECT
                    ur.user_id,
                    ur.resource_id,
                    ur.quota_period_months,
                    u.created AS account_created_at
                FROM __reana.user_resource AS ur
                JOIN __reana.user_ AS u ON u.id_ = ur.user_id
                WHERE ur.quota_period_months IS NOT NULL
                """)).mappings().all()

    for row in rows:
        current_period_start_at = _get_current_quota_period_start_at(
            row["account_created_at"],
            row["quota_period_months"],
        )
        connection.execute(
            sa.text("""
                UPDATE __reana.user_resource
                SET quota_period_start_at = :quota_period_start_at
                WHERE user_id = :user_id
                  AND resource_id = :resource_id
                """),
            {
                "quota_period_start_at": current_period_start_at,
                "user_id": row["user_id"],
                "resource_id": row["resource_id"],
            },
        )

    inspector = sa.inspect(connection)
    column_names = {
        column["name"]
        for column in inspector.get_columns("user_resource", schema="__reana")
    }
    if "quota_period_anchor_at" in column_names:
        op.drop_column("user_resource", "quota_period_anchor_at", schema="__reana")


def downgrade():
    """Keep the schema introduced in revision 06dbbeef6d9b."""
