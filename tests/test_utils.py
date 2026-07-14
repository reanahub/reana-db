# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB utils tests."""

from __future__ import absolute_import, print_function
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import mock
import pytest

from reana_commons.config import SHARED_VOLUME_PATH

import reana_db.utils as utils
from reana_db import database
from reana_db import config as db_config
from reana_db.models import (
    InteractiveSession,
    User,
    UserResource,
    UserToken,
    UserTokenStatus,
    UserTokenType,
    Workflow,
)
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

    Driving from ``UserResource`` still includes JWT-only and legacy accounts
    (they hold a quota row but no ``UserToken``) while avoiding a full ``user_``
    table scan and a per-account quota lookup.
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
    """Key rotation covers legacy tokens and newer encrypted secrets."""
    old_key = f"old-{uuid4()}"
    new_key = db_config.DB_SECRET_KEY
    token_value = f"token-{uuid4()}"
    webhook_value = f"webhook-{uuid4()}"
    session_value = f"session-{uuid4()}"

    try:
        # The package-scoped test database retains rows created by earlier
        # tests. Key rotation assumes one current key across the database, so
        # isolate the encrypted columns before creating old-key fixtures.
        session.query(InteractiveSession).delete(synchronize_session=False)
        session.query(UserToken).delete(synchronize_session=False)
        session.query(User).update(
            {"gitlab_webhook_secret": None}, synchronize_session=False
        )
        session.commit()
        db_config.DB_SECRET_KEY = old_key
        user = User(
            email=f"{uuid4()}@reana.io",
            gitlab_webhook_secret=webhook_value,
        )
        session.add(user)
        session.flush()
        user_token = UserToken(
            token=token_value,
            status=UserTokenStatus.active,
            type_=UserTokenType.reana,
            user_id=user.id_,
        )
        interactive_session = InteractiveSession(
            name=f"session-{uuid4()}",
            path=f"/sessions/{uuid4()}",
            owner_id=user.id_,
            session_secret=session_value,
        )
        session.add_all([user_token, interactive_session])
        session.commit()
        ids = (user.id_, user_token.id_, interactive_session.id_)
        session.expunge_all()

        db_config.DB_SECRET_KEY = new_key
        change_key_encrypted_columns(old_key)
        session.expunge_all()

        assert session.query(User).filter_by(
            id_=ids[0]
        ).one().gitlab_webhook_secret == (webhook_value)
        assert session.query(UserToken).filter_by(id_=ids[1]).one().token == token_value
        assert (
            session.query(InteractiveSession).filter_by(id_=ids[2]).one().session_secret
            == session_value
        )
    finally:
        db_config.DB_SECRET_KEY = new_key


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
