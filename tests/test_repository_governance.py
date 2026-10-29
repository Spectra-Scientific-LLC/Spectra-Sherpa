"""Public, platform-independent governance checks: no private receipts required."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_checker():
    spec = importlib.util.spec_from_file_location("copy_checker", ROOT / "scripts/check_user_copy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_user_copy_ratchet():
    checker = copy_checker()
    baseline = json.loads(checker.BASELINE.read_text(encoding="utf-8"))
    assert not checker.failures(checker.inventory(ROOT), baseline)


def test_copy_gate_ignores_identifiers_and_scientific_terms():
    checker = copy_checker()
    fragments = checker.copy_fragments(
        "<script>const execute_workflow = run; // execute workflow\n</script><style>.data-portfolio {}</style>"
        '<div :title="execute_workflow" data-id="data portfolio">'
        "{{ execute_workflow }} T² Q RMSEP holdout RMSECV</div>"
        "<pre>execute workflow</pre>",
        ".vue",
    )
    assert "execute workflow" not in " ".join(fragments)
    assert "T² Q RMSEP holdout RMSECV" in " ".join(fragments)
    assert checker.copy_fragments('<div title="Execute workflow">Data Portfolio</div>', ".vue") == [
        "Execute workflow",
        "Data Portfolio",
    ]
    assert checker.failures({"new.vue": {"execute-workflow": 1}}, {})
    assert checker.failures({}, {"old.vue": {"execute-workflow": 1}})


def test_copy_gate_covers_bound_attributes_interpolations_and_script_literals():
    checker = copy_checker()
    fragments = checker.copy_fragments(
        """<script setup>
        // Execute workflow is an old term.
        const message = "Execute workflow";
        const escaped = 'Data\\u0020Portfolio';
        const other = `Short scientific summary: ${name}`;
        </script>
        <div :title="ready ? 'Data Portfolio' : label">
        {{ ready ? "Execute workflow" : run_label }}
        </div>""",
        ".vue",
    )
    combined = " ".join(fragments)
    assert combined.count("Data Portfolio") == 2
    assert combined.count("Execute workflow") == 2
    assert "Short scientific summary" in combined
    assert "old term" not in combined
    assert checker.failures({"x": {"data-portfolio": 1}}, {"x": {"data-portfolio": 1}})


def test_copy_check_does_not_rewrite_baseline():
    checker = copy_checker()
    before = checker.BASELINE.read_bytes()
    subprocess.run([sys.executable, str(ROOT / "scripts/check_user_copy.py")], check=True)
    assert checker.BASELINE.read_bytes() == before


def test_precommit_has_no_bundle_or_automatic_staging():
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "git add" not in config
    assert "rebuild-frontend-static" not in config
    assert "npm run build" not in config
    assert "scripts/frontend_lint.py" in config


def test_frontend_lint_uses_the_same_warning_budget_locally_and_in_ci():
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["lint"] == "eslint src/ --max-warnings 300"
    assert '"--max-warnings", "300"' in (ROOT / "scripts/frontend_lint.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "run: npm run lint" in workflow
    assert "--max-warnings 310" not in workflow


def test_authority_map_has_separate_owners_documents_tests_consumers():
    text = (ROOT / "docs/AUTHORITIES.md").read_text(encoding="utf-8")
    assert (
        "| Topic | Owning implementation / schema | Normative document | Enforcing tests / checks | Consumers |" in text
    )
    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert len(rows) >= 15
    assert all(len(line.split("|")) == 7 for line in rows)
    assert all(all(cell.strip() for cell in line.split("|")[1:-1]) for line in rows)
    for line in rows[2:]:
        topic, _, _, enforcement, _ = [cell.strip() for cell in line.split("|")[1:-1]]
        references = re.findall(r"`([^`]+)`", enforcement)
        tests = [path for path in references if path.endswith((".py", ".test.ts", ".spec.ts"))]
        assert tests, f"{topic}: name a real enforcing test/check path, not a prose assurance"
        for path in tests:
            target = ROOT / path
            assert target.is_file(), f"{topic}: enforcing check does not exist: {path}"
            text = target.read_text(encoding="utf-8")
            assert (
                "def test" in text or re.search(r"\b(?:test|it)(?:\.each)?\s*\(", text) or "def main" in text
            ), f"{topic}: {path} is not an executable test/check"


def test_data_portfolio_is_approved_selection_terminology():
    checker = copy_checker()
    assert not any(re.search(pattern, "Data Portfolio", re.I) for pattern, _ in checker.RULES.values())
    assert "execute-workflow" in checker.RULES
    assert "scientific-summary" in checker.RULES
