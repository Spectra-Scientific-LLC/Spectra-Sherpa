from __future__ import annotations

from types import SimpleNamespace


def test_effective_params_snapshot_materializes_plsda_defaults():
    from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

    snapshot = build_effective_params_snapshot(
        [
            SimpleNamespace(
                node_id="model_1",
                node_type="classification.plsda",
                parameters={"n_components": 5, "template_binding": "wine-demo"},
            )
        ]
    )

    assert snapshot["model_1"]["n_components"] == 5
    assert snapshot["model_1"]["cv_folds"] == 5
    assert snapshot["model_1"]["scale"] is False
    assert snapshot["model_1"]["probability_method"] == "softmax"
    assert snapshot["model_1"]["template_binding"] == "wine-demo"


def test_effective_params_snapshot_falls_back_for_legacy_nodes():
    from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

    snapshot = build_effective_params_snapshot(
        [
            SimpleNamespace(
                node_id="legacy_1",
                node_type="data.legacy_source",
                parameters={"source": "old-template"},
            )
        ]
    )

    assert snapshot == {"legacy_1": {"source": "old-template"}}
