# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Database-coupled pytest fixtures for REANA-DB."""

from __future__ import absolute_import, print_function

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema
from sqlalchemy_utils import create_database, database_exists

# Imports of reana_db.database and reana_db.models are deferred into the
# individual fixture bodies below. This is a coverage-measurement concern,
# not a correctness one: pytest-cov starts measuring on pytest_configure,
# after pytest11 plugins have been auto-loaded, so module-level imports
# performed by this plugin would be missed and the projects' coverage
# baselines would drop without any test changes. Keep them lazy so the
# class definitions in models.py execute under coverage.
from reana_db.utils import build_workspace_path


@pytest.fixture()
def session():
    """Create a SQL Alchemy session.

    Scope: function

    This fixture offers a SQLAlchemy session which has been created from the
    ``db_engine`` fixture.

    .. code-block:: python

        from reana_db.models import Workflow

        def test_create_workflow(session):
            workflow = Workflow(...)
            session.add(workflow)
            session.commit()
    """
    from reana_db.database import Session

    yield Session
    Session.close()


@pytest.fixture()
def app(base_app):
    """Flask application fixture.

    Scope: function

    This fixture offers a Flask application with already a database connection
    and all the models created. When finished it will delete all models.

    .. code-block:: python

        def create_ninja_turtle()
            with app.test_client() as client:
                somedata = 'ninja turtle'
                res = client.post(url_for('api.create_object'),
                                  content_type='application/json',
                                  data=json.dumps(somedata))

                assert res.status_code == 200

    """
    from reana_db.database import Session
    from reana_db.models import Base, Resource

    engine = create_engine(base_app.config["SQLALCHEMY_DATABASE_URI"])
    base_app.session.bind = engine
    with base_app.app_context():
        with engine.begin() as connection:
            if not engine.dialect.has_schema(connection, "__reana"):
                connection.execute(CreateSchema("__reana"))
        if not database_exists(engine.url):
            create_database(engine.url)
        Base.metadata.create_all(bind=engine)
        Resource.initialise_default_resources()
        yield base_app
        Session.close()  # close hanging connections
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def user0(app, session):
    """Create admin user.

    Scope: function

    This fixture creates an admin user with a default UUID
    ``00000000-0000-0000-0000-000000000000`` and ``email`` `user0@reana.io`,
    and returns it.
    """
    from reana_db.models import User

    user0_id = "00000000-0000-0000-0000-000000000000"
    user = session.query(User).filter_by(id_=user0_id).first()
    if not user:
        with patch("reana_db.database.Session", new=session):
            user = User(id_=user0_id, email="user0@reana.io")
        session.add(user)
        session.commit()
    return user


@pytest.fixture()
def user1(app, session):
    """Create first regular user.

    Scope: function

    This fixture creates a user with UUID
    ``11111111-1111-1111-1111-111111111111`` and ``email`` `user1@reana.io`,
    and returns it.
    """
    from reana_db.models import User

    user1_id = "11111111-1111-1111-1111-111111111111"
    user = session.query(User).filter_by(id_=user1_id).first()
    if not user:
        with patch("reana_db.database.Session", new=session):
            user = User(id_=user1_id, email="user1@reana.io")
        session.add(user)
        session.commit()
    return user


@pytest.fixture()
def user2(app, session):
    """Create second regular user.

    Scope: function

    This fixture creates a user with UUID
    ``22222222-2222-2222-2222-222222222222`` and ``email`` `user2@reana.io`,
    and returns it.
    """
    from reana_db.models import User

    user2_id = "22222222-2222-2222-2222-222222222222"
    user = session.query(User).filter_by(id_=user2_id).first()
    if not user:
        with patch("reana_db.database.Session", new=session):
            user = User(id_=user2_id, email="user2@reana.io")
        session.add(user)
        session.commit()
    return user


@pytest.fixture()
def sample_yadage_workflow_in_db(
    app,
    user0,
    session,
    yadage_workflow_with_name,
    sample_workflow_workspace,
    tmp_shared_volume_path,
):
    """Create a sample workflow in the database.

    Scope: function

    Adds a sample yadage workflow in the DB.
    """
    from reana_db.models import UserWorkflow, Workflow

    workflow_id = uuid4()
    relative_workspace_path = build_workspace_path(
        user0.id_, workflow_id, tmp_shared_volume_path
    )
    next(sample_workflow_workspace(relative_workspace_path))
    workflow = Workflow(
        id_=workflow_id,
        name="sample_yadage_workflow_1",
        owner_id=user0.id_,
        reana_specification=yadage_workflow_with_name["reana_specification"],
        operational_options={},
        type_=yadage_workflow_with_name["reana_specification"]["workflow"]["type"],
        logs="",
        workspace_path=relative_workspace_path,
    )
    session.add(workflow)
    session.commit()
    yield workflow
    for job in workflow.jobs:
        session.delete(job)
    for resource in workflow.resources:
        session.delete(resource)
    for user_workflow in session.query(UserWorkflow).filter_by(
        workflow_id=workflow.id_
    ):
        session.delete(user_workflow)
    session.delete(workflow)
    session.commit()


@pytest.fixture()
def sample_yadage_workflow_in_db_owned_by_user1(
    app,
    user1,
    session,
    yadage_workflow_with_name,
    sample_workflow_workspace,
    tmp_shared_volume_path,
):
    """Create a sample workflow in the database.

    Scope: function

    Adds a sample yadage workflow in the DB.
    """
    from reana_db.models import UserWorkflow, Workflow

    workflow_id = uuid4()
    relative_workspace_path = build_workspace_path(
        user1.id_, workflow_id, tmp_shared_volume_path
    )
    next(sample_workflow_workspace(relative_workspace_path))
    workflow = Workflow(
        id_=workflow_id,
        name="sample_yadage_workflow_2",
        owner_id=user1.id_,
        reana_specification=yadage_workflow_with_name["reana_specification"],
        operational_options={},
        type_=yadage_workflow_with_name["reana_specification"]["workflow"]["type"],
        logs="",
        workspace_path=relative_workspace_path,
    )
    session.add(workflow)
    session.commit()
    yield workflow
    for job in workflow.jobs:
        session.delete(job)
    for resource in workflow.resources:
        session.delete(resource)
    for user_workflow in session.query(UserWorkflow).filter_by(
        workflow_id=workflow.id_
    ):
        session.delete(user_workflow)
    session.delete(workflow)
    session.commit()


@pytest.fixture()
def sample_serial_workflow_in_db(
    app,
    user0,
    session,
    serial_workflow,
    sample_workflow_workspace,
    tmp_shared_volume_path,
):
    """Create a sample workflow in the database.

    Scope: function

    Adds a sample serial workflow in the DB.
    """
    from reana_db.models import UserWorkflow, Workflow

    workflow_id = uuid4()
    relative_workspace_path = build_workspace_path(
        user0.id_, workflow_id, tmp_shared_volume_path
    )
    next(sample_workflow_workspace(relative_workspace_path))
    workflow = Workflow(
        id_=workflow_id,
        name="sample_serial_workflow_1",
        owner_id=user0.id_,
        reana_specification=serial_workflow["reana_specification"],
        operational_options={},
        type_=serial_workflow["reana_specification"]["workflow"]["type"],
        logs="",
        workspace_path=relative_workspace_path,
    )
    session.add(workflow)
    session.commit()
    yield workflow
    for job in workflow.jobs:
        session.delete(job)
    for resource in workflow.resources:
        session.delete(resource)
    for user_workflow in session.query(UserWorkflow).filter_by(
        workflow_id=workflow.id_
    ):
        session.delete(user_workflow)
    session.delete(workflow)
    session.commit()


@pytest.fixture()
def sample_serial_workflow_in_db_owned_by_user1(
    app,
    user1,
    session,
    serial_workflow,
    sample_workflow_workspace,
    tmp_shared_volume_path,
):
    """Create a sample workflow in the database.

    Scope: function

    Adds a sample serial workflow in the DB.
    """
    from reana_db.models import UserWorkflow, Workflow

    workflow_id = uuid4()
    relative_workspace_path = build_workspace_path(
        user1.id_, workflow_id, tmp_shared_volume_path
    )
    next(sample_workflow_workspace(relative_workspace_path))
    workflow = Workflow(
        id_=workflow_id,
        name="sample_serial_workflow_2",
        owner_id=user1.id_,
        reana_specification=serial_workflow["reana_specification"],
        operational_options={},
        type_=serial_workflow["reana_specification"]["workflow"]["type"],
        logs="",
        workspace_path=relative_workspace_path,
    )
    session.add(workflow)
    session.commit()
    yield workflow
    for job in workflow.jobs:
        session.delete(job)
    for resource in workflow.resources:
        session.delete(resource)
    for user_workflow in session.query(UserWorkflow).filter_by(
        workflow_id=workflow.id_
    ):
        session.delete(user_workflow)
    session.delete(workflow)
    session.commit()
