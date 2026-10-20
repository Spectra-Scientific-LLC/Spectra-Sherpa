"""Advisor sees bounded scalar PLS-DA terms, never raw sample or class labels."""

import json

import pytest

from spectra_sherpa.app.services.diagnostic_review_summary import build_summary


def _receipt():
    return {
        "model_kind": "plsda",
        "fitted_state_sha256": "a" * 64,
        "feature_count": 3,
        "components": 2,
        "reference_count": 2,
        "screening_method": "prediction_f_and_residual_spectrum_0.95_strict_greater",
        "q_limit_method": "jackson_mudholkar",
        "score_covariance_rank": 2,
        "t2_limit": 5.0,
        "q_limit": 2.0,
        "t2_units": "dimensionless",
        "q_units": "squared standardized predictor units",
        "t2_unavailable_reason": None,
        "q_unavailable_reason": None,
        "feature_labels": ["SECRET-v1", "SECRET-v2", "SECRET-v3"],
        "rows": [
            {
                "id": "private:sample-1",
                "class": "SECRET-class",
                "scores": [1.0, 2.0],
                "t2": 6.0,
                "q": 0.4,
                "outside_t2": True,
                "outside_q": False,
                "terms": {
                    "variables": [[0, 0.25, 8.0], [1, 0.1, -3.0]],
                    "omitted_q": 0.05,
                    "omitted_t2": 1.0,
                    "omitted_t2_absolute": 1.0,
                },
            },
            {
                "id": "private:sample-2",
                "class": "SECRET-class",
                "scores": [0.0, 0.0],
                "t2": None,
                "q": 0.3,
                "outside_t2": None,
                "outside_q": False,
                "terms": {"variables": [], "omitted_q": 0.3, "omitted_t2": None, "omitted_t2_absolute": None},
            },
        ],
    }


def test_saved_plsda_packet_preserves_signed_terms_and_omits_private_labels():
    packet = build_summary(_receipt(), selected_ids=["private:sample-1"], variable_ids=[])
    assert packet["facts"]["S1.v0.t2"]["value"] == 8.0
    assert packet["facts"]["S1.v0.ordinal"]["value"] == 1
    assert packet["facts"]["S1.v1.t2"]["value"] == -3.0
    assert packet["facts"]["S1.omitted_t2"]["value"] == 1.0
    assert packet["facts"]["S1.q"]["value"] == 0.4
    assert packet["facts"]["selection.t2.outside"]["value"] == 1
    assert packet["contains_held_out"] is False
    serialized = json.dumps(packet)
    assert "SECRET" not in serialized
    assert "private:sample" not in serialized


def test_saved_plsda_packet_rejects_foreign_sample_and_variable_id():
    with pytest.raises(ValueError, match="unique saved calibration"):
        build_summary(_receipt(), selected_ids=["foreign"], variable_ids=[])
    with pytest.raises(ValueError, match="outside the fitted classifier"):
        build_summary(_receipt(), selected_ids=["private:sample-1"], variable_ids=["b" * 64 + ":0"])


def test_saved_plsda_packet_marks_missing_statistic_unknown():
    receipt = _receipt()
    receipt["t2_limit"] = None
    receipt["t2_unavailable_reason"] = "rank_deficient_score_covariance"
    packet = build_summary(receipt, selected_ids=["private:sample-2"], variable_ids=[])
    assert packet["facts"]["selection.t2.unknown"]["value"] == 1
    assert packet["facts"]["screening.t2_limit"]["value"] is None
    assert packet["facts"]["S2.t2"]["value"] is None


def test_default_terms_show_dominant_q_and_t2_drivers_not_lowest_indexes():
    receipt = _receipt()
    receipt["feature_count"] = 12
    receipt["rows"][0]["terms"]["variables"] = [[index, float(index + 1), float(index - 5)] for index in range(12)]
    packet = build_summary(receipt, selected_ids=["private:sample-1"], variable_ids=[])
    assert "S1.v11.q" in packet["facts"]
    assert "S1.v0.t2" in packet["facts"]
    assert len([key for key in packet["facts"] if key.startswith("S1.v") and key.endswith(".q")]) <= 10


def test_requested_nonretained_variable_is_explicitly_unavailable():
    packet = build_summary(_receipt(), selected_ids=["private:sample-1"], variable_ids=["a" * 64 + ":2"])
    assert packet["facts"]["S1.v2.unavailable"]["value"] is True
    assert "S1.v2.q" not in packet["facts"]


def test_shared_authority_preserves_classifier_facts_and_population():
    from spectra_sherpa.app.services.diagnostic_review_summary import SCHEMA, build_summary

    receipt = {**_receipt(), "model_kind": "plsda"}
    packet = build_summary(receipt, selected_ids=["private:sample-1"])
    assert packet["schema_version"] == SCHEMA
    assert packet["availability"] == "available"
    # Literal fixture expectations, not equality with a wrapper calling this
    # same implementation. Wrong scalar/sign/population must fail directly.
    assert packet["selection_count"] == 1
    assert packet["facts"]["S1.q"]["value"] == 0.4
    assert packet["facts"]["S1.v1.t2"]["value"] == -3.0
    assert len(packet["samples"]) == 1
    assert packet["samples"][0]["alias"] == "S1"
    assert packet["populations"] == {"calibration": {"total": 2, "selected": 1}}
    assert packet["contains_held_out"] is False
    assert "SECRET" not in json.dumps(packet)
    assert "private:sample" not in json.dumps(packet)
    with pytest.raises(ValueError, match="regression response"):
        build_summary(receipt, selected_ids=["private:sample-1"], response_index=1)
    with pytest.raises(ValueError, match="review state"):
        build_summary(receipt, selected_ids=["private:sample-1"], state={"marked": ["private:sample-1"]})


@pytest.mark.parametrize("kind", ["pcr", "simca", "knn", "svm", "random_forest", "lda", "svr", "linear"])
def test_unsupported_family_is_explicitly_unavailable_without_disclosure(kind):
    from spectra_sherpa.app.services.diagnostic_review_summary import build_summary

    packet = build_summary({"model_kind": kind, "rows": [{"id": "secret"}]}, selected_ids=["secret"])
    assert packet["availability"] == "unavailable"
    assert packet["facts"] == {}
    assert packet["populations"] == {}
    assert "secret" not in json.dumps(packet)
