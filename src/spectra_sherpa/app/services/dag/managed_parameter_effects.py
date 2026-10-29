"""Prospective PLS search controls; historical graph identity stays intact.

Manual fits use curves only for diagnostics. Automatic fits use their fold
count and search bound for selection: keep that selection protocol fixed
across proposed trials instead of optimizing the validation design itself.
"""

from collections.abc import Mapping

PLS_REPORTING_PARAMETER_NAMES = frozenset({"component_selection_rule", "component_curve_max", "component_cv_folds"})


def is_reporting_only_parameter(operation_id: str, parameter: str) -> bool:
    return operation_id == "model.fitted_pls" and parameter in PLS_REPORTING_PARAMETER_NAMES


def inactive_pls_count(operation_id: str, parameter: str, parameters: Mapping[str, object]) -> bool:
    return (
        operation_id == "model.fitted_pls"
        and parameter == "n_components"
        and parameters.get("component_fit_mode") == "one_standard_error"
    )
