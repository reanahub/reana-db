# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for the shared bearer-secret primitive."""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from sqlalchemy.orm import sessionmaker
from sqlalchemy_utils.types.encrypted.encrypted_type import AesGcmEngine

from reana_db import database
from reana_db.models import User
from reana_db.secrets import (
    bearer_secret_column,
    compute_lookup_digest,
    get_or_create_bearer_secret,
)


def test_bearer_secret_column_uses_authenticated_encryption():
    """The factory must always produce AES-GCM, never a deterministic engine."""
    assert isinstance(bearer_secret_column().type.engine, AesGcmEngine)


def test_models_never_declares_encrypted_type_directly():
    """Every bearer-secret column must go through the shared factory.

    A column declared as ``EncryptedType(...)`` directly in ``models.py``
    bypasses ``bearer_secret_column()`` and could silently reintroduce a
    deterministic engine -- exactly how ``InteractiveSession.session_secret``
    ended up on CBC while ``User.gitlab_webhook_secret`` was already on GCM.
    This statically asserts models.py contains no such call, so a new secret
    column is structurally forced through the factory instead of relying on
    a reviewer to notice.
    """
    models_path = Path(database.__file__).parent / "models.py"
    tree = ast.parse(models_path.read_text(), filename=str(models_path))
    direct_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EncryptedType"
    ]
    assert direct_calls == []


def test_compute_lookup_digest_matches_stored_digest(db, session):
    """The digest helper matches what the model computes on assignment."""
    secret = f"webhook-{uuid4()}"
    user = User(email=f"{uuid4()}@reana.io", gitlab_webhook_secret=secret)
    session.add(user)
    session.commit()

    assert user.gitlab_webhook_secret_digest == compute_lookup_digest(secret)
    assert compute_lookup_digest(None) is None


def test_get_or_create_bearer_secret_creates_when_absent(db, session):
    """A row with no existing secret gets one generated and persisted."""
    user = User(email=f"{uuid4()}@reana.io")
    session.add(user)
    session.commit()
    generated_value = f"generated-{uuid4()}"

    value, created = get_or_create_bearer_secret(
        session,
        User,
        {"id_": user.id_},
        "gitlab_webhook_secret",
        lambda: generated_value,
    )
    session.commit()

    assert value == generated_value
    assert created is True
    session.refresh(user)
    assert user.gitlab_webhook_secret == generated_value


def test_get_or_create_bearer_secret_reuses_existing(db, session):
    """A row with an existing secret returns it unchanged, never regenerated."""
    existing_value = f"already-there-{uuid4()}"
    user = User(email=f"{uuid4()}@reana.io", gitlab_webhook_secret=existing_value)
    session.add(user)
    session.commit()

    def _fail():
        raise AssertionError("generate_fn must not be called when a secret exists")

    value, created = get_or_create_bearer_secret(
        session, User, {"id_": user.id_}, "gitlab_webhook_secret", _fail
    )
    session.commit()

    assert value == existing_value
    assert created is False


def test_get_or_create_bearer_secret_serializes_concurrent_creation(db, session):
    """Two concurrent first-creates on the same row converge on one value.

    Two independent sessions race to be the first to observe an empty
    secret, synchronized with a barrier so both start their attempt at the
    same time. ``get_or_create_bearer_secret``'s ``SELECT ... FOR UPDATE``
    then serializes them at the database level: the loser's query blocks
    until the winner commits, at which point it must observe the winner's
    already-persisted value rather than generating and persisting a second,
    different one. The barrier must fire *before* either thread issues its
    locking query -- synchronizing any later (e.g. on flush) would deadlock,
    since the loser would already be blocked inside Postgres by then.
    """
    user = User(email=f"{uuid4()}@reana.io")
    session.add(user)
    session.commit()
    user_id = user.id_

    entry_barrier = Barrier(2)
    independent_session = sessionmaker(bind=database.engine)

    def _create_racing():
        worker_session = independent_session()
        try:
            entry_barrier.wait(timeout=10)
            value, created = get_or_create_bearer_secret(
                worker_session,
                User,
                {"id_": user_id},
                "gitlab_webhook_secret",
                lambda: f"generated-{uuid4()}",
            )
            worker_session.commit()
            return value, created
        finally:
            worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _create_racing(), range(2)))

    values = [value for value, _created in results]
    created_flags = [created for _value, created in results]
    assert values[0] == values[1]
    assert sorted(created_flags) == [False, True]
    session.refresh(user)
    assert user.gitlab_webhook_secret == values[0]
