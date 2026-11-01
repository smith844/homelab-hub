"""add container groups, assignments and overrides

Revision ID: 009_container_groups
Revises: 008_add_mac_address
Create Date: 2026-11-01

Additive migration: no existing tables or columns are modified. The app's
``db.create_all()`` fallback may create these tables before the migration runs
(see migrations/env.py), so table creation and index creation are guarded.
"""
import sqlalchemy as sa
from alembic import op

from utils.migration_helpers import add_column_if_not_exists

# revision identifiers, used by Alembic.
revision = "009_container_groups"
down_revision = "008_add_mac_address"
branch_labels = None
depends_on = None


def _ensure_index(table_name, index_name, columns):
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def _drop_table_if_exists(table_name):
    inspector = sa.inspect(op.get_bind())
    if table_name in inspector.get_table_names():
        op.drop_table(table_name)


def upgrade():
    op.create_table(
        "container_groups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("host_key", sa.Text()),
        sa.Column("external_id", sa.Text()),
        sa.Column("external_parent_id", sa.Text()),
        sa.Column("icon", sa.Text()),
        sa.Column("color", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "source", "host_key", "external_id",
            name="uq_container_group_source_host_external",
        ),
        if_not_exists=True,
    )
    # Tolerate tables partially created by the db.create_all() fallback.
    add_column_if_not_exists("container_groups", sa.Column("name", sa.Text(), nullable=False, server_default=""))
    add_column_if_not_exists("container_groups", sa.Column("source", sa.Text(), nullable=False, server_default="manual"))
    add_column_if_not_exists("container_groups", sa.Column("host_key", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("external_id", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("external_parent_id", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("icon", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("color", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    add_column_if_not_exists("container_groups", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    add_column_if_not_exists("container_groups", sa.Column("metadata_json", sa.Text()))
    add_column_if_not_exists("container_groups", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    add_column_if_not_exists("container_groups", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    _ensure_index("container_groups", "ix_container_group_source_host", ["source", "host_key"])

    op.create_table(
        "container_group_assignments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("container_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_key", sa.Text(), nullable=False),
        sa.Column("host_label", sa.Text()),
        sa.Column("container_key", sa.Text(), nullable=False),
        sa.Column("container_label", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "host_key", "container_key",
            name="uq_container_assignment_host_container",
        ),
        if_not_exists=True,
    )
    add_column_if_not_exists("container_group_assignments", sa.Column("group_id", sa.Integer, nullable=False))
    add_column_if_not_exists("container_group_assignments", sa.Column("host_key", sa.Text(), nullable=False))
    add_column_if_not_exists("container_group_assignments", sa.Column("host_label", sa.Text()))
    add_column_if_not_exists("container_group_assignments", sa.Column("container_key", sa.Text(), nullable=False))
    add_column_if_not_exists("container_group_assignments", sa.Column("container_label", sa.Text()))
    add_column_if_not_exists("container_group_assignments", sa.Column("metadata_json", sa.Text()))
    add_column_if_not_exists("container_group_assignments", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    add_column_if_not_exists("container_group_assignments", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    _ensure_index("container_group_assignments", "ix_container_assignment_group", ["group_id"])

    op.create_table(
        "container_group_overrides",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("container_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("host_key", sa.Text(), nullable=False),
        sa.Column("host_label", sa.Text()),
        sa.Column("container_key", sa.Text(), nullable=False),
        sa.Column("container_label", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "host_key", "container_key",
            name="uq_container_override_host_container",
        ),
        if_not_exists=True,
    )
    add_column_if_not_exists("container_group_overrides", sa.Column("group_id", sa.Integer, nullable=True))
    add_column_if_not_exists("container_group_overrides", sa.Column("host_key", sa.Text(), nullable=False))
    add_column_if_not_exists("container_group_overrides", sa.Column("host_label", sa.Text()))
    add_column_if_not_exists("container_group_overrides", sa.Column("container_key", sa.Text(), nullable=False))
    add_column_if_not_exists("container_group_overrides", sa.Column("container_label", sa.Text()))
    add_column_if_not_exists("container_group_overrides", sa.Column("note", sa.Text()))
    add_column_if_not_exists("container_group_overrides", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    add_column_if_not_exists("container_group_overrides", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
    _ensure_index("container_group_overrides", "ix_container_override_group", ["group_id"])


def downgrade():
    _drop_table_if_exists("container_group_overrides")
    _drop_table_if_exists("container_group_assignments")
    _drop_table_if_exists("container_groups")
