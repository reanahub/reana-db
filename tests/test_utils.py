# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022 CERN.
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
from reana_db.models import Workflow
from reana_db.utils import (
    _advance_user_cpu_quota_period_if_needed,
    _get_accounted_workflow_cpu_milliseconds,
    _get_current_user_cpu_quota_period_start_at,
    _get_workflow_with_uuid_or_name,
    get_current_quota_period_start_at_from_anchor,
    split_run_number,
    update_users_cpu_quota,
    update_workflow_cpu_quota,
    update_workflows_cpu_quota,
    update_workflows_disk_quota,
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
    "anchor_at, quota_period_months, now, expected",
    [
        (None, 3, datetime(2026, 4, 14, 0, 0, 0), None),
        (
            datetime(2026, 1, 15, 12, 0, 0),
            3,
            datetime(2026, 5, 20, 0, 0, 0),
            datetime(2026, 4, 15, 12, 0, 0),
        ),
    ],
)
def test_get_current_quota_period_start_at_from_anchor(
    anchor_at, quota_period_months, now, expected
):
    """Test deriving the active quota period from an anchor timestamp."""
    assert (
        get_current_quota_period_start_at_from_anchor(
            anchor_at, quota_period_months, now=now
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
    user_resource_query = mock.MagicMock()
    user_resource_query.filter_by.return_value.first.return_value = None
    session.query.return_value = user_resource_query
    timer = mock.MagicMock()
    user = SimpleNamespace(id_="user-1")

    monkeypatch.setattr(database, "Session", session)
    monkeypatch.setattr(utils, "should_skip_quota_update", mock.Mock(return_value=True))
    monkeypatch.setattr(
        utils,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(utils, "Timer", mock.Mock(return_value=timer))

    assert update_users_cpu_quota(user=user) is None
    update_users_cpu_quota(user=user, override_policy_checks=True)

    user_resource_query.filter_by.assert_called_once_with(
        user_id="user-1", resource_id="cpu"
    )
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
