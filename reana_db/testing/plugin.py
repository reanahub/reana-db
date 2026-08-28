# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest plugin entry point for REANA-DB fixtures.

Only the database-coupled fixtures live here. Pure-Python and
REANA-Commons-coupled fixtures (workflow spec dicts, queue helpers,
workspace fixtures) are provided by ``reana_commons.testing.plugin``,
which pytest auto-loads independently because ``reana-db[tests]``
declares ``reana-commons[tests]`` as a dependency.
"""

from __future__ import absolute_import, print_function

import os

from .fixtures import (  # noqa: F401
    app,
    sample_serial_workflow_in_db,
    sample_serial_workflow_in_db_owned_by_user1,
    sample_yadage_workflow_in_db,
    sample_yadage_workflow_in_db_owned_by_user1,
    session,
    user0,
    user1,
    user2,
)


def pytest_configure(config):
    """Give tests a stable, explicit encryption key if none is configured.

    ``reana_db.config.DB_SECRET_KEY`` has no default (see its docstring) so
    that a real deployment fails loudly instead of silently encrypting
    under a guessable key. Test suites across reana-db, reana-server, and
    reana-workflow-controller (all of which load this shared plugin) don't
    set ``REANA_SECRET_KEY`` explicitly and would otherwise hit that same
    failure on the first encrypted-column read/write.

    Set the *environment variable* itself, not just the resulting module
    attribute: ``reana_db/tests/test_config.py`` legitimately exercises
    ``importlib.reload(reana_db.config)`` to test other env-driven settings,
    which re-executes ``DB_SECRET_KEY = os.getenv("REANA_SECRET_KEY")`` and
    would silently reset a direct attribute patch back to ``None`` the
    moment that test runs. ``os.environ.setdefault`` keeps this reload-safe
    for the rest of the session while still doing nothing when a real key
    is already configured.
    """
    os.environ.setdefault("REANA_SECRET_KEY", "pytest-only-not-a-real-secret")

    import reana_db.config as db_config

    if not db_config.DB_SECRET_KEY:
        db_config.DB_SECRET_KEY = os.environ["REANA_SECRET_KEY"]
