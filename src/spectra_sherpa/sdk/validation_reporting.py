"""Shared interpretation vocabulary for existing run and campaign reports."""

from .validate import REGRESSION_METRIC_REGISTRY_VERSION


def regression_reporting_notes() -> dict[str, str]:
    """Return shared metric definitions and claim limitations without computing results."""
    return {
        "metric_registry_version": REGRESSION_METRIC_REGISTRY_VERSION,
        "residual": "prediction minus reference",
        "RMSE": "sqrt(sum(residual^2)/n); response units",
        "MAE": "sum(abs(residual))/n; response units",
        "bias": "sum(residual)/n; positive means overprediction; response units",
        "SEP": "sqrt(sum((residual-bias)^2)/(n-1)); undefined for n < 2; response units",
        "R2": "1 - sum(residual^2)/sum((reference-mean(reference))^2); undefined for constant references",
        "slope_intercept": "least-squares prediction versus reference; undefined for constant references",
        "RER": "reference range / SEP; undefined when SEP is zero; no automatic quality threshold",
        "repeat_spread": (
            "variation across partitions of the same dataset; " "not independent specimens or a confidence interval"
        ),
        "external_validation": (
            "requires independently justified population and no reuse for fitting, " "selection or interval calibration"
        ),
        "reproduction": "matching retained computation is not proof of predictive generalization",
    }
