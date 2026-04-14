# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB config tests."""

import importlib

import reana_db.config as config


def test_periodic_quota_config_is_loaded_from_environment(monkeypatch):
    """Test periodic quota defaults are parsed from environment variables."""
    with monkeypatch.context() as context:
        context.setenv("REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED", "true")
        context.setenv("REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS", "6")
        context.setenv("REANA_PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY", "true")

        reloaded_config = importlib.reload(config)

        assert reloaded_config.DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED is True
        assert reloaded_config.DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS == 6
        assert bool(reloaded_config.PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY) is True
        assert (
            reloaded_config._get_optional_int_env(
                "REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS"
            )
            == 6
        )

    importlib.reload(config)


def test_periodic_quota_config_uses_none_for_empty_months(monkeypatch):
    """Test empty periodic quota month configuration is treated as missing."""
    with monkeypatch.context() as context:
        context.delenv("REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED", raising=False)
        context.setenv("REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS", "")
        context.setenv("REANA_PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY", "false")

        reloaded_config = importlib.reload(config)

        assert reloaded_config.DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED is False
        assert reloaded_config.DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS is None
        assert bool(reloaded_config.PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY) is False
        assert (
            reloaded_config._get_optional_int_env(
                "REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS"
            )
            is None
        )

    importlib.reload(config)
