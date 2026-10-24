"""Routine dependency updates cannot silently replace qualified runtimes."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_engine_version_updates_require_explicit_scientific_qualification():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    python = next(update for update in config["updates"] if update["package-ecosystem"] == "pip")
    for name in ("scikit-learn", "spectrochempy"):
        rules = [rule for rule in python["ignore"] if rule["dependency-name"] == name]
        assert len(rules) == 1, f"{name} requires one explicit qualified-runtime update policy"
        assert set(rules[0]) == {"dependency-name", "update-types"}, "Do not ignore vulnerable versions"
        assert set(rules[0]["update-types"]) == {
            "version-update:semver-major",
            "version-update:semver-minor",
            "version-update:semver-patch",
        }
    assert python.get("open-pull-requests-limit", 5) > 0
    assert "allow" not in python, "Unrelated dependencies must remain eligible for updates"
