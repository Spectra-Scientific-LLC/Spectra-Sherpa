"""Canonical contract, byte-binding, and scientific-shape proofs for data sources."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection, collection_manifest
from spectra_sherpa.app.lib.collection_definition import (
    COLLECTION_DEFINITION_SCHEMA,
    apply_collection_definition,
    scientific_collection_identity,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    FeatureAxis,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
    TimeAxis,
)
from spectra_sherpa.app.services import project_data_sources
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data import loaders as data_loaders
from spectra_sherpa.app.services.dag.nodes.data import references, source_contracts
from spectra_sherpa.app.services.dag.nodes.data.loaders import CollectionLoadNode, LoadGroupNode
from spectra_sherpa.app.services.dag.nodes.data.references import NISTLibraryNode
from spectra_sherpa.app.services.dag.nodes.data.synthetic import SyntheticCurveNode
from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver
from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.core.execution_runtime import (
    ExecutionRuntime,
    ResolvedExperimentCollection,
    ResolvedExperimentFile,
)
from spectra_sherpa.core.spectra_meta import get_spectra_meta
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.io import registry as ingestion_registry
from spectra_sherpa.io.types import SourceMember
from tests.performance_contract import PerformanceCeiling

_TEST_MANIFEST_LIMITS = {
    "max_members": 10,
    "max_file_bytes": 1024 * 1024,
    "max_total_bytes": 2 * 1024 * 1024,
}


@pytest.mark.parametrize(
    ("node_type", "runtime_family", "capabilities", "output_count"),
    [
        ("data.collection_load", RuntimeFamily.SHERPA_NATIVE.value, (WorkerCapability.READ_DATASET.value,), 2),
        ("data.load_group", RuntimeFamily.SHERPA_NATIVE.value, (WorkerCapability.READ_DATASET.value,), 1),
        ("data.nist_library", RuntimeFamily.SHERPA_NATIVE.value, (WorkerCapability.READ_DATASET.value,), 1),
        ("data.synthetic_curve", RuntimeFamily.SHERPA_NATIVE.value, (), 1),
    ],
)
def test_canonical_data_source_contracts_are_local_and_explicit(
    node_type: str,
    runtime_family: str,
    capabilities: tuple[str, ...],
    output_count: int,
) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["runtime_family"] == runtime_family
    assert contract.payload["lifecycle_kind"] == LifecycleKind.DATA_SOURCE.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == capabilities
    assert contract.payload["semantic_inputs"] == ()
    assert len(contract.payload["semantic_outputs"]) == output_count
    assert metadata.policy is not None
    assert metadata.policy.data_egress_risk == "none"


def test_collection_load_exposes_binding_action_without_editable_internal_ids() -> None:
    metadata = node_registry.get_metadata("data.collection_load")
    parameters = {parameter.name: parameter for parameter in metadata.parameters}

    assert {
        "experiment_id",
        "stage",
        "asset_id",
        "selected_file_ids",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "target_authority",
        "group_column",
    } <= {name for name, parameter in parameters.items() if parameter.category == "internal"}


@pytest.mark.parametrize(
    ("node_type", "implementation_modules"),
    [
        ("data.file_load", ingestion_registry.native_implementation_modules()),
        ("data.collection_load", ingestion_registry.native_implementation_modules()),
        ("data.load_group", ingestion_registry.native_implementation_modules()),
        ("data.nist_library", ingestion_registry.jcamp_implementation_modules()),
    ],
)
def test_registry_consuming_nodes_digest_bind_their_parser_closure(
    node_type: str,
    implementation_modules: tuple[object, ...],
) -> None:
    """A delegated parser change must change every consuming node identity."""

    contract = node_registry.get_metadata(node_type).resolved_execution_contract()
    component_ids = {item["component_id"] for item in contract.payload["implementation_components"]}
    expected = {module.__name__ for module in implementation_modules}
    assert expected <= component_ids
    assert ingestion_registry.__name__ in component_ids
    if node_type == "data.file_load":
        assert "spectra_sherpa.app.lib.data_formats" in component_ids
        assert "spectra_sherpa.app.services.dag.io_contracts" in component_ids
    if node_type in {"data.collection_load", "data.load_group"}:
        assert "spectra_sherpa.app.lib.sample_labels" in component_ids
        assert "spectra_sherpa.app.lib.collection_assembly" in component_ids
        assert "spectra_sherpa.core.prepared_data" in component_ids
    if node_type != "data.nist_library":
        assert "spectra_sherpa.io.formats.scp_temporary" not in component_ids
        assert "distribution.h5py" in component_ids
        assert {item["distribution"]: item["version"] for item in contract.payload["runtime_requirements"]}[
            "h5py"
        ] == "3.16.0"


def test_native_parser_closure_covers_every_registered_native_plugin() -> None:
    declared = {module.__name__ for module in ingestion_registry.native_implementation_modules()}
    registered = {plugin.__class__.__module__ for plugin in ingestion_registry.builtin_registry.plugins}
    assert registered <= declared


def test_source_manifest_is_order_independent_and_byte_bound(tmp_path: Path) -> None:
    first = tmp_path / "a.spa"
    second = tmp_path / "nested" / "b.spa"
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    manifest = source_contracts.file_manifest(tmp_path, [second, first], **_TEST_MANIFEST_LIMITS)
    reversed_manifest = source_contracts.file_manifest(tmp_path, [first, second], **_TEST_MANIFEST_LIMITS)

    assert manifest == reversed_manifest
    assert [member["path"] for member in manifest["members"]] == ["a.spa", "nested/b.spa"]

    second.write_bytes(b"changed")
    assert (
        source_contracts.file_manifest(tmp_path, [first, second], **_TEST_MANIFEST_LIMITS)["manifest_digest"]
        != manifest["manifest_digest"]
    )


def test_source_manifest_rejects_empty_duplicate_and_escaped_members(tmp_path: Path) -> None:
    member = tmp_path / "member.spa"
    member.write_bytes(b"member")
    escaped = tmp_path.parent / "escaped.spa"
    escaped.write_bytes(b"escaped")

    with pytest.raises(ValueError, match="at least one"):
        source_contracts.file_manifest(tmp_path, [], **_TEST_MANIFEST_LIMITS)
    with pytest.raises(ValueError, match="repeats"):
        source_contracts.file_manifest(tmp_path, [member, member], **_TEST_MANIFEST_LIMITS)
    with pytest.raises(ValueError, match="escapes"):
        source_contracts.file_manifest(tmp_path, [escaped], **_TEST_MANIFEST_LIMITS)


def _loaded_record(path: Path, dataset: SherpaDataset) -> data_loaders._LoadedDataset:
    return data_loaders._LoadedDataset(
        dataset=dataset,
        file_name=path.name,
        file_path=str(path),
        source_members=(
            SourceMember(
                name=path.name,
                sha256=source_contracts.sha256_file(path, max_bytes=1024 * 1024),
                size_bytes=path.stat().st_size,
            ),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("curve_type", ["sigmoid", "gaussian", "linear", "exponential", "step"])
async def test_synthetic_curve_is_deterministic_and_uses_physical_time(curve_type: str) -> None:
    parameters = {
        "curve_type": curve_type,
        "n_points": 128,
        "max_concentration": 2.0,
        "center": 0.5,
        "width": 0.1,
        "duration_seconds": 12.5,
    }
    first = await SyntheticCurveNode("curve", parameters).execute()
    second = await SyntheticCurveNode("curve", parameters).execute()

    assert isinstance(first, SherpaDataset)
    assert isinstance(first.feature_axis, TimeAxis)
    assert first.feature_axis.units == "s"
    assert first.feature_axis.values[0] == pytest.approx(0.0)
    assert first.feature_axis.values[-1] == pytest.approx(12.5)
    assert np.all(np.isfinite(first.X))
    np.testing.assert_array_equal(first.X, second.X)
    np.testing.assert_array_equal(first.feature_axis.values, second.feature_axis.values)


@pytest.mark.asyncio
async def test_synthetic_curve_live_and_generated_paths_share_one_typed_operation() -> None:
    parameters = {
        "curve_type": "gaussian",
        "n_points": 64,
        "max_concentration": 2.0,
        "center": 0.4,
        "width": 0.2,
        "duration_seconds": 8.0,
    }
    node = SyntheticCurveNode("curve", parameters)
    live = await node.execute()
    namespace: dict[str, object] = {"results": {}}
    exec("\n".join(node.generate_python({}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["curve"]  # type: ignore[index]

    assert isinstance(generated, SherpaDataset)
    np.testing.assert_array_equal(live.X, generated.X)
    np.testing.assert_array_equal(live.feature_axis.values, generated.feature_axis.values)
    assert live.feature_axis.units == generated.feature_axis.units == "s"
    assert get_spectra_meta(live) == get_spectra_meta(generated)


def test_synthetic_curve_rejects_unknown_and_irrelevant_settings() -> None:
    with pytest.raises(ValueError, match="curve_type"):
        node_registry.create_node("data.synthetic_curve", "curve", {"curve_type": "constant"})
    with pytest.raises(ValueError, match="non-default center or width"):
        node_registry.create_node(
            "data.synthetic_curve",
            "curve",
            {"curve_type": "linear", "center": 0.25},
        )
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node("data.synthetic_curve", "curve", {"seed": 42})


def test_synthetic_curve_meets_reviewed_absolute_performance_ceiling() -> None:
    parameters = {
        "curve_type": "gaussian",
        "n_points": 100_000,
        "max_concentration": 1.0,
        "center": 0.5,
        "width": 0.1,
        "duration_seconds": 60.0,
    }
    ceiling = PerformanceCeiling("data.synthetic_curve", "100000-point-gaussian", 2.0)
    with ceiling.measure():
        time_values, curve = source_contracts.generate_synthetic_curve(parameters)
    assert time_values.shape == curve.shape == (100_000,)


@pytest.mark.parametrize("library_id", [True, 0, -1, 1.5, "1"])
def test_nist_library_requires_an_exact_positive_entry_id(library_id: object) -> None:
    with pytest.raises(ValueError, match="library_id"):
        node_registry.create_node("data.nist_library", "nist", {"library_id": library_id})


@pytest.mark.parametrize("failure", ["short", "duplicate", "nonfinite", "xunits", "yunits", "technique", "title"])
def test_nist_jcamp_requires_a_supported_finite_spectral_domain(failure: str) -> None:
    x = np.asarray([1_000.0, 1_100.0])
    y = np.asarray([[0.1, 0.2]], dtype=float)
    xunits = "cm-1"
    yunits = "absorbance"
    technique = "IR"
    title = "Wavenumber"
    if failure == "short":
        x, y = x[:1], y[:, :1]
    elif failure == "duplicate":
        x = np.asarray([1_000.0, 1_000.0])
    elif failure == "nonfinite":
        x = np.asarray([1_000.0, float("nan")])
    elif failure == "xunits":
        xunits = None
    elif failure == "yunits":
        yunits = None
    elif failure == "technique":
        technique = None
    elif failure == "title":
        title = "Time"
    dataset = SherpaDataset(
        X=y,
        feature_axis=SpectralAxis(values=x, units=xunits, title=title),
        domain=DomainContext(technique=technique, data_quantity="Absorbance"),
        units=yunits,
    )
    with pytest.raises(ValueError):
        references._validated_jcamp_dataset(dataset)


class _ScalarResult:
    def __init__(self, entry: object) -> None:
        self._entry = entry

    def scalar_one_or_none(self) -> object:
        return self._entry


class _FakeSession:
    def __init__(self, entry: object) -> None:
        self._entry = entry

    async def execute(self, _query: object) -> _ScalarResult:
        return _ScalarResult(self._entry)

    async def scalar(self, _query: object) -> object:
        return self._entry


class _CollectionScalarResult:
    def __init__(self, entries: list[object]) -> None:
        self._entries = entries

    def all(self) -> list[object]:
        return self._entries


class _CollectionSession:
    def __init__(self, experiment: object, records: list[object]) -> None:
        self._experiment = experiment
        self._records = records

    async def scalar(self, _query: object) -> object:
        return self._experiment

    async def scalars(self, _query: object) -> _CollectionScalarResult:
        return _CollectionScalarResult(self._records)


@pytest.mark.asyncio
async def test_preloaded_collection_members_retain_exact_source_authority_for_subsetting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = 7
    experiment_root = tmp_path / "experiments" / "exp_007" / "raw"
    experiment_root.mkdir(parents=True)
    members = {
        "one.csv": b"wavenumber,absorbance\n1000,0.1\n900,0.2\n",
        "two.csv": b"wavenumber,absorbance\n1000,0.3\n900,0.4\n",
    }
    records = []
    for index, (name, content) in enumerate(members.items(), start=1):
        (experiment_root / name).write_bytes(content)
        records.append(
            SimpleNamespace(
                id=index,
                experiment_id=experiment_id,
                stage="raw",
                file_path=f"raw/{name}",
                file_size_bytes=len(content),
                created_at=SimpleNamespace(isoformat=lambda: "2026-09-02T00:00:00+00:00"),
            )
        )
    admitted = _spectral_dataset([0.1, 0.2])
    preloaded = SimpleNamespace(
        experiment_id=experiment_id,
        stage="raw",
        file_ids=[1, 2],
        dataset=admitted,
        asset_id="collection",
    )

    @asynccontextmanager
    async def fake_session():
        yield _CollectionSession(SimpleNamespace(id=experiment_id, name="Exact collection"), records)

    monkeypatch.setattr("spectra_sherpa.app.services.dataset_source_resolver.async_session", fake_session)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.settings",
        SimpleNamespace(data_dir=tmp_path),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.read_collection_definition",
        lambda _experiment_id: None,
    )

    resolved = await ApplicationDatasetSourceResolver(
        preloaded_datasets={"collection": preloaded}
    ).resolve_experiment_collection(experiment_id=experiment_id)

    assert resolved.preloaded_dataset is admitted
    assert [member.file_id for member in resolved.files] == [1, 2]
    assert [member.size_bytes for member in resolved.files] == [len(value) for value in members.values()]
    assert [member.sha256 for member in resolved.files] == [
        hashlib.sha256(value).hexdigest() for value in members.values()
    ]
    assert all(member.prepared_overrides is not None for member in resolved.files)


@pytest.mark.asyncio
async def test_nist_library_binds_exact_content_and_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "nist" / "entry.jdx"
    source.parent.mkdir()
    source.write_text(
        "##TITLE=Water\n"
        "##DATA TYPE=INFRARED SPECTRUM\n"
        "##XUNITS=1/CM\n"
        "##YUNITS=ABSORBANCE\n"
        "##FIRSTX=1200\n"
        "##LASTX=1000\n"
        "##DELTAX=-100\n"
        "##NPOINTS=3\n"
        "##XYDATA=(X++(Y..Y))\n"
        "1200 0.1 0.2 0.3\n"
        "##END=\n",
        encoding="ascii",
    )
    entry = SimpleNamespace(
        id=7,
        file_path="nist/entry.jdx",
        compound_name="Water",
        cas_number="7732-18-5",
        resolution="4 cm-1",
        nist_id="C7732185",
        molecular_formula="H2O",
    )

    @asynccontextmanager
    async def fake_session():
        yield _FakeSession(entry)

    monkeypatch.setattr("spectra_sherpa.app.services.dataset_source_resolver.async_session", fake_session)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.settings",
        SimpleNamespace(data_dir=tmp_path),
    )
    node = NISTLibraryNode("nist", {"library_id": 7})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=ApplicationDatasetSourceResolver()))
    dataset = await node.execute()

    assert isinstance(dataset, SherpaDataset)
    assert dataset.domain.technique == "IR"
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    assert dataset.get_extra("nist.content_sha256") == source_contracts.sha256_file(
        source,
        max_bytes=1024 * 1024,
    )
    assert dataset.get_extra("nist.cas_number") == "7732-18-5"


@pytest.mark.asyncio
async def test_nist_library_rejects_a_path_outside_its_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    escaped = tmp_path.parent / "escaped.jdx"
    escaped.write_bytes(b"escaped")
    entry = SimpleNamespace(id=7, file_path="../escaped.jdx")

    @asynccontextmanager
    async def fake_session():
        yield _FakeSession(entry)

    monkeypatch.setattr("spectra_sherpa.app.services.dataset_source_resolver.async_session", fake_session)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dataset_source_resolver.settings",
        SimpleNamespace(data_dir=tmp_path),
    )

    node = NISTLibraryNode("nist", {"library_id": 7})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=ApplicationDatasetSourceResolver()))
    with pytest.raises(ValueError, match="escapes"):
        await node.execute()


def _spectral_dataset(
    values: list[float],
    *,
    axis_units: str = "cm^-1",
    axis_title: str = "Wavenumber",
    signal_units: str = "absorbance",
):
    return SherpaDataset(
        X=np.asarray(values, dtype=np.float64).reshape(1, -1),
        feature_axis=SpectralAxis(
            values=np.linspace(1_000.0, 1_300.0, len(values)),
            units=axis_units,
            title=axis_title,
        ),
        domain=DomainContext(data_quantity="absorbance"),
        sample_axis=SampleAxis(labels=["sample"], title="Sample"),
        units=signal_units,
        data_role="X_spectra",
    )


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("axis_units", "nm", "X-axis validation"),
        ("axis_title", "Wavelength", "X-axis validation"),
        ("signal_units", "transmittance", "Signal-unit validation"),
    ],
)
def test_load_group_rejects_axis_or_signal_semantic_mismatch(
    attribute: str,
    value: str,
    message: str,
) -> None:
    reference = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    options = {attribute: value}
    mismatched = _spectral_dataset([2.0, 3.0, 4.0, 5.0], **options)

    with pytest.raises(ValueError, match=message):
        LoadGroupNode("group", {"folder_path": "/tmp"})._validate_axes_match(
            [reference, mismatched],
            ["reference.spa", "mismatched.spa"],
        )


def test_load_group_rejects_nonmonotonic_axis() -> None:
    dataset = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    dataset.feature_axis = SpectralAxis(
        values=np.asarray([1_000.0, 1_200.0, 1_100.0, 1_300.0]),
        units="cm^-1",
        title="Wavenumber",
    )
    with pytest.raises(ValueError, match="strictly monotonic"):
        LoadGroupNode("group", {"folder_path": "/tmp"})._validate_axes_match([dataset], ["bad.spa"])


def _targeted_spectrum(value: float, *, context: TargetContext) -> SherpaDataset:
    dataset = _spectral_dataset([value, value + 1.0, value + 2.0, value + 3.0])
    dataset.target = np.asarray([value], dtype=np.float64)
    dataset.target_context = context
    return dataset


@pytest.mark.parametrize(
    "changed_context",
    [
        TargetContext(target_type="continuous", target_name="protein", target_units="%"),
        TargetContext(target_type="ordinal", target_name="moisture", target_units="%"),
        TargetContext(target_type="continuous", target_name="moisture", target_units="g/L"),
        TargetContext(
            target_type="continuous",
            target_name="moisture",
            target_names=["moisture", "protein"],
            target_units="%",
            selected_target="protein",
        ),
        TargetContext(
            target_type="categorical",
            target_name="grade",
            n_classes=2,
            class_names=["A", "C"],
        ),
    ],
    ids=["name", "type", "units", "selected-target", "class-vocabulary"],
)
def test_load_group_rejects_any_target_context_mismatch(changed_context: TargetContext) -> None:
    reference_context = TargetContext(target_type="continuous", target_name="moisture", target_units="%")
    if changed_context.target_type == "categorical":
        reference_context = TargetContext(
            target_type="categorical",
            target_name="grade",
            n_classes=2,
            class_names=["A", "B"],
        )
    elif changed_context.selected_target is not None:
        reference_context = TargetContext(
            target_type="continuous",
            target_name="moisture",
            target_names=["moisture", "protein"],
            target_units="%",
            selected_target="moisture",
        )

    with pytest.raises(ValueError, match="incompatible target semantics"):
        assemble_collection(
            [
                CollectionMember(_targeted_spectrum(1.0, context=reference_context), "reference.csv", 1, "a" * 64),
                CollectionMember(_targeted_spectrum(999.0, context=changed_context), "mismatch.csv", 1, "b" * 64),
            ],
            title="target mismatch",
        )


def test_load_group_preserves_one_exact_shared_target_context() -> None:
    context = TargetContext(
        target_type="continuous",
        target_name="moisture",
        target_names=["moisture"],
        target_units="%",
        selected_target="moisture",
    )
    result = assemble_collection(
        [
            CollectionMember(_targeted_spectrum(1.0, context=context), "first.csv", 1, "a" * 64),
            CollectionMember(
                _targeted_spectrum(2.0, context=context.model_copy(deep=True)),
                "second.csv",
                1,
                "b" * 64,
            ),
        ],
        title="targets",
    )

    np.testing.assert_array_equal(result.target, [1.0, 2.0])
    assert result.target_context == context
    assert result.target_context is not context


def test_load_group_rejects_mixed_target_presence_and_response_shape() -> None:
    context = TargetContext(target_type="continuous", target_name="moisture", target_units="%")
    targeted = _targeted_spectrum(1.0, context=context)
    target_free = _spectral_dataset([2.0, 3.0, 4.0, 5.0])
    with pytest.raises(ValueError, match="target-bearing and target-free"):
        assemble_collection(
            [
                CollectionMember(targeted, "targeted.csv", 1, "a" * 64),
                CollectionMember(target_free, "target-free.csv", 1, "b" * 64),
            ],
            title="mixed targets",
        )

    two_response = _targeted_spectrum(2.0, context=context)
    two_response.target = np.asarray([[2.0, 3.0]])
    with pytest.raises(ValueError, match="target response shape"):
        assemble_collection(
            [
                CollectionMember(targeted, "one.csv", 1, "a" * 64),
                CollectionMember(two_response, "two.csv", 1, "b" * 64),
            ],
            title="shape mismatch",
        )


@pytest.mark.asyncio
async def test_load_group_is_deterministic_and_binds_exact_member_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, payload in (("sample_10.spa", b"ten"), ("sample_2.spa", b"two")):
        (tmp_path / name).write_bytes(payload)

    def load_member(path: Path, *, asset_id: str | None = None):
        assert asset_id is None
        offset = 10.0 if path.name == "sample_10.spa" else 2.0
        return _loaded_record(
            path,
            _spectral_dataset([offset, offset + 1.0, offset + 2.0, offset + 3.0]),
        )

    node = LoadGroupNode(
        "group",
        {
            "folder_path": str(tmp_path),
            "pattern": "*.spa",
            "recursive": False,
            "sort_by": "numeric_suffix",
            "group_title": "Ordered spectra",
        },
    )
    monkeypatch.setattr(node, "_load_single_file", load_member)

    dataset = await node.execute()
    metadata = get_spectra_meta(dataset)

    assert isinstance(dataset, SherpaDataset)
    np.testing.assert_array_equal(dataset.X[:, 0], [2.0, 10.0])
    assert metadata is not None
    manifest = metadata.custom["group_load_params"]["source_manifest"]
    assert [member["path"] for member in manifest["members"]] == ["sample_10.spa", "sample_2.spa"]
    assert len(manifest["manifest_digest"]) == 64


@pytest.mark.asyncio
async def test_load_group_meets_reviewed_absolute_performance_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(100):
        (tmp_path / f"sample_{index:03d}.spa").write_bytes(index.to_bytes(4, "big"))
    template = _spectral_dataset(np.linspace(0.0, 1.0, 400).tolist())
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.spa"})
    monkeypatch.setattr(
        node,
        "_load_single_file",
        lambda path, *, asset_id=None: _loaded_record(path, template.copy()),
    )

    with PerformanceCeiling("data.load_group", "100-files-by-400-features", 5.0).measure():
        result = await node.execute()

    assert result.X.shape == (100, 400)


@pytest.mark.asyncio
async def test_load_group_rejects_replace_parse_restore_source_attack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.csv"
    original_bytes = b"sample,1000,1100\nA,1,2\n"
    replacement_bytes = b"sample,1000,1100\nA,9,8\n"
    assert len(original_bytes) == len(replacement_bytes)
    source.write_bytes(original_bytes)

    original_loader = data_loaders._load_registry_asset

    def replace_parse_restore(*args: object, **kwargs: object):
        source.write_bytes(replacement_bytes)
        try:
            return original_loader(*args, **kwargs)
        finally:
            source.write_bytes(original_bytes)

    monkeypatch.setattr(data_loaders, "_load_registry_asset", replace_parse_restore)
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.csv"})

    with pytest.raises(ValueError, match="changed before their registry snapshots were admitted"):
        await node.execute()


@pytest.mark.asyncio
async def test_load_group_rejects_oversized_file_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "oversized.csv"
    source.write_bytes(b"123456")
    monkeypatch.setattr(
        data_loaders,
        "_LOAD_GROUP_PARSER_LIMITS",
        data_loaders.ParserLimits(max_source_bytes=5, max_probe_bytes=5),
    )
    monkeypatch.setattr(
        source_contracts,
        "sha256_file",
        lambda *_args, **_kwargs: pytest.fail("oversized source reached hashing"),
    )

    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.csv"})
    with pytest.raises(ValueError, match="limit is 5"):
        await node.execute()


@pytest.mark.asyncio
async def test_load_group_rejects_file_count_before_parser_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(3):
        (tmp_path / f"sample-{index}.csv").write_bytes(b"x")
    monkeypatch.setattr(data_loaders, "_LOAD_GROUP_MAX_FILES", 2)
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.csv"})
    monkeypatch.setattr(
        node,
        "_load_single_file",
        lambda _path: pytest.fail("over-count group reached parser execution"),
    )

    with pytest.raises(ValueError, match="3 files; limit is 2"):
        await node.execute()


@pytest.mark.asyncio
async def test_load_group_rejects_aggregate_source_bytes_before_hashing_or_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(2):
        (tmp_path / f"sample-{index}.csv").write_bytes(b"123456")
    monkeypatch.setattr(data_loaders, "_LOAD_GROUP_MAX_SOURCE_BYTES", 10)
    monkeypatch.setattr(
        source_contracts,
        "sha256_file",
        lambda *_args, **_kwargs: pytest.fail("over-byte group reached hashing"),
    )
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.csv"})
    monkeypatch.setattr(
        node,
        "_load_single_file",
        lambda _path: pytest.fail("over-byte group reached parser execution"),
    )

    with pytest.raises(ValueError, match="aggregate limit is 10"):
        await node.execute()


@pytest.mark.asyncio
async def test_load_group_rejects_aggregate_decoded_bytes_before_concatenation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(2):
        (tmp_path / f"sample-{index}.csv").write_bytes(b"source")
    monkeypatch.setattr(data_loaders, "_LOAD_GROUP_MAX_DECODED_BYTES", 100)
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.csv"})
    monkeypatch.setattr(
        node,
        "_load_single_file",
        lambda path, *, asset_id=None: _loaded_record(path, _spectral_dataset([1.0, 2.0, 3.0, 4.0])),
    )
    monkeypatch.setattr(
        data_loaders.np,
        "vstack",
        lambda *_args, **_kwargs: pytest.fail("over-byte group reached concatenation"),
    )

    with pytest.raises(ValueError, match="decoded bytes; limit is 100"):
        await node.execute()


@pytest.mark.asyncio
async def test_load_group_counts_array_backed_synthetic_ground_truth_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "synthetic.npz"
    source.write_bytes(b"source")
    fixture = (
        Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "synthetic" / "Synthetic_atmospheric-6.npz"
    )
    dataset = ingestion_registry.ingest(fixture).assets[0].dataset
    spectra = dataset.get_extra("ground_truth.spectra")
    assert isinstance(spectra, np.ndarray)
    assert dataset.get_extra("synthetic.S") is None
    assert dataset.get_extra("synthetic.C") is None
    elements, decoded_bytes = data_loaders._retained_numeric_footprint(dataset)

    # A second metadata reference to the same array must not inflate the
    # retained numeric projection. The new mapping entry itself is charged.
    dataset.set_extra("test.same_ground_truth_authority", spectra)
    repeated_elements, repeated_bytes = data_loaders._retained_numeric_footprint(dataset)
    assert repeated_elements == elements
    assert decoded_bytes < repeated_bytes < decoded_bytes + 1024

    monkeypatch.setattr(data_loaders, "_LOAD_GROUP_MAX_DECODED_BYTES", repeated_bytes - 1)
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.npz"})
    monkeypatch.setattr(
        node,
        "_load_single_file",
        lambda path, *, asset_id=None: _loaded_record(path, dataset),
    )
    monkeypatch.setattr(
        data_loaders.np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("over-byte synthetic group reached concatenation"),
    )

    with pytest.raises(ValueError, match="decoded bytes; limit is"):
        await node.execute()


def test_load_group_rejects_deprecated_escape_hatches() -> None:
    parameters = {"folder_path": "/tmp/spectra", "validate_axes": False}
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node("data.load_group", "group", parameters)
    with pytest.raises(ValueError, match="sort_by"):
        node_registry.create_node(
            "data.load_group",
            "group",
            {"folder_path": "/tmp/spectra", "sort_by": "modified_time"},
        )


def test_collection_assembly_preserves_the_complete_sample_table() -> None:
    first = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    first.sample_axis = SampleAxis(
        labels=["a"],
        title="Sample",
        sample_table={"specimen_id": ["A"], "block": [1]},
    )
    second = _spectral_dataset([5.0, 6.0, 7.0, 8.0])
    second.sample_axis = SampleAxis(
        labels=["b"],
        title="Sample",
        sample_table={"specimen_id": ["B"], "block": [2]},
    )
    members = [
        CollectionMember(first, "a.spa", 1, "a" * 64),
        CollectionMember(second, "b.spa", 1, "b" * 64),
    ]

    result = assemble_collection(members, title="collection")

    assert result.sample_axis.sample_table == {"specimen_id": ["A", "B"], "block": [1, 2]}
    assert result.sample_axis.labels == ["a", "b"]


def test_collection_assembly_preserves_explicit_single_sample_identities() -> None:
    first = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    first.sample_axis = SampleAxis(labels=["specimen-A"], title="Sample")
    second = _spectral_dataset([5.0, 6.0, 7.0, 8.0])
    second.sample_axis = SampleAxis(labels=["specimen-B"], title="Sample")
    members = [
        CollectionMember(first, "raw-001.spa", 1, "a" * 64),
        CollectionMember(second, "raw-002.spa", 1, "b" * 64),
    ]

    result = assemble_collection(members, title="collection")

    assert result.sample_axis.labels == ["specimen-A", "specimen-B"]
    second.sample_axis = SampleAxis(labels=["specimen-A"], title="Sample")
    with pytest.raises(ValueError, match="duplicate sample identities"):
        assemble_collection(members, title="collection")


def test_collection_assembly_preserves_aligned_exclusion_reasons() -> None:
    first = _spectral_dataset([1.0, 2.0])
    first.sample_axis = SampleAxis(
        labels=["first"],
        title="Sample",
        include_mask=np.asarray([False]),
        exclusion_reasons=["saturated"],
    )
    second = _spectral_dataset([3.0, 4.0])
    second.sample_axis = SampleAxis(
        labels=["second"],
        title="Sample",
        include_mask=np.asarray([True]),
    )
    third = _spectral_dataset([5.0, 6.0])
    third.sample_axis = SampleAxis(
        labels=["third"],
        title="Sample",
        include_mask=np.asarray([False]),
        exclusion_reasons=["saturated"],
    )

    result = assemble_collection(
        [
            CollectionMember(first, "first.spa", 1, "a" * 64),
            CollectionMember(second, "second.spa", 1, "b" * 64),
            CollectionMember(third, "third.spa", 1, "c" * 64),
        ],
        title="collection",
    )

    assert result.sample_axis.include_mask.tolist() == [False, True, False]
    assert result.sample_axis.exclusion_reasons == ["saturated", None, "saturated"]


def test_collection_budget_charges_long_exclusion_reasons_before_concatenation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.lib import collection_assembly

    dataset = _spectral_dataset([1.0, 2.0])
    dataset.sample_axis = SampleAxis(
        labels=["first"],
        title="Sample",
        include_mask=np.asarray([False]),
        exclusion_reasons=["x" * 20_000],
    )
    member = CollectionMember(dataset, "first.spa", 1, "a" * 64)
    monkeypatch.setattr(collection_assembly, "MAX_COLLECTION_RETAINED_BYTES", 10_000)
    monkeypatch.setattr(
        collection_assembly.np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("over-budget reason reached concatenation"),
    )

    with pytest.raises(ValueError, match="retained-data limit"):
        assemble_collection([member], title="collection")


def test_collection_assembly_preserves_exact_inner_axes_and_member_metadata() -> None:
    ground_truth = np.asarray([[1.0, 2.0]], dtype=np.float64)
    members = []
    for index in range(2):
        dataset = SherpaDataset(
            X=np.arange(6, dtype=np.float64).reshape(1, 2, 3) + index,
            feature_axis=SpectralAxis(
                values=np.asarray([1000.0, 1001.0, 1002.0]),
                units="cm^-1",
                quantity=AxisQuantity.WAVENUMBER,
            ),
            sample_axis=SampleAxis(labels=[f"sample-{index}"], title="Sample"),
            axes={1: TimeAxis(values=np.asarray([0.0, 1.0]), units="s", title="Delay")},
            domain=DomainContext(data_quantity="absorbance"),
            extra={"ground_truth.spectra": ground_truth, "scientist.annotation": f"member-{index}"},
            title=f"Member {index}",
            units="absorbance",
            data_role="X_spectra",
        )
        members.append(CollectionMember(dataset, f"member-{index}.npz", 1, str(index) * 64))

    result = assemble_collection(members, title="collection")

    assert result.shape == (2, 2, 3)
    assert isinstance(result.inner_axes[1], TimeAxis)
    np.testing.assert_array_equal(result.inner_axes[1].values, [0.0, 1.0])
    metadata = result.meta["source_member_metadata"]
    assert [entry["file_name"] for entry in metadata] == ["member-0.npz", "member-1.npz"]
    assert [entry["title"] for entry in metadata] == ["Member 0", "Member 1"]
    assert [entry["metadata"]["scientist.annotation"] for entry in metadata] == ["member-0", "member-1"]
    np.testing.assert_array_equal(metadata[0]["metadata"]["ground_truth.spectra"], ground_truth)

    mismatched = members[1].dataset
    mismatched._axes[1] = TimeAxis(values=np.asarray([0.0, 2.0]), units="s", title="Delay")
    with pytest.raises(ValueError, match="incompatible inner-axis values"):
        assemble_collection(members, title="collection")


def test_single_member_inspection_projection_is_unambiguous_and_wire_bounded(monkeypatch) -> None:
    from spectra_sherpa.app.api.v1.routes.builder import _project_single_member_metadata
    from spectra_sherpa.app.services.dag import serialize as dag_serialize

    canonical = {
        "contents_stage": "synthetic",
        "api_serialization": {"mode": "full", "full_dataset_handle": "dataset-1"},
        "source_member_metadata": [
            {
                "metadata": {
                    "contents_stage": "wrong",
                    "recipe": {"payload": list(range(20))},
                }
            }
        ],
    }
    result = {
        "type": "SherpaDataset",
        "dataset_id": "dataset-1",
        "shape": [1, 90],
        "data": [list(range(90))],
        "metadata": canonical,
    }
    _project_single_member_metadata(canonical, contents_file_count=1)
    assert canonical["contents_stage"] == "synthetic"
    assert canonical["recipe"]["payload"] == list(range(20))

    monkeypatch.setattr(dag_serialize, "API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS", 100)
    finalized = dag_serialize.finalize_api_dataset_response(result)
    assert finalized["metadata"]["api_serialization"]["mode"] == "handle_only"
    assert finalized["metadata"]["preview_unavailable_reason"] == "aggregate_wire_numeric_element_ceiling"
    assert finalized["data"] == []

    multi_metadata = {
        "source_member_metadata": [
            {"metadata": {"recipe": {"member": 1}}},
            {"metadata": {"recipe": {"member": 2}}},
        ]
    }
    _project_single_member_metadata(multi_metadata, contents_file_count=2)
    assert "recipe" not in multi_metadata


def test_collection_assembly_rejects_axis_and_dtype_coercion_in_any_order() -> None:
    spectral = _spectral_dataset([1.0, 2.0, 3.0])
    generic = _spectral_dataset([4.0, 5.0, 6.0])
    generic.feature_axis = FeatureAxis(
        values=np.asarray(spectral.feature_axis.values),
        units=spectral.feature_axis.units,
        title=spectral.feature_axis.title,
    )
    for ordered in ((spectral, generic), (generic, spectral)):
        with pytest.raises(ValueError, match="incompatible feature-axis type"):
            assemble_collection(
                [
                    CollectionMember(ordered[0], "first.csv", 1, "a" * 64),
                    CollectionMember(ordered[1], "second.csv", 1, "b" * 64),
                ],
                title="collection",
            )

    first = _targeted_spectrum(1.0, context=TargetContext(target_type="continuous"))
    second = _targeted_spectrum(2.0, context=TargetContext(target_type="continuous"))
    first.target = np.asarray([1], dtype=np.int64)
    second.target = np.asarray([2.0], dtype=np.float64)
    with pytest.raises(ValueError, match="incompatible target dtype"):
        assemble_collection(
            [
                CollectionMember(first, "first.csv", 1, "a" * 64),
                CollectionMember(second, "second.csv", 1, "b" * 64),
            ],
            title="collection",
        )

    first.target = second.target = None
    first_axis = first.sample_axis
    second_axis = second.sample_axis
    assert first_axis is not None and second_axis is not None
    first_axis.values = np.asarray([1], dtype=np.int64)
    second_axis.values = np.asarray([2.0], dtype=np.float64)
    first.sample_axis = first_axis
    second.sample_axis = second_axis
    with pytest.raises(ValueError, match="incompatible sample-coordinate dtype"):
        assemble_collection(
            [
                CollectionMember(first, "first.csv", 1, "a" * 64),
                CollectionMember(second, "second.csv", 1, "b" * 64),
            ],
            title="collection",
        )

    first_axis.values = second_axis.values = None
    first_axis.classes = np.asarray([1], dtype=np.int64)
    second_axis.classes = np.asarray([2.0], dtype=np.float64)
    first.sample_axis = first_axis
    second.sample_axis = second_axis
    with pytest.raises(ValueError, match="incompatible sample-class dtype"):
        assemble_collection(
            [
                CollectionMember(first, "first.csv", 1, "a" * 64),
                CollectionMember(second, "second.csv", 1, "b" * 64),
            ],
            title="collection",
        )


def test_collection_manifest_binds_prepared_read_semantics() -> None:
    from spectra_sherpa.app.lib.collection_assembly import prepared_data_digest

    dataset = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    source = CollectionMember(dataset, "raw/a.spa", 4, "a" * 64)
    prepared = CollectionMember(
        dataset,
        "raw/a.spa",
        4,
        "a" * 64,
        prepared_data_digest({"x_units": "cm-1"}),
    )

    assert collection_manifest([source])["manifest_digest"] != collection_manifest([prepared])["manifest_digest"]
    with pytest.raises(ValueError, match="invalid source identity"):
        collection_manifest([CollectionMember(dataset, "../a.spa", 4, "a" * 64)])
    with pytest.raises(ValueError, match="duplicate source names"):
        collection_manifest([source, CollectionMember(dataset, "RAW/A.SPA", 4, "b" * 64)])
    for noncanonical in ("raw\\a.spa", "raw//a.spa", "raw/./a.spa"):
        with pytest.raises(ValueError, match="invalid source identity"):
            collection_manifest([CollectionMember(dataset, noncanonical, 4, "b" * 64)])


def test_collection_budget_refuses_before_concatenation(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectra_sherpa.app.lib import collection_assembly

    dataset = _spectral_dataset([1.0, 2.0, 3.0, 4.0])
    member = CollectionMember(dataset, "a.spa", 4, "a" * 64)
    monkeypatch.setattr(collection_assembly, "MAX_COLLECTION_RETAINED_BYTES", 1)
    monkeypatch.setattr(
        np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("refused collection reached concatenation"),
    )

    with pytest.raises(ValueError, match="retained-data limit"):
        assemble_collection([member], title="oversized")


def test_single_member_budget_reuses_admitted_matrix_and_charges_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.lib import collection_assembly

    dataset = SherpaDataset(
        X=np.zeros((64, 229), dtype=np.float64),
        feature_axis=SpectralAxis(values=np.arange(229, dtype=np.float64), title="Wavelength", units="nm"),
        sample_axis=SampleAxis(labels=[f"pixel-{index}" for index in range(64)], title="Pixel"),
        data_role="X_spectra",
    )
    member = CollectionMember(dataset, "image.mat", dataset.X.nbytes, "a" * 64, asset_id="image")

    input_elements, input_bytes = collection_assembly.dataset_retained_footprint(dataset)
    projected_elements, projected_bytes = collection_assembly.collection_retained_footprint([member])
    assert projected_elements == input_elements
    assert projected_bytes == input_bytes + 4096
    collection_assembly.require_collection_budget([member])
    monkeypatch.setattr(
        collection_assembly.np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("singleton assembly allocated an output matrix"),
    )
    admitted = assemble_collection([member], title="Image source")
    assert admitted is dataset
    assert admitted.X is dataset.X
    assert admitted.meta["source_collection"]["file_count"] == 1
    assert collection_assembly.dataset_retained_footprint(admitted)[1] <= projected_bytes

    monkeypatch.setattr(collection_assembly, "MAX_COLLECTION_RETAINED_BYTES", projected_bytes - 1)
    with pytest.raises(ValueError, match="retained-data limit"):
        assemble_collection([member], title="Over budget")


def test_collection_budget_charges_array_backed_metadata_before_concatenation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.lib import collection_assembly

    members = []
    for index in range(2):
        dataset = _spectral_dataset([1.0, 2.0])
        dataset.meta["ground_truth"] = np.zeros(10_000, dtype=np.float64)
        members.append(CollectionMember(dataset, f"{index}.spa", 1, str(index) * 64))
    monkeypatch.setattr(collection_assembly, "MAX_COLLECTION_RETAINED_BYTES", 10_000)
    monkeypatch.setattr(
        collection_assembly.np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("over-budget metadata reached concatenation"),
    )

    with pytest.raises(ValueError, match="retained-data limit"):
        assemble_collection(members, title="oversized metadata")


def test_collection_budget_charges_output_projection_before_concatenation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.lib import collection_assembly

    members = []
    for index in range(2):
        dataset = SherpaDataset(
            X=np.zeros((50, 100), dtype=np.float64),
            feature_axis=SpectralAxis(values=np.arange(100, dtype=np.float64), units="cm^-1"),
            sample_axis=SampleAxis(labels=[f"{index}-{row}" for row in range(50)], title="Sample"),
            domain=DomainContext(data_quantity="absorbance"),
            units="absorbance",
            data_role="X_spectra",
        )
        members.append(CollectionMember(dataset, f"{index}.spa", 1, str(index) * 64))
    input_bytes = sum(collection_assembly.dataset_retained_footprint(member.dataset)[1] for member in members)
    _, projected_bytes = collection_assembly.collection_retained_footprint(members)
    assert projected_bytes > input_bytes
    monkeypatch.setattr(
        collection_assembly,
        "MAX_COLLECTION_RETAINED_BYTES",
        input_bytes + (projected_bytes - input_bytes) // 2,
    )
    monkeypatch.setattr(
        collection_assembly.np,
        "concatenate",
        lambda *_args, **_kwargs: pytest.fail("over-budget output reached concatenation"),
    )

    with pytest.raises(ValueError, match="retained-data limit"):
        assemble_collection(members, title="oversized output")


@pytest.mark.asyncio
async def test_project_collection_source_is_manifest_bound_and_fail_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [tmp_path / "a.spa", tmp_path / "b.spa"]
    for path, payload in zip(paths, (b"first", b"second"), strict=True):
        path.write_bytes(payload)
    resolved = tuple(
        ResolvedExperimentFile(
            path=str(path),
            original_file_path=f"raw/{path.name}",
            created_datetime=f"2026-08-24T00:00:0{index}+00:00",
            file_id=index,
            stage="raw",
            size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for index, path in enumerate(paths, 1)
    )

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id: int, stage: str = "raw"):
            assert experiment_id == 7
            assert stage == "raw"
            return ResolvedExperimentCollection(7, "Exact collection", resolved)

    def load_member(_self, file_path, **_kwargs):
        path = Path(file_path)
        offset = 1.0 if path.name == "a.spa" else 5.0
        return _loaded_record(path, _spectral_dataset([offset, offset + 1, offset + 2, offset + 3]))

    monkeypatch.setattr(data_loaders.ExperimentDatasetReader, "_load_file", load_member)
    expected = collection_manifest(
        [
            CollectionMember(
                dataset=_spectral_dataset([offset, offset + 1, offset + 2, offset + 3]),
                file_name=source.original_file_path,
                size_bytes=int(source.size_bytes),
                sha256=str(source.sha256),
            )
            for source, offset in zip(resolved, (1.0, 5.0), strict=True)
        ]
    )
    parameters = {
        "source_mode": "experiment_collection",
        "experiment_id": 7,
        "stage": "raw",
        "asset_id": "spectrum",
        "source_manifest_sha256": expected["manifest_digest"],
    }
    node = LoadGroupNode("group", parameters)
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))

    result = await node.execute()

    assert result.shape == (2, 4)
    assert result.sample_axis.labels == ["a 001", "b 001"]
    assert get_spectra_meta(result).custom["source_collection"]["manifest_digest"] == expected["manifest_digest"]

    wrong = LoadGroupNode("wrong", {**parameters, "source_manifest_sha256": "0" * 64})
    wrong.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))
    with pytest.raises(ValueError, match="saved source manifest"):
        await wrong.execute()

    def fail_second(_self, file_path, **kwargs):
        if Path(file_path).name == "b.spa":
            raise ValueError("corrupt second member")
        return load_member(_self, file_path, **kwargs)

    monkeypatch.setattr(data_loaders.ExperimentDatasetReader, "_load_file", fail_second)
    failed = LoadGroupNode("failed", parameters)
    failed.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))
    with pytest.raises(ValueError, match="corrupt second member"):
        await failed.execute()


@pytest.mark.asyncio
async def test_collection_load_preserves_exact_members_and_attaches_declared_supervision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [tmp_path / "a.spa", tmp_path / "b.spa"]
    for path, payload in zip(paths, (b"first", b"second"), strict=True):
        path.write_bytes(payload)
    resolved = tuple(
        ResolvedExperimentFile(
            path=str(path),
            original_file_path=f"raw/{path.name}",
            created_datetime=f"2026-09-01T00:00:0{index}+00:00",
            file_id=index,
            stage="raw",
            size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for index, path in enumerate(paths, 1)
    )

    def load_member(_self, file_path, **_kwargs):
        path = Path(file_path)
        index = 0 if path.name == "a.spa" else 1
        dataset = _spectral_dataset([1.0 + index, 2.0 + index, 3.0 + index, 4.0 + index])
        dataset.sample_axis = SampleAxis(
            labels=[f"sample-{index + 1}"],
            title="Sample",
            sample_table={
                "sample_id": [f"sample-{index + 1}"],
                "claimed_botanical_group": ["angustifolia" if index == 0 else "intermedia"],
                "block": [index + 1],
            },
        )
        return _loaded_record(path, dataset)

    monkeypatch.setattr(data_loaders.ExperimentDatasetReader, "_load_file", load_member)
    members = [
        CollectionMember(
            dataset=load_member(None, source.path).dataset,
            file_name=source.original_file_path,
            size_bytes=int(source.size_bytes),
            sha256=str(source.sha256),
            asset_id="single-auto",
        )
        for source in resolved
    ]
    expected = collection_manifest(members)
    columns = ["sample_id", "specimen_id", "block", "claimed_botanical_group"]
    definition = validate_collection_definition(
        {
            "schema_version": COLLECTION_DEFINITION_SCHEMA,
            "columns": columns,
            "collection": {
                "dataset_id": "selection-test/1",
                "title": "Selected collection",
                "units": "absorbance",
                "data_role": "X_spectra",
                "domain": DomainContext(
                    technique="IR",
                    expected_units="cm-1",
                    data_quantity="absorbance",
                ).model_dump(mode="json", exclude_none=False),
                "sample_axis": {"title": "Sample", "units": None, "values_policy": "omit"},
            },
            "rows": [
                {
                    "file_name": source.original_file_path,
                    "sha256": source.sha256,
                    "asset_id": "single-auto",
                    "source_row_index": 0,
                    "sample_id": f"sample-{index}",
                    "annotations": {
                        "sample_id": f"sample-{index}",
                        "specimen_id": f"specimen-{index}",
                        "block": index,
                        "claimed_botanical_group": "angustifolia" if index == 1 else "intermedia",
                    },
                }
                for index, source in enumerate(resolved, 1)
            ],
        }
    )
    defined = apply_collection_definition(members, definition)
    identity = scientific_collection_identity(expected, definition, defined)

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id: int, stage: str = "raw"):
            assert experiment_id == 7
            assert stage == "raw"
            return ResolvedExperimentCollection(
                7,
                "Selected collection",
                resolved,
                collection_definition_bytes=definition.canonical_bytes,
            )

    node = CollectionLoadNode(
        "collection",
        {
            "experiment_id": 7,
            "stage": "raw",
            "selected_file_ids": ["1", "2"],
            "source_manifest_sha256": expected["manifest_digest"],
            "collection_definition_sha256": definition.sha256,
            "scientific_collection_sha256": identity["scientific_collection_sha256"],
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "claimed_botanical_group",
                "target_type": "categorical",
                "units": None,
                "source_digest": identity["scientific_collection_sha256"],
            },
            "group_column": "block",
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))

    result = await node.execute()

    assert result["default"].shape == (2, 4)
    assert result["target"].tolist() == ["angustifolia", "intermedia"]
    assert result["default"].target_context.selected_target == "claimed_botanical_group"
    assert result["default"].meta["supervision_binding"]["group_column"] == "block"


def test_load_group_rejects_unqualified_vendor_format_before_reader_execution(tmp_path: Path) -> None:
    path = tmp_path / "legacy.srsx"
    path.write_bytes(b"not parsed")
    node = LoadGroupNode("group", {"folder_path": str(tmp_path), "pattern": "*.srsx"})

    with pytest.raises(ValueError, match="not directly readable yet"):
        node._load_single_file(path)


def test_group_source_fingerprint_covers_every_read_semantic() -> None:
    base = {
        "node_type": "data.load_group",
        "node_id": "source",
        "parameters": {
            "folder_path": "/data/spectra",
            "pattern": "*.spa",
            "recursive": False,
            "sort_by": "filename",
        },
    }
    changed = {
        **base,
        "parameters": {**base["parameters"], "recursive": True},
    }
    first = project_data_sources.describe_node_data_source(base)
    second = project_data_sources.describe_node_data_source(changed)
    assert first is not None and second is not None
    assert first.fingerprint != second.fingerprint

    explicit_asset = {
        **base,
        "parameters": {**base["parameters"], "asset_id": "a"},
    }
    selected = project_data_sources.describe_node_data_source(explicit_asset)
    assert selected is not None
    assert selected.fingerprint != first.fingerprint
    assert selected.metadata["asset_id"] == "a"
    assert first.metadata["asset_selection"] == "single-auto"

    project_collection = {
        **base,
        "parameters": {
            "source_mode": "experiment_collection",
            "experiment_id": 4,
            "stage": "raw",
            "asset_id": "spectrum",
            "source_manifest_sha256": "a" * 64,
        },
    }
    changed_manifest = {
        **project_collection,
        "parameters": {**project_collection["parameters"], "source_manifest_sha256": "b" * 64},
    }
    bound = project_data_sources.describe_node_data_source(project_collection)
    changed_bound = project_data_sources.describe_node_data_source(changed_manifest)
    assert bound is not None and changed_bound is not None
    assert bound.source_type == "upload"
    assert bound.fingerprint != changed_bound.fingerprint
    assert bound.metadata["source_manifest_sha256"] == "a" * 64
    assert (
        project_data_sources.describe_node_data_source(
            {
                **project_collection,
                "parameters": {**project_collection["parameters"], "source_manifest_sha256": "A" * 64},
            }
        )
        is None
    )
    assert (
        project_data_sources.describe_node_data_source(
            {**project_collection, "parameters": {**project_collection["parameters"], "source_mode": "legacy"}}
        )
        is None
    )


def test_file_source_fingerprint_distinguishes_exact_scientific_assets() -> None:
    base = {
        "node_type": "data.file_load",
        "node_id": "source",
        "parameters": {"experiment_id": 4, "file_id": 9, "stage": "raw"},
    }
    absorbance = {**base, "parameters": {**base["parameters"], "asset_id": "a"}}
    reference = {**base, "parameters": {**base["parameters"], "asset_id": "rf"}}

    automatic = project_data_sources.describe_node_data_source(base)
    selected_a = project_data_sources.describe_node_data_source(absorbance)
    selected_rf = project_data_sources.describe_node_data_source(reference)

    assert automatic is not None and selected_a is not None and selected_rf is not None
    assert len({automatic.fingerprint, selected_a.fingerprint, selected_rf.fingerprint}) == 3
    assert automatic.metadata["asset_selection"] == "single-auto"
    assert selected_a.metadata["asset_id"] == "a"
    assert selected_rf.metadata["asset_id"] == "rf"


def test_project_collection_identity_remaps_only_the_project_local_experiment() -> None:
    from spectra_sherpa.app.api.v1.routes.projects import _remap_source_ref, _remap_workflow_parameters

    parameters = {
        "source_mode": "experiment_collection",
        "experiment_id": 4,
        "stage": "raw",
        "asset_id": "spectrum",
        "source_manifest_sha256": "c" * 64,
    }
    remapped = _remap_workflow_parameters(parameters, {}, {4: 14}, {})

    assert remapped == {**parameters, "experiment_id": 14}
    assert (
        _remap_source_ref(
            f"experiment:4:collection:raw:asset:spectrum:manifest:{'c' * 64}",
            {4: 14},
            {},
        )
        == f"experiment:14:collection:raw:asset:spectrum:manifest:{'c' * 64}"
    )
