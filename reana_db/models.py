# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Models for REANA Components."""

from __future__ import absolute_import

import enum
import math
import logging
import uuid
from datetime import datetime
from functools import reduce
from typing import Dict, List, Tuple

from reana_commons.config import (
    MQ_MAX_PRIORITY,
    REANA_MAX_CONCURRENT_BATCH_WORKFLOWS,
    REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES,
    WORKFLOW_TIME_FORMAT,
)
from reana_commons.errors import REANAValidationError
from reana_commons.utils import get_disk_usage
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    or_,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy_utils import EncryptedType, JSONType, UUIDType
from sqlalchemy_utils.models import Timestamp
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine
from sqlalchemy.dialects.postgresql import ARRAY

from reana_db.config import (
    DB_SECRET_KEY,
    DEFAULT_QUOTA_LIMITS,
    DEFAULT_QUOTA_RESOURCES,
    WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY,
)
from reana_db.utils import (
    build_workspace_path,
    store_workflow_disk_quota,
    split_run_number,
    update_users_cpu_quota,
    update_users_disk_quota,
    update_workflow_cpu_quota,
    update_workspace_retention_rules,
)


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Constraint naming convention."""

metadata_obj = MetaData(naming_convention=convention)

Base = declarative_base(metadata=metadata_obj)


def generate_uuid():
    """Generate new uuid."""
    return str(uuid.uuid4())


class QuotaBase:
    """Quota base functionality."""

    def _get_quota_by_type(self, resource_type):
        """Aggregate quota usage by resource type."""

        def _get_health_status(usage, limit):
            """Calculate quota health status."""
            health = QuotaHealth.healthy
            if limit:
                percentage = usage / limit * 100
                if percentage >= 80:
                    if percentage >= 100:
                        health = QuotaHealth.critical
                    else:
                        health = QuotaHealth.warning
            return health.name

        quota_usage = 0
        quota_limit = 0
        unit = None

        for resource in self.resources:
            if resource.resource.type_ == resource_type:
                # make sure that all resources of the same type use the same units
                if unit and unit != resource.resource.unit:
                    raise Exception(
                        "Error while calculating quota usage. Not all "
                        "resources of resource type {} use "
                        "the same units.".format(resource_type)
                    )
                unit = resource.resource.unit
                quota_usage += resource.quota_used
                if hasattr(resource, "quota_limit"):
                    quota_limit += resource.quota_limit

        usage_dict = {
            "usage": {
                "raw": quota_usage,
                "human_readable": ResourceUnit.human_readable_unit(unit, quota_usage),
            }
        }
        if quota_limit:
            usage_dict["limit"] = {
                "raw": quota_limit,
                "human_readable": ResourceUnit.human_readable_unit(unit, quota_limit),
            }
            usage_dict["health"] = _get_health_status(quota_usage, quota_limit)

        return usage_dict

    def get_quota_usage(self):
        """Get quota usage information."""
        used_resource_types = set(res.resource.type_ for res in self.resources)
        return {
            resource_type.name: self._get_quota_by_type(resource_type)
            for resource_type in used_resource_types
        }


class User(Base, Timestamp, QuotaBase):
    """User table."""

    __tablename__ = "user_"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, unique=True, default=generate_uuid)
    email = Column(String(length=255), unique=True, primary_key=True)
    full_name = Column(String(length=255))
    username = Column(String(length=255))
    tokens = relationship("UserToken", backref="user_", lazy="dynamic")
    workflows = relationship("Workflow", backref="owner", lazy="dynamic")
    audit_logs = relationship("AuditLog", backref="user_")

    def __init__(self, access_token=None, **kwargs):
        """Initialize user model."""
        for k, v in kwargs.items():
            setattr(self, k, v)
        if access_token:
            self.access_token = access_token
        self.initialize_user_quota_limits()

    @hybrid_property
    def active_token(self):
        """REANA active access token object."""
        return self.tokens.filter_by(
            status=UserTokenStatus.active, type_=UserTokenType.reana
        ).one_or_none()

    @hybrid_property
    def access_token(self):
        """REANA active access token value."""
        return self.active_token.token if self.active_token else None

    @access_token.setter
    def access_token(self, value):
        """REANA access token setter."""
        from .database import Session

        if self.tokens.count() and self.active_token:
            raise Exception("User {} has already an active access token.".format(self))
        if (
            self.tokens.count()
            and self.access_token_status == UserTokenStatus.requested.name
        ):
            self.latest_access_token.status = UserTokenStatus.active
            self.latest_access_token.token = value
        else:
            user_token = UserToken(
                user_=self,
                token=value,
                status=UserTokenStatus.active,
                type_=UserTokenType.reana,
            )
            Session.add(user_token)

    @hybrid_property
    def latest_access_token(self):
        """REANA most recent access token."""
        latest_reana_token = (
            self.tokens.filter_by(type_=UserTokenType.reana).order_by(
                UserToken.created.desc()
            )
        ).first()
        return latest_reana_token or None

    @hybrid_property
    def access_token_status(self):
        """REANA most recent access token status."""
        return (
            self.latest_access_token.status.name if self.latest_access_token else None
        )

    def get_user_workspace(self):
        """Build user's workspace directory path.

        :return: Path to the user's workspace directory.
        """
        return build_workspace_path(self.id_)

    def request_access_token(self):
        """Create user token and mark it as requested."""
        from .database import Session

        if self.tokens.count() and self.active_token:
            raise Exception("User {} has already an active access token.".format(self))
        if (
            self.tokens.count()
            and self.access_token_status == UserTokenStatus.requested.name
        ):
            raise Exception(
                "User {} has already requested an access" " token.".format(self)
            )
        user_token = UserToken(
            user_=self,
            token=None,
            status=UserTokenStatus.requested,
            type_=UserTokenType.reana,
        )
        Session.add(user_token)
        Session.commit()

    def log_action(self, action, details=None):
        """Create audit log entry for the user.

        :param action: Type of action.
        :type action: AuditLogAction
        :param details: JSON field containing action details.
        """
        from .database import Session

        audit_log = AuditLog(user_id=self.id_, action=action, details=details)
        Session.add(audit_log)
        Session.commit()
        return audit_log

    def initialize_user_quota_limits(self):
        """Initialize user quota limits."""
        resources = Resource.query.all()
        for resource in resources:
            self.resources.append(
                UserResource(
                    user_id=self.id_,
                    resource_id=resource.id_,
                    quota_limit=DEFAULT_QUOTA_LIMITS[resource.type_.name],
                    quota_used=0,
                )
            )

    def has_exceeded_quota(self):
        """Get whether user has exceeded the quota of any resource."""
        return any(
            r.quota_limit != 0 and r.quota_used >= r.quota_limit for r in self.resources
        )

    def get_workflow_overload_priority(self):
        """Get priority factor based on the number of current workflows ``running``."""
        max_concurrent_workflows = REANA_MAX_CONCURRENT_BATCH_WORKFLOWS
        running_count = self.workflows.filter(
            or_(
                Workflow.status == RunStatus.pending,
                Workflow.status == RunStatus.running,
            )
        ).count()
        if running_count >= max_concurrent_workflows:
            return 0.1
        # we reduce the 10% (* 0.9) to avoid getting a 0 multiplier factor when
        # `running_count == `max_concurrent_workflows`, thus taking into
        # account workflow complexity when workflows are requeued.
        priority = round(1 - (running_count * 0.9) / max_concurrent_workflows, 2)
        return priority

    def __repr__(self):
        """User string representation."""
        return "<User %r>" % self.id_


class UserTokenStatus(enum.Enum):
    """Enumeration of possible user token statuses."""

    requested = 0
    active = 1
    revoked = 2


class UserTokenType(enum.Enum):
    """Enumeration of possible user token types."""

    reana = 0


class UserToken(Base, Timestamp):
    """User tokens table."""

    __tablename__ = "user_token"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    token = Column(
        EncryptedType(String(length=255), DB_SECRET_KEY, AesEngine, "pkcs5"),
        unique=True,
    )
    status = Column(Enum(UserTokenStatus))
    user_id = Column(UUIDType, ForeignKey("__reana.user_.id_"), nullable=False)
    type_ = Column(Enum(UserTokenType), nullable=False)


class CleanUpDependingOnStatusMixin:
    """Mixin to determine whether to clean up jobs for REANA status enums."""

    @classmethod
    def should_cleanup_job(cls, job_status):
        """Determine if a job/workflow should be cleaned up depending on its status."""
        job_status_name = (
            job_status.name if isinstance(job_status, enum.Enum) else job_status
        )
        keep_on_status_set = set(REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES)
        all_statuses_list = [s.name for s in cls]
        if not keep_on_status_set.issubset(all_statuses_list):
            logging.warning(
                "The configuration variable REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES contains "
                "unknown statuses {} which will be ignored, possibly causing jobs not to be cleaned up.".format(
                    keep_on_status_set.difference(all_statuses_list)
                )
            )
        return not (job_status_name in keep_on_status_set)


class RunStatus(CleanUpDependingOnStatusMixin, enum.Enum):
    """Enumeration of possible run statuses."""

    created = 0
    running = 1
    finished = 2
    failed = 3
    deleted = 4
    stopped = 5
    queued = 6
    pending = 7


ALLOWED_WORKFLOW_STATUS_TRANSITIONS = [
    # Created
    (RunStatus.created, RunStatus.deleted),
    (RunStatus.created, RunStatus.queued),
    # Queued
    (RunStatus.queued, RunStatus.deleted),
    (RunStatus.queued, RunStatus.pending),
    (RunStatus.queued, RunStatus.failed),
    # Pending
    (RunStatus.pending, RunStatus.running),
    (RunStatus.pending, RunStatus.deleted),
    # Running
    (RunStatus.running, RunStatus.failed),
    (RunStatus.running, RunStatus.finished),
    (RunStatus.running, RunStatus.stopped),
    (RunStatus.running, RunStatus.running),
    # Stopped
    (RunStatus.stopped, RunStatus.deleted),
    # Failed
    (RunStatus.failed, RunStatus.deleted),
    (RunStatus.failed, RunStatus.running),
    # Finished
    (RunStatus.finished, RunStatus.deleted),
    (RunStatus.finished, RunStatus.running),
]


class JobStatus(CleanUpDependingOnStatusMixin, enum.Enum):
    """Enumeration of possible job statuses."""

    created = 0
    running = 1
    finished = 2
    failed = 3
    stopped = 4
    queued = 5


class WorkflowSession(Base):
    """Workflow Session table."""

    __tablename__ = "workflow_session"
    __table_args__ = {"schema": "__reana"}

    workflow_id = Column(UUIDType, ForeignKey("__reana.workflow.id_"), nullable=True)
    session_id = Column(
        UUIDType, ForeignKey("__reana.interactive_session.id_"), primary_key=True
    )

    def __repr__(self):
        """Workflow Session string representation."""
        return "<WorkflowSession {} {}>".format(self.session_id, self.workflow_id)


class InteractiveSessionType(enum.Enum):
    """Enumeration of interactive session types."""

    jupyter = 0


class InteractiveSession(Base, Timestamp, QuotaBase):
    """Interactive Session table."""

    __tablename__ = "interactive_session"
    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    name = Column(String(255))
    path = Column(Text)  # path to access the interactive session
    status = Column(Enum(RunStatus), nullable=False, default=RunStatus.created)
    owner_id = Column(UUIDType, ForeignKey("__reana.user_.id_"))
    type_ = Column(
        Enum(InteractiveSessionType),
        nullable=False,
        default=InteractiveSessionType.jupyter,
    )

    __table_args__ = (
        UniqueConstraint("name", "path"),
        {"schema": "__reana"},
    )

    def __repr__(self):
        """Interactive Session string representation."""
        return "<InteractiveSession %r>" % self.name


class Workflow(Base, Timestamp, QuotaBase):
    """Workflow table."""

    __tablename__ = "workflow"

    id_ = Column(UUIDType, primary_key=True)
    name = Column(String(255))
    status = Column(Enum(RunStatus), default=RunStatus.created, index=True)
    owner_id = Column(UUIDType, ForeignKey("__reana.user_.id_"))
    reana_specification = Column(JSONType)
    input_parameters = Column(JSONType)
    operational_options = Column(JSONType)
    complexity = Column(ARRAY(BigInteger(), dimensions=2), default=[])
    type_ = Column(String(30))
    logs = Column(String)
    run_started_at = Column(DateTime)
    run_finished_at = Column(DateTime)
    run_stopped_at = Column(DateTime)
    run_number_major = Column(Integer)
    run_number_minor = Column(Integer, default=0)
    job_progress = Column(JSONType, default=dict)
    workspace_path = Column(String)
    restart = Column(Boolean, default=False)
    # job_progress = {
    #  jobs_total = {total: job_number}
    #  jobs_running = {job_ids: [], total: c}
    #  jobs_finished = {job_ids: [], total: c}
    #  jobs_failed = {job_ids: [], total: c}}
    engine_specific = Column(JSONType)
    git_ref = Column(String(40))
    git_repo = Column(String(255))
    git_provider = Column(String(255))
    launcher_url = Column(String)
    sessions = relationship(
        "InteractiveSession",
        secondary="__reana.workflow_session",
        lazy="dynamic",
        backref="workflow",
        cascade="all, delete",
    )
    retention_rules = relationship(
        "WorkspaceRetentionRule", backref="workflow", lazy="dynamic"
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "name",
            "run_number_major",
            "run_number_minor",
        ),
        {"schema": "__reana"},
    )

    def __init__(
        self,
        id_,
        name,
        owner_id,
        reana_specification,
        type_,
        logs="",
        input_parameters={},
        operational_options={},
        status=RunStatus.created,
        complexity=[],
        git_ref="",
        git_repo=None,
        git_provider=None,
        workspace_path=None,
        restart=False,
        run_number=None,
        launcher_url=None,
    ):
        """Initialize workflow model."""
        self.id_ = id_
        self.name = name
        self.status = status
        self.owner_id = owner_id
        self.reana_specification = reana_specification
        self.input_parameters = input_parameters
        self.operational_options = operational_options
        self.complexity = complexity
        self.type_ = type_
        self.logs = logs or ""
        self.git_ref = git_ref
        self.git_repo = git_repo
        self.git_provider = git_provider
        self.restart = restart
        self.run_number_major, self.run_number_minor = self.get_new_run_number(
            run_number
        )
        self.workspace_path = workspace_path or build_workspace_path(
            self.owner_id, self.id_
        )
        self.launcher_url = launcher_url

    def __repr__(self):
        """Workflow string representation."""
        return "<Workflow %r>" % self.id_

    @property
    def run_number(self) -> str:
        """Get workflow run number."""
        if self.run_number_minor != 0:
            return f"{self.run_number_major}.{self.run_number_minor}"
        return str(self.run_number_major)

    def _get_last_workflow(self, run_number):
        """Fetch the last workflow restart given a certain run number."""
        from .database import Session

        if run_number:
            run_number_major, run_number_minor = split_run_number(run_number)
            last_workflow = (
                Session.query(Workflow)
                .filter(
                    Workflow.name == self.name,
                    Workflow.run_number_major == run_number_major,
                    Workflow.owner_id == self.owner_id,
                )
                .order_by(
                    Workflow.run_number_major.desc(), Workflow.run_number_minor.desc()
                )
                .first()
            )
        else:
            last_workflow = (
                Session.query(Workflow)
                .filter_by(name=self.name, restart=False, owner_id=self.owner_id)
                .order_by(
                    Workflow.run_number_major.desc(), Workflow.run_number_minor.desc()
                )
                .first()
            )
        return last_workflow

    def get_new_run_number(self, run_number) -> Tuple[int, int]:
        """Return the major and minor run numbers for a new workflow.

        Return a tuple where the first element is the major run number and the
        second element is the minor run number.
        """
        last_workflow = self._get_last_workflow(run_number)

        if not last_workflow:
            if self.restart:
                raise REANAValidationError(
                    "Cannot restart a workflow that has not been run before."
                )
            return 1, 0  # First workflow run

        else:
            if not self.restart:
                run_number_major = last_workflow.run_number_major + 1
                run_number_minor = 0
            else:
                run_number_major = last_workflow.run_number_major
                run_number_minor = last_workflow.run_number_minor + 1

            return run_number_major, run_number_minor

    def get_input_parameters(self):
        """Return workflow parameters."""
        return self.reana_specification.get("inputs", {}).get("parameters", {})

    def get_specification(self):
        """Return workflow specification."""
        return self.reana_specification["workflow"].get("specification", {})

    def get_owner_access_token(self):
        """Return workflow owner access token."""
        from .database import Session

        db_session = Session.object_session(self)
        owner = db_session.query(User).filter_by(id_=self.owner_id).first()
        return owner.access_token

    def get_full_workflow_name(self):
        """Return full workflow name including run number."""
        return "{}.{}".format(self.name, self.run_number)

    def get_workspace_disk_usage(self, summarize=False, search=None):
        """Retrieve disk usage information of a workspace."""
        from functools import partial

        return get_disk_usage(
            self.workspace_path,
            summarize,
            search,
            to_human_readable_units=partial(
                ResourceUnit.human_readable_unit, ResourceUnit.bytes_
            ),
        )

    def set_workspace_retention_rules(self, rules: List[Dict[str, str]]):
        """Set workspace retention rules for the workflow."""
        from .database import Session

        for rule in rules:
            wr = WorkspaceRetentionRule(
                workflow_id=self.id_,
                workspace_files=rule["workspace_files"],
                retention_days=rule["retention_days"],
            )
            Session.add(wr)
        Session.commit()

    def activate_workspace_retention_rules(self):
        """Activate workspace retention rules for the workflow."""
        rules = WorkspaceRetentionRule.query.filter_by(
            workflow_id=self.id_, status=WorkspaceRetentionRuleStatus.created
        )
        update_workspace_retention_rules(rules, WorkspaceRetentionRuleStatus.active)

    def get_all_restarts(self):
        """Get all the restarts of this workflow, including the original workflow.

        Returns all the restarts of this workflow, that is all the workflows that have
        the same name and the same major run number. This includes the
        original workflow, as well as all the following restarts.
        """
        restarts = Workflow.query.filter(
            Workflow.name == self.name,
            Workflow.owner_id == self.owner_id,
            Workflow.run_number_major == self.run_number_major,
        )
        return restarts

    def inactivate_workspace_retention_rules(self):
        """Inactivate workspace retention rules for all the parent workflows."""
        rules = WorkspaceRetentionRule.query.join(
            self.get_all_restarts().subquery()
        ).filter(
            or_(
                WorkspaceRetentionRule.status == WorkspaceRetentionRuleStatus.created,
                WorkspaceRetentionRule.status == WorkspaceRetentionRuleStatus.active,
            ),
        )
        update_workspace_retention_rules(rules, WorkspaceRetentionRuleStatus.inactive)

    def workspace_has_pending_retention_rules(self):
        """Check whether the workspace has retention rules that are pending.

        All the restarts of the workflow are considered when checking the retention
        rules, as they all share the same workspace.
        """
        pending_rules = WorkspaceRetentionRule.query.join(
            self.get_all_restarts().subquery()
        ).filter(
            WorkspaceRetentionRule.status == WorkspaceRetentionRuleStatus.pending,
        )
        return pending_rules.first() is not None

    def get_priority(self, cluster_memory):
        """Workflow priority when scheduling it.

        Takes into account both the workflow complexity and the number of workflows
        ``running`` at a certain time.
        """
        return round(
            self.owner.get_workflow_overload_priority()
            * self.get_complexity_priority(cluster_memory)
        )

    def get_complexity_priority(self, total_cluster_memory):
        """Calculate workflow priority based on its complexity."""
        if not self.complexity:
            return 0
        wf_memory = int(
            reduce(lambda sum, item: sum + item[0] * item[1], self.complexity, 0)
        )
        if not total_cluster_memory or wf_memory > total_cluster_memory:
            return 0
        return int(round(1 - wf_memory / total_cluster_memory, 2) * MQ_MAX_PRIORITY)

    @staticmethod
    def update_workflow_status(
        db_session, workflow_uuid, status, new_logs="", message=None
    ):
        """Update database workflow status.

        :param workflow_uuid: UUID which represents the workflow.
        :param status: String that represents the workflow status.
        :param new_logs: New logs from workflow execution.
        :param message: Unused.
        """
        try:
            workflow = db_session.query(Workflow).filter_by(id_=workflow_uuid).first()

            if not workflow:
                raise Exception(
                    "Workflow {0} doesn't exist in database.".format(workflow_uuid)
                )
            if status:
                workflow.status = status
            if new_logs:
                workflow.logs = (workflow.logs or "") + new_logs + "\n"
            db_session.commit()
        except Exception as e:
            raise e

    def can_transition_to(self, next_status):
        """Whether the provided workflow can transition to the next status."""
        current_transition = (self.status, next_status)
        return current_transition in ALLOWED_WORKFLOW_STATUS_TRANSITIONS

    def update_workflow_timestamp(self, new_status):
        """Update workflow timestamps according to new status."""
        from .database import Session

        if new_status in [
            RunStatus.finished,
            RunStatus.failed,
        ]:
            self.run_finished_at = datetime.now()
        elif new_status in [RunStatus.stopped]:
            self.run_stopped_at = datetime.now()
        elif new_status in [RunStatus.running]:
            self.run_started_at = datetime.now()
        Session.commit()


@event.listens_for(Workflow.status, "set")
def workflow_status_change_listener(workflow, new_status, old_status, initiator):
    """Workflow status change listener."""

    def _update_disk_quota(workflow):
        if ResourceType.disk.name not in WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY:
            return

        try:
            store_workflow_disk_quota(workflow)
            update_users_disk_quota(user=workflow.owner)
        except Exception as e:
            logging.error(f"Failed to update disk quota: \n{e}\nContinuing...")

    def _update_cpu_quota(workflow):
        if ResourceType.cpu.name not in WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY:
            return

        try:
            update_workflow_cpu_quota(workflow=workflow)
            update_users_cpu_quota(user=workflow.owner)
        except Exception as e:
            logging.error(f"Failed to update cpu quota: \n{e}\nContinuing...")

    workflow.update_workflow_timestamp(new_status)
    if new_status in [RunStatus.finished, RunStatus.failed]:
        workflow.activate_workspace_retention_rules()
    if new_status in [
        RunStatus.finished,
        RunStatus.failed,
        RunStatus.stopped,
    ]:
        _update_cpu_quota(workflow)
        _update_disk_quota(workflow)
    elif new_status in [RunStatus.deleted]:
        _update_disk_quota(workflow)

    return new_status


class Job(Base, Timestamp):
    """Job table."""

    __tablename__ = "job"

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
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
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    prettified_cmd = Column(JSONType)
    job_name = Column(Text)

    __table_args__ = (
        Index(None, "workflow_uuid", "created"),
        {"schema": "__reana"},
    )


@event.listens_for(Job.status, "set")
def job_status_change_listener(job, new_status, old_status, initiator):
    """Job status change listener."""
    if new_status != old_status:
        from .database import Session

        if new_status in [
            JobStatus.finished,
            JobStatus.failed,
        ]:
            job.finished_at = datetime.now()
        elif new_status in [JobStatus.running]:
            job.started_at = datetime.now()

        Session.commit()


class JobCache(Base, Timestamp):
    """Job Cache table."""

    __tablename__ = "job_cache"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    job_id = Column(UUIDType, ForeignKey("__reana.job.id_"), primary_key=True)
    parameters = Column(String(1024))
    result_path = Column(String(1024))
    workspace_hash = Column(String(1024))
    access_times = Column(JSONType)


class AuditLogAction(enum.Enum):
    """Enumeration of audit log actions."""

    request_token = 0
    grant_token = 1
    revoke_token = 2


class AuditLog(Base, Timestamp):
    """Audit log table."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    user_id = Column(UUIDType, ForeignKey("__reana.user_.id_"), nullable=False)
    action = Column(Enum(AuditLogAction), nullable=False)
    details = Column(JSONType)

    def __repr__(self):
        """Audit log string representation."""
        return "<AuditLog {} {}>".format(self.id_, self.action)


class WorkspaceRetentionRuleStatus(enum.Enum):
    """Enumeration of workspace retention rule status.

    - ``created`` : initial status of each rule.
    - ``active``  : the workflow has finished running and the rule can now be considered.
    - ``inactive``: the rule will not be considered, even though it wasn't applied.
    - ``pending`` : the rule is currently being handled by the cronjob.
    - ``applied`` : the rule was handled by the cronjob and the files were deleted.
    """

    created = 0
    active = 1
    inactive = 2
    applied = 3
    pending = 4


ALLOWED_WORKSPACE_RETENTION_RULE_STATUS_TRANSITIONS = [
    # Created
    (WorkspaceRetentionRuleStatus.created, WorkspaceRetentionRuleStatus.active),
    (WorkspaceRetentionRuleStatus.created, WorkspaceRetentionRuleStatus.inactive),
    # Active
    (WorkspaceRetentionRuleStatus.active, WorkspaceRetentionRuleStatus.inactive),
    (WorkspaceRetentionRuleStatus.active, WorkspaceRetentionRuleStatus.pending),
    # Inactive
    (WorkspaceRetentionRuleStatus.inactive, WorkspaceRetentionRuleStatus.active),
    # Pending
    (WorkspaceRetentionRuleStatus.pending, WorkspaceRetentionRuleStatus.applied),
    (WorkspaceRetentionRuleStatus.pending, WorkspaceRetentionRuleStatus.active),
    # Applied
    (WorkspaceRetentionRuleStatus.applied, WorkspaceRetentionRuleStatus.applied),
]


class WorkspaceRetentionAuditLog(Base):
    """Workspace retention audit log table."""

    __tablename__ = "workspace_retention_audit_log"
    __table_args__ = {"schema": "__reana"}

    workspace_retention_rule_id = Column(
        UUIDType,
        ForeignKey("__reana.workspace_retention_rule.id_"),
        primary_key=True,
        nullable=False,
    )
    timestamp = Column(DateTime, server_default=func.now(), primary_key=True)
    action = Column(
        Enum(WorkspaceRetentionRuleStatus), primary_key=True, nullable=False
    )

    def __repr__(self):
        """Workspace Retention audit log string representation."""
        return f"<WorkspaceRetentionAuditLog {self.workspace_retention_rule_id} {self.action}>"


class WorkspaceRetentionRule(Base):
    """Workspace retention rule table."""

    __tablename__ = "workspace_retention_rule"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    workflow_id = Column(UUIDType, ForeignKey("__reana.workflow.id_"), nullable=False)
    workspace_files = Column(String(length=255), nullable=False)
    retention_days = Column(Integer, nullable=False)
    apply_on = Column(DateTime, nullable=True)
    status = Column(
        Enum(WorkspaceRetentionRuleStatus),
        default=WorkspaceRetentionRuleStatus.created,
        nullable=False,
    )
    audit_logs = relationship(
        "WorkspaceRetentionAuditLog", backref="workspace_retention_rule", lazy="dynamic"
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "workspace_files"),
        {"schema": "__reana"},
    )

    def can_transition_to(self, next_status):
        """Whether the provided retention rule can transition to the next status."""
        current_transition = (self.status, next_status)
        return current_transition in ALLOWED_WORKSPACE_RETENTION_RULE_STATUS_TRANSITIONS

    def serialize(self):
        """Serialize workspace retention rule object data."""
        return {
            "id": str(self.id_),
            "workspace_files": self.workspace_files,
            "retention_days": self.retention_days,
            "apply_on": (
                self.apply_on.strftime(WORKFLOW_TIME_FORMAT) if self.apply_on else None
            ),
            "status": self.status.name,
        }

    def __repr__(self):
        """Workspace Retention string representation."""
        return f"<WorkspaceRetentionRule {self.workflow_id} {self.workspace_files} {self.retention_days} {self.status}>"


@event.listens_for(WorkspaceRetentionRule, "after_insert")
@event.listens_for(WorkspaceRetentionRule, "after_update")
def workspace_retention_change_listener(mapper, connection, workspace_retention_rule):
    """Workspace retention change listener."""
    connection.execute(
        WorkspaceRetentionAuditLog.__table__.insert(),
        workspace_retention_rule_id=workspace_retention_rule.id_,
        action=workspace_retention_rule.status,
    )


class ResourceType(enum.Enum):
    """Enumeration of resource types."""

    cpu = 0
    disk = 1


class ResourceUnit(enum.Enum):
    """Enumeration of resource usage units."""

    bytes_ = 0
    milliseconds = 1

    @staticmethod
    def _human_readable_milliseconds(milliseconds):
        """Convert milliseconds usage to human readable string."""
        abs_seconds = abs(milliseconds) // 1000
        hours, minutes, seconds = (
            abs_seconds // (60 * 60),
            (abs_seconds // 60) % 60,
            abs_seconds % 60,
        )

        human_readable_milliseconds = "-" if milliseconds < 0 else ""
        for value, unit in [(hours, "h"), (minutes, "m"), (seconds, "s")]:
            if value >= 1:
                human_readable_milliseconds += "{value}{unit} ".format(
                    value=value, unit=unit
                )

        return human_readable_milliseconds.strip() or "0s"

    @staticmethod
    def _human_readable_bytes(bytes_):
        """Convert bytes usage to human readable string."""
        if bytes_ == 0:
            return "0 Bytes"
        units = ["Bytes", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
        digits = 2
        k = 1024
        unit_index = math.floor(math.log(abs(bytes_), k))

        converted_value = round(bytes_ / math.pow(k, unit_index), digits)
        return "{converted_value} {converted_unit}".format(
            converted_value=(
                int(converted_value)
                if converted_value.is_integer()
                else converted_value
            ),
            converted_unit=units[unit_index],
        )

    @staticmethod
    def human_readable_unit(unit, value):
        """Convert passed value in units to human readable string."""
        convert_to_human_readable = {
            ResourceUnit.bytes_: ResourceUnit._human_readable_bytes,
            ResourceUnit.milliseconds: ResourceUnit._human_readable_milliseconds,
        }
        return convert_to_human_readable[unit](value)


class Resource(Base, Timestamp):
    """Resource table."""

    __tablename__ = "resource"
    __table_args__ = {"schema": "__reana"}

    id_ = Column(UUIDType, primary_key=True, default=generate_uuid)
    name = Column(String(1024), unique=True, nullable=False)
    type_ = Column(Enum(ResourceType), nullable=False)
    unit = Column(Enum(ResourceUnit), nullable=False)
    title = Column(String(1024))

    def __repr__(self):
        """Resource string representation."""
        return "<Resource {}>".format(self.id_)

    @staticmethod
    def initialise_default_resources():
        """Initialise default Resources."""
        from reana_db.database import Session

        existing_resources = [r.name for r in Resource.query.all()]
        default_resources = []
        resource_type_to_unit = {
            ResourceType.cpu: ResourceUnit.milliseconds,
            ResourceType.disk: ResourceUnit.bytes_,
        }
        for type_, name in DEFAULT_QUOTA_RESOURCES.items():
            if name not in existing_resources:
                default_resources.append(
                    Resource(
                        name=name,
                        type_=ResourceType[type_],
                        unit=resource_type_to_unit[ResourceType[type_]],
                        title="Default {} resource.".format(type_),
                    )
                )

        if default_resources:
            Session.add_all(default_resources)
            Session.commit()

        return default_resources


class UserResource(Base, Timestamp):
    """User Resource table."""

    __tablename__ = "user_resource"
    __table_args__ = {"schema": "__reana"}

    user_id = Column(UUIDType, ForeignKey("__reana.user_.id_"), primary_key=True)
    resource_id = Column(UUIDType, ForeignKey("__reana.resource.id_"), primary_key=True)
    quota_limit = Column(BigInteger())
    quota_used = Column(BigInteger())
    user = relationship("User", backref="resources")
    resource = relationship("Resource", backref="user_resource")

    def __repr__(self):
        """User Resource string representation."""
        return "<UserResource {} {}>".format(self.user_id, self.resource_id)


class WorkflowResource(Base, Timestamp):
    """Workflow Resource table."""

    __tablename__ = "workflow_resource"
    __table_args__ = {"schema": "__reana"}

    workflow_id = Column(UUIDType, ForeignKey("__reana.workflow.id_"), primary_key=True)
    resource_id = Column(UUIDType, ForeignKey("__reana.resource.id_"), primary_key=True)
    quota_used = Column(BigInteger())
    workflow = relationship("Workflow", backref="resources")
    resource = relationship("Resource", backref="workflow_resources")

    def __repr__(self):
        """Workflow Resource string representation."""
        return "<WorkflowResource {} {}>".format(self.workflow_id, self.resource_id)


class InteractiveSessionResource(Base, Timestamp):
    """Interactive Session Resource table."""

    __tablename__ = "interactive_session_resource"
    __table_args__ = {"schema": "__reana"}

    session_id = Column(
        UUIDType, ForeignKey("__reana.interactive_session.id_"), primary_key=True
    )
    resource_id = Column(UUIDType, ForeignKey("__reana.resource.id_"), primary_key=True)
    quota_used = Column(BigInteger())
    interactive_session = relationship("InteractiveSession", backref="resources")
    resource = relationship("Resource", backref="interactive_session_resources")

    def __repr__(self):
        """Interactive Session Resource string representation."""
        return "<InteractiveSessionResource {} {}>".format(
            self.session_id, self.resource_id
        )


class QuotaHealth(enum.Enum):
    """Enumeration of quota health statuses."""

    healthy = 0
    warning = 1
    critical = 2
