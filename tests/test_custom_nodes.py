"""Local custom nodes: author contract, run-time defaults, composition and boundaries."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import pytest

from spectra_sherpa.app.services import custom_nodes
from spectra_sherpa.sdk.custom import CustomNodeError, Spectra, custom_node, param

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

DESPIKE = textwrap.dedent('''
    from typing import Annotated

    import numpy as np

    from spectra_sherpa.sdk.custom import Spectra, custom_node, param


    @custom_node(label="Whitaker-Hayes despike", category="preprocessing")
    def despike(
        spectra: Spectra,
        threshold: Annotated[float, param(min=3.0, max=20.0)] = 6.0,
        window: Annotated[int, param(min=1, max=10)] = 2,
    ) -> Spectra:
        """Flag spikes by the modified z-score of first differences."""
        x = spectra.values
        out = x.copy()
        for row in range(x.shape[0]):
            delta = np.diff(x[row])
            mad = np.median(np.abs(delta - np.median(delta))) or 1e-12
            spikes = np.zeros(x.shape[1], dtype=bool)
            spikes[1:] = np.abs(0.6745 * (delta - np.median(delta)) / mad) > threshold
            for j in np.flatnonzero(spikes):
                lo, hi = max(0, j - window), min(x.shape[1], j + window + 1)
                keep = [k for k in range(lo, hi) if not spikes[k]]
                if keep:
                    out[row, j] = x[row, keep].mean()
        return spectra.with_values(out)
''')


def _spec(function):
    return function.__spectra_custom_node__


def _dataset(rows: int = 4, columns: int = 30):
    import spectra_sherpa.sdk as ss

    axis = np.linspace(400.0, 1800.0, columns)
    values = np.vstack([np.sin(axis / 200.0 + index) + 2.0 for index in range(rows)])
    return ss.data.from_array(values, x=axis, units="cm-1")


def _run(node_class, parameters=None, dataset=None):
    node = node_class("n1", parameters or {})
    return asyncio.run(node.execute(dataset if dataset is not None else _dataset())).outputs["default"]


# ── Author contract ────────────────────────────────────────────────────────


def test_decorator_records_a_description_and_leaves_the_function_callable():
    @custom_node(label="Offset", category="preprocessing")
    def offset(spectra: np.ndarray, amount: Annotated[float, param(min=-5, max=5)] = 1.0) -> np.ndarray:
        """Add a constant."""
        return spectra + amount

    spec = _spec(offset)
    assert (spec.name, spec.label, spec.description, spec.input_kind, spec.output_kind) == (
        "offset",
        "Offset",
        "Add a constant.",
        "array",
        "array",
    )
    assert [(item.name, item.kind, item.default) for item in spec.parameters] == [("amount", "number", 1.0)]
    assert offset(np.zeros((1, 2)), 2.0).tolist() == [[2.0, 2.0]]


@pytest.mark.parametrize("option", ["fits", "uses_target", "uses_groups", "changes_rows", "changes_axis"])
def test_unsupported_opt_ins_are_refused_by_name(option):
    with pytest.raises(CustomNodeError, match=f"{option}=True is not available in this release"):
        custom_node(label="X", **{option: True})


def test_definition_errors_name_the_fix():
    with pytest.raises(CustomNodeError, match="needs a default value"):

        @custom_node(label="X")
        def missing(spectra: Spectra, width: int) -> Spectra:
            return spectra

    with pytest.raises(CustomNodeError, match="annotated as Spectra or numpy.ndarray"):

        @custom_node(label="X")
        def untyped(spectra, width: int = 1) -> Spectra:
            return spectra

    with pytest.raises(CustomNodeError, match="category must be one of"):
        custom_node(label="X", category="modeling")
    with pytest.raises(CustomNodeError, match="random_seed must name an int parameter"):

        @custom_node(label="X", random_seed="seed")
        def stochastic(spectra: Spectra, seed: float = 1.0) -> Spectra:
            return spectra


# ── Generated node and run-time defaults ───────────────────────────────────


def test_generated_node_has_a_local_untrusted_contract():
    @custom_node(label="Mode", category="preprocessing")
    def mode(spectra: Spectra, kind: Literal["a", "b"] = "a", flag: bool = False) -> Spectra:
        return spectra

    node_class = custom_nodes.build_node_class(_spec(mode), "lab-nodes", "1.2.0")
    metadata = node_class.get_metadata()
    payload = metadata.resolved_execution_contract().payload
    assert metadata.node_type == "user.lab-nodes.mode" and metadata.distribution == "user"
    assert payload["runtime_family"] == "approved_custom"
    assert payload["custom_trust_class"] == "local_untrusted"
    assert list(payload["managed_optimization_eligibility"]) == ["local"]
    assert list(payload["managed_optimization_profiles"]) == []
    assert (payload["sample_effect"], payload["feature_effect"], payload["axis_effect"], payload["unit_effect"]) == (
        "preserves_samples",
        "preserves_features",
        "preserves_axis",
        "preserves_units",
    )
    assert payload["target_access"] == "none" and payload["group_access"] == "none"
    assert payload["implementation_components"][0]["component_id"] == mode.__module__
    assert [(item.name, item.param_type) for item in metadata.parameters] == [("kind", "select"), ("flag", "boolean")]


def test_parameters_are_refused_never_repaired():
    @custom_node(label="Window")
    def window(spectra: Spectra, width: Annotated[int, param(min=3, max=9, odd=True)] = 5) -> Spectra:
        return spectra

    spec = _spec(window)
    assert custom_nodes.canonical_parameters(spec, {}) == {"width": 5}
    assert custom_nodes.canonical_parameters(spec, {"width": 7.0}) == {"width": 7}
    for bad, message in ((4, "must be odd"), (11, "at most 9"), (True, "finite number"), (5.5, "whole number")):
        with pytest.raises(CustomNodeError, match=message):
            custom_nodes.canonical_parameters(spec, {"width": bad})
    with pytest.raises(CustomNodeError, match="Unknown parameter"):
        custom_nodes.canonical_parameters(spec, {"other": 1})


def test_values_change_and_metadata_survives():
    @custom_node(label="Double")
    def double(spectra: Spectra) -> Spectra:
        return spectra.with_values(spectra.values * 2.0)

    source = _dataset()
    output = _run(custom_nodes.build_node_class(_spec(double), "lab", "0.0.0"), dataset=source)
    assert np.allclose(output.X, source.X * 2.0)
    assert output.feature_axis.units == source.feature_axis.units
    assert np.allclose(output.feature_axis.values, source.feature_axis.values)
    from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history

    step = get_processing_history(output)[-1]
    assert step["op_id"] == "user.lab.double" and step["impact"]["source"] == "lab"


def test_run_time_checks_enforce_the_defaults():
    @custom_node(label="Trim")
    def trim(spectra: np.ndarray) -> np.ndarray:
        return spectra[:, 2:-2]

    @custom_node(label="Drop row")
    def drop(spectra: np.ndarray) -> np.ndarray:
        return spectra[1:]

    @custom_node(label="Nan")
    def nan(spectra: Spectra) -> Spectra:
        values = spectra.values
        values[0, 0] = np.nan
        return spectra.with_values(values)

    for function, message in (
        (trim, "declare changes_features=True"),
        (drop, "keep every sample"),
        (nan, "NaN or infinite"),
    ):
        with pytest.raises(CustomNodeError, match=message):
            _run(custom_nodes.build_node_class(_spec(function), "lab", "0.0.0"))


def test_changes_features_keeps_a_declared_subset_with_its_axis():
    @custom_node(label="Crop", changes_features=True)
    def crop(spectra: Spectra) -> Spectra:
        kept = spectra.select_features(slice(5, 25))
        return kept.with_values(kept.values - 1.0)

    source = _dataset()
    node_class = custom_nodes.build_node_class(_spec(crop), "lab", "0.0.0")
    assert node_class.get_metadata().resolved_execution_contract().payload["feature_effect"] == "filters_features"
    output = _run(node_class, dataset=source)
    assert output.shape == (4, 20)
    assert np.allclose(output.feature_axis.values, source.feature_axis.values[5:25])
    assert np.allclose(output.X, source.X[:, 5:25] - 1.0)


def test_custom_functions_never_see_reference_values_or_the_dataset():
    import spectra_sherpa.sdk as ss

    seen = {}

    @custom_node(label="Probe")
    def probe(spectra: Spectra) -> Spectra:
        seen["dataset"] = hasattr(spectra, "dataset")
        seen["slots"] = [type(getattr(spectra, name)).__name__ for name in Spectra.__slots__]
        return spectra.with_values(spectra.values + 1.0)

    axis = np.linspace(400.0, 1800.0, 12)
    values = np.vstack([np.sin(axis / 200.0) + index for index in range(5)])
    source = ss.data.from_array(values, x=axis, units="cm-1", y=np.arange(5.0), y_name="moisture")
    output = _run(custom_nodes.build_node_class(_spec(probe), "lab", "0.0.0"), dataset=source)
    assert seen["dataset"] is False
    # Only copied arrays, units, positions and an opaque origin token reach the function.
    assert set(seen["slots"]) <= {"ndarray", "str", "NoneType", "bool", "object"}
    # The engine rebuilt the output from its own dataset, so reference values survive untouched.
    assert np.allclose(output.target, source.target) and np.allclose(output.X, values + 1.0)


def test_a_function_cannot_return_spectra_it_did_not_receive():
    @custom_node(label="Forge")
    def forge(spectra: Spectra) -> Spectra:
        return Spectra(np.zeros(spectra.shape))

    with pytest.raises(CustomNodeError, match="must return the spectra it received"):
        _run(custom_nodes.build_node_class(_spec(forge), "lab", "0.0.0"))


# ── Sources and composition ────────────────────────────────────────────────


def _source(root: Path, name: str, body: str = DESPIKE, filename: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / (filename or f"{name}.py")).write_text(body)
    return folder


def test_a_folder_source_composes_as_one_user_pack(tmp_path):
    folder = _source(tmp_path, "whitaker_hayes")
    composed, statuses = custom_nodes.compose_sources([custom_nodes.folder_candidate(folder)])
    assert [status.status for status in statuses] == ["loaded"]
    result = composed[0][1]
    identity = result.identity("folder")
    assert (identity["source"], [node[0] for node in identity["nodes"]]) == (
        "whitaker-hayes",
        ["user.whitaker-hayes.despike"],
    )
    # Every file of the folder is part of its recorded build.
    (folder / "notes.txt").write_text("calibrated on 2026-11-20")
    again, _ = custom_nodes.compose_sources([custom_nodes.folder_candidate(folder)])
    assert again[0][1].build_sha256 != result.build_sha256


def test_failing_and_colliding_sources_are_reported_not_loaded(tmp_path):
    good = _source(tmp_path / "a", "good")
    broken = _source(tmp_path / "a", "broken", "raise RuntimeError('import failed on purpose')\n")
    first = _source(tmp_path / "b", "twin", filename="one.py")
    second = _source(tmp_path / "c", "twin", filename="two.py")
    packs, statuses = custom_nodes.compose_sources(
        [custom_nodes.folder_candidate(path) for path in (good, broken, first, second)]
    )
    assert [result.source for _, result in packs] == ["good"]
    by_location = {status.location: status for status in statuses}
    assert by_location[str(broken)].status == "failed"
    assert "import failed on purpose" in by_location[str(broken)].message
    assert "Two sources use the name 'twin'" in by_location[str(first)].message


def test_source_names_are_normalized_or_refused():
    assert custom_nodes.source_id("Whitaker_Hayes") == "whitaker-hayes"
    with pytest.raises(CustomNodeError, match="start it with a letter"):
        custom_nodes.source_id("2nd")


def test_custom_nodes_never_replace_built_ins_or_load_late():
    from spectra_sherpa.app.services.dag.node_base import NodeRegistry, node_registry

    @custom_node(label="Late")
    def late(spectra: Spectra) -> Spectra:
        return spectra

    node_class = custom_nodes.build_node_class(_spec(late), "lab", "0.0.0")
    node_registry.list_nodes()  # an ordinary read seals the catalog
    with pytest.raises(ValueError, match="composed at startup"):
        node_registry.compose_local_custom_nodes((node_class,), [])
    isolated = NodeRegistry(managed_startup=True)
    isolated._finish_builtin_imports()
    impostor = type("Impostor", (node_class,), {"metadata": replace(node_class.metadata, distribution="oss")})
    with pytest.raises(ValueError, match="user distribution"):
        isolated.compose_local_custom_nodes((impostor,), [])
    assert not isolated.is_frozen  # a refused composition leaves the catalog usable


def test_missing_custom_node_names_how_to_restore_it():
    from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
    from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow

    result = preflight_workflow([WorkflowNode("n1", "user.lab.despike", {})], [])
    issue = next(issue for issue in result.issues if issue.code == "unknown_node_type")
    assert "Restore its source in your My nodes folder" in issue.message


def test_nodes_check_reports_success_and_the_fix(tmp_path):
    folder = _source(tmp_path, "whitaker_hayes")
    passed, lines = custom_nodes.check_source(str(folder / "whitaker_hayes.py"))
    assert passed and any(line.startswith("OK user.whitaker-hayes.despike") for line in lines)
    bad = _source(
        tmp_path,
        "trim",
        "import numpy as np\nfrom spectra_sherpa.sdk.custom import custom_node\n\n"
        "@custom_node(label='Trim')\ndef trim(spectra: np.ndarray) -> np.ndarray:\n"
        "    return spectra[:, 1:]\n",
    )
    passed, lines = custom_nodes.check_source(str(bad))
    assert not passed and "declare changes_features=True" in "\n".join(lines)


def test_every_documented_example_passes_the_self_check(tmp_path):
    import re

    page = (PACKAGE_ROOT / "docs" / "developers" / "custom-nodes.md").read_text(encoding="utf-8")
    examples = [block for block in re.findall(r"```python\n(.*?)```", page, re.S) if "@custom_node" in block]
    assert len(examples) >= 4
    for index, example in enumerate(examples):
        folder = _source(tmp_path, f"example_{index}", example)
        passed, lines = custom_nodes.check_source(str(folder))
        assert passed, "\n".join(lines)


# ── Whole-process behavior (fresh interpreters own the global catalog) ────


def _app_process(tmp_path: Path, script: str, **env: str) -> dict:
    data = tmp_path / "data"
    _source(data / "user" / "my_nodes", "whitaker_hayes")
    environment = {**os.environ, "DATA_DIR": str(data), "SPECTRA_SHERPA_CUSTOM_NODES": "1", **env}
    environment["PYTHONPATH"] = os.pathsep.join([str(PACKAGE_ROOT / "src"), str(PACKAGE_ROOT), *sys.path])
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=180,
        env=environment,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_local_workbench_loads_runs_and_binds_a_custom_node(tmp_path):
    report = _app_process(
        tmp_path,
        """
        import asyncio, json
        import numpy as np
        import spectra_sherpa.app.main  # composes custom nodes before the catalog seals
        import spectra_sherpa.sdk as ss
        from spectra_sherpa.app.services import custom_nodes
        from spectra_sherpa.app.services.dag.node_base import node_registry
        from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
        from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile

        values = np.tile(np.sin(np.linspace(0, 6, 50)), (3, 1)); values[1, 20] += 5
        node = node_registry.create_node("user.whitaker-hayes.despike", "n1", {})
        output = asyncio.run(node.run(ss.data.from_array(values, x=np.linspace(400, 1800, 50), units="cm-1")))
        impact = get_processing_history(output.outputs["default"])[-1]["impact"]
        source = node_registry.custom_sources[0]
        print(json.dumps({
            "statuses": [s.as_dict()["status"] for s in custom_nodes.source_statuses()],
            "spike": float(output.outputs["default"].X[1, 20]),
            "recorded": impact["source_build_sha256"] == source["build_sha256"]
            and impact["execution_contract_sha256"] == source["nodes"][0][3],
            "profile": managed_optimization_profile().digest,
            "worker_initializer": custom_nodes.worker_initializer() is custom_nodes.initialize_custom_nodes,
        }))
        """,
    )
    assert report["statuses"] == ["loaded"]
    assert abs(report["spike"]) < 1.5
    assert report["recorded"] is True
    assert report["worker_initializer"] is True
    baseline = _app_process(
        tmp_path / "off",
        """
        import json
        import spectra_sherpa.app.main
        from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
        print(json.dumps({"profile": managed_optimization_profile().digest}))
        """,
        SPECTRA_SHERPA_CUSTOM_NODES="0",
    )
    # The managed-optimization vocabulary is unchanged by an installed custom node.
    assert baseline["profile"] == report["profile"]


def test_a_bad_source_folder_is_reported_and_workbench_still_starts(tmp_path):
    (tmp_path / "data" / "user" / "my_nodes" / "01-notes").mkdir(parents=True)
    (tmp_path / "data" / "user" / "my_nodes" / "empty").mkdir(parents=True)
    report = _app_process(
        tmp_path,
        """
        import json
        import spectra_sherpa.app.main  # startup must not abort
        from spectra_sherpa.app.services import custom_nodes
        from spectra_sherpa.app.services.dag.node_base import node_registry
        print(json.dumps({
            "statuses": {s.source: [s.status, s.message] for s in custom_nodes.source_statuses()},
            "loaded": [n.node_type for n in node_registry.list_nodes() if n.node_type.startswith("user.")],
        }))
        """,
    )
    assert report["loaded"] == ["user.whitaker-hayes.despike"]
    assert report["statuses"]["whitaker-hayes"][0] == "loaded"
    assert (
        report["statuses"]["01-notes"][0] == "failed" and "start it with a letter" in report["statuses"]["01-notes"][1]
    )
    assert report["statuses"]["empty"] == ["failed", "CustomNodeError: The folder has no .py files"]


def test_hosted_modes_never_load_custom_nodes(tmp_path):
    report = _app_process(
        tmp_path,
        """
        import json
        from spectra_sherpa.app.services import custom_nodes
        custom_nodes.initialize_custom_nodes()
        from spectra_sherpa.app.services.dag.node_base import node_registry
        print(json.dumps({
            "nodes": [n.node_type for n in node_registry.list_nodes() if n.node_type.startswith("user.")],
            "active": custom_nodes.active(),
        }))
        """,
        APP_MODE="enterprise",
    )
    assert report == {"nodes": [], "active": False}


def test_spawned_worker_runs_the_same_custom_node(tmp_path):
    report = _app_process(
        tmp_path,
        """
        import asyncio, json, os
        import numpy as np
        import spectra_sherpa.app.main
        from spectra_sherpa.app.services import custom_nodes
        from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool
        from tests.custom_node_worker import run_despike

        async def main():
            pool = IsolatedWorkerPool(1, initializer=custom_nodes.worker_initializer())
            try:
                async with pool.workflow():
                    remote = await pool.run(run_despike, timeout=60)
            finally:
                pool.shutdown()
            return remote

        remote = asyncio.run(main())
        local = run_despike()
        print(json.dumps({"different_process": remote[0] != local[0], "same": remote[1] == local[1]}))
        """,
    )
    assert report == {"different_process": True, "same": True}
