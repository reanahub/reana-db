"""Harden GitLab webhook secret storage and lookup.

Revision ID: 8ae7b67c2d41
Revises: d8f509a4169e
Create Date: 2026-08-21 15:00:00.000000

Webhook secrets were originally encrypted with deterministic AES-CBC so the
encrypted column itself could be searched and constrained as unique.  Split
those responsibilities: AES-GCM now protects the recoverable plaintext and a
SHA-256 digest provides stable lookup and uniqueness for the generated
256-bit secret.
"""

import hashlib

import sqlalchemy as sa
from alembic import op
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine, AesGcmEngine

import reana_db.config as db_config

# revision identifiers, used by Alembic.
revision = "8ae7b67c2d41"
down_revision = "d8f509a4169e"
branch_labels = None
depends_on = None


def _encryption_engines():
    """Return AES-CBC/AES-GCM engines initialised with the database key."""
    if not db_config.DB_SECRET_KEY:
        raise RuntimeError(
            "REANA_SECRET_KEY is required to migrate existing GitLab "
            "webhook secrets."
        )
    cbc = AesEngine()
    cbc._set_padding_mechanism("pkcs5")
    cbc._update_key(db_config.DB_SECRET_KEY)
    gcm = AesGcmEngine()
    gcm._update_key(db_config.DB_SECRET_KEY)
    return cbc, gcm


def _secret_rows(connection):
    """Return raw encrypted webhook-secret rows without ORM decryption."""
    return connection.execute(
        sa.text(
            "SELECT id_, gitlab_webhook_secret "
            "FROM __reana.user_ "
            "WHERE gitlab_webhook_secret IS NOT NULL"
        )
    ).fetchall()


def _as_text(ciphertext):
    """Normalise the LargeBinary database value for encryption engines."""
    if isinstance(ciphertext, memoryview):
        ciphertext = ciphertext.tobytes()
    return ciphertext.decode("utf-8") if isinstance(ciphertext, bytes) else ciphertext


def upgrade():
    """Add digest lookup and convert existing ciphertext from CBC to GCM."""
    op.add_column(
        "user_",
        sa.Column("gitlab_webhook_secret_digest", sa.String(length=64)),
        schema="__reana",
    )
    connection = op.get_bind()
    rows = _secret_rows(connection)
    if rows:
        cbc, gcm = _encryption_engines()
        for user_id, ciphertext in rows:
            secret = cbc.decrypt(_as_text(ciphertext))
            connection.execute(
                sa.text(
                    "UPDATE __reana.user_ "
                    "SET gitlab_webhook_secret = :ciphertext, "
                    "gitlab_webhook_secret_digest = :digest "
                    "WHERE id_ = :user_id"
                ),
                {
                    "ciphertext": gcm.encrypt(secret).encode("utf-8"),
                    "digest": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
                    "user_id": user_id,
                },
            )
    op.drop_constraint(
        "uq_user__gitlab_webhook_secret",
        "user_",
        schema="__reana",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_user__gitlab_webhook_secret_digest",
        "user_",
        ["gitlab_webhook_secret_digest"],
        schema="__reana",
    )
    op.create_check_constraint(
        "gitlab_webhook_secret_complete",
        "user_",
        "(gitlab_webhook_secret IS NULL) = " "(gitlab_webhook_secret_digest IS NULL)",
        schema="__reana",
    )


def downgrade():
    """Restore deterministic CBC storage and ciphertext uniqueness."""
    connection = op.get_bind()
    rows = _secret_rows(connection)
    if rows:
        cbc, gcm = _encryption_engines()
        for user_id, ciphertext in rows:
            secret = gcm.decrypt(_as_text(ciphertext))
            connection.execute(
                sa.text(
                    "UPDATE __reana.user_ "
                    "SET gitlab_webhook_secret = :ciphertext "
                    "WHERE id_ = :user_id"
                ),
                {
                    "ciphertext": cbc.encrypt(secret).encode("utf-8"),
                    "user_id": user_id,
                },
            )
    op.drop_constraint(
        "gitlab_webhook_secret_complete",
        "user_",
        schema="__reana",
        type_="check",
    )
    op.drop_constraint(
        "uq_user__gitlab_webhook_secret_digest",
        "user_",
        schema="__reana",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_user__gitlab_webhook_secret",
        "user_",
        ["gitlab_webhook_secret"],
        schema="__reana",
    )
    op.drop_column("user_", "gitlab_webhook_secret_digest", schema="__reana")
