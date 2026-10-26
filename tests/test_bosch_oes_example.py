"""Regression checks for the seven findings in the original BOSCH prototype."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/bosch_oes"


def load(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_facade_does_not_register_an_abstract_dag_node():
    from spectra_sherpa.app.services.dag.node_base import node_registry

    before = node_registry.list_nodes()
    facade = load("bosch_parser_node")
    assert node_registry.list_nodes() == before
    assert not hasattr(facade.BoschOESNetCDFParserNode, "__abstractmethods__")
    with pytest.raises(ValueError, match="Phase-specific"):
        facade.BoschOESParser.parse_dataset(Path("absent.nc"), Path("absent.nc"), step_filter="etch_mean")
    with pytest.raises(ValueError, match="Phase-specific"):
        facade.BoschOESParser.parse_dataset(Path("absent.nc"), Path("absent.nc"), step_filter="passivation_mean")


def test_reference_candidate_and_transition_are_for_the_same_species(tmp_path):
    ref = tmp_path / "lines.csv"
    ref.write_text("wavelength,species\n251.9,CF2\n")
    analyzer = load("transition_analyzer").TransitionAnalyzer(ref)
    match = analyzer.identify_peak(251.61, 0.7)
    assert match["species"] == "CF2"
    assert match["nist_transition"]["species"].startswith("CF₂")
    assert match["nist_transition"]["wavelength_nm"] == 251.9


def test_csv_quotes_transition_terms_and_retains_zero_delta(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    runner = load("run_oes_workflow")
    ref = tmp_path / "lines.csv"
    ref.write_text("wavelength,species\n251.9,CF2\n")
    analyzer = load("transition_analyzer").TransitionAnalyzer(ref)
    output = tmp_path / "peaks.csv"
    runner.write_peak_csv(
        output, [{"median_pos": 251.9, "median_height": 20.0, "median_half_prominence_width": 0.5}], analyzer
    )
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and None not in rows[0]
    assert rows[0]["delta_nm"] == "0.0"
    assert rows[0]["term_transition"] == "(0,0,0) -> (0,v₂',0)"


def test_canonical_pipeline_reads_real_output_ports_and_emits_nonempty_peaks(tmp_path, monkeypatch):
    import h5py
    import numpy as np

    monkeypatch.syspath_prepend(str(EXAMPLE))
    runner = load("run_oes_workflow")
    source, dictionary = tmp_path / "Day.nc", tmp_path / "Dictionary.nc"
    for path in (source, dictionary):
        with h5py.File(path, "w") as f:
            f.attrs["_NCProperties"] = "version=2,netcdf=4.9.2,hdf5=1.14.4"
    with h5py.File(dictionary, "a") as f:
        f["data"] = np.arange(100, dtype=np.float32)
    x = np.arange(51)
    profile = (70 * np.exp(-(((x - 12) / 3) ** 2)) + 60 * np.exp(-(((x - 37) / 3) ** 2))).astype(np.uint16)
    with h5py.File(source, "a") as f:
        g = f.create_group("Wafer_01")
        g["data"] = np.tile(profile, (10, 1))
        g["wavelengths"] = np.linspace(250, 800, 51)
        g["times"] = np.arange(10, dtype=np.float64) * 0.04 + 1722855600.0
        g["times"].attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"
    output = tmp_path / "peaks.csv"
    report = runner.run_pipeline(source, dictionary, group="Wafer_01", row_count=10, output=output)
    assert report["consensus_peaks"] == 2
    with output.open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 2
