"""Fail-closed containment for the optional SpectroChemPy runtime."""

from __future__ import annotations

import ast
from pathlib import Path

_NDDATASET_MODULES = frozenset({"interoperability/spectrochempy_adapter.py"})


def _source_root() -> Path:
    root = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa"
    if not root.is_dir():
        raise FileNotFoundError(f"Cannot find spectra_sherpa source at {root}")
    return root


def test_nddataset_references_are_confined_to_the_closed_temporary_set() -> None:
    root = _source_root()
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "NDDataset" in path.read_text(encoding="utf-8")
    }

    assert observed == _NDDATASET_MODULES, (
        "Only the minimal optional adapter may construct the external dataset type.\n"
        f"unexpected={sorted(observed - _NDDATASET_MODULES)}\n"
        f"missing={sorted(_NDDATASET_MODULES - observed)}"
    )


def test_retired_scp_extractor_module_does_not_exist() -> None:
    root = _source_root()
    assert not (root / "app" / "lib" / "adapters" / "scp_extractors.py").exists()
    assert (root / "app" / "lib" / "fitted_state.py").is_file()


def test_dag_node_vocabulary_is_canonical_sherpa_dataset() -> None:
    root = _source_root()
    nodes_root = root / "app" / "services" / "dag" / "nodes"
    occurrences: list[tuple[str, str]] = []
    for path in nodes_root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "NDDataset" in line:
                occurrences.append((path.relative_to(root).as_posix(), line.strip()))

    assert occurrences == []


def test_node_metadata_defaults_name_the_canonical_dataset() -> None:
    source = (_source_root() / "app" / "services" / "dag" / "node_base.py").read_text(encoding="utf-8")
    assert 'default_factory=lambda: ["SherpaDataset"]' in source
    assert 'output_type: str = "SherpaDataset"' in source
    assert '"NDDataset"' not in source


def test_frontend_production_source_has_no_retired_dataset_vocabulary() -> None:
    frontend = Path(__file__).resolve().parent.parent / "frontend" / "src"
    occurrences = []
    for path in frontend.rglob("*"):
        if not path.is_file() or "test" in path.parts:
            continue
        if path.suffix not in {".ts", ".vue"}:
            continue
        if "NDDataset" in path.read_text(encoding="utf-8"):
            occurrences.append(path.relative_to(frontend).as_posix())
    assert occurrences == []


def test_only_the_adapter_can_import_the_optional_runtime() -> None:
    root = _source_root()
    observed: set[str] = set()
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name == "spectrochempy" for alias in node.names):
                observed.add(relative)
            elif isinstance(node, ast.ImportFrom) and node.module == "spectrochempy":
                observed.add(relative)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"import_module", "__import__"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "spectrochempy"
            ):
                observed.add(relative)
    assert observed == {"interoperability/spectrochempy_adapter.py"}


def test_only_three_optional_nodes_import_the_adapter() -> None:
    root = _source_root()
    observed: set[str] = set()
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "spectra_sherpa.interoperability":
                if any(alias.name == "spectrochempy_adapter" for alias in node.names):
                    observed.add(relative)
    assert observed == {
        "app/services/dag/nodes/modeling/efa_nodes.py",
        "app/services/dag/nodes/modeling/mcr_nodes.py",
        "app/services/dag/nodes/modeling/simplisma_nodes.py",
    }


def test_retired_compatibility_and_product_authorities_do_not_exist() -> None:
    root = _source_root()
    for relative in (
        "app/lib/scp_compat.py",
        "app/lib/scp_catalog.py",
        "app/lib/adapters/scp_adapter.py",
    ):
        assert not (root / relative).exists()

    retired = {
        "HAS_NDDATASET",
        "HAS_SCP",
        "SCP_DATADIR",
        "SCP_DATA_BOOTSTRAP",
        "spectrochempy-examples",
        "scp_roundtrip",
        "from_nddataset",
        "to_nddataset",
    }
    occurrences: list[tuple[str, str]] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for symbol in retired:
            if symbol in text:
                occurrences.append((path.relative_to(root).as_posix(), symbol))
    assert occurrences == []


_RETIRED_PRODUCT_AUTHORITIES = (
    "SCP_DATA_BOOTSTRAP",
    "SCP_DATADIR",
    "spectrochempy-examples",
    "SCP dataset not found",
    "_resolve_scp_path",
)


def _assert_no_retired_product_authorities(product_files: list[Path], root: Path) -> None:
    occurrences = [
        (path.relative_to(root).as_posix(), symbol)
        for path in product_files
        for symbol in _RETIRED_PRODUCT_AUTHORITIES
        if symbol in path.read_text(encoding="utf-8")
    ]
    assert occurrences == []


def test_retired_product_authorities_are_absent_from_delivery_sources() -> None:
    package_root = Path(__file__).resolve().parent.parent
    product_files = [package_root / ".env.example"]
    product_files.extend(
        path
        for path in (package_root / "frontend" / "src").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".vue"} and "test" not in path.parts
    )
    _assert_no_retired_product_authorities(product_files, package_root)


def test_retired_product_authorities_are_absent_from_hosted_backend(monorepo_root: Path) -> None:
    _assert_no_retired_product_authorities(
        [monorepo_root / "packages/spectra-ops/docker/Dockerfile.backend"], monorepo_root
    )
