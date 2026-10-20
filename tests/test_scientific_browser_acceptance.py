"""Protect the browser acceptance fixtures and explicit qualification boundary."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.io import load_csv_as_sherpa
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry

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


def test_pls_starter_keeps_canonical_source_to_partition_graph() -> None:
    template = next(item for item in TemplateLoader().load_all() if item["slug"] == "pls_calibration")
    graph = template["template_data"]
    assert not any(item["node_type"] == "data.filter_samples" for item in graph["nodes"])
    incoming = [edge for edge in graph["edges"] if edge["to_node_id"] == "partition_1"]
    assert incoming == [
        {"from_node_id": "data_1", "to_node_id": "partition_1", "from_output": "default", "to_input": "X"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("response_kind", ["embedded", "array", "dataset"])
async def test_split_materializes_inclusion_with_original_indices_and_export_parity(response_kind: str) -> None:
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    source = load_csv_as_sherpa(FIXTURES / "moisture-nir.csv")
    before = source.scientific_digest
    included = np.flatnonzero(source.sample_axis.include_mask)
    y = None
    if response_kind == "array":
        y = np.asarray(source.target)
    elif response_kind == "dataset":
        y = SherpaDataset(
            X=np.asarray(source.target).reshape(-1, 1),
            sample_axis=source.sample_axis.copy(),
            target_context=source.target_context.model_copy(deep=True),
        )
    node = node_registry.create_node(
        "data.train_test_split", "partition", {"split_method": "kennard_stone", "test_size": 0.25}
    )
    live = await node.execute(X=source, y=y)
    namespace = {"source": source, "response": y, "np": np, "results": {}}
    exec(node_code := "\n".join(node.generate_python({"X": "source", "y": "response"}, indent="")), namespace)
    assert "prepare_split_source" in node_code
    generated = namespace["results"]["partition"]
    np.testing.assert_array_equal(np.sort(np.r_[live["train_indices"], live["test_indices"]]), included)
    for branch in ("train", "test"):
        indices = live[f"{branch}_indices"]
        dataset = live[f"X_{branch}"]
        np.testing.assert_allclose(dataset.X, source.X[indices])
        np.testing.assert_allclose(np.asarray(live[f"y_{branch}"]).ravel(), np.asarray(source.target)[indices].ravel())
        assert dataset.sample_axis.labels == [source.sample_axis.labels[i] for i in indices]
        assert dataset.sample_axis.sample_table["sample_id"] == [
            source.sample_axis.sample_table["sample_id"][i] for i in indices
        ]
        assert np.all(dataset.sample_axis.include_mask)
        assert dataset.target_context.target_units == "wt %"
        np.testing.assert_array_equal(generated[f"{branch}_indices"], indices)
        np.testing.assert_allclose(generated[f"X_{branch}"].X, dataset.X)
    assert source.scientific_digest == before


@pytest.mark.asyncio
async def test_split_refuses_empty_population_feature_exclusions_and_misaligned_responses() -> None:
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    source = load_csv_as_sherpa(FIXTURES / "moisture-nir.csv")
    node = node_registry.create_node("data.train_test_split", "partition", {})
    response = SherpaDataset(X=np.asarray(source.target).reshape(-1, 1), sample_axis=source.sample_axis.copy())
    response = response[np.arange(source.n_samples - 1, -1, -1)]
    with pytest.raises(ValueError, match="identities/order differ"):
        await node.execute(X=source, y=response)
    features = source.feature_axis.copy()
    features.include_mask = np.array([False] + [True] * 12)
    source.feature_axis = features
    with pytest.raises(ValueError, match="excluded variables"):
        await node.execute(X=source)
    samples = source.sample_axis.copy()
    samples.include_mask = np.zeros(24, dtype=bool)
    source.sample_axis = samples
    with pytest.raises(ValueError, match="at least two included"):
        await node.execute(X=source)


@pytest.mark.asyncio
async def test_split_rebinds_declared_groups_after_source_inclusion() -> None:
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import bind_split_groups
    from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision
    from tests.test_canonical_train_test_split import _grouped_dataset

    source = _grouped_dataset()
    samples = source.sample_axis.copy()
    samples.include_mask = np.array([i not in (1, 10) for i in range(source.n_samples)])
    source.sample_axis = samples
    # Changing inclusion invalidates an old supervision receipt. Deliberately
    # reselect the same target/group via its authority before splitting.
    source = attach_sample_table_supervision(
        source, target_column="class", target_type="categorical", group_column="block", node_id="attach"
    )
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "group_holdout", "held_out_groups": ["3"]},
    )
    result = await node.execute(X=source)
    np.testing.assert_array_equal(result["test_indices"], [8, 9, 11])
    assert set(result["train_indices"]) == {0, 2, 3, 4, 5, 6, 7}
    assert set(bind_split_groups(result["X_train"])) == {1, 2}
    assert result["X_test"].sample_axis.sample_table["block"] == [3, 3, 3]


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
