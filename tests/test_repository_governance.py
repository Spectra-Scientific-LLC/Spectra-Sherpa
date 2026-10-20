"""Public, platform-independent governance checks: no private receipts required."""

import importlib.util
import json
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
        '<script>const x = "execute workflow";</script><style>.data-portfolio {}</style>'
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


def test_authority_map_has_separate_owners_documents_tests_consumers():
    text = (ROOT / "docs/AUTHORITIES.md").read_text(encoding="utf-8")
    assert (
        "| Topic | Owning implementation / schema | Normative document | Enforcing tests / checks | Consumers |" in text
    )
    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert len(rows) >= 15
    assert all(len(line.split("|")) == 7 for line in rows)
    assert all(all(cell.strip() for cell in line.split("|")[1:-1]) for line in rows)
