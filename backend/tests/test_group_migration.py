"""Exercise the upgrade on a populated Phase 3 SQLite database."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import db


def test_phase3_upgrade_preserves_existing_groups(app, tmp_path):
    path = tmp_path / "phase3.db"
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{path}")
    db.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE container_groups DROP COLUMN customisations_json")
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        conn.execute("INSERT INTO alembic_version VALUES ('009_container_groups')")
        conn.execute("INSERT INTO container_groups (name, source, host_key, external_id, icon, sort_order, active, created_at, updated_at) VALUES ('Media', 'folderview', 'betty', 'media', '🎬', 42, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}
    for _ in range(2):
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name, icon, sort_order, active, customisations_json FROM container_groups").fetchone() == ("Media", "🎬", 42, 0, None)
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == '010_group_customisations'


@pytest.fixture()
def migration_010():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/010_group_customisations.py"
    spec = importlib.util.spec_from_file_location("migration_010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_customisations_column_is_preserved(migration_010, monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE container_groups (id INTEGER PRIMARY KEY, customisations_json TEXT)"
        )
        connection.execute(
            sa.text("INSERT INTO container_groups VALUES (1, :choices)"),
            {"choices": '["icon", "active"]'},
        )
        monkeypatch.setattr(migration_010, "op", Operations(MigrationContext.configure(connection)))
        # Exercise upgrade itself twice, not an Alembic run already at head.
        migration_010.upgrade()
        migration_010.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM container_groups").all() == [
            (1, '["icon", "active"]')
        ]
        assert [column["name"] for column in sa.inspect(connection).get_columns("container_groups")] == [
            "id", "customisations_json"
        ]
    engine.dispose()


def test_unexpected_column_addition_failure_propagates(migration_010, monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE container_groups (id INTEGER PRIMARY KEY)")
        connection.commit()
        monkeypatch.setattr(migration_010, "op", Operations(MigrationContext.configure(connection)))
        # Inspection works, but SQLite rejects DDL. The previous broad exception
        # handler swallowed this real OperationalError as if the column existed.
        connection.exec_driver_sql("PRAGMA query_only = ON")
        with pytest.raises(sa.exc.OperationalError, match="readonly"):
            migration_010.upgrade()
        assert [column["name"] for column in sa.inspect(connection).get_columns("container_groups")] == ["id"]
    engine.dispose()
