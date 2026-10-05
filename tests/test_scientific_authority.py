"""Systemic gates for the repository-wide scientific execution authority."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = REPO_ROOT / "tools/scientific_authority.py"


def _tool():
    spec = importlib.util.spec_from_file_location("scientific_authority_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_scientific_authority_matches_live_repository() -> None:
    tool = _tool()
    checked = tool.json.loads(tool.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert tool.stable_projection(checked) == tool.stable_projection(tool.build_manifest())


def test_new_route_in_existing_module_changes_the_closed_inventory(tmp_path: Path) -> None:
    tool = _tool()
    route_root = tmp_path / "routes"
    route_root.mkdir()
    (route_root / "health.py").write_text(
        "@router.get('/ready')\ndef ready():\n    return {}\n",
        encoding="utf-8",
    )
    first = tool._discover_routes(route_root, package="sherpa", defaults={"health.py": "application_orchestration"})
    (route_root / "health.py").write_text(
        "@router.get('/ready')\ndef ready():\n    return {}\n"
        "@router.post('/invented')\ndef invented():\n    return {}\n",
        encoding="utf-8",
    )
    second = tool._discover_routes(route_root, package="sherpa", defaults={"health.py": "application_orchestration"})
    assert second != first
    assert {record["function"] for record in second} == {"ready", "invented"}


def test_route_identity_ignores_source_line_shifts_but_keeps_duplicate_occurrences(tmp_path: Path) -> None:
    tool = _tool()
    route_root = tmp_path / "routes"
    route_root.mkdir()
    source = route_root / "health.py"
    source.write_text("@router.get('/ready')\ndef ready():\n    return {}\n", encoding="utf-8")
    first = tool._discover_routes(route_root, package="sherpa", defaults={"health.py": "application_orchestration"})
    source.write_text("# review note\n\n@router.get('/ready')\ndef ready():\n    return {}\n", encoding="utf-8")
    shifted = tool._discover_routes(route_root, package="sherpa", defaults={"health.py": "application_orchestration"})
    assert tool.stable_projection(shifted) == tool.stable_projection(first)
    source.write_text(
        "@router.get('/ready')\ndef ready():\n    return {}\n"
        "@router.get('/ready')\ndef ready_again():\n    return {}\n",
        encoding="utf-8",
    )
    duplicated = tool._discover_routes(
        route_root, package="sherpa", defaults={"health.py": "application_orchestration"}
    )
    assert tool.stable_projection(duplicated) != tool.stable_projection(first)


def test_unclassified_route_module_fails_closed(tmp_path: Path) -> None:
    tool = _tool()
    path = tmp_path / "invented.py"
    path.write_text("@router.post('/science')\ndef science():\n    return {}\n", encoding="utf-8")
    with pytest.raises(tool.ScientificAuthorityError, match="unclassified sherpa route module"):
        tool._discover_routes(tmp_path, package="sherpa", defaults={})


def test_factory_registered_routes_are_inventoried(tmp_path: Path) -> None:
    tool = _tool()
    path = tmp_path / "app.py"
    path.write_text(
        "def build(router):\n"
        "    router.add_api_route('/health', lambda: {}, methods=['GET'])\n"
        "    return router\n",
        encoding="utf-8",
    )

    records = tool._discover_routes(
        tmp_path,
        package="server",
        defaults={"app.py": "application_orchestration"},
    )

    assert [(record["method"], record["local_path"]) for record in records] == [("GET", "/health")]


def test_direct_estimator_call_outside_authority_fails_closed(tmp_path: Path) -> None:
    tool = _tool()
    tree = ast.parse("def hidden(model, X):\n    return model.predict(X)\n")
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in tool.DIRECT_METHODS
        for node in ast.walk(tree)
    )
    with pytest.raises(tool.ScientificAuthorityError, match="unclassified direct scientific method call"):
        tool._direct_call_policy("sherpa", "app/services/hidden_science.py")


def test_open_authority_finding_requires_named_increment() -> None:
    tool = _tool()
    with pytest.raises(tool.ScientificAuthorityError, match="lacks a target increment"):
        tool._validate_record({"role": "application_orchestration", "disposition": "rewire"})


def test_stale_route_override_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool()
    monkeypatch.setattr(
        tool,
        "ROUTE_OVERRIDES",
        {"sherpa:builder.py:missing_handler": ("domain_service", "rewire", "authority-pr2")},
    )

    with pytest.raises(tool.ScientificAuthorityError, match="handlers that do not exist"):
        tool._validate_route_overrides([])


def test_execution_callsite_census_is_derived_from_resolvable_source() -> None:
    tool = _tool()
    records = tool._discover_execution_calls()

    assert records
    assert {record["kind"] for record in records} >= {
        "canonical-application-executor",
        "dag-executor",
        "executable-export-projection",
        "fold-graph-executor",
        "registered-node-invocation",
        "sdk-operation-executor",
        "sdk-workflow-executor",
    }
    for record in records:
        root = tool.SHERPA_PACKAGE if record["package"] == "sherpa" else tool.SERVER_PACKAGE
        source = root / record["module"]
        assert source.is_file(), record
        lines = source.read_text(encoding="utf-8").splitlines()
        assert 1 <= record["line"] <= len(lines), record
        assert record["callable"], record


def test_model_application_enters_through_dag_executor_not_node_execute() -> None:
    tool = _tool()
    records = [
        record for record in tool._discover_execution_calls() if record["module"] == "app/services/model_application.py"
    ]

    assert [(record["kind"], record["invocation"]) for record in records] == [("dag-executor", "execute")]


def test_new_direct_registered_node_invocation_fails_closed(tmp_path: Path) -> None:
    tool = _tool()
    source = tmp_path / "hidden.py"
    source.write_text(
        "async def hidden():\n"
        "    operation = InventedNode('hidden', {})\n"
        "    return await operation.execute(input_data=None)\n",
        encoding="utf-8",
    )

    with pytest.raises(tool.ScientificAuthorityError, match="registered nodes may be invoked directly"):
        tool._discover_execution_calls([("sherpa", source)])


def test_new_dag_execution_callsite_changes_the_derived_census(tmp_path: Path) -> None:
    tool = _tool()
    source = tmp_path / "service.py"
    source.write_text(
        "async def service():\n" "    runner = DAGExecutor()\n" "    return await runner.execute()\n",
        encoding="utf-8",
    )

    records = tool._discover_execution_calls([("sherpa", source)])

    assert [(record["kind"], record["invocation"], record["callable"]) for record in records] == [
        ("dag-executor", "execute", "service")
    ]


def test_aliased_and_attribute_held_execution_authorities_are_derived(tmp_path: Path) -> None:
    tool = _tool()
    source = tmp_path / "service.py"
    source.write_text(
        "from package import DAGExecutor as CanonicalRunner\n"
        "from package import execute_workflow as run_workflow\n"
        "class Service:\n"
        "    def __init__(self):\n"
        "        self.runner = CanonicalRunner()\n"
        "    async def execute(self):\n"
        "        await self.runner.execute()\n"
        "        return run_workflow({'nodes': [], 'edges': []})\n",
        encoding="utf-8",
    )

    records = tool._discover_execution_calls([("sherpa", source)])

    assert [(record["kind"], record["invocation"]) for record in records] == [
        ("dag-executor", "execute"),
        ("sdk-workflow-executor", "execute_workflow"),
    ]


def _write_dependency_census(path: Path, *, components: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "node_type": "test.operation",
                        "execution_contract": {
                            "payload": {
                                "implementation_components": [
                                    {"component_id": component, "digest": "0" * 64} for component in components
                                ]
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_numerical_dependency_closure_records_exact_aliases_and_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text(
        "import numpy as np\n"
        "import sklearn.cross_decomposition as cross\n"
        "from scipy.signal import savgol_filter as smooth\n",
        encoding="utf-8",
    )
    census = tmp_path / "census.json"
    _write_dependency_census(
        census,
        components=[
            "distribution.numpy",
            "distribution.scikit-learn",
            "distribution.scipy",
            "spectra_sherpa.operation",
        ],
    )
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    records = tool._numerical_dependency_closure()

    assert [record["imported_module"] for record in records] == [
        "numpy",
        "sklearn.cross_decomposition",
        "scipy.signal",
    ]
    assert records[0]["symbols"] == [{"local_name": "np", "name": "numpy"}]
    assert records[1]["symbols"] == [{"local_name": "cross", "name": "sklearn.cross_decomposition"}]
    assert records[2]["symbols"] == [{"local_name": "smooth", "name": "savgol_filter"}]


def test_live_numerical_dependency_census_resolves_to_bound_source_and_distribution() -> None:
    tool = _tool()
    records = tool._numerical_dependency_closure()
    census = json.loads(tool.NODE_CENSUS.read_text(encoding="utf-8"))
    components_by_operation = {
        node["node_type"]: {
            component["component_id"]
            for component in node["execution_contract"]["payload"]["implementation_components"]
        }
        for node in census["nodes"]
    }

    assert records
    for record in records:
        source = tool._component_source(record["component_id"])
        lines = source.read_text(encoding="utf-8").splitlines()
        assert 1 <= record["line"] <= len(lines), record
        assert record["imported_module"].split(".", 1)[0] in lines[record["line"] - 1], record
        assert f"distribution.{record['distribution']}" in components_by_operation[record["operation_id"]], record


def test_unbound_numerical_dependency_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text(
        "from sklearn.cross_decomposition import PLSCanonical as AlternatePLS\n",
        encoding="utf-8",
    )
    census = tmp_path / "census.json"
    _write_dependency_census(census, components=["distribution.numpy", "spectra_sherpa.operation"])
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    with pytest.raises(tool.ScientificAuthorityError, match="without binding distribution.scikit-learn"):
        tool._numerical_dependency_closure()


def test_hdf5_decoder_dependency_requires_an_exact_distribution_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text("import h5py\n", encoding="utf-8")
    census = tmp_path / "census.json"
    _write_dependency_census(census, components=["distribution.numpy", "spectra_sherpa.operation"])
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    with pytest.raises(tool.ScientificAuthorityError, match="without binding distribution.h5py"):
        tool._numerical_dependency_closure()


def test_unclassified_third_party_dependency_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text("import invented_numerical_package\n", encoding="utf-8")
    census = tmp_path / "census.json"
    _write_dependency_census(census, components=["distribution.numpy", "spectra_sherpa.operation"])
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    with pytest.raises(tool.ScientificAuthorityError, match="unclassified third-party package"):
        tool._numerical_dependency_closure()


def test_non_numerical_storage_dependency_is_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text(
        "from sqlalchemy.ext.asyncio import AsyncSession\n",
        encoding="utf-8",
    )
    census = tmp_path / "census.json"
    _write_dependency_census(census, components=["distribution.numpy", "spectra_sherpa.operation"])
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    assert tool._numerical_dependency_closure() == []


def test_non_literal_dynamic_dependency_import_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool()
    package = tmp_path / "spectra_sherpa"
    package.mkdir()
    (package / "operation.py").write_text(
        "import importlib\n" "def load(name):\n" "    return importlib.import_module(name)\n",
        encoding="utf-8",
    )
    census = tmp_path / "census.json"
    _write_dependency_census(census, components=["distribution.numpy", "spectra_sherpa.operation"])
    monkeypatch.setattr(tool, "SHERPA_PACKAGE", package)
    monkeypatch.setattr(tool, "NODE_CENSUS", census)

    with pytest.raises(tool.ScientificAuthorityError, match="non-literal dynamic import"):
        tool._numerical_dependency_closure()


def test_no_placeholder_compute_route_source_remains() -> None:
    source = REPO_ROOT / "packages/spectra-sherpa/src/spectra_sherpa/app/api/v1/routes/compute.py"
    assert not source.exists()
    api_source = (REPO_ROOT / "packages/spectra-sherpa/src/spectra_sherpa/app/api/v1/api.py").read_text(
        encoding="utf-8"
    )
    assert "compute.router" not in api_source
