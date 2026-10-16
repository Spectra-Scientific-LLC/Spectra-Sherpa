"""Bounded, label-free Advisor facts from a verified saved PLS-DA receipt."""

from __future__ import annotations

import json
from typing import Any

MAX_PACKET_BYTES = 16 * 1024


def build_plsda_summary(receipt: dict[str, Any], *, selected_ids: list[str], variable_ids: list[str]) -> dict[str, Any]:
    rows = receipt["rows"]
    selected = set(selected_ids)
    if not selected or len(selected) != len(selected_ids) or not selected.issubset({row["id"] for row in rows}):
        raise ValueError("Selection must identify unique saved calibration observations")
    feature_identity = receipt["fitted_state_sha256"]
    requested = set()
    for identity in variable_ids:
        prefix, sep, index = identity.rpartition(":")
        if not sep or prefix != feature_identity or not index.isdigit() or int(index) >= receipt["feature_count"]:
            raise ValueError("Selected variable is outside the fitted classifier")
        requested.add(int(index))
    packet: dict[str, Any] = {
        "schema_version": "diagnostic-review-plsda/1",
        "model_kind": "plsda",
        "contains_held_out": False,
        "population": "fitted calibration observations",
        "facts": {},
        "samples": [],
        "omissions": {"selected_sample_details": 0, "variable_details": 0},
        "limitations": [
            "This receipt contains calibration observations only; "
            "it does not establish held-out classification performance.",
            "Global predictor screening does not establish class probability, local support, "
            "prediction correctness or a measurement defect.",
            "Component loadings describe model patterns; Q and signed T-squared terms describe one selected sample.",
        ],
    }

    def fact(key: str, value: str | int | float | bool | None, meaning: str, units: str | None = None):
        entry: dict[str, Any] = {"value": value, "meaning": meaning, "population": "calibration"}
        if units:
            entry["units"] = units
        packet["facts"][key] = entry

    fact("selection.count", len(selected), "Selected calibration observations")
    fact("model.components", receipt["components"], "Retained latent variables")
    fact("calibration.count", receipt["reference_count"], "Fitted calibration observations")
    fact("screening.method", receipt["screening_method"], "Fitted global screening method")
    fact("screening.q_limit_method", receipt["q_limit_method"], "Fitted Q limit method")
    fact("screening.rank", receipt["score_covariance_rank"], "Fitted score covariance rank")
    fact("screening.t2_limit", receipt["t2_limit"], "Fitted T-squared prediction limit", receipt["t2_units"])
    fact("screening.q_limit", receipt["q_limit"], "Fitted Q residual limit", receipt["q_units"])
    for statistic in ("t2", "q"):
        fact(
            f"screening.{statistic}_unavailable_reason",
            receipt[f"{statistic}_unavailable_reason"],
            f"{statistic.upper()} unavailable reason",
        )
    ordered = [(index, row) for index, row in enumerate(rows) if row["id"] in selected]
    for statistic in ("t2", "q"):
        finite = [row[statistic] for _, row in ordered if row[statistic] is not None]
        fact(f"selection.{statistic}.valid", len(finite), f"Selected observations with available {statistic.upper()}")
        fact(
            f"selection.{statistic}.missing",
            len(ordered) - len(finite),
            f"Selected observations missing {statistic.upper()}",
        )
        outside = [row[f"outside_{statistic}"] for _, row in ordered]
        fact(
            f"selection.{statistic}.outside",
            sum(value is True for value in outside),
            f"Selected observations outside fitted {statistic.upper()} limit",
        )
        fact(
            f"selection.{statistic}.unknown",
            sum(value is None for value in outside),
            f"Selected observations with unknown {statistic.upper()} screen",
        )

    for index, row in ordered[:2]:
        alias = f"S{index + 1}"
        keys: list[str] = []

        def sample_fact(suffix: str, value: str | int | float | bool | None, meaning: str, units: str | None = None):
            key = f"{alias}.{suffix}"
            fact(key, value, meaning, units)
            keys.append(key)

        sample_fact("t2", row["t2"], "Sample total T-squared", receipt["t2_units"])
        sample_fact("q", row["q"], "Sample total Q residual", receipt["q_units"])
        sample_fact("outside_t2", row["outside_t2"], "Sample outside fitted T-squared limit")
        sample_fact("outside_q", row["outside_q"], "Sample outside fitted Q limit")
        for component, score in enumerate(row["scores"][:2], 1):
            sample_fact(f"score{component}", score, f"Fitted latent score {component}")
        terms = row["terms"]
        variables = terms["variables"]
        if requested:
            shown = [term for term in variables if term[0] in requested]
        else:
            # The retained union is ordered by feature index, not explanatory
            # strength. Show the leading Q and signed T² drivers separately.
            q_leaders = sorted(variables, key=lambda term: (-term[1], term[0]))[:5]
            t2_leaders = sorted(
                (term for term in variables if term[2] is not None),
                key=lambda term: (-abs(term[2]), term[0]),
            )[:5]
            shown = list({term[0]: term for term in [*q_leaders, *t2_leaders]}.values())
        packet["omissions"]["variable_details"] += len(variables) - len(shown)
        for variable, q, t2 in shown:
            sample_fact(f"v{variable}.ordinal", variable + 1, "One-based fitted predictor variable ordinal")
            sample_fact(
                f"v{variable}.q", q, f"Predictor variable {variable + 1} sample Q contribution", receipt["q_units"]
            )
            sample_fact(
                f"v{variable}.t2",
                t2,
                f"Predictor variable {variable + 1} sample signed T-squared contribution",
                receipt["t2_units"],
            )
        for variable in sorted(requested - {term[0] for term in shown}):
            sample_fact(f"v{variable}.ordinal", variable + 1, "One-based fitted predictor variable ordinal")
            sample_fact(
                f"v{variable}.unavailable",
                True,
                f"Requested predictor variable {variable + 1} was not retained among the bounded per-sample terms; "
                "its individual Q and T-squared contributions are unavailable.",
            )
        sample_fact("omitted_q", terms["omitted_q"], "Receipt omitted Q contribution", receipt["q_units"])
        sample_fact(
            "omitted_t2", terms["omitted_t2"], "Receipt omitted signed T-squared contribution", receipt["t2_units"]
        )
        sample_fact(
            "omitted_t2_absolute",
            terms["omitted_t2_absolute"],
            "Receipt omitted absolute T-squared mass",
            receipt["t2_units"],
        )
        packet["samples"].append({"alias": alias, "role": "calibration", "facts": keys})
    packet["omissions"]["selected_sample_details"] = len(ordered) - len(packet["samples"])
    if len(json.dumps(packet, allow_nan=False).encode()) > MAX_PACKET_BYTES:
        raise ValueError("Diagnostic Advisor packet exceeds its disclosure limit; narrow the selection")
    return packet
