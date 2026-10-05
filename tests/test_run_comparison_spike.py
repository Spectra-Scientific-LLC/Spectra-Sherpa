from dataclasses import replace
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.services.run_comparison import (
    ResultRole,
    declared_result_roles,
    pair_result_roles,
    saved_run_result_pairs,
)


def test_historical_runs_without_declarations_report_every_pair():
    runs = [SimpleNamespace(id=i, diagnostics=None) for i in (1, 2, 3)]
    pairs = saved_run_result_pairs(runs)
    assert {(pair.left_run_id, pair.right_run_id) for pair in pairs} == {(1, 2), (1, 3), (2, 3)}
    assert all(pair.state == "insufficient_evidence" for pair in pairs)
    assert all(pair.reason and not pair.requires_pairing for pair in pairs)


def test_retained_declarations_override_missing_database_preview(tmp_path, monkeypatch):
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.run_comparison import saved_scientific_ledger

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    ledger = {
        "model": {
            "contract": {
                "schema_version": "spectrasherpa-node-presentation/1",
                "presentations": [
                    {"presentation_id": "scores", "kind": "pca_scores", "source_ports": ["scores"]},
                ],
            }
        }
    }
    evidence = retention.retain_run_outputs(
        1,
        {"model": {"scores": [[1, 2]]}},
        {
            "_scientific_presentations": ledger,
        },
    )
    run = SimpleNamespace(id=1, user_id=1, diagnostics=None, evidence_completeness=evidence)
    assert saved_scientific_ledger(run, "_scientific_presentations") == ledger
    second = SimpleNamespace(id=2, user_id=1, diagnostics=None, evidence_completeness=evidence)
    assert saved_run_result_pairs([run, second])[0].state == "comparable"
    item = evidence["outputs"]["__diagnostics__"]["_scientific_presentations"]
    (retention._user_directory(1) / f"{item['sha256']}.json").unlink()
    run.diagnostics = {"_scientific_presentations": ledger}
    assert saved_scientific_ledger(run, "_scientific_presentations") == {}


def test_identical_exact_retained_outputs_are_comparable_without_ranking():
    def run(identifier, node, digest):
        return SimpleNamespace(
            id=identifier,
            diagnostics={
                "_scientific_presentations": {
                    node: {
                        "contract": {
                            "schema_version": "spectrasherpa-node-presentation/1",
                            "presentations": [
                                {"presentation_id": "scores", "kind": "pca_scores", "source_ports": ["scores"]}
                            ],
                        }
                    }
                }
            },
            evidence_completeness={
                "schema_version": 1,
                "qualification": "qualified",
                "outputs": {
                    node: {
                        "scores": {
                            "state": "exact",
                            "storage": "file",
                            "sha256": digest,
                            "format_version": 1,
                            "byte_count": 100,
                        }
                    }
                },
            },
        )

    left, right = run(1, "old", "a" * 64), run(2, "renamed", "a" * 64)
    pair = saved_run_result_pairs([left, right])[0]
    assert pair.state == "comparable"
    assert "does not qualify metric ranking" in pair.reason
    right.evidence_completeness["outputs"]["renamed"]["scores"]["sha256"] = "b" * 64
    assert saved_run_result_pairs([left, right])[0].state == "insufficient_evidence"
    for item, node, version in [(left, "old", "1.0"), (right, "renamed", "2.0")]:
        item.diagnostics["_scientific_values"] = {
            node: {
                "scores": {
                    "schema_version": "spectrasherpa-scientific-value/1",
                    "type_ref": f"spectrasherpa://types/ScoreMatrix/{version}",
                }
            }
        }
    assert saved_run_result_pairs([left, right])[0].state == "incompatible"


def role(node, kind="pca_scores"):
    return ResultRole(node, "scores", kind, ("scores",))


def test_node_ids_do_not_establish_correspondence():
    pairs = pair_result_roles([role("old")], [role("new")])
    assert len(pairs) == 1
    assert not pairs[0].requires_pairing
    assert "not yet established" in pairs[0].reason
    different = pair_result_roles([role("same")], [role("same", "pls_scores")])
    assert len(different) == 2
    assert all(not pair.left or not pair.right for pair in different)


def test_ambiguity_is_not_resolved_by_matching_node_name():
    pairs = pair_result_roles([role("same"), role("other")], [role("same")])
    assert pairs[0].requires_pairing
    assert len(pairs[0].left) == 2


def test_unknown_historical_contract_does_not_acquire_current_semantics():
    assert declared_result_roles({"pca": {"contract": {"schema_version": "future"}}}) == []


def test_unmaterialized_optional_presentations_do_not_create_correspondence():
    record = {
        "contract": {
            "schema_version": "spectrasherpa-node-presentation/1",
            "presentations": [
                {"presentation_id": "result", "kind": "numeric_matrix", "source_ports": ["result"]},
                {"presentation_id": "labels", "kind": "categorical_labels", "source_ports": ["labels"]},
            ],
        },
        "presentations": [{"presentation_id": "result"}],
    }
    assert declared_result_roles({"apply": record}) == [ResultRole("apply", "result", "numeric_matrix", ("result",))]
    record["presentations"] = []
    assert declared_result_roles({"failed": record}) == []


@pytest.mark.parametrize("presentations", [None, 42, "scores", {}])
def test_malformed_historical_declaration_is_not_a_comparison_server_error(presentations):
    assert (
        declared_result_roles(
            {
                "pca": {
                    "contract": {"schema_version": "spectrasherpa-node-presentation/1", "presentations": presentations}
                }
            }
        )
        == []
    )


def test_saved_contract_reads_roles_not_display_names():
    records = {
        "renamed": {
            "contract": {
                "schema_version": "spectrasherpa-node-presentation/1",
                "presentations": [
                    {"presentation_id": "score", "label": "Anything", "kind": "pca_scores", "source_ports": ["scores"]}
                ],
            }
        }
    }
    assert declared_result_roles(records) == [ResultRole("renamed", "score", "pca_scores", ("scores",))]


@pytest.mark.asyncio
async def test_executed_qualification_families_keep_roles_across_renamed_workflows():
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dag.presentation_contract import describe_executed_presentations
    from spectra_sherpa.app.services.dag.scientific_values import describe_node_outputs
    from tests.run_evidence_cases import executed_cases

    cases = await executed_cases()
    types = {
        "pca": "model.pca",
        "pls": "model.fitted_pls",
        "classification": "classification.plsda",
        "hca": "model.hca",
        "transformed_data": "preprocess.scale",
    }
    for case, node_type in types.items():
        metadata = node_registry.get_metadata(node_type)
        record = describe_executed_presentations(metadata, describe_node_outputs(metadata, cases[case]))
        left = declared_result_roles({"original": record})
        right = declared_result_roles({"renamed": record})
        assert left, case
        pairs = pair_result_roles(left, right)
        assert all(pair.left and pair.right for pair in pairs), case
        assert all(role.node_id == "renamed" for pair in pairs for role in pair.right)
    # The older direct fitted-state application fixture has no executed node
    # declaration; its prediction keys must not invent one.
    assert declared_result_roles({"application": cases["model_application"]}) == []
