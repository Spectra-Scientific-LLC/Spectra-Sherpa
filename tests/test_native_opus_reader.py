from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io import ParserLimits, ingest, select_asset

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "opus"
CONFORMANCE_PATH = REPO_ROOT / "docs" / "evidence" / "native-opus-reader-conformance.json"


def _external_corpus_root() -> Path:
    configured = os.environ.get("SPECTRA_EXTERNAL_VENDOR_CORPUS")
    return Path(configured) if configured else Path.home() / ".spectrochempy" / "testdata"


def _require_external_corpus() -> bool:
    return os.environ.get("SPECTRA_REQUIRE_EXTERNAL_VENDOR_CORPUS") == "1"


def _digest(array: object) -> str:
    values = np.ascontiguousarray(np.asarray(array, dtype="<f8"))
    return hashlib.sha256(values.tobytes()).hexdigest()


def _mutate_absorbance_pair_type(payload: bytearray, *, code_index: int, code_value: int) -> None:
    """Change one scientific type dimension on both absorbance pair entries."""
    shifts = (0, 2, 4, 10, 17, 19)
    widths = (2, 2, 6, 7, 2, 3)
    directory_offset = struct.unpack_from("<i", payload, 12)[0]
    max_blocks = struct.unpack_from("<i", payload, 16)[0]
    changed = 0
    for index in range(max_blocks):
        entry_offset = directory_offset + 12 * index
        type_value, _size, block_offset = struct.unpack_from("<iii", payload, entry_offset)
        if block_offset <= 0:
            break
        type_index = (type_value >> 10) & 0b1111111
        source_role = (type_value >> 2) & 0b11
        data_flags = (type_value >> 19) & 0b111
        if type_index % 32 != 4 or source_role != 3 or data_flags != 0:
            continue
        shift = shifts[code_index]
        mask = ((1 << widths[code_index]) - 1) << shift
        type_value = (type_value & ~mask) | (code_value << shift)
        struct.pack_into("<i", payload, entry_offset, type_value)
        changed += 1
    assert changed == 2


def _conformance() -> dict:
    return json.loads(CONFORMANCE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("record", _conformance()["bundled_fixtures"], ids=lambda item: item["fixture_id"])
def test_opus_bundled_fixture_matches_licensed_independently_verified_science(record: dict) -> None:
    path = FIXTURE_ROOT / record["filename"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    result = ingest(path)

    assert result.format_id == "opus"
    assert result.variant == "directory-block-v1"
    assert result.parser_id == "spectrasherpa.opus"
    assert result.parser_version == _conformance()["parser_version"]
    assert result.raw_metadata["opus.version"] == record["version"]
    assert result.raw_metadata["opus.block_count"] == record["block_count"]
    assert [asset.asset_id for asset in result.assets] == record["asset_order"]
    assert result.raw_metadata["opus.parameters"]
    assert result.raw_metadata["opus.parameter_blocks"]
    assert result.raw_metadata["opus.refused_blocks"] == record["refused_blocks"]

    for asset, expected in zip(result.assets, record["assets"], strict=True):
        dataset = asset.dataset
        axis = dataset.feature_axis
        assert asset.asset_id == expected["asset_id"]
        assert list(dataset.shape) == expected["shape"]
        assert _digest(dataset.X) == expected["values_sha256"]
        assert _digest(axis.values) == expected["axis_sha256"]
        assert dataset.X[0, 0] == expected["first_value"]
        assert dataset.X[0, -1] == expected["last_value"]
        assert axis.values[0] == expected["first_axis"]
        assert axis.values[-1] == expected["last_axis"]
        assert axis.units == expected["axis_units"]
        assert dataset.domain.data_quantity == expected["data_quantity"]
        assert dataset.units == expected["value_units"]


def test_opus_conformance_record_is_closed_and_exactly_attributed() -> None:
    record = _conformance()
    assert set(record) == {
        "schema_version",
        "format_id",
        "parser_id",
        "parser_version",
        "bundled_fixture_root",
        "source_authority",
        "bundled_corpus_source",
        "external_corpus_source",
        "retained_scope",
        "fixture_policy",
        "external_fixtures",
        "bundled_fixtures",
    }
    assert record["schema_version"] == "spectrasherpa-native-opus-conformance/3"
    assert record["bundled_fixture_root"] == "packages/spectra-sherpa/tests/fixtures/opus"
    assert record["source_authority"] == {
        "project": "brukeropus",
        "version": "1.4.3",
        "git_commit": "af5a508cef7de8089acd27a215d644ab451257dd",
        "source_distribution_sha256": "0e67c27d6dcc8fbe06e8c56eec616aec9d55457ae06666520e7bcdc5c91b59cb",
        "license": "MIT",
        "upstream_url": "https://github.com/joshduran/brukeropus",
    }
    assert record["bundled_corpus_source"] == {
        "repository": "https://github.com/spectral-cockpit/opusreader2",
        "commit": "96f970beb0ef92ccb3ee62fc3d8b7f27e1587c41",
        "path_root": "inst/extdata/test_data",
        "license": "MIT",
        "use_boundary": (
            "Only the five exact-hash package-authored test_data files listed under bundled_fixtures are "
            "redistributed. Three issue-submitted new_data files lack an explicit contributor redistribution "
            "grant and are not bundled or claimed as MIT."
        ),
    }
    assert record["external_corpus_source"] == {
        "repository": "https://github.com/spectrochempy/spectrochempy_data",
        "commit": "08bb9b0cbff8f4363c48b6bff7ccb743f8140e0a",
        "path_root": "testdata",
        "license": None,
        "use_boundary": (
            "Exact-hash files are retrieved from the named public upstream commit only into an ephemeral "
            "qualification directory. They are not redistributed, cached, bundled, or downloaded by "
            "SpectraSherpa tests or runtime code."
        ),
    }
    assert "not redistributed" in record["fixture_policy"]
    assert len(record["external_fixtures"]) == 3
    assert len(record["bundled_fixtures"]) == 6
    # Three independently checked external files cover two genuinely distinct
    # binary structures. Different sample values from one structure are not
    # promoted into fake structural independence.
    assert {item["structural_variant"] for item in record["external_fixtures"]} == {
        "two-asset-reference-interferogram-spectrum",
        "six-asset-sample-reference-absorbance",
    }
    # Six licensed bundled files span six distinct structural variants: the
    # two pairing-resolution regressions, two documented-scope refusal shapes,
    # a second real duplicate-pairing source, and the original Open Specy case.
    assert {item["structural_variant"] for item in record["bundled_fixtures"]} == {
        "licensed-five-asset-sample-reference-absorbance-with-one-refused-block",
        "five-asset-sample-reference-absorbance-with-non-matching-status-envelope",
        "six-asset-sample-reference-absorbance-with-duplicate-absorbance-pair",
        "four-asset-diffuse-reflectance-soil-absorbance-with-duplicate-absorbance-pair",
        "five-asset-sample-reference-absorbance-with-four-refused-blocks",
        "two-asset-sample-reference-with-refused-reflectance-and-flagged-blocks",
    }
    assert all(
        item["source"] and item["verification"] and item["assets"]
        for item in (*record["external_fixtures"], *record["bundled_fixtures"])
    )
    licenses = {(item["filename"], item["license"], item["notice"]) for item in record["bundled_fixtures"]}
    assert ("openspecy-polystyrene.0", "CC-BY-4.0", "THIRD_PARTY_LICENSES/OpenSpecy-CC-BY-4.0.txt") in licenses
    opusreader2_notice = "THIRD_PARTY_LICENSES/opusreader2-MIT.txt"
    assert sum(1 for item in record["bundled_fixtures"] if item["notice"] == opusreader2_notice) == 5
    assert all(item["license"] == "MIT" for item in record["bundled_fixtures"] if item["notice"] == opusreader2_notice)


@pytest.mark.parametrize("record", _conformance()["external_fixtures"], ids=lambda item: item["fixture_id"])
def test_external_exact_hash_opus_science_when_available(record: dict) -> None:
    path = _external_corpus_root() / record["external_locator"]
    if not path.is_file():
        if _require_external_corpus():
            pytest.fail(f"required external exact-hash OPUS reference is missing: {record['external_locator']}")
        pytest.skip("external exact-hash OPUS reference is not installed; bundled Open Specy coverage always runs")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    result = ingest(path)
    assert [asset.asset_id for asset in result.assets] == record["asset_order"]
    for asset, expected in zip(result.assets, record["assets"], strict=True):
        assert list(asset.dataset.shape) == expected["shape"]
        assert _digest(asset.dataset.X) == expected["values_sha256"]
        assert _digest(asset.dataset.feature_axis.values) == expected["axis_sha256"]


def test_opus_runtime_scope_equals_independently_qualified_variants() -> None:
    record = _conformance()["retained_scope"]
    assert record["supported"] == [
        "float32 DPF=1 non-compact one-dimensional OPUS data blocks",
        "WN and PNT coordinate codes",
        "type indices 1 spectrum, 2 interferogram, 3 phase, and 4 absorbance",
        "unambiguous one-to-one data/status pairing, admitted without requiring the "
        "status block's recorded MNY/MXY to reproduce from the decoded bytes",
        "same-type data/status pairings disambiguated by comparing each candidate's "
        "decoded, CSF-scaled value envelope against its declared MNY/MXY",
        "numeric filename extensions",
        "explicit multi-asset results",
    ]
    assert "DPF other than 1" in record["rejected"]
    assert "MI/LGW/MIN or unknown coordinate codes" in record["rejected"]
    assert "same-type data/status pairings that cannot be uniquely resolved by value" in record["rejected"]


def test_opus_requires_explicit_asset_selection() -> None:
    result = ingest(FIXTURE_ROOT / "openspecy-polystyrene.0")
    with pytest.raises(ValueError, match="select one exact asset_id"):
        select_asset(result)
    assert select_asset(result, asset_id="a").dataset.domain.data_quantity == "Absorbance"
    with pytest.raises(ValueError, match="Available assets"):
        select_asset(result, asset_id="invented")


def test_canonical_file_load_binds_one_exact_opus_asset() -> None:
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode

    path = FIXTURE_ROOT / "openspecy-polystyrene.0"
    with pytest.raises(ValueError, match="select one exact asset_id"):
        load_canonical_file_as_sherpa(path)

    selected = load_canonical_file_as_sherpa(path, asset_id="a")
    assert selected.domain.data_quantity == "Absorbance"
    node_selected = FileLoadNode(
        "opus",
        {"experiment_id": 1, "file_id": 1, "stage": "raw", "asset_id": "a"},
    )._load_file(path, asset_id="a")
    np.testing.assert_array_equal(node_selected.X, selected.X)


@pytest.mark.asyncio
async def test_group_builder_and_batch_share_one_exact_opus_asset(tmp_path: Path) -> None:
    from spectra_sherpa.app.api.v1.routes.builder import _file_as_sherpa
    from spectra_sherpa.app.services.batch_predict import load_single_file
    from spectra_sherpa.app.services.dag.nodes.data.loaders import LoadGroupNode

    shutil.copyfile(FIXTURE_ROOT / "openspecy-polystyrene.0", tmp_path / "sample_1.0")

    with pytest.raises(ValueError, match="select one exact asset_id"):
        _file_as_sherpa(tmp_path / "sample_1.0")
    assert _file_as_sherpa(tmp_path / "sample_1.0", asset_id="a").shape == (1, 2126)
    assert load_single_file(tmp_path / "sample_1.0", asset_id="a").shape == (1, 2126)

    grouped = await LoadGroupNode(
        "group",
        {
            "folder_path": str(tmp_path),
            "pattern": "*.0",
            "recursive": False,
            "sort_by": "filename",
            "group_title": "OPUS absorbance",
            "asset_id": "a",
        },
    ).execute()
    assert grouped.shape == (1, 2126)
    assert grouped.domain.data_quantity == "Absorbance"

    # A second byte-identical source carries the same explicit scientific
    # sample label. Collection assembly must not fabricate a distinct sample
    # identity from the copied filename.
    shutil.copyfile(FIXTURE_ROOT / "openspecy-polystyrene.0", tmp_path / "sample_2.0")
    with pytest.raises(ValueError, match="duplicate sample identities"):
        await LoadGroupNode(
            "duplicate-group",
            {
                "folder_path": str(tmp_path),
                "pattern": "*.0",
                "recursive": False,
                "sort_by": "filename",
                "group_title": "OPUS absorbance",
                "asset_id": "a",
            },
        ).execute()


def test_exact_asset_identity_is_typed_across_retained_source_consumers() -> None:
    from spectra_sherpa.app.api.v1.routes.builder import DataMatrixRequest, FileInfoRequest
    from spectra_sherpa.app.api.v1.routes.models import MyDatasetModelApplyRef
    from spectra_sherpa.app.api.v1.routes.runs import RunDatasetRef
    from spectra_sherpa.app.schemas.deploy import BatchPredictRequest, FolderWatchCreate
    from spectra_sherpa.app.schemas.workflows import CanonicalProjectSourceBindingRequest
    from spectra_sherpa.app.services.batch_predict import load_single_file, run_batch_prediction
    from spectra_sherpa.app.services.canonical_project_binding import bind_canonical_project_source
    from spectra_sherpa.app.services.dag.canonical_workbench_baseline import CanonicalDatasetSelection
    from spectra_sherpa.app.services.dag.nodes.data.loaders import LoadGroupNode
    from spectra_sherpa.app.services.model_application import load_project_dataset

    assert "asset_id" in CanonicalDatasetSelection.__dataclass_fields__
    for schema in (
        DataMatrixRequest,
        FileInfoRequest,
        MyDatasetModelApplyRef,
        RunDatasetRef,
        BatchPredictRequest,
        FolderWatchCreate,
        CanonicalProjectSourceBindingRequest,
    ):
        assert "asset_id" in schema.model_fields
    for operation in (load_single_file, run_batch_prediction, bind_canonical_project_source, load_project_dataset):
        assert "asset_id" in inspect.signature(operation).parameters
    assert "asset_id" in {parameter.name for parameter in LoadGroupNode.metadata.parameters}

    frontend = Path(__file__).parents[1] / "frontend" / "src"
    data_content = (frontend / "views" / "data" / "DataContent.vue").read_text(encoding="utf-8")
    source_preview = (frontend / "views" / "data" / "DatasetSourcePreview.vue").read_text(encoding="utf-8")
    batch_run = (frontend / "views" / "experiments" / "BatchRunTab.vue").read_text(encoding="utf-8")
    assert "uploadAssetIds[member.staging_id]" in data_content
    assert "fetchFileAssets" in data_content
    assert "onInspectionAssetChange" in data_content
    assert 'source.asset_id ?? "auto"' in source_preview
    assert "selectedAssetId" in batch_run
    assert "scientific-assets" in batch_run


def test_opus_declared_elements_fail_before_data_block_decode(monkeypatch) -> None:
    from spectra_sherpa.io.formats import opus

    decoded = False

    def _unexpected(*_args, **_kwargs):
        nonlocal decoded
        decoded = True
        raise AssertionError("data block must not decode before the declared output gate")

    monkeypatch.setattr(opus, "_raw_values", _unexpected)
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(FIXTURE_ROOT / "openspecy-polystyrene.0", limits=ParserLimits(max_decoded_elements=100))
    assert decoded is False


def _mutated_fixture(tmp_path: Path, mutate) -> Path:
    payload = bytearray((FIXTURE_ROOT / "openspecy-polystyrene.0").read_bytes())
    mutate(payload)
    path = tmp_path / "mutated.0"
    path.write_bytes(payload)
    return path


def test_opus_rejects_truncated_directory_range(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        struct.pack_into("<i", payload, 12, len(payload) - 4)

    with pytest.raises(UnreadableSpectrumError, match="declared .*range exceeds"):
        ingest(_mutated_fixture(tmp_path, mutate))


def test_opus_rejects_overlapping_directory_blocks(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        first_offset = struct.unpack_from("<i", payload, 24 + 8)[0]
        struct.pack_into("<i", payload, 24 + 12 + 8, first_offset)

    with pytest.raises(UnreadableSpectrumError, match="blocks overlap"):
        ingest(_mutated_fixture(tmp_path, mutate))


def test_opus_rejects_directory_entry_that_contradicts_header(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        directory_offset = struct.unpack_from("<i", payload, 12)[0]
        _type_value, size_words, block_offset = struct.unpack_from("<iii", payload, directory_offset)
        struct.pack_into("<iii", payload, directory_offset, 0, size_words, block_offset)

    with pytest.raises(UnreadableSpectrumError, match="does not authenticate"):
        ingest(_mutated_fixture(tmp_path, mutate))


def test_opus_series_block_is_recognized_and_refused_without_flattening(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        directory_offset = struct.unpack_from("<i", payload, 12)[0]
        max_blocks = struct.unpack_from("<i", payload, 16)[0]
        for index in range(max_blocks):
            entry_offset = directory_offset + 12 * index
            type_value, _size, block_offset = struct.unpack_from("<iii", payload, entry_offset)
            if block_offset <= 0:
                break
            type_index = (type_value >> 10) & 0b1111111
            parameter_index = (type_value >> 4) & 0b111111
            if parameter_index == 0 and type_index not in {0, 13}:
                type_value = (type_value & ~(0b111 << 19)) | (2 << 19)
                struct.pack_into("<i", payload, entry_offset, type_value)
                return
        raise AssertionError("fixture has no data block")

    with pytest.raises(UnsupportedFormatVariantError, match="series/3-D.*not supported"):
        ingest(_mutated_fixture(tmp_path, mutate))


def _assert_block_refused(path: Path, *, reason: str) -> None:
    """One unqualified block is refused by name; its qualified siblings still load.

    SpectraSherpa never silently omits a block it cannot interpret, and never
    lets unqualified science reach a scientist.  It also must not deny access to
    the qualified blocks stored beside it, which real OPUS acquisitions carry.
    """
    baseline_result = ingest(FIXTURE_ROOT / "openspecy-polystyrene.0")
    baseline = {asset.asset_id for asset in baseline_result.assets}
    baseline_refused = baseline_result.raw_metadata["opus.refused_blocks"]
    result = ingest(path)
    admitted = {asset.asset_id for asset in result.assets}
    refused = result.raw_metadata["opus.refused_blocks"]
    assert refused, "expected the unqualified block to be recorded"
    assert any(re.search(reason, str(block["reason"])) for block in refused), refused
    assert all("offset" in block and "type_code" in block for block in refused)
    assert admitted < baseline, "the unqualified block must not reach the scientist"
    assert len(baseline) - len(admitted) == len(refused) - len(baseline_refused)
    assert admitted, "qualified blocks must remain available"
    assert any("not independently qualified" in warning for warning in result.warnings)


def test_opus_unqualified_dpf_refuses_only_that_block(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        offset = payload.find(b"DPF")
        assert offset > 0
        struct.pack_into("<i", payload, offset + 8, 2)

    _assert_block_refused(_mutated_fixture(tmp_path, mutate), reason="DPF=2.*not independently qualified")


def test_opus_missing_dpf_fails_closed(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        offset = payload.find(b"DPF")
        assert offset > 0
        payload[offset : offset + 3] = b"ZZZ"

    with pytest.raises(UnreadableSpectrumError, match="missing an explicit integer DPF"):
        ingest(_mutated_fixture(tmp_path, mutate))


def test_opus_missing_csf_fails_closed(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        offset = payload.find(b"CSF")
        assert offset > 0
        payload[offset : offset + 3] = b"ZZZ"

    with pytest.raises(UnreadableSpectrumError, match="missing an explicit finite CSF"):
        ingest(_mutated_fixture(tmp_path, mutate))


@pytest.mark.parametrize(
    ("code_index", "code_value", "message"),
    [
        (0, 1, "complex-part code 1"),
        (3, 36, "Multi-channel OPUS"),
        (4, 1, "derivative order 1"),
        (5, 1, "data-flags code 1"),
        (5, 5, "data-flags code 5"),
    ],
)
def test_opus_unqualified_scientific_type_dimensions_refuse_only_that_block(
    tmp_path: Path,
    code_index: int,
    code_value: int,
    message: str,
) -> None:
    def mutate(payload: bytearray) -> None:
        _mutate_absorbance_pair_type(payload, code_index=code_index, code_value=code_value)

    _assert_block_refused(_mutated_fixture(tmp_path, mutate), reason=re.escape(message))


def test_opus_unqualified_axis_code_refuses_only_that_block(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        cursor = 0
        while True:
            offset = payload.find(b"DXU", cursor)
            assert offset > 0
            value_offset = offset + 8
            if payload[value_offset : value_offset + 2] == b"WN":
                payload[value_offset : value_offset + 2] = b"MI"
                return
            cursor = offset + 3

    _assert_block_refused(_mutated_fixture(tmp_path, mutate), reason="axis code 'MI'.*not independently qualified")


def test_opus_unqualified_data_type_refuses_only_that_block(tmp_path: Path) -> None:
    def mutate(payload: bytearray) -> None:
        directory_offset = struct.unpack_from("<i", payload, 12)[0]
        max_blocks = struct.unpack_from("<i", payload, 16)[0]
        changed = 0
        for index in range(max_blocks):
            entry_offset = directory_offset + 12 * index
            type_value, _size, block_offset = struct.unpack_from("<iii", payload, entry_offset)
            if block_offset <= 0:
                break
            data_flags = (type_value >> 19) & 0b111
            if ((type_value >> 10) & 0b1111111) % 32 == 4 and data_flags == 0:
                type_value = (type_value & ~(0b1111111 << 10)) | (10 << 10)
                struct.pack_into("<i", payload, entry_offset, type_value)
                changed += 1
        assert changed == 2

    _assert_block_refused(_mutated_fixture(tmp_path, mutate), reason="data type 10.*not independently qualified")


def test_opus_file_with_no_qualified_block_still_fails_closed(tmp_path: Path) -> None:
    """Per-block refusal must not become a way to ingest a wholly unqualified file."""

    def mutate(payload: bytearray) -> None:
        directory_offset = struct.unpack_from("<i", payload, 12)[0]
        max_blocks = struct.unpack_from("<i", payload, 16)[0]
        changed = 0
        for index in range(max_blocks):
            entry_offset = directory_offset + 12 * index
            type_value, _size, block_offset = struct.unpack_from("<iii", payload, entry_offset)
            if block_offset <= 0:
                break
            parameter_index = (type_value >> 4) & 0b111111
            type_index = (type_value >> 10) & 0b1111111
            if parameter_index == 0 and type_index not in {0, 13}:
                # data-flags code 1 on every result block
                type_value = (type_value & ~(0b111 << 19)) | (1 << 19)
                struct.pack_into("<i", payload, entry_offset, type_value)
                changed += 1
        assert changed > 1

    with pytest.raises(UnsupportedFormatVariantError, match="Every OPUS data block"):
        ingest(_mutated_fixture(tmp_path, mutate))


def test_real_acquisition_with_unqualified_block_still_yields_its_qualified_science() -> None:
    """A published Bruker acquisition carrying one unqualified block must still load.

    ``openspecy-polystyrene.0`` is a real OPUS file from the Open Specy project
    (CC-BY-4.0).  It stores a second absorbance block whose data-flags code
    SpectraSherpa has not qualified.  Refusing the file for that reason would
    deny the scientist five qualified blocks, including the absorbance spectrum
    the acquisition exists to deliver.
    """
    result = ingest(FIXTURE_ROOT / "openspecy-polystyrene.0")

    assert {asset.asset_id for asset in result.assets} == {"igsm", "sm", "a", "igrf", "rf"}
    absorbance = next(asset for asset in result.assets if asset.asset_id == "a")
    assert absorbance.dataset.shape == (1, 2126)
    assert absorbance.dataset.feature_axis.units == "cm-1"

    refused = result.raw_metadata["opus.refused_blocks"]
    assert len(refused) == 1
    assert refused[0]["type_code"] == [3, 3, 0, 4, 0, 1]
    assert "data-flags code 1" in refused[0]["reason"]
    assert any("not independently qualified" in warning for warning in result.warnings)


def test_singular_pairing_is_admitted_without_requiring_its_value_envelope_to_match() -> None:
    """A real, published acquisition whose one status candidate mismatches on value must still load.

    ``617262_1TP_C-1_A5.0`` (opusreader2, MIT) has exactly one status block
    sharing each data block's pairing key -- an unambiguous pairing -- but the
    interferogram sample status block's recorded MNY/MXY does not reproduce
    from the block's literal decoded, CSF-scaled bytes. Before this fix, the
    reader required every pairing to pass that value check regardless of
    ambiguity, so this file failed to load at all. brukeropus, the project
    this reader's pairing logic is adapted from, accepts a singular type match
    unconditionally; this reader now does too.
    """
    result = ingest(FIXTURE_ROOT / "617262_1TP_C-1_A5.0")

    assert {asset.asset_id for asset in result.assets} == {"igsm", "sm", "a", "igrf", "rf"}
    assert result.raw_metadata["opus.refused_blocks"] == []

    igsm = next(asset for asset in result.assets if asset.asset_id == "igsm")
    status = igsm.raw_metadata["opus.data_parameters"]
    values = np.asarray(igsm.dataset.X, dtype=float).reshape(-1)
    scaled = status["csf"] * values
    # The regression this test pins: the recorded envelope does not match the
    # decoded one, and the block is admitted anyway because its pairing is
    # unambiguous.
    assert not np.isclose(float(scaled.min()), status["mny"], rtol=2e-6)


def test_duplicate_absorbance_pairing_is_disambiguated_by_value_not_refused() -> None:
    """Two data blocks sharing one OPUS type must each resolve to their own status, not both refuse.

    ``BF_lo_01_soil_cal.1`` (opusreader2, MIT) is a Bruker ALPHA diffuse-
    reflectance soil measurement carrying two absorbance results with an
    identical type code -- and therefore an identical pairing key. Before this
    fix, any data block whose pairing key matched more than one status block
    was refused outright, discarding both results. Disambiguating them by
    their decoded value envelope, matching brukeropus, admits both.
    """
    result = ingest(FIXTURE_ROOT / "BF_lo_01_soil_cal.1")

    assert {asset.asset_id for asset in result.assets} == {"sm", "rf", "a", "a_2"}
    assert result.raw_metadata["opus.refused_blocks"] == []

    primary = next(asset for asset in result.assets if asset.asset_id == "a")
    older = next(asset for asset in result.assets if asset.asset_id == "a_2")
    assert primary.dataset.shape == older.dataset.shape
    assert not np.array_equal(primary.dataset.X, older.dataset.X)


def _mutated_duplicate_absorbance_fixture(tmp_path: Path, mutate) -> Path:
    payload = bytearray((FIXTURE_ROOT / "BF_lo_01_soil_cal.1").read_bytes())
    # The exact-hash fixture's first absorbance status block.  Keeping this
    # fixed makes the mutation prove the parser's repeated-key behavior rather
    # than duplicating its directory walker in the test.
    first_status_start = 25_808
    first_status_end = 25_984
    mutate(payload, first_status_start, first_status_end)
    path = tmp_path / "mutated-duplicate.1"
    path.write_bytes(payload)
    return path


def test_duplicate_pairing_never_treats_missing_envelope_as_a_match(tmp_path: Path) -> None:
    """A status without MNY/MXY cannot disambiguate a repeated pairing key."""

    def mutate(payload: bytearray, start: int, end: int) -> None:
        for key, replacement in ((b"MNY", b"ZZY"), (b"MXY", b"ZZX")):
            offset = payload.find(key, start, end)
            assert offset >= start
            payload[offset : offset + 3] = replacement

    baseline = ingest(FIXTURE_ROOT / "BF_lo_01_soil_cal.1")
    expected = next(asset for asset in baseline.assets if asset.asset_id == "a")
    result = ingest(_mutated_duplicate_absorbance_fixture(tmp_path, mutate))
    absorbance = [asset for asset in result.assets if asset.asset_id.startswith("a")]

    assert [asset.asset_id for asset in absorbance] == ["a"]
    np.testing.assert_array_equal(absorbance[0].dataset.X, expected.dataset.X)
    assert any(
        "match this block's decoded value envelope" in block["reason"]
        for block in result.raw_metadata["opus.refused_blocks"]
    )


def test_duplicate_pairing_never_becomes_singular_after_status_disqualification(tmp_path: Path) -> None:
    """Filtering one status out cannot attach the surviving status to the wrong data block."""

    def mutate(payload: bytearray, start: int, end: int) -> None:
        offset = payload.find(b"DPF", start, end)
        assert offset >= start
        struct.pack_into("<i", payload, offset + 8, 2)

    baseline = ingest(FIXTURE_ROOT / "BF_lo_01_soil_cal.1")
    expected = next(asset for asset in baseline.assets if asset.asset_id == "a")
    result = ingest(_mutated_duplicate_absorbance_fixture(tmp_path, mutate))
    absorbance = [asset for asset in result.assets if asset.asset_id.startswith("a")]

    assert [asset.asset_id for asset in absorbance] == ["a"]
    np.testing.assert_array_equal(absorbance[0].dataset.X, expected.dataset.X)
    assert any("DPF=2" in block["reason"] for block in result.raw_metadata["opus.refused_blocks"])


def test_native_opus_import_and_execution_do_not_load_scp() -> None:
    import os
    import subprocess
    import sys

    script = f"""
import sys
from spectra_sherpa.io import ingest
r = ingest({str(FIXTURE_ROOT / "openspecy-polystyrene.0")!r})
assert r.format_id == 'opus'
assert not any(name == 'spectrochempy' or name.startswith('spectrochempy.') for name in sys.modules)
assert 'spectra_sherpa.app.lib.scp_adapter' not in sys.modules
assert 'spectra_sherpa.app.lib.scp_compat' not in sys.modules
"""
    env = dict(os.environ)
    env["SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION"] = "1"
    completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_native_absorbance_matches_spectrochempy_when_available() -> None:
    scp = pytest.importorskip("spectrochempy")
    path = FIXTURE_ROOT / "openspecy-polystyrene.0"
    native = select_asset(ingest(path), asset_id="a").dataset
    reference = scp.read_opus(path, merge=False)
    np.testing.assert_allclose(native.X, np.asarray(reference.data, dtype=float), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(
        native.feature_axis.values,
        np.asarray(reference.x.data, dtype=float),
        rtol=1e-12,
        # SpectroChemPy rounds the reconstructed axis slightly differently;
        # the native values are digest-bound to brukeropus's linspace rule.
        atol=8e-4,
    )
