"""Basic non-spectroscopic tables: row-index columns and .tsv/.txt/.dat extensions.

Every variant of the iris table must load exactly like the scikit-learn
Reference Dataset: four features, 150 rows, species kept for target binding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spectra_sherpa.app.lib.sklearn_info import load_sklearn_reference_as_sherpa
from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_registry_asset
from spectra_sherpa.io import ingest

FEATURES = ["sepal length (cm)", "sepal width (cm)", "petal length (cm)", "petal width (cm)"]
SPACE_FEATURES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]


@pytest.fixture(scope="module")
def reference():
    return load_sklearn_reference_as_sherpa("iris")


@pytest.fixture(scope="module")
def iris_frame(reference) -> pd.DataFrame:
    frame = pd.DataFrame(np.asarray(reference.X), columns=FEATURES)
    classes = reference.target_context.class_names
    frame["species"] = [classes[int(index)] for index in np.asarray(reference.target)]
    return frame


def _write_variants(frame: pd.DataFrame, root) -> dict[str, tuple[object, list[str] | None]]:
    """Return {name: (path, expected sample labels)} for common exports."""

    spaced = frame.rename(columns=dict(zip(FEATURES, SPACE_FEATURES)))
    first = [str(index) for index in range(len(frame))]
    one_based = [str(index + 1) for index in range(len(frame))]
    variants: dict[str, tuple[object, list[str] | None]] = {}

    def put(name, text, labels):
        path = root / name
        path.write_text(text, encoding="utf-8")
        variants[name] = (path, labels)

    put("no_index.csv", frame.to_csv(index=False), None)
    put("pandas_index.csv", frame.to_csv(index=True), first)
    put("no_index.txt", frame.to_csv(index=False), None)
    put("no_index.dat", frame.to_csv(index=False), None)
    put("tab_index.tsv", frame.to_csv(index=True, sep="\t"), first)
    put("tab_index.txt", frame.to_csv(index=True, sep="\t"), first)
    put("semicolon.txt", frame.to_csv(index=False, sep=";"), None)
    put("space_index.dat", spaced.to_csv(index=True, sep=" ").lstrip(" "), first)
    one = frame.copy()
    one.index = one.index + 1
    put("one_based_index.csv", one.to_csv(index=True, index_label="index"), one_based)
    # R write.table: header is one field shorter; row names are quoted.
    r_lines = [" ".join(f'"{name}"' for name in [*SPACE_FEATURES, "species"])]
    for index, row in enumerate(frame.itertuples(index=False), start=1):
        r_lines.append(" ".join([f'"{index}"', *(repr(float(value)) for value in row[:4]), f'"{row[4]}"']))
    put("r_rownames.txt", "\n".join(r_lines) + "\n", one_based)
    return variants


def test_every_text_table_variant_matches_the_reference_dataset(tmp_path, reference, iris_frame):
    for name, (path, labels) in _write_variants(iris_frame, tmp_path).items():
        dataset = ingest(path).assets[0].dataset
        np.testing.assert_allclose(np.asarray(dataset.X, dtype=float), reference.X, err_msg=name)
        assert len(dataset.feature_axis.labels) == 4, name
        assert dataset.extra["prop_names"] == ["species"], name
        actual = None if dataset.sample_axis.labels is None else list(dataset.sample_axis.labels)
        assert actual == labels, name


def test_bound_species_target_matches_the_reference_after_index_removal(tmp_path, reference, iris_frame):
    path = tmp_path / "iris.csv"
    path.write_text(iris_frame.to_csv(index=True), encoding="utf-8")
    dataset = _load_registry_asset(
        path,
        prepared_overrides={"data_role": "X_features", "target_column": "species", "target_type": "categorical"},
    ).dataset
    assert dataset.feature_axis.labels == FEATURES
    np.testing.assert_allclose(np.asarray(dataset.X, dtype=float), reference.X)
    expected = np.asarray(reference.target_context.class_names)[np.asarray(reference.target)]
    assert np.asarray(dataset.target).astype(str).tolist() == expected.tolist()
    assert dataset.target_context.class_names == reference.target_context.class_names


@pytest.mark.parametrize(
    ("header", "values"),
    [
        ("length", [1, 2, 3, 4]),  # a named measurement is never an index
        ("", [2, 3, 4, 5]),  # does not start at 0 or 1
        ("", [0, 1, 3, 4]),  # not consecutive
        ("", [0.0, 0.5, 1.0, 1.5]),  # not integers
    ],
)
def test_first_columns_that_are_not_a_row_index_stay_features(tmp_path, header, values):
    path = tmp_path / "table.csv"
    rows = "\n".join(f"{value},{10 + i},{20 + i}" for i, value in enumerate(values))
    path.write_text(f"{header},a,b\n{rows}\n", encoding="utf-8")
    dataset = ingest(path).assets[0].dataset
    assert np.asarray(dataset.X).shape == (4, 3)


@pytest.mark.parametrize("suffix", [".txt", ".dat"])
def test_unstructured_text_is_not_claimed_as_a_table(tmp_path, suffix):
    from spectra_sherpa.ingestion_errors import UnsupportedFormatError

    path = tmp_path / f"notes{suffix}"
    path.write_text("Instrument notes\nrun started at noon, detector warm\nok\n", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        ingest(path)


def test_renishaw_text_still_owns_its_txt_exports(tmp_path):
    path = tmp_path / "spectrum.txt"
    path.write_text("#Wave\t#Intensity\n100.0\t1.0\n101.0\t2.0\n102.0\t3.0\n", encoding="utf-8")
    assert ingest(path).format_id == "renishaw-text"
