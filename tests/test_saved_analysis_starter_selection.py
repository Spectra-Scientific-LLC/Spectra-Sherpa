"""New starters re-admit saved intent; existing workflow bindings stay frozen."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.app.schemas.experiments import ExperimentAnalysisSelection


def selection(**updates):
    return ExperimentAnalysisSelection(
        schema_version="spectra-sherpa-analysis-selection/1",
        updated_at=datetime.now(timezone.utc),
        **{"selected_target": "CO2", "target_type": "continuous", "source_digest": "a" * 64, **updates},
    )


def dataset():
    value = SherpaDataset(
        X=np.arange(12, dtype=float).reshape(4, 3),
        target=np.arange(4, dtype=float),
        domain=DomainContext(technique="FTIR"),
        feature_axis=SpectralAxis(values=[1000, 1100, 1200], units="cm^-1"),
        extra={"source_collection": {"scientific_collection_sha256": "a" * 64}},
    )
    value.target_context = value.target_context.model_copy(
        update={"target_names": ["CO2"], "target_name": "CO2", "target_units": "ppm", "target_type": "continuous"}
    )
    return value


def binding():
    return routes.DataBindingSpec(source="experiment", experiment_id=1, file_ids=[2], stage="raw")


def test_saved_target_uses_source_units_and_rejects_stale_intent():
    original = binding()
    resolved = routes._binding_with_saved_selection(original, dataset(), selection())
    assert resolved.target_authority.units == "ppm"
    assert resolved.selected_target == "CO2"
    assert original.target_authority is None
    with pytest.raises(ValueError, match="different source revision"):
        routes._binding_with_saved_selection(original, dataset(), selection(source_digest="b" * 64))
    cleared = routes._binding_with_saved_selection(
        resolved, dataset(), selection(selected_target=None, target_type=None)
    )
    assert cleared.target_authority is None


def test_response_table_title_is_not_advertised_as_an_extra_target():
    from spectra_sherpa.app.lib.dataset_compatibility import analysis_profile_from_dataset

    value = dataset()
    value.target_context = value.target_context.model_copy(update={"target_name": "synthetic concentration"})
    assert analysis_profile_from_dataset(value)["target_fields"] == ["CO2"]
    value.target_context = value.target_context.model_copy(update={"target_names": []})
    assert analysis_profile_from_dataset(value)["target_fields"] == ["synthetic concentration"]


@pytest.mark.asyncio
async def test_collection_preview_opt_in_reads_saved_intent_after_access_check(monkeypatch):
    order = []

    async def access(*args):
        order.append("access")

    async def get(*args):
        order.append("metadata")
        return SimpleNamespace(metadata_path="safe-metadata")

    monkeypatch.setattr(routes, "require_experiment_access", access)
    monkeypatch.setattr(routes, "resolve_data_path", lambda path: path)
    monkeypatch.setattr(
        routes, "read_metadata", lambda path: {"analysis_selection": selection().model_dump(mode="json")}
    )
    monkeypatch.setattr(
        routes,
        "load_project_dataset",
        AsyncMock(
            return_value=SimpleNamespace(
                dataset=dataset(),
                stage="raw",
                file_ids=[2],
                source_manifest_sha256="b" * 64,
                collection_definition_sha256="c" * 64,
                scientific_collection_sha256="a" * 64,
            )
        ),
    )
    session = SimpleNamespace(get=get)
    resolved, profile = await routes._validate_binding(session, 7, binding(), 9, use_saved_analysis_selection=True)
    assert order == ["access", "metadata"]
    assert resolved.selected_target == "CO2"
    assert resolved.target_authority.units == "ppm"
    assert profile["target_type"] == "continuous"
    # Ordinary existing bindings never consult mutable Data-page intent.
    order.clear()
    unchanged, _ = await routes._validate_binding(session, 7, binding(), 9)
    assert order == ["access"]
    assert unchanged.target_authority is None


@pytest.mark.asyncio
async def test_denied_dataset_never_reads_saved_metadata(monkeypatch):
    denied = AsyncMock(side_effect=PermissionError("denied"))
    monkeypatch.setattr(routes, "require_experiment_access", denied)
    session = SimpleNamespace(get=AsyncMock(side_effect=AssertionError("must not read metadata")))
    with pytest.raises(PermissionError):
        await routes._validate_binding(session, 7, binding(), 9, use_saved_analysis_selection=True)
    session.get.assert_not_awaited()


def test_binding_reads_the_load_node_empty_view_digest_as_absent():
    """Load nodes persist "" for "no saved definition"; clients may echo it back."""
    from pydantic import ValidationError

    absent = routes.DataBindingSpec(
        source="experiment", experiment_id=1, file_ids=[2], stage="raw", dataset_view_sha256=""
    )
    assert absent.dataset_view_sha256 is None
    # Still paired: an id with an empty digest is refused, as is a malformed digest.
    for overrides in ({"dataset_view_id": 3, "dataset_view_sha256": ""}, {"dataset_view_sha256": "abc"}):
        with pytest.raises(ValidationError):
            routes.DataBindingSpec(source="experiment", experiment_id=1, file_ids=[2], stage="raw", **overrides)
