"""Execution response serialization preserves values and transport refusal."""

from datetime import datetime, timezone

import numpy as np
import pytest
from pydantic import BaseModel

from spectra_sherpa.app.services.serialization import serialize_result


def test_nested_plot_and_diagnostic_values_keep_exact_json_projection():
    values = [[0.0, -1.5, float("nan")], [2.25, 3.0, float("inf")]]
    source = {
        "plot": {"data": values, "labels": ["replicate", "replicate"]},
        "diagnostic": (np.int64(2), np.float64(1.25)),
        "axis": np.array([4000.0, 650.0]),
        "at": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "_private": {"value": 1},
    }
    result = serialize_result(source)
    assert set(result) == {"plot", "diagnostic", "axis", "at"}
    assert result["plot"]["labels"] == ["replicate", "replicate"]
    np.testing.assert_array_equal(result["plot"]["data"], values)
    assert result["diagnostic"] == [2, 1.25]
    assert result["axis"] == [4000.0, 650.0]
    assert result["at"] == "2026-11-01T00:00:00+00:00"
    assert serialize_result(source, retain_full=True)["_private"] == {"value": 1}


def test_new_pydantic_projection_must_pass_transport_validation():
    class Projection(BaseModel):
        def model_dump(self, **kwargs):
            foreign = type("Hidden", (), {"__module__": "spectrochempy.fake"})()
            return {"nested": [foreign]}

    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result({"output": Projection()})


@pytest.mark.parametrize("container", ["list", "dict", "models"])
def test_values_generated_by_container_subclass_are_revalidated(container):
    def foreign():
        return type("Hidden", (), {"__module__": "spectrochempy.generated"})()

    class GeneratedList(list):
        def __init__(self):
            self.reads = 0

        def __iter__(self):
            self.reads += 1
            return iter([1 if self.reads == 1 else foreign()])

    class GeneratedDict(dict):
        def __init__(self):
            self.reads = 0

        def items(self):
            self.reads += 1
            return [("value", 1 if self.reads == 1 else foreign())]

    value = GeneratedList() if container == "list" else GeneratedDict()
    payload = {"models": value} if container == "models" else value
    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result(payload)


def test_custom_materializer_cannot_introduce_foreign_values_in_a_sibling_branch():
    sibling = [1]

    class MutatingList(list):
        def __init__(self):
            self.reads = 0

        def __iter__(self):
            self.reads += 1
            if self.reads > 1:
                sibling.append(type("Hidden", (), {"__module__": "spectrochempy.generated"})())
            return iter([1])

    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result({"trigger": MutatingList(), "sibling": sibling})


def test_model_names_are_preserved_but_private_model_values_keep_original_filtering():
    source = {"models": {"_classA": {"_private": 1, "score": 2}, "models": {"_private": 3, "score": 4}}}
    assert serialize_result(source) == {"models": {"_classA": {"score": 2}, "models": {"score": 4}}}


def test_metaclass_equality_cannot_qualify_a_custom_value_for_plain_copying():
    class PretendsBuiltin(type):
        def __eq__(cls, other):
            return True

        __hash__ = type.__hash__

    class GeneratedList(list, metaclass=PretendsBuiltin):
        def __init__(self):
            self.reads = 0

        def __iter__(self):
            self.reads += 1
            value = 1 if self.reads == 1 else type("Hidden", (), {"__module__": "spectrochempy.generated"})()
            return iter([value])

    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result(GeneratedList())

    class UnknownWrapper(metaclass=PretendsBuiltin):
        def __iter__(self):
            raise AssertionError("Unknown wrappers must not be materialized as plain JSON")

    wrapper = UnknownWrapper()
    assert serialize_result(wrapper) is wrapper
