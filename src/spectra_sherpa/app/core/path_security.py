"""Filesystem path validation helpers for user-facing file operations."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _display_path(value: str | Path) -> str:
    text = str(value)
    return text if len(text) <= 240 else text[:237] + "..."


def _resolve_existing_path(value: str | Path, *, label: str) -> Path:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} path is required.")
    if "\x00" in text:
        raise ValueError(f"{label} path contains an invalid NUL byte.")

    try:
        return Path(text).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} path does not exist: {_display_path(value)}") from exc


def _assert_under_root(path: Path, root: Path, *, label: str) -> None:
    allowed_root = root.expanduser().resolve(strict=False)
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"{label} path must be under the data directory ({allowed_root}). Got: {path}") from exc


def _active_multi_user_data_root() -> Path | None:
    from spectra_sherpa.app.core.mode_policy import is_multi_user

    if not is_multi_user():
        return None

    from spectra_sherpa.app.core.config import settings

    return Path(settings.data_dir)


def resolve_existing_file_path(
    value: str | Path,
    *,
    label: str,
    suffixes: Iterable[str] | None = None,
    restrict_to_data_dir_in_multi_user: bool = False,
) -> Path:
    """Resolve a user-supplied existing file path and enforce app boundaries.

    OSS/local mode may intentionally open arbitrary local files selected by the
    user.  Multi-user deployments must keep user-selected file operations under
    ``settings.data_dir`` so API payloads cannot escape into server paths.
    """

    resolved = _resolve_existing_path(value, label=label)
    if not resolved.is_file():
        raise ValueError(f"{label} path is not a file: {resolved}")

    allowed_suffixes = {suffix.lower() for suffix in suffixes or ()}
    if allowed_suffixes and resolved.suffix.lower() not in allowed_suffixes:
        expected = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Unsupported {label} extension: {resolved.suffix or '<none>'}; expected one of {expected}")

    if restrict_to_data_dir_in_multi_user:
        data_root = _active_multi_user_data_root()
        if data_root is not None:
            _assert_under_root(resolved, data_root, label=label)

    return resolved


def resolve_existing_directory_path(
    value: str | Path,
    *,
    label: str,
    restrict_to_data_dir_in_multi_user: bool = False,
) -> Path:
    """Resolve a user-supplied existing directory path and enforce boundaries."""

    resolved = _resolve_existing_path(value, label=label)
    if not resolved.is_dir():
        raise ValueError(f"{label} path is not a directory: {resolved}")

    if restrict_to_data_dir_in_multi_user:
        data_root = _active_multi_user_data_root()
        if data_root is not None:
            _assert_under_root(resolved, data_root, label=label)

    return resolved
