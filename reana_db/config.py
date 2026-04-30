# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA DB configuration."""

import os
from distutils.util import strtobool

from reana_commons.config import REANA_INFRASTRUCTURE_COMPONENTS_HOSTNAMES

DB_NAME = os.getenv("REANA_DB_NAME", "reana")
"""Database name."""

DB_USERNAME = os.getenv("REANA_DB_USERNAME", "reana")
"""Database user name."""

DB_PASSWORD = os.getenv("REANA_DB_PASSWORD", "reana")
"""Database password."""

DB_HOST = os.getenv("REANA_DB_HOST", REANA_INFRASTRUCTURE_COMPONENTS_HOSTNAMES["db"])
"""Database service host."""
# Loading REANA_COMPONENT_PREFIX from environment because REANA-DB
# doesn't depend on REANA-Commons, the package which loads this config.

DB_PORT = os.getenv("REANA_DB_PORT", "5432")
"""Database service port."""

DB_SECRET_KEY = os.getenv("REANA_SECRET_KEY", "reana")
"""Database encryption secret key."""

SQLALCHEMY_DATABASE_URI = os.getenv(
    "REANA_SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg2://{username}:{password}"
    "@{host}:{port}/{db}".format(
        username=DB_USERNAME,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        db=DB_NAME,
    ),
)
"""SQLAlchemy database location."""

SQLALCHEMY_MAX_OVERFLOW = int(float(os.getenv("SQLALCHEMY_MAX_OVERFLOW", 2)))
"""How many new connections can temporarily exceed the pool size?"""

SQLALCHEMY_POOL_PRE_PING = (
    os.getenv("SQLALCHEMY_POOL_PRE_PING", "False").lower() == "true"
)
"""Do we always pre-ping for pessimistic connection handling?"""

SQLALCHEMY_POOL_RECYCLE = int(float(os.getenv("SQLALCHEMY_POOL_RECYCLE", 3600)))
"""How many seconds a connection can persist?"""

SQLALCHEMY_POOL_SIZE = int(float(os.getenv("SQLALCHEMY_POOL_SIZE", 5)))
"""How many permanent connections to the database to keep?"""

SQLALCHEMY_POOL_TIMEOUT = int(float(os.getenv("SQLALCHEMY_POOL_TIMEOUT", 30)))
"""How many seconds to wait when retrieving a new connection from the pool?"""

DEFAULT_QUOTA_RESOURCES = {
    "cpu": "processing time",
    "disk": "shared storage",
}
"""Default quota resources to fill Resource table."""

DEFAULT_QUOTA_LIMITS = {
    "cpu": int(float(os.getenv("REANA_DEFAULT_QUOTA_CPU_LIMIT", 0))),
    "disk": int(float(os.getenv("REANA_DEFAULT_QUOTA_DISK_LIMIT", 0))),
}
"""Default CPU (in milliseconds) and disk (in bytes) quota limits."""


def _get_optional_int_env(var_name):
    value = os.getenv(var_name)
    return int(float(value)) if value not in (None, "") else None


DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED = bool(
    strtobool(os.getenv("REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_ENABLED", "false"))
)
"""Whether newly created users should receive a periodic CPU accounting policy."""

DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS = _get_optional_int_env(
    "REANA_DEFAULT_QUOTA_CPU_PERIODIC_RESET_MONTHS"
)
"""Length of the default CPU accounting window in months for newly created users."""

policies = os.getenv("REANA_WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY")
WORKFLOW_TERMINATION_QUOTA_UPDATE_POLICY = policies.split(",") if policies else []
"""What quota types to update, if not specified all quotas will be calculated, if empty no quotas will be updated."""


PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY = strtobool(
    os.getenv("REANA_PERIODIC_RESOURCE_QUOTA_UPDATE_POLICY", "false")
)
"""Whether to run the periodic (cronjob) resource quota updater."""
