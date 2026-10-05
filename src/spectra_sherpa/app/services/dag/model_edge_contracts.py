"""Refine broad model types with their producer-owned application contracts.

Inspection ports remain polymorphic. Computational consumers must accept the
actual producer/port, not merely a common ancestor such as RegressionModel.
"""

from .managed_port_topology import resolve_declared_port


def model_edge_error(source, source_port, target, target_port):
    try:
        output = resolve_declared_port(source, source_port, "output")
        input_port = resolve_declared_port(target, target_port, "input")
    except ValueError:
        return None  # Ordinary port admission owns missing declarations.
    if target.node_type == "model.predict_regression" and input_port.name == "fitted_state":
        allowed = {
            (name, "fitted_state")
            for name in (
                "model.fitted_pls",
                "model.fitted_pcr",
                "model.fitted_svr",
                "model.fitted_linear_regression",
                "model.pcr",
                "model.svr",
                "model.linear_regression",
            )
        }
    elif input_port.name == "fitted_state" and target.node_type.startswith(
        ("model.apply_fitted_", "classification.apply_")
    ):
        producer = target.node_type.replace(".apply_fitted_", ".fitted_")
        if target.node_type.startswith("classification.apply_"):
            producer = target.node_type.replace(".apply_", ".")
        allowed = {(producer, "fitted_state")}
    elif target.node_type == "model.pca_transform" and input_port.name == "model":
        allowed = {("model.pca", "model"), ("model.pca", "fitted_state")}
    elif target.node_type == "diagnostics.outliers" and input_port.name == "default":
        allowed = {("model.pca", "diagnostic_state"), ("diagnostics.outliers", "model")}
    elif target.node_type == "selection.variable_select" and input_port.name == "model":
        allowed = {("model.fitted_pls", "fitted_state")}
    elif target.node_type == "transfer.apply_fitted" and input_port.name == "fitted_state":
        allowed = {(name, "fitted_state") for name in ("transfer.ds", "transfer.pds", "transfer.sws")}
    else:
        return None
    if (source.node_type, output.name) in allowed:
        return None
    guidance = (
        "Use Predict Regression with the trainer's Fitted State output for interchangeable regression models."
        if "/RegressionModel/" in output.type_ref
        else "Connect the matching model's fitted state to this application node."
    )
    return (
        f"{target.label} ({target.node_type}) cannot consume {source.label} "
        f"({source.node_type}) output '{output.name}': incompatible fitted-model contract. {guidance}"
    )
