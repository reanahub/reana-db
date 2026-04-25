# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB database tests."""

import importlib

import mock


def test_engine_dispose_registered_at_exit():
    """Test that engine.dispose is registered to run at process exit.

    This verifies that when any process using reana-db exits (CronJob containers,
    long-running services), SQLAlchemy sends proper TCP FIN messages to PostgreSQL
    rather than abandoning connections, which would cause 'unexpected EOF' log noise.
    """
    with mock.patch("atexit.register") as mock_register:
        import reana_db.database as db_module

        importlib.reload(db_module)
        mock_register.assert_any_call(db_module.engine.dispose)
