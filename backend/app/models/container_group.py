from .base import db, BaseMixin


class ContainerGroup(BaseMixin, db.Model):
    """A user-visible container group.

    Imported FolderView Plus folders and manually created groups share this
    table. ``external_id``/``host_key`` preserve the FolderView folder id and
    host scope; ``metadata_json`` keeps raw source metadata (regex rules,
    settings, member identities, ...) without interpreting it.
    """

    __tablename__ = "container_groups"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=False)
    source = db.Column(db.Text, nullable=False, default="manual")  # manual | folderview
    host_key = db.Column(db.Text)  # normalised host identity (imported groups)
    external_id = db.Column(db.Text)  # FolderView folder id
    external_parent_id = db.Column(db.Text)  # FolderView parentId (preserved)
    icon = db.Column(db.Text)
    color = db.Column(db.Text)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    metadata_json = db.Column(db.Text)

    assignments = db.relationship(
        "ContainerGroupAssignment",
        back_populates="group",
        lazy="select",
        cascade="all, delete-orphan",
    )
    overrides = db.relationship(
        "ContainerGroupOverride",
        back_populates="group",
        lazy="select",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "source", "host_key", "external_id",
            name="uq_container_group_source_host_external",
        ),
        db.Index("ix_container_group_source_host", "source", "host_key"),
    )


class ContainerGroupAssignment(BaseMixin, db.Model):
    """Imported membership: one row per host-scoped container identity.

    The row is keyed by normalised ``(host_key, container_key)`` so it survives
    container recreation and database id churn. Manual override rows live in
    ``ContainerGroupOverride`` and always take precedence.
    """

    __tablename__ = "container_group_assignments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(
        db.Integer,
        db.ForeignKey("container_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    host_key = db.Column(db.Text, nullable=False)
    host_label = db.Column(db.Text)
    container_key = db.Column(db.Text, nullable=False)
    container_label = db.Column(db.Text)
    metadata_json = db.Column(db.Text)

    group = db.relationship("ContainerGroup", back_populates="assignments")

    __table_args__ = (
        db.UniqueConstraint(
            "host_key", "container_key",
            name="uq_container_assignment_host_container",
        ),
        db.Index("ix_container_assignment_group", "group_id"),
    )


class ContainerGroupOverride(BaseMixin, db.Model):
    """Manual grouping choice; never touched by the importer.

    ``group_id = NULL`` is an explicit "keep this container ungrouped" choice
    that also wins over imported assignments.
    """

    __tablename__ = "container_group_overrides"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(
        db.Integer,
        db.ForeignKey("container_groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    host_key = db.Column(db.Text, nullable=False)
    host_label = db.Column(db.Text)
    container_key = db.Column(db.Text, nullable=False)
    container_label = db.Column(db.Text)
    note = db.Column(db.Text)

    group = db.relationship("ContainerGroup", back_populates="overrides")

    __table_args__ = (
        db.UniqueConstraint(
            "host_key", "container_key",
            name="uq_container_override_host_container",
        ),
        db.Index("ix_container_override_group", "group_id"),
    )
