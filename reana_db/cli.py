# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2020, 2021, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA DB command line."""

import logging
import os
import sys

import click
from alembic import command
from alembic import config as alembic_config
from reana_commons.config import REANA_LOG_FORMAT, REANA_LOG_LEVEL
from reana_db.config import (
    DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED,
    DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS,
)


from reana_db.database import init_db
from reana_db.models import Resource, ResourceType
from reana_db.utils import (
    get_current_quota_period_start_at_from_anchor,
    get_default_quota_resource,
    change_key_encrypted_columns,
    update_users_cpu_quota,
    update_users_disk_quota,
    update_workflows_cpu_quota,
    update_workflows_disk_quota,
)

# Set up logging for CLI commands
logging.basicConfig(level=REANA_LOG_LEVEL, format=REANA_LOG_FORMAT)


@click.group()
def cli():
    """REANA database commands."""


@cli.command()
def init():
    """Show REANA database migration recipes history."""
    init_db()
    click.secho("Database initialised.", fg="green")


@cli.command()
@click.option(
    "--old-key",
    required=True,
    help="Previous key used to encrypt database columns.",
)
def migrate_secret_key(old_key):
    """Change the secret key used to encrypt database columns."""
    click.echo("Migrating secret key...")

    try:
        change_key_encrypted_columns(old_key)
    except Exception:
        logging.exception("Failed to migrate secret key")
        sys.exit(1)

    click.echo("Successfully migrated secret key")


@cli.group("alembic")
@click.pass_context
def alembic_group(ctx):
    """REANA database migration commands.

    Note that this command is just a light wrapper around alembic.
    """
    reana_alembic_ini = os.path.join(os.path.dirname(__file__), "alembic.ini")
    config = alembic_config.Config(reana_alembic_ini)
    ctx.obj = config


@alembic_group.command(name="init")
@click.pass_obj
def alembic_init(config):
    """Populate 'alembic_version' table with existing revisions."""
    command.stamp(config, "head")


@alembic_group.command()
@click.option(
    "-m", "--message", default=None, help="Message string to use with 'revision'"
)
@click.option(
    "--autogenerate/--no-autogenerate",
    default=True,
    help=(
        "Populate revision script with candidate "
        "migration operations, based on comparison of "
        "database to model"
    ),
)
@click.option(
    "--sql",
    default=False,
    help=(
        "Don't emit SQL to database - dump to standard output/file instead. See alembic docs on offline mode."
    ),
)
@click.option(
    "--head",
    default="head",
    help=("Specify head revision or <branchname>@head to base new revision on."),
)
@click.option(
    "--splice",
    is_flag=True,
    help=("Allow a non-head revision as the 'head' to splice onto."),
)
@click.option(
    "--branch-label",
    default=None,
    help=("Specify a branch label to apply to the new revision"),
)
@click.option(
    "--version-path",
    default=None,
    help=("Specify specific path from config for version file"),
)
@click.option(
    "--rev-id",
    default=None,
    help=("Specify a hardcoded revision id instead of generating one"),
)
@click.option(
    "--depends-on",
    default=None,
    help=(
        "Specify one or more revision identifiers which this revision should depend on."
    ),
)
@click.pass_obj
def revision(
    config,
    message,
    autogenerate,
    sql,
    head,
    splice,
    branch_label,
    version_path,
    rev_id,
    depends_on,
):
    """Create a REANA database alembic revision."""
    command.revision(
        config,
        message=message,
        autogenerate=autogenerate,
        sql=sql,
        head=head,
        splice=splice,
        branch_label=branch_label,
        version_path=version_path,
        rev_id=rev_id,
        depends_on=depends_on,
    )


@alembic_group.command()
@click.argument("revision", default="head")
@click.option(
    "--sql",
    is_flag=True,
    help=(
        "Don't emit SQL to database - dump to standard output/file instead. See alembic docs on offline mode."
    ),
)
@click.option(
    "--tag",
    default=None,
    help=("Arbitrary 'tag' name - can be used by custom env.py scripts."),
)
@click.pass_obj
def upgrade(config, revision, sql, tag):
    """Upgrade REANA database."""
    command.upgrade(config, revision, sql=sql, tag=tag)


@alembic_group.command()
@click.argument("revision", default="head")
@click.option(
    "--sql",
    is_flag=True,
    help=(
        "Don't emit SQL to database - dump to standard output/file instead. See alembic docs on offline mode."
    ),
)
@click.option(
    "--tag",
    default=None,
    help=("Arbitrary 'tag' name - can be used by custom env.py scripts."),
)
@click.pass_obj
def downgrade(config, revision, sql, tag):
    """Downgrade REANA database."""
    command.downgrade(config, revision, sql=sql, tag=tag)


@alembic_group.command()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help=("Use more verbose output."),
)
@click.pass_obj
def current(config, verbose):
    """Show current database state."""
    command.current(config, verbose=verbose)


@alembic_group.command()
@click.option(
    "-r",
    "--rev-range",
    default=None,
    help=("Specify a revision range; format is [start]:[end]."),
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help=("Use more verbose output."),
)
@click.option(
    "-i",
    "--indicate-current",
    is_flag=True,
    help=("Indicate the current revision."),
)
@click.pass_obj
def history(config, rev_range, verbose, indicate_current):
    """Show REANA database migration recipes history."""
    command.history(
        config, rev_range=rev_range, verbose=verbose, indicate_current=indicate_current
    )


@cli.group("quota")
@click.pass_context
def quota_group(ctx):
    """REANA DB quota related commands."""


@quota_group.command()
def create_default_resources():
    """Create default quota resources."""
    created_resources = Resource.initialise_default_resources()
    if created_resources:
        click.secho(
            "Created resources: {}".format([r.name for r in created_resources]),
            fg="green",
        )
    else:
        click.secho(
            "No action to be taken: default resources already exist.", fg="yellow"
        )
        sys.exit(1)


@quota_group.command()
def resource_usage_update() -> None:
    """Update users disk and CPU quotas."""

    def _resource_usage_update(resource: ResourceType) -> None:
        """Update users resource quota usage."""
        try:
            if resource == ResourceType.disk:
                update_workflows_disk_quota(override_policy_checks=True)
                update_users_disk_quota(override_policy_checks=True)
                click.secho(
                    "Disk quota usage updated successfully for all users and workflows.",
                    fg="green",
                )
            elif resource == ResourceType.cpu:
                update_workflows_cpu_quota(override_policy_checks=True)
                update_users_cpu_quota(override_policy_checks=True)
                click.secho(
                    "CPU quota usage updated successfully for all users and workflows.",
                    fg="green",
                )
        except Exception as e:
            click.secho(
                f"[ERROR]: An error occurred when updating users {resource.name} quota usage: {repr(e)}",
                fg="red",
            )
            sys.exit(1)

    _resource_usage_update(ResourceType.disk)
    _resource_usage_update(ResourceType.cpu)


@quota_group.command("init-periodic-defaults")
def init_periodic_defaults() -> None:
    """Backfill deployment default periodic CPU quota policy for existing users."""
    from reana_db.database import Session
    from reana_db.models import UserResource

    if not (
        DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED
        and DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS
    ):
        click.secho(
            "Periodic CPU reset deployment defaults are not configured.",
            fg="yellow",
        )
        return

    cpu_resource = get_default_quota_resource(ResourceType.cpu.name)
    user_resources = (
        Session.query(UserResource)
        .filter(UserResource.resource_id == cpu_resource.id_)
        .filter(UserResource.quota_period_months.is_(None))
        .all()
    )

    for user_resource in user_resources:
        user_resource.quota_period_months = DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS
        user_resource.quota_period_start_at = (
            get_current_quota_period_start_at_from_anchor(
                anchor_at=user_resource.user.created,
                quota_period_months=DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS,
            )
        )
    Session.commit()
    updated_rows = len(user_resources)

    click.secho(
        f"Initialised periodic CPU reset policy for {updated_rows} existing users.",
        fg="green",
    )
