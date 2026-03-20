# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-DB utils."""

import calendar
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from reana_commons.errors import REANAMissingWorkspaceError
from reana_commons.utils import get_disk_usage
from reana_db.config import (
    PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY,
    WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY,
)
from sqlalchemy import func, inspect
from sqlalchemy.orm import defer


def build_workspace_path(user_id, workflow_id=None, workspace_root_path=None):
    """Build user's workspace relative path.

    :param user_id: Owner of the workspace.
    :param workflow_id: Optional parameter, if provided gives the path to the
        workflow workspace instead of just the path to the user workspace.
    :param workspace_root_path: Optional parameter, if provided changes the
        root path under which the workflow workspaces are stored.
    :return: String that represents the workspace absolute path.
        i.e. /var/reana/users/0000/workflows/0034
    """
    from reana_commons.config import DEFAULT_WORKSPACE_PATH, SHARED_VOLUME_PATH

    users_dir = os.path.join("users", str(user_id), "workflows")
    if workspace_root_path:
        workspace_path = workspace_root_path
        # in case shared volume is used in workspace path use the default directory
        if SHARED_VOLUME_PATH in workspace_root_path:
            workspace_path = os.path.join(SHARED_VOLUME_PATH, users_dir)
    else:
        workspace_path = os.path.join(DEFAULT_WORKSPACE_PATH, users_dir)

    if workflow_id:
        workspace_path = os.path.join(workspace_path, str(workflow_id))

    return workspace_path


def split_run_number(run_number):
    """Split run number into major and minor run numbers."""
    run_number = str(run_number)
    if "." in run_number:
        return tuple(map(int, run_number.split(".", maxsplit=1)))
    return int(run_number), 0


def _get_workflow_with_uuid_or_name(
    uuid_or_name, user_uuid, include_shared_workflows=False
):
    """Get Workflow from database with uuid or name.

    :param uuid_or_name: String representing a valid UUIDv4 or valid
        Workflow name. Valid name contains only ASCII alphanumerics.

        Name might be in format 'reana.workflow.123' with arbitrary
        number of dot-delimited substrings, where last substring specifies
        the run number of the workflow this workflow name refers to.

        If name does not contain a valid run number, but it is a valid name,
        workflow with latest run number of all the workflows with this name
        is returned.
    :type uuid_or_name: String
    :param user_uuid: UUID of the workflow's owner.

    :rtype: reana-db.models.Workflow
    """
    from reana_db.database import Session
    from reana_db.models import UserWorkflow, Workflow

    # Check existence
    if not uuid_or_name:
        raise ValueError("No Workflow was specified.")

    # Check validity
    try:
        uuid_or_name.encode("ascii")
    except UnicodeEncodeError:
        # `workflow_name` contains something else than just ASCII.
        raise ValueError("Workflow name {} is not valid.".format(uuid_or_name))

    # Check if UUIDv4
    try:
        # is_uuid = UUID(uuid_or_name, version=4)
        is_uuid = UUID("{" + uuid_or_name + "}", version=4)
    except (TypeError, ValueError):
        is_uuid = None

    if is_uuid:
        # `uuid_or_name` is an UUIDv4.
        # Search with it since it is expected to be unique.
        return _get_workflow_by_uuid(uuid_or_name, user_uuid, include_shared_workflows)

    else:
        # `uuid_or_name` is not and UUIDv4. Expect it is a name.

        # Expect name might be in format 'reana.workflow.123' with arbitrary
        # number of dot-delimited substring, where last substring specifies
        # the run_number of the workflow this workflow name refers to.

        # Possible candidates for names are e.g. :
        # 'workflow_name' -> ValueError
        # 'workflow.name' -> True, True
        # 'workflow.name.123' -> True, True
        # '123.' -> True, False
        # '' -> ValueError
        # '.123' -> False, True
        # '..' -> False, False
        # '123.12' -> True, True
        # '123.12.' -> True, False

        # Try to split the dot-separated string.
        try:
            workflow_name, run_number = uuid_or_name.split(".", maxsplit=1)
        except ValueError:
            # Couldn't split. Probably not a dot-separated string.
            #  -> Search with `uuid_or_name`
            return _get_workflow_by_name(
                uuid_or_name, user_uuid, include_shared_workflows
            )

        # Check if `run_number` was specified
        if not run_number:
            # No `run_number` specified.
            # -> Search by `workflow_name`
            return _get_workflow_by_name(
                workflow_name, user_uuid, include_shared_workflows
            )

        # `run_number` was specified.
        try:
            run_number_major, run_number_minor = split_run_number(run_number)
        except ValueError:
            # The specified `run_number` is not valid.
            # Assume that this string is the name of
            # the workflow and search with it.
            return _get_workflow_by_name(
                uuid_or_name, user_uuid, include_shared_workflows
            )

        # `run_number` is valid.

        # Search by `run_number_major` and `run_number_minor`, since it is a primary key.
        if include_shared_workflows:
            workflow = (
                Session.query(Workflow)
                .outerjoin(UserWorkflow, UserWorkflow.workflow_id == Workflow.id_)
                .filter(
                    (Workflow.name == workflow_name)
                    & (Workflow.run_number_major == run_number_major)
                    & (Workflow.run_number_minor == run_number_minor)
                    & (
                        (Workflow.owner_id == user_uuid)
                        | (UserWorkflow.user_id == user_uuid)
                    )
                )
                .one_or_none()
            )
        else:
            workflow = (
                Session.query(Workflow)
                .filter(
                    Workflow.name == workflow_name,
                    Workflow.run_number_major == run_number_major,
                    Workflow.run_number_minor == run_number_minor,
                    Workflow.owner_id == user_uuid,
                )
                .one_or_none()
            )

        if not workflow:
            raise ValueError(
                f"REANA_WORKON is set to {workflow_name}.{str(int(run_number))}, but "
                "that workflow does not exist. "
                "Please set your REANA_WORKON environment "
                "variable appropriately."
            )

        return workflow


def _get_workflow_by_name(workflow_name, user_uuid, include_shared_workflows=False):
    """From Workflows named as `workflow_name` the latest run_number.

    Only use when you are sure that workflow_name is not UUIDv4.

    :rtype: reana-db.models.Workflow
    """
    from reana_db.database import Session
    from reana_db.models import UserWorkflow, Workflow

    if include_shared_workflows:
        workflow = (
            Session.query(Workflow)
            .outerjoin(UserWorkflow, Workflow.id_ == UserWorkflow.workflow_id)
            .filter(
                (Workflow.name == workflow_name)
                & (
                    (Workflow.owner_id == user_uuid)
                    | (UserWorkflow.user_id == user_uuid)
                )
            )
            .order_by(
                Workflow.run_number_major.desc(), Workflow.run_number_minor.desc()
            )
            .first()
        )
    else:
        workflow = (
            Session.query(Workflow)
            .filter(Workflow.name == workflow_name, Workflow.owner_id == user_uuid)
            .order_by(
                Workflow.run_number_major.desc(), Workflow.run_number_minor.desc()
            )
            .first()
        )

    if not workflow:
        raise ValueError(
            "REANA_WORKON is set to {0}, but "
            "that workflow does not exist. "
            "Please set your REANA_WORKON environment "
            "variable appropriately.".format(workflow_name)
        )
    return workflow


def _get_workflow_by_uuid(workflow_uuid, user_uuid, include_shared_workflows=False):
    """Get Workflow with UUIDv4.

    :param workflow_uuid: UUIDv4 of a Workflow.
    :type workflow_uuid: String representing a valid UUIDv4.
    :param user_uuid: UUID of the workflow's owner.

    :rtype: reana-db.models.Workflow
    """
    from reana_db.database import Session
    from reana_db.models import UserWorkflow, Workflow

    if include_shared_workflows:
        workflow = (
            Session.query(Workflow)
            .outerjoin(UserWorkflow, Workflow.id_ == UserWorkflow.workflow_id)
            .filter(
                (Workflow.id_ == workflow_uuid)
                & (
                    (Workflow.owner_id == user_uuid)
                    | (UserWorkflow.user_id == user_uuid)
                )
            )
            .first()
        )
    else:
        workflow = (
            Session.query(Workflow)
            .filter(Workflow.id_ == workflow_uuid, Workflow.owner_id == user_uuid)
            .first()
        )

    if not workflow:
        raise ValueError(
            "REANA_WORKON is set to {0}, but "
            "that workflow does not exist. "
            "Please set your REANA_WORKON environment "
            "variable appropriately.".format(workflow_uuid)
        )
    return workflow


class Timer:
    """Timer to time events and log periodic progress."""

    def __init__(self, name=None, total=None, periodic_delta=100) -> None:
        """Initialise new Timer."""
        self.name = name
        self.total = total
        self.periodic_delta = periodic_delta
        self.count = 0
        self.start = datetime.now()

    def elapsed(self) -> float:
        """Elapsed time since the creation of the Timer, in seconds."""
        diff = datetime.now() - self.start
        return diff.total_seconds()

    def estimated_total(self) -> float:
        """Estimated total time, in seconds."""
        if not self.total or not self.count:
            return 0
        return self.elapsed() * self.total / self.count

    def per_event(self) -> float:
        """Time per event, in seconds."""
        if self.count == 0:
            return 0
        return self.elapsed() / self.count

    def log_progress(self) -> None:
        """Log progress of events."""
        progress = ""
        if self.name:
            progress = f"{self.name} "
        progress += f"progress: {self.count}"
        if self.total:
            progress += f"/{self.total}"
        progress += (
            f"  elapsed: {self.elapsed():.3f}s"
            f"  est.total: {self.estimated_total():.3f}s"
            f"  per event: {self.per_event():.3f}s"
        )
        logging.info(progress)

    def log_periodic_progress(self) -> None:
        """Periodically log progress of events.

        Progress is logged periodically after a given amount of events
        and when all the events are completed.
        """
        if self.count != self.total and self.count % self.periodic_delta != 0:
            return
        self.log_progress()

    def count_event(self) -> None:
        """Count a new event."""
        self.count += 1
        self.log_periodic_progress()


def get_default_quota_resource(resource_type):
    """
    Get default quota resource by given resource type.

    :param resource_type: Resource type corresponding to default resource to get.
    :type resource_type: reana_db.models.ResourceType
    """
    from reana_db.config import DEFAULT_QUOTA_RESOURCES
    from reana_db.models import Resource

    if resource_type not in DEFAULT_QUOTA_RESOURCES.keys():
        raise Exception(
            "Default resource of type {} does not exist.".format(resource_type)
        )

    from reana_db.database import Session

    return (
        Session.query(Resource)
        .filter_by(name=DEFAULT_QUOTA_RESOURCES[resource_type])
        .one()
    )


def should_skip_quota_update(resource_type) -> bool:
    """Check if quota updates should be skipped based on the update policy.

    :param resource_type: Resource type of the quota that needs to be updated.
    """
    return (
        resource_type.name not in WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY
        and not PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY
    )


def update_users_disk_quota(
    user=None, bytes_to_sum: Optional[int] = None, override_policy_checks: bool = False
) -> None:
    """Update users disk quota usage.

    User disk quota usage will be calculated from the individual workflow disk quota
    usage numbers, so this function should be typically called only after
    ``update_workflows_disk_quota()``.

    :param user: User whose disk quota will be updated. If None, applies to all users.
    :param bytes_to_sum: Amount of bytes to sum to user disk quota,
        if None, `du` will be used to recalculate it.

    :type user: reana_db.models.User
    :type bytes_to_sum: int

    :param override_policy_checks: Whether to update the disk quota without checking the
        update policy.
    """
    from reana_db.database import Session
    from reana_db.models import (
        ResourceType,
        User,
        UserResource,
        Workflow,
        WorkflowResource,
    )

    if not override_policy_checks and should_skip_quota_update(ResourceType.disk):
        return

    disk_resource = get_default_quota_resource(ResourceType.disk.name)

    users = [user] if user else Session.query(User).all()
    timer = Timer("User disk quota usage update", total=len(users))
    for u in users:
        user_resource_quota = (
            Session.query(UserResource)
            .filter_by(user_id=u.id_, resource_id=disk_resource.id_)
            .one()
        )
        if bytes_to_sum is not None:
            updated_quota_usage = user_resource_quota.quota_used + bytes_to_sum
            if updated_quota_usage < 0:
                logging.warning(
                    f"Disk quota consumption of user {u.id_} would become negative: "
                    f"{user_resource_quota.quota_used} [original usage] + {bytes_to_sum} [delta] "
                    f"-> {updated_quota_usage} [new usage]. Setting the new usage to zero."
                )
                user_resource_quota.quota_used = 0
            else:
                user_resource_quota.quota_used = updated_quota_usage
        else:
            # get the size of each workspace of each workflow of the given user
            size_per_workspace = (
                Session.query(
                    Workflow.workspace_path,
                    func.max(WorkflowResource.quota_used).label("quota_used"),
                )
                .filter(WorkflowResource.workflow_id == Workflow.id_)
                .filter(WorkflowResource.resource_id == disk_resource.id_)
                .filter(Workflow.owner_id == u.id_)
                # multiple workflows might have the same workspace path, so the query groups
                # by `workspace_path` in order to consider each workspace only once
                .group_by(Workflow.workspace_path)
                .subquery()
            )
            disk_usage_bytes = Session.query(
                func.sum(size_per_workspace.c.quota_used)
            ).scalar()
            if not disk_usage_bytes:
                disk_usage_bytes = 0
            user_resource_quota.quota_used = disk_usage_bytes
        Session.commit()
        timer.count_event()


def update_workflow_cpu_quota(workflow) -> int:
    """Update workflow CPU quota based on started and finished/stopped times.

    :return: Workflow running time in milliseconds if workflow has terminated, else 0.
    """
    from reana_db.database import Session
    from reana_db.models import ResourceType, UserResource, WorkflowResource

    if should_skip_quota_update(ResourceType.cpu):
        return

    cpu_resource = get_default_quota_resource(ResourceType.cpu.name)

    cpu_milliseconds = _get_accounted_workflow_cpu_milliseconds(workflow)

    if cpu_milliseconds:
        # WorkflowResource might exist already if the cluster
        # follows a combined termination + periodic policy (eg. created
        # by the status listener, revisited by the cronjob)
        workflow_resource = (
            Session.query(WorkflowResource)
            .filter_by(workflow_id=workflow.id_, resource_id=cpu_resource.id_)
            .one_or_none()
        )
        if workflow_resource:
            workflow_resource.quota_used = cpu_milliseconds
        else:
            workflow_resource = WorkflowResource(
                workflow_id=workflow.id_,
                resource_id=cpu_resource.id_,
                quota_used=cpu_milliseconds,
            )
            Session.add(workflow_resource)
        Session.commit()
        return cpu_milliseconds
    return 0


def _get_accounted_workflow_cpu_milliseconds(
    workflow, quota_period_start_at=None
) -> int:
    """Return workflow CPU usage in milliseconds.

    If quota_period_start_at is provided, the accounted CPU time is clipped
    so that only the portion inside the active quota window is counted.
    """
    terminated_at = workflow.run_finished_at or workflow.run_stopped_at

    if not workflow.run_started_at or not terminated_at:
        return 0

    effective_start_at = workflow.run_started_at
    if quota_period_start_at:
        effective_start_at = max(effective_start_at, quota_period_start_at)

    if terminated_at <= effective_start_at:
        return 0

    cpu_time = terminated_at - effective_start_at
    return int(cpu_time.total_seconds() * 1000)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole months to a datetime while preserving time of day."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def get_current_quota_period_start_at_from_anchor(
    anchor_at: Optional[datetime],
    quota_period_months: Optional[int],
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Calculate current quota period start from an anchor datetime."""
    if not anchor_at or not quota_period_months:
        return None

    now = now or datetime.utcnow()
    period_start_at = anchor_at
    while now >= _add_months(period_start_at, quota_period_months):
        period_start_at = _add_months(period_start_at, quota_period_months)
    return period_start_at


def _get_current_user_cpu_quota_period_start_at(
    user_resource_quota, now: Optional[datetime] = None
) -> Optional[datetime]:
    """Return the current CPU quota period start for a user resource.

    Use quota_period_start_at if already stored,
    otherwise initialize it from quota_period_anchor_at.

    If the anchored period is in the past, advance it by whole
    quota_period_months intervals until it lands in the current window.
    """
    if not user_resource_quota.quota_period_months:
        return None

    now = now or datetime.utcnow()
    period_months = user_resource_quota.quota_period_months

    period_start_at = user_resource_quota.quota_period_start_at
    if not period_start_at:
        period_start_at = user_resource_quota.quota_period_anchor_at

    if not period_start_at:
        return None

    return get_current_quota_period_start_at_from_anchor(
        period_start_at, period_months, now
    )


def _advance_user_cpu_quota_period_if_needed(
    user_resource_quota, now: Optional[datetime] = None
) -> bool:
    """Advance the user's CPU quota period until it reaches the current window.

    Returns True if the active period start changed, otherwise False.
    """
    if not user_resource_quota.quota_period_months:
        return False

    now = now or datetime.utcnow()
    current_period_start_at = _get_current_user_cpu_quota_period_start_at(
        user_resource_quota, now=now
    )

    if not current_period_start_at:
        return False

    original_period_start_at = user_resource_quota.quota_period_start_at
    if original_period_start_at == current_period_start_at:
        return False

    user_resource_quota.quota_period_start_at = current_period_start_at
    logging.info(
        "Set current CPU quota period for user %s from %s to %s",
        user_resource_quota.user_id,
        original_period_start_at,
        current_period_start_at,
    )
    return True


def update_workflows_cpu_quota() -> None:
    """Update the CPU quotas of all workflows in a more efficient way."""
    from reana_db.database import Session
    from reana_db.models import Workflow

    # logs and reana_specification are not loaded to avoid consuming
    # huge amounts of memory
    workflows = (
        Session.query(Workflow)
        .options(defer(Workflow.logs), defer(Workflow.reana_specification))
        .all()
    )
    # We expunge all the workflows, as they will not be modified when updating the quotas.
    # This makes `Session.commit()` much faster
    for workflow in workflows:
        Session.expunge(workflow)
    timer = Timer("Workflow CPU quota usage update", total=len(workflows))
    for workflow in workflows:
        update_workflow_cpu_quota(workflow)
        timer.count_event()


def update_users_cpu_quota(user=None) -> None:
    """Update users CPU quota usage.

    For users with periodic CPU enabled, advance the active quota
    window if needed and then calculate the CPU usage inside the current window.
    For legacy users, calculate CPU usage from lifetime workflow CPU quotas.

    :param user: User whose CPU quota will be updated. If None, applies to all users.
    :type user: reana_db.models.User
    """
    from reana_db.database import Session
    from reana_db.models import (
        ResourceType,
        User,
        UserResource,
        UserToken,
        UserTokenStatus,
        Workflow,
        WorkflowResource,
    )

    if should_skip_quota_update(ResourceType.cpu):
        return

    cpu_resource = get_default_quota_resource(ResourceType.cpu.name)

    if user:
        users = [user]
    else:
        users = (
            Session.query(User)
            .join(UserToken)
            .filter_by(status=UserTokenStatus.active)  # skip users with no active token
            .all()
        )
    timer_user = Timer("User CPU quota usage update", total=len(users))
    for user in users:
        user_resource_quota = UserResource.query.filter_by(
            user_id=user.id_, resource_id=cpu_resource.id_
        ).first()

        if not user_resource_quota:
            timer_user.count_event()
            continue

        _advance_user_cpu_quota_period_if_needed(user_resource_quota)

        quota_period_start_at = _get_current_user_cpu_quota_period_start_at(
            user_resource_quota
        )

        if quota_period_start_at:
            workflows = Session.query(Workflow).filter_by(owner_id=user.id_).all()
            cpu_milliseconds = sum(
                _get_accounted_workflow_cpu_milliseconds(
                    workflow,
                    quota_period_start_at=quota_period_start_at,
                )
                for workflow in workflows
            )
        else:
            cpu_milliseconds = (
                Session.query(func.sum(WorkflowResource.quota_used))
                .filter(WorkflowResource.resource_id == cpu_resource.id_)
                .join(Workflow, WorkflowResource.workflow_id == Workflow.id_)
                .filter(Workflow.owner_id == user.id_)
                .scalar()
            )

            if not cpu_milliseconds:
                cpu_milliseconds = 0
        user_resource_quota.quota_used = cpu_milliseconds
        Session.commit()
        timer_user.count_event()


def update_workspace_retention_rules(rules, status) -> None:
    """Update workspace retention rules status.

    :param rules: Workspace retention rules that need to be updated
    :param status: Status accoring which retention rules need to be updated

    :type rules: reana_db.models.WorkspaceRetentionRule
    :type status: reana_db.models.WorkspaceRetentionRuleStatus
    """
    from reana_db.database import Session
    from reana_db.models import WorkspaceRetentionRuleStatus

    for rule in rules:
        if rule.status == status:
            continue
        if not rule.can_transition_to(status):
            raise Exception(
                f"Cannot transition workspace retention rule {rule.id_} "
                f"from status {rule.status} to {status}."
            )
        if status == WorkspaceRetentionRuleStatus.inactive:
            rule.apply_on = None
        if status == WorkspaceRetentionRuleStatus.active:
            rule.apply_on = datetime.today().replace(
                hour=23, minute=59, second=59
            ) + timedelta(days=rule.retention_days)
        rule.status = status
        Session.add(rule)
    Session.commit()


def get_disk_usage_or_zero(workspace_path) -> int:
    """Get disk usage for the workspace if exists, zero if not."""
    from reana_db.models import ResourceType

    if (
        ResourceType.disk.name not in WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY
        and not PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY
    ):
        return 0

    try:
        disk_bytes = get_disk_usage(workspace_path, summarize=True)
        return int(disk_bytes[0]["size"]["raw"])
    except REANAMissingWorkspaceError:
        return 0


def store_workflow_disk_quota(
    workflow, bytes_to_sum: Optional[int] = None, override_policy_checks: bool = False
):
    """
    Update or create disk workflow resource.

    :param workflow: Workflow whose disk resource usage must be calculated.
    :param bytes_to_sum: Amount of bytes to sum to workflow disk quota,
        if None, `du` will be used to recalculate it.

    :type workflow: reana_db.models.Workflow
    :type bytes_to_sum: int

    :param override_policy_checks: Whether to update the disk quota without checking the
        update policy.
    """
    from reana_db.database import Session
    from reana_db.models import ResourceType, WorkflowResource

    if not override_policy_checks and should_skip_quota_update(ResourceType.disk):
        return

    disk_resource = get_default_quota_resource(ResourceType.disk.name)
    workflow_resource = (
        Session.query(WorkflowResource)
        .filter_by(workflow_id=workflow.id_, resource_id=disk_resource.id_)
        .one_or_none()
    )

    if workflow_resource:
        if bytes_to_sum is not None:
            updated_quota_usage = workflow_resource.quota_used + bytes_to_sum
            if updated_quota_usage < 0:
                logging.warning(
                    f"Disk quota consumption of workflow {workflow.id_} would become negative: "
                    f"{workflow_resource.quota_used} [original usage] + {bytes_to_sum} [delta] "
                    f"-> {updated_quota_usage} [new usage]. Setting the new usage to zero."
                )
                workflow_resource.quota_used = 0
            else:
                workflow_resource.quota_used = updated_quota_usage
        else:
            workflow_resource.quota_used = get_disk_usage_or_zero(
                workflow.workspace_path
            )
        Session.commit()
    else:
        workflow_resource = WorkflowResource(
            workflow_id=workflow.id_,
            resource_id=disk_resource.id_,
            quota_used=get_disk_usage_or_zero(workflow.workspace_path),
        )
        Session.add(workflow_resource)
        Session.commit()

    return workflow_resource


def update_workflows_disk_quota() -> None:
    """Update the disk quotas of all workflows in a more efficient way."""
    from reana_db.database import Session
    from reana_db.models import Workflow

    # logs and reana_specification are not loaded to avoid consuming
    # huge amounts of memory
    workflows = (
        Session.query(Workflow)
        .options(defer(Workflow.logs), defer(Workflow.reana_specification))
        .all()
    )
    # We expunge all the workflows, as they will not be modified when updating the quotas.
    # This makes `Session.commit()` much faster
    for workflow in workflows:
        Session.expunge(workflow)
    timer = Timer("Workflow disk quota usage update", total=len(workflows))
    for workflow in workflows:
        store_workflow_disk_quota(workflow)
        timer.count_event()


def change_key_encrypted_columns(old_key):
    """Re-encrypt database columns with new secret key.

    REANA should be already deployed with the new secret key in `REANA_SECRET_KEY`.
    The old key is needed to decrypt the database and is passed as parameter.
    """
    from reana_db.database import Session
    from reana_db.models import UserToken
    from reana_db import config

    new_key = config.DB_SECRET_KEY

    # set old key to be able to decrypt columns in database
    config.DB_SECRET_KEY = old_key

    # read the columns from the database
    user_tokens = Session.query(UserToken.id_, UserToken.token).all()
    Session.expunge_all()

    # revert to new key
    config.DB_SECRET_KEY = new_key

    # write columns to the database to encrypt them with new key
    for user_token in user_tokens:
        Session.query(UserToken).filter_by(id_=user_token.id_).update(
            {"token": user_token.token}
        )
    Session.commit()
