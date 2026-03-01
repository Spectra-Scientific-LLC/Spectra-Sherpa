"""Declarative base classes for spec-driven workflow nodes.

Phase 2 of the node architecture improvement plan.  These base classes let
authors define standard preprocessing transforms and sklearn-style estimators
by declaring a *spec* object instead of writing custom ``execute()`` and
``generate_python()`` methods.

Two families are provided:

* **TransformSpecNode** — stateless Dataset-in / Dataset-out transforms
  (e.g. ClipFloor, MeanCenter, SNV, ScaleMax).
* **EstimatorSpecNode** — sklearn-style fit/predict workflows
  (e.g. LinearRegression, SVR, PCR).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

from .export_helpers import (
    extract_data_lines,
    format_kwargs,
    format_value,
    header_line,
    wrap_result_lines,
)
from .io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    resolve_target_names,
    to_numpy_1d,
    to_numpy_2d,
)
from .meta_helpers import add_processing_step
from .node_base import Node

# ---------------------------------------------------------------------------
# TransformSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransformSpec:
    """Declarative specification for a stateless Dataset-in / Dataset-out transform.

    Attributes:
        transform_fn:
            ``(data: ndarray, **kwargs) -> ndarray``.  Receives the 2-D
            float64 matrix extracted from the input dataset.  *kwargs* come
            from ``param_map`` applied to the resolved node parameters.
        param_map:
            Maps ``NodeParameter.name`` → kwarg name passed to *transform_fn*.
            Entries that are the same on both sides can be omitted (identity
            mapping is the default).
        output_units:
            Static output units string (e.g. ``"dimensionless"``).
            ``None`` means "inherit from the input dataset".
        export_lines_fn:
            ``(params, inp, node_id, indent, use_scp) -> list[str]`` returning
            Python code lines for ``generate_python()``.  ``None`` falls back
            to auto-export or the ``Node`` base implementation.
        extra_imports:
            Additional import lines for the generated Python export script.
        input_dtype:
            dtype passed to ``to_numpy_2d``.  Default ``np.float64``.
        numpy_expr:
            Format string for auto-export.  Param names are substituted via
            ``str.format()``, and ``_data`` refers to the extracted numpy array.
            Example: ``"np.clip(_data, a_min={floor}, a_max=None)"``.
            When set, ``generate_python()`` auto-generates extraction →
            expression → result wrapping code.
    """

    transform_fn: Callable[..., np.ndarray]
    param_map: Dict[str, str] = field(default_factory=dict)
    output_units: Optional[str] = None
    export_lines_fn: Optional[Callable[..., List[str]]] = None
    extra_imports: List[str] = field(default_factory=list)
    input_dtype: Any = np.float64
    numpy_expr: Optional[str] = None
    state_effects: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TransformSpecNode
# ---------------------------------------------------------------------------


class TransformSpecNode(Node):
    """Base class for stateless transforms defined by a :class:`TransformSpec`.

    Subclasses declare only::

        metadata = NodeMetadata(...)
        spec = TransformSpec(...)

    and optionally set ``python_extra_imports`` at the class level.

    ``execute()`` and ``generate_python()`` are provided automatically.
    Subclasses may still override ``execute()`` (e.g. to add diagnostics)
    and call ``await super().execute(input_data)`` for the standard flow.
    """

    # Subclass MUST set this
    spec: TransformSpec = None  # type: ignore[assignment]

    def __init__(self, node_id: str, parameters: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(node_id, parameters)
        # Merge spec-level imports with class-level imports so that
        # python_export.py picks them up from the instance attribute.
        cls_imports: List[str] = list(getattr(type(self), "python_extra_imports", []))
        spec_imports = self.spec.extra_imports if self.spec else []
        seen: set[str] = set()
        merged: List[str] = []
        for imp in cls_imports + spec_imports:
            if imp not in seen:
                seen.add(imp)
                merged.append(imp)
        self.python_extra_imports = merged  # type: ignore[assignment]

    # -- execute -------------------------------------------------------------

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:  # noqa: D401
        """Standard transform: coerce → extract → call → wrap → provenance."""
        if self.spec is None:
            raise NotImplementedError(f"{type(self).__name__} must define a 'spec' class attribute")

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=self.spec.input_dtype)

        # Build kwargs from resolved parameters + param_map
        params = self._resolve_params()
        fn_kwargs: Dict[str, Any] = {}
        for param_name, value in params.items():
            kwarg_name = self.spec.param_map.get(param_name, param_name)
            fn_kwargs[kwarg_name] = value

        # Call the transform
        result_data = self.spec.transform_fn(data, **fn_kwargs)

        # Wrap result preserving metadata
        result = build_dataset_like(result_data, input_ds, units=self.spec.output_units)

        # Record provenance
        add_processing_step(
            result,
            self.metadata.node_type,
            params,
            node_id=self.node_id,
            state_effects=self.spec.state_effects or None,
        )

        return result

    # -- export --------------------------------------------------------------

    def supports_python_export(self) -> bool:
        if self.spec is not None:
            if self.spec.export_lines_fn is not None:
                return True
            if self.spec.numpy_expr is not None:
                return True
        # Fall back to scp_method check (skip the generate_python override
        # check in Node base — our override delegates, it doesn't add logic).
        return self.scp_method is not None

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        # Priority 1: custom export callback
        if self.spec is not None and self.spec.export_lines_fn is not None:
            params = self._resolve_params()
            inp = next(iter(inputs.values())) if inputs else "input_data"
            return self.spec.export_lines_fn(
                params=params,
                inp=inp,
                node_id=self.node_id,
                indent=indent,
                use_scp=use_scp,
            )

        # Priority 2: auto-export from numpy_expr
        if self.spec is not None and self.spec.numpy_expr is not None:
            params = self._resolve_params()
            inp = next(iter(inputs.values())) if inputs else "input_data"
            # Substitute resolved param values into the expression
            fmt_params = {k: format_value(v) for k, v in params.items()}
            formatted = self.spec.numpy_expr.format(**fmt_params)
            lines: List[str] = [header_line(self.metadata.label, self.node_id, indent)]
            lines += extract_data_lines(inp, indent)
            lines.append(f"{indent}_result = {formatted}")
            lines += wrap_result_lines(self.node_id, "_result", inp, indent, use_scp)
            return lines

        # Priority 3: base class scp_method pattern
        return super().generate_python(inputs, indent, use_scp)


# ---------------------------------------------------------------------------
# EstimatorSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstimatorSpec:
    """Declarative specification for an sklearn-style fit/predict node.

    Attributes:
        estimator_class:
            An sklearn-compatible class that supports ``.fit(X, y)`` and
            ``.predict(X)``.
        param_map:
            Maps ``NodeParameter.name`` → estimator constructor kwarg.
        y_required:
            Whether the *y* input is mandatory.
        scale:
            If ``True``, wrap the estimator in a
            ``Pipeline([StandardScaler, estimator])``.
        scale_param:
            Name of the ``NodeParameter`` that controls scaling
            (only used when *scale* is ``True``).
        post_fit_fn:
            ``(model, X_data, y_array, X_ds, params, node_id) -> dict``
            returning additional output keys to merge into the result.
        metric_fns:
            ``{name: fn(y_true, y_pred) -> float}``.  If ``None``, the
            default R² and RMSE are computed.
        extra_imports:
            Additional import lines for the generated Python export script.
        export_lines_fn:
            Code-generation callback for ``generate_python()``.
        estimator_import:
            Full import line for auto-export, e.g.
            ``"from sklearn.linear_model import LinearRegression"``.
            When set, ``generate_python()`` auto-generates fit/predict code.
    """

    estimator_class: Type
    param_map: Dict[str, str] = field(default_factory=dict)
    y_required: bool = True
    scale: bool = False
    scale_param: str = "scale"
    post_fit_fn: Optional[Callable[..., Dict[str, Any]]] = None
    metric_fns: Optional[Dict[str, Callable]] = None
    extra_imports: List[str] = field(default_factory=list)
    export_lines_fn: Optional[Callable[..., List[str]]] = None
    estimator_import: Optional[str] = None


# ---------------------------------------------------------------------------
# EstimatorSpecNode
# ---------------------------------------------------------------------------


class EstimatorSpecNode(Node):
    """Base class for sklearn-style fit/predict nodes defined by an :class:`EstimatorSpec`.

    Subclasses declare only::

        metadata = NodeMetadata(...)
        spec = EstimatorSpec(...)

    ``execute()`` handles input binding, fitting, predicting, and metrics.
    """

    # Subclass MUST set this
    spec: EstimatorSpec = None  # type: ignore[assignment]

    def __init__(self, node_id: str, parameters: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(node_id, parameters)
        cls_imports: List[str] = list(getattr(type(self), "python_extra_imports", []))
        spec_imports = self.spec.extra_imports if self.spec else []
        seen: set[str] = set()
        merged: List[str] = []
        for imp in cls_imports + spec_imports:
            if imp not in seen:
                seen.add(imp)
                merged.append(imp)
        self.python_extra_imports = merged  # type: ignore[assignment]

    # -- execute -------------------------------------------------------------

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> Any:
        """Bind inputs → fit → predict → metrics → post-fit hook."""
        if self.spec is None:
            raise NotImplementedError(f"{type(self).__name__} must define a 'spec' class attribute")

        from sklearn.metrics import mean_squared_error, r2_score

        # Bind inputs
        X_ds = bind_X(
            X,
            missing_message=f"{self.metadata.label}: missing required input X",
            allow_array=True,
        )
        # Resolve target names BEFORE bind_y strips dataset metadata.
        # Enrich X_ds.target_context so post_fit hooks can read from it.
        _resolved_target_names = resolve_target_names(y, X_ds)
        if _resolved_target_names:
            tc = X_ds.target_context
            if tc is None or not tc.target_names:
                X_ds.target_context = TargetContext(
                    target_type=tc.target_type if tc else "continuous",
                    target_names=_resolved_target_names,
                )

        y_value = bind_y(
            y,
            X=X_ds,
            required=self.spec.y_required,
            infer_from_X=True,
            dataset_as_data=True,
            missing_message=(
                f"{self.metadata.label}: no target values found. Either:\n"
                "  1. Use a data source with embedded targets (e.g., Corn M5, sklearn)\n"
                "  2. Connect target values to the 'y' input port\n"
                "  3. Use 'Attach Target' node to add targets to your dataset"
            ),
        )

        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array: Optional[np.ndarray] = None
        if y_value is not None:
            y_array = to_numpy_1d(
                y_value,
                name="y",
                expected_length=X_data.shape[0],
                dtype=np.float64,
            )

        # Build estimator constructor kwargs from resolved parameters
        params = self._resolve_params()
        est_kwargs: Dict[str, Any] = {}
        for param_name, value in params.items():
            # Skip the scale toggle — it's handled separately
            if self.spec.scale and param_name == self.spec.scale_param:
                continue
            kwarg_name = self.spec.param_map.get(param_name, param_name)
            est_kwargs[kwarg_name] = value

        estimator = self.spec.estimator_class(**est_kwargs)

        # Optionally wrap in Pipeline with StandardScaler
        if self.spec.scale:
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler

            do_scale = params.get(self.spec.scale_param, True)
            scaler = StandardScaler(with_mean=bool(do_scale), with_std=bool(do_scale))
            model = Pipeline([("scaler", scaler), ("estimator", estimator)])
        else:
            model = estimator

        # Fit
        if y_array is not None:
            model.fit(X_data, y_array)
        else:
            model.fit(X_data)

        # Predict
        y_pred = model.predict(X_data)

        # Build result dict
        result: Dict[str, Any] = {
            "model": model,
            "y_pred": y_pred.tolist(),
        }

        if y_array is not None:
            result["predictions"] = y_pred.tolist()
            result["residuals"] = (y_array - y_pred).tolist()

            # Metrics
            if self.spec.metric_fns:
                for name, fn in self.spec.metric_fns.items():
                    result[name] = fn(y_array, y_pred)
            else:
                result["r2"] = float(r2_score(y_array, y_pred))
                result["rmse"] = float(np.sqrt(mean_squared_error(y_array, y_pred)))

        # Post-fit hook
        if self.spec.post_fit_fn is not None:
            extra = self.spec.post_fit_fn(
                model=model,
                X_data=X_data,
                y_array=y_array,
                X_ds=X_ds,
                params=params,
                node_id=self.node_id,
            )
            result.update(extra)

        return result

    # -- export --------------------------------------------------------------

    def supports_python_export(self) -> bool:
        if self.spec is not None:
            if self.spec.export_lines_fn is not None:
                return True
            if self.spec.estimator_import is not None:
                return True
        return self.scp_method is not None

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        # Priority 1: custom export callback
        if self.spec is not None and self.spec.export_lines_fn is not None:
            params = self._resolve_params()
            return self.spec.export_lines_fn(
                params=params,
                inputs=inputs,
                node_id=self.node_id,
                indent=indent,
                use_scp=use_scp,
            )

        # Priority 2: auto-export from estimator_import
        if self.spec is not None and self.spec.estimator_import is not None:
            return self._auto_export_estimator(inputs, indent)

        # Priority 3: base class scp_method pattern
        return super().generate_python(inputs, indent, use_scp)

    def _auto_export_estimator(
        self,
        inputs: Dict[str, str],
        indent: str,
    ) -> List[str]:
        """Generate fit/predict code from ``spec.estimator_import``."""
        params = self._resolve_params()
        cls_name = self.spec.estimator_class.__name__

        lines: List[str] = [header_line(self.metadata.label, self.node_id, indent)]
        lines.append(f"{indent}{self.spec.estimator_import}")

        # Extract X
        x_inp = inputs.get("X", inputs.get("default", "input_data"))
        lines.append(f"{indent}X = np.array({x_inp}.data, dtype=np.float64)")

        # Extract y (if required)
        if self.spec.y_required:
            y_inp = inputs.get("y", "y_data")
            lines.append(f"{indent}y = np.array({y_inp}, dtype=np.float64).ravel()")

        # Build estimator constructor kwargs (skip scale_param)
        est_kwargs: Dict[str, Any] = {}
        for pname, val in params.items():
            if self.spec.scale and pname == self.spec.scale_param:
                continue
            kwarg = self.spec.param_map.get(pname, pname)
            est_kwargs[kwarg] = val
        kwargs_str = format_kwargs(est_kwargs) if est_kwargs else ""

        # Optionally wrap in Pipeline with StandardScaler
        if self.spec.scale:
            do_scale = params.get(self.spec.scale_param, True)
            lines.append(f"{indent}from sklearn.pipeline import Pipeline")
            lines.append(f"{indent}from sklearn.preprocessing import StandardScaler")
            lines.append(
                f"{indent}_scaler = StandardScaler("
                f"with_mean={format_value(do_scale)}, with_std={format_value(do_scale)})"
            )
            lines.append(f"{indent}_est = {cls_name}({kwargs_str})")
            lines.append(f"{indent}model = Pipeline(" f"[('scaler', _scaler), ('estimator', _est)])")
        else:
            lines.append(f"{indent}model = {cls_name}({kwargs_str})")

        # Fit + predict
        if self.spec.y_required:
            lines.append(f"{indent}model.fit(X, y)")
        else:
            lines.append(f"{indent}model.fit(X)")
        lines.append(f"{indent}y_pred = model.predict(X)")
        lines.append(f"{indent}results['{self.node_id}'] = " f"{{'model': model, 'y_pred': y_pred.tolist()}}")

        return lines
