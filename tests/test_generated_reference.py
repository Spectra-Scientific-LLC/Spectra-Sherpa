"""Generated node-reference drift and built-HTML help-link contracts."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_built_help as help_check
import generate_node_reference as reference


@pytest.fixture
def row() -> dict:
    return {
        "node_type": "test.example",
        "label": "Example",
        "execution_contract": {"payload": {"help_reference": "docs/nodes/example.md"}},
        "typed_ports": {
            "inputs_declared": True,
            "outputs_declared": True,
            "input_ports": [],
            "output_ports": [
                {
                    "name": "default",
                    "type_ref": "spectrasherpa://types/Array2D/1.0",
                    "required": True,
                    "variadic": False,
                    "accepted_data_roles": ["X_features"],
                }
            ],
        },
        "parameters": [
            {
                "name": "method",
                "param_type": "select",
                "required": True,
                "default": "a",
                "options": [{"label": "A | B", "value": "a"}, "b"],
                "min_value": None,
                "max_value": None,
                "step": None,
                "category": "advanced",
                "visible_when": {"enabled": [True]},
                "description": "Use <x> | y\non the same rows.",
                "hint": None,
                "max_value_reason": None,
            }
        ],
    }


def page(root: Path, content: str | None = None, *, name: str = "example.md") -> Path:
    target = root / "docs/nodes" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            content
            if content is not None
            else (
                f"# Methodology\n\nKeep scientific guidance.\n\n{reference.BEGIN}\nold\n{reference.END}"
                "\n\n## Examples\n\nKeep me.\n"
            )
        ),
        encoding="utf-8",
    )
    return target


def test_generated_reference_is_current_via_cli() -> None:
    """Ordinary pytest/CI must fail when metadata or the checked reference drifts."""
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (ROOT / "docs/nodes").glob("*.md")}
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/generate_node_reference.py"), "--check"],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before}


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_generation_is_deterministic_and_preserves_prose(tmp_path: Path, row: dict, newline: str) -> None:
    target = page(tmp_path)
    target.write_bytes(target.read_text(encoding="utf-8").replace("\n", newline).encode("utf-8"))
    second = copy.deepcopy(row)
    second["node_type"] = "test.another"
    assert reference.render_section([row, second]) == reference.render_section([second, row])
    before = target.read_bytes()
    modified = target.stat().st_mtime_ns
    assert reference.generate(tmp_path, [row], check=True) == [target]
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == modified
    assert reference.generate(tmp_path, [row], check=False) == [target]
    assert reference.generate(tmp_path, [row], check=False) == []
    assert reference.generate(tmp_path, [row], check=True) == []
    generated = target.read_bytes().decode("utf-8")
    assert generated.split(reference.BEGIN)[0] == before.decode("utf-8").split(reference.BEGIN)[0]
    assert generated.split(reference.END)[1] == before.decode("utf-8").split(reference.END)[1]
    assert help_check.generated_help_rows(tmp_path) == [
        {"node_type": row["node_type"], "execution_contract": row["execution_contract"]}
    ]


@pytest.mark.parametrize(
    "markers",
    [
        "",
        reference.BEGIN,
        reference.END,
        reference.BEGIN + reference.BEGIN + reference.END,
        reference.BEGIN + reference.END + reference.END,
        reference.END + reference.BEGIN,
    ],
)
@pytest.mark.parametrize("check", [True, False])
def test_bad_markers_fail_before_any_write(tmp_path: Path, row: dict, markers: str, check: bool) -> None:
    valid = page(tmp_path)
    broken = page(tmp_path, "# Scientific guidance\n" + markers, name="z-broken.md")
    second = copy.deepcopy(row)
    second["node_type"] = "test.broken"
    second["execution_contract"]["payload"]["help_reference"] = "docs/nodes/z-broken.md"
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (valid, broken)}
    with pytest.raises(ValueError, match="marker"):
        reference.generate(tmp_path, [row, second], check=check)
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before}


def test_missing_or_orphaned_pages_and_duplicate_nodes_refuse(tmp_path: Path, row: dict) -> None:
    with pytest.raises(ValueError, match="missing node help page"):
        reference.generate(tmp_path, [row], check=True)
    page(tmp_path)
    with pytest.raises(ValueError, match="Duplicate registry node"):
        reference.generate(tmp_path, [row, row], check=True)
    page(tmp_path, reference.BEGIN + reference.END, name="orphan.md")
    with pytest.raises(ValueError, match="orphaned"):
        reference.generate(tmp_path, [row], check=True)


def test_reference_projects_types_defaults_enums_and_escapes(row: dict) -> None:
    rendered = reference.render_section([row])
    assert "spectrasherpa://types/Array2D/1.0" in rendered
    assert "<code>&quot;a&quot;</code>" in rendered
    assert "A &#124; B" in rendered
    assert "Use &lt;x&gt; &#124; y<br>on the same rows." in rendered
    assert "visible_when" in rendered and "advanced" in rendered
    row["parameters"][0]["default"] = None
    assert "<code>null</code>" in reference.render_section([row])
    row["parameters"][0]["default"] = False
    assert "<code>false</code>" in reference.render_section([row])
    row["parameters"][0]["default"] = 0
    assert "<code>0</code>" in reference.render_section([row])


def test_method_topics_reads_authority_and_refuses_partial_parsing() -> None:
    source = 'export const METHOD_TOPICS = { first: "a/#one", second: "b/#two" } as const;'
    assert help_check.method_topics(source) == {"first": "a/#one", "second": "b/#two"}
    assert help_check.method_topics(source.replace("a/#one", "changed/#custom"))["first"] == "changed/#custom"
    for invalid in (
        source.replace('second: "b/#two"', "...otherTopics"),
        source.replace("second:", "first:"),
        source + source,
        "export const METHOD_TOPICS = {} as const;",
    ):
        with pytest.raises(ValueError):
            help_check.method_topics(invalid)


def test_help_checks_actual_html_ids_not_heading_slugs(tmp_path: Path, row: dict) -> None:
    target = tmp_path / "nodes/example/index.html"
    target.parent.mkdir(parents=True)
    target.write_text('<h2 id="explicit&amp;id">A different heading</h2><a name="legacy"></a>', encoding="utf-8")
    topics = {"custom": "nodes/example/#explicit%26id", "legacy": "nodes/example/#legacy"}
    assert help_check.check_built_help(tmp_path, topics, [row]) == []
    failures = help_check.check_built_help(tmp_path, {"wrong": "nodes/example/#a-different-heading"}, [row])
    assert len(failures) == 1 and "missing HTML anchor" in failures[0]
    target.unlink()
    failures = help_check.check_built_help(tmp_path, topics, [row])
    assert len(failures) == 3 and all("missing built HTML" in failure for failure in failures)


@pytest.mark.parametrize(
    "url",
    ["../outside/", "%2e%2e/outside/", "/absolute/", "https://example.com/", "nodes/a/?q=1", r"nodes\a/", "a.md"],
)
def test_help_urls_fail_closed(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError):
        help_check.built_target(tmp_path, url)


def test_generated_help_metadata_is_required_unique_and_bound_to_page(tmp_path: Path, row: dict) -> None:
    target = page(tmp_path)
    with pytest.raises(ValueError, match="metadata"):
        help_check.generated_help_rows(tmp_path)
    reference.generate(tmp_path, [row], check=False)
    valid = target.read_text()
    metadata_line = next(line for line in valid.splitlines() if line.startswith(reference.HELP_METADATA))
    target.write_text(valid.replace(metadata_line, metadata_line + "\n" + metadata_line))
    with pytest.raises(ValueError, match="metadata"):
        help_check.generated_help_rows(tmp_path)
    target.write_text(valid.replace("docs/nodes/example.md", "docs/nodes/elsewhere.md"))
    with pytest.raises(ValueError, match="containing page"):
        help_check.generated_help_rows(tmp_path)
    target.write_text(valid.replace('"test.example"]', '"test.example", "test.example"]'))
    with pytest.raises(ValueError, match="duplicate"):
        help_check.generated_help_rows(tmp_path)


def test_checker_can_start_without_site_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-B", "-S", str(ROOT / "scripts/check_built_help.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--site-dir" in result.stdout


def test_manual_schema_tables_were_replaced() -> None:
    for path in (ROOT / "docs/nodes").glob("*.md"):
        source = path.read_text(encoding="utf-8")
        assert "| Key Configuration |" not in source, path
        assert "| Main Configuration |" not in source, path
        assert "| Inputs | Outputs |" not in source, path
