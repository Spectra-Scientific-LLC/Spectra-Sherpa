"""Classify compatibility changes without workflow-level path filters (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.request
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


def current_draft(pr: dict) -> bool:
    """Return the PR's draft state now, not when the triggering event fired.

    A rerun replays the original payload. Without this, a verdict that failed
    while the PR was a draft stays failed on the same commit after the PR is
    marked ready, and blocks the merge although the ready run passed. Any API
    error fails the scope job, so the verdict still fails closed.
    """
    token, url = os.environ.get("GITHUB_TOKEN"), pr.get("url")
    if not token or not isinstance(url, str) or not url.startswith("https://api.github.com/repos/"):
        return bool(pr.get("draft", False))
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed https API origin
        draft = json.load(response)["draft"]
    if not isinstance(draft, bool):
        raise ValueError("Pull request draft state is unavailable")
    return draft


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    deferred = False
    needed = True
    if os.environ["EVENT_NAME"] == "pull_request":
        pr = event["pull_request"]
        deferred = current_draft(pr)
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
