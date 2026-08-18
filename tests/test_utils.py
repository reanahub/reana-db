# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB utils tests."""

from __future__ import absolute_import, print_function
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import mock
import pytest
from sqlalchemy.orm import sessionmaker

from reana_commons.config import SHARED_VOLUME_PATH

import reana_db.utils as utils
from reana_db import database
from reana_db import config as db_config
from reana_db.models import (
    InteractiveSession,
    User,
    UserResource,
    Workflow,
)
from reana_db.secrets import compute_lookup_digest
from reana_db.utils import (
    _advance_user_cpu_quota_period_if_needed,
    _add_months,
    _get_accounted_workflow_cpu_milliseconds,
    _get_current_user_cpu_quota_period_start_at,
    _get_workflow_with_uuid_or_name,
    get_current_quota_period_start_at,
    split_run_number,
    update_users_cpu_quota,
    update_workflow_cpu_quota,
    update_workflows_cpu_quota,
    update_workflows_disk_quota,
    change_key_encrypted_columns,
)


@pytest.mark.parametrize(
    "run_number, run_number_major, run_number_minor",
    [
        ("1", 1, 0),
        ("156.12", 156, 12),
        ("2.4", 2, 4),
        (3.22, 3, 22),
        pytest.param(
            "1.2.3",
            None,
            None,
            marks=pytest.mark.xfail(raises=ValueError, strict=True),
        ),
    ],
)
def test_split_run_number(run_number, run_number_major, run_number_minor):
    """Tests for split_run_number()."""
    assert split_run_number(run_number) == (run_number_major, run_number_minor)


@pytest.mark.parametrize(
    "user_id,workflow_id,workspace_root_path,workspace_path",
    [
        (0, None, None, SHARED_VOLUME_PATH + "/users/0/workflows"),
        (0, 1, None, SHARED_VOLUME_PATH + "/users/0/workflows/1"),
        (0, 1, "/eos/myanalysis", "/eos/myanalysis/1"),
        (0, 1, SHARED_VOLUME_PATH, SHARED_VOLUME_PATH + "/users/0/workflows/1"),
        (0, 1, SHARED_VOLUME_PATH + "/db", SHARED_VOLUME_PATH + "/users/0/workflows/1"),
    ],
)
def test_build_workspace_path(
    user_id, workflow_id, workspace_root_path, workspace_path
):
    """Tests for build_workspace_path()."""
    from reana_db.utils import build_workspace_path

    assert (
        build_workspace_path(
            user_id=user_id,
            workflow_id=workflow_id,
            workspace_root_path=workspace_root_path,
        )
        == workspace_path
    )


def test_get_workflow_with_uuid_or_name(session, new_user):
    """Tests for _get_workflow_with_uuid_or_name."""
    workflow = Workflow(
        id_=uuid4(),
        name="workflow",
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
    )
    session.add(workflow)
    session.commit()

    user_uuid = str(new_user.id_)
    assert workflow == _get_workflow_with_uuid_or_name(str(workflow.id_), user_uuid)
    assert workflow == _get_workflow_with_uuid_or_name(workflow.name, user_uuid)
    assert workflow == _get_workflow_with_uuid_or_name(f"{workflow.name}.1", user_uuid)

    # Check that an exception is raised when passing the wrong owner
    another_user_uuid = str(uuid4())
    with pytest.raises(ValueError):
        _get_workflow_with_uuid_or_name(str(workflow.id_), another_user_uuid)
    with pytest.raises(ValueError):
        _get_workflow_with_uuid_or_name(workflow.name, another_user_uuid)
    with pytest.raises(ValueError):
        _get_workflow_with_uuid_or_name(f"{workflow.name}.1", another_user_uuid)


@pytest.mark.parametrize(
    "quota_period_start_at, expected_milliseconds",
    [
        (None, 30 * 60 * 1000),
        (datetime(2026, 4, 1, 10, 10, 0), 20 * 60 * 1000),
        (datetime(2026, 4, 1, 11, 0, 0), 0),
    ],
)
def test_get_accounted_workflow_cpu_milliseconds(
    quota_period_start_at, expected_milliseconds
):
    """Test workflow CPU accounting inside a periodic quota window."""
    workflow = SimpleNamespace(
        run_started_at=datetime(2026, 4, 1, 10, 0, 0),
        run_finished_at=datetime(2026, 4, 1, 10, 30, 0),
        run_stopped_at=None,
    )

    assert (
        _get_accounted_workflow_cpu_milliseconds(
            workflow, quota_period_start_at=quota_period_start_at
        )
        == expected_milliseconds
    )


@pytest.mark.parametrize(
    "dt, months, expected",
    [
        (datetime(2026, 1, 31, 12, 0, 0), 1, datetime(2026, 2, 28, 12, 0, 0)),
        (datetime(2024, 2, 29, 8, 15, 0), 12, datetime(2025, 2, 28, 8, 15, 0)),
        (datetime(2026, 12, 31, 23, 30, 0), 2, datetime(2027, 2, 28, 23, 30, 0)),
    ],
)
def test_add_months_clamps_to_last_valid_day(dt, months, expected):
    """Test month addition clamps to the last valid day of the target month."""
    assert _add_months(dt, months) == expected


@pytest.mark.parametrize(
    "reference_start_at, quota_period_months, now, expected",
    [
        (None, 3, datetime(2026, 4, 14, 0, 0, 0), None),
        (
            datetime(2026, 1, 15, 12, 0, 0),
            3,
            datetime(2026, 5, 20, 0, 0, 0),
            datetime(2026, 4, 15, 12, 0, 0),
        ),
        (
            datetime(2026, 1, 31, 12, 0, 0),
            1,
            datetime(2027, 3, 1, 0, 0, 0),
            datetime(2027, 2, 28, 12, 0, 0),
        ),
    ],
)
def test_get_current_quota_period_start_at(
    reference_start_at, quota_period_months, now, expected
):
    """Test deriving the active quota period from a reference timestamp."""
    assert (
        get_current_quota_period_start_at(
            reference_start_at, quota_period_months, now=now
        )
        == expected
    )


def test_get_current_user_cpu_quota_period_start_at_falls_back_to_user_created():
    """Test periodic CPU quota fallback to the account creation timestamp."""
    user_resource_quota = SimpleNamespace(
        quota_period_months=3,
        quota_period_start_at=None,
        user=SimpleNamespace(created=datetime(2026, 1, 15, 12, 0, 0)),
    )

    assert _get_current_user_cpu_quota_period_start_at(
        user_resource_quota, now=datetime(2026, 5, 20, 0, 0, 0)
    ) == datetime(2026, 4, 15, 12, 0, 0)


def test_advance_user_cpu_quota_period_if_needed_updates_stored_period_start():
    """Test advancing a stored periodic CPU quota window to the current one."""
    user_resource_quota = SimpleNamespace(
        quota_period_months=3,
        quota_period_start_at=datetime(2026, 1, 15, 12, 0, 0),
        user=SimpleNamespace(created=datetime(2026, 1, 15, 12, 0, 0)),
        user_id="user-1",
    )

    assert _advance_user_cpu_quota_period_if_needed(
        user_resource_quota, now=datetime(2026, 5, 20, 0, 0, 0)
    )
    assert user_resource_quota.quota_period_start_at == datetime(2026, 4, 15, 12, 0, 0)
    assert not _advance_user_cpu_quota_period_if_needed(
        user_resource_quota, now=datetime(2026, 5, 20, 0, 0, 0)
    )


def test_update_workflow_cpu_quota_respects_override_policy_checks(monkeypatch):
    """Test manual CPU quota refresh overrides policy checks."""
    session = mock.MagicMock()
    workflow_resource_query = mock.MagicMock()
    workflow_resource_query.filter_by.return_value.one_or_none.return_value = None
    session.query.return_value = workflow_resource_query

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "should_skip_quota_update", mock.Mock(return_value=True))
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(
        utils, "_get_accounted_workflow_cpu_milliseconds", mock.Mock(return_value=1234)
    )

    workflow = SimpleNamespace(id_="workflow-1")

    assert update_workflow_cpu_quota(workflow) == 0
    assert update_workflow_cpu_quota(workflow, override_policy_checks=True) == 1234
    assert session.add.call_args[0][0].quota_used == 1234
    session.commit.assert_called_once()


def test_update_workflows_cpu_quota_passes_override_policy_checks(monkeypatch):
    """Test CPU quota cronjob forwards override flags to workflow updates."""
    session = mock.MagicMock()
    workflow_query = mock.MagicMock()
    workflow_query.options.return_value.all.return_value = [
        SimpleNamespace(id_="workflow-1"),
        SimpleNamespace(id_="workflow-2"),
    ]
    session.query.return_value = workflow_query
    timer = mock.MagicMock()

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "Timer", mock.Mock(return_value=timer))
    update_workflow_cpu_quota_mock = mock.Mock()
    monkeypatch.setattr(
        utils, "update_workflow_cpu_quota", update_workflow_cpu_quota_mock
    )

    update_workflows_cpu_quota(override_policy_checks=True)

    assert session.expunge.call_count == 2
    update_workflow_cpu_quota_mock.assert_has_calls(
        [
            mock.call(
                workflow_query.options.return_value.all.return_value[0],
                override_policy_checks=True,
            ),
            mock.call(
                workflow_query.options.return_value.all.return_value[1],
                override_policy_checks=True,
            ),
        ]
    )
    assert timer.count_event.call_count == 2


def test_update_users_cpu_quota_override_bypasses_policy_gate(monkeypatch):
    """Test manual user CPU quota refresh bypasses the policy gate."""
    session = mock.MagicMock()
    ur_query = mock.MagicMock()
    ur_query.filter_by.return_value.filter_by.return_value.all.return_value = []
    session.query.return_value = ur_query
    user = SimpleNamespace(id_="user-1")

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "should_skip_quota_update", mock.Mock(return_value=True))
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(utils, "Timer", mock.Mock())

    # Policy gate active: without the override the refresh is skipped entirely,
    # before any database query is issued.
    assert update_users_cpu_quota(user=user) is None
    session.query.assert_not_called()

    # The override bypasses the gate and refreshes from the CPU quota rows.
    update_users_cpu_quota(user=user, override_policy_checks=True)

    session.query.assert_called_once_with(UserResource)
    ur_query.filter_by.assert_called_once_with(resource_id="cpu")
    ur_query.filter_by.return_value.filter_by.assert_called_once_with(user_id="user-1")


def test_update_users_cpu_quota_bulk_drives_from_quota_rows(monkeypatch):
    """Bulk CPU quota maintenance scans CPU quota rows, not the whole user table.

    Driving from ``UserResource`` still includes accounts not yet linked to
    an identity, since every account has a quota row, while avoiding a full
    ``user_`` table scan and a per-account quota lookup.
    """
    session = mock.MagicMock()
    quota_rows = [
        SimpleNamespace(user_id="jwt-user", quota_used=None),
        SimpleNamespace(user_id="legacy-user", quota_used=None),
    ]
    ur_query = mock.MagicMock()
    ur_query.filter_by.return_value.all.return_value = quota_rows
    # Each row falls into the no-active-window branch, which sums workflow CPU.
    sum_query = mock.MagicMock()
    sum_query.filter.return_value.join.return_value.filter.return_value.scalar.return_value = (
        42
    )
    session.query.side_effect = [ur_query, sum_query, sum_query]
    timer = mock.MagicMock()

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(utils, "Timer", mock.Mock(return_value=timer))
    monkeypatch.setattr(utils, "_advance_user_cpu_quota_period_if_needed", mock.Mock())
    monkeypatch.setattr(
        utils,
        "_get_current_user_cpu_quota_period_start_at",
        mock.Mock(return_value=None),
    )

    update_users_cpu_quota(override_policy_checks=True)

    # Driven from the CPU ``UserResource`` rows...
    assert session.query.call_args_list[0] == mock.call(UserResource)
    ur_query.filter_by.assert_called_once_with(resource_id="cpu")
    # ...and never from a full ``user_`` table scan (identity check avoids
    # evaluating SQLAlchemy expression equality).
    queried_models = [call.args[0] for call in session.query.call_args_list]
    assert not any(model is User for model in queried_models)
    # Both quota rows were updated and the timer advanced once each.
    assert [row.quota_used for row in quota_rows] == [42, 42]
    assert timer.count_event.call_count == 2


def test_change_key_rotates_every_encrypted_column(db, session):
    """Key rotation covers every encrypted secret column."""
    old_key = f"old-{uuid4()}"
    new_key = db_config.DB_SECRET_KEY
    webhook_value = f"webhook-{uuid4()}"
    session_value = f"session-{uuid4()}"

    try:
        # The package-scoped test database retains rows created by earlier
        # tests. Key rotation assumes one current key across the database, so
        # isolate the encrypted columns before creating old-key fixtures.
        session.query(InteractiveSession).delete(synchronize_session=False)
        session.query(User).update(
            {
                "gitlab_webhook_secret": None,
                "gitlab_webhook_secret_digest": None,
            },
            synchronize_session=False,
        )
        session.commit()
        db_config.DB_SECRET_KEY = old_key
        user = User(
            email=f"{uuid4()}@reana.io",
            gitlab_webhook_secret=webhook_value,
        )
        session.add(user)
        session.flush()
        interactive_session = InteractiveSession(
            name=f"session-{uuid4()}",
            path=f"/sessions/{uuid4()}",
            owner_id=user.id_,
            session_secret=session_value,
        )
        session.add(interactive_session)
        session.commit()
        ids = (user.id_, interactive_session.id_)
        session.expunge_all()

        db_config.DB_SECRET_KEY = new_key
        change_key_encrypted_columns(old_key)
        session.expunge_all()

        assert session.query(User).filter_by(
            id_=ids[0]
        ).one().gitlab_webhook_secret == (webhook_value)
        assert (
            session.query(InteractiveSession).filter_by(id_=ids[1]).one().session_secret
            == session_value
        )
    finally:
        db_config.DB_SECRET_KEY = new_key


def test_change_key_raises_actionable_error_on_undecryptable_secret(db, session):
    """A secret undecryptable under either key must fail loudly, not silently.

    Prior to the Task 4.2 fix (PR269-11), this test reproduced the ordinary
    TOCTOU race -- a secret written under the *new* key before rotation ran
    -- and asserted it raised. That is no longer the expected behaviour: the
    fix makes ``change_key_encrypted_columns`` try each value under
    ``old_key`` first and silently accept it if it instead decrypts under
    ``new_key``, since that means a concurrent writer already rotated it
    correctly. See ``test_change_key_recovers_from_concurrent_new_key_write``
    below for that now-passing race scenario, and for proof that a second
    call is not needed to make it succeed.

    What must still raise is a secret that decrypts under *neither* key --
    e.g. genuine data corruption, or ciphertext from some unrelated key --
    which this test reproduces by writing a secret under a third key that is
    neither ``old_key`` nor ``new_key``. Decrypting it here must not surface
    as a raw sqlalchemy_utils padding/decode error -- it should be a clear,
    actionable RuntimeError telling the operator what happened, and it must
    not silently corrupt the row.
    """
    old_key = f"old-{uuid4()}"
    new_key = db_config.DB_SECRET_KEY
    third_key = f"third-{uuid4()}"
    corrupted_user_email = f"{uuid4()}@reana.io"

    try:
        session.query(InteractiveSession).delete(synchronize_session=False)
        session.query(User).update(
            {
                "gitlab_webhook_secret": None,
                "gitlab_webhook_secret_digest": None,
            },
            synchronize_session=False,
        )
        session.commit()

        # A secret encrypted under neither old_key nor new_key at all --
        # undecryptable under both, by construction.
        db_config.DB_SECRET_KEY = third_key
        corrupted_user = User(
            email=corrupted_user_email,
            gitlab_webhook_secret=f"webhook-{uuid4()}",
        )
        session.add(corrupted_user)
        session.commit()
        corrupted_id = corrupted_user.id_
        session.expunge_all()

        db_config.DB_SECRET_KEY = new_key
        with pytest.raises(RuntimeError, match="genuine data corruption"):
            change_key_encrypted_columns(old_key)

        # The corrupted row must be untouched, not silently overwritten.
        db_config.DB_SECRET_KEY = third_key
        session.expunge_all()
        assert (
            session.query(User).filter_by(id_=corrupted_id).one().gitlab_webhook_secret
            is not None
        )
    finally:
        db_config.DB_SECRET_KEY = new_key
        # corrupted_user's secret is still undecryptable under new_key --
        # leaving it would make every later test that reads all users'
        # gitlab_webhook_secret hit the same decode error this test exists
        # to catch. Clear it under the key it was actually written with so
        # nothing undecryptable survives into other tests.
        db_config.DB_SECRET_KEY = third_key
        session.query(User).filter(User.email == corrupted_user_email).update(
            {
                "gitlab_webhook_secret": None,
                "gitlab_webhook_secret_digest": None,
            },
            synchronize_session=False,
        )
        session.commit()
        db_config.DB_SECRET_KEY = new_key


def test_change_key_recovers_from_concurrent_new_key_write(db, session):
    """Retry-safety: a row raced by a live writer mid-rotation must not wedge.

    Reproduces the exact scenario PR269-11 fixes: while rotation is running,
    a live reana-server process (already deployed with the new key, as the
    runbook requires) renews a webhook secret for a row rotation has not yet
    reached -- that row is now already encrypted under ``new_key``. Before
    the fix, rotation reading that row under ``old_key`` would raise, and
    every retry would hit the exact same row and fail identically forever,
    since retrying re-reads the same now-new-key-encrypted ciphertext under
    ``old_key`` again. The fix makes each value tried under ``old_key``
    first, falling back to ``new_key`` (and skipping silently) on failure,
    so this is no longer a dead end.

    Uses the same real-Postgres, real-thread race pattern as
    ``test_initialise_default_resources_converges_across_sessions`` in
    ``tests/test_models.py`` (an independent ``sessionmaker`` session racing
    the test's own session against actual Postgres), but coordinated via a
    reusable two-phase ``Barrier`` instead of a ``before_flush`` listener,
    since ``change_key_encrypted_columns`` has no flush to hook during its
    read phase. ``change_key_encrypted_columns`` accepts a private
    ``_after_ids_fetched`` test hook for exactly this: it is invoked once
    rotation has fetched the ids to rotate but before it reads any row's
    value, which is the precise window the race needs to land in.
    """
    old_key = f"old-{uuid4()}"
    new_key = db_config.DB_SECRET_KEY
    racing_user_email = f"{uuid4()}@reana.io"
    old_webhook_value = f"old-webhook-{uuid4()}"
    new_webhook_value = f"new-webhook-{uuid4()}"

    independent_session_factory = sessionmaker(bind=database.engine)
    # Reused for two rendezvous points (a threading.Barrier resets itself
    # once every party has passed through, so it is safe to await twice):
    #   1. rotation has captured its id list -> safe for the writer to write
    #   2. the writer's write is committed -> safe for rotation to read rows
    race_barrier = Barrier(2)

    def live_server_write():
        """Simulate reana-server renewing this secret mid-rotation."""
        race_barrier.wait(timeout=10)  # (1) wait for rotation's id list
        worker_session = independent_session_factory()
        try:
            db_config.DB_SECRET_KEY = new_key
            worker_session.query(User).filter_by(id_=racing_id).update(
                {
                    "gitlab_webhook_secret": new_webhook_value,
                    "gitlab_webhook_secret_digest": compute_lookup_digest(
                        new_webhook_value
                    ),
                },
                synchronize_session=False,
            )
            worker_session.commit()
        finally:
            worker_session.close()
        race_barrier.wait(timeout=10)  # (2) tell rotation the write landed

    def rotation_sync_hook():
        """Rendezvous (1) then (2), matching ``live_server_write``'s two waits."""
        race_barrier.wait(timeout=10)  # (1) id list captured -> writer may write
        race_barrier.wait(timeout=10)  # (2) writer's write landed -> safe to read

    def run_rotation():
        return change_key_encrypted_columns(
            old_key, _after_ids_fetched=rotation_sync_hook
        )

    try:
        session.query(InteractiveSession).delete(synchronize_session=False)
        session.query(User).update(
            {
                "gitlab_webhook_secret": None,
                "gitlab_webhook_secret_digest": None,
            },
            synchronize_session=False,
        )
        session.commit()

        # The row rotation will race: written under old_key, like any
        # ordinary pre-rotation secret.
        db_config.DB_SECRET_KEY = old_key
        racing_user = User(
            email=racing_user_email, gitlab_webhook_secret=old_webhook_value
        )
        session.add(racing_user)
        session.commit()
        racing_id = racing_user.id_
        session.expunge_all()
        db_config.DB_SECRET_KEY = new_key

        with ThreadPoolExecutor(max_workers=2) as executor:
            rotation_future = executor.submit(run_rotation)
            writer_future = executor.submit(live_server_write)
            writer_future.result(timeout=10)
            rotation_future.result(timeout=10)

        # The race must not have raised: the row is already correctly
        # encrypted under new_key (by the concurrent writer) and rotation
        # must have silently left it alone rather than erroring.
        db_config.DB_SECRET_KEY = new_key
        session.expunge_all()
        assert (
            session.query(User).filter_by(id_=racing_id).one().gitlab_webhook_secret
            == new_webhook_value
        )

        # Retry-safety is the actual regression guard: a second call, run
        # after the race window has closed, must also complete without
        # raising and without disturbing the already-correct value. Before
        # the fix, this exact row would have failed identically on every
        # retry forever.
        change_key_encrypted_columns(old_key)
        session.expunge_all()
        assert (
            session.query(User).filter_by(id_=racing_id).one().gitlab_webhook_secret
            == new_webhook_value
        )
    finally:
        # Deleting racing_user outright would hit the FK from its
        # auto-created UserResource quota rows; clearing the secret (like
        # the other change_key_* tests' cleanup) is enough to keep it from
        # affecting later tests that read every user's gitlab_webhook_secret.
        db_config.DB_SECRET_KEY = new_key
        session.query(User).filter(User.email == racing_user_email).update(
            {
                "gitlab_webhook_secret": None,
                "gitlab_webhook_secret_digest": None,
            },
            synchronize_session=False,
        )
        session.commit()


def test_change_key_locks_each_value_before_reencrypting(monkeypatch):
    """Rotation must lock a row before its plaintext is read and rewritten."""
    fake_session = mock.MagicMock()
    user_ids_query = mock.MagicMock()
    session_ids_query = mock.MagicMock()
    value_query = mock.MagicMock()
    update_query = mock.MagicMock()
    user_id = uuid4()

    user_ids_query.filter.return_value = user_ids_query
    user_ids_query.all.return_value = [SimpleNamespace(id_=user_id)]
    session_ids_query.filter.return_value = session_ids_query
    session_ids_query.all.return_value = []
    value_query.filter.return_value = value_query
    value_query.with_for_update.return_value = value_query
    value_query.scalar.return_value = "old-webhook-secret"
    update_query.filter.return_value = update_query
    fake_session.query.side_effect = [
        user_ids_query,
        session_ids_query,
        value_query,
        update_query,
    ]
    monkeypatch.setattr(database, "Session", fake_session)
    monkeypatch.setattr(db_config, "DB_SECRET_KEY", "new-key")

    change_key_encrypted_columns("old-key")

    value_query.with_for_update.assert_called_once_with()
    update_query.update.assert_called_once_with(
        {"gitlab_webhook_secret": "old-webhook-secret"}
    )
    fake_session.commit.assert_called_once_with()


def test_update_users_cpu_quota_periodic_path_loads_only_needed_fields(monkeypatch):
    """Test periodic CPU refresh avoids loading heavy workflow columns."""
    session = mock.MagicMock()
    user_resource_query = mock.MagicMock()
    workflow_query = mock.MagicMock()
    workflow_options_query = mock.MagicMock()
    timer = mock.MagicMock()
    user = SimpleNamespace(id_="user-1")
    user_resource_quota = SimpleNamespace(
        user_id="user-1",
        quota_period_months=3,
        quota_period_start_at=datetime(2026, 4, 1, 0, 0, 0),
        quota_used=0,
    )
    workflows = [SimpleNamespace(id_="wf-1"), SimpleNamespace(id_="wf-2")]

    user_resource_query.filter_by.return_value.filter_by.return_value.all.return_value = [
        user_resource_quota
    ]
    workflow_query.options.return_value = workflow_options_query
    workflow_options_query.filter_by.return_value.all.return_value = workflows
    session.query.side_effect = [user_resource_query, workflow_query]

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(utils, "Timer", mock.Mock(return_value=timer))
    monkeypatch.setattr(
        utils, "_advance_user_cpu_quota_period_if_needed", mock.Mock(return_value=False)
    )
    monkeypatch.setattr(
        utils,
        "_get_current_user_cpu_quota_period_start_at",
        mock.Mock(return_value=datetime(2026, 4, 1, 0, 0, 0)),
    )
    monkeypatch.setattr(
        utils,
        "_get_accounted_workflow_cpu_milliseconds",
        mock.Mock(side_effect=[100, 200]),
    )
    monkeypatch.setattr(utils, "load_only", mock.Mock(return_value="load_only_option"))
    defer_mock = mock.Mock(side_effect=["defer_logs", "defer_reana_specification"])
    monkeypatch.setattr(utils, "defer", defer_mock)

    update_users_cpu_quota(user=user, override_policy_checks=True)

    workflow_query.options.assert_called_once_with(
        "load_only_option",
        "defer_logs",
        "defer_reana_specification",
    )
    workflow_options_query.filter_by.assert_called_once_with(owner_id="user-1")
    assert user_resource_quota.quota_used == 300
    session.commit.assert_called_once()
    timer.count_event.assert_called_once()


def test_update_workflows_disk_quota_passes_override_policy_checks(monkeypatch):
    """Test disk quota cronjob forwards override flags to workflow updates."""
    session = mock.MagicMock()
    workflow_query = mock.MagicMock()
    workflow_query.options.return_value.all.return_value = [
        SimpleNamespace(id_="workflow-1")
    ]
    session.query.return_value = workflow_query
    timer = mock.MagicMock()
    store_workflow_disk_quota_mock = mock.Mock()

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "Timer", mock.Mock(return_value=timer))
    monkeypatch.setattr(
        utils, "store_workflow_disk_quota", store_workflow_disk_quota_mock
    )

    update_workflows_disk_quota(override_policy_checks=True)

    session.expunge.assert_called_once_with(
        workflow_query.options.return_value.all.return_value[0]
    )
    store_workflow_disk_quota_mock.assert_called_once_with(
        workflow_query.options.return_value.all.return_value[0],
        override_policy_checks=True,
    )
    timer.count_event.assert_called_once()


def test_store_workflow_disk_quota_override_bypasses_policy_gates(monkeypatch):
    """Test manual disk quota refresh still reads workspace usage with override."""
    session = mock.MagicMock()
    workflow_resource_query = mock.MagicMock()
    workflow_resource = SimpleNamespace(quota_used=1)
    workflow_resource_query.filter_by.return_value.one_or_none.return_value = (
        workflow_resource
    )
    session.query.return_value = workflow_resource_query

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY", False)
    monkeypatch.setattr(utils, "WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY", [])
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="disk")),
    )
    monkeypatch.setattr(
        utils,
        "get_disk_usage",
        mock.Mock(return_value=[{"size": {"raw": 294912}}]),
    )

    workflow = SimpleNamespace(id_="workflow-1", workspace_path="/var/reana/workflow-1")

    utils.store_workflow_disk_quota(workflow, override_policy_checks=True)

    assert workflow_resource.quota_used == 294912
    session.commit.assert_called_once()
