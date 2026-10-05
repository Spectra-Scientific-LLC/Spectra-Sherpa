"""Cross-format guards for the native vendor readers.

Three separate obligations are enforced here, because Phase E qualified four
vendor parsers whose fixtures come from four different provenance stories:

1.  every native vendor format keeps at least one *bundled* real instrument
    file, so a clean checkout verifies real bytes rather than only synthesized
    ones;
2.  bundled fixtures are not copies of an unlicensed third-party corpus; and
3.  while SpectroChemPy remains installable it is used as a differential
    oracle for the readers that replaced it.

The parity checks are deliberately not the retained scientific authority --
the per-format conformance records are.  They are a free regression net that
stays useful for as long as the optional scientific extra exists.
"""

from __future__ import annotations

import hashlib
import json
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.io import ingest

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parents[3]
ATTRIBUTION_PATH = REPO_ROOT / "docs" / "evidence" / "bundled-vendor-fixture-attribution.json"

# Formats whose readers consume vendor binary files.  Each must keep bundled
# real-instrument coverage; synthesized bytes alone cannot qualify a parser
# because they encode the same assumptions the parser reads with.
VENDOR_FIXTURE_DIRECTORIES = ("spc", "opus", "omnic", "wdf")
VENDOR_FIXTURE_CONTROL_FILES = {"__index__"}


def _bundled_vendor_files(root: Path = FIXTURES) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for name in VENDOR_FIXTURE_DIRECTORIES:
        directory = root / name
        found[name] = sorted(
            path for path in directory.iterdir() if path.is_file() and path.name not in VENDOR_FIXTURE_CONTROL_FILES
        )
    return found


@pytest.mark.parametrize("format_name", VENDOR_FIXTURE_DIRECTORIES)
def test_every_vendor_format_keeps_bundled_real_file_coverage(format_name: str) -> None:
    """A clean checkout must verify each vendor reader against real bytes."""
    matches = _bundled_vendor_files()[format_name]
    assert matches, (
        f"{format_name} has no bundled real instrument fixture; a checkout without an "
        "external corpus would qualify this reader on synthesized bytes only"
    )


def test_bundled_vendor_fixtures_are_ingestible() -> None:
    """Every bundled vendor fixture is either read or explicitly refused by name."""
    from spectra_sherpa.ingestion_errors import IngestionError

    for _format_name, matches in sorted(_bundled_vendor_files().items()):
        for path in matches:
            try:
                result = ingest(path)
            except IngestionError as error:
                # Negative fixtures are permitted, but the refusal must name the
                # reason rather than surface as an opaque failure.
                assert str(error).strip(), f"{path} failed without an explanation"
                continue
            assert result.assets, f"{path} produced no assets"


def _attribution_failures(*, repo_root: Path, fixture_root: Path, record: dict) -> list[str]:
    failures: list[str] = []
    rows = record.get("fixtures")
    if record.get("schema_version") != "spectrasherpa-bundled-vendor-fixture-attribution/1":
        failures.append("unknown attribution schema")
    if not isinstance(rows, list):
        return [*failures, "fixtures must be a list"]

    actual = {
        path.relative_to(repo_root).as_posix()
        for matches in _bundled_vendor_files(fixture_root).values()
        for path in matches
    }
    declared = [row.get("path") for row in rows if isinstance(row, dict)]
    if len(declared) != len(set(declared)):
        failures.append("fixture attribution paths must be unique")
    if set(declared) != actual:
        failures.append(
            "fixture attribution mismatch: "
            f"missing={sorted(actual - set(declared))} "
            f"extra={sorted(set(declared) - actual)}"
        )

    for row in rows:
        if not isinstance(row, dict):
            failures.append("fixture attribution rows must be objects")
            continue
        if set(row) != {"path", "sha256", "source", "upstream", "license", "notice"}:
            failures.append(f"incomplete attribution row:{row.get('path')}")
            continue
        path = repo_root / row["path"]
        notice = repo_root / row["notice"]
        if not path.is_file():
            failures.append(f"missing attributed fixture:{row['path']}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            failures.append(f"fixture digest mismatch:{row['path']}")
        if not row["source"] or not row["upstream"] or not row["license"]:
            failures.append(f"empty provenance field:{row['path']}")
        if row["notice"].endswith("opusreader2-MIT.txt") and (
            "@96f970beb0ef92ccb3ee62fc3d8b7f27e1587c41" not in row["source"]
            or "/tree/96f970beb0ef92ccb3ee62fc3d8b7f27e1587c41/" not in row["upstream"]
        ):
            failures.append(f"unpinned opusreader2 provenance:{row['path']}")
        if not notice.is_file() or not notice.read_text().strip():
            failures.append(f"missing retained notice:{row['notice']}")
    return failures


def test_every_bundled_vendor_fixture_has_exact_fail_closed_attribution() -> None:
    record = json.loads(ATTRIBUTION_PATH.read_text())
    assert _attribution_failures(repo_root=REPO_ROOT, fixture_root=FIXTURES, record=record) == []


def test_opusreader2_attribution_refuses_an_unpinned_upstream() -> None:
    record = json.loads(ATTRIBUTION_PATH.read_text())
    row = next(item for item in record["fixtures"] if item["notice"].endswith("opusreader2-MIT.txt"))
    row["source"] = row["source"].replace(
        "@96f970beb0ef92ccb3ee62fc3d8b7f27e1587c41",
        "",
    )
    failures = _attribution_failures(repo_root=REPO_ROOT, fixture_root=FIXTURES, record=record)
    assert any("unpinned opusreader2 provenance" in failure for failure in failures)


def test_unattributed_vendor_fixture_is_rejected(tmp_path: Path) -> None:
    fixture_root = tmp_path / "packages" / "spectra-sherpa" / "tests" / "fixtures"
    for name in VENDOR_FIXTURE_DIRECTORIES:
        (fixture_root / name).mkdir(parents=True, exist_ok=True)
    extra = fixture_root / "opus" / "unattributed.0"
    extra.write_bytes(b"unattributed")
    failures = _attribution_failures(
        repo_root=tmp_path,
        fixture_root=fixture_root,
        record={"schema_version": "spectrasherpa-bundled-vendor-fixture-attribution/1", "fixtures": []},
    )
    assert any("unattributed.0" in failure for failure in failures)


@pytest.mark.parametrize("suffix", (".1", ".42", ".0007"))
def test_every_numeric_opus_suffix_is_inside_attribution_boundary(tmp_path: Path, suffix: str) -> None:
    fixture_root = tmp_path / "packages" / "spectra-sherpa" / "tests" / "fixtures"
    for name in VENDOR_FIXTURE_DIRECTORIES:
        (fixture_root / name).mkdir(parents=True, exist_ok=True)
    extra = fixture_root / "opus" / f"unattributed{suffix}"
    extra.write_bytes(b"unattributed")
    failures = _attribution_failures(
        repo_root=tmp_path,
        fixture_root=fixture_root,
        record={"schema_version": "spectrasherpa-bundled-vendor-fixture-attribution/1", "fixtures": []},
    )
    assert any(extra.name in failure for failure in failures)


def test_scp_ci_runs_every_native_reader_with_required_external_corpus() -> None:
    """The installed-SCP job must make all retained external science non-skippable."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for test_file in (
        "tests/test_native_opus_reader.py",
        "tests/test_native_omnic_ingestion.py",
        "tests/test_native_wdf_reader.py",
        "tests/test_native_spc_reader.py",
    ):
        assert test_file in workflow
    assert "tools/provision_external_vendor_conformance.py" in workflow
    assert "SPECTRA_REQUIRE_EXTERNAL_VENDOR_CORPUS=1" in workflow


# --------------------------------------------------------------------------
# Differential oracle against the reader stack the native parsers replaced.
# --------------------------------------------------------------------------


def _scp():
    try:
        distribution("spectrochempy")
    except PackageNotFoundError:
        pytest.skip("spectrochempy is not installed in this profile")
    try:
        return import_module("spectrochempy")
    except Exception as exc:
        pytest.fail(
            "The SpectroChemPy distribution is installed but its differential "
            f"oracle cannot import: {type(exc).__name__}: {exc}"
        )


def test_differential_oracle_fails_when_installed_runtime_is_broken(monkeypatch) -> None:
    monkeypatch.setattr(
        f"{__name__}.distribution",
        lambda name: object() if name == "spectrochempy" else None,
    )

    def broken_import(name: str):
        raise RuntimeError(f"broken import for {name}")

    monkeypatch.setattr(f"{__name__}.import_module", broken_import)
    with pytest.raises(pytest.fail.Exception, match="distribution is installed.*cannot import"):
        _scp()


def _reference(module, reader: str, path: Path):
    loaded = getattr(module, reader)(str(path))
    loaded = loaded[0] if isinstance(loaded, list) else loaded
    return np.asarray(loaded.data, dtype=float), np.asarray(loaded.x.data, dtype=float)


@pytest.mark.parametrize(
    ("relative", "reader"),
    [
        ("omnic/openspecy-polyethylene-reflectance.spa", "read_omnic"),
        ("wdf/sp.wdf", "read_wdf"),
        ("wdf/depth.wdf", "read_wdf"),
        ("wdf/line.wdf", "read_wdf"),
    ],
)
def test_native_vendor_values_match_spectrochempy(relative: str, reader: str) -> None:
    """Intensities must agree exactly with the implementation being replaced."""
    module = _scp()
    path = FIXTURES / relative
    reference_values, reference_axis = _reference(module, reader, path)
    if reference_values.ndim == 1:
        reference_values = reference_values.reshape(1, -1)
    # WiRE maps are a sample-major matrix in SpectraSherpa; WMAP topology is
    # explicit metadata rather than an implied cube dimension.
    reference_values = reference_values.reshape(-1, reference_values.shape[-1])

    asset = ingest(path).assets[0]
    values = np.asarray(asset.dataset.X, dtype=float)
    axis = np.asarray(asset.dataset.feature_axis.values, dtype=float)

    assert values.shape == reference_values.shape
    assert np.array_equal(values, reference_values), "native intensities diverge from SpectroChemPy"
    # Axes are rebuilt in float64 from the file's float32 endpoints, so they
    # agree to float32 resolution rather than bit-exactly.
    assert axis.shape == reference_axis.shape
    assert np.max(np.abs(axis - reference_axis)) < 1e-2
