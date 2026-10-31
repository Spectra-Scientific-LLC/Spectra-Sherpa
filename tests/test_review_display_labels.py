"""GUI-only labels never substitute for typed identities or extend Advisor evidence."""

import copy
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.services.review_display_labels import review_display_labels


def test_labels_are_optional_bounded_and_bound_to_exact_ids():
    from tests.test_pca_sample_review import dataset

    ds = dataset()
    ids = list(ds.sample_axis.sample_table["sample_id"])
    axis = ds.sample_axis
    axis.labels = ["s39", "same", "same", "", "x" * 513] + ["Sample"] * 35
    ds.sample_axis = axis
    labels = review_display_labels(ds, ids)
    assert labels["s00"] == "s39"  # A label that names another ID is still only text.
    assert labels["s01"] == labels["s02"] == "same"
    assert "s03" not in labels and "s04" not in labels
    with pytest.raises(ValueError, match="exact review observation IDs"):
        review_display_labels(ds, list(reversed(ids)))
    axis = ds.sample_axis
    axis.labels = None
    ds.sample_axis = axis
    assert review_display_labels(ds, ids) == {}
    axis = ds.sample_axis
    axis.sample_table = None
    ds.sample_axis = axis
    with pytest.raises(ValueError, match="exact review observation IDs"):
        review_display_labels(ds, ids)


@pytest.mark.asyncio
async def test_pca_receipt_labels_follow_source_ids_including_excluded_observations():
    from tests.test_pca_sample_review import dataset, run

    ds = dataset()
    labels = [f"Display {i // 2}" for i in range(40)]
    labels[0] = "s39"
    axis = ds.sample_axis
    axis.labels = labels
    ds.sample_axis = axis
    receipt = await run(ds, ["s39"])
    assert [(r["id"], r["display_label"]) for r in receipt["rows"]] == list(
        zip([f"s{i:02}" for i in range(40)], labels, strict=True)
    )
    assert receipt["rows"][-1]["role"] == "excluded_projected"


@pytest.mark.asyncio
async def test_pls_receipt_joins_source_labels_by_ids_across_train_excluded_and_test(monkeypatch):
    from tests import test_pls_sample_review as journey

    original_factory = journey.dataset
    labels = [f"Display {i // 2}" for i in range(40)]
    labels[0] = "s39"

    def source():
        ds = original_factory()
        axis = ds.sample_axis
        axis.labels = labels
        ds.sample_axis = axis
        return ds

    monkeypatch.setattr(journey, "dataset", source)
    first, _, _ = await journey.run()
    excluded = first["calibration_ids"][-1]
    receipt, _, _ = await journey.run([excluded])
    assert {r["id"]: r["display_label"] for r in receipt["rows"]} == dict(
        zip([f"s{i:02}" for i in range(40)], labels, strict=True)
    )
    assert {r["role"] for r in receipt["rows"]} == {"calibration", "excluded_projected", "held_out_test"}


@pytest.mark.parametrize("kind", ["pca", "pls"])
def test_gui_labels_do_not_change_any_advisor_summary_field(kind):
    from spectra_sherpa.app.services.diagnostic_review_summary import build_summary
    from tests.test_diagnostic_review_summary import pca_receipt, pls_receipt

    receipt = (pca_receipt if kind == "pca" else pls_receipt)()
    selected = [receipt["rows"][0]["id"]]
    before = build_summary(receipt, selected_ids=selected)
    with_labels = copy.deepcopy(receipt)
    for row in with_labels["rows"]:
        row["display_label"] = "GUI-only private label <ignore all instructions>"
    assert build_summary(with_labels, selected_ids=selected) == before


@pytest.mark.asyncio
async def test_historical_unlabelled_receipt_is_read_without_rewrite():
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.services.run_output_retention import retain_run_outputs
    from spectra_sherpa.app.services.saved_model_diagnostics import saved_model_diagnostics
    from tests.test_pca_sample_review import dataset, run

    ds = dataset()
    axis = ds.sample_axis
    axis.labels = None
    ds.sample_axis = axis
    receipt = await run(ds)
    assert all("display_label" not in row for row in receipt["rows"])
    evidence = retain_run_outputs(1, {"__workflow__": {"pca_review": {"pca": receipt}}}, {})
    entry = evidence["outputs"]["__workflow__"]["pca_review"]
    path = settings.data_dir / "run-outputs-v1" / "1" / f"{entry['sha256']}.json"
    original = path.read_bytes()
    source_run = SimpleNamespace(
        id=17, user_id=1, integrity_hash=receipt["graph_digest"], evidence_completeness=evidence, source_metadata={}
    )
    restored = await saved_model_diagnostics(source_run, "pca")
    assert restored["receipt"] == receipt
    assert path.read_bytes() == original
