"""Filesystem path validation helpers for user-facing file operations."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def _clean_path_text(value: str | Path, *, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} path is required.")
    if "\x00" in text:
        raise ValueError(f"{label} path contains an invalid NUL byte.")
    return text


def _display_path(value: str | Path) -> str:
    text = str(value)
    return text if len(text) <= 240 else text[:237] + "..."


def _resolve_existing_path(value: str | Path, *, label: str) -> Path:
    text = _clean_path_text(value, label=label)

    try:
        # Intended only for trusted local-file workflows. API-exposed callers
        # pass restrict_to_data_dir_in_multi_user=True so multi-user deployments
        # are routed through _resolve_existing_path_under_root before strict
        # filesystem access.
        # Local/desktop mode intentionally accepts user-selected filesystem
        # paths. Multi-user API call sites set
        # ``restrict_to_data_dir_in_multi_user=True`` and therefore use the
        # containment-enforced resolver below.
        # lgtm[py/path-injection]
        return Path(text).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} path does not exist: {_display_path(value)}") from exc


def _resolve_existing_path_under_root(value: str | Path, root: Path, *, label: str) -> Path:
    text = _clean_path_text(value, label=label)
    allowed_root = root.expanduser().resolve(strict=False)
    allowed_text = os.path.normcase(os.path.normpath(str(allowed_root)))

    # The raw value is inspected only to decide absolute-vs-relative form;
    # filesystem access happens after commonpath + resolved containment checks.
    # lgtm[py/path-injection]
    raw_path = Path(text).expanduser()
    if raw_path.is_absolute():
        candidate_text = os.path.normcase(os.path.normpath(str(raw_path)))
    else:
        candidate_text = os.path.normcase(os.path.normpath(os.path.join(allowed_text, str(raw_path))))

    try:
        common = os.path.commonpath([allowed_text, candidate_text])
    except ValueError as exc:
        raise ValueError(f"{label} path must be under the data directory ({allowed_root}). Got: {text}") from exc
    if common != allowed_text:
        raise ValueError(f"{label} path must be under the data directory ({allowed_root}). Got: {text}")

    candidate = Path(candidate_text)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} path does not exist: {_display_path(value)}") from exc
    _assert_under_root(resolved, allowed_root, label=label)
    return resolved


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
    user. Multi-user deployments must keep user-selected file operations under
    ``settings.data_dir`` so API payloads cannot escape into server paths.
    """

    if restrict_to_data_dir_in_multi_user:
        data_root = _active_multi_user_data_root()
        if data_root is not None:
            resolved = _resolve_existing_path_under_root(value, data_root, label=label)
        else:
            resolved = _resolve_existing_path(value, label=label)
    else:
        resolved = _resolve_existing_path(value, label=label)

    if not resolved.is_file():
        raise ValueError(f"{label} path is not a file: {resolved}")

    allowed_suffixes = {suffix.lower() for suffix in suffixes or ()}
    if allowed_suffixes and resolved.suffix.lower() not in allowed_suffixes:
        expected = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Unsupported {label} extension: {resolved.suffix or '<none>'}; expected one of {expected}")
    return resolved


def resolve_existing_directory_path(
    value: str | Path,
    *,
    label: str,
    restrict_to_data_dir_in_multi_user: bool = False,
) -> Path:
    """Resolve a user-supplied existing directory path and enforce boundaries."""

    if restrict_to_data_dir_in_multi_user:
        data_root = _active_multi_user_data_root()
        if data_root is not None:
            resolved = _resolve_existing_path_under_root(value, data_root, label=label)
        else:
            resolved = _resolve_existing_path(value, label=label)
    else:
        resolved = _resolve_existing_path(value, label=label)

    if not resolved.is_dir():
        raise ValueError(f"{label} path is not a directory: {resolved}")

    return resolved
