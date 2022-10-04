# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-DB."""

from __future__ import absolute_import, print_function

import os
import re

from setuptools import find_packages, setup

readme = open("README.rst").read()
history = open("CHANGES.rst").read()

tests_require = [
    "pytest-reana>=0.9.0a6,<0.10.0",
]

extras_require = {
    "docs": [
        "Sphinx>=1.5.1",
        "sphinx-rtd-theme>=0.1.9",
        "sphinx-click>=1.0.4",
    ],
    "tests": tests_require,
}

extras_require["all"] = []
for key, reqs in extras_require.items():
    if ":" == key[0]:
        continue
    extras_require["all"].extend(reqs)

setup_requires = [
    "pytest-runner>=2.7",
]

install_requires = [
    "alembic>=1.4.2",
    "psycopg2-binary>=2.6.1",
    "SQLAlchemy>=1.2.7,<1.4.0",
    "sqlalchemy-utils>=0.35.0",
    "cryptography>=2.9.2",  # Required by sqlalchemy_utils.EncryptedType
    "reana-commons>=0.9.0a10,<0.10.0",
]

packages = find_packages()


# Get the version string. Cannot be done with import!
with open(os.path.join("reana_db", "version.py"), "rt") as f:
    version = re.search(r'__version__\s*=\s*"(?P<version>.*)"\n', f.read()).group(
        "version"
    )

setup(
    name="reana-db",
    version=version,
    description=__doc__,
    license="MIT",
    long_description=readme + "\n\n" + history,
    author="REANA",
    author_email="info@reana.io",
    url="https://github.com/reanahub/reana-db",
    packages=packages,
    entry_points={
        "console_scripts": ["reana-db=reana_db.cli:cli"],
    },
    zip_safe=False,
    include_package_data=True,
    python_requires=">=3.6",
    install_requires=install_requires,
    extras_require=extras_require,
    setup_requires=setup_requires,
    tests_require=tests_require,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
