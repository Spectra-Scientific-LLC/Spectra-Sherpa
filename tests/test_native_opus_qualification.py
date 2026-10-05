from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from spectra_sherpa.ingestion_errors import ParserLimitError
from spectra_sherpa.io import ingest
from spectra_sherpa.io import registry as ingestion_registry
from spectra_sherpa.io.types import SourceMember

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "qualify_native_opus_ingestion.py"
REPORT_PATH = REPO_ROOT / "docs" / "evidence" / "native-opus-ingestion-qualification.json"

SPEC = importlib.util.spec_from_file_location("qualify_native_opus_ingestion", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def _report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _accept_refreshed_digest(monkeypatch: pytest.MonkeyPatch, report: dict) -> None:
    monkeypatch.setattr(TOOL, "CHECKED_REPORT_SHA256", hashlib.sha256(TOOL._canonical_bytes(report)).hexdigest())


def _isolate_spectrochempy_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(sys.modules):
        if name == "spectrochempy" or name.startswith("spectrochempy."):
            monkeypatch.delitem(sys.modules, name)


def test_checked_native_opus_report_is_closed_and_semantically_valid() -> None:
    TOOL.validate_public_report(_report())


def test_report_uses_the_canonical_native_ingestion_implementation_closure() -> None:
    expected = {
        ingestion_registry.__name__,
        *(module.__name__ for module in ingestion_registry.native_implementation_modules()),
    }
    observed = _report()["parser"]["implementation_source_sha256"]
    assert set(observed) == expected
    assert "spectra_sherpa.io.formats._helpers" in observed
    assert "spectra_sherpa.app.lib.io" in observed


def test_direct_helper_source_change_changes_the_implementation_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    native_sha = TOOL._stream_sha256
    helper_module = next(
        module
        for module in ingestion_registry.native_implementation_modules()
        if module.__name__ == "spectra_sherpa.io.formats._helpers"
    )
    helper_path = Path(helper_module.__file__).resolve()

    def changed_helper(path: Path, *, expected_size: int | None = None) -> tuple[int, str]:
        size, digest = native_sha(path, expected_size=expected_size)
        return (size, "0" * 64) if path == helper_path else (size, digest)

    before = TOOL._source_modules(REPO_ROOT)
    monkeypatch.setattr(TOOL, "_stream_sha256", changed_helper)
    after = TOOL._source_modules(REPO_ROOT)
    assert after["spectra_sherpa.io.formats._helpers"]["sha256"] == "0" * 64
    assert after != before


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("claim_boundary",), "general OPUS compatibility"),
        (("nonclaims",), []),
        (("privacy", "external_source_paths_in_report"), True),
        (("parser", "implementation_commit"), "0" * 40),
        (("parser", "implementation_source_sha256"), {}),
        (("runtime", "python"), "invented"),
        (("conformance_authority", "retained_scope_sha256"), "0" * 64),
        (("execution", "spectrochempy_loaded_after"), True),
        (("execution", "native_ingestion_only"), False),
        (("execution", "fixture_count"), 8),
        (("execution", "asset_count"), 1),
        (("execution", "fixtures", 0, "source_sha256"), "0" * 64),
        (("execution", "fixtures", 0, "source_size_bytes"), 1),
        (("execution", "fixtures", 0, "scientific_projection_sha256"), "0" * 64),
        (("execution", "fixtures", 0, "source_kind"), "external_ephemeral_not_redistributed"),
    ],
)
def test_semantic_mutations_fail_even_with_refreshed_whole_file_digest(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[object, ...],
    value: object,
) -> None:
    report = copy.deepcopy(_report())
    cursor = report
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    if path[:1] == ("runtime",):
        report["runtime_sha256"] = TOOL._digest_json(report["runtime"])
    if path[:2] == ("execution", "fixtures"):
        report["execution"]["fixture_projection_sha256"] = TOOL._digest_json(report["execution"]["fixtures"])
    _accept_refreshed_digest(monkeypatch, report)
    with pytest.raises(TOOL.QualificationError):
        TOOL.validate_public_report(report)


def test_report_rejects_unknown_nested_fields_even_with_refreshed_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    report = copy.deepcopy(_report())
    report["execution"]["invented"] = True
    _accept_refreshed_digest(monkeypatch, report)
    with pytest.raises(TOOL.QualificationError, match="schema is not closed"):
        TOOL.validate_public_report(report)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"one","schema_version":"two"}\n', encoding="utf-8")
    with pytest.raises(TOOL.QualificationError, match="duplicate JSON key"):
        TOOL._read_json(path)


def test_source_reader_rejects_symlink_and_oversize_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.0"
    source.write_bytes(b"OPUS")
    linked = tmp_path / "linked.0"
    linked.symlink_to(source)
    with pytest.raises(TOOL.QualificationError, match="non-symlink"):
        TOOL._stream_sha256(linked)

    monkeypatch.setattr(TOOL, "MAX_SOURCE_BYTES", 3)
    with pytest.raises(TOOL.QualificationError, match="exceeds"):
        TOOL._stream_sha256(source)


def test_external_locator_refuses_aliases_and_traversal() -> None:
    assert TOOL._validated_locator("irdata/OPUS/test.0000") == "irdata/OPUS/test.0000"
    for value in ("/irdata/OPUS/test.0000", "irdata/../secret", "irdata//OPUS/test.0000", "OPUS/test.0000"):
        with pytest.raises(TOOL.QualificationError):
            TOOL._validated_locator(value)


def test_live_exact_external_corpus_reproduces_checked_report() -> None:
    import os

    root = os.environ.get("SPECTRA_EXTERNAL_VENDOR_CORPUS")
    if not root:
        pytest.skip("external OPUS qualification corpus is not installed")
    TOOL.check_corpus(external_root=Path(root), report=_report())


def test_optional_scp_ci_runs_qualification_in_a_fresh_process_before_combined_suite() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    unit_command = "poetry run pytest tests/test_native_opus_qualification.py"
    live_command = "poetry run python tools/qualify_native_opus_ingestion.py check-corpus"
    combined_command = "tests/test_scp_contracts.py"
    assert workflow.count(unit_command) == 1
    assert workflow.count(live_command) == 1
    assert workflow.index(unit_command) < workflow.index(live_command) < workflow.index(combined_command)
    combined = workflow[workflow.index(combined_command) :]
    assert "tests/test_native_opus_qualification.py" not in combined


def test_cached_dependency_downloads_cannot_supply_a_stale_project_wheel() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    explicit_checkout_install = "poetry run pip install --no-deps --no-cache-dir --force-reinstall --editable ."

    assert "poetry install --with dev --no-root" in workflow
    assert "poetry install --with dev --extras postgres --no-root" in workflow
    assert "poetry install --with dev --extras scp --no-root" in workflow
    jobs = yaml.safe_load(workflow)["jobs"]
    for name in ("sherpa-backend", "sherpa-backend-native", "sherpa-scp-compat"):
        commands = [step.get("run", "") for step in jobs[name]["steps"]]
        assert any(explicit_checkout_install in command for command in commands), name


def test_standalone_installed_authority_resolves_to_repository_source() -> None:
    """Catch wheel installs hidden by pytest's configured ``src`` path."""

    source_root = REPO_ROOT / "packages" / "spectra-sherpa" / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
from pathlib import Path
import sys
from spectra_sherpa.io import registry

root = Path(sys.argv[1]).resolve()
modules = (registry, *registry.native_implementation_modules())
outside = [
    f"{module.__name__}={Path(module.__file__ or '').resolve()}"
    for module in modules
    if not Path(module.__file__ or '').resolve().is_relative_to(root)
]
if outside:
    raise SystemExit("native ingestion authority escaped repository source: " + ", ".join(outside))
""",
            str(source_root),
        ],
        cwd=REPO_ROOT / "packages" / "spectra-sherpa",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _one_bundled_fixture_conformance(tmp_path: Path) -> tuple[dict, Path]:
    conformance = json.loads(
        (REPO_ROOT / "docs" / "evidence" / "native-opus-reader-conformance.json").read_text(encoding="utf-8")
    )
    record = conformance["bundled_fixtures"][0]
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    source = REPO_ROOT / conformance["bundled_fixture_root"] / record["filename"]
    target = fixture_root / record["filename"]
    target.write_bytes(source.read_bytes())
    conformance["bundled_fixture_root"] = "fixtures"
    conformance["bundled_fixtures"] = [record]
    conformance["external_fixtures"] = []
    return conformance, target


def test_parser_returned_source_member_must_equal_pre_admitted_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conformance, _target = _one_bundled_fixture_conformance(tmp_path)
    native_ingest = ingest
    _isolate_spectrochempy_modules(monkeypatch)

    def forged_member(path: Path, *, limits: object) -> object:
        result = native_ingest(path, limits=limits)
        original = result.source_members[0]
        return replace(
            result,
            source_members=(SourceMember(name=original.name, size_bytes=original.size_bytes, sha256="0" * 64),),
        )

    monkeypatch.setattr(TOOL, "ingest", forged_member)
    with pytest.raises(TOOL.QualificationError, match="source custody mismatch"):
        TOOL._fixture_rows(tmp_path, tmp_path / "external", conformance)


def test_between_open_oversize_substitution_is_refused_by_parser_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conformance, target = _one_bundled_fixture_conformance(tmp_path)
    native_sha = TOOL._stream_sha256
    calls = 0
    _isolate_spectrochempy_modules(monkeypatch)

    def replace_after_admission(path: Path, *, expected_size: int | None = None) -> tuple[int, str]:
        nonlocal calls
        result = native_sha(path, expected_size=expected_size)
        calls += 1
        if calls == 1:
            with target.open("r+b") as stream:
                stream.truncate(TOOL.MAX_SOURCE_BYTES + 1)
        return result

    monkeypatch.setattr(TOOL, "_stream_sha256", replace_after_admission)
    with pytest.raises(ParserLimitError, match="Source is .* parser limit"):
        TOOL._fixture_rows(tmp_path, tmp_path / "external", conformance)
