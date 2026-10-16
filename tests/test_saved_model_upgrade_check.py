"""Rules that decide whether a saved-model upgrade refusal blocks a release."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "saved_model_upgrade_check.py"
SPEC = importlib.util.spec_from_file_location("saved_model_upgrade_check", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

TODAY = dt.date(2026, 10, 16)
ONE = frozenset({("s", "pca")})


def _outcome(template: str, applies: bool, reason: str | None = None, scenario: str = "s"):
    return TOOL.ModelOutcome(
        scenario=scenario, template=template, artifact_uid="a", fitted=True, applies=applies, reason=reason
    )


def _baseline(*entries: dict) -> dict:
    return {"schema_version": 1, "known_incompatibilities": list(entries)}


def _entry(**overrides) -> dict:
    entry = {
        "reference_version": "0.6.0",
        "template": "pca",
        "reason_contains": "unsupported",
        "tracking": "https://example.invalid/1",
        "decision": "accepted-retrain",
    }
    entry.update(overrides)
    return entry


def _evaluate(outcomes, baseline, expected=ONE):
    return TOOL.evaluate(outcomes, baseline, "0.6.0", TODAY, expected=expected)


def test_unlisted_refusal_fails() -> None:
    result = _evaluate([_outcome("pca", False, "unsupported schema")], _baseline())
    assert len(result.failures) == 1
    assert "no longer applies" in result.failures[0]


def test_accepted_refusal_is_known_without_a_review_date() -> None:
    result = _evaluate([_outcome("pca", False, "unsupported schema")], _baseline(_entry()))
    assert result.failures == []
    assert len(result.known) == 1


def test_entry_for_another_reference_release_does_not_excuse_a_refusal() -> None:
    result = _evaluate([_outcome("pca", False, "unsupported schema")], _baseline(_entry(reference_version="0.5.0")))
    assert len(result.failures) == 1


def test_listed_model_that_applies_again_fails_so_the_list_cannot_go_stale() -> None:
    result = _evaluate([_outcome("pca", True)], _baseline(_entry()))
    assert len(result.failures) == 1
    assert "remove the baseline entry" in result.failures[0]


def test_refusal_for_a_different_reason_fails() -> None:
    result = _evaluate([_outcome("pca", False, "artifact digest mismatch")], _baseline(_entry()))
    assert len(result.failures) == 1
    assert "different reason" in result.failures[0]


def test_pending_fix_fails_after_its_review_date() -> None:
    entry = _entry(decision="fix-pending", review_by="2026-10-15")
    result = _evaluate([_outcome("pca", False, "unsupported")], _baseline(entry))
    assert len(result.failures) == 1
    assert "review date" in result.failures[0]

    entry["review_by"] = "2026-10-16"
    assert _evaluate([_outcome("pca", False, "unsupported")], _baseline(entry)).failures == []


def test_unknown_decision_fails() -> None:
    result = _evaluate([_outcome("pca", False, "unsupported")], _baseline(_entry(decision="later")))
    assert len(result.failures) == 1


def test_reference_fit_failure_fails_unless_explicitly_reviewed() -> None:
    unfitted = TOOL.ModelOutcome(scenario="s", template="pca", fit_error="HTTP 500")
    fitted = _outcome("knn", True)
    expected = frozenset({("s", "pca"), ("s", "knn")})
    result = _evaluate([unfitted, fitted], _baseline(), expected)
    assert result.failures == ["s/pca: reference release did not produce a model (HTTP 500)"]

    reviewed = _entry(decision="unsupported-in-reference", reason_contains="template absent")
    result = _evaluate([unfitted, fitted], _baseline(reviewed), expected)
    assert any("unreviewed reason" in failure for failure in result.failures)

    absent = TOOL.ModelOutcome(scenario="s", template="pca", fit_error="template absent in reference release")
    result = _evaluate([absent, fitted], _baseline(reviewed), expected)
    assert result.failures == []
    assert result.known and "not fittable in 0.6.0" in result.known[0]

    result = _evaluate([_outcome("pca", True), fitted], _baseline(reviewed), expected)
    assert any("listed as not fittable but the reference fitted it" in f for f in result.failures)


def test_a_run_that_fitted_nothing_fails_even_with_a_permissive_baseline() -> None:
    """Reproduces the reviewed false green: all 11 real cases unfitted."""

    outcomes = [
        TOOL.ModelOutcome(scenario=scenario, template=template, fit_error="HTTP 500")
        for scenario, template in sorted(TOOL.expected_cases())
    ]
    assert len(outcomes) == 11
    upgrade = TOOL.evaluate(outcomes, _baseline(), "0.6.0", TODAY)
    assert any("no model was fitted" in failure for failure in upgrade.failures)
    assert len(upgrade.failures) == 12
    round_trip = TOOL.evaluate_round_trip(outcomes)
    assert any("no model was fitted" in failure for failure in round_trip.failures)


def test_missing_duplicate_and_unexpected_cases_fail() -> None:
    expected = frozenset({("s", "pca"), ("s", "knn")})
    result = _evaluate([_outcome("pca", True), _outcome("pca", True), _outcome("simca", True)], _baseline(), expected)
    assert "s/knn: expected case did not run" in result.failures
    assert "s/simca: unexpected case" in result.failures
    assert "s/pca: case reported more than once" in result.failures


def test_baseline_entry_that_matches_no_case_fails() -> None:
    result = _evaluate([_outcome("pca", True)], _baseline(_entry(template="pls_typo")))
    assert result.failures == ["baseline entry matches no case: */pls_typo"]


def test_committed_baseline_is_well_formed_and_names_real_cases() -> None:
    baseline = json.loads((ROOT / "scripts" / "saved_model_upgrade_baseline.json").read_text())
    assert baseline["schema_version"] == 1
    assert baseline["reference_versions"]
    cases = TOOL.expected_cases()
    for entry in baseline["known_incompatibilities"]:
        assert entry["reference_version"] in baseline["reference_versions"]
        assert entry["decision"] in TOOL.DECISIONS
        assert entry["tracking"].startswith("https://")
        assert entry["reason_contains"]
        assert any(
            template == entry["template"] and entry.get("scenario") in (None, scenario) for scenario, template in cases
        )
        if entry["decision"] == "fix-pending":
            dt.date.fromisoformat(entry["review_by"])


def test_scenario_scoped_entry_does_not_excuse_the_same_template_elsewhere() -> None:
    outcomes = [
        _outcome("pca", False, "unsupported", scenario="tabular"),
        _outcome("pca", False, "unsupported", scenario="spectral"),
    ]
    expected = frozenset({("tabular", "pca"), ("spectral", "pca")})
    result = _evaluate(outcomes, _baseline(_entry(scenario="tabular")), expected)
    assert len(result.known) == 1 and "tabular/pca" in result.known[0]
    assert len(result.failures) == 1 and "spectral/pca" in result.failures[0]


def test_round_trip_admits_no_waivers() -> None:
    applied = TOOL.ModelOutcome(scenario="s", template="pls", fitted=True, applies=True)
    refused = TOOL.ModelOutcome(scenario="s", template="pca", fitted=True, applies=False, reason="no replay")
    unfitted = TOOL.ModelOutcome(scenario="s", template="knn", fit_error="HTTP 500")
    legacy = TOOL.ModelOutcome(scenario="s", template="simca", fitted=True, applies=True, acknowledged=True)
    assert TOOL.evaluate_round_trip([applied], frozenset({("s", "pls")})).failures == []
    expected = frozenset({("s", "pca"), ("s", "knn"), ("s", "simca")})
    failures = TOOL.evaluate_round_trip([refused, unfitted, legacy], expected).failures
    assert len(failures) == 3
    assert "does not apply" in failures[0]
    assert "could not fit" in failures[1]
    assert "legacy exploratory acknowledgement" in failures[2]


def test_round_trip_and_upgrade_modes_are_both_offered() -> None:
    with pytest.raises(SystemExit):
        TOOL.main(["--candidate-command", "x", "--work-dir", "/nonexistent"])  # upgrade needs a reference


def test_server_that_never_becomes_ready_is_stopped(tmp_path, monkeypatch) -> None:
    """A slow server must not keep the port for the next run."""

    monkeypatch.setattr(TOOL.time, "monotonic", iter([0.0, 0.0, 1000.0]).__next__)
    monkeypatch.setattr(TOOL.time, "sleep", lambda _seconds: None)
    server = TOOL.Server(f"{sys.executable} -c 'import time; time.sleep(60)'", tmp_path, 1, tmp_path / "log")
    with pytest.raises(RuntimeError, match="did not become ready"):
        server.__enter__()
    assert server.process is not None and server.process.poll() is not None
