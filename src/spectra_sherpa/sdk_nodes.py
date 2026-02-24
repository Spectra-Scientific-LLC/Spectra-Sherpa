"""Public node-authoring facade for OSS contributors.

This module provides a low-friction API for common chemometric transform nodes
without introducing a second execution engine. Nodes still register into the
existing DAG registry and execute through the same runtime.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any, ClassVar, get_args, get_origin

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.export_helpers import (
    extract_data_lines,
    format_value,
    header_line,
    wrap_result_lines,
)
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata

ChemometricsParam = NodeParameter

_SPECTRAL_DATASET_TYPE = "spectrasherpa://types/SpectralDataset/1.0"
_DIAGNOSTIC_KEYS = ["output_shape", "output_min", "output_max", "output_mean", "output_std"]


def _labelize(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _safe_stat(arr: np.ndarray, reducer: Any) -> float | None:
    if arr.size == 0:
        return None
    try:
        return float(reducer(arr))
    except (TypeError, ValueError, FloatingPointError):
        return None


def _unwrap_primitive_annotation(annotation: Any, *, param_name: str) -> type:
    """Return a primitive annotation type or raise TypeError."""
    if isinstance(annotation, str):
        anno_map = {"int": int, "float": float, "bool": bool, "str": str}
        if annotation in anno_map:
            return anno_map[annotation]
        raise TypeError(
            f"Unsupported annotation for parameter '{param_name}': {annotation!r}. "
            "Use int/float/bool/str or define explicit NodeParameter entries."
        )

    origin = get_origin(annotation)
    if origin is None:
        resolved = annotation
    elif origin is list or origin is dict or origin is tuple:
        raise TypeError(
            f"Unsupported annotation for parameter '{param_name}': {annotation!r}. "
            "Use int/float/bool/str or define explicit NodeParameter entries."
        )
    else:
        args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
        if len(args) != 1:
            raise TypeError(
                f"Unsupported annotation for parameter '{param_name}': {annotation!r}. "
                "Use int/float/bool/str or define explicit NodeParameter entries."
            )
        resolved = args[0]

    if resolved in (int, float, bool, str):
        return resolved

    raise TypeError(
        f"Unsupported annotation for parameter '{param_name}': {annotation!r}. "
        "Use int/float/bool/str or define explicit NodeParameter entries."
    )


def _infer_parameter_defs(cls: type["ChemometricsNode"]) -> list[NodeParameter]:
    sig = inspect.signature(cls.process)
    params: list[NodeParameter] = []

    for param in sig.parameters.values():
        if param.name in {"self", "dataset"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(
                f"process() parameter '{param.name}' on {cls.__name__} uses *args/**kwargs. "
                "Use explicit parameters=... for variable signatures."
            )
        if param.annotation is inspect._empty:
            raise TypeError(
                f"Missing type annotation for parameter '{param.name}' on {cls.__name__}. "
                "Use int/float/bool/str hints or define explicit parameters=."
            )

        resolved_ann = _unwrap_primitive_annotation(param.annotation, param_name=param.name)
        if resolved_ann is bool:
            param_type = "boolean"
        elif resolved_ann in (int, float):
            param_type = "number"
        else:
            param_type = "text"

        required = param.default is inspect._empty
        default = None if required else param.default

        params.append(
            NodeParameter(
                name=param.name,
                label=_labelize(param.name),
                param_type=param_type,
                default=default,
                required=required,
                description=None,
            )
        )

    return params


def param_number(
    name: str,
    *,
    default: int | float | None = None,
    label: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    step: float | None = None,
    description: str | None = None,
    required: bool | None = None,
) -> ChemometricsParam:
    return ChemometricsParam(
        name=name,
        label=label or _labelize(name),
        param_type="number",
        default=default,
        min_value=min_value,
        max_value=max_value,
        step=step,
        description=description,
        required=(default is None if required is None else required),
    )


def param_bool(
    name: str,
    *,
    default: bool = False,
    label: str | None = None,
    description: str | None = None,
    required: bool = False,
) -> ChemometricsParam:
    return ChemometricsParam(
        name=name,
        label=label or _labelize(name),
        param_type="boolean",
        default=default,
        description=description,
        required=required,
    )


def param_text(
    name: str,
    *,
    default: str | None = None,
    label: str | None = None,
    description: str | None = None,
    required: bool | None = None,
) -> ChemometricsParam:
    return ChemometricsParam(
        name=name,
        label=label or _labelize(name),
        param_type="text",
        default=default,
        description=description,
        required=(default is None if required is None else required),
    )


def param_select(
    name: str,
    *,
    options: list[str] | list[dict[str, Any]],
    default: Any,
    label: str | None = None,
    description: str | None = None,
    required: bool = True,
) -> ChemometricsParam:
    normalized_options: list[dict[str, Any]] = []
    for option in options:
        if isinstance(option, dict):
            normalized_options.append(option)
        else:
            normalized_options.append({"label": str(option), "value": option})

    return ChemometricsParam(
        name=name,
        label=label or _labelize(name),
        param_type="select",
        default=default,
        options=normalized_options,
        description=description,
        required=required,
    )


class ChemometricsNode(Node):
    """Simplified Dataset-in / Dataset-out node base for OSS authors."""

    metadata: ClassVar[NodeMetadata | None] = None

    node_type: ClassVar[str | None] = None
    category: ClassVar[str | None] = None
    label: ClassVar[str | None] = None
    description: ClassVar[str] = ""

    # Optional explicit parameter definitions. If omitted, inferred from process().
    parameters: ClassVar[list[NodeParameter] | None] = None

    # Optional auto-export expression. If absent, export is unsupported by default.
    numpy_expr: ClassVar[str | None] = None

    def process(self, dataset: SherpaDataset, **kwargs: Any) -> Any:
        raise NotImplementedError("ChemometricsNode subclasses must implement process(dataset, **kwargs)")

    @classmethod
    def _require_metadata_attrs(cls) -> None:
        missing = [
            attr
            for attr in ("node_type", "category", "label")
            if not isinstance(getattr(cls, attr, None), str) or not getattr(cls, attr, "").strip()
        ]
        if missing:
            raise ValueError(f"{cls.__name__} missing required class attribute(s): {', '.join(missing)}")

    @classmethod
    def _parameter_defs(cls) -> list[NodeParameter]:
        explicit = getattr(cls, "parameters", None)
        if explicit is not None:
            return [copy.deepcopy(param) for param in explicit]
        return _infer_parameter_defs(cls)

    def _resolve_params(self) -> dict[str, Any]:
        params = {}
        for p in self.get_metadata().parameters:
            params[p.name] = self.parameters.get(p.name, p.default)
        return params

    def validate_parameters(self) -> None:
        # Ensure lazily-built metadata exists before base-class validation.
        self.get_metadata()
        super().validate_parameters()

    @classmethod
    def get_metadata(cls) -> NodeMetadata:
        if cls.metadata is not None:
            return cls.metadata

        cls._require_metadata_attrs()
        cls.metadata = NodeMetadata(
            node_type=cls.node_type or "",
            category=cls.category or "",
            label=cls.label or "",
            description=(cls.description or cls.label or ""),
            parameters=cls._parameter_defs(),
            input_types=["NDDataset"],
            output_type="NDDataset",
            input_ports=[
                PortMetadata(
                    name="default",
                    type_ref=_SPECTRAL_DATASET_TYPE,
                    required=True,
                    label="Input Data",
                )
            ],
            output_ports=[
                PortMetadata(
                    name="default",
                    type_ref=_SPECTRAL_DATASET_TYPE,
                    required=True,
                    label="Output Data",
                )
            ],
            diagnostics=list(_DIAGNOSTIC_KEYS),
        )
        return cls.metadata

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        if input_data is None:
            if "default" in kwargs:
                input_data = kwargs["default"]
            elif "input_0" in kwargs:
                input_data = kwargs["input_0"]

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        params = self._resolve_params()

        result = self.process(input_ds, **params)
        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, SherpaDataset):
            result_ds = result
        else:
            result_ds = build_dataset_like(result, input_ds)

        add_processing_step(result_ds, self.get_metadata().node_type, params, node_id=self.node_id)

        out = np.asarray(result_ds.data, dtype=np.float64)
        diagnostics = {
            "output_shape": list(out.shape),
            "output_min": _safe_stat(out, np.nanmin),
            "output_max": _safe_stat(out, np.nanmax),
            "output_mean": _safe_stat(out, np.nanmean),
            "output_std": _safe_stat(out, np.nanstd),
        }
        return NodeResult(outputs={"default": result_ds}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return bool(self.numpy_expr)

    def generate_python(self, inputs: dict[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        if not self.numpy_expr:
            return [
                f"{indent}# TODO: {self.get_metadata().node_type} does not support Python export yet",
                f"{indent}raise NotImplementedError('{self.get_metadata().node_type} export not implemented')",
            ]

        params = self._resolve_params()
        formatted_params = {k: format_value(v) for k, v in params.items()}
        try:
            expression = self.numpy_expr.format(**formatted_params)
        except KeyError as exc:
            raise ValueError(
                f"numpy_expr for {self.get_metadata().node_type} references unknown parameter {exc!s}"
            ) from exc

        inp = next(iter(inputs.values())) if inputs else "input_data"
        lines: list[str] = [header_line(self.get_metadata().label, self.node_id, indent)]
        lines += extract_data_lines(inp, indent)
        lines.append(f"{indent}_result = {expression}")
        lines += wrap_result_lines(self.node_id, "_result", inp, indent, use_scp)
        return lines


__all__ = [
    "ChemometricsNode",
    "ChemometricsParam",
    "param_number",
    "param_bool",
    "param_text",
    "param_select",
]
