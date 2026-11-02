import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.config import Config as AppConfig

BACKEND_DIR = Path(__file__).resolve().parents[1]
GROUP_TABLES = {
    "container_groups",
    "container_group_assignments",
    "container_group_overrides",
}


def _alembic_config():
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_migration_creates_and_drops_grouping_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    uri = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setattr(AppConfig, "SQLALCHEMY_DATABASE_URI", uri)
    cfg = _alembic_config()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(uri)
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        assert GROUP_TABLES <= tables

        group_columns = {
            column["name"]
            for column in inspector.get_columns("container_groups")
        }
        assert {
            "name",
            "source",
            "host_key",
            "external_id",
            "external_parent_id",
            "active",
            "metadata_json",
        } <= group_columns

        assignment_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("container_group_assignments")
        }
        assert "uq_container_assignment_host_container" in assignment_uniques

        override_columns = {
            column["name"]
            for column in inspector.get_columns("container_group_overrides")
        }
        assert {"group_id", "host_key", "container_key", "note"} <= override_columns
    finally:
        engine.dispose()

    command.downgrade(cfg, "008_add_mac_address")

    engine = sa.create_engine(uri)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert not (GROUP_TABLES & tables)
    finally:
        engine.dispose()


def test_migration_adds_and_removes_reconciliation_exclusions(tmp_path, monkeypatch):
    db_path = tmp_path / "exclusions-migration.db"
    uri = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setattr(AppConfig, "SQLALCHEMY_DATABASE_URI", uri)
    cfg = _alembic_config()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(uri)
    try:
        inspector = sa.inspect(engine)
        assert "reconciliation_exclusions" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("reconciliation_exclusions")}
        assert {"id", "host_key", "container_key", "container_label", "reason",
                "created_at", "updated_at"} <= columns
        uniques = {item["name"] for item in inspector.get_unique_constraints("reconciliation_exclusions")}
        assert "uq_reconciliation_exclusion_host_container" in uniques
        indexes = {item["name"] for item in inspector.get_indexes("reconciliation_exclusions")}
        assert "ix_reconciliation_exclusion_host" in indexes
        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO reconciliation_exclusions "
                "(host_key, container_key, container_label, reason, created_at, updated_at) "
                "VALUES ('betty', 'old-backup', 'old-backup', 'retained', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            assert connection.execute(sa.text(
                "SELECT host_key, container_key FROM reconciliation_exclusions"
            )).all() == [("betty", "old-backup")]
    finally:
        engine.dispose()

    command.downgrade(cfg, "010_group_customisations")

    engine = sa.create_engine(uri)
    try:
        assert "reconciliation_exclusions" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_reconciliation_exclusion_migration_creates_the_missing_table(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/011_reconciliation_exclusions.py"
    spec = importlib.util.spec_from_file_location("migration_011", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        module.upgrade()  # Re-running the guarded migration is safe.
        inspector = sa.inspect(connection)
        assert "reconciliation_exclusions" in inspector.get_table_names()
        assert "uq_reconciliation_exclusion_host_container" in {
            item["name"] for item in inspector.get_unique_constraints("reconciliation_exclusions")}
        assert "ix_reconciliation_exclusion_host" in {
            item["name"] for item in inspector.get_indexes("reconciliation_exclusions")}
        connection.exec_driver_sql(
            "INSERT INTO reconciliation_exclusions "
            "(host_key, container_key, container_label, reason, created_at, updated_at) "
            "VALUES ('betty', 'old-backup', 'old-backup', 'retained', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        module.downgrade()
        assert "reconciliation_exclusions" not in sa.inspect(connection).get_table_names()
    engine.dispose()
