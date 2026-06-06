from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn
from spectra_sherpa.app.lib.data_roles import require_data_role
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset
from spectra_sherpa.app.schemas.template_schema import TemplateFile


def test_sklearn_adapter_emits_feature_table_role():
    from sklearn.datasets import load_iris

    dataset = from_sklearn(load_iris(), name="iris")

    assert dataset.data_role == "X_features"
    assert dataset.data_modality == "features"
    assert isinstance(dataset.feature_axis, FeatureAxis)
    assert dataset.extra["sherpa.data_role"] == "X_features"


def test_template_loader_surfaces_dual_modalities():
    templates = TemplateLoader().load_all()
    by_slug = {template["slug"]: template for template in templates}

    assert by_slug["pca"]["name"] == "PCA with Outlier Diagnostics"
    assert by_slug["pca"]["template_data"]["data_modalities"] == ["spectra", "features"]
    assert by_slug["classification_plsda"]["template_data"]["data_modalities"] == ["spectra", "features"]


def test_template_schema_rejects_malformed_modality_string():
    with pytest.raises(ValidationError):
        TemplateFile.model_validate(
            {
                "schema_version": 1,
                "name": "Bad",
                "slug": "bad",
                "description": "bad",
                "category": "exploratory",
                "data_modalities": "spectra+hsi",
                "template_data": {
                    "nodes": [],
                    "edges": [],
                    "data_roles": {},
                    "certified_datasets": [],
                },
            }
        )


def test_spectrum_only_role_guard_rejects_feature_tables():
    dataset = SherpaDataset(
        X=np.ones((3, 2)),
        feature_axis=FeatureAxis(labels=["a", "b"], title="Feature"),
        data_role="X_features",
    )

    with pytest.raises(ValueError, match="requires X_spectra input; received X_features"):
        require_data_role(dataset, ["X_spectra"], context="Peak detection")
