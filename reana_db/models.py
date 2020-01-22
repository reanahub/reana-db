# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Models for REANA Components."""

from __future__ import absolute_import

import enum
import uuid

from sqlalchemy import (Boolean, Column, DateTime, Enum, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy_utils import JSONType, UUIDType
from sqlalchemy_utils.models import Timestamp

from reana_db.utils import build_workspace_path

Base = declarative_base()


def generate_uuid():
    """Generate new uuid."""
    return str(uuid.uuid4())


class User(Base, Timestamp):
    """User table."""

    __tablename__ = 'user_'

    id_ = Column(UUIDType, primary_key=True, unique=True,
                 default=generate_uuid)
    access_token = Column(String(length=255))
    email = Column(String(length=255), unique=True, primary_key=True)
    full_name = Column(String(length=255))
    username = Column(String(length=255))
    workflows = relationship("Workflow", backref="user_")

    def __repr__(self):
        """User string represetantion."""
        return '<User %r>' % self.id_

    def get_user_workspace(self):
        """Build user's workspace directory path.

        :return: Path to the user's workspace directory.
        """
        return build_workspace_path(self.id_)


class WorkflowStatus(enum.Enum):
    """Enumeration of possible workflow statuses."""

    created = 0
    running = 1
    finished = 2
    failed = 3
    deleted = 4
    stopped = 5
    queued = 6


class JobStatus(enum.Enum):
    """Enumeration of possible job statuses."""

    created = 0
    running = 1
    finished = 2
    failed = 3
    stopped = 4
    queued = 5


class Workflow(Base, Timestamp):
    """Workflow table."""

    __tablename__ = 'workflow'

    id_ = Column(UUIDType, primary_key=True)
    name = Column(String(255))
    status = Column(Enum(WorkflowStatus), default=WorkflowStatus.created)
    owner_id = Column(UUIDType, ForeignKey('user_.id_'))
    reana_specification = Column(JSONType)
    input_parameters = Column(JSONType)
    operational_options = Column(JSONType)
    type_ = Column(String(30))
    interactive_session = Column(Text)
    interactive_session_name = Column(Text)
    interactive_session_type = Column(Text)
    logs = Column(String)
    run_started_at = Column(DateTime)
    run_finished_at = Column(DateTime)
    run_stopped_at = Column(DateTime)
    run_number = Column(Integer)
    job_progress = Column(JSONType, default=dict)
    restart = Column(Boolean, default=False)
    restart_info = Column(JSONType, default=list)
    # job_progress = {
    #  jobs_total = {total: job_number}
    #  jobs_running = {job_ids: [], total: c}
    #  jobs_finished = {job_ids: [], total: c}
    #  jobs_failed = {job_ids: [], total: c}}
    engine_specific = Column(JSONType)
    git_ref = Column(String(40))
    git_repo = Column(String(255))
    git_provider = Column(String(255))

    __table_args__ = UniqueConstraint('name', 'owner_id', 'run_number',
                                      name='_user_workflow_run_uc'),

    def __init__(self,
                 id_,
                 name,
                 owner_id,
                 reana_specification,
                 type_,
                 logs='',
                 interactive_session=None,
                 interactive_session_name=None,
                 interactive_session_type=None,
                 input_parameters={},
                 operational_options={},
                 status=WorkflowStatus.created,
                 git_ref='',
                 git_repo=None,
                 git_provider=None):
        """Initialize workflow model."""
        self.id_ = id_
        self.name = name
        self.status = status
        self.owner_id = owner_id
        self.reana_specification = reana_specification
        self.input_parameters = input_parameters
        self.operational_options = operational_options
        self.type_ = type_
        self.logs = logs or ''
        self.interactive_session = interactive_session
        self.interactive_session_name = interactive_session_name
        self.interactive_session_type = interactive_session_type
        self.git_ref = git_ref
        self.git_repo = git_repo
        self.git_provider = git_provider
        from .database import Session
        last_workflow = Session.query(Workflow).filter_by(
            name=name,
            owner_id=owner_id).\
            order_by(Workflow.run_number.desc()).first()
        if not last_workflow:
            self.run_number = 1
        else:
            self.run_number = last_workflow.run_number + 1

    def __repr__(self):
        """Workflow string represetantion."""
        return '<Workflow %r>' % self.id_

    def get_workspace(self):
        """Build workflow directory path.

        :return: Path to the workflow workspace directory.
        """
        return build_workspace_path(self.owner_id, self.id_)

    def get_input_parameters(self):
        """Return workflow parameters."""
        return self.reana_specification.get('inputs', {}).get('parameters', {})

    def get_specification(self):
        """Return workflow specification."""
        return self.reana_specification['workflow'].get('specification', {})

    def get_owner_access_token(self):
        """Return workflow owner access token."""
        from .database import Session
        db_session = Session.object_session(self)
        owner = db_session.query(User).filter_by(
            id_=self.owner_id).first()
        return owner.access_token

    def get_full_workflow_name(self):
        """Return full workflow name including run number."""
        return "{}.{}".format(self.name, self.run_number)

    @staticmethod
    def update_workflow_status(db_session, workflow_uuid, status,
                               new_logs='', message=None):
        """Update database workflow status.

        :param workflow_uuid: UUID which represents the workflow.
        :param status: String that represents the workflow status.
        :param new_logs: New logs from workflow execution.
        :param message: Unused.
        """
        try:
            workflow = \
                db_session.query(Workflow).filter_by(id_=workflow_uuid).first()

            if not workflow:
                raise Exception('Workflow {0} doesn\'t exist in database.'.
                                format(workflow_uuid))
            if status:
                workflow.status = status
            if new_logs:
                workflow.logs = (workflow.logs or '') + new_logs + '\n'
            db_session.commit()
        except Exception as e:
            raise e


class Job(Base, Timestamp):
    """Job table."""

    __tablename__ = 'job'

    id_ = Column(UUIDType, unique=True, primary_key=True,
                 default=generate_uuid)
    backend_job_id = Column(String(256))
    workflow_uuid = Column(UUIDType)
    status = Column(Enum(JobStatus), default=JobStatus.created)
    compute_backend = Column(String(30))
    cvmfs_mounts = Column(Text)
    shared_file_system = Column(Boolean)
    docker_img = Column(String(256))
    cmd = Column(JSONType)
    env_vars = Column(JSONType)
    deleted = Column(Boolean)
    logs = Column(String, nullable=True)
    prettified_cmd = Column(JSONType)
    job_name = Column(Text)


class JobCache(Base, Timestamp):
    """Job Cache table."""

    __tablename__ = 'job_cache'

    id_ = Column(UUIDType, unique=True, primary_key=True,
                 default=generate_uuid)
    job_id = Column(UUIDType, ForeignKey('job.id_'), primary_key=True)
    parameters = Column(String(1024))
    result_path = Column(String(1024))
    workspace_hash = Column(String(1024))
    access_times = Column(JSONType)
