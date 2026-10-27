"""Canonical partitioned loading, explicit averaging and wide peak tables."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import h5py
import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.presentation_contract import NodePresentationContract, ScientificPresentation
from spectra_sherpa.core.time_series_portfolio import AveragingParameters, TimeSeriesPortfolio, acquisition_batches
from spectra_sherpa.io.registry import builtin_registry

ANY = "spectrasherpa://types/Any/1.0"
SPECTRA = "spectrasherpa://types/SpectralDataset/1.0"
PIN = [
    NodeParameter("project_id", "Project", "number", default=None, required=True),
    NodeParameter("portfolio_id", "Portfolio", "number", default=None, required=True),
    NodeParameter("selection_sha256", "Selection SHA-256", "text", default="", required=True),
]


def _digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pin(parameters):
    for key in ("project_id", "portfolio_id"):
        if type(parameters.get(key)) is not int or parameters[key] < 1:
            raise ValueError(f"{key} must be an exact positive integer")
    digest = parameters.get("selection_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("An exact immutable selection SHA-256 is required")
    return {k: parameters[k] for k in ("project_id", "portfolio_id", "selection_sha256")}


@register_node
class PortfolioLoadNode(Node):
    metadata = NodeMetadata(
        node_type="data.portfolio_load",
        category="data",
        label="Load Data · Portfolio",
        description="Resolve an immutable portfolio without materializing or averaging its time series.",
        presentation_contract=NodePresentationContract(
            default_presentation="default",
            presentations=(
                ScientificPresentation(
                    presentation_id="default",
                    label="Pinned portfolio",
                    kind="structured_record",
                    source_ports=("default",),
                    modes=("record",),
                ),
            ),
        ),
        parameters=PIN,
        input_types=[],
        output_type="Any",
        input_ports=[],
        output_ports=[
            PortMetadata(
                name="default", type_ref="spectrasherpa://types/PartitionedSource/1.0", label="Partitioned time series"
            )
        ],
        policy=NodePolicy(offload_to_pool=False),
    )

    async def execute(self, **kwargs):
        pin = _pin(self.parameters)
        resolver = self.require_execution_runtime().require_dataset_source_resolver()
        receipt = TimeSeriesPortfolio.model_validate(await resolver.resolve_time_series_portfolio(**pin))
        if receipt.sha256() != pin["selection_sha256"] or receipt.project_id != pin["project_id"]:
            raise ValueError("Portfolio receipt differs from the pinned selection")
        return NodeResult(outputs={"default": {"schema_version": "spectrasherpa-partitioned-source/1", **pin}})


@register_node
class PortfolioAverageNode(Node):
    metadata = NodeMetadata(
        node_type="preprocess.portfolio_average",
        category="preprocessing",
        label="Average · Portfolio",
        description=(
            "Stream equally weighted acquisitions by step, phase across cycles, or cycle and phase; "
            "choose mean or per-wavelength median. Wafers remain independent."
        ),
        parameters=PIN
        + [
            NodeParameter(
                "mode", "Average by", "select", default="step", options=["step", "phase_across_cycles", "cycle_phase"]
            ),
            NodeParameter("statistic", "Statistic", "select", default="mean", options=["mean", "median"]),
            NodeParameter("transition_trim_seconds", "Trim each phase boundary (s)", "number", default=0, min_value=0),
        ],
        input_types=["Any"],
        output_type="SpectralDataset",
        input_ports=[PortMetadata(name="default", type_ref=ANY, required=True)],
        output_ports=[PortMetadata(name="default", type_ref=SPECTRA)],
        policy=NodePolicy(offload_to_pool=False),
    )

    async def execute(self, default=None, **kwargs):
        pin = _pin(self.parameters)
        if default != {"schema_version": "spectrasherpa-partitioned-source/1", **pin}:
            raise ValueError("Connect Load Data for the same immutable portfolio")
        resolver = self.require_execution_runtime().require_dataset_source_resolver()
        receipt = TimeSeriesPortfolio.model_validate(await resolver.resolve_time_series_portfolio(**pin))
        if receipt.sha256() != pin["selection_sha256"]:
            raise ValueError("Portfolio changed")
        params = AveragingParameters(
            statistic=self.parameters.get("statistic", "mean"),
            mode=self.parameters.get("mode", "step"),
            transition_trim_seconds=self.parameters.get("transition_trim_seconds", 0),
        )
        lookup = files("spectra_sherpa").joinpath("data", "bosch_netcdf", "Dictionary_OES.nc")
        process_lookup = files("spectra_sherpa").joinpath("data", "bosch_netcdf", "Dictionary_process.nc")
        oes_hash = hashlib.sha256(lookup.read_bytes()).hexdigest()
        process_hash = hashlib.sha256(process_lookup.read_bytes()).hexdigest()
        verified = {}
        means = []
        rows = []
        feature_axis = None
        from importlib.resources import as_file

        with as_file(lookup) as dictionary_path, h5py.File(dictionary_path, "r") as dictionary:
            decoder = dictionary["data"][:]
            for partition in receipt.partitions:
                if partition.oes_dictionary_sha256 != oes_hash or partition.process_dictionary_sha256 != process_hash:
                    raise ValueError("Decoding dictionary differs from the saved portfolio")
                resolved = []
                for file_id, expected in [
                    (partition.file_id, partition.source_sha256),
                    (partition.process_file_id, partition.process_sha256),
                ]:
                    identity = (partition.experiment_id, file_id)
                    if identity not in verified:
                        source = await resolver.resolve_experiment_file(
                            experiment_id=partition.experiment_id, file_id=file_id, stage="raw"
                        )
                        if _digest(source.path) != expected:
                            raise ValueError("Source bytes differ from the saved portfolio")
                        verified[identity] = (source.path, expected)
                    path, digest = verified[identity]
                    if digest != expected:
                        raise ValueError("Conflicting portfolio source hashes")
                    resolved.append(path)
                # Native preflight validates the HDF5 schema and rejects external links.
                template = (
                    builtin_registry.ingest(
                        resolved[0], asset_id=partition.asset_id, rows=(partition.intervals[0].first - 1,)
                    )
                    .assets[0]
                    .dataset
                )
                if feature_axis is None:
                    feature_axis = template.feature_axis.model_copy(deep=True)
                elif not np.array_equal(feature_axis.values, template.feature_axis.values):
                    raise ValueError("Portfolio wavelengths differ; explicit alignment is required")
                sums = {}
                counts = {}
                times = {}
                # Exact median cannot be computed from batch medians. Retain encoded
                # values on temporary disk, then decode bounded wavelength blocks.
                spool_paths = {}
                spool_bytes = 0
                with (
                    TemporaryDirectory(prefix="sherpa-portfolio-median-") as scratch,
                    h5py.File(resolved[0], "r", rdcc_nbytes=64 * 1024 * 1024) as source,
                ):
                    group = source[partition.asset_id]
                    encoded_data = group["data"]
                    clock_data = group["times"]
                    for interval, batch in acquisition_batches(partition):
                        key = params.group_key(partition, interval)
                        if key not in sums:
                            if (len(means) + len(sums) + 1) * template.n_features > 16_000_000:
                                raise ValueError(
                                    "Averaged output exceeds the bounded matrix limit; partition the portfolio"
                                )
                            sums[key] = np.zeros(template.n_features)
                            counts[key] = 0
                            times[key] = []
                            spool_paths[key] = Path(scratch) / str(len(spool_paths))
                        clock = np.asarray(clock_data[batch], dtype=float)
                        keep = np.ones(len(clock), dtype=bool)
                        if params.transition_trim_seconds:
                            start = float(clock_data[interval.first - 1])
                            end = float(clock_data[interval.last - 1])
                            keep = (clock >= start + params.transition_trim_seconds) & (
                                clock <= end - params.transition_trim_seconds
                            )
                        encoded = encoded_data[batch, :][keep]
                        values = np.asarray(decoder[encoded], dtype=float)
                        if not np.isfinite(values).all():
                            raise ValueError("Averaging requires finite decoded intensities")
                        if len(values):
                            if params.statistic == "median":
                                spool_bytes += encoded.nbytes
                                if spool_bytes > 512 * 1024 * 1024:
                                    raise ValueError(
                                        "Median temporary storage exceeds 512 MiB per wafer; partition the selection"
                                    )
                                with spool_paths[key].open("ab") as stream:
                                    encoded.tofile(stream)
                            else:
                                sums[key] += values.sum(axis=0)
                            counts[key] += len(values)
                            times[key].extend([float(clock[keep][0]), float(clock[keep][-1])])
                    for key, total in sums.items():
                        if not counts[key]:
                            raise ValueError("Transition trim removed an entire averaging unit")
                        if params.statistic == "median":
                            # Keep each decoded block at most 16 MiB, leaving room
                            # for NumPy's exact order-statistic workspace.
                            block_columns = (16 * 1024 * 1024) // (counts[key] * 8)
                            if block_columns < 1:
                                raise ValueError(
                                    "Median group exceeds the bounded column workspace; partition the selection"
                                )
                            encoded_rows = np.memmap(
                                spool_paths[key],
                                mode="r",
                                dtype=encoded_data.dtype,
                                shape=(counts[key], template.n_features),
                            )
                            reduced = np.empty(template.n_features)
                            try:
                                for first in range(0, template.n_features, block_columns):
                                    last = min(template.n_features, first + block_columns)
                                    block = np.asarray(decoder[encoded_rows[:, first:last]], dtype=float)
                                    reduced[first:last] = np.median(block, axis=0, overwrite_input=True)
                            finally:
                                encoded_rows._mmap.close()
                            spool_paths[key].unlink()
                            means.append(reduced)
                        else:
                            means.append(total / counts[key])
                        rows.append(
                            {
                                "sample_id": hashlib.sha256(
                                    json.dumps([pin, params.model_dump(mode="json"), key], sort_keys=True).encode()
                                ).hexdigest(),
                                "date": partition.day.isoformat(),
                                "wafer": partition.wafer,
                                "step": partition.step_id,
                                "phase": key[-1] if params.mode.value != "step" else "all",
                                "cycle": key[-2] if params.mode.value == "cycle_phase" else None,
                                "acquisition_count": counts[key],
                                "statistic": params.statistic,
                                "start_time": min(times[key]),
                                "end_time": max(times[key]),
                                "source_sha256": partition.source_sha256,
                                "portfolio_sha256": receipt.sha256(),
                            }
                        )
        # Fail before exposing any result if files changed during streaming.
        for path, expected in verified.values():
            if _digest(path) != expected:
                raise ValueError("Source changed during averaging")
        dataset = SherpaDataset(
            X=np.stack(means),
            feature_axis=feature_axis,
            sample_axis=SampleAxis(
                labels=[f"{r['date']} / {r['wafer']} / {r['step']} / {r['phase']} / {r['cycle']}" for r in rows],
                sample_table={key: [row[key] for row in rows] for key in rows[0]},
            ),
            data_role="X_spectra",
            title=f"Portfolio {params.statistic} spectra",
            domain=template.domain.model_copy(deep=True),
            units=template.units,
        )
        dataset.provenance.append("preprocess.portfolio_average", params.model_dump(mode="json"), node_id=self.node_id)
        return NodeResult(outputs={"default": dataset})


@register_node
class WidePeakTableNode(Node):
    metadata = NodeMetadata(
        node_type="data.wide_peak_table",
        category="data",
        label="Combine peak columns",
        description="Match peak groups to explicit reference positions; preserve independent date/wafer/step columns.",
        parameters=[
            NodeParameter("reference_positions", "Reference positions", "string_list", default=[], required=True),
            NodeParameter("tolerance", "Matching tolerance (axis units)", "number", default=0.5, min_value=0),
        ],
        input_types=["Any"],
        output_type="SpectralDataset",
        input_ports=[PortMetadata(name="default", type_ref=ANY, required=True, variadic=True)],
        output_ports=[PortMetadata(name="default", type_ref=SPECTRA)],
        policy=NodePolicy(offload_to_pool=False),
    )

    async def execute(self, default=None, **kwargs):
        references = np.asarray(self.parameters.get("reference_positions", []), dtype=float)
        tolerance = float(self.parameters.get("tolerance", 0.5))
        if (
            references.ndim != 1
            or not 1 <= len(references) <= 1024
            or not np.isfinite(references).all()
            or len(set(references)) != len(references)
            or not np.isfinite(tolerance)
            or tolerance < 0
        ):
            raise ValueError("Distinct finite reference positions and nonnegative tolerance are required")
        inputs = default if isinstance(default, (list, tuple)) else [default]
        columns = []
        names = []
        identities = set()
        inputs = [batch for value in inputs for batch in (value if isinstance(value, (list, tuple)) else [value])]
        for value in inputs:
            source = coerce_to_sherpa(value, input_name="default")
            groups = source.meta.get("peak_groups")
            table = source.sample_axis.sample_table if source.sample_axis else None
            if groups is None or not table or "sample_id" not in table:
                raise ValueError(
                    "Connect per_spectrum output from canonical Peak Finding with retained sample identities"
                )
            if groups and (source.feature_axis is None or source.feature_axis.labels is None):
                raise ValueError("Peak measurements require labeled feature columns")
            feature_names = list(source.feature_axis.labels) if source.feature_axis is not None else []
            if (len(columns) + source.n_samples) * len(references) > 1_000_000:
                raise ValueError("Wide peak table exceeds the retained-value limit")
            for sample in range(source.n_samples):
                identity = table["sample_id"][sample]
                if identity in identities:
                    raise ValueError("Duplicate observation identity across peak branches")
                identities.add(identity)
                out = np.full(len(references), np.nan)
                used = set()
                for row, reference in enumerate(references):
                    matches = [g for g in groups if abs(g["guide_position"] - reference) <= tolerance]
                    if len(matches) > 1:
                        raise ValueError("Ambiguous peak matching; narrow the tolerance")
                    if matches:
                        g = matches[0]
                        if g["index"] in used:
                            raise ValueError("One peak group matches multiple references")
                        used.add(g["index"])
                        # Missing detected peak stays NaN, distinct from measured zero.
                        out[row] = source.X[sample, feature_names.index(f"magnitude_at_peak_{g['index']}")]
                columns.append(out)
                names.append(
                    " | ".join(
                        f"{k}={table[k][sample]}"
                        for k in ("date", "wafer", "step", "phase", "cycle", "statistic")
                        if k in table
                    )
                    + f" | id={identity}"
                )
        result = SherpaDataset(
            X=np.column_stack(columns),
            feature_axis=FeatureAxis(labels=names, title="Independent measurements"),
            sample_axis=SampleAxis(
                labels=[f"peak@{x:g}" for x in references],
                sample_table={
                    "sample_id": [f"peak@{x:g}" for x in references],
                    "reference_position": references.tolist(),
                },
            ),
            data_role="X_features",
            title="Peak intensities by date, wafer and step",
        )
        result.provenance.append(
            "data.wide_peak_table",
            {"reference_positions": references.tolist(), "tolerance": tolerance},
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result})


from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

for _class, _lifecycle, _samples, _features in [
    (PortfolioLoadNode, LifecycleKind.DATA_SOURCE, "generates_samples", "generates_features"),
    (PortfolioAverageNode, LifecycleKind.STATELESS_TRANSFORM, "aggregates_samples", "preserves_features"),
    (WidePeakTableNode, LifecycleKind.STATELESS_TRANSFORM, "generates_samples", "generates_features"),
]:
    bind_stable_execution_contract(
        _class,
        runtime_family=RuntimeFamily.SHERPA_NATIVE,
        lifecycle_kind=_lifecycle,
        implementation_id="spectrasherpa." + _class.metadata.node_type,
        implementation_version="0.1.0",
        required_worker_capabilities=(WorkerCapability.READ_DATASET,),
        managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
        sample_effect=_samples,
        feature_effect=_features,
        axis_effect="changes_axis",
        unit_effect="preserves_units",
        resource_hints={"timeout_seconds": 600, "cpu_seconds": 600, "memory_bytes": 536870912},
        license_id="Apache-2.0",
        help_reference="docs/nodes/data.md",
        implementation_distributions=("h5py", "numpy"),
        runtime_requirements=(("h5py", "3.16.0"), ("numpy", "1.26.4")),
    )


@register_node
class PeakCSVNode(Node):
    metadata = NodeMetadata(
        node_type="output.peak_csv",
        category="output",
        label="Export wide peak CSV",
        description="Export wide peak intensities; missing detections are empty cells, distinct from zero.",
        parameters=[
            NodeParameter("filename", "Filename", "text", default="peak-intensities.csv"),
            NodeParameter("format", "Format", "select", default="csv", options=["csv"], category="internal"),
        ],
        input_types=["SpectralDataset"],
        output_type="ExportArtifact",
        input_ports=[PortMetadata(name="default", type_ref=SPECTRA, required=True)],
        output_ports=[PortMetadata(name="artifact", type_ref="spectrasherpa://types/ExportArtifact/1.0")],
        policy=NodePolicy(offload_to_pool=False),
    )

    async def execute(self, default=None, **kwargs):
        import csv
        import io

        from spectra_sherpa.app.lib.export_artifact import (
            _safe_csv_text,
            canonicalize_export_parameters,
            verify_export_artifact,
        )

        dataset = coerce_to_sherpa(default, input_name="default")
        if dataset.title != "Peak intensities by date, wafer and step" or dataset.sample_axis is None:
            raise ValueError("Connect the canonical wide peak table")
        values = np.asarray(dataset.X)
        if values.size > 1_000_000 or np.isinf(values).any():
            raise ValueError("Peak CSV exceeds its limit or contains infinity")
        filename = canonicalize_export_parameters(
            {"filename": self.parameters.get("filename", "peak-intensities.csv"), "format": "csv"}
        )["filename"]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            ["peak_identity", *[_safe_csv_text(v, field="measurement") for v in dataset.feature_axis.labels]]
        )
        for name, row in zip(dataset.sample_axis.labels, values, strict=True):
            writer.writerow(
                [
                    _safe_csv_text(name, field="peak_identity"),
                    *["" if np.isnan(v) else format(float(v), ".17g") for v in row],
                ]
            )
        content = buffer.getvalue()
        encoded = content.encode()
        if len(encoded) > 32 * 1024 * 1024:
            raise ValueError("Peak CSV exceeds its byte limit")
        artifact = verify_export_artifact(
            {
                "schema_version": "spectrasherpa-export-artifact/1",
                "filename": filename,
                "format": "csv",
                "media_type": "text/csv;charset=utf-8",
                "content_encoding": "utf-8",
                "content": content,
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "byte_length": len(encoded),
                "source_digest": dataset.scientific_digest,
                "shape": list(dataset.shape),
            }
        )
        return NodeResult(outputs={"artifact": artifact})


bind_stable_execution_contract(
    PeakCSVNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.output.peak_csv",
    implementation_version="0.1.0",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 134217728},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)


@register_node
class PartitionedPeaksNode(Node):
    """Bound the existing canonical detector's retained plot payload per call."""

    from spectra_sherpa.app.services.dag.nodes.modeling.peak_finding_nodes import PeakFindingNode as _Detector

    metadata = NodeMetadata(
        node_type="analysis.partitioned_peaks",
        category="exploratory",
        label="Find peaks · Partitioned",
        description=(
            "Run canonical peak detection in bounded batches; combine observations with explicit reference peaks."
        ),
        parameters=_Detector.metadata.parameters
        + [
            NodeParameter("reference_positions", "Reference positions", "string_list", default=[], required=False),
            NodeParameter("matching_tolerance", "Reference matching tolerance", "number", default=0.5, min_value=0),
        ],
        input_types=["SpectralDataset"],
        output_type="Any",
        input_ports=[PortMetadata(name="default", type_ref=SPECTRA, required=True)],
        output_ports=[
            PortMetadata(name="per_spectrum", type_ref="spectrasherpa://types/PartitionedPeakMeasurements/1.0")
        ],
        presentation_contract=NodePresentationContract(
            default_presentation="per_spectrum",
            presentations=(
                ScientificPresentation(
                    presentation_id="per_spectrum",
                    label="Partitioned peak measurements",
                    kind="structured_record",
                    source_ports=("per_spectrum",),
                    modes=("record",),
                ),
            ),
        ),
        policy=NodePolicy(offload_to_pool=False),
    )

    async def execute(self, default=None, **kwargs):
        from spectra_sherpa.app.services.dag.nodes.modeling.peak_finding_nodes import PeakFindingNode

        source = coerce_to_sherpa(default, input_name="default")
        batch_rows = min(32, max(1, 200_000 // source.n_features))
        output = []
        total = 0
        for start in range(0, source.n_samples, batch_rows):
            subset = source[start : start + batch_rows, :]
            peak_parameters = {
                k: v for k, v in self.parameters.items() if k not in {"reference_positions", "matching_tolerance"}
            }
            result = await PeakFindingNode(self.node_id + f"-{start}", peak_parameters).execute(subset)
            measurements = result.outputs["per_spectrum"]
            references = np.asarray(self.parameters.get("reference_positions", []), dtype=float)
            if references.size:
                tolerance = float(self.parameters.get("matching_tolerance", 0.5))
                if not np.isfinite(references).all() or not np.isfinite(tolerance) or tolerance < 0:
                    raise ValueError("Finite reference positions and nonnegative matching tolerance required")
                matched = [
                    g
                    for g in measurements.meta["peak_groups"]
                    if any(abs(g["guide_position"] - r) <= tolerance for r in references)
                ]
                indices = [i for g in matched for i in range(4 * (g["index"] - 1), 4 * g["index"])]
                if indices:
                    measurements = measurements[:, indices]
                    measurements.meta["peak_groups"] = matched
                else:
                    # Keep one original column as transport shape; empty peak_groups means all references are missing.
                    measurements = measurements[:, :1]
                    measurements.meta["peak_groups"] = []
            total += measurements.X.size
            if total > 1_000_000:
                raise ValueError(
                    "Partitioned peak output exceeds its retained-value limit; select fewer units or peaks"
                )
            output.append(measurements)
        return NodeResult(outputs={"per_spectrum": output})


bind_stable_execution_contract(
    PartitionedPeaksNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.analysis.partitioned_peaks",
    implementation_version="0.1.0",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 600, "cpu_seconds": 600, "memory_bytes": 536870912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
)
