from __future__ import annotations

import inspect

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.pca_reporting import build_pca_block_report
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import execute_pca_node


def _balanced_scores() -> tuple[np.ndarray, list[str], dict[str, list[object]]]:
    specimen = [f"S{index:02d}" for index in range(1, 12)] * 3
    block = [value for value in range(1, 4) for _ in range(11)]
    order = list(range(1, 12)) * 3
    sample_id = [f"{specimen[index]}__{block[index]}" for index in range(33)]
    scores = np.asarray(
        [
            [float(position), float(position % 4) + block_index * 0.1, float(block_index)]
            for block_index in range(3)
            for position in range(11)
        ],
        dtype=np.float64,
    )
    return (
        scores,
        sample_id,
        {
            "sample_id": list(sample_id),
            "specimen_id": specimen,
            "block": block,
            "acquisition_order": order,
            "annotation": [f"row-{index}" for index in range(33)],
        },
    )


def test_block_report_uses_exact_frozen_formulas() -> None:
    scores, labels, table = _balanced_scores()
    result = build_pca_block_report(scores, sample_labels=labels, sample_table=table)
    summary = result.public_summary
    assert summary["score_shape"] == [33, 3]
    assert summary["within_specimen_pairwise_distance"]["count"] == 33
    assert summary["between_specimen_centroid_distance"]["count"] == 55
    assert len(summary["block_centroids"]) == 3
    assert 0.0 <= summary["block_r_squared"] <= 1.0
    assert summary["order_specimen_fully_aliased"] is True
    for path in summary["ordered_paths"]:
        assert path["spearman_by_component"][2] == {
            "component": 3,
            "rho": None,
            "status": "unavailable_constant_rank",
        }
    assert len(result.private_pairs["within_specimen"]) == 33
    assert len(result.private_pairs["between_specimen_centroids"]) == 55


def test_block_report_is_invariant_to_component_sign_and_typed_row_reordering() -> None:
    scores, labels, table = _balanced_scores()
    baseline = build_pca_block_report(scores, sample_labels=labels, sample_table=table).public_summary
    flipped = scores * np.asarray([-1.0, 1.0, -1.0])
    sign_result = build_pca_block_report(flipped, sample_labels=labels, sample_table=table).public_summary
    for field in (
        "within_specimen_pairwise_distance",
        "between_specimen_centroid_distance",
        "between_to_within_mean_ratio",
        "block_r_squared",
    ):
        assert sign_result[field] == baseline[field]

    permutation = np.random.default_rng(732).permutation(33)
    permuted_table = {name: [values[int(index)] for index in permutation] for name, values in table.items()}
    permuted_labels = [labels[int(index)] for index in permutation]
    permuted = build_pca_block_report(
        scores[permutation], sample_labels=permuted_labels, sample_table=permuted_table
    ).public_summary
    assert permuted["within_specimen_pairwise_distance"] == baseline["within_specimen_pairwise_distance"]
    assert permuted["between_specimen_centroid_distance"] == baseline["between_specimen_centroid_distance"]
    assert permuted["block_r_squared"] == pytest.approx(baseline["block_r_squared"], abs=1e-15)


def test_block_report_refuses_undefined_zero_within_specimen_ratio() -> None:
    scores, labels, table = _balanced_scores()
    identical_replicates = np.tile(scores[:11], (3, 1))
    with pytest.raises(ValueError, match="undefined for zero within-specimen distance"):
        build_pca_block_report(identical_replicates, sample_labels=labels, sample_table=table)


def test_block_report_preserves_typed_scalar_block_identity() -> None:
    scores, labels, table = _balanced_scores()
    table["block"] = [1] * 11 + ["1"] * 11 + [True] * 11
    table["acquisition_order"] = [np.int64(value) for value in table["acquisition_order"]]
    result = build_pca_block_report(scores, sample_labels=labels, sample_table=table)
    assert result.public_summary["block_ids"] == [True, 1, "1"]
    assert len(result.public_summary["block_centroids"]) == 3


def test_block_report_refuses_quadratic_pair_projection_before_materialization(monkeypatch) -> None:
    import spectra_sherpa.app.lib.pca_reporting as reporting

    specimen_count = 1_000
    rows = specimen_count * 2
    scores = np.arange(rows * 3, dtype=np.float64).reshape(rows, 3)
    specimen_ids = [f"S{index:04d}" for index in range(specimen_count)] * 2
    blocks = [1] * specimen_count + [2] * specimen_count
    labels = [f"{specimen_ids[index]}__B{blocks[index]}" for index in range(rows)]
    table = {
        "sample_id": labels,
        "specimen_id": specimen_ids,
        "block": blocks,
        "acquisition_order": list(range(1, specimen_count + 1)) * 2,
    }
    monkeypatch.setattr(reporting.np, "vstack", lambda *args, **kwargs: pytest.fail("pair projection allocated"))
    with pytest.raises(ValueError, match="private pair-record limit"):
        build_pca_block_report(scores, sample_labels=labels, sample_table=table)


@pytest.mark.parametrize(
    "mutation, match",
    [
        (lambda labels, table: table.pop("block"), "requires sample_id"),
        (lambda labels, table: table["sample_id"].reverse(), "exactly match"),
        (lambda labels, table: table["specimen_id"].__setitem__(0, ""), "non-empty strings"),
        (lambda labels, table: table["block"].__setitem__(0, "B2"), "balanced row"),
        (lambda labels, table: table["acquisition_order"].__setitem__(0, 2), "unique"),
    ],
)
def test_block_report_rejects_malformed_typed_identity(mutation, match: str) -> None:
    scores, labels, table = _balanced_scores()
    mutation(labels, table)
    with pytest.raises(ValueError, match=match):
        build_pca_block_report(scores, sample_labels=labels, sample_table=table)


def test_block_report_consumes_the_single_live_pca_result_without_refitting() -> None:
    scores, labels, table = _balanced_scores()
    rng = np.random.default_rng(733)
    matrix = scores @ rng.normal(size=(3, 12)) + rng.normal(scale=0.01, size=(33, 12))
    dataset = SherpaDataset(X=matrix, sample_axis=SampleAxis(labels=labels, sample_table=table))
    result = execute_pca_node(
        dataset,
        node_id="block-aware-pca",
        parameters={"n_components": "3", "standardized": False, "scaled": False},
    )
    output = result.outputs["scores"]
    assert "block_aware_summary" not in output.meta
    assert output.sample_axis is not None
    summary = build_pca_block_report(
        output.X,
        sample_labels=output.sample_axis.labels,
        sample_table=output.sample_axis.sample_table,
    ).public_summary
    assert summary["score_shape"] == [33, 3]
    assert summary["sample_identity_sha256"]
    assert output.sample_axis.sample_table == table


def test_live_pca_node_does_not_require_block_fields_for_general_datasets() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(5, 12)
    labels = [f"sample-{index}" for index in range(5)]
    dataset = SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(labels=labels, sample_table={"sample_id": labels}),
    )
    result = execute_pca_node(
        dataset,
        node_id="ordinary-pca",
        parameters={"n_components": "3", "standardized": False, "scaled": False},
    )
    assert "block_aware_summary" not in result.outputs["scores"].meta


def test_live_pca_node_does_not_require_balanced_optional_metadata() -> None:
    matrix = np.arange(36, dtype=np.float64).reshape(3, 12)
    labels = ["S1__B1", "S2__B1", "S1__B2"]
    dataset = SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": ["S1", "S2", "S1"],
                "block": [1, 1, 2],
                "acquisition_order": [1, 2, 1],
            },
        ),
    )
    result = execute_pca_node(
        dataset,
        node_id="unbalanced-metadata-pca",
        parameters={"n_components": "2", "standardized": False, "scaled": False},
    )
    assert result.outputs["scores"].shape == (3, 2)


def test_reporting_authority_cannot_fit_or_recompute_pca() -> None:
    import spectra_sherpa.app.lib.pca_reporting as reporting

    source = inspect.getsource(reporting)
    forbidden = ("sklearn", "fit_pca", "linalg.svd", "PCA(")
    assert not any(token in source for token in forbidden)
