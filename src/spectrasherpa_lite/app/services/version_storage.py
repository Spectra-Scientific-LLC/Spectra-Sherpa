from __future__ import annotations

import hashlib
import json
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.experiments import experiment_dir


class VersionStorage(ABC):
    """Abstract storage interface for experiment versions."""

    def __init__(self, experiment_id: int) -> None:
        self.experiment_id = experiment_id
        self.base_dir = experiment_dir(experiment_id)

    @abstractmethod
    def create_version(
        self,
        version_name: str,
        files: Iterable[Path],
        description: str | None = None,
        parent_version: str | None = None,
        base_path: Path | None = None,
    ) -> Path:
        raise NotImplementedError

    @abstractmethod
    def restore_version(self, version_name: str, overwrite: bool = False) -> int:
        raise NotImplementedError


class ContentAddressableStorage(VersionStorage):
    """Content-addressable storage implementation for experiment versions."""

    def __init__(self, experiment_id: int) -> None:
        super().__init__(experiment_id)
        self.objects_dir = self.base_dir / "objects"
        self.versions_dir = self.base_dir / "versions"

    def store_file(self, file_path: Path) -> str:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        file_hash = self._hash_file(file_path)
        target_path = self.objects_dir / file_hash
        if not target_path.exists():
            shutil.copyfile(file_path, target_path)
        return file_hash

    def create_version(
        self,
        version_name: str,
        files: Iterable[Path],
        description: str | None = None,
        parent_version: str | None = None,
        base_path: Path | None = None,
    ) -> Path:
        version_dir = self.versions_dir / version_name
        version_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = version_dir / "manifest.json"

        base_path = base_path or self.base_dir

        manifest = {
            "version_name": version_name,
            "parent_version": parent_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "description": description,
            "files": {},
        }

        for file_path in files:
            file_path = file_path.resolve()
            relative_path = file_path.relative_to(base_path).as_posix()
            file_hash = self.store_file(file_path)
            manifest["files"][relative_path] = {
                "hash": file_hash,
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(
                    file_path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }

        manifest_path.write_text(json.dumps(manifest, indent=2))
        return manifest_path

    def load_manifest(self, version_name: str) -> dict:
        manifest_path = self.versions_dir / version_name / "manifest.json"
        return json.loads(manifest_path.read_text())

    def restore_version(self, version_name: str, overwrite: bool = False) -> int:
        manifest = self.load_manifest(version_name)
        restored = 0

        for relative_path, entry in manifest.get("files", {}).items():
            target_path = (self.base_dir / relative_path).resolve()
            if not target_path.is_relative_to(self.base_dir):
                raise ValueError(f"Invalid path in manifest: {relative_path}")
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"File already exists: {relative_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            object_path = self.objects_dir / entry["hash"]
            target_path.write_bytes(object_path.read_bytes())
            restored += 1

        return restored

    def get_all_referenced_hashes(self) -> set[str]:
        hashes: set[str] = set()
        for manifest_path in self.versions_dir.rglob("manifest.json"):
            manifest = json.loads(manifest_path.read_text())
            for entry in manifest.get("files", {}).values():
                if "hash" in entry:
                    hashes.add(entry["hash"])
        return hashes

    def find_orphaned_objects(self) -> list[Path]:
        referenced = self.get_all_referenced_hashes()
        if not self.objects_dir.exists():
            return []
        return [
            path
            for path in self.objects_dir.iterdir()
            if path.is_file() and path.name not in referenced
        ]

    def garbage_collect(self, grace_period_days: int = 7) -> list[Path]:
        if grace_period_days < 0:
            raise ValueError("grace_period_days must be non-negative")

        cutoff = datetime.now(timezone.utc).timestamp() - grace_period_days * 86400
        deleted: list[Path] = []
        for object_path in self.find_orphaned_objects():
            if object_path.stat().st_mtime <= cutoff:
                object_path.unlink()
                deleted.append(object_path)
        return deleted

    def _hash_file(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
