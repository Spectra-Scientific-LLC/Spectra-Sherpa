"""Classify compatibility changes without workflow-level path filters (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def matches(path: str, pattern: str) -> bool:
    regex = "".join(
        ".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
        for token in re.findall(r"\*\*|\*|[^*]+", pattern)
    )
    return re.fullmatch(regex, path) is not None


def required(paths: list[str], patterns: list[str], prefix: str) -> bool:
    return any(
        path == ".github/workflows/saved-model-compat.yml"
        or any(matches(path, prefix + pattern) for pattern in patterns)
        for path in paths
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    deferred = False
    needed = True
    if os.environ["EVENT_NAME"] == "pull_request":
        pr = event["pull_request"]
        deferred = pr.get("draft", False)
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        if any(re.fullmatch(r"[0-9a-f]{40}", sha) is None for sha in (base, head)):
            raise ValueError("Invalid PR commit identities")
        # Compare the PR contribution, including deletions and both sides of renames.
        raw = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"])
        paths = raw.decode().split("\0")[:-1]
        patterns = json.loads(Path(__file__).with_name("saved_model_compat_paths.json").read_text())
        needed = required(paths, patterns, args.prefix) and not deferred
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"required={str(needed).lower()}\ndeferred={str(deferred).lower()}\n")


if __name__ == "__main__":
    main()
