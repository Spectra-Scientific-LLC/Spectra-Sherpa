"""Load a local user's own custom nodes at startup, in local mode only.

Custom nodes come from two local sources. Each source is identified by the
SHA-256 of all its files, and every output a custom node produces records that
build digest and the node's execution-contract digest in its provenance:

* a subfolder of the My nodes folder (``<data dir>/user/my_nodes/<source>/``);
* an installed package declaring a ``spectra_sherpa.custom_nodes`` entry point.

Nothing loads unless the user turned custom nodes on in Settings
(``SPECTRA_SHERPA_CUSTOM_NODES=1``), the app runs in local mode, and it is not
the desktop shell. Loading happens once, before the node catalog is sealed;
changes take effect on restart. Spawned workers reproduce the same composition
through :func:`initialize_custom_nodes`.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from spectra_sherpa.sdk.custom import CustomNodeError, CustomNodeSpec, Spectra, check_parameter, specs_in

logger = logging.getLogger(__name__)

ENABLE_ENV = "SPECTRA_SHERPA_CUSTOM_NODES"
ENTRY_POINT_GROUP = "spectra_sherpa.custom_nodes"
NODE_PREFIX = "user"
LICENSE_ID = "LicenseRef-Custom-Node-Author"
_SOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_MODULE_PREFIX = "spectra_user_nodes"
_TYPE_REF = "spectrasherpa://types/SpectralDataset/1.0"


@dataclass(frozen=True)
class SourceStatus:
    """What happened to one custom-node source at startup."""

    source: str
    kind: str  # "folder" or "package"
    location: str
    version: str | None
    status: str  # "loaded" or "failed"
    nodes: tuple[str, ...] = ()
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "location": self.location,
            "version": self.version,
            "status": self.status,
            "nodes": list(self.nodes),
            "message": self.message,
        }


@dataclass
class _Candidate:
    source: str
    kind: str
    location: str
    version: str
    root: Path
    modules: list[ModuleType] = field(default_factory=list)
    load_modules: Any = None


_lock = threading.Lock()
_loaded = False
_active = False
_status: tuple[SourceStatus, ...] = ()


def enabled() -> bool:
    """Whether the user turned custom nodes on (takes effect on restart)."""
    # Importing the configuration applies the saved .env settings first.
    from spectra_sherpa.app.core import config  # noqa: F401

    return os.environ.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def available() -> bool:
    """Custom nodes exist only in local, non-desktop Workbench."""
    from spectra_sherpa.app.core.desktop_policy import is_desktop
    from spectra_sherpa.app.core.mode_policy import is_local

    return is_local() and not is_desktop()


def my_nodes_dir() -> Path:
    from spectra_sherpa.app.core.app_paths import get_app_data_paths
    from spectra_sherpa.app.core.config import settings

    return get_app_data_paths(Path(settings.data_dir)).user_dir / "my_nodes"


def source_statuses() -> tuple[SourceStatus, ...]:
    return _status


def active() -> bool:
    """Whether this process started with custom nodes turned on."""
    return _active


def source_id(name: str) -> str:
    """``Whitaker_Hayes`` -> ``whitaker-hayes``; raises if nothing usable remains."""
    value = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)[:48].rstrip("-")
    if not _SOURCE_RE.fullmatch(value):
        raise CustomNodeError(f"{name!r} cannot name a custom-node source; start it with a letter")
    return value


def _semver(version: str) -> str:
    parts = version.split(".")
    if not all(part.isdigit() for part in parts) or not 1 <= len(parts) <= 3:
        raise CustomNodeError(f"Package version {version!r} must be numeric, such as 1.2.0")
    parts = [str(int(part)) for part in parts] + ["0"] * (3 - len(parts))
    return ".".join(parts)


def node_type(source: str, spec: CustomNodeSpec) -> str:
    return f"{NODE_PREFIX}.{source}.{spec.name}"


# ── Building a node class from a decorated function ────────────────────────


def _parameter(spec) -> Any:
    from spectra_sherpa.app.services.dag.node_base import NodeParameter

    bounds = spec.bounds
    label = bounds.label or spec.name.replace("_", " ").capitalize()
    if spec.kind == "choice":
        return NodeParameter(
            name=spec.name,
            label=label,
            param_type="select",
            default=spec.default,
            options=list(bounds.choices),
            description=bounds.description,
        )
    if spec.kind == "boolean":
        return NodeParameter(
            name=spec.name, label=label, param_type="boolean", default=spec.default, description=bounds.description
        )
    return NodeParameter(
        name=spec.name,
        label=label,
        param_type="number",
        default=spec.default,
        min_value=bounds.min,
        max_value=bounds.max,
        max_value_reason="Declared by the custom node's author." if bounds.max is not None else None,
        step=(2 if bounds.odd else 1) if spec.kind == "integer" else None,
        description=bounds.description,
    )


def canonical_parameters(spec: CustomNodeSpec, values: dict[str, object]) -> dict[str, object]:
    """Fill defaults and refuse unknown or invalid values; never repair them."""
    if not isinstance(values, dict):
        raise CustomNodeError("Custom node parameters must be an object")
    declared = {item.name: item for item in spec.parameters}
    unknown = sorted(set(values) - set(declared))
    if unknown:
        raise CustomNodeError(f"Unknown parameter(s) for {spec.label}: {', '.join(unknown)}")
    return {
        name: check_parameter(item, values[name] if name in values else item.default) for name, item in declared.items()
    }


def _result_values(spec: CustomNodeSpec, returned: Any, received: Spectra) -> Spectra:
    """Enforce the declared defaults on what the function returned."""
    if spec.output_kind == "array":
        array = np.asarray(returned, dtype=np.float64) if isinstance(returned, np.ndarray) else None
        if array is None:
            raise CustomNodeError(f"{spec.label} must return a numpy array")
        if array.ndim != 2 or array.shape[0] != received.n_samples:
            raise CustomNodeError(
                f"{spec.label} returned shape {tuple(array.shape)}; custom nodes keep every sample "
                f"({received.n_samples} rows)"
            )
        if array.shape[1] != received.n_features:
            raise CustomNodeError(
                f"{spec.label} changed the number of features; declare changes_features=True and return "
                "spectra.select_features(...).with_values(...)"
            )
        result = received.with_values(array)
    elif isinstance(returned, Spectra):
        if returned._origin is None or returned._origin is not received._origin:
            raise CustomNodeError(
                f"{spec.label} must return the spectra it received, for example spectra.with_values(values)"
            )
        result = returned
    else:
        raise CustomNodeError(f"{spec.label} must return Spectra (for example spectra.with_values(values))")
    if result.n_samples != received.n_samples:
        raise CustomNodeError(f"{spec.label} must keep every sample ({received.n_samples} rows)")
    if result.n_features != received.n_features and not spec.changes_features:
        raise CustomNodeError(
            f"{spec.label} changed the number of features; declare changes_features=True if that is intended"
        )
    if not np.all(np.isfinite(result.values)):
        raise CustomNodeError(f"{spec.label} returned NaN or infinite values")
    return result


def apply_custom_function(spec: CustomNodeSpec, source_data: Any, parameters: dict[str, object]) -> Spectra:
    """Call the author's function once and enforce the declared defaults on its result.

    The function receives only copied values, feature axis and units, never the
    dataset. This is the one computation shared by the node and by ``nodes check``.
    """
    if getattr(source_data, "ndim", None) != 2:
        raise CustomNodeError(f"{spec.label} needs a two-dimensional samples x features dataset")
    received = Spectra._from_dataset(source_data)
    argument = received if spec.input_kind == "spectra" else received.values
    try:
        returned = spec.function(argument, **parameters)
    except SystemExit as exc:  # a run must fail like any other error, never stop Workbench
        raise CustomNodeError(f"{spec.label} called sys.exit() ({exc.code!r}); raise an exception instead") from None
    return _result_values(spec, returned, received)


def _feature_positions(result: Spectra, source_features: int) -> np.ndarray:
    positions = np.asarray(result._features)
    if (
        positions.ndim != 1
        or positions.size != result.n_features
        or positions.size == 0
        or not np.issubdtype(positions.dtype, np.integer)
        or np.any(np.diff(positions) <= 0)
        or positions[0] < 0
        or positions[-1] >= source_features
    ):
        raise CustomNodeError("The returned spectra do not name valid features of the input")
    return positions


def build_output(source_data: Any, result: Spectra) -> Any:
    """Rebuild the output from the engine's own samples, axis and units."""
    from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like

    positions = _feature_positions(result, int(source_data.shape[1]))
    base = source_data
    if positions.size != source_data.shape[1]:
        mask = np.zeros(source_data.shape[1], dtype=bool)
        mask[positions] = True
        base = source_data[:, mask]
    return build_dataset_like(result.values, base, units=getattr(source_data, "units", None))


def build_node_class(spec: CustomNodeSpec, source: str, version: str, build: str = "unrecorded") -> type:
    """One ordinary node class, bound through the stable execution contract."""
    from spectra_sherpa.app.services.dag import supervision_binding
    from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
    from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodePolicy, NodeResult, PortMetadata
    from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
    from spectra_sherpa.execution_contract_vocabulary import (
        CustomTrustClass,
        LifecycleKind,
        ManagedOptimizationEligibility,
        RuntimeFamily,
    )

    operation = node_type(source, spec)

    def validator(values: dict[str, object]) -> dict[str, object]:
        try:
            return canonical_parameters(spec, values)
        except CustomNodeError as exc:
            raise ValueError(str(exc)) from exc

    metadata = NodeMetadata(
        node_type=operation,
        category=spec.category,
        label=spec.label,
        description=spec.description,
        parameters=[_parameter(item) for item in spec.parameters],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref=_TYPE_REF,
                required=True,
                label="Input Spectra",
                description="Spectra passed to the custom function.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref=_TYPE_REF,
                required=True,
                label="Output Spectra",
                description="Spectra returned by the custom function; samples are always kept.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        distribution=NODE_PREFIX,
        canonical_parameter_validator=validator,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any):
        del kwargs
        source_data = coerce_to_sherpa(input_data if input_data is not None else default, input_name="input_data")
        parameters = validator(dict(self.parameters))
        result = await asyncio.to_thread(apply_custom_function, spec, source_data, parameters)
        output = build_output(source_data, result)
        add_processing_step(
            output,
            operation,
            parameters,
            node_id=self.node_id,
            input_shape=source_data.shape,
            impact={
                "schema_version": "spectrasherpa-custom-node-impact/1",
                "source": source,
                "source_version": version,
                "source_build_sha256": build,
                "execution_contract_sha256": self.metadata.execution_contract.digest,
                "features_in": int(source_data.shape[1]),
                "features_out": result.n_features,
            },
        )
        supervision_binding.rebind_sample_preserving_supervision(source_data, output)
        return NodeResult(outputs={"default": output})

    class_name = "".join(part.capitalize() for part in spec.name.split("_")) + "CustomNode"
    node_class = type(
        class_name,
        (Node,),
        {
            "__module__": spec.function.__module__,
            "__qualname__": class_name,
            "__doc__": spec.description,
            "metadata": metadata,
            "execute": execute,
            "custom_spec": spec,
        },
    )
    bind_stable_execution_contract(
        node_class,
        runtime_family=RuntimeFamily.APPROVED_CUSTOM,
        custom_trust_class=CustomTrustClass.LOCAL_UNTRUSTED,
        lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
        implementation_id=operation,
        implementation_version=version,
        required_worker_capabilities=(),
        managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
        sample_effect="preserves_samples",
        feature_effect="filters_features" if spec.changes_features else "preserves_features",
        axis_effect="preserves_axis",
        unit_effect="preserves_units",
        resource_hints={
            "timeout_seconds": spec.timeout_seconds,
            "cpu_seconds": spec.timeout_seconds,
            "memory_bytes": spec.memory_mb * 1024 * 1024,
        },
        license_id=LICENSE_ID,
        help_reference=f"custom-node/{source}",
        deterministic=spec.seed_parameter is None,
        seed_parameter=spec.seed_parameter,
        citations=spec.citations,
    )
    return node_class


# ── Discovering and composing sources ──────────────────────────────────────


def _inventory(root: Path):
    from spectra_sherpa.core.pack_build import PackFile, _installed_files

    files = []
    for relative in sorted(_installed_files(root)):
        files.append(PackFile(path=relative, sha256=hashlib.sha256((root / relative).read_bytes()).hexdigest()))
    return tuple(files)


# The SHA-256 of the exact source bytes each custom-node module was compiled
# from in this process. Custom-node modules never run cached bytecode, so a
# source's recorded build always describes the code that actually ran.
_EXECUTED: dict[Path, str] = {}


class _SourceBytesLoader(importlib.machinery.SourceFileLoader):
    """Compile a module from the bytes it records, never from ``__pycache__``.

    A cached ``.pyc`` is trusted by modification time and size, so a same-size
    edit with a preserved timestamp would otherwise run the old code while the
    build digest describes the new file.
    """

    def get_code(self, fullname: str):
        path = self.get_filename(fullname)
        data = self.get_data(path)
        _EXECUTED[Path(path).resolve()] = hashlib.sha256(data).hexdigest()
        return self.source_to_code(data, path)


class _SourceBytesFinder(importlib.abc.MetaPathFinder):
    """Route imports of a package's own source files through the loader above."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None or not isinstance(spec.loader, importlib.machinery.SourceFileLoader) or not spec.origin:
            return None
        if not Path(spec.origin).resolve().is_relative_to(self.root):
            return None
        spec.loader = _SourceBytesLoader(fullname, spec.origin)
        return spec


def _import_package_module(module_name: str) -> ModuleType:
    top = importlib.util.find_spec(module_name.split(".", 1)[0])
    locations = list(getattr(top, "submodule_search_locations", None) or ()) if top is not None else []
    finder = _SourceBytesFinder(Path(locations[0])) if locations else None
    if finder is not None:
        sys.meta_path.insert(0, finder)
    try:
        return importlib.import_module(module_name)
    finally:
        if finder is not None:
            sys.meta_path.remove(finder)


def _require_executed_bytes(root: Path, modules: list[ModuleType], files) -> None:
    """Refuse a source unless every module of it ran the inventoried bytes."""
    expected = {(root / item.path).resolve(): item.sha256 for item in files}
    loaded = {Path(module.__file__).resolve() for module in modules if getattr(module, "__file__", None)}
    for module in list(sys.modules.values()):
        location = getattr(module, "__file__", None)
        if location and Path(location).resolve() in expected:
            loaded.add(Path(location).resolve())
    for path in sorted(loaded):
        relative = path.relative_to(root) if path.is_relative_to(root) else path
        if path not in expected:
            raise CustomNodeError(f"{relative} is outside the source folder and cannot be recorded")
        executed = _EXECUTED.get(path)
        if executed is None:
            raise CustomNodeError(f"{relative} was imported before custom nodes loaded, so its code cannot be recorded")
        if executed != expected[path]:
            raise CustomNodeError(f"{relative} changed while it was loading; restart to load the saved version")


def _import_file(path: Path, source: str) -> ModuleType:
    name = f"{_MODULE_PREFIX}_{source.replace('-', '_')}_{path.stem}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise CustomNodeError(f"{path.name} needs a Python identifier file name")
    existing = sys.modules.get(name)
    if (
        existing is not None
        and Path(getattr(existing, "__file__", "")).resolve() == path.resolve()
        and _EXECUTED.get(path.resolve()) == hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        return existing
    spec = importlib.util.spec_from_file_location(name, path, loader=_SourceBytesLoader(name, str(path)))
    if spec is None or spec.loader is None:
        raise CustomNodeError(f"{path.name} cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def folder_candidate(directory: Path) -> _Candidate:
    """One My nodes subfolder; each top-level ``.py`` file is imported on its own."""
    source = source_id(directory.name)
    candidate = _Candidate(source, "folder", str(directory), "0.0.0", directory.resolve())

    def load():
        files = sorted(path for path in directory.glob("*.py") if path.is_file())
        if not files:
            raise CustomNodeError("The folder has no .py files")
        return [_import_file(path, source) for path in files]

    candidate.load_modules = load
    return candidate


# What a source may raise without stopping Workbench. ``SystemExit`` comes from
# converted scripts that call ``argparse`` or ``sys.exit()`` at module scope;
# ``KeyboardInterrupt`` still stops startup as the user intends.
_SOURCE_ERRORS = (Exception, SystemExit)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return (
            f"SystemExit: the source exited while importing (code {exc.code!r}). "
            'Move script code such as argparse under `if __name__ == "__main__":`.'
        )[:500]
    return f"{type(exc).__name__}: {exc}"[:500]


def _failure(name: str, kind: str, location: str, exc: BaseException) -> SourceStatus:
    logger.warning("Custom-node source %s was not loaded: %s", location, exc)
    return SourceStatus(name, kind, location, None, "failed", message=_describe(exc))


def _folder_candidates() -> tuple[list[_Candidate], list[SourceStatus]]:
    """Every My nodes subfolder; one that cannot become a source is reported, not fatal."""
    candidates, failures = [], []
    root = my_nodes_dir()
    try:
        if not root.is_dir():
            return [], []
        folders = sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith((".", "_")))
    except OSError as exc:
        return [], [_failure("my-nodes", "folder", str(root), exc)]
    for path in folders:
        try:
            candidates.append(folder_candidate(path))
        except Exception as exc:
            failures.append(_failure(path.name, "folder", str(path), exc))
    return candidates, failures


def _package_candidates() -> tuple[list[_Candidate], list[SourceStatus]]:
    """Every declared entry point; a broken declaration is reported, not fatal."""
    candidates, failures = [], []
    try:
        entry_points = sorted(importlib.metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda item: item.name)
    except Exception as exc:
        return [], [_failure("packages", "package", ENTRY_POINT_GROUP, exc)]
    for entry_point in entry_points:
        name = entry_point.name
        try:
            distribution = getattr(entry_point, "dist", None)
            name = distribution.metadata["Name"] if distribution is not None else entry_point.name
            version = distribution.version if distribution is not None else "0.0.0"
            module_name = entry_point.value.split(":", 1)[0]
            candidate = _Candidate(source_id(name), "package", f"{name}=={version}", version, Path("."))
        except Exception as exc:
            failures.append(_failure(name, "package", entry_point.value, exc))
            continue

        def load(module_name=module_name, candidate=candidate):
            module = _import_package_module(module_name)
            location = getattr(module, "__file__", None)
            if not location:
                raise CustomNodeError(f"{module_name} has no source file")
            root = Path(location).resolve().parent
            if root.name == "site-packages" or root.name == "dist-packages":
                raise CustomNodeError("Put custom nodes inside a package directory, not a top-level module")
            candidate.root = root
            return [module]

        candidate.load_modules = load
        candidates.append(candidate)
    return candidates, failures


@dataclass(frozen=True)
class _Composed:
    source: str
    version: str
    build_sha256: str
    files: int
    nodes: tuple[type, ...]

    def identity(self, kind: str) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": kind,
            "version": self.version,
            "build_sha256": self.build_sha256,
            "nodes": [
                [
                    node.get_metadata().node_type,
                    node.__module__,
                    node.__qualname__,
                    node.get_metadata().execution_contract.digest,
                ]
                for node in self.nodes
            ],
        }


def _compose(candidate: _Candidate) -> _Composed:
    """Import, build and validate one source in isolation; never touches the catalog."""
    from spectra_sherpa.app.services.dag.node_base import NodeRegistry
    from spectra_sherpa.app.services.pack_bootstrap import _require_inventoried_source
    from spectra_sherpa.core.pack_build import MAX_BUILD_BYTES, MAX_BUILD_FILES, MAX_FILE_BYTES, build_sha256

    version = _semver(candidate.version)
    modules = candidate.load_modules()
    specs = [spec for module in modules for spec in specs_in(module)]
    if not specs:
        raise CustomNodeError("No @custom_node functions were found")
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise CustomNodeError("Two custom nodes in this source share a function name")
    files = _inventory(candidate.root)
    if len(files) > MAX_BUILD_FILES:
        raise CustomNodeError(f"A custom-node source may contain at most {MAX_BUILD_FILES} files")
    sizes = [(candidate.root / item.path).stat().st_size for item in files]
    if max(sizes, default=0) > MAX_FILE_BYTES or sum(sizes) > MAX_BUILD_BYTES:
        raise CustomNodeError("A custom-node source is too large; keep data files out of its folder")
    _require_executed_bytes(candidate.root, modules, files)
    build = build_sha256(files)
    nodes = tuple(build_node_class(spec, candidate.source, version, build) for spec in specs)
    staged = NodeRegistry()
    inventory = {item.path for item in files}
    for node_class in nodes:
        _require_inventoried_source(node_class, candidate.root, inventory)
        staged.register(node_class)
    return _Composed(candidate.source, version, build, len(files), nodes)


def compose_sources(candidates: list[_Candidate]) -> tuple[list[tuple[_Candidate, _Composed]], list[SourceStatus]]:
    """Validate every source; a failing source is reported, never loaded."""
    composed, statuses = [], []
    names: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        names.setdefault(candidate.source, []).append(candidate)
    for candidate in candidates:
        if len(names[candidate.source]) > 1:
            others = ", ".join(item.location for item in names[candidate.source])
            message = f"Two sources use the name {candidate.source!r}: {others}. Rename one."
            statuses.append(
                SourceStatus(candidate.source, candidate.kind, candidate.location, None, "failed", message=message)
            )
            continue
        try:
            result = _compose(candidate)
        except _SOURCE_ERRORS as exc:  # an author's code may raise anything at import
            statuses.append(_failure(candidate.source, candidate.kind, candidate.location, exc))
            continue
        composed.append((candidate, result))
        statuses.append(
            SourceStatus(
                candidate.source,
                candidate.kind,
                candidate.location,
                result.version,
                "loaded",
                nodes=tuple(node.get_metadata().node_type for node in result.nodes),
            )
        )
    return composed, statuses


def initialize_custom_nodes() -> None:
    """Compose enabled custom-node sources before the catalog is sealed.

    Also the spawned-worker initializer: it rebuilds the same composition, and
    the worker pool refuses a worker whose composition digest differs.
    """
    global _loaded, _active, _status
    with _lock:
        if _loaded:
            return
        _loaded = True
        if not enabled():
            return
        if not available():
            logger.warning("Custom nodes are ignored outside local Workbench")
            return
        _active = True
        try:
            _status = tuple(_compose_enabled_sources())
        except _SOURCE_ERRORS as exc:  # never let a user's source stop Workbench from starting
            logger.exception("Custom nodes could not be loaded")
            _status = (_failure("custom-nodes", "folder", str(my_nodes_dir()), exc),)


def _compose_enabled_sources() -> list[SourceStatus]:
    folders, folder_failures = _folder_candidates()
    packages, package_failures = _package_candidates()
    composed, statuses = compose_sources(folders + packages)
    statuses = folder_failures + package_failures + statuses
    if composed:
        from spectra_sherpa.app.services.dag.node_base import node_registry

        try:
            node_registry.compose_local_custom_nodes(
                tuple(node for _, result in composed for node in result.nodes),
                [result.identity(candidate.kind) for candidate, result in composed],
            )
        except Exception as exc:
            logger.error("Custom nodes could not be composed: %s", exc)
            message = f"Custom nodes could not be loaded: {exc}"[:500]
            statuses = [
                (
                    SourceStatus(item.source, item.kind, item.location, None, "failed", message=message)
                    if item.status == "loaded"
                    else item
                )
                for item in statuses
            ]
    return statuses


def worker_initializer():
    """The initializer the worker pool needs once custom nodes are composed."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    return initialize_custom_nodes if node_registry.custom_sources else None


def _reset_for_tests() -> None:
    global _loaded, _active, _status
    _loaded, _active, _status = False, False, ()


# ── Self-check for authors and coding agents ───────────────────────────────


def _check_dataset():
    """A small bundled example: smooth synthetic spectra with one spike."""
    import spectra_sherpa.sdk as ss

    axis = np.linspace(400.0, 1800.0, 120)
    rng = np.random.default_rng(7)
    rows = []
    for index in range(6):
        band = np.exp(-0.5 * ((axis - 1000.0 - 40 * index) / 60.0) ** 2)
        rows.append(band + 0.1 + 0.002 * rng.standard_normal(axis.size))
    values = np.vstack(rows)
    values[2, 60] += 3.0
    return ss.data.from_array(values, x=axis, units="cm-1")


def check_source(location: str) -> tuple[bool, list[str]]:
    """Load one source the way Workbench does, then run each node once.

    ``location`` is a My nodes source folder, a ``.py`` file inside one, or an
    importable module name of a package that declares the entry point.
    """
    lines: list[str] = []
    path = Path(location).expanduser()
    if path.suffix == ".py" and path.is_file():
        lines.append(f"Checking the whole source folder {path.parent} (every file in it is part of the source).")
        path = path.parent
    try:
        if path.is_dir():
            candidate = folder_candidate(path)
        else:
            candidate = _Candidate(source_id(location.split(".")[0]), "package", location, "0.0.0", Path("."))

            def load(candidate=candidate):
                module = _import_package_module(location)
                candidate.root = Path(module.__file__).resolve().parent
                return [module]

            candidate.load_modules = load
        pack = _compose(candidate)
    except _SOURCE_ERRORS as exc:
        lines.append(f"FAILED to load: {_describe(exc)}")
        return False, lines
    lines.append(
        f"Source {pack.source!r}: {len(pack.nodes)} node(s), {pack.files} file(s), build {pack.build_sha256[:12]}"
    )
    dataset = _check_dataset()
    ok = True
    for node_class in pack.nodes:
        metadata = node_class.get_metadata()
        parameters = ", ".join(
            f"{item.name}={item.default!r}"
            + (f" [{item.min_value}..{item.max_value}]" if item.param_type == "number" else "")
            for item in metadata.parameters
        )
        try:
            spec = node_class.custom_spec
            output = apply_custom_function(spec, dataset, canonical_parameters(spec, {}))
        except _SOURCE_ERRORS as exc:
            ok = False
            lines.append(f"FAILED {metadata.node_type} ({metadata.label}): {_describe(exc)}")
            continue
        lines.append(
            f"OK {metadata.node_type} ({metadata.label}, {metadata.category}); parameters: {parameters or 'none'}; "
            f"sample run {dataset.shape[0]}x{dataset.shape[1]} -> {output.shape[0]}x{output.shape[1]}"
        )
    if ok:
        lines.append("All checks passed. Turn on custom nodes in Settings and restart Workbench to use them.")
    return ok, lines
