# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Shared primitive for authenticated-encryption bearer secrets.

Every live bearer credential REANA persists (a delegated capability like a
GitLab webhook secret or a notebook session token) is a variation on the
same shape: high-entropy random value, authenticated encryption at rest,
optionally looked up by value rather than by owner. This module is the one
place that shape is implemented, so a new secret type inherits correct
encryption and concurrency-safe creation instead of reinventing both.
"""

import hashlib

from sqlalchemy import Column, String
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesGcmEngine

import reana_db.config


def _secret_key():
    """Secret key used to encrypt database columns.

    Do not use `DB_SECRET_KEY` directly, as that does not let us change the key
    at runtime, which is needed when migrating between different keys.
    """
    return reana_db.config.DB_SECRET_KEY


def bearer_secret_column(length=255, name=None):
    """Column factory for an authenticated-encryption bearer secret.

    The only sanctioned way to declare a bearer-secret column -- always
    AES-GCM, never a deterministic engine. A repo-level regression test
    (``tests/test_models.py``) asserts no ``EncryptedType`` column in
    ``models.py`` uses anything else.

    :param name: explicit database column name, for the (rare) case where
        the Python attribute must differ from it -- e.g. a private
        attribute backing a ``hybrid_property`` of the public name.
    """
    secret_type = EncryptedType(String(length=length), _secret_key, AesGcmEngine)
    return Column(name, secret_type) if name else Column(secret_type)


def lookup_digest_column():
    """Column factory for a bearer secret's non-reversible lookup digest.

    Pair with a value stored via :func:`bearer_secret_column` when the
    secret must be found by equality (e.g. an incoming webhook's token)
    rather than only through its owning row.
    """
    return Column(String(length=64))


def compute_lookup_digest(secret):
    """Return the stable SHA-256 lookup digest for a high-entropy secret."""
    if secret is None:
        return None
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def get_or_create_bearer_secret(session, model, pk_filter, secret_attr, generate_fn):
    """Atomically read-or-create a bearer secret on an existing owner row.

    Locks the row matching ``pk_filter`` with ``SELECT ... FOR UPDATE`` so
    that two concurrent callers racing to initialise the same secret cannot
    each generate and persist a different value: the first to acquire the
    lock creates the secret, and the second observes and reuses it. Any
    lifecycle policy layered on top of the returned value (e.g. rejecting an
    already-expired secret, or stamping a sibling expiry column only when a
    secret was actually just created) is the caller's responsibility -- this
    function only guarantees atomic creation, not the secret's
    business-level validity. A caller that needs to set such a sibling
    column can rely on the locked row being the same identity-mapped object
    as any already-loaded instance for that primary key in ``session``, and
    set it directly when ``created`` is true.

    The caller must commit; the row lock is held until it does.

    :param session: SQLAlchemy session to query and lock through.
    :param model: the ORM model owning the secret column.
    :param pk_filter: ``filter_by``-style kwargs identifying the one row.
    :param secret_attr: name of the bearer-secret attribute on ``model``.
    :param generate_fn: zero-argument callable producing a new secret value.
    :return: ``(value, created)`` -- the row's secret value (freshly
        created if it was empty) and whether this call was the one that
        created it.
    """
    # populate_existing() is required, not optional decoration: the caller
    # (e.g. an auth decorator) has very likely already loaded this exact row
    # earlier in the same request, before this function ever runs. Without
    # populate_existing(), SQLAlchemy's identity map returns that
    # already-mapped object without refreshing its attributes from this
    # query's result -- so although FOR UPDATE correctly blocks at the
    # database level until a concurrent winner commits, the loser reads back
    # its own *stale, pre-lock* in-memory value once unblocked, and wrongly
    # concludes no secret exists yet. That silently reduces this function to
    # the exact unsynchronized race it exists to prevent. Proven against a
    # real Postgres container with two genuinely concurrent transactions
    # (see the concurrency test) -- this is not a defensive-only measure.
    locked_row = (
        session.query(model)
        .filter_by(**pk_filter)
        .populate_existing()
        .with_for_update()
        .one()
    )
    value = getattr(locked_row, secret_attr)
    created = not value
    if created:
        value = generate_fn()
        setattr(locked_row, secret_attr, value)
    return value, created
