# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB CLI tests."""

from datetime import datetime
from types import SimpleNamespace

import mock
from click.testing import CliRunner

import reana_db.cli as cli_module
from reana_db import database


def test_resource_usage_update_passes_override_policy_checks(monkeypatch):
    """Test the manual quota refresh command overrides policy gates."""
    update_workflows_disk_quota = mock.Mock()
    update_users_disk_quota = mock.Mock()
    update_workflows_cpu_quota = mock.Mock()
    update_users_cpu_quota = mock.Mock()

    monkeypatch.setattr(
        cli_module, "update_workflows_disk_quota", update_workflows_disk_quota
    )
    monkeypatch.setattr(cli_module, "update_users_disk_quota", update_users_disk_quota)
    monkeypatch.setattr(
        cli_module, "update_workflows_cpu_quota", update_workflows_cpu_quota
    )
    monkeypatch.setattr(cli_module, "update_users_cpu_quota", update_users_cpu_quota)

    result = CliRunner().invoke(cli_module.cli, ["quota", "resource-usage-update"])

    assert result.exit_code == 0
    assert "Disk quota usage updated successfully" in result.output
    assert "CPU quota usage updated successfully" in result.output
    update_workflows_disk_quota.assert_called_once_with(override_policy_checks=True)
    update_users_disk_quota.assert_called_once_with(override_policy_checks=True)
    update_workflows_cpu_quota.assert_called_once_with(override_policy_checks=True)
    update_users_cpu_quota.assert_called_once_with(override_policy_checks=True)


def test_resource_usage_update_exits_on_error(monkeypatch):
    """Test the manual quota refresh command aborts on updater failures."""
    update_workflows_cpu_quota = mock.Mock()

    monkeypatch.setattr(
        cli_module,
        "update_workflows_disk_quota",
        mock.Mock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(cli_module, "update_users_disk_quota", mock.Mock())
    monkeypatch.setattr(
        cli_module, "update_workflows_cpu_quota", update_workflows_cpu_quota
    )
    monkeypatch.setattr(cli_module, "update_users_cpu_quota", mock.Mock())

    result = CliRunner().invoke(cli_module.cli, ["quota", "resource-usage-update"])

    assert result.exit_code == 1
    assert "An error occurred when updating users disk quota usage" in result.output
    update_workflows_cpu_quota.assert_not_called()


def test_init_periodic_defaults_warns_if_not_configured(monkeypatch):
    """Test the backfill command exits early if defaults are not configured."""
    monkeypatch.setattr(cli_module, "DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED", False)
    monkeypatch.setattr(cli_module, "DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS", None)

    result = CliRunner().invoke(cli_module.cli, ["quota", "init-periodic-defaults"])

    assert result.exit_code == 0
    assert "Periodic CPU reset deployment defaults are not configured." in result.output


def test_init_periodic_defaults_backfills_from_user_created(monkeypatch):
    """Test periodic default backfill derives the active window from user creation."""
    created_at = datetime(2026, 4, 1, 13, 6, 32, 992595)
    user_resource = SimpleNamespace(
        user=SimpleNamespace(created=created_at),
        quota_period_months=None,
        quota_period_start_at=None,
    )
    query = mock.MagicMock()
    query.filter.return_value = query
    query.all.return_value = [user_resource]
    session = mock.MagicMock()
    session.query.return_value = query

    monkeypatch.setattr(cli_module, "DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED", True)
    monkeypatch.setattr(cli_module, "DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS", 3)
    monkeypatch.setattr(
        cli_module,
        "get_default_quota_resource",
        mock.Mock(return_value=SimpleNamespace(id_="cpu")),
    )
    monkeypatch.setattr(
        cli_module,
        "get_current_quota_period_start_at_from_anchor",
        mock.Mock(return_value=datetime(2026, 4, 1, 13, 6, 32, 992595)),
    )
    monkeypatch.setattr(database, "Session", session)

    result = CliRunner().invoke(cli_module.cli, ["quota", "init-periodic-defaults"])

    assert result.exit_code == 0
    assert (
        "Initialised periodic CPU reset policy for 1 existing users." in result.output
    )
    assert user_resource.quota_period_months == 3
    assert user_resource.quota_period_start_at == datetime(
        2026, 4, 1, 13, 6, 32, 992595
    )
    session.commit.assert_called_once()
