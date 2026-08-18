# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Static regression guard for Alembic migration create/drop name mismatches.

Migration-only code (the body of ``upgrade()``/``downgrade()``) is not
exercised by any other test in this suite -- the rest of the suite builds
its schema straight from ``Base.metadata.create_all()``, bypassing Alembic
entirely. A migration's ``downgrade()`` can therefore drop a constraint or
index name that ``upgrade()`` never actually created and no test notices,
because nothing ever runs ``alembic downgrade`` against real DDL.

This is exactly what happened in ``972826f7f99f``:
``op.create_check_constraint("idp_identity_complete", ...)`` is a bare
``op`` call with no naming-convention template, so the constraint is
created with the literal name ``"idp_identity_complete"``; ``downgrade()``
called ``op.drop_constraint(op.f("ck_user__idp_identity_complete"), ...)``
-- a different, never-created name -- so downgrading always failed with
"constraint does not exist". ``op.f(...)`` marks a string as an
already-resolved literal name; it does not fix or validate it.

This is a purely source-based, AST-level check (no database needed): for
every migration, collect the constraint/index names ``upgrade()`` creates
and the names ``downgrade()`` drops, and assert every dropped name was
actually created. It cannot verify a migration is otherwise correct, only
that it cannot fail with Postgres's "constraint/index does not exist" on
this specific, previously-unguarded mistake.

Known limitation of this first check: its AST walker only recognizes
structured ``op.drop_constraint``/``op.drop_index``/
``op.create_check_constraint``/``op.create_unique_constraint`` calls. A
migration whose ``downgrade()`` drops a constraint via a raw
``op.execute("ALTER TABLE ... DROP CONSTRAINT IF EXISTS ...")`` SQL string
(as ``972826f7f99f`` does) is invisible to this walker -- it contributes
zero "created" and zero "dropped" names for that file, so the test passes
trivially for it. That is "not checked", not "verified safe". Extending
the walker to parse raw SQL strings is out of scope here.

A second, related gap (PR269-09): a migration's bare
``op.create_check_constraint``/``op.create_unique_constraint`` call is
driven through Alembic's real ``MigrationContext``, which (as wired up by
this repo's ``env.py``, via ``target_metadata = Base.metadata``) copies
this project's ``naming_convention`` onto the ad-hoc ``MetaData()`` Alembic
builds the constraint against. That means the literal string passed to
``op.create_check_constraint`` is *not* the final constraint name -- it is
run back through the naming-convention template exactly like a bare
``models.py`` constraint name would be. A migration literal that is already
pre-expanded (e.g. ``"ck_user__idp_identity_complete"`` instead of the bare
``"idp_identity_complete"``) gets expanded a second time into a
double-prefixed, wrong name at real-migration time
(``"ck_user__ck_user__idp_identity_complete"``), even though the raw
source-literal string alone still reads as a plausible, correctly-named
constraint. The second check below closes that gap: for every
create-constraint call found by the AST walker, it drives the literal name
through Alembic's actual naming-convention machinery (a real
``MigrationContext``/``Operations`` pair in ``as_sql`` mode) and compares
the resulting, *actually-emitted* constraint name against the live,
convention-expanded names already present on
``reana_db.models.Base.metadata`` -- instead of comparing the raw literal
string, which cannot distinguish an already-correct bare name from an
already-expanded one that will be double-prefixed for real.
"""

import ast
import importlib.util
import pathlib
import re
from unittest import mock

import pytest
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine, AesGcmEngine

import reana_db.config as db_config

VERSIONS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "reana_db" / "alembic" / "versions"
)


def _load_migration(filename):
    """Load one migration module directly from its versioned filename."""
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CREATE_METHODS = {
    "create_check_constraint",
    "create_unique_constraint",
    "create_index",
    "create_foreign_key",
    "create_primary_key",
}
_DROP_METHODS = {"drop_constraint", "drop_index"}


def _literal_name(node):
    """Return the literal string an ``op.<method>(...)`` call's first arg names.

    Handles both a bare string constant and ``op.f("...")``, which marks a
    string as an already-resolved literal name without transforming it.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "f"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _named_op_calls(func_node, method_names):
    """Yield the literal name argument of every ``op.<method>(...)`` call found."""
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in method_names
            and node.args
        ):
            name = _literal_name(node.args[0])
            if name:
                yield name


def _create_constraint_calls(func_node, method_names):
    """Yield ``(method_name, name, table_name, schema)`` for create-constraint calls.

    Covers ``op.create_check_constraint``/``op.create_unique_constraint``,
    whose signature is ``(constraint_name, table_name, ..., schema=None)``.
    ``method_name`` is the ``op.<method_name>(...)`` attribute name actually
    called (e.g. ``"create_check_constraint"``), so callers can re-invoke the
    same method through a real ``Operations`` instance.
    """
    for node in ast.walk(func_node):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in method_names
            and len(node.args) >= 2
        ):
            continue
        name = _literal_name(node.args[0])
        table_name = (
            node.args[1].value if isinstance(node.args[1], ast.Constant) else None
        )
        schema = None
        for kw in node.keywords:
            if kw.arg == "schema" and isinstance(kw.value, ast.Constant):
                schema = kw.value.value
        if name and table_name:
            yield node.func.attr, name, table_name, schema


def _live_orm_constraint_names():
    """Return ``{(schema, table): {names}}`` for CheckConstraint/UniqueConstraint.

    ``reana_db.models.Base.metadata`` already has the project's
    ``naming_convention`` applied at Table/Constraint construction time, so
    these are the *actual* names ``create_all()`` produces today -- reading
    them here avoids re-deriving (and potentially mis-deriving) the
    convention's template formula inside the test itself.
    """
    import reana_db.models as models

    live = {}
    for table in models.Base.metadata.tables.values():
        names = {
            c.name
            for c in table.constraints
            if c.__class__.__name__ in ("CheckConstraint", "UniqueConstraint")
        }
        if names:
            live[(table.schema, table.name)] = names
    return live


def _migration_functions(path):
    """Return ``(upgrade, downgrade)`` FunctionDef nodes for one migration file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    upgrade_fn = downgrade_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade_fn = node
        elif isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            downgrade_fn = node
    return upgrade_fn, downgrade_fn


def test_downgrade_never_drops_a_name_upgrade_did_not_create():
    """Every constraint/index name a migration's downgrade() drops must exist.

    Regression guard for the exact 972826f7f99f class of bug: a drop whose
    name was never created makes the migration undowngradable.
    """
    violations = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        upgrade_fn, downgrade_fn = _migration_functions(path)
        if not upgrade_fn or not downgrade_fn:
            continue
        created = set(_named_op_calls(upgrade_fn, _CREATE_METHODS))
        dropped = set(_named_op_calls(downgrade_fn, _DROP_METHODS))
        orphan = dropped - created
        if orphan:
            violations.append(
                f"{path.name}: downgrade drops {sorted(orphan)}, "
                f"upgrade only created {sorted(created)}"
            )
    assert not violations, "Migration downgrade drops an uncreated name:\n" + "\n".join(
        violations
    )


def _alembic_expanded_constraint_name(method_name, name, table_name, schema):
    """Return the constraint name Alembic actually emits for a create call.

    Builds a real ``MigrationContext``/``Operations`` pair the same way
    ``env.py`` does (``target_metadata=reana_db.models.Base.metadata``), in
    ``as_sql`` mode so no real database connection is needed, invokes the
    given create-constraint method with the literal ``name`` exactly as the
    migration source does, and parses the constraint name Alembic actually
    wrote out of the rendered ``ADD CONSTRAINT ...`` SQL. This is what
    closes the PR269-09 gap: the naming-convention template is applied for
    real, so an already-expanded literal (which would otherwise look
    identical to a correct one in a raw string comparison) gets caught
    double-expanding into the wrong name.

    ``sqlite://`` cannot be used here -- SQLite's Alembic dialect has no
    support for ``ALTER TABLE ... ADD CONSTRAINT`` at all, even in
    ``as_sql`` mode. ``postgresql://`` is used instead; ``as_sql=True``
    means no real connection is ever opened, only SQL text is rendered.
    """
    import io

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    import reana_db.models as models

    buffer = io.StringIO()
    context = MigrationContext.configure(
        url="postgresql://",
        opts={
            "as_sql": True,
            "target_metadata": models.Base.metadata,
            "output_buffer": buffer,
        },
    )
    operations = Operations(context)
    method = getattr(operations, method_name)
    if method_name == "create_check_constraint":
        # signature: (constraint_name, table_name, condition, schema=None)
        method(name, table_name, "1=1", schema=schema)
    else:
        # create_unique_constraint signature:
        # (constraint_name, table_name, columns, schema=None) -- the third
        # positional arg is a list of column names, not a SQL string. The
        # actual column name(s) don't affect the emitted constraint name, so
        # any placeholder column name works here.
        method(name, table_name, ["placeholder_column"], schema=schema)
    match = re.search(r"ADD CONSTRAINT (\S+)", buffer.getvalue())
    assert match, f"Could not parse emitted constraint name from: {buffer.getvalue()!r}"
    return match.group(1)


def test_check_and_unique_constraint_names_match_the_naming_convention():
    """Migration-created CHECK/UNIQUE constraint names must match create_all().

    Regression guard for the naming-convention-drift class of bug (PR269-09
    / PR269-10): a migration's bare ``op.create_check_constraint``/
    ``op.create_unique_constraint`` call is driven through the same
    ``naming_convention`` template as ``models.py``'s ORM-declared
    constraints once a real ``MigrationContext`` is involved (which is how
    ``env.py`` actually drives migrations). A literal name that isn't the
    bare/short constraint name -- e.g. one that's already pre-expanded --
    gets expanded a second time into a different, wrong name than what
    ``create_all()`` produces for the equivalent ORM constraint.

    Comparing the raw source-literal string against the live ORM name (as
    an earlier version of this test did) cannot catch that: an
    already-expanded literal can read identically to a correct one as a
    plain string while still emitting the wrong, double-prefixed name at
    real-migration time. So each literal name found via
    ``_create_constraint_calls`` is instead driven through Alembic's actual
    naming-convention machinery via ``_alembic_expanded_constraint_name``,
    and *that* derived name -- what Alembic would really emit -- is what
    gets compared against ``_live_orm_constraint_names()``.

    Scoped to migrations whose target table still exists in current
    ``models.py`` -- a migration for a table since dropped has nothing live
    to compare against and is not a regression this guard can check. Also
    scoped to migrations *after* ``2461610e9698_enforce_naming_convention``
    (2023-11-28): that migration retroactively renamed every pre-existing,
    pre-convention constraint via raw ``ALTER TABLE ... RENAME CONSTRAINT``
    (a pattern this AST-only checker doesn't parse), so older migrations'
    original literal names -- e.g. ``"_user_workflow_run_uc"``, later renamed
    to ``uq_workflow_owner_id`` -- are expected historical artifacts, not
    drift; only migrations from that point on are expected to already match
    the convention when first created.
    """
    live = _live_orm_constraint_names()
    cutoff = "20231128_1729_2461610e9698_enforce_naming_convention.py"
    violations = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name <= cutoff:
            continue
        upgrade_fn, _ = _migration_functions(path)
        if not upgrade_fn:
            continue
        # A constraint introduced by this migration need not still exist in
        # current ORM metadata when a later upgrade deliberately replaces it
        # (for example, moving webhook-secret uniqueness from deterministic
        # ciphertext to an independent digest).  Still validate its original
        # name through the downgrade/create symmetry check above, but do not
        # require superseded schema to remain in today's model.
        later_upgrade_drops = set()
        for later_path in sorted(VERSIONS_DIR.glob("*.py")):
            if later_path.name <= path.name:
                continue
            later_upgrade_fn, _ = _migration_functions(later_path)
            if later_upgrade_fn:
                later_upgrade_drops.update(
                    _named_op_calls(later_upgrade_fn, _DROP_METHODS)
                )
        for method_name, name, table_name, schema in _create_constraint_calls(
            upgrade_fn, {"create_check_constraint", "create_unique_constraint"}
        ):
            if name in later_upgrade_drops:
                continue
            live_names = live.get((schema, table_name))
            if live_names is None:
                continue
            expanded_name = _alembic_expanded_constraint_name(
                method_name, name, table_name, schema
            )
            if expanded_name not in live_names:
                violations.append(
                    f"{path.name}: creates {name!r} on {schema}.{table_name}, "
                    f"which Alembic actually expands to {expanded_name!r} -- "
                    f"create_all() would not produce that name "
                    f"(live names: {sorted(live_names)})"
                )
    assert not violations, (
        "Migration constraint name diverges from the ORM naming convention:\n"
        + "\n".join(violations)
    )


class _RowsResult:
    """Minimal SQLAlchemy result used by migration unit tests."""

    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


@pytest.mark.parametrize(
    "existing,expected_sql,creates",
    [
        (
            {"ck_user__idp_identity_complete"},
            [],
            False,
        ),
        (
            {"ck_user__ck_user__idp_identity_complete"},
            ["RENAME CONSTRAINT"],
            False,
        ),
        (
            {"idp_identity_complete"},
            ["RENAME CONSTRAINT"],
            False,
        ),
        (set(), [], True),
    ],
)
def test_stamped_identity_constraint_repair_converges_known_states(
    existing, expected_sql, creates
):
    """The forward repair handles every known already-stamped schema state."""
    migration = _load_migration(
        "20260824_1015_3f6c0d2a1b7e_repair_idp_identity_constraint.py"
    )
    connection = mock.Mock()
    connection.execute.return_value = _RowsResult([(name,) for name in existing])
    executed = []

    with mock.patch.object(
        migration.op, "get_bind", return_value=connection
    ), mock.patch.object(
        migration.op, "execute", side_effect=executed.append
    ), mock.patch.object(
        migration.op, "create_check_constraint"
    ) as create:
        migration.upgrade()

    query = str(connection.execute.call_args.args[0])
    assert "JOIN pg_class" in query
    assert "JOIN pg_namespace" in query
    assert "ns.nspname" in query and "rel.relname" in query
    assert all(
        any(fragment in statement for statement in executed)
        for fragment in expected_sql
    )
    assert create.called is creates


def test_stamped_identity_constraint_repair_removes_redundant_variant():
    """A correct constraint wins and a simultaneous broken variant is removed."""
    migration = _load_migration(
        "20260824_1015_3f6c0d2a1b7e_repair_idp_identity_constraint.py"
    )
    connection = mock.Mock()
    connection.execute.return_value = _RowsResult(
        [
            ("ck_user__idp_identity_complete",),
            ("ck_user__ck_user__idp_identity_complete",),
        ]
    )
    with mock.patch.object(
        migration.op, "get_bind", return_value=connection
    ), mock.patch.object(migration.op, "execute") as execute, mock.patch.object(
        migration.op, "create_check_constraint"
    ) as create:
        migration.upgrade()

    assert "DROP CONSTRAINT" in execute.call_args.args[0]
    create.assert_not_called()


class _EncryptedValueConnection:
    """Hold one raw encrypted value while a data migration rewrites it."""

    def __init__(self, ciphertext):
        self.ciphertext = ciphertext

    def execute(self, statement, params=None):
        if str(statement).lstrip().upper().startswith("SELECT"):
            return _RowsResult([("session-id", self.ciphertext)])
        self.ciphertext = params["ciphertext"]
        return _RowsResult([])


def test_session_secret_migration_round_trips_cbc_and_gcm(monkeypatch):
    """The session-secret migration preserves plaintext in both directions."""
    migration = _load_migration(
        "20260824_1027_e940248e5165_convert_session_secret_to_gcm.py"
    )
    key = "migration-test-key"
    secret = "interactive-session-secret"
    monkeypatch.setattr(db_config, "DB_SECRET_KEY", key)
    cbc = AesEngine()
    cbc._set_padding_mechanism("pkcs5")
    cbc._update_key(key)
    original = cbc.encrypt(secret).encode("utf-8")
    connection = _EncryptedValueConnection(original)

    with mock.patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()

    gcm = AesGcmEngine()
    gcm._update_key(key)
    assert connection.ciphertext != original
    assert gcm.decrypt(connection.ciphertext.decode("utf-8")) == secret

    with mock.patch.object(migration.op, "get_bind", return_value=connection):
        migration.downgrade()

    assert cbc.decrypt(connection.ciphertext.decode("utf-8")) == secret


def test_user_token_removal_is_explicitly_irreversible():
    """Downgrade refuses to recreate an empty table that suggests data survived."""
    migration = _load_migration("20260824_1031_a6c2120d5b2b_drop_user_token.py")
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()
