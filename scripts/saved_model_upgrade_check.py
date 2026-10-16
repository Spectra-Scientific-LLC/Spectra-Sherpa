#!/usr/bin/env python3
"""Check that models saved by a published release still apply after upgrade.

A user who upgrades keeps their data directory. This check reproduces that:

1. Start the *reference* release (installed separately, normally from PyPI)
   on an empty data directory, import bundled reference data, and fit one
   model per starter template through the ordinary REST API.
2. Stop it and start the *candidate* code on the same data directory, so the
   candidate's migrations run against the old database.
3. For every saved model, run the same compatibility preflight and batch
   application the Runs > Batch page uses.

Every refusal must either be listed in the baseline file as a known, reviewed
incompatibility or the check fails. A listed incompatibility that now applies
also fails, so the list cannot go stale. The script uses only the standard
library so it can drive any two installed versions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Bundled sources only: the check must run offline and in public CI.
SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "name": "iris-classification",
        "reference": {"source": "sklearn", "name": "iris"},
        "stage": "raw",
        "target": "target",
        "target_type": "categorical",
        "templates": (
            "classification_plsda",
            "knn_classification",
            "simca_classification",
            "pca",
            "ica_decomposition",
        ),
    },
    {
        # No bundled reference is both spectral and categorical; iris has a
        # label axis, which exercises a different application path.
        "name": "spectral-classification",
        "upload_csv": "spectral_classes",
        "stage": "raw",
        "target": "class",
        "target_type": "categorical",
        "templates": (
            "classification_plsda",
            "knn_classification",
            "simca_classification",
            "pca",
            "ica_decomposition",
        ),
    },
    {
        "name": "synthetic-regression",
        "reference": {"source": "synthetic", "name": "Synthetic_atmospheric-6"},
        "stage": "synthetic",
        "target": "Carbon dioxide",
        "target_type": "continuous",
        "templates": ("pls_calibration",),
    },
)


# Decisions for a reviewed baseline entry:
#   "accepted-retrain": the saved model is refused on purpose; the release notes
#       tell users to retrain it.
#   "fix-pending": the refusal is a defect, with a review-by date.
#   "unsupported-in-reference": the reference release cannot fit this scenario
#       at all (for example the template did not exist yet), so there is no
#       saved model to carry forward.
DECISIONS = frozenset({"accepted-retrain", "fix-pending", "unsupported-in-reference"})


def expected_cases() -> frozenset[tuple[str, str]]:
    """Every scenario/template pair a complete run must report."""

    return frozenset((scenario["name"], template) for scenario in SCENARIOS for template in scenario["templates"])


@dataclass
class ModelOutcome:
    scenario: str
    template: str
    artifact_uid: str | None = None
    workflow_id: int | None = None
    project_id: int | None = None
    experiment_id: int | None = None
    fitted: bool = False
    fit_error: str | None = None
    applies: bool | None = None
    reason: str | None = None
    # Applied only after the explicit exploratory-use acknowledgement that
    # releases newer than 0.6.0 require for models without signal identity.
    acknowledged: bool = False


@dataclass
class Evaluation:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)


class Api:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}/api/v1"

    def call(self, method: str, path: str, body: Any = None, timeout: float = 600) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"content-type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        return json.loads(raw) if raw else None

    def upload(self, experiment_id: int, filename: str, text: str, fields: dict[str, str]) -> Any:
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            for key, value in fields.items()
        ]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: text/csv\r\n\r\n{text}\r\n--{boundary}--\r\n"
        )
        request = urllib.request.Request(
            f"{self.base}/experiments/{experiment_id}/files",
            data="".join(parts).encode(),
            method="POST",
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - loopback only
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(f"upload {filename} -> HTTP {exc.code}: {detail}") from exc


def spectral_classes_csv() -> str:
    """Three Gaussian-band classes on a numeric wavenumber axis (deterministic)."""

    rng = random.Random(7)
    axis = [4000 - 20 * i for i in range(121)]
    rows = ["sample,class," + ",".join(str(x) for x in axis)]
    for label, centre in (("A", 3200), ("B", 2600), ("C", 1800)):
        for n in range(12):
            values = [
                math.exp(-(((x - centre) / 150) ** 2)) * (1 + 0.1 * rng.random()) + 0.01 * rng.random() for x in axis
            ]
            rows.append(f"{label}{n},{label}," + ",".join(f"{v:.6f}" for v in values))
    return "\n".join(rows) + "\n"


UPLOADS = {"spectral_classes": spectral_classes_csv}


class Server:
    """Run one installed version on a data directory until stopped."""

    def __init__(self, command: str, data_dir: Path, port: int, log: Path) -> None:
        self.command, self.data_dir, self.port, self.log = command, data_dir, port, log
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> Api:
        env = {**os.environ, "DATA_DIR": str(self.data_dir)}
        argv = [*shlex.split(self.command), "--no-browser", "--port", str(self.port)]
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(  # noqa: S603 - maintainer-supplied command
            argv, env=env, stdout=self.log.open("wb"), stderr=subprocess.STDOUT
        )
        api = Api(self.port)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"server exited early; see {self.log}")
            try:
                api.call("GET", "/config", timeout=5)
                return api
            except (OSError, RuntimeError):
                time.sleep(2)
        # __exit__ never runs when __enter__ raises; stop the process here so it
        # cannot hold the port and answer the next run's readiness probe.
        self.__exit__(None, None, None)
        raise RuntimeError(f"server did not become ready; see {self.log}")

    def __exit__(self, *exc: object) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _template_ids(api: Api) -> dict[str, int]:
    rows = api.call("GET", "/workflow-templates")
    rows = rows if isinstance(rows, list) else rows.get("items") or rows.get("templates") or []
    return {row["slug"]: int(row["id"]) for row in rows}


def fit_reference_models(api: Api) -> list[ModelOutcome]:
    """Fit one model per scenario template with the reference release."""

    templates = _template_ids(api)
    outcomes: list[ModelOutcome] = []
    for scenario in SCENARIOS:
        project = api.call("POST", "/projects", {"name": f"upgrade-check {scenario['name']}"})
        experiment = api.call("POST", "/experiments", {"name": scenario["name"], "project_id": project["id"]})
        if "upload_csv" in scenario:
            api.upload(
                experiment["id"],
                f"{scenario['upload_csv']}.csv",
                UPLOADS[scenario["upload_csv"]](),
                {
                    "stage": scenario["stage"],
                    "target_column": scenario["target"],
                    "target_type": scenario["target_type"],
                },
            )
        else:
            api.call(
                "POST",
                f"/experiments/{experiment['id']}/import-reference",
                {"datasets": [scenario["reference"]]},
            )
        api.call(
            "PUT",
            f"/experiments/{experiment['id']}/analysis-selection",
            {
                "selected_target": scenario["target"],
                "target_type": scenario["target_type"],
                "group_column": None,
                "source_digest": None,
            },
        )
        binding: dict[str, Any] = {
            "experiment_id": experiment["id"],
            "stage": scenario["stage"],
            "all_files": True,
        }
        try:
            info = api.call("POST", "/builder/file-info", {"experiment_id": experiment["id"]})
        except RuntimeError:
            info = {}
        source = (info.get("metadata") or {}).get("source_collection") or {}
        context = (info.get("scientific_projection") or {}).get("target_context") or {}
        units = context.get("target_units") if scenario["target"] in (context.get("target_names") or ()) else None
        if source.get("scientific_collection_sha256"):
            # Releases that require an explicit target authority reject
            # supervised bindings without one; older releases ignore it.
            binding["target_authority"] = {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": scenario["target"],
                "target_type": scenario["target_type"],
                "units": units,
                "source_digest": source["scientific_collection_sha256"],
            }
        for slug in scenario["templates"]:
            outcome = ModelOutcome(scenario=scenario["name"], template=slug)
            outcomes.append(outcome)
            if slug not in templates:
                outcome.fit_error = "template absent in reference release"
                continue
            try:
                workflow = api.call(
                    "POST",
                    f"/workflow-templates/{templates[slug]}/instantiate",
                    {
                        "workflow_name": f"upgrade-check {slug}",
                        "project_id": project["id"],
                        "launch_mode": "user",
                        "data_bindings": {"data_1": binding},
                    },
                )
                result = api.call("POST", f"/workflows/{workflow['id']}/execute", {"initial_data": {}})
                run = api.call("GET", f"/runs/{result['run_id']}?project_id={project['id']}")
            except RuntimeError as exc:
                outcome.fit_error = str(exc)
                continue
            artifacts = run.get("produced_artifact_uids") or []
            outcome.workflow_id = int(workflow["id"])
            outcome.project_id, outcome.experiment_id = int(project["id"]), int(experiment["id"])
            outcome.fitted = run.get("status") == "completed" and bool(artifacts)
            outcome.artifact_uid = artifacts[0] if artifacts else None
            if not outcome.fitted:
                outcome.fit_error = f"run status {run.get('status')!r}; artifacts {len(artifacts)}"
    return outcomes


def _preflight(api: Api, project_id: int | None, pair: dict[str, Any]) -> dict[str, Any]:
    response = api.call(
        "POST",
        "/runs/verification/preflight",
        {"project_id": project_id, "mode": "apply_model", "pairs": [pair]},
    )
    return response["pairs"][0]


def apply_with_candidate(api: Api, outcomes: list[ModelOutcome]) -> None:
    """Run the Batch page's preflight and application for each saved model."""

    for outcome in outcomes:
        if not outcome.fitted or outcome.artifact_uid is None:
            continue
        project_id, experiment_id = outcome.project_id, outcome.experiment_id
        pair = {
            "workflow_id": outcome.workflow_id,
            "artifact_uid": outcome.artifact_uid,
            "dataset": {"experiment_id": experiment_id},
        }
        try:
            check = _preflight(api, project_id, pair)
            if not check.get("compatible") and check.get("code") == "legacy_ack_required":
                pair["acknowledge_legacy_input_uncertainty"] = True
                outcome.acknowledged = True
                check = _preflight(api, project_id, pair)
            if not check.get("compatible"):
                outcome.applies, outcome.reason = False, str(check.get("reason") or "refused")
                continue
            batch = api.call(
                "POST",
                "/runs/verification",
                {
                    "project_id": project_id,
                    "mode": "apply_model",
                    "pairs": [{**pair, "receipt": check.get("receipt")}],
                },
            )
            status = batch["results"][0].get("status")
            outcome.applies = status == "completed"
            outcome.reason = None if outcome.applies else f"application run status {status!r}"
        except RuntimeError as exc:
            outcome.applies, outcome.reason = False, str(exc)


def _coverage_failures(outcomes: list[ModelOutcome], expected: frozenset[tuple[str, str]], fitted_by: str) -> list[str]:
    """A run that skipped cases, or fitted nothing, proves nothing."""

    seen = [(o.scenario, o.template) for o in outcomes]
    failures = [f"{s}/{t}: expected case did not run" for s, t in sorted(expected - set(seen))]
    failures += [f"{s}/{t}: unexpected case" for s, t in sorted(set(seen) - expected)]
    failures += [f"{s}/{t}: case reported more than once" for s, t in sorted({c for c in seen if seen.count(c) > 1})]
    if not any(o.fitted for o in outcomes):
        failures.append(f"no model was fitted by the {fitted_by}; the check would prove nothing")
    return failures


def _entry_for(entries: list[dict[str, Any]], outcome: ModelOutcome) -> int | None:
    return next(
        (
            index
            for index, entry in enumerate(entries)
            if entry.get("template") == outcome.template and entry.get("scenario") in (None, outcome.scenario)
        ),
        None,
    )


def evaluate(
    outcomes: list[ModelOutcome],
    baseline: dict[str, Any],
    reference_version: str,
    today: dt.date,
    expected: frozenset[tuple[str, str]] | None = None,
) -> Evaluation:
    """Compare outcomes with the reviewed decision list. Anything unreviewed fails."""

    result = Evaluation()
    result.failures += _coverage_failures(outcomes, expected_cases() if expected is None else expected, "reference")
    entries = [
        entry
        for entry in baseline.get("known_incompatibilities", [])
        if entry.get("reference_version") == reference_version
    ]
    matched: set[int] = set()
    for outcome in outcomes:
        label = f"{outcome.scenario}/{outcome.template}"
        listed = _entry_for(entries, outcome)
        entry = entries[listed] if listed is not None else {}
        decision = entry.get("decision")
        if listed is not None:
            matched.add(listed)
            if decision not in DECISIONS:
                result.failures.append(f"{label}: baseline decision must be one of {sorted(DECISIONS)}")
                continue
        if not outcome.fitted:
            # A reference fit failure is a gap in the evidence, never a pass.
            if decision != "unsupported-in-reference":
                result.failures.append(f"{label}: reference release did not produce a model ({outcome.fit_error})")
            elif str(entry.get("reason_contains") or "") not in str(outcome.fit_error):
                result.failures.append(
                    f"{label}: reference fit failed for an unreviewed reason ({outcome.fit_error!r})"
                )
            else:
                result.known.append(f"{label}: not fittable in {reference_version} ({entry.get('tracking')})")
            continue
        if decision == "unsupported-in-reference":
            result.failures.append(f"{label}: listed as not fittable but the reference fitted it; remove the entry")
            continue
        if outcome.applies:
            if listed is not None:
                result.failures.append(f"{label}: listed as incompatible but now applies; remove the baseline entry")
            continue
        if listed is None:
            result.failures.append(f"{label}: saved model no longer applies after upgrade: {outcome.reason}")
            continue
        expected_reason = str(entry.get("reason_contains") or "")
        if expected_reason and expected_reason not in str(outcome.reason):
            result.failures.append(f"{label}: refused for a different reason than reviewed ({outcome.reason!r})")
            continue
        message = f"{label}: known incompatibility ({entry.get('tracking')}); decision: {decision}"
        # An accepted break is permanent for that reference release and is
        # announced in the release notes. A pending fix must name a date.
        review_by = dt.date.fromisoformat(str(entry["review_by"])) if decision == "fix-pending" else None
        if review_by is not None and today > review_by:
            result.failures.append(f"{message}; review date {review_by} has passed")
        else:
            result.known.append(message)
    for index, entry in enumerate(entries):
        if index not in matched:
            result.failures.append(
                f"baseline entry matches no case: {entry.get('scenario') or '*'}/{entry.get('template')}"
            )
    return result


def evaluate_round_trip(outcomes: list[ModelOutcome], expected: frozenset[tuple[str, str]] | None = None) -> Evaluation:
    """Models the candidate fits itself must apply without any waiver.

    The baseline only ever excuses models saved by an older release. A refusal
    here is a defect in the release being prepared, so it always fails.
    """

    result = Evaluation()
    result.failures += _coverage_failures(outcomes, expected_cases() if expected is None else expected, "candidate")
    for outcome in outcomes:
        label = f"{outcome.scenario}/{outcome.template}"
        if not outcome.fitted:
            result.failures.append(f"{label}: candidate could not fit its own starter ({outcome.fit_error})")
        elif not outcome.applies:
            result.failures.append(f"{label}: model fitted by the candidate does not apply: {outcome.reason}")
        elif outcome.acknowledged:
            result.failures.append(f"{label}: a current model needed the legacy exploratory acknowledgement")
    return result


def render_markdown(reference_version: str, outcomes: list[ModelOutcome], evaluation: Evaluation) -> str:
    lines = [
        f"## Saved-model check ({reference_version})",
        "",
        "| Scenario | Template | Fitted | Applies | Reason |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        applies = "—" if o.applies is None else ("**no**" if not o.applies else "yes")
        if o.applies and o.acknowledged:
            applies = "yes, after exploratory acknowledgement"
        reason = (o.reason or o.fit_error or "").replace("|", "\\|")[:160]
        lines.append(f"| {o.scenario} | {o.template} | {'yes' if o.fitted else 'no'} | {applies} | {reason} |")
    for title, items in (
        ("Failures", evaluation.failures),
        ("Known", evaluation.known),
        ("Warnings", evaluation.warnings),
    ):
        if items:
            lines += ["", f"### {title}", *[f"- {item}" for item in items]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--mode",
        choices=("upgrade", "round-trip"),
        default="upgrade",
        help="upgrade: fit with the reference release, apply with the candidate; "
        "round-trip: fit and apply with the candidate (no baseline waivers)",
    )
    parser.add_argument("--reference-command", help="command that starts the reference release")
    parser.add_argument("--reference-version")
    parser.add_argument("--candidate-command", required=True, help="command that starts the candidate code")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).with_name("saved_model_upgrade_baseline.json"),
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--report", type=Path, help="write a Markdown summary here")
    args = parser.parse_args(argv)
    if args.mode == "upgrade" and not (args.reference_command and args.reference_version):
        parser.error("--mode upgrade needs --reference-command and --reference-version")

    data_dir = args.work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=False)
    fit_command = args.reference_command if args.mode == "upgrade" else args.candidate_command
    with Server(fit_command, data_dir, args.port, args.work_dir / "fit.log") as api:
        outcomes = fit_reference_models(api)
    with Server(args.candidate_command, data_dir, args.port, args.work_dir / "apply.log") as api:
        apply_with_candidate(api, outcomes)

    if args.mode == "upgrade":
        baseline = json.loads(args.baseline.read_text())
        evaluation = evaluate(outcomes, baseline, args.reference_version, dt.date.today())
        title = f"from {args.reference_version}"
    else:
        evaluation = evaluate_round_trip(outcomes)
        title = "candidate round trip"
    report = render_markdown(title, outcomes, evaluation)
    print(report)
    if args.report:
        args.report.write_text(report)
    (args.work_dir / "outcomes.json").write_text(json.dumps([asdict(o) for o in outcomes], indent=2))
    return 1 if evaluation.failures else 0


if __name__ == "__main__":
    sys.exit(main())
