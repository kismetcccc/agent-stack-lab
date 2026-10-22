"""Explicit additive v1 -> v2 migration. Never reset, alter, or down-migrate data."""

from sqlalchemy import UniqueConstraint, inspect, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.db import Base, SchemaVersion, connect

CURRENT_SCHEMA_VERSION = 2
# Freeze the historical table set; adding models to Base MUST NOT expand v1.
V1_TABLES = ("users", "sessions", "tasks", "outbox", "inbox", "attempts", "schema_version", "task_events")
V2_TABLES = ("lab_records", "lab_kafka_messages")


def _validate_table(inspector, name, *, allow_missing_indexes=False):
    expected = Base.metadata.tables[name]
    actual = {column["name"]: column for column in inspector.get_columns(name)}
    if set(actual) != set(expected.columns.keys()):
        raise RuntimeError(f"Unsupported schema: columns differ in {name}")
    for column in expected.columns:
        found = actual[column.name]
        explicit_collation = getattr(column.type.dialect_impl(inspector.bind.dialect), "collation", None)
        actual_collation = getattr(found["type"], "collation", None)
        if explicit_collation is not None and actual_collation is None:
            # MySQL may omit a per-column COLLATE when it equals the table default.
            actual_collation = inspector.get_table_options(name).get(inspector.bind.dialect.name + "_collate")
        if (
            type(found["type"].as_generic()) is not type(column.type.as_generic())
            or getattr(found["type"], "length", None) != getattr(column.type, "length", None)
            or bool(found["nullable"]) != column.nullable
            or (explicit_collation is not None and actual_collation != explicit_collation)
        ):
            raise RuntimeError(f"Unsupported schema: column definition differs in {name}.{column.name}")
    if set(inspector.get_pk_constraint(name)["constrained_columns"]) != {
        column.name for column in expected.primary_key.columns
    }:
        raise RuntimeError(f"Unsupported schema: primary key differs in {name}")
    indexes = {index["name"]: index for index in inspector.get_indexes(name)}
    for index in expected.indexes:
        found = indexes.get(index.name)
        if found is None and allow_missing_indexes:
            continue
        if found is None or found["column_names"] != [column.name for column in index.columns] or bool(
            found["unique"]
        ) != bool(index.unique):
            raise RuntimeError(f"Unsupported schema: index differs in {name}")
    unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
    unique.update(tuple(item["column_names"]) for item in indexes.values() if item["unique"])
    expected_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in expected.constraints if isinstance(constraint, UniqueConstraint)
    }
    if unique != expected_unique:
        raise RuntimeError(f"Unsupported schema: unique constraints differ in {name}")
    # Neither historical nor teaching tables define these constraints. Extra constraints
    # can silently reject otherwise valid requests, so they are not harmless additions.
    if inspector.get_check_constraints(name) or inspector.get_foreign_keys(name):
        raise RuntimeError(f"Unsupported schema: unexpected constraints in {name}")


def _state(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return set(), tables
    if "schema_version" not in tables:
        raise RuntimeError("Unsupported schema: existing tables have no version history")
    _validate_table(inspector, "schema_version")
    with engine.connect() as connection:
        versions = set(connection.execute(select(SchemaVersion.version)).scalars())
    if versions not in ({1}, {1, 2}):
        raise RuntimeError("Unsupported schema version history; no changes applied")
    if not set(V1_TABLES) <= tables:
        raise RuntimeError("Unsupported schema: historical v1 tables are missing")
    for name in V1_TABLES:
        _validate_table(inspector, name)
    for name in V2_TABLES:
        if name in tables:
            _validate_table(inspector, name, allow_missing_indexes=versions == {1})
    if versions == {1, 2} and not set(V2_TABLES) <= tables:
        raise RuntimeError("Unsupported schema: version 2 objects are missing")
    return versions, tables


def assert_current_schema(engine):
    versions, _ = _state(engine)
    if versions != {1, 2}:
        raise RuntimeError("Schema version 2 required; run the explicit migration first")


def migrate(engine):
    versions, tables = _state(engine)  # Validate all known preexisting objects BEFORE any mutation.
    if versions == {1, 2}:
        return
    if not versions:
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in V1_TABLES])
        with Session(engine) as session, session.begin():
            session.add(SchemaVersion(version=1))
    # MySQL DDL commits implicitly. Correct partial v2 table/index creation is resumable;
    # conflicting objects fail validation rather than being overwritten or "repaired".
    for name in V2_TABLES:
        table = Base.metadata.tables[name]
        if name not in tables:
            table.create(engine, checkfirst=True)
        for index in table.indexes:
            index.create(engine, checkfirst=True)
    inspector = inspect(engine)
    for name in V2_TABLES:
        _validate_table(inspector, name)
    with Session(engine) as session, session.begin():
        session.add(SchemaVersion(version=CURRENT_SCHEMA_VERSION))
    assert_current_schema(engine)


if __name__ == "__main__":
    engine, _ = connect(Settings().database_url)
    migrate(engine)
    print(f"schema version {CURRENT_SCHEMA_VERSION} applied")
