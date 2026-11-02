"""Persistent, host-scoped reconciliation policy choices."""

from .base import db, BaseMixin


class ReconciliationExclusion(BaseMixin, db.Model):
    """An operator choice to suppress missing-inventory warnings.

    Keyed by normalised root host and stable Docker container name, never by a
    transient container ID. Exclusions do not delete inventory or Docker
    resources and never imply anything about container identity or grouping.
    """

    __tablename__ = "reconciliation_exclusions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    host_key = db.Column(db.Text, nullable=False)
    container_key = db.Column(db.Text, nullable=False)
    container_label = db.Column(db.Text)
    reason = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint(
            "host_key",
            "container_key",
            name="uq_reconciliation_exclusion_host_container",
        ),
        db.Index("ix_reconciliation_exclusion_host", "host_key"),
    )
