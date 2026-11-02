"""Track local presentation choices separately from FolderView source metadata."""
import sqlalchemy as sa
from alembic import op

revision = "010_group_customisations"
down_revision = "009_container_groups"
branch_labels = None
depends_on = None


def upgrade():
    # create_app() may already have created the current model's column on a new
    # database. Skip only that known case; unexpected inspection/DDL errors must
    # abort the migration rather than falsely advancing the Alembic revision.
    columns = sa.inspect(op.get_bind()).get_columns("container_groups")
    if not any(column["name"] == "customisations_json" for column in columns):
        op.add_column("container_groups", sa.Column("customisations_json", sa.Text()))


def downgrade():
    op.drop_column("container_groups", "customisations_json")
