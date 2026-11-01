"""Flask CLI maintenance commands.

Container grouping is imported through the CLI rather than an unauthenticated
HTTP endpoint in this phase. Operators run it from the server/container console:

    flask --app wsgi container-groups import-folderview --host Betty --dry-run
    flask --app wsgi container-groups import-folderview --host Betty

The importer only reads the FolderView Plus configuration; it never writes to it.
"""

import json
import os

import click
from flask.cli import with_appcontext

from .models import ContainerGroup, db
from .services.folderview_import import FolderviewImportError, import_folderview_file

DEFAULT_PATH_ENV = "FOLDERVIEW_CONFIG_PATH"


def register_cli(app):
    @app.cli.group("container-groups")
    def container_groups():
        """Container grouping maintenance commands."""

    @container_groups.command("import-folderview")
    @click.option(
        "--host",
        "host_key",
        required=True,
        help="HomeLab-Hub host name (Hardware.name or VM.name) that owns these containers.",
    )
    @click.option(
        "--host-label",
        default=None,
        help="Display label for the host; defaults to --host.",
    )
    @click.option(
        "--file",
        "path",
        default=None,
        help=f"Path to FolderView Plus docker.json (default: ${DEFAULT_PATH_ENV}).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Report the proposed changes without writing to the database.",
    )
    @with_appcontext
    def import_folderview(host_key, host_label, path, dry_run):
        """Import an Unraid FolderView Plus configuration (read-only)."""
        resolved_path = path or os.environ.get(DEFAULT_PATH_ENV)
        if not resolved_path:
            raise click.ClickException(
                f"Provide --file or set the {DEFAULT_PATH_ENV} environment variable"
            )
        try:
            report = import_folderview_file(
                resolved_path,
                host_key=host_key,
                host_label=host_label,
                dry_run=dry_run,
            )
        except FolderviewImportError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(json.dumps(report, indent=2, sort_keys=True))

    @container_groups.command("list")
    @with_appcontext
    def list_groups():
        """List stored container groups and their membership counts."""
        rows = []
        for group in db.session.query(ContainerGroup).order_by(
            ContainerGroup.source, ContainerGroup.name
        ).all():
            rows.append(
                {
                    "name": group.name,
                    "source": group.source,
                    "host_key": group.host_key,
                    "external_id": group.external_id,
                    "active": bool(group.active),
                    "assignments": len(group.assignments),
                    "overrides": len(group.overrides),
                }
            )
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
