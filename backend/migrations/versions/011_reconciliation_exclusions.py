"""Persist host-scoped reconciliation exclusions.

Additive migration: no existing table or column is modified. ``db.create_all()``
may already have created the table and index, so both steps are guarded.
"""
import sqlalchemy as sa
from alembic import op

revision = "011_reconciliation_exclusions"
down_revision = "010_group_customisations"
branch_labels = None
depends_on = None


def _table_exists():
    return "reconciliation_exclusions" in sa.inspect(op.get_bind()).get_table_names()


def _index_exists():
    return any(
        index["name"] == "ix_reconciliation_exclusion_host"
        for index in sa.inspect(op.get_bind()).get_indexes("reconciliation_exclusions")
    )


def upgrade():
    if not _table_exists():
        op.create_table(
            "reconciliation_exclusions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("host_key", sa.Text(), nullable=False),
            sa.Column("container_key", sa.Text(), nullable=False),
            sa.Column("container_label", sa.Text()),
            sa.Column("reason", sa.Text()),
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
                "host_key",
                "container_key",
                name="uq_reconciliation_exclusion_host_container",
            ),
        )
    if not _index_exists():
        op.create_index(
            "ix_reconciliation_exclusion_host",
            "reconciliation_exclusions",
            ["host_key"],
        )


def downgrade():
    if _table_exists():
        op.drop_table("reconciliation_exclusions")
