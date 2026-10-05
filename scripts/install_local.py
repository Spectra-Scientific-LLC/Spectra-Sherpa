#!/usr/bin/env python3
"""Choose optional local capabilities before invoking pip in this Python environment."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

EXTRAS = {
    "scp": "SpectroChemPy: EFA, MCR-ALS and SIMPLISMA (no additional file readers)",
    "hitran": "HITRAN/HAPI2 downloads (requires your API key and enabled network settings)",
    "nist": "NIST WebBook search and acquisition",
}


def ask_extras() -> list[str]:
    selected = []
    for extra, description in EXTRAS.items():
        while True:
            answer = input(f"Install {description}? [y/N] ").strip().lower()
            if answer in {"", "n", "no", "y", "yes"}:
                if answer in {"y", "yes"}:
                    selected.append(extra)
                break
            print("Please answer yes or no.")
    return selected


def install_requirement(args: argparse.Namespace, extras: list[str]) -> str:
    suffix = f"[{','.join(extras)}]" if extras else ""
    if args.version:
        return f"spectra-sherpa{suffix}=={args.version}"
    target = Path(args.source or args.wheel).expanduser().resolve()
    if args.source and not (target / "pyproject.toml").is_file():
        raise ValueError("--source must name the spectra-sherpa package directory containing pyproject.toml")
    if args.wheel and (not target.is_file() or target.suffix != ".whl"):
        raise ValueError("--wheel must name an existing .whl file")
    return f"{target}{suffix}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source", help="Exact qualified checkout's packages/spectra-sherpa directory")
    target.add_argument("--wheel", help="Exact built or downloaded wheel path")
    target.add_argument("--version", help="Exact version already published on the configured pip index")
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument("--extras", help="Comma-separated opt-ins: scp,hitran,nist; skips prompts")
    choices.add_argument("--base", action="store_true", help="Explicitly install without optional extras")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without installing")
    args = parser.parse_args(argv)
    if args.base:
        extras = []
    elif args.extras is not None:
        extras = list(dict.fromkeys(item.strip() for item in args.extras.split(",")))
        if any(extra not in EXTRAS for extra in extras):
            parser.error("--extras accepts only scp,hitran,nist; use --base for no extras")
    else:
        if not sys.stdin.isatty():
            parser.error("Non-interactive installation requires --extras or --base")
        try:
            extras = ask_extras()
        except (EOFError, KeyboardInterrupt):
            print("\nInstallation cancelled; pip was not started.", file=sys.stderr)
            return 130
    try:
        requirement = install_requirement(args, extras)
    except ValueError as exc:
        parser.error(str(exc))
    command = [sys.executable, "-m", "pip", "install", requirement]
    print(f"Install command: {shlex.join(command)}", flush=True)
    if args.dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
