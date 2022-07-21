# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB models tests."""

from uuid import uuid4

import pytest
import mock

from reana_db.models import (
    ALLOWED_WORKFLOW_STATUS_TRANSITIONS,
    AuditLogAction,
    ResourceUnit,
    ResourceType,
    JobStatus,
    UserTokenStatus,
    UserTokenType,
    Workflow,
    WorkflowResource,
    RunStatus,
    WorkspaceRetentionRule,
    WorkspaceRetentionRuleStatus,
)
from reana_db.utils import (
    get_default_quota_resource,
    update_users_cpu_quota,
    update_workspace_retention_rules,
)


def test_workflow_run_number_assignment(db, session, new_user):
    """Test workflow run number assignment."""
    workflow_name = "workflow"

    first_workflow = Workflow(
        id_=str(uuid4()),
        name=workflow_name,
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
    )
    session.add(first_workflow)
    session.commit()
    assert first_workflow.run_number == 1
    second_workflow = Workflow(
        id_=str(uuid4()),
        name=workflow_name,
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
    )
    session.add(second_workflow)
    session.commit()
    assert second_workflow.run_number == 2
    first_workflow_restart = Workflow(
        id_=str(uuid4()),
        name=workflow_name,
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
        restart=True,
        run_number=first_workflow.run_number,
    )
    session.add(first_workflow_restart)
    session.commit()
    assert first_workflow_restart.run_number == 1.1
    first_workflow_second_restart = Workflow(
        id_=str(uuid4()),
        name=workflow_name,
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
        restart=True,
        run_number=first_workflow_restart.run_number,
    )
    session.add(first_workflow_second_restart)
    session.commit()
    assert first_workflow_second_restart.run_number == 1.2


def test_workflow_retention_rules(db, session, new_user):
    """Test workflow retention rules."""
    retention_rules = [{"workspace_files": "**/*.root", "retention_days": 1}]
    workflow = Workflow(
        id_=str(uuid4()),
        name="workflow",
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
    )
    session.add(workflow)
    session.commit()

    workflow.set_workspace_retention_rules(retention_rules)
    assert (
        workflow.retention_rules.first().status == WorkspaceRetentionRuleStatus.created
    )
    workflow.activate_workspace_retention_rules()
    assert (
        workflow.retention_rules.first().status == WorkspaceRetentionRuleStatus.active
    )
    workflow.inactivate_workspace_retention_rules()
    assert (
        workflow.retention_rules.first().status == WorkspaceRetentionRuleStatus.inactive
    )
    rules = workflow.retention_rules.all()
    with pytest.raises(Exception) as e:
        update_workspace_retention_rules(rules, WorkspaceRetentionRuleStatus.created)
    assert "Cannot transition workspace retention rule" in e.value.args[0]

    with pytest.raises(Exception) as e:
        workflow.set_workspace_retention_rules(retention_rules)
    assert "duplicate key value violates unique constraint" in e.value.args[0]


# def _test_when_workflows_delete_workspace_retention_rules_inactivated(
#     db, session, new_user
# ):
#     retention_rules = [{"workspace_files": "**/*.root", "retention_days": 1}]
#     workflow = Workflow(
#         id_=str(uuid4()),
#         name="workflow",
#         owner_id=new_user.id_,
#         reana_specification=[],
#         type_="serial",
#         logs="",
#     )
#     session.add(workflow)
#     session.commit()
#
#     workflow.set_workspace_retention_rules(retention_rules)
#     workflow.status = RunStatus.deleted
#     session.add(workflow)
#     session.commit()
#
#     for rule in workflow.retention_rules.all():
#         assert rule.status == WorkspaceRetentionRuleStatus.inactive


@mock.patch(
    "reana_commons.utils.get_disk_usage", return_value=[{"size": {"raw": "128"}}]
)
@pytest.mark.parametrize(
    "from_status, to_status, can_transition",
    [
        (RunStatus.created, RunStatus.failed, False),
        (RunStatus.created, RunStatus.finished, False),
        (RunStatus.created, RunStatus.stopped, False),
        (RunStatus.created, RunStatus.running, False),
        (RunStatus.created, RunStatus.pending, False),
        (RunStatus.queued, RunStatus.failed, True),
        (RunStatus.queued, RunStatus.finished, False),
        (RunStatus.queued, RunStatus.stopped, False),
        (RunStatus.queued, RunStatus.running, False),
        (RunStatus.pending, RunStatus.failed, False),
        (RunStatus.pending, RunStatus.finished, False),
        (RunStatus.pending, RunStatus.stopped, False),
        (RunStatus.pending, RunStatus.created, False),
        (RunStatus.deleted, RunStatus.created, False),
        (RunStatus.deleted, RunStatus.failed, False),
        (RunStatus.deleted, RunStatus.finished, False),
        (RunStatus.deleted, RunStatus.stopped, False),
        (RunStatus.failed, RunStatus.created, False),
        (RunStatus.failed, RunStatus.finished, False),
        (RunStatus.failed, RunStatus.stopped, False),
        (RunStatus.finished, RunStatus.created, False),
        (RunStatus.finished, RunStatus.failed, False),
        (RunStatus.finished, RunStatus.stopped, False),
        (RunStatus.running, RunStatus.created, False),
        (RunStatus.running, RunStatus.deleted, False),
        (RunStatus.stopped, RunStatus.created, False),
        (RunStatus.stopped, RunStatus.failed, False),
        (RunStatus.stopped, RunStatus.finished, False),
        (RunStatus.stopped, RunStatus.running, False),
    ]
    + [tuple + (True,) for tuple in ALLOWED_WORKFLOW_STATUS_TRANSITIONS],
)
def test_workflow_can_transition_to(
    db, session, from_status, to_status, can_transition, new_user
):
    """Test workflow run number assignment."""
    workflow_name = "test-workflow"
    workflow = Workflow(
        id_=str(uuid4()),
        name=workflow_name,
        owner_id=new_user.id_,
        reana_specification=[],
        type_="serial",
        logs="",
        status=from_status,
    )
    session.add(workflow)
    session.commit()
    assert workflow.can_transition_to(to_status) is can_transition


@pytest.mark.parametrize(
    "action, can_do",
    [
        (AuditLogAction.request_token, True),
        ("request_token", True),
        ("delete_database", False),
    ],
)
def test_audit_action(session, new_user, action, can_do):
    """Test audit log actions creation."""
    details = {"reason": "Use REANA."}

    def _audit_action():
        audited_action = new_user.log_action(action, details)
        return audited_action

    if can_do:
        audited_action = _audit_action()
        assert audited_action.action == getattr(
            AuditLogAction, getattr(action, "name", action)
        )
        assert audited_action.details == details
    else:
        with pytest.raises(Exception):
            _audit_action()


def test_access_token(db, session, new_user):
    """Test user access token use cases."""
    assert new_user.access_token
    assert new_user.access_token_status == UserTokenStatus.active.name
    assert new_user.tokens.count() == 1
    assert new_user.active_token.type_ == UserTokenType.reana

    # Assign second active access token
    with pytest.raises(Exception) as e:
        new_user.access_token = "new_token"
    assert "has already an active access token" in e.value.args[0]

    # Revoke token
    new_user.active_token.status = UserTokenStatus.revoked.name
    session.commit()
    assert not new_user.access_token
    assert not new_user.active_token
    assert new_user.access_token_status == UserTokenStatus.revoked.name

    # User requests token
    new_user.request_access_token()
    assert not new_user.access_token
    assert new_user.access_token_status == UserTokenStatus.requested.name

    # Tries to request again
    with pytest.raises(Exception) as e:
        new_user.request_access_token()
    assert "has already requested an access token" in e.value.args[0]

    # Grant new token
    new_user.access_token = "new_token"
    session.commit()
    assert new_user.access_token == "new_token"
    assert new_user.tokens.count() == 2

    # Status of most recent access token
    assert new_user.access_token_status == UserTokenStatus.active.name


@mock.patch(
    "reana_commons.utils.get_disk_usage", return_value=[{"size": {"raw": "128"}}]
)
@mock.patch(
    "reana_db.models.WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY",
    [ResourceType.cpu.name, ResourceType.disk.name],
)
def test_workflow_cpu_quota_usage_update(db, session, run_workflow):
    """Test quota usage update once workflow is finished/stopped/failed."""
    time_elapsed_seconds = 0.5
    workflow = run_workflow(time_elapsed_seconds=time_elapsed_seconds)
    cpu_resource = get_default_quota_resource(ResourceType.cpu.name)
    cpu_milliseconds = (
        WorkflowResource.query.filter_by(
            workflow_id=workflow.id_, resource_id=cpu_resource.id_
        )
        .first()
        .quota_used
    )
    assert cpu_milliseconds >= time_elapsed_seconds * 1000


@pytest.mark.parametrize(
    "workflow_termination_quota_update_policy",
    [
        ([ResourceType.cpu.name, ResourceType.disk.name],),
        ([ResourceType.cpu.name]),
        ([ResourceType.disk.name]),
        ([]),
    ],
)
@mock.patch("reana_db.utils.get_disk_usage", return_value=[{"size": {"raw": "128"}}])
def test_workflow_termination_user_quota_usage(
    db, session, new_user, run_workflow, workflow_termination_quota_update_policy
):
    """Test aggregated CPU usage per user."""
    with mock.patch(
        "reana_db.models.WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY",
        workflow_termination_quota_update_policy,
    ), mock.patch(
        "reana_db.utils.WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY",
        workflow_termination_quota_update_policy,
    ):

        time_elapsed_seconds = 0.5
        num_workflows = 2
        for n in range(num_workflows):
            run_workflow(time_elapsed_seconds=time_elapsed_seconds)

        quota_usage = new_user.get_quota_usage()

        if ResourceType.cpu.name in workflow_termination_quota_update_policy:
            assert (
                quota_usage["cpu"]["usage"]["raw"]
                >= num_workflows * time_elapsed_seconds * 1000
            )
        else:
            quota_usage["cpu"]["usage"]["raw"] == 0

        if ResourceType.disk.name in workflow_termination_quota_update_policy:
            assert quota_usage["disk"]["usage"]["raw"] == 128
        else:
            quota_usage["disk"]["usage"]["raw"] == 0


@pytest.mark.parametrize(
    "workflow_termination_quota_update_policy, periodic_update",
    [
        ([], True),
        ([], False),
        ([ResourceType.cpu.name], False),
        ([ResourceType.cpu.name], True),
    ],
)
def test_all_users_cpu_quota_usage_update(
    db,
    session,
    new_user,
    run_workflow,
    workflow_termination_quota_update_policy,
    periodic_update,
):
    """Test CPU periodic update cronjob functionality."""
    with mock.patch(
        "reana_db.models.WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY",
        workflow_termination_quota_update_policy,
    ), mock.patch(
        "reana_db.utils.PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY",
        periodic_update,
    ):
        time_elapsed_seconds = 0.5
        num_workflows = 2
        for n in range(num_workflows):
            run_workflow(time_elapsed_seconds=time_elapsed_seconds)

        quota_cpu_usage = new_user.get_quota_usage()["cpu"]["usage"]["raw"]
        if workflow_termination_quota_update_policy:
            assert quota_cpu_usage >= num_workflows * time_elapsed_seconds * 1000
        else:
            assert quota_cpu_usage == 0

        update_users_cpu_quota()

        quota_cpu_usage = new_user.get_quota_usage()["cpu"]["usage"]["raw"]
        if workflow_termination_quota_update_policy or periodic_update:
            assert quota_cpu_usage >= num_workflows * time_elapsed_seconds * 1000
        else:
            assert quota_cpu_usage == 0


@pytest.mark.parametrize(
    "unit, value, human_readable_string",
    [
        # Milliseconds VS human readable
        (ResourceUnit.milliseconds, 0, "0s"),
        (ResourceUnit.milliseconds, 1000 * 35, "35s"),
        (ResourceUnit.milliseconds, 1000 * 60 * 7 + 1000 * 40, "7m 40s"),
        (ResourceUnit.milliseconds, 1000 * 60 * 60 * 2, "2h"),
        (ResourceUnit.milliseconds, 1000 * 60 * 60 * 2 + 1000 * 60 * 20, "2h 20m"),
        (
            ResourceUnit.milliseconds,
            1000 * 60 * 60 * 2 + 1000 * 60 * 35 + 1000 * 10,
            "2h 35m 10s",
        ),
        # Bytes VS human readable
        (ResourceUnit.bytes_, 0, "0 Bytes"),
        (ResourceUnit.bytes_, 1024 * 35, "35 KiB"),
        (ResourceUnit.bytes_, 1024 * 200 + 512, "200.5 KiB"),
        (ResourceUnit.bytes_, 1024**2, "1 MiB"),
        (ResourceUnit.bytes_, 1024**2 + 1024 * 768, "1.75 MiB"),
        (ResourceUnit.bytes_, 1024**3 * 5 + 1024**2 * 100, "5.1 GiB"),
        (ResourceUnit.bytes_, 1024**4 + 1024**3 * 256, "1.25 TiB"),
    ],
)
def test_human_readable_unit_values(unit, value, human_readable_string):
    """Test converting units from canonical values to human-readable string."""
    assert ResourceUnit.human_readable_unit(unit, value) == human_readable_string


@pytest.mark.parametrize(
    "REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES, job_status, should_cleanup, class_, emits_warning",
    [
        (["failed", "finished"], RunStatus.finished, False, RunStatus, False),
        (["failed"], RunStatus.finished, True, RunStatus, False),
        (["failed"], "finished", True, RunStatus, False),
        (["failed", "finished"], JobStatus.finished, False, JobStatus, False),
        (["failed"], JobStatus.failed, False, JobStatus, False),
        (["failed"], "failed", False, JobStatus, False),
        (["faild"], "failed", True, JobStatus, True),
        ([], "failed", True, JobStatus, False),
    ],
)
def test_should_cleanup_job(
    REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES,
    job_status,
    should_cleanup,
    class_,
    emits_warning,
    caplog,
):
    """Test logic to determine whether jobs should be cleaned up depending on their status."""
    with mock.patch(
        "reana_db.models.REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES",
        REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES,
    ):
        assert class_.should_cleanup_job(job_status) == should_cleanup
        if emits_warning:
            assert any(
                s in caplog.text
                for s in REANA_RUNTIME_KUBERNETES_KEEP_ALIVE_JOBS_WITH_STATUSES
            )


@pytest.mark.parametrize(
    "running_workflows, REANA_MAX_CONCURRENT_BATCH_WORKFLOWS,  priority",
    [
        (2, 10, 0.82),
        (3, 10, 0.73),
        (4, 10, 0.64),
        (11, 10, 0.1),
        (15, 30, 0.55),
        (12, 30, 0.64),
        (30, 30, 0.1),
        (17, 50, 0.69),
        (7, 64, 0.9),
    ],
)
def test_get_workflow_overload_priority(
    run_workflow,
    running_workflows,
    REANA_MAX_CONCURRENT_BATCH_WORKFLOWS,
    priority,
):
    """Test logic to determine workflow overload priority factor based on running workflows."""
    with mock.patch(
        "reana_db.models.REANA_MAX_CONCURRENT_BATCH_WORKFLOWS",
        REANA_MAX_CONCURRENT_BATCH_WORKFLOWS,
    ):
        for _ in range(running_workflows):
            workflow = run_workflow(finish=False)

        assert workflow.owner.get_workflow_overload_priority() == priority


@pytest.mark.parametrize(
    "complexity,priority,cluster_memory",
    [
        ([(1, 8589934592.0), (2, 4294967296.0), (5, 4294967296.0)], 55, 85899345920.0),
        ([(2, 8)], 96, 400),
        ([(1, 6), (1, 6)], 97, 400),
        ([(5, 2), (5, 2)], 95, 400),
        ([(1, 396)], 1, 400),
        ([(1, 401)], 0, 400),
        ([], 0, 100),
        ([(3, 5), (1, 5)], 80, 100),
        ([(3, 20), (2, 10)], 20, 100),
        ([(2, 20), (5, 1)], 55, 100),
        ([(1, 1), (1, 1)], 98, 100),
        ([(1, 10), (1, 20), (1, 5), (1, 5), (1, 10), (1, 10)], 40, 100),
    ],
)
def test_get_workflow_complexity_priority(
    run_workflow, session, complexity, priority, cluster_memory
):
    """Test ``get_complexity_priority``."""
    workflow = run_workflow(finish=False)
    workflow.complexity = complexity
    session.commit()
    assert workflow.get_complexity_priority(cluster_memory) == priority
