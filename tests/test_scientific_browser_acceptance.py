"""Protect the browser acceptance fixtures and explicit qualification boundary."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.io import load_csv_as_sherpa

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "frontend/e2e/scientific/fixtures"


@pytest.mark.parametrize("name", ["mixture-ir", "moisture-nir"])
def test_original_browser_fixture_retains_values_axes_identity_and_inclusion(name: str) -> None:
    expected = json.loads((FIXTURES / f"{name}.json").read_text())
    dataset = load_csv_as_sherpa(FIXTURES / f"{name}.csv", _infer_implicit_target=False)
    assert dataset.shape == (24, 13)
    np.testing.assert_allclose(dataset.X, expected["values"], rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(dataset.feature_axis.values, expected["axis"])
    assert dataset.feature_axis.units == expected["axis_units"]
    assert dataset.sample_axis.labels == expected["labels"]
    assert dataset.sample_axis.sample_table["sample_id"] == expected["labels"]
    assert list(dataset.sample_axis.include_mask) == expected["included"]
    assert sum(expected["included"]) == 22
    if expected["target"] is not None:
        np.testing.assert_allclose(np.asarray(dataset.target).ravel(), expected["target"])
        assert dataset.target_context.target_units == "wt %"


def test_original_fixture_generator_is_reproducible(tmp_path: Path) -> None:
    generator = runpy.run_path(str(ROOT / "scripts/generate_scientific_browser_fixtures.py"))
    generator["generate"](tmp_path)
    for name in ("mixture-ir", "moisture-nir"):
        actual = json.loads((tmp_path / f"{name}.json").read_text())
        expected = json.loads((FIXTURES / f"{name}.json").read_text())
        # Permit floating-point BLAS/platform rounding, never changed scientific content.
        np.testing.assert_allclose(actual.pop("values"), expected.pop("values"), rtol=1e-12, atol=1e-12)
        assert actual == expected


def test_pls_starter_materializes_source_inclusion_before_partitioning() -> None:
    template = next(item for item in TemplateLoader().load_all() if item["slug"] == "pls_calibration")
    graph = template["template_data"]
    node = next(item for item in graph["nodes"] if item["node_id"] == "inclusion_1")
    assert node["node_type"] == "data.filter_samples"
    assert node["parameters"]["field"] == "source_inclusion"
    incoming = [edge for edge in graph["edges"] if edge["to_node_id"] == "partition_1"]
    assert incoming == [
        {"from_node_id": "inclusion_1", "to_node_id": "partition_1", "from_output": "default", "to_input": "X"}
    ]


def test_provider_browser_lane_is_explicit_and_not_discovered_by_ordinary_ci() -> None:
    ordinary = (ROOT / "frontend/playwright.scientific.config.ts").read_text()
    legacy = (ROOT / "frontend/playwright.config.ts").read_text()
    provider = (ROOT / "frontend/playwright.provider.config.ts").read_text()
    assert 'testDir: "./e2e/scientific"' in ordinary
    assert '"**/provider/**"' in legacy
    assert 'testDir: "./e2e/provider"' in provider
    package = json.loads((ROOT / "frontend/package.json").read_text())
    assert "--grep @smoke" in package["scripts"]["test:science:smoke"]
    assert "playwright.provider.config.ts" in package["scripts"]["test:science:provider"]
    assert "reuseExistingServer: false" in ordinary
