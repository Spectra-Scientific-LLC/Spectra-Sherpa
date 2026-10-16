"""Require successful public-main workflow runs for an exact release commit.

Uses workflow identities, not arbitrary commit-status names. PR runs (including
forks) cannot substitute for the public-main push qualification. The latest run
and its current attempt must be complete and successful. API errors fail closed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request

WORKFLOWS = ("ci.yml", "codeql.yml", "saved-model-compat.yml")


def validate_run(run: dict, repository: str, sha: str, workflow: str) -> None:
    expected = {
        "head_sha": sha,
        "head_branch": "main",
        "event": "push",
        "path": f".github/workflows/{workflow}",
        "status": "completed",
        "conclusion": "success",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{workflow}: latest exact-commit push run is not successful")
    if run.get("head_repository", {}).get("full_name") != repository:
        raise ValueError(f"{workflow}: run originates from another repository")


def verify(repository: str, sha: str, get_json) -> list[dict]:
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repository) is None or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("Invalid repository or commit")
    evidence = []
    for workflow in WORKFLOWS:
        query = urllib.parse.urlencode({"head_sha": sha, "branch": "main", "event": "push", "per_page": 100})
        runs = get_json(f"/repos/{repository}/actions/workflows/{workflow}/runs?{query}")["workflow_runs"]
        if not runs:
            raise ValueError(f"{workflow}: no public-main qualification for {sha}")
        # GitHub returns newest runs first; explicit ID ordering avoids assuming that.
        latest = max(runs, key=lambda run: run["id"])
        # Read again by ID to observe the current attempt/status after a rerun.
        run = get_json(f"/repos/{repository}/actions/runs/{latest['id']}")
        validate_run(run, repository, sha, workflow)
        evidence.append({"workflow": workflow, "run_id": run["id"], "attempt": run["run_attempt"], "sha": sha})
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    def get_json(path: str):
        request = urllib.request.Request(
            "https://api.github.com" + path,
            headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API origin
            return json.load(response)

    print(json.dumps(verify(args.repository, args.sha, get_json), indent=2))


if __name__ == "__main__":
    main()
