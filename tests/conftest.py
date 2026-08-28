# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020, 2021, 2022, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-DB."""

from datetime import datetime, timedelta
from uuid import uuid4

import mock
import pytest

from reana_db.models import Resource, RunStatus, User, Workflow


@pytest.fixture(scope="package")
def db():
    """Initialize database fixture."""
    from reana_db.database import init_db

    init_db()
    Resource.initialise_default_resources()


@pytest.fixture
def new_user(session, db):
    """Create new user."""
    user = User(email="{}@reana.io".format(uuid4()))
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def run_workflow(session, new_user):
    """Mock workflow run factory."""

    def _run_workflow(time_elapsed_seconds=0.5, finish=True):
        """Mock a workflow run."""
        id_ = uuid4()
        workflow = Workflow(
            id_=str(id_),
            name="test_{}".format(id_),
            owner_id=new_user.id_,
            reana_specification=[],
            type_="serial",
            logs="",
            status=RunStatus.created,
        )
        # start workflow
        workflow.status = RunStatus.running
        session.add(workflow)
        session.commit()
        termination_value = datetime.now() + timedelta(seconds=time_elapsed_seconds)

        class MockDatetime(datetime):
            @classmethod
            def now(cls):
                return termination_value

        if finish:
            with mock.patch("reana_db.models.datetime", MockDatetime):
                Workflow.update_workflow_status(
                    session, workflow.id_, RunStatus.finished
                )
        return workflow

    return _run_workflow
