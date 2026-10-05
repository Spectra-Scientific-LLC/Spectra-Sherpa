#!/usr/bin/env python3
"""Verify excluded modules stay out and approved HITRAN clients actually work.

This runs in CI against the real bundle. It is deliberately layout-agnostic:
Windows and Linux collect into ``SpectraSherpa/_internal`` while a macOS
``.app`` splits code into ``Contents/Frameworks`` and data into
``Contents/Resources``.

Usage:
    verify_optional_exclusions.py <bundle-root>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from optional_exclusions import HOSTED_SERVICE_MODULES, OPTIONAL_DISTRIBUTION_MODULES  # noqa: E402

# PyInstaller packs pure-Python modules into an archive embedded in the
# executable, so a file scan alone cannot see them. These are the backend
# entry points whose embedded archives are also inspected.
BACKEND_EXECUTABLES = ("SpectraSherpa", "SpectraSherpa.exe")


def _normalized(name: str) -> str:
    """PyPI name normalization, so hitran-api2 matches hitran_api2.dist-info."""
    return name.replace("-", "_").replace(".", "_").lower()


def _jedi_type_stubs_only(path: Path) -> bool:
    """Jedi vendors .pyi descriptions of packages it does not install/import."""
    parts = path.parts
    if not any(parts[i : i + 4] == ("jedi", "third_party", "typeshed", "stubs") for i in range(len(parts) - 3)):
        return False
    files = [item for item in path.rglob("*") if item.is_file()]
    return any(item.suffix == ".pyi" for item in files) and all(
        item.suffix == ".pyi" or item.name == "METADATA.toml" for item in files
    )


def find_violations(root: Path) -> list[str]:
    violations: list[str] = []
    module_names = set(OPTIONAL_DISTRIBUTION_MODULES.values())
    dist_prefixes = {_normalized(dist) for dist in OPTIONAL_DISTRIBUTION_MODULES}

    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        name = path.name

        if path.is_dir():
            if name in module_names and not _jedi_type_stubs_only(path):
                violations.append(f"module package present: {relative}")
                continue
            if name.endswith((".dist-info", ".egg-info")):
                # Strip the suffix before splitting: ".dist-info" contains a
                # hyphen of its own, so rsplit on the raw name would keep the
                # version and never match.
                base = name.removesuffix(".dist-info").removesuffix(".egg-info")
                stem = _normalized(base.rsplit("-", 1)[0] if "-" in base else base)
                if stem in dist_prefixes:
                    violations.append(f"distribution metadata present: {relative}")
            continue

        # A single-file module, or a compiled extension for one.
        stem = name.split(".", 1)[0]
        if stem in module_names and (name.endswith((".py", ".pyc", ".so", ".pyd", ".dylib")) or "." not in name):
            violations.append(f"module file present: {relative}")

    return sorted(violations)


def _forbidden(module: str) -> bool:
    top = module.split(".", 1)[0]
    if top in OPTIONAL_DISTRIBUTION_MODULES.values():
        return True
    return any(module == name or module.startswith(name + ".") for name in HOSTED_SERVICE_MODULES)


def embedded_module_violations(root: Path, archive_modules=None) -> list[str]:
    """Report forbidden modules packed inside the backend executable's archive."""
    if archive_modules is None:
        archive_modules = _embedded_archive_modules
    executables = [root / name for name in BACKEND_EXECUTABLES if (root / name).is_file()]
    if not executables:
        return ["backend executable not found; embedded modules were not inspected"]
    violations: list[str] = []
    for executable in executables:
        for module in archive_modules(executable):
            if _forbidden(module):
                violations.append(f"embedded module present: {executable.name}:{module}")
    return sorted(violations)


def _embedded_archive_modules(executable: Path) -> list[str]:
    # Imported here so the file-scan helpers stay usable without PyInstaller.
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(executable))
    modules: list[str] = []
    for name, entry in reader.toc.items():
        if entry[-1] in ("z", "Z"):
            modules.extend(reader.open_embedded_archive(name).toc)
    if not modules:
        raise SystemExit(f"no embedded module archive found in {executable}")
    return modules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, help="Built bundle root to scan")
    args = parser.parse_args()

    if not args.bundle.is_dir():
        raise SystemExit(f"bundle root not found: {args.bundle}")

    violations = find_violations(args.bundle) + embedded_module_violations(args.bundle)
    if violations:
        print("Excluded extras and hosted-service clients must not ship inside the desktop bundle:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        print(
            "\nThese stay available through pip extras "
            "(spectra-sherpa[scp,nist,postgres]); they are not included "
            "inside a signed installer.",
            file=sys.stderr,
        )
        return 1

    from verify_hitran_clients import verify

    verify(args.bundle)
    print(f"Desktop module boundary and offline HAPI/HAPI2 qualification passed: {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
