"""Convert interactive session secrets to AES-GCM.

Revision ID: e940248e5165
Revises: 3f6c0d2a1b7e
Create Date: 2026-08-24 10:27:00.000000

Notebook session secrets were encrypted with deterministic AES-CBC for no
functional reason -- unlike the GitLab webhook secret before it, this value
is never queried by ciphertext and has no uniqueness requirement, so there
was nothing that needed determinism. Move it to authenticated, randomised
AES-GCM, matching ``gitlab_webhook_secret``'s ``8ae7b67c2d41`` conversion. No
digest column is added: a session secret is only ever looked up by its
owning row, never by value.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine, AesGcmEngine

import reana_db.config as db_config

# revision identifiers, used by Alembic.
revision = "e940248e5165"
down_revision = "3f6c0d2a1b7e"
branch_labels = None
depends_on = None


def _encryption_engines():
    """Return AES-CBC/AES-GCM engines initialised with the database key."""
    if not db_config.DB_SECRET_KEY:
        raise RuntimeError(
            "REANA_SECRET_KEY is required to migrate existing interactive "
            "session secrets."
        )
    cbc = AesEngine()
    cbc._set_padding_mechanism("pkcs5")
    cbc._update_key(db_config.DB_SECRET_KEY)
    gcm = AesGcmEngine()
    gcm._update_key(db_config.DB_SECRET_KEY)
    return cbc, gcm


def _secret_rows(connection):
    """Return raw encrypted session-secret rows without ORM decryption."""
    return connection.execute(
        sa.text(
            "SELECT id_, session_secret "
            "FROM __reana.interactive_session "
            "WHERE session_secret IS NOT NULL"
        )
    ).fetchall()


def _as_text(ciphertext):
    """Normalise the LargeBinary database value for encryption engines."""
    if isinstance(ciphertext, memoryview):
        ciphertext = ciphertext.tobytes()
    return ciphertext.decode("utf-8") if isinstance(ciphertext, bytes) else ciphertext


def upgrade():
    """Convert existing session-secret ciphertext from CBC to GCM."""
    connection = op.get_bind()
    rows = _secret_rows(connection)
    if rows:
        cbc, gcm = _encryption_engines()
        for session_id, ciphertext in rows:
            secret = cbc.decrypt(_as_text(ciphertext))
            connection.execute(
                sa.text(
                    "UPDATE __reana.interactive_session "
                    "SET session_secret = :ciphertext "
                    "WHERE id_ = :session_id"
                ),
                {
                    "ciphertext": gcm.encrypt(secret).encode("utf-8"),
                    "session_id": session_id,
                },
            )


def downgrade():
    """Restore deterministic CBC storage for session secrets."""
    connection = op.get_bind()
    rows = _secret_rows(connection)
    if rows:
        cbc, gcm = _encryption_engines()
        for session_id, ciphertext in rows:
            secret = gcm.decrypt(_as_text(ciphertext))
            connection.execute(
                sa.text(
                    "UPDATE __reana.interactive_session "
                    "SET session_secret = :ciphertext "
                    "WHERE id_ = :session_id"
                ),
                {
                    "ciphertext": cbc.encrypt(secret).encode("utf-8"),
                    "session_id": session_id,
                },
            )
