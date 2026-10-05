"""Contracts for the deliberately narrow optional SpectroChemPy adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.interoperability import spectrochempy_adapter

try:
    import spectrochempy as scp
except ImportError:
    scp = None

requires_scp = pytest.mark.skipif(scp is None, reason="spectrochempy not installed")


def _dataset(*, descending: bool = False) -> SherpaDataset:
    axis = np.asarray([400.0, 517.0, 801.0])
    if descending:
        axis = axis[::-1]
    return SherpaDataset(
        X=np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        feature_axis=SpectralAxis(values=axis, units="nm", title="Wavelength"),
        sample_axis=SampleAxis(labels=["first", "second"], title="Samples"),
        title="native",
    )


@pytest.mark.parametrize("descending", [False, True])
@requires_scp
def test_adapter_projects_only_the_exact_matrix_in_original_order(descending: bool) -> None:
    source = _dataset(descending=descending)
    projected = spectrochempy_adapter.to_spectrochempy_dataset(source, operation_id="model.efa")
    np.testing.assert_array_equal(np.asarray(projected.data), source.X)


@requires_scp
def test_mcr_initial_concentration_projection_is_exact() -> None:
    c0 = np.asarray([[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]])
    projected = spectrochempy_adapter.spectrochempy_dataset_from_array(
        c0,
        operation_id="model.mcr_als",
    )
    np.testing.assert_array_equal(np.asarray(projected.data), c0)


@pytest.mark.parametrize(
    "bad",
    [np.asarray([1.0, 2.0]), np.asarray([[1.0, np.nan]]), np.empty((0, 2))],
)
@requires_scp
def test_adapter_rejects_non_matrix_nonfinite_or_empty_input(bad: np.ndarray) -> None:
    with pytest.raises(ValueError):
        spectrochempy_adapter.spectrochempy_dataset_from_array(
            bad,
            operation_id="model.mcr_als",
        )


@requires_scp
def test_adapter_nonfinite_refusal_identifies_rows_and_recovery() -> None:
    source = _dataset()
    source.X[0, 1] = np.nan
    source.X[1, 2] = np.inf

    with pytest.raises(ValueError) as captured:
        spectrochempy_adapter.to_spectrochempy_dataset(source, operation_id="model.efa")

    message = str(captured.value)
    assert "SherpaDataset.X contains 2 missing or non-finite values" in message
    assert "sample row(s) 1, 2" in message
    assert "Prepare Samples" in message
    assert "do not infer replacement values implicitly" in message


def test_unknown_operation_cannot_expand_the_adapter_surface() -> None:
    with pytest.raises(ValueError, match="not an authority"):
        spectrochempy_adapter.require_spectrochempy("model.unapproved")


def test_adapter_public_surface_is_exactly_the_private_matrix_boundary() -> None:
    assert spectrochempy_adapter.__all__ == (
        "extract_efa_state",
        "extract_mcr_state",
        "extract_simplisma_state",
        "require_spectrochempy",
        "spectrochempy_dataset_from_array",
        "to_spectrochempy_dataset",
    )


def test_optional_runtime_state_is_closed_inside_the_adapter() -> None:
    class EFA:
        n_components = 2
        f_ev = np.asarray([[4.0, 2.0], [3.0, 1.0]])
        b_ev = np.asarray([[1.0, 3.0], [2.0, 4.0]])

    class MCR:
        C = np.asarray([[1.0, 0.0], [0.25, 0.75]])
        St = np.asarray([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0]])

    class SIMPLISMA:
        C = MCR.C
        St = MCR.St
        Pt = np.asarray([[0.1, 0.9, 0.2], [0.3, 0.4, 0.8]])
        purities = None

    efa = spectrochempy_adapter.extract_efa_state(EFA())
    mcr = spectrochempy_adapter.extract_mcr_state(MCR(), concentration_solver="nnls")
    simplisma = spectrochempy_adapter.extract_simplisma_state(SIMPLISMA())

    np.testing.assert_array_equal(efa.forward_ev, EFA.f_ev)
    np.testing.assert_array_equal(efa.backward_ev, EFA.b_ev)
    np.testing.assert_array_equal(mcr.C, MCR.C)
    np.testing.assert_array_equal(mcr.St, MCR.St)
    np.testing.assert_array_equal(simplisma.purities, np.asarray([0.9, 0.8]))


def test_all_three_optional_contracts_digest_bind_the_adapter() -> None:
    from spectra_sherpa.app.services.dag.node_base import node_registry

    for operation_id in ("model.efa", "model.mcr_als", "model.simplisma"):
        contract = node_registry.get_metadata(operation_id).resolved_execution_contract()
        component_ids = {component["component_id"] for component in contract.payload["implementation_components"]}
        assert "spectra_sherpa.interoperability.spectrochempy_adapter" in component_ids


@pytest.mark.parametrize("preimport", [False, True])
@requires_scp
def test_adapter_first_import_is_local_only_without_update_or_testdata_network(tmp_path: Path, preimport: bool) -> None:
    runtime_home = tmp_path / "home"
    config_home = runtime_home / "config"
    projects_home = runtime_home / "projects"
    for path in (runtime_home, config_home, projects_home):
        path.mkdir(parents=True, exist_ok=True)
    probe = r"""
import json
import os
import socket
import threading

attempts = []
thread_targets = []
def blocked(*args, **kwargs):
    del kwargs
    attempts.append(repr(args))
    raise RuntimeError("network blocked")

socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.getaddrinfo = blocked
original_start = threading.Thread.start
def tracked_start(thread):
    target = getattr(thread, "_target", None)
    thread_targets.append(
        f"{getattr(target, '__module__', '')}.{getattr(target, '__qualname__', '')}"
    )
    return original_start(thread)
threading.Thread.start = tracked_start
if os.getenv("SPECTRA_SCP_PREIMPORT") == "1":
    import spectrochempy
from spectra_sherpa.interoperability.spectrochempy_adapter import require_spectrochempy
module = require_spectrochempy("model.efa")
print(json.dumps({"attempts": attempts, "version": module.__version__, "thread_targets": thread_targets}))
"""
    environment = {
        **os.environ,
        "HOME": str(runtime_home),
        "XDG_CONFIG_HOME": str(runtime_home / ".config"),
        "SCP_CONFIG_HOME": str(config_home),
        "SCP_PROJECTS_HOME": str(projects_home),
        "MPLCONFIGDIR": str(runtime_home / "matplotlib"),
        "PYTHONNOUSERSITE": "1",
        "SPECTRA_SCP_PREIMPORT": "1" if preimport else "0",
    }
    environment.pop("DISABLE_AUTO_UPDATE", None)
    environment.pop("DOC_BUILDING", None)
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["attempts"] == []
    assert report["version"] == "0.8.1"
    forbidden_targets = {
        "spectrochempy.application.check_update.check_update",
        "spectrochempy.application.testdata.download_full_testdata_directory",
    }
    assert forbidden_targets.isdisjoint(report["thread_targets"])
