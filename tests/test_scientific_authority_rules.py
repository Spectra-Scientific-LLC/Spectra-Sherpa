"""Shared rules must agree at preview, admission, execution, and retained reporting."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes.workflow_templates import _require_independent_classification_group
from spectra_sherpa.app.services.run_validation_summary import _retained_target_unit_context
from spectra_sherpa.core.specimen_independence import (
    cross_block_violations,
    independence_preview,
    independence_violations,
)
from spectra_sherpa.core.target_units import TargetUnits, resolve_response_units, resolve_target_units


@pytest.mark.parametrize("target_type", ["continuous", "categorical"])
@pytest.mark.parametrize("group", [None, "block", "specimen_id", "patient_id"])
def test_preview_and_starter_use_execution_rule(target_type, group):
    table = {
        "specimen_id": ["a", "a", "b", "b", "c", "c", "d", "d"],
        "patient_id": ["p", "p", "p", "p", "q", "q", "q", "q"],
        "block": ["one", "two"] * 4,
    }
    common = dict(n_samples=8, target_type=target_type, target_names=["response"])
    expected = independence_violations(table, groups=table.get(group), **common)
    preview = independence_preview(table, group_column=group, **common)
    assert [item["code"] for item in preview["violations"]] == [item.code for item in expected]
    assert preview["suggested_groups"] == ["patient_id"]
    dataset = SimpleNamespace(n_samples=8, sample_axis=SimpleNamespace(sample_table=table))
    binding = SimpleNamespace(target_type=target_type, selected_target="response", group_column=group)
    # The UI profile is not allowed to override actual retained specimen columns.
    if expected:
        with pytest.raises(HTTPException) as refused:
            _require_independent_classification_group(dataset, binding, {"identity_fields": []})
        assert refused.value.detail == expected[0].message
    else:
        _require_independent_classification_group(dataset, binding, {"identity_fields": []})


def test_identity_values_are_case_sensitive_and_partial_identity_fails_closed():
    table = {"specimen_id": ["a", "a", "A", "A"]}
    assert not independence_violations(table, n_samples=4, target_type="continuous", groups=table["specimen_id"])
    table["specimen_id"][2] = None
    assert (
        independence_violations(table, n_samples=4, target_type="continuous", groups=["a", "a", "A", "A"])[0].code
        == "incomplete_identity"
    )
    assert independence_preview(None, n_samples=None, target_type="continuous")["checked"] is False


def test_known_specimen_cross_block_is_distinct_from_unseen_specimen_validation():
    table = {"specimen_id": ["a", "b", "a", "b"]}
    assert not cross_block_violations(table, n_samples=4, train_indices=[0, 1], test_indices=[2, 3])
    assert (
        independence_violations(table, n_samples=4, target_type="continuous", groups=[1, 1, 2, 2])[0].code
        == "divided_specimen"
    )
    table["specimen_id"][-1] = "new"
    assert (
        cross_block_violations(table, n_samples=4, train_indices=[0, 1], test_indices=[2, 3])[0].code == "new_specimen"
    )
    assert (
        cross_block_violations({}, n_samples=4, train_indices=[0, 1], test_indices=[2, 3])[0].code
        == "missing_specimen_identity"
    )


@pytest.mark.parametrize(
    "values, expected",
    [
        (["wt %", "wt %"], TargetUnits("recorded", "wt %")),
        (["wt %", "mg/L"], TargetUnits("ambiguous")),
        (["wt %", None], TargetUnits("missing")),
        ([], TargetUnits("missing")),
    ],
)
def test_unit_agreement_is_not_a_first_nonempty_fallback(values, expected):
    assert resolve_target_units(values) == expected


def test_response_units_select_by_exact_name_or_index():
    names, units = ["Moisture", "Protein"], ["wt %", "mg/L"]
    assert resolve_response_units(names, units, "Protein") == TargetUnits("recorded", "mg/L")
    assert resolve_response_units(names, units, 0) == TargetUnits("recorded", "wt %")
    assert resolve_response_units(names, units, None).state == "ambiguous"
    assert resolve_response_units(names, units, "protein").state == "missing"
    assert resolve_response_units(["Protein", "Protein"], units, "Protein").state == "ambiguous"


def test_retained_response_units_respect_branch_response_and_missing_selected_authority():
    def revision(node, column, units):
        return {
            "source_node_id": node,
            "revision_number": 1,
            "selection": {"target_authority": {"column": column, "units": units}},
        }

    run = SimpleNamespace(
        source_metadata={
            "data_selection_revisions": [
                revision("source", "Moisture", "wt %"),
                revision("other_source", "Moisture", "g/L"),
                revision("response", "Protein", "mg/L"),
            ]
        },
        evidence_completeness={},
    )
    definition = {
        "edges": [
            {"from_node_id": "source", "to_node_id": "model"},
            {"from_node_id": "response", "to_node_id": "model"},
        ]
    }
    assert _retained_target_unit_context(run, definition, "model", "Moisture") == TargetUnits("recorded", "wt %")
    assert _retained_target_unit_context(run, definition, "model", "Protein") == TargetUnits("recorded", "mg/L")
    assert _retained_target_unit_context(run, definition, "model").state == "ambiguous"
    run.source_metadata["data_selection_revisions"][0]["selection"]["target_authority"]["units"] = None
    assert _retained_target_unit_context(run, definition, "model", "Moisture").state == "missing"
