from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig

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
