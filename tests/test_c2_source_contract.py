"""C2b contract and admission proofs for the retained canonical data source."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentFile
from spectra_sherpa.core.spectra_meta import get_spectra_meta
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


def test_file_load_has_one_complete_local_sherpa_native_contract() -> None:
    metadata = node_registry.get_metadata("data.file_load")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == "data.file_load"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.DATA_SOURCE.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["semantic_inputs"] == ()
    assert [port["name"] for port in contract.payload["semantic_outputs"]] == [
        "default",
        "target",
        "sample_table",
    ]
    assert contract.payload["semantic_outputs"][0]["type_ref"] == ("spectrasherpa://types/SpectralDataset/1.0")
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["runtime_requirements"] == (
        {"distribution": "h5py", "version": "3.16.0"},
        {"distribution": "numpy", "version": "1.26.4"},
        {"distribution": "pandas", "version": "2.3.3"},
        {"distribution": "scipy", "version": "1.17.1"},
    )
    assert metadata.resolved_required_worker_capabilities() == (WorkerCapability.READ_DATASET.value,)


def test_file_load_canonicalizes_exact_persisted_source_identity() -> None:
    node = node_registry.create_node(
        "data.file_load",
        "source",
        {"experiment_id": 11, "file_id": 12},
    )

    assert node.parameters == {"experiment_id": 11, "file_id": 12, "stage": "raw"}


@pytest.mark.parametrize("field", ["experiment_id", "file_id"])
@pytest.mark.parametrize("value", [True, 1.5, "1", 0, -1])
def test_file_load_rejects_nonexact_or_nonpositive_source_identity(field: str, value: object) -> None:
    parameters: dict[str, object] = {"experiment_id": 1, "file_id": 2}
    parameters[field] = value

    with pytest.raises(ValueError, match=field):
        node_registry.create_node("data.file_load", "source", parameters)


def test_file_load_rejects_undeclared_source_parameters() -> None:
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node(
            "data.file_load",
            "source",
            {"experiment_id": 1, "file_id": 2, "reader": "spectrochempy"},
        )


def test_file_load_reads_portable_numpy_data_as_sherpa_dataset(tmp_path: Path) -> None:
    path = tmp_path / "portable.npz"
    expected = np.arange(12, dtype=np.float64).reshape(3, 4)
    np.savez(
        path,
        X=expected,
        wavenumber=np.array([1_000.0, 1_100.0, 1_200.0, 1_300.0]),
        sample_labels=np.array(["a", "b", "c"]),
    )

    loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(str(path))

    assert isinstance(loaded, SherpaDataset)
    np.testing.assert_array_equal(loaded.X, expected)
    np.testing.assert_array_equal(loaded.feature_axis.values, [1_000.0, 1_100.0, 1_200.0, 1_300.0])
    assert loaded.sample_axis.labels == ["a", "b", "c"]


def test_file_load_has_a_representative_absolute_performance_ceiling(tmp_path: Path) -> None:
    path = tmp_path / "representative.npz"
    matrix = np.random.default_rng(20260902).normal(size=(200, 1_600))
    np.savez(path, X=matrix, wavenumber=np.linspace(4_000.0, 400.0, 1_600))

    with PerformanceCeiling("data.file_load", "native-npz-200x1600", 5.0).measure():
        loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(path)

    assert loaded.shape == matrix.shape
    authority = loaded.get_extra("ingestion.authority")
    assert authority["format_id"] == "numpy"
    assert authority["source_members"] == [
        {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
    ]


class _ExactFileResolver:
    def __init__(self, source: ResolvedExperimentFile) -> None:
        self.source = source

    async def resolve_experiment_file(self, **_identity: object) -> ResolvedExperimentFile:
        return self.source


@pytest.mark.asyncio
async def test_file_load_executes_through_explicit_source_capability(tmp_path: Path) -> None:
    path = tmp_path / "portable.npy"
    np.save(path, np.arange(12, dtype=np.float64).reshape(3, 4))
    source = ResolvedExperimentFile(
        path=str(path),
        original_file_path="raw/portable.npy",
        created_datetime="2026-08-15T00:00:00+00:00",
        prepared_overrides=PreparedDataOverrides(x_title="Wavelength", x_units="nm").to_sidecar_dict(),
    )
    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    result = await node.execute()

    dataset = result["default"]
    assert isinstance(dataset, SherpaDataset)
    assert dataset.feature_axis.title == "Wavelength"
    assert dataset.feature_axis.units == "nm"
    assert get_spectra_meta(dataset).provenance.original_file_path == "raw/portable.npy"


@pytest.mark.asyncio
async def test_file_load_binds_native_reader_output_to_the_resolved_source_digest(tmp_path: Path) -> None:
    path = tmp_path / "portable.npy"
    np.save(path, np.arange(12, dtype=np.float64).reshape(3, 4))
    source = ResolvedExperimentFile(
        path=str(path),
        original_file_path="raw/portable.npy",
        created_datetime="2026-09-02T00:00:00+00:00",
        size_bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    result = await node.execute()

    authority = result["default"].get_extra("ingestion.authority")
    assert authority["parser_id"] == "spectrasherpa.numpy"
    assert authority["parser_version"] == "2"


@pytest.mark.asyncio
async def test_file_load_refuses_when_parser_bytes_differ_from_resolved_authority(tmp_path: Path) -> None:
    path = tmp_path / "portable.npy"
    np.save(path, np.arange(12, dtype=np.float64).reshape(3, 4))
    source = ResolvedExperimentFile(
        path=str(path),
        original_file_path="raw/portable.npy",
        created_datetime="2026-09-02T00:00:00+00:00",
        size_bytes=path.stat().st_size,
        sha256="0" * 64,
    )
    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    with pytest.raises(ValueError, match="parsed source identity differs"):
        await node.execute()


@pytest.mark.asyncio
async def test_file_load_consumes_the_admitted_snapshot_without_reopening_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = SherpaDataset(X=np.arange(12, dtype=np.float64).reshape(3, 4))
    source = ResolvedExperimentFile(
        path="/source-must-not-be-opened.npy",
        original_file_path="raw/admitted.npy",
        created_datetime="2026-08-26T00:00:00+00:00",
        preloaded_dataset=admitted,
        preloaded_asset_id="spectrum",
    )
    node = FileLoadNode(
        "source",
        {"experiment_id": 1, "file_id": 2, "stage": "raw", "asset_id": "spectrum"},
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))
    monkeypatch.setattr(node, "_load_file", lambda *args, **kwargs: pytest.fail("source reopened after admission"))

    result = await node.execute()

    assert np.array_equal(result["default"].X, admitted.X)
    assert result["default"] is not admitted


@pytest.mark.asyncio
async def test_file_load_refuses_target_semantics_that_contradict_the_admitted_snapshot() -> None:
    admitted = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=np.asarray([1.0, 2.0, 3.0]),
        target_context=TargetContext(
            target_type="continuous",
            target_name="Moisture",
            target_names=["Moisture"],
            selected_target="Moisture",
        ),
    )
    source = ResolvedExperimentFile(
        path="/source-must-not-be-opened.npy",
        original_file_path="raw/admitted.npy",
        created_datetime="2026-08-26T00:00:00+00:00",
        sha256="a" * 64,
        preloaded_dataset=admitted,
        preloaded_asset_id="spectrum",
    )
    node = FileLoadNode(
        "source",
        {
            "experiment_id": 1,
            "file_id": 2,
            "stage": "raw",
            "asset_id": "spectrum",
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "Protein",
                "target_type": "categorical",
                "units": None,
                "source_digest": "a" * 64,
            },
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    with pytest.raises(ValueError, match="requested target type contradicts the admitted dataset target type"):
        await node.execute()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_context", "parameters", "message"),
    [
        (
            TargetContext(
                target_type="continuous",
                target_name="Moisture",
                target_names=["Moisture"],
                selected_target="Moisture",
            ),
            {
                "target_authority": {
                    "schema_version": "spectrasherpa-target-authority/1",
                    "column": "Moisture",
                    "target_type": "categorical",
                    "units": None,
                    "source_digest": "a" * 64,
                }
            },
            "requested target type contradicts the admitted dataset target type",
        ),
        (
            None,
            {
                "target_authority": {
                    "schema_version": "spectrasherpa-target-authority/1",
                    "column": "Moisture",
                    "target_type": "continuous",
                    "units": None,
                    "source_digest": "a" * 64,
                }
            },
            "Target column 'Moisture' is not present",
        ),
    ],
)
async def test_file_load_refuses_each_preloaded_target_semantics_mismatch(
    target_context: TargetContext | None,
    parameters: dict[str, object],
    message: str,
) -> None:
    target = None if target_context is None else np.asarray([1.0, 2.0, 3.0])
    admitted = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=target,
        target_context=target_context,
    )
    source = ResolvedExperimentFile(
        path="/source-must-not-be-opened.npy",
        original_file_path="raw/admitted.npy",
        created_datetime="2026-08-26T00:00:00+00:00",
        sha256="a" * 64,
        preloaded_dataset=admitted,
        preloaded_asset_id="spectrum",
    )
    node = FileLoadNode(
        "source",
        {
            "experiment_id": 1,
            "file_id": 2,
            "stage": "raw",
            "asset_id": "spectrum",
            **parameters,
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    with pytest.raises(ValueError, match=message):
        await node.execute()


@pytest.mark.asyncio
async def test_file_load_records_only_target_semantics_matching_the_admitted_snapshot() -> None:
    admitted = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=np.asarray([1.0, 2.0, 3.0]),
        target_context=TargetContext(
            target_type="continuous",
            target_name="Moisture",
            target_names=["Moisture"],
            selected_target="Moisture",
        ),
    )
    source = ResolvedExperimentFile(
        path="/source-must-not-be-opened.npy",
        original_file_path="raw/admitted.npy",
        created_datetime="2026-08-26T00:00:00+00:00",
        sha256="a" * 64,
        preloaded_dataset=admitted,
        preloaded_asset_id="spectrum",
    )
    node = FileLoadNode(
        "source",
        {
            "experiment_id": 1,
            "file_id": 2,
            "stage": "raw",
            "asset_id": "spectrum",
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "Moisture",
                "target_type": "continuous",
                "units": None,
                "source_digest": "a" * 64,
            },
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    result = await node.execute()

    dataset = result["default"]
    assert dataset.target_context.selected_target == "Moisture"
    assert dataset.target_context.selected_authority.source_digest == "a" * 64
    assert dataset.provenance.to_list()[-1]["parameters"] == {
        "experiment_id": 1,
        "file_id": 2,
        "stage": "raw",
        "asset_id": "spectrum",
        "target_authority": {
            "schema_version": "spectrasherpa-target-authority/1",
            "column": "Moisture",
            "target_type": "continuous",
            "units": None,
            "source_digest": "a" * 64,
        },
    }


@pytest.mark.asyncio
async def test_file_load_selects_one_response_from_the_same_preloaded_snapshot() -> None:
    admitted = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        target=np.asarray([[10.0, 1.0], [11.0, 2.0], [12.0, 3.0]]),
        target_context=TargetContext(
            target_type="continuous",
            target_names=["Moisture", "Protein"],
            selected_target=None,
        ),
    )
    source = ResolvedExperimentFile(
        path="/source-must-not-be-opened.npy",
        original_file_path="raw/admitted.npy",
        created_datetime="2026-08-26T00:00:00+00:00",
        sha256="a" * 64,
        preloaded_dataset=admitted,
        preloaded_asset_id="spectrum",
    )
    node = FileLoadNode(
        "source",
        {
            "experiment_id": 1,
            "file_id": 2,
            "stage": "raw",
            "asset_id": "spectrum",
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "Moisture",
                "target_type": "continuous",
                "units": None,
                "source_digest": "a" * 64,
            },
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=_ExactFileResolver(source)))

    result = await node.execute()

    assert np.array_equal(result["default"].target, np.asarray([10.0, 11.0, 12.0]))
    assert np.array_equal(result["target"], np.asarray([10.0, 11.0, 12.0]))
    assert result["default"].target_context.selected_target == "Moisture"
    assert admitted.target.shape == (3, 2)


@pytest.mark.asyncio
async def test_file_load_fails_before_io_without_source_capability(tmp_path: Path) -> None:
    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    node.bind_execution_runtime(ExecutionRuntime())

    with pytest.raises(ValueError, match="dataset-source resolution capability is unavailable"):
        await node.execute()


def test_file_load_applies_exact_file_metadata_after_canonical_reader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "portable.npy"
    np.save(path, np.arange(12, dtype=np.float64).reshape(3, 4))
    prepared_overrides = PreparedDataOverrides(
        x_title="Wavelength",
        x_units="nm",
        y_title="Absorbance",
        is_time_series=True,
    ).to_sidecar_dict()

    loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(
        path,
        prepared_overrides=prepared_overrides,
    )

    assert loaded.feature_axis is not None
    assert loaded.feature_axis.title == "Wavelength"
    assert loaded.feature_axis.units == "nm"
    assert loaded.meta["data_quantity"] == "Absorbance"
    assert loaded.is_time_series is True


def test_file_load_replays_the_durable_headerless_csv_profile(tmp_path: Path) -> None:
    path = tmp_path / "supplier-export.csv"
    path.write_text("4000.0,0.10\n3999.0,0.20\n3998.0,0.30\n", encoding="utf-8")

    loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(
        path,
        prepared_overrides=PreparedDataOverrides(
            csv_layout="headerless_two_column_spectrum",
            x_title="Wavenumber",
            x_units="cm-1",
        ).to_sidecar_dict(),
    )

    np.testing.assert_allclose(loaded.X, [[0.10, 0.20, 0.30]])
    np.testing.assert_allclose(loaded.feature_axis.values, [4000.0, 3999.0, 3998.0])
    assert loaded.feature_axis.title == "Wavenumber"
    assert loaded.feature_axis.units == "cm-1"
    assert loaded.meta["csv.profile"] == "headerless_two_column_spectrum"


@pytest.mark.asyncio
async def test_exact_file_metadata_survives_representative_downstream_transform(
    tmp_path: Path,
) -> None:
    path = tmp_path / "portable.npz"
    np.savez(path, X=np.arange(20, dtype=np.float64).reshape(5, 4))
    prepared_overrides = PreparedDataOverrides(
        x_title="Wavenumber",
        x_units="cm^-1",
        y_title="Absorbance",
        is_time_series=True,
    ).to_sidecar_dict()
    loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(
        path,
        prepared_overrides=prepared_overrides,
    )

    transformed = await ScaleNode("scale", {"method": "autoscale"}).execute(loaded)
    output = transformed.outputs["default"]

    assert output.feature_axis.title == "Wavenumber"
    assert output.feature_axis.units == "cm^-1"
    assert output.meta["data_quantity"] == "Absorbance"
    assert output.is_time_series is True


def test_file_load_projects_only_the_explicit_csv_target(
    tmp_path: Path,
) -> None:
    path = tmp_path / "corn-shaped.csv"
    path.write_text(
        "sample_id,1000,1100,Moisture,Oil\nsample-a,1.0,2.0,10.5,4.0\nsample-b,3.0,4.0,11.5,5.0\n",
        encoding="utf-8",
    )
    loaded = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(
        path,
        selected_target="Moisture",
        target_type="continuous",
        prepared_overrides=PreparedDataOverrides(selected_target="Oil", target_mode="single").to_sidecar_dict(),
    )

    np.testing.assert_array_equal(loaded.X, [[1.0, 2.0], [3.0, 4.0]])
    np.testing.assert_array_equal(loaded.target, [10.5, 11.5])
    assert loaded.target_context is not None
    assert loaded.target_context.selected_target == "Moisture"
    assert loaded.meta["selected_target"] == "Moisture"
    assert loaded.meta["csv.target_column"] == "Moisture"
    assert loaded.meta["csv.target_type"] == "continuous"


def test_file_load_rejects_an_unknown_explicit_target(tmp_path: Path) -> None:
    path = tmp_path / "spectra.csv"
    path.write_text("sample_id,1000,1100\na,1.0,2.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Target column 'Protein'"):
        FileLoadNode("source", {"experiment_id": 1, "file_id": 2})._load_file(
            path,
            selected_target="Protein",
            target_type="continuous",
        )


def test_file_load_rejects_unknown_formats(tmp_path: Path) -> None:
    path = tmp_path / "vendor.unknown"
    path.write_bytes(b"not interpreted")

    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    with pytest.raises(ValueError, match="does not admit"):
        node._load_file(str(path))


@pytest.mark.parametrize("suffix", [".spa", ".spg"])
def test_file_load_admits_vendor_extensions_but_refuses_unrecognized_bytes(tmp_path: Path, suffix: str) -> None:
    """OMNIC is a qualified native reader, so admission moves from the extension to the bytes.

    The canonical source node no longer refuses these extensions outright.  A
    file that merely claims the extension is refused by structural probe
    instead, which is the stronger check.
    """
    path = tmp_path / f"vendor{suffix}"
    path.write_bytes(b"not interpreted")

    node = FileLoadNode("source", {"experiment_id": 1, "file_id": 2})
    with pytest.raises(ValueError, match="structurally recognizes"):
        node._load_file(str(path))


def test_prototype_source_nodes_are_not_promoted_into_the_canonical_contract() -> None:
    for node_type in ("data.source", "data.my_dataset"):
        with pytest.raises(KeyError, match="Unknown node type"):
            node_registry.get_metadata(node_type)
