"""SQLite migration guard tests; real frozen-MySQL upgrade lives in integration."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Column, Index, Integer, MetaData, Table, event, inspect, select
from sqlalchemy.orm import Session

from backend.app import create_app
from backend.config import Settings
from backend.db import Base, LabRecord, SchemaVersion, User, connect
from backend.migrate import CURRENT_SCHEMA_VERSION, V1_TABLES, V2_TABLES, assert_current_schema, migrate
from backend.runtime import Runtime


@pytest.fixture
def engine():
    value, _ = connect("sqlite+pysqlite:///:memory:")
    yield value
    value.dispose()


def legacy(engine):
    # Guard unit fixture only; real integration uses independently frozen v1 SQL.
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in V1_TABLES])
    with Session(engine) as session, session.begin():
        session.add(SchemaVersion(version=1))
        session.add(User(id="retained", username="retained", password_hash="synthetic-unchanged"))


def versions(engine):
    with engine.connect() as connection:
        return set(connection.execute(select(SchemaVersion.version)).scalars())


def test_initial_and_repeat_migration_validate_current_schema(engine):
    assert CURRENT_SCHEMA_VERSION == 2
    with pytest.raises(RuntimeError):
        assert_current_schema(engine)
    migrate(engine)
    assert versions(engine) == {1, 2}
    assert_current_schema(engine)
    migrate(engine)
    assert set(inspect(engine).get_table_names()) == set(V1_TABLES + V2_TABLES)


def test_legacy_upgrade_preserves_rows_and_prior_version(engine):
    legacy(engine)
    with pytest.raises(RuntimeError):
        assert_current_schema(engine)
    for _ in range(2):
        migrate(engine)
        with Session(engine) as session:
            assert session.get(User, "retained").password_hash == "synthetic-unchanged"
        assert versions(engine) == {1, 2}
        assert_current_schema(engine)


@pytest.mark.parametrize("markers", [set(), {2}, {3}, {1, 3}, {1, 2, 99}])
def test_unknown_or_gapped_history_is_rejected_before_any_schema_change(engine, markers):
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["schema_version"]])
    with Session(engine) as session, session.begin():
        session.add_all(SchemaVersion(version=value) for value in markers)
    before = set(inspect(engine).get_table_names())
    for operation in (migrate, assert_current_schema):
        with pytest.raises(RuntimeError):
            operation(engine)
        assert versions(engine) == markers
        assert set(inspect(engine).get_table_names()) == before


def test_unversioned_or_incomplete_schema_is_not_overwritten(engine):
    Base.metadata.tables["users"].create(engine)
    with pytest.raises(RuntimeError, match="no version"):
        migrate(engine)
    assert set(inspect(engine).get_table_names()) == {"users"}


def test_partial_v2_table_and_index_creation_is_resumable(engine):
    legacy(engine)

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("CREATE TABLE lab_records"):
            raise RuntimeError("synthetic crash after table DDL before indexes")

    event.listen(engine, "after_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="synthetic crash"):
            migrate(engine)
    finally:
        event.remove(engine, "after_cursor_execute", interrupt)
    assert "lab_records" in inspect(engine).get_table_names()
    assert not inspect(engine).get_indexes("lab_records")
    assert versions(engine) == {1}
    with pytest.raises(RuntimeError):
        assert_current_schema(engine)
    migrate(engine)
    assert_current_schema(engine)
    assert versions(engine) == {1, 2}


def test_wrong_shape_partial_table_rejected_before_second_table_creation(engine):
    legacy(engine)
    Table("lab_records", MetaData(), Column("id", Integer, primary_key=True)).create(engine)
    with pytest.raises(RuntimeError, match="columns differ"):
        migrate(engine)
    assert "lab_kafka_messages" not in inspect(engine).get_table_names()
    assert versions(engine) == {1}


@pytest.mark.parametrize("extra", ["unique", "check"])
def test_extra_constraints_cannot_silently_change_allowed_lab_data(engine, extra):
    legacy(engine)
    metadata = MetaData()
    table = LabRecord.__table__.to_metadata(metadata)
    if extra == "unique":
        Index("unexpected_name_unique", table.c.name, unique=True)
    else:
        table.append_constraint(CheckConstraint("value <> ''", name="unexpected_nonempty_value"))
    table.create(engine)
    with pytest.raises(RuntimeError, match="constraint"):
        migrate(engine)
    assert versions(engine) == {1}
    assert "lab_kafka_messages" not in inspect(engine).get_table_names()


def test_v2_marker_does_not_hide_missing_indexes_or_tables(engine):
    migrate(engine)
    index = next(iter(LabRecord.__table__.indexes))
    index.drop(engine)
    for operation in (migrate, assert_current_schema):
        with pytest.raises(RuntimeError, match="index differs"):
            operation(engine)
    assert versions(engine) == {1, 2}
    # Only a synthetic unit-test database is modified; production has no down migration.
    LabRecord.__table__.drop(engine)
    with pytest.raises(RuntimeError, match="objects are missing"):
        assert_current_schema(engine)


def test_legacy_missing_index_is_not_repaired_by_teaching_migration(engine):
    legacy(engine)
    index = next(iter(Base.metadata.tables["sessions"].indexes))
    index.drop(engine)
    with pytest.raises(RuntimeError, match="index differs"):
        migrate(engine)
    assert not set(V2_TABLES) & set(inspect(engine).get_table_names())


def test_readiness_refuses_v1_and_future_markers_without_mutating_schema():
    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:"))
    try:
        legacy(runtime.engine)
        with TestClient(create_app(runtime)) as client:
            response = client.get("/readyz")
            assert response.status_code == 503 and response.json()["dependencies"]["sqlite"] == "down"
            assert versions(runtime.engine) == {1}
            assert set(inspect(runtime.engine).get_table_names()) == set(V1_TABLES)
            migrate(runtime.engine)
            assert client.get("/readyz").status_code == 200
            with runtime.sessions() as session, session.begin():
                session.add(SchemaVersion(version=99))
            assert client.get("/readyz").status_code == 503
            assert versions(runtime.engine) == {1, 2, 99}
    finally:
        runtime.engine.dispose()


def test_worker_refuses_legacy_schema_before_initializing_topics(engine, monkeypatch):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock

    from backend import worker

    legacy(engine)
    bus = Mock()
    runtime = SimpleNamespace(settings=SimpleNamespace(mode="production"), engine=engine, bus=bus)
    monkeypatch.setattr(worker, "Runtime", lambda: runtime)
    monkeypatch.setattr(sys, "argv", ["worker"])
    with pytest.raises(RuntimeError, match="version 2 required"):
        worker.main()
    bus.ensure_topics.assert_not_called()


@pytest.mark.parametrize("collation,accepted", [("utf8mb4_bin", True), ("utf8mb4_general_ci", False)])
def test_mysql_explicit_binary_collation_allows_equivalent_table_default(engine, collation, accepted):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from sqlalchemy.dialects import mysql

    from backend.migrate import _validate_table

    legacy(engine)
    # Reflection double ONLY: real MySQL reflection remains integration-owned.
    inspector = Mock(wraps=inspect(engine))
    inspector.bind = SimpleNamespace(dialect=mysql.dialect())
    inspector.get_table_options.return_value = {"mysql_collate": collation}
    if accepted:
        _validate_table(inspector, "tasks")
    else:
        with pytest.raises(RuntimeError, match="column definition differs"):
            _validate_table(inspector, "tasks")
