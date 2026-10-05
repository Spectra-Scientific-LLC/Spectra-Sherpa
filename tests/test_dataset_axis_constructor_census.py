from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "packages/spectra-sherpa/tools/generate_dataset_axis_constructor_census.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("dataset_axis_constructor_census", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checked_dataset_axis_constructor_census_is_current() -> None:
    module = _load_tool()
    expected = module.OUTPUT.read_bytes()
    checked = module.json.loads(expected)
    generated = module.census()
    assert module.stable_projection(checked) == module.stable_projection(generated)


def test_axis_constructor_census_detects_a_new_preservation_sensitive_path(tmp_path: Path) -> None:
    module = _load_tool()
    source_root = tmp_path / "src"
    source_root.mkdir()
    source = source_root / "derived.py"
    source.write_text(
        "def rebuild(axis):\n" "    return SampleAxis(values=axis.values, title=axis.title)\n",
        encoding="utf-8",
    )

    payload = module.census(source_root, repository_root=tmp_path)

    assert payload["constructor_call_count"] == 1
    assert payload["preservation_sensitive_call_count"] == 1
    assert payload["calls"][0]["keyword_arguments"] == ["title", "values"]


def test_axis_census_identity_ignores_line_shifts_but_detects_duplicate_calls(tmp_path: Path) -> None:
    module = _load_tool()
    source_root = tmp_path / "src"
    source_root.mkdir()
    source = source_root / "derived.py"
    source.write_text("def rebuild(axis):\n    return SampleAxis(values=axis.values)\n", encoding="utf-8")
    first = module.census(source_root, repository_root=tmp_path)
    source.write_text(
        "# review note\n\ndef rebuild(axis):\n    return SampleAxis(values=axis.values)\n", encoding="utf-8"
    )
    shifted = module.census(source_root, repository_root=tmp_path)
    assert shifted["census_sha256"] == first["census_sha256"]
    source.write_text(
        "def rebuild(axis):\n"
        "    return SampleAxis(values=axis.values)\n"
        "\n"
        "def rebuild_again(axis):\n"
        "    return SampleAxis(values=axis.values)\n",
        encoding="utf-8",
    )
    duplicated = module.census(source_root, repository_root=tmp_path)
    assert duplicated["census_sha256"] != first["census_sha256"]
