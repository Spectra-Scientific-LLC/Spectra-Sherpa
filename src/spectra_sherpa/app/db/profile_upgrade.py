"""Pre-upgrade custody for local SQLite profiles.

Called inside the shared BEGIN IMMEDIATE migration transaction, before any DDL.
Only the database is mutated by the schema migration chain. Source data, model
artifacts and exports stay in their existing canonical profile directories.
Snapshots are retained until the operator explicitly removes them; startup never
prunes the last (or any) recovery copy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from spectra_sherpa import __version__


class ProfileUpgradeError(RuntimeError):
    """Actionable startup refusal consumed by CLI and the desktop handshake."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_database(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ProfileUpgradeError(
                "backup_invalid", "SQLite integrity verification failed; keep the original profile."
            )


def restore_database_copy(snapshot: Path, destination: Path) -> Path:
    """Verify and restore to a NEW path; never overwrite a profile database."""
    snapshot = snapshot.resolve()
    destination = destination.absolute()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    source = snapshot / "database.sqlite3"
    if manifest.get("format") != 1 or _digest(source) != manifest["database"]["sha256"]:
        raise ProfileUpgradeError("backup_invalid", "Backup manifest or digest does not match; do not restore it.")
    _verify_database(source)
    # Exclusive creation prevents an accidental replacement, including a symlink.
    created = False
    try:
        with destination.open("xb") as stream:
            created = True
            with source.open("rb") as incoming:
                shutil.copyfileobj(incoming, stream)
        _verify_database(destination.resolve())
        if _digest(destination) != manifest["database"]["sha256"]:
            raise ProfileUpgradeError("restore_invalid", "Restored copy digest differs from its verified backup.")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def prepare_profile_upgrade(connection: Connection, scripts: ScriptDirectory) -> Path | None:
    """Check compatibility/space and retain a verified consistent pre-DDL backup.

    The caller holds SQLite's reserved write lock for the entire migration.
    A separate read-only connection is essential: backing up from the connection
    with an active write transaction can block indefinitely. SQLite's backup API
    includes committed pages still residing in WAL.
    """
    database_name = connection.engine.url.database
    if connection.dialect.name != "sqlite" or not database_name or database_name == ":memory:":
        return None
    database = Path(database_name).resolve()
    tables = inspect(connection).get_table_names()
    revisions = (
        list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
        if "alembic_version" in tables
        else []
    )
    heads = scripts.get_heads()
    known = {revision.revision for revision in scripts.walk_revisions()}
    if any(revision not in known for revision in revisions):
        raise ProfileUpgradeError(
            "schema_incompatible",
            "This profile has an unknown or newer database revision. Use the matching or newer app; "
            "do not downgrade or delete the database.",
        )
    if set(revisions) == set(heads):
        return None
    page_count = connection.exec_driver_sql("PRAGMA page_count").scalar_one()
    page_size = connection.exec_driver_sql("PRAGMA page_size").scalar_one()
    required = page_count * page_size * 3 + 16 * 1024 * 1024
    available = shutil.disk_usage(database.parent).free
    if available < required:
        raise ProfileUpgradeError(
            "insufficient_space",
            f"Need at least {required} free bytes before upgrading this profile; {available} available. "
            "Free disk space and retry. No schema changes were made.",
        )
    if not tables:
        return None  # No user database exists to recover; bootstrap is still atomic.

    root = database.parent / ".profile-upgrades"
    root.mkdir(mode=0o700, exist_ok=True)
    snapshot = root / uuid4().hex
    snapshot.mkdir(mode=0o700)
    target = snapshot / "database.sqlite3"
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
        _verify_database(target)
        manifest = {
            "format": 1,
            "application_version": __version__,
            "source_database": database.name,
            "source_revisions": revisions,
            "target_revisions": heads,
            "database": {"file": target.name, "size": target.stat().st_size, "sha256": _digest(target)},
            "scope": "SQLite database only; migrations do not rewrite external data/model/export files",
            "retention": "Keep until explicitly removed by the operator; no automatic pruning",
        }
        (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Exercise the actual restore path before allowing any database mutation.
        with tempfile.TemporaryDirectory(prefix="restore-check-", dir=root) as temporary:
            restore_database_copy(snapshot, Path(temporary) / "verified.sqlite3")
        return snapshot
    except Exception as exc:
        raise ProfileUpgradeError(
            "backup_failed",
            f"Cannot verify a recovery snapshot at {snapshot}. No schema changes were made. "
            "Check free space and directory permissions, then retry.",
        ) from exc


def main() -> None:
    """Copy-only recovery entry point for pip users and support procedures."""
    import argparse

    parser = argparse.ArgumentParser(description="Verify and restore a Sherpa database backup to a NEW file")
    parser.add_argument("snapshot", type=Path, help="Directory containing manifest.json and database.sqlite3")
    parser.add_argument("destination", type=Path, help="New database path; existing files are never overwritten")
    args = parser.parse_args()
    try:
        restored = restore_database_copy(args.snapshot, args.destination)
    except (OSError, ValueError, KeyError, sqlite3.Error, ProfileUpgradeError) as exc:
        parser.exit(1, f"Recovery refused: {exc}\n")
    print(f"Verified database copy: {restored}")


if __name__ == "__main__":
    main()
