"""Turn your own Python function into a local workflow node.

Write a plain function, decorate it, and put the file in your My nodes folder
or ship it in a package with a ``spectra_sherpa.custom_nodes`` entry point::

    from typing import Annotated
    from spectra_sherpa.sdk.custom import Spectra, custom_node, param

    @custom_node(label="Moving median despike", category="preprocessing")
    def despike(spectra: Spectra, window: Annotated[int, param(min=3, max=51, odd=True)] = 5) -> Spectra:
        \"\"\"Replace each point with the median of an odd-width window.\"\"\"
        ...
        return spectra.with_values(filtered)

The decorator only records a description of the node; the function stays an
ordinary function you can call and test directly. Workbench builds the node
when it loads your source at startup (local mode, after you turn custom nodes
on in Settings). You own the science of your nodes.

By default a custom node is a stateless, deterministic transform that keeps
every sample, feature, axis and unit, and never sees reference values or
groups. These defaults are checked on every run.
"""

from __future__ import annotations

import inspect
import keyword
import re
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "CustomNodeError",
    "CustomNodeSpec",
    "Param",
    "Spectra",
    "custom_node",
    "param",
]

CATEGORIES = ("preprocessing", "exploratory", "selection", "output")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Not available in this release; refused with a clear message instead of ignored.
_UNSUPPORTED_OPT_INS = {
    "fits": "fitted custom nodes",
    "uses_target": "custom nodes that read reference values",
    "uses_groups": "custom nodes that read groups",
    "changes_rows": "custom nodes that add, remove or reorder samples",
    "changes_axis": "custom nodes that replace the feature axis",
}
_MAX_TIMEOUT_SECONDS = 600
_MAX_MEMORY_MB = 8192


class CustomNodeError(ValueError):
    """A custom node definition, parameter or result breaks its declared contract."""


@dataclass(frozen=True)
class Param:
    """Bounds and choices for one parameter; use through ``Annotated[..., param(...)]``."""

    min: float | None = None
    max: float | None = None
    odd: bool = False
    choices: tuple[Any, ...] | None = None
    label: str | None = None
    description: str | None = None


def param(
    *,
    min: float | None = None,  # noqa: A002 - mirrors the scientific wording authors use
    max: float | None = None,  # noqa: A002
    odd: bool = False,
    choices: Sequence[Any] | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Param:
    """Declare bounds (``min``/``max``), odd integers, or a closed set of ``choices``."""
    if min is not None and max is not None and min > max:
        raise CustomNodeError("param(min=...) must not exceed param(max=...)")
    return Param(
        min=min,
        max=max,
        odd=odd,
        choices=tuple(choices) if choices is not None else None,
        label=label,
        description=description,
    )


class Spectra:
    """The spectra a custom node receives and returns: values, feature axis and units only.

    A custom function never sees the dataset behind them: no reference values,
    groups, sample metadata or provenance. ``values`` is a copy of the
    samples x features array and ``axis`` a copy of the feature coordinates
    (for example wavenumbers) when the data has them. Return
    ``spectra.with_values(new_values)``. To keep only some features (cropping,
    derivative edges) declare ``changes_features=True`` and return
    ``spectra.select_features(keep).with_values(...)``. Workbench rebuilds the
    output from its own copy of the samples, axis and units.
    """

    __slots__ = ("_values", "_axis", "_axis_units", "_value_units", "_features", "_replaced", "_origin")

    def __init__(
        self,
        values: Any,
        *,
        axis: Any = None,
        axis_units: str | None = None,
        value_units: str | None = None,
        _features: Any = None,
        _replaced: bool = False,
        _origin: object | None = None,
    ) -> None:
        array = np.array(values, dtype=np.float64, copy=True)
        if array.ndim != 2:
            raise CustomNodeError("Spectra values must be a samples x features array")
        array.setflags(write=False)
        features = np.arange(array.shape[1]) if _features is None else np.array(_features, dtype=np.int64)
        features.setflags(write=False)
        coordinates = None
        if axis is not None:
            coordinates = np.array(axis, dtype=np.float64, copy=True)
            if coordinates.shape != (array.shape[1],):
                raise CustomNodeError("Spectra axis must have one coordinate per feature")
            coordinates.setflags(write=False)
        self._values = array
        self._axis = coordinates
        self._axis_units = str(axis_units) if axis_units else None
        self._value_units = str(value_units) if value_units else None
        self._features = features
        self._replaced = _replaced
        self._origin = _origin

    @classmethod
    def _from_dataset(cls, dataset: Any) -> "Spectra":
        """Engine-only: copy the values, axis and units out of a dataset."""
        feature_axis = getattr(dataset, "feature_axis", None)
        coordinates = getattr(feature_axis, "values", None)
        if coordinates is not None and np.shape(coordinates) != (np.shape(dataset.X)[1],):
            coordinates = None
        return cls(
            dataset.X,
            axis=coordinates,
            axis_units=getattr(feature_axis, "units", None),
            value_units=getattr(dataset, "units", None),
            _origin=object(),
        )

    @property
    def values(self) -> np.ndarray:
        return self._values.copy()

    @property
    def shape(self) -> tuple[int, int]:
        rows, columns = self._values.shape
        return int(rows), int(columns)

    @property
    def n_samples(self) -> int:
        return self.shape[0]

    @property
    def n_features(self) -> int:
        return self.shape[1]

    @property
    def axis(self) -> np.ndarray | None:
        return None if self._axis is None else self._axis.copy()

    @property
    def axis_units(self) -> str | None:
        return self._axis_units

    @property
    def value_units(self) -> str | None:
        return self._value_units

    def with_values(self, values: Any) -> "Spectra":
        """Return these spectra with new values of the same shape."""
        array = np.asarray(values, dtype=np.float64)
        if array.ndim != 2 or array.shape != self.shape:
            raise CustomNodeError(
                f"with_values() needs an array of shape {self.shape}; got {tuple(array.shape)}. "
                "To drop features, use select_features() first and declare changes_features=True."
            )
        return Spectra(
            array,
            axis=self._axis,
            axis_units=self._axis_units,
            value_units=self._value_units,
            _features=self._features,
            _replaced=True,
            _origin=self._origin,
        )

    def select_features(self, keep: Any) -> "Spectra":
        """Keep a subset of features: a boolean mask, integer positions or a slice."""
        if self._replaced:
            raise CustomNodeError("Call select_features() before with_values().")
        index = np.arange(self.n_features)[keep] if isinstance(keep, slice) else np.asarray(keep)
        if index.dtype == bool:
            if index.shape != (self.n_features,):
                raise CustomNodeError("select_features() mask must have one entry per feature")
            index = np.flatnonzero(index)
        if index.ndim != 1 or index.size == 0 or not np.issubdtype(index.dtype, np.integer):
            raise CustomNodeError("select_features() needs a non-empty mask, slice or list of feature positions")
        if np.any(np.diff(index) <= 0) or index[0] < 0 or index[-1] >= self.n_features:
            raise CustomNodeError("select_features() positions must be increasing and within range")
        return Spectra(
            self._values[:, index],
            axis=None if self._axis is None else self._axis[index],
            axis_units=self._axis_units,
            value_units=self._value_units,
            _features=self._features[index],
            _origin=self._origin,
        )


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: str  # "integer", "number", "boolean", "choice"
    default: Any
    bounds: Param = field(default_factory=Param)


@dataclass(frozen=True)
class CustomNodeSpec:
    """What ``@custom_node`` recorded about one function."""

    function: Callable[..., Any]
    name: str
    label: str
    category: str
    description: str
    input_kind: str  # "spectra" or "array"
    output_kind: str
    parameters: tuple[ParameterSpec, ...]
    changes_features: bool
    seed_parameter: str | None
    timeout_seconds: int
    memory_mb: int
    citations: tuple[str, ...]


def _unwrap(annotation: Any) -> tuple[Any, Param]:
    if typing.get_origin(annotation) is typing.Annotated:
        base, *extras = typing.get_args(annotation)
        bounds = next((item for item in extras if isinstance(item, Param)), Param())
        return base, bounds
    return annotation, Param()


def _data_kind(annotation: Any, where: str) -> str:
    if annotation is Spectra:
        return "spectra"
    if annotation is np.ndarray:
        return "array"
    raise CustomNodeError(f"The {where} must be annotated as Spectra or numpy.ndarray")


def _parameter_spec(name: str, annotation: Any, default: Any) -> ParameterSpec:
    if default is inspect.Parameter.empty:
        raise CustomNodeError(f"Parameter {name!r} needs a default value")
    base, bounds = _unwrap(annotation)
    if typing.get_origin(base) is typing.Literal:
        bounds = Param(choices=typing.get_args(base), label=bounds.label, description=bounds.description)
        base = type(bounds.choices[0])
    if bounds.choices is not None:
        if not bounds.choices or len(set(bounds.choices)) != len(bounds.choices):
            raise CustomNodeError(f"Parameter {name!r} needs distinct choices")
        if default not in bounds.choices:
            raise CustomNodeError(f"Default for {name!r} must be one of its choices")
        return ParameterSpec(name, "choice", default, bounds)
    if base is bool:
        if type(default) is not bool:
            raise CustomNodeError(f"Default for {name!r} must be True or False")
        return ParameterSpec(name, "boolean", default, bounds)
    if base is int:
        kind = "integer"
    elif base is float:
        kind = "number"
    else:
        raise CustomNodeError(f"Parameter {name!r} must be int, float, bool, a Literal, or have choices")
    if bounds.odd and kind != "integer":
        raise CustomNodeError(f"Parameter {name!r} can be odd only if it is an int")
    spec = ParameterSpec(name, kind, default, bounds)
    check_parameter(spec, default)
    return spec


def check_parameter(spec: ParameterSpec, value: Any) -> Any:
    """Return ``value`` if it is admissible, otherwise refuse; never repair it."""
    name, bounds = spec.name, spec.bounds
    if spec.kind == "choice":
        if value not in bounds.choices:
            raise CustomNodeError(f"{name} must be one of {list(bounds.choices)}")
        return value
    if spec.kind == "boolean":
        if type(value) is not bool:
            raise CustomNodeError(f"{name} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise CustomNodeError(f"{name} must be a finite number")
    if spec.kind == "integer":
        if float(value) != int(value):
            raise CustomNodeError(f"{name} must be a whole number")
        value = int(value)
        if bounds.odd and value % 2 == 0:
            raise CustomNodeError(f"{name} must be odd")
    else:
        value = float(value)
    if bounds.min is not None and value < bounds.min:
        raise CustomNodeError(f"{name} must be at least {bounds.min}")
    if bounds.max is not None and value > bounds.max:
        raise CustomNodeError(f"{name} must be at most {bounds.max}")
    return value


def custom_node(
    *,
    label: str,
    category: str = "preprocessing",
    changes_features: bool = False,
    random_seed: str | None = None,
    timeout_seconds: int = 60,
    memory_mb: int = 1024,
    citations: Sequence[str] = (),
    **unsupported: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Describe a function as a local workflow node and return it unchanged.

    ``label`` is the palette name. ``category`` is one of
    preprocessing, exploratory, selection or output. Declare
    ``changes_features=True`` if the node keeps only some features,
    ``random_seed="seed"`` to name an int seed parameter for a stochastic
    node, and ``timeout_seconds`` / ``memory_mb`` for heavier work.
    """
    for option, value in unsupported.items():
        reason = _UNSUPPORTED_OPT_INS.get(option)
        if reason is None:
            raise CustomNodeError(f"Unknown custom_node option {option!r}")
        if value is False:
            continue  # stating the default explicitly is fine
        raise CustomNodeError(f"{option}=True is not available in this release: {reason} are not supported yet.")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise CustomNodeError("label must be 1 to 80 characters")
    if category not in CATEGORIES:
        raise CustomNodeError(f"category must be one of {', '.join(CATEGORIES)}")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise CustomNodeError(f"timeout_seconds must be an int from 1 to {_MAX_TIMEOUT_SECONDS}")
    if not isinstance(memory_mb, int) or not 64 <= memory_mb <= _MAX_MEMORY_MB:
        raise CustomNodeError(f"memory_mb must be an int from 64 to {_MAX_MEMORY_MB}")

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.isfunction(function) or inspect.iscoroutinefunction(function):
            raise CustomNodeError("@custom_node decorates a plain (not async) function")
        name = function.__name__
        if not _NAME_RE.fullmatch(name) or keyword.iskeyword(name):
            raise CustomNodeError("Custom node function names use lowercase letters, digits and underscores")
        hints = typing.get_type_hints(function, include_extras=True)
        signature = inspect.signature(function)
        arguments = list(signature.parameters.values())
        if not arguments or arguments[0].kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise CustomNodeError("The first argument receives the spectra")
        if any(item.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) for item in arguments):
            raise CustomNodeError("Custom nodes cannot take *args or **kwargs")
        input_kind = _data_kind(hints.get(arguments[0].name), "first argument")
        output_kind = _data_kind(hints.get("return"), "return value")
        parameters = tuple(_parameter_spec(item.name, hints.get(item.name), item.default) for item in arguments[1:])
        if random_seed is not None:
            seed = next((item for item in parameters if item.name == random_seed), None)
            if seed is None or seed.kind != "integer":
                raise CustomNodeError("random_seed must name an int parameter of the function")
        description = inspect.cleandoc(function.__doc__ or "").strip() or label
        function.__spectra_custom_node__ = CustomNodeSpec(  # type: ignore[attr-defined]
            function=function,
            name=name,
            label=label.strip(),
            category=category,
            description=description[:2000],
            input_kind=input_kind,
            output_kind=output_kind,
            parameters=parameters,
            changes_features=bool(changes_features),
            seed_parameter=random_seed,
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            citations=tuple(str(item) for item in citations),
        )
        return function

    return decorate


def specs_in(module: Any) -> tuple[CustomNodeSpec, ...]:
    """The custom nodes defined (not merely imported) by one module, in name order."""
    found = []
    for value in vars(module).values():
        spec = getattr(value, "__spectra_custom_node__", None)
        if isinstance(spec, CustomNodeSpec) and spec.function.__module__ == module.__name__:
            found.append(spec)
    return tuple(sorted(found, key=lambda item: item.name))
