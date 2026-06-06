"""
Tests for ModelArtifact DB model and ModelStore file persistence.
"""

from __future__ import annotations

import io
import json
import os
import time

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Phase 1: ModelStore file persistence
# ---------------------------------------------------------------------------


class TestModelStore:
    """Verify ModelStore save/load roundtrip and integrity checking."""

    @pytest.fixture()
    def store(self, tmp_path):
        from spectra_sherpa.app.services.model_store import ModelStore

        return ModelStore(tmp_path)

    @pytest.fixture()
    def sample_manifest(self):
        return {
            "model_type": "pca",
            "format_version": "1.0",
            "n_features": 50,
            "n_components": 3,
            "feature_axis": {"units": "cm^-1", "range": [400, 4000]},
            "metrics": {"explained_variance": 0.95},
        }

    @pytest.fixture()
    def sample_arrays(self):
        rng = np.random.default_rng(42)
        return {
            "loadings": rng.standard_normal((3, 50)).astype(np.float64),
            "mean": rng.standard_normal(50).astype(np.float64),
            "explained_variance_ratio": np.array([0.6, 0.25, 0.1], dtype=np.float64),
        }

    def test_save_load_roundtrip(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-001"
        integrity_hash = store.save(uid, sample_manifest, sample_arrays)

        assert isinstance(integrity_hash, str)
        assert len(integrity_hash) == 64  # SHA-256 hex

        manifest, arrays = store.load(uid)

        assert manifest["model_type"] == "pca"
        assert manifest["n_features"] == 50
        assert manifest["integrity_hash"] == integrity_hash
        assert manifest["artifact_uid"] == uid

        # Arrays preserved exactly
        for name in sample_arrays:
            np.testing.assert_array_equal(arrays[name], sample_arrays[name])

    def test_manifest_is_valid_json(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-json"
        store.save(uid, sample_manifest, sample_arrays)

        manifest_path = store.models_dir / uid / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            parsed = json.load(f)

        assert parsed["model_type"] == "pca"
        assert "arrays" in parsed
        assert "loadings" in parsed["arrays"]
        assert parsed["arrays"]["loadings"]["shape"] == [3, 50]
        assert parsed["arrays"]["loadings"]["dtype"] == "float64"

    def test_manifest_contains_array_inventory(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-inventory"
        store.save(uid, sample_manifest, sample_arrays)
        manifest = store.load_manifest(uid)

        assert set(manifest["arrays"].keys()) == {"loadings", "mean", "explained_variance_ratio"}

        for name, info in manifest["arrays"].items():
            assert "shape" in info
            assert "dtype" in info
            assert info["shape"] == list(sample_arrays[name].shape)

    def test_load_manifest_only(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-manifest-only"
        store.save(uid, sample_manifest, sample_arrays)
        manifest = store.load_manifest(uid)

        assert manifest["model_type"] == "pca"
        assert "arrays" in manifest

    def test_load_arrays_only(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-arrays-only"
        store.save(uid, sample_manifest, sample_arrays)
        arrays = store.load_arrays(uid)

        assert set(arrays.keys()) == {"loadings", "mean", "explained_variance_ratio"}
        np.testing.assert_array_equal(arrays["loadings"], sample_arrays["loadings"])

    def test_integrity_hash_verification(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-integrity"
        store.save(uid, sample_manifest, sample_arrays)

        assert store.verify_integrity(uid) is True

    def test_integrity_hash_detects_tampering(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-tamper"
        store.save(uid, sample_manifest, sample_arrays)

        # Tamper with arrays.npz
        npz_path = store.models_dir / uid / "arrays.npz"
        with open(npz_path, "ab") as f:
            f.write(b"tampered")

        assert store.verify_integrity(uid) is False

    def test_delete_removes_directory(self, store, sample_manifest, sample_arrays):
        uid = "test-uid-delete"
        store.save(uid, sample_manifest, sample_arrays)

        artifact_dir = store.models_dir / uid
        assert artifact_dir.exists()

        store.delete(uid)
        assert not artifact_dir.exists()

    def test_list_artifacts(self, store, sample_manifest, sample_arrays):
        store.save("uid-a", dict(sample_manifest), dict(sample_arrays))
        store.save("uid-b", dict(sample_manifest), dict(sample_arrays))

        uids = store.list_artifacts()
        assert set(uids) == {"uid-a", "uid-b"}

    def test_load_nonexistent_raises(self, store):
        with pytest.raises(FileNotFoundError, match="not found"):
            store.load_manifest("nonexistent-uid")

        with pytest.raises(FileNotFoundError, match="not found"):
            store.load_arrays("nonexistent-uid")

    def test_save_with_numpy_scalar_in_manifest(self, store, sample_arrays):
        """Manifest with numpy scalars should JSON-serialize cleanly."""
        manifest = {
            "model_type": "pls",
            "n_features": np.int64(50),
            "r2": np.float64(0.95),
        }
        uid = "test-uid-numpy-scalars"
        store.save(uid, manifest, sample_arrays)

        loaded = store.load_manifest(uid)
        assert loaded["n_features"] == 50
        assert loaded["r2"] == 0.95

    def test_empty_arrays_dict(self, store):
        """Saving with no arrays should still work (e.g., EFA diagnostic model)."""
        uid = "test-uid-empty"
        store.save(uid, {"model_type": "efa"}, {})
        manifest, arrays = store.load(uid)
        assert manifest["model_type"] == "efa"
        assert len(arrays) == 0


# ---------------------------------------------------------------------------
# Phase 1: ModelArtifact DB model
# ---------------------------------------------------------------------------


class TestModelArtifactModel:
    """Verify ModelArtifact can be imported and has expected attributes."""

    def test_model_artifact_importable(self):
        from spectra_sherpa.app.models.model_artifact import ModelArtifact

        assert ModelArtifact.__tablename__ == "model_artifact"

    def test_model_artifact_in_package_init(self):
        from spectra_sherpa.app.models import ModelArtifact

        assert ModelArtifact.__tablename__ == "model_artifact"

    def test_model_artifact_has_expected_columns(self):
        from spectra_sherpa.app.models.model_artifact import ModelArtifact

        expected_columns = {
            "id",
            "artifact_uid",
            "user_id",
            "project_id",
            "workflow_id",
            "workflow_version_id",
            "source_run_id",
            "training_dataset_id",
            "node_id",
            "model_type",
            "name",
            "display_name",
            "description",
            "artifact_dir",
            "integrity_hash",
            "n_features",
            "n_components",
            "classes_json",
            "feature_axis_json",
            "metrics_json",
            "training_data_hash",
            "preprocessing_summary",
            "is_active",
            "is_deploy_ready",
            "tags",
            "created_at",
            "updated_at",
        }
        actual_columns = {c.name for c in ModelArtifact.__table__.columns}
        assert expected_columns == actual_columns

    def test_project_has_models_relationship(self):
        from spectra_sherpa.app.models.project import Project

        assert hasattr(Project, "models")


# ---------------------------------------------------------------------------
# Phase 2: Extract roundtrip serialization
# ---------------------------------------------------------------------------


class TestPCAExtractArtifact:
    """Verify PCAExtract to_artifact/from_artifact roundtrip and transform."""

    @pytest.fixture()
    def pca_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        rng = np.random.default_rng(42)
        n_samples, n_features, n_components = 20, 50, 3
        mean = rng.standard_normal(n_features).astype(np.float64)
        loadings = rng.standard_normal((n_components, n_features)).astype(np.float64)
        # Orthogonalize loadings for realism
        loadings, _ = np.linalg.qr(loadings.T)
        loadings = loadings.T[:n_components]
        scores = (rng.standard_normal((n_samples, n_features)) - mean) @ loadings.T

        return PCAExtract(
            scores=scores,
            loadings=loadings,
            explained_variance_ratio=np.array([0.6, 0.25, 0.1], dtype=np.float64),
            explained_variance=np.array([3.0, 1.25, 0.5], dtype=np.float64),
            n_components=n_components,
            mean=mean,
        )

    def test_roundtrip(self, pca_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        metadata, arrays = pca_extract.to_artifact()
        restored = PCAExtract.from_artifact(metadata, arrays)

        assert restored.n_components == pca_extract.n_components
        np.testing.assert_array_equal(restored.loadings, pca_extract.loadings)
        np.testing.assert_array_equal(restored.mean, pca_extract.mean)
        np.testing.assert_array_equal(restored.explained_variance_ratio, pca_extract.explained_variance_ratio)
        np.testing.assert_array_equal(restored.explained_variance, pca_extract.explained_variance)
        np.testing.assert_array_equal(restored.scores, pca_extract.scores)

    def test_roundtrip_without_mean(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract(
            scores=np.zeros((5, 2)),
            loadings=np.eye(2, 10),
            explained_variance_ratio=np.array([0.7, 0.3]),
            explained_variance=np.array([2.0, 1.0]),
            n_components=2,
            mean=None,
        )
        metadata, arrays = extract.to_artifact()
        restored = PCAExtract.from_artifact(metadata, arrays)
        assert restored.mean is None
        assert restored.n_components == 2

    def test_transform_with_mean(self, pca_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 50)).astype(np.float64)
        scores = pca_extract.transform(X_new)

        assert scores.shape == (5, 3)
        # Manual check
        expected = (X_new - pca_extract.mean) @ pca_extract.loadings.T
        np.testing.assert_allclose(scores, expected)

    def test_transform_without_mean(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        loadings = np.eye(2, 5, dtype=np.float64)
        extract = PCAExtract(
            scores=np.zeros((1, 2)),
            loadings=loadings,
            explained_variance_ratio=np.array([0.7, 0.3]),
            explained_variance=np.array([2.0, 1.0]),
            n_components=2,
        )
        X = np.ones((3, 5), dtype=np.float64)
        scores = extract.transform(X)
        expected = X @ loadings.T
        np.testing.assert_allclose(scores, expected)

    def test_transform_single_sample(self, pca_extract):
        X_single = np.random.default_rng(7).standard_normal(50).astype(np.float64)
        scores = pca_extract.transform(X_single)
        assert scores.shape == (1, 3)

    def test_transform_matches_sklearn(self):
        """PCAExtract.transform() must match sklearn PCA.transform()."""
        from sklearn.decomposition import PCA

        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        rng = np.random.default_rng(123)
        X_train = rng.standard_normal((30, 10)).astype(np.float64)
        X_test = rng.standard_normal((5, 10)).astype(np.float64)

        sk_pca = PCA(n_components=3).fit(X_train)

        extract = PCAExtract(
            scores=sk_pca.transform(X_train),
            loadings=sk_pca.components_,
            explained_variance_ratio=sk_pca.explained_variance_ratio_,
            explained_variance=sk_pca.explained_variance_,
            n_components=3,
            mean=sk_pca.mean_,
        )
        our_scores = extract.transform(X_test)
        sk_scores = sk_pca.transform(X_test)
        np.testing.assert_allclose(our_scores, sk_scores, atol=1e-12)

    def test_transform_replays_saved_scaling_state(self):
        """PCAExtract.transform() must replay raw-space standardization state before projection."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        loadings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
        extract = PCAExtract(
            scores=np.empty((0, 2), dtype=np.float64),
            loadings=loadings,
            explained_variance_ratio=np.array([0.6, 0.4], dtype=np.float64),
            explained_variance=np.array([1.0, 0.5], dtype=np.float64),
            n_components=2,
            mean=np.array([10.0, 20.0], dtype=np.float64),
            scale=np.array([2.0, 5.0], dtype=np.float64),
            scale_mode="standard",
        )

        metadata, arrays = extract.to_artifact()
        restored = PCAExtract.from_artifact(metadata, arrays)
        scores = restored.transform(np.array([[12.0, 30.0]], dtype=np.float64))
        np.testing.assert_allclose(scores, np.array([[1.0, 2.0]], dtype=np.float64))

    def test_transform_replays_saved_minmax_scaled_state(self):
        """SCP PCA scaled=True must replay centered min-max data before projection."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        loadings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
        extract = PCAExtract(
            scores=np.empty((0, 2), dtype=np.float64),
            loadings=loadings,
            explained_variance_ratio=np.array([0.6, 0.4], dtype=np.float64),
            explained_variance=np.array([1.0, 0.5], dtype=np.float64),
            n_components=2,
            offset=np.array([10.0, 20.0], dtype=np.float64),
            scale=np.array([2.0, 5.0], dtype=np.float64),
            center=np.array([0.25, 0.5], dtype=np.float64),
            scale_mode="minmax",
        )

        metadata, arrays = extract.to_artifact()
        assert metadata["scaled"] is True
        assert metadata["standardized"] is False
        assert metadata["scale_mode"] == "minmax"
        restored = PCAExtract.from_artifact(metadata, arrays)
        scores = restored.transform(np.array([[12.0, 30.0]], dtype=np.float64))
        np.testing.assert_allclose(scores, np.array([[0.75, 1.5]], dtype=np.float64))

    def test_from_scp_scaled_persists_minmax_state(self, monkeypatch):
        """Extractor must persist SCP scaled=True as min/range plus scaled-space center."""
        from spectra_sherpa.app.lib.adapters import scp_extractors
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        monkeypatch.setattr(scp_extractors, "require_scp", lambda _reason: None)

        class FakePCA:
            components = np.eye(2, 3, dtype=np.float64)
            explained_variance_ratio = np.array([0.7, 0.2], dtype=np.float64)
            explained_variance = np.array([2.0, 1.0], dtype=np.float64)

            def transform(self):
                return np.zeros((3, 2), dtype=np.float64)

        X_train = np.array(
            [
                [10.0, 20.0, 1.0],
                [12.0, 25.0, 1.0],
                [14.0, 30.0, 1.0],
            ],
            dtype=np.float64,
        )

        extract = PCAExtract.from_scp(FakePCA(), X_train, scaled=True)

        np.testing.assert_allclose(extract.offset, np.array([10.0, 20.0, 1.0], dtype=np.float64))
        np.testing.assert_allclose(extract.scale, np.array([4.0, 10.0, 1.0], dtype=np.float64))
        np.testing.assert_allclose(extract.center, np.array([0.5, 0.5, 0.0], dtype=np.float64))
        assert extract.mean is None
        assert extract.scale_mode == "minmax"
        scores = extract.transform(np.array([[12.0, 25.0, 1.0]], dtype=np.float64))
        np.testing.assert_allclose(scores, np.array([[0.0, 0.0]], dtype=np.float64))

    def test_scaled_artifact_without_center_fails_loudly(self):
        """Legacy scaled PCA artifacts without post-scale center cannot be replayed safely."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract.from_artifact(
            {"model_type": "pca", "n_components": 2, "scaled": True},
            {
                "loadings": np.eye(2, 2, dtype=np.float64),
                "scale": np.array([2.0, 5.0], dtype=np.float64),
                "offset": np.array([10.0, 20.0], dtype=np.float64),
            },
        )
        with pytest.raises(ValueError, match="post-scale center"):
            extract.transform(np.array([[12.0, 30.0]], dtype=np.float64))

    def test_modelstore_integration(self, tmp_path, pca_extract):
        """Full pipeline: to_artifact → ModelStore.save → load → from_artifact."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract
        from spectra_sherpa.app.services.model_store import ModelStore

        store = ModelStore(tmp_path)
        metadata, arrays = pca_extract.to_artifact()
        metadata["n_features"] = 50
        store.save("pca-test", metadata, arrays)

        loaded_manifest, loaded_arrays = store.load("pca-test")
        restored = PCAExtract.from_artifact(loaded_manifest, loaded_arrays)

        np.testing.assert_array_equal(restored.loadings, pca_extract.loadings)
        np.testing.assert_array_equal(restored.mean, pca_extract.mean)

        # Transform should give identical results
        rng = np.random.default_rng(77)
        X = rng.standard_normal((3, 50))
        np.testing.assert_allclose(restored.transform(X), pca_extract.transform(X), atol=1e-12)


class TestPLSExtractArtifact:
    """Verify PLSExtract to_artifact/from_artifact roundtrip and predict."""

    @pytest.fixture()
    def pls_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        rng = np.random.default_rng(42)
        n_features, n_targets, n_components = 50, 1, 3
        return PLSExtract(
            x_scores=rng.standard_normal((20, n_components)),
            y_scores=rng.standard_normal((20, n_components)),
            x_loadings=rng.standard_normal((n_features, n_components)),
            y_loadings=rng.standard_normal((n_targets, n_components)),
            coef=rng.standard_normal((n_features, n_targets)),
            n_components=n_components,
            x_mean=rng.standard_normal(n_features),
            y_mean=rng.standard_normal(n_targets),
            x_scale=np.abs(rng.standard_normal(n_features)) + 0.1,
            t2_limit=4.5,
            q_limit=2.5,
            t2_q_method="pomerantsev_dd_moments",
        )

    def test_roundtrip(self, pls_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        metadata, arrays = pls_extract.to_artifact()
        restored = PLSExtract.from_artifact(metadata, arrays)

        assert restored.n_components == pls_extract.n_components
        assert restored.t2_limit == pls_extract.t2_limit
        assert restored.q_limit == pls_extract.q_limit
        assert restored.t2_q_method == pls_extract.t2_q_method
        np.testing.assert_array_equal(restored.coef, pls_extract.coef)
        np.testing.assert_array_equal(restored.x_mean, pls_extract.x_mean)
        np.testing.assert_array_equal(restored.y_mean, pls_extract.y_mean)
        np.testing.assert_array_equal(restored.x_scale, pls_extract.x_scale)
        np.testing.assert_array_equal(restored.x_loadings, pls_extract.x_loadings)
        np.testing.assert_array_equal(restored.y_loadings, pls_extract.y_loadings)

    def test_predict(self, pls_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 50))
        y_pred = pls_extract.predict(X_new)

        assert y_pred.shape == (5, 1)
        expected = (X_new - pls_extract.x_mean) @ pls_extract.coef + pls_extract.y_mean
        np.testing.assert_allclose(y_pred, expected)

    def test_applicability_diagnostics_flags_out_of_domain_samples(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        extract = PLSExtract(
            x_scores=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]),
            y_scores=None,
            x_loadings=np.eye(2),
            y_loadings=None,
            coef=np.ones((2, 1)),
            n_components=2,
            x_mean=np.zeros(2),
            y_mean=np.zeros(1),
            x_scale=np.ones(2),
            t2_limit=2.0,
            q_limit=0.1,
            t2_q_method="pomerantsev_dd_moments",
        )

        diagnostics = extract.applicability_diagnostics(np.array([[0.1, 0.1], [4.0, 0.0]], dtype=np.float64))

        assert diagnostics is not None
        assert diagnostics["type"] == "pls_applicability"
        assert diagnostics["out_of_domain"] == [False, True]
        assert diagnostics["n_out_of_domain"] == 1
        assert diagnostics["t2_limit"] == 2.0

    def test_predict_no_coef_raises(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        extract = PLSExtract(
            x_scores=None,
            y_scores=None,
            x_loadings=None,
            y_loadings=None,
            coef=None,
            n_components=2,
        )
        with pytest.raises(ValueError, match="coef is None"):
            extract.predict(np.ones((3, 10)))

    def test_predict_matches_sklearn(self):
        """PLSExtract.predict() must match sklearn PLSRegression.predict()."""
        from sklearn.cross_decomposition import PLSRegression

        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        rng = np.random.default_rng(456)
        X_train = rng.standard_normal((40, 20)).astype(np.float64)
        y_train = rng.standard_normal((40, 1)).astype(np.float64)
        X_test = rng.standard_normal((5, 20)).astype(np.float64)

        sk_pls = PLSRegression(n_components=3, scale=False).fit(X_train, y_train)

        # sklearn stores coef_ as (n_targets, n_features) → transpose
        coef = sk_pls.coef_.T if sk_pls.coef_.shape[0] != X_train.shape[1] else sk_pls.coef_
        # With scale=False: intercept = y_mean - x_mean @ coef
        x_mean = X_train.mean(axis=0)
        y_mean = y_train.mean(axis=0)

        extract = PLSExtract(
            x_scores=None,
            y_scores=None,
            x_loadings=None,
            y_loadings=None,
            coef=coef,
            n_components=3,
            x_mean=x_mean,
            y_mean=y_mean,
        )
        our_pred = extract.predict(X_test)
        sk_pred = sk_pls.predict(X_test)
        np.testing.assert_allclose(our_pred, sk_pred, atol=1e-10)

    def test_from_scp_predict_matches_scaled_scp_model(self):
        from spectra_sherpa.app.lib.scp_compat import HAS_SCP, scp

        if not HAS_SCP:
            pytest.skip("SpectroChemPy is optional")

        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        rng = np.random.default_rng(1234)
        X_train = rng.standard_normal((40, 12)) * np.linspace(1.0, 4.0, 12)
        y_train = rng.standard_normal((40, 1))
        X_test = rng.standard_normal((6, 12)) * np.linspace(1.0, 4.0, 12)

        X_ndd = scp.NDDataset(X_train)
        y_ndd = scp.NDDataset(y_train)
        pls = scp.PLSRegression(n_components=3, scale=True)
        pls.fit(X_ndd, y_ndd)

        extract = PLSExtract.from_scp(pls, X_ndd, Y_ndd=y_ndd)
        our_pred = extract.predict(X_test)
        scp_pred = np.asarray(pls.predict(scp.NDDataset(X_test)).data).reshape(our_pred.shape)

        assert extract.x_scale is not None
        np.testing.assert_allclose(our_pred, scp_pred, atol=1e-10)


class TestMCRExtractArtifact:
    """Verify MCRExtract to_artifact/from_artifact roundtrip and transform."""

    @pytest.fixture()
    def mcr_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import MCRExtract

        rng = np.random.default_rng(42)
        return MCRExtract(
            C=rng.standard_normal((20, 3)).astype(np.float64),
            St=rng.standard_normal((3, 50)).astype(np.float64),
            n_components=3,
        )

    def test_roundtrip(self, mcr_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import MCRExtract

        metadata, arrays = mcr_extract.to_artifact()
        restored = MCRExtract.from_artifact(metadata, arrays)

        assert restored.n_components == 3
        np.testing.assert_array_equal(restored.C, mcr_extract.C)
        np.testing.assert_array_equal(restored.St, mcr_extract.St)

    def test_transform(self, mcr_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 50))
        C_new = mcr_extract.transform(X_new)

        assert C_new.shape == (5, 3)
        expected = X_new @ np.linalg.pinv(mcr_extract.St)
        np.testing.assert_allclose(C_new, expected, atol=1e-10)


class TestEFAExtractArtifact:
    """Verify EFAExtract to_artifact/from_artifact roundtrip."""

    def test_roundtrip(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import EFAExtract

        rng = np.random.default_rng(42)
        extract = EFAExtract(
            forward_ev=rng.standard_normal((20, 3)).astype(np.float64),
            backward_ev=rng.standard_normal((20, 3)).astype(np.float64),
            n_components=3,
        )
        metadata, arrays = extract.to_artifact()
        restored = EFAExtract.from_artifact(metadata, arrays)

        assert restored.n_components == 3
        np.testing.assert_array_equal(restored.forward_ev, extract.forward_ev)
        np.testing.assert_array_equal(restored.backward_ev, extract.backward_ev)

    def test_roundtrip_none_arrays(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import EFAExtract

        extract = EFAExtract(forward_ev=None, backward_ev=None, n_components=2)
        metadata, arrays = extract.to_artifact()
        restored = EFAExtract.from_artifact(metadata, arrays)

        assert restored.forward_ev is None
        assert restored.backward_ev is None
        assert restored.n_components == 2


class TestSIMPLISMAExtractArtifact:
    """Verify SIMPLISMAExtract roundtrip and transform."""

    @pytest.fixture()
    def simplisma_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMPLISMAExtract

        rng = np.random.default_rng(42)
        return SIMPLISMAExtract(
            C=rng.standard_normal((20, 3)).astype(np.float64),
            St=rng.standard_normal((3, 50)).astype(np.float64),
            purities=np.array([0.9, 0.85, 0.7], dtype=np.float64),
            n_components=3,
        )

    def test_roundtrip(self, simplisma_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMPLISMAExtract

        metadata, arrays = simplisma_extract.to_artifact()
        restored = SIMPLISMAExtract.from_artifact(metadata, arrays)

        assert restored.n_components == 3
        np.testing.assert_array_equal(restored.C, simplisma_extract.C)
        np.testing.assert_array_equal(restored.St, simplisma_extract.St)
        np.testing.assert_array_equal(restored.purities, simplisma_extract.purities)

    def test_transform(self, simplisma_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 50))
        C_new = simplisma_extract.transform(X_new)

        assert C_new.shape == (5, 3)
        expected = X_new @ np.linalg.pinv(simplisma_extract.St)
        np.testing.assert_allclose(C_new, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Phase 2: New Extract classes — PLS-DA, KNN, SIMCA
# ---------------------------------------------------------------------------


class TestPLSDAExtractArtifact:
    """Verify PLSDAExtract roundtrip and predict."""

    @pytest.fixture()
    def plsda_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSDAExtract

        rng = np.random.default_rng(42)
        n_features, n_classes = 20, 3
        return PLSDAExtract(
            coef=rng.standard_normal((n_features, n_classes)).astype(np.float64),
            x_mean=rng.standard_normal(n_features).astype(np.float64),
            y_mean=np.array([1 / 3, 1 / 3, 1 / 3], dtype=np.float64),
            classes=["A", "B", "C"],
            x_loadings=rng.standard_normal((n_features, 3)).astype(np.float64),
            y_loadings=rng.standard_normal((n_classes, 3)).astype(np.float64),
            n_components=3,
        )

    def test_roundtrip(self, plsda_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSDAExtract

        metadata, arrays = plsda_extract.to_artifact()
        restored = PLSDAExtract.from_artifact(metadata, arrays)

        assert restored.classes == ["A", "B", "C"]
        assert restored.n_components == 3
        np.testing.assert_array_equal(restored.coef, plsda_extract.coef)
        np.testing.assert_array_equal(restored.x_mean, plsda_extract.x_mean)
        np.testing.assert_array_equal(restored.y_mean, plsda_extract.y_mean)

    def test_predict_returns_labels_and_probs(self, plsda_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 20))
        labels, probs = plsda_extract.predict(X_new)

        assert labels.shape == (5,)
        assert probs.shape == (5, 3)
        # Probabilities sum to 1 (softmax)
        np.testing.assert_allclose(probs.sum(axis=1), np.ones(5), atol=1e-12)
        # All probabilities non-negative
        assert np.all(probs >= 0)
        # Labels are from the class list
        assert all(label in ["A", "B", "C"] for label in labels)

    def test_predict_single_sample(self, plsda_extract):
        X = np.random.default_rng(7).standard_normal(20)
        labels, probs = plsda_extract.predict(X)
        assert labels.shape == (1,)
        assert probs.shape == (1, 3)

    def test_modelstore_integration(self, tmp_path, plsda_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSDAExtract
        from spectra_sherpa.app.services.model_store import ModelStore

        store = ModelStore(tmp_path)
        metadata, arrays = plsda_extract.to_artifact()
        metadata["n_features"] = 20
        store.save("plsda-test", metadata, arrays)

        loaded_manifest, loaded_arrays = store.load("plsda-test")
        restored = PLSDAExtract.from_artifact(loaded_manifest, loaded_arrays)

        rng = np.random.default_rng(77)
        X = rng.standard_normal((3, 20))
        labels_orig, probs_orig = plsda_extract.predict(X)
        labels_rest, probs_rest = restored.predict(X)
        np.testing.assert_array_equal(labels_orig, labels_rest)
        np.testing.assert_allclose(probs_orig, probs_rest, atol=1e-12)


class TestKNNExtractArtifact:
    """Verify KNNExtract roundtrip and predict."""

    @pytest.fixture()
    def knn_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract

        rng = np.random.default_rng(42)
        n_train, n_features = 30, 10
        classes = ["cat", "dog", "bird"]
        X_train = rng.standard_normal((n_train, n_features)).astype(np.float64)
        y_train_encoded = rng.integers(0, 3, size=n_train).astype(np.int64)

        return KNNExtract(
            X_train=X_train,
            y_train_encoded=y_train_encoded,
            classes=classes,
            k=5,
            metric="euclidean",
            weights="uniform",
        )

    def test_roundtrip(self, knn_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract

        metadata, arrays = knn_extract.to_artifact()
        restored = KNNExtract.from_artifact(metadata, arrays)

        assert restored.classes == ["cat", "dog", "bird"]
        assert restored.k == 5
        assert restored.metric == "euclidean"
        assert restored.weights == "uniform"
        np.testing.assert_array_equal(restored.X_train, knn_extract.X_train)
        np.testing.assert_array_equal(restored.y_train_encoded, knn_extract.y_train_encoded)

    def test_predict_returns_labels_and_probs(self, knn_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 10))
        labels, probs = knn_extract.predict(X_new)

        assert labels.shape == (5,)
        assert probs.shape == (5, 3)
        # Probabilities sum to 1
        np.testing.assert_allclose(probs.sum(axis=1), np.ones(5), atol=1e-12)
        assert all(label in ["cat", "dog", "bird"] for label in labels)

    def test_predict_matches_sklearn(self):
        """KNNExtract.predict() must match sklearn KNN for uniform weights."""
        from sklearn.neighbors import KNeighborsClassifier

        from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract

        rng = np.random.default_rng(789)
        classes = ["alpha", "beta", "gamma"]
        X_train = rng.standard_normal((50, 8)).astype(np.float64)
        y_train_int = rng.integers(0, 3, size=50).astype(np.int64)
        y_train_str = np.array([classes[i] for i in y_train_int])
        X_test = rng.standard_normal((10, 8)).astype(np.float64)

        sk_knn = KNeighborsClassifier(n_neighbors=5, metric="euclidean", weights="uniform")
        sk_knn.fit(X_train, y_train_str)
        sk_labels = sk_knn.predict(X_test)

        extract = KNNExtract(
            X_train=X_train,
            y_train_encoded=y_train_int,
            classes=classes,
            k=5,
            metric="euclidean",
            weights="uniform",
        )
        our_labels, _ = extract.predict(X_test)
        np.testing.assert_array_equal(our_labels, sk_labels)

    def test_distance_weights(self):
        """Distance-weighted KNN gives different results from uniform."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract

        # Place training points at known locations
        X_train = np.array([[0, 0], [1, 0], [0.4, 0]], dtype=np.float64)
        y_encoded = np.array([0, 1, 1], dtype=np.int64)
        classes = ["A", "B"]

        # Test point closer to class A (origin)
        X_test = np.array([[0.1, 0]], dtype=np.float64)

        uniform = KNNExtract(X_train=X_train, y_train_encoded=y_encoded, classes=classes, k=3, weights="uniform")
        distance = KNNExtract(X_train=X_train, y_train_encoded=y_encoded, classes=classes, k=3, weights="distance")

        labels_u, _ = uniform.predict(X_test)
        labels_d, _ = distance.predict(X_test)

        # Uniform: 2 neighbors are B, 1 is A → B
        assert labels_u[0] == "B"
        # Distance: A is much closer → A
        assert labels_d[0] == "A"


class TestSIMCAExtractArtifact:
    """Verify SIMCAExtract roundtrip and predict."""

    @pytest.fixture()
    def simca_extract(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract

        rng = np.random.default_rng(42)
        n_features, n_comp = 20, 2
        classes = ["red", "blue"]

        # Build per-class PCA models
        class_loadings = {}
        class_eigenvalues = {}
        class_means = {}
        for label in classes:
            loadings = rng.standard_normal((n_comp, n_features)).astype(np.float64)
            # Orthogonalize
            q, _ = np.linalg.qr(loadings.T)
            class_loadings[label] = q.T[:n_comp]
            class_eigenvalues[label] = np.array([2.0, 0.5], dtype=np.float64)
            class_means[label] = rng.standard_normal(n_features).astype(np.float64)

        return SIMCAExtract(
            class_loadings=class_loadings,
            class_eigenvalues=class_eigenvalues,
            class_means=class_means,
            classes=classes,
            T2_limits={"red": 6.0, "blue": 6.0},
            Q_limits={"red": 2.0, "blue": 2.0},
            n_components=n_comp,
        )

    def test_roundtrip(self, simca_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract

        metadata, arrays = simca_extract.to_artifact()
        restored = SIMCAExtract.from_artifact(metadata, arrays)

        assert restored.classes == ["red", "blue"]
        assert restored.n_components == 2
        assert restored.T2_limits == {"red": 6.0, "blue": 6.0}
        assert restored.Q_limits == {"red": 2.0, "blue": 2.0}

        for label in ["red", "blue"]:
            np.testing.assert_array_equal(restored.class_loadings[label], simca_extract.class_loadings[label])
            np.testing.assert_array_equal(restored.class_eigenvalues[label], simca_extract.class_eigenvalues[label])
            np.testing.assert_array_equal(restored.class_means[label], simca_extract.class_means[label])

    def test_predict_returns_labels_and_probabilities(self, simca_extract):
        rng = np.random.default_rng(99)
        X_new = rng.standard_normal((5, 20))
        labels, probs = simca_extract.predict(X_new)

        assert labels.shape == (5,)
        assert probs.shape == (5, 2)  # 2 classes
        assert all(label in ["red", "blue", "unassigned"] for label in labels)
        # Probabilities should sum to 1 per sample
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-10)
        # All probabilities should be non-negative
        assert np.all(probs >= 0)

    def test_predict_assigns_to_nearest_class(self):
        """Samples near a class mean should be assigned to that class."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract

        n_feat = 5
        loadings = np.eye(2, n_feat, dtype=np.float64)
        eigenvalues = np.array([1.0, 1.0], dtype=np.float64)
        mean_a = np.zeros(n_feat, dtype=np.float64)
        mean_b = np.ones(n_feat, dtype=np.float64) * 10

        extract = SIMCAExtract(
            class_loadings={"A": loadings, "B": loadings},
            class_eigenvalues={"A": eigenvalues, "B": eigenvalues},
            class_means={"A": mean_a, "B": mean_b},
            classes=["A", "B"],
            T2_limits={"A": 10.0, "B": 10.0},
            Q_limits={"A": 10.0, "B": 10.0},
            n_components=2,
        )

        # Samples near A's mean
        X_near_A = np.array([[0.1, 0.1, 0, 0, 0]], dtype=np.float64)
        labels, _ = extract.predict(X_near_A)
        assert labels[0] == "A"

        # Samples near B's mean
        X_near_B = np.array([[10.1, 10.1, 10, 10, 10]], dtype=np.float64)
        labels, _ = extract.predict(X_near_B)
        assert labels[0] == "B"

    def test_modelstore_integration(self, tmp_path, simca_extract):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract
        from spectra_sherpa.app.services.model_store import ModelStore

        store = ModelStore(tmp_path)
        metadata, arrays = simca_extract.to_artifact()
        metadata["n_features"] = 20
        store.save("simca-test", metadata, arrays)

        loaded_manifest, loaded_arrays = store.load("simca-test")
        restored = SIMCAExtract.from_artifact(loaded_manifest, loaded_arrays)

        rng = np.random.default_rng(77)
        X = rng.standard_normal((3, 20))
        labels_orig, probs_orig = simca_extract.predict(X)
        labels_rest, probs_rest = restored.predict(X)
        np.testing.assert_array_equal(labels_orig, labels_rest)
        np.testing.assert_allclose(probs_orig, probs_rest, atol=1e-12)


# ---------------------------------------------------------------------------
# Phase 2: EXTRACT_REGISTRY
# ---------------------------------------------------------------------------


class TestExtractRegistry:
    """Verify the extract registry maps all model types."""

    def test_registry_contains_all_types(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import EXTRACT_REGISTRY

        expected = {
            "pca",
            "pls",
            "pcr",
            "linear_regression",
            "svr",
            "mcr",
            "nmf",
            "fastica",
            "efa",
            "simplisma",
            "plsda",
            "knn",
            "simca",
        }
        assert set(EXTRACT_REGISTRY.keys()) == expected

    def test_registry_classes_have_from_artifact(self):
        from spectra_sherpa.app.lib.adapters.scp_extractors import EXTRACT_REGISTRY

        for name, cls in EXTRACT_REGISTRY.items():
            assert hasattr(cls, "from_artifact"), f"{name} missing from_artifact"
            assert hasattr(cls, "to_artifact"), f"{name} missing to_artifact"


# ---------------------------------------------------------------------------
# Phase 4: LoadApplyModelNode
# ---------------------------------------------------------------------------


def _init_store_and_save(tmp_path, model_type, extract):
    """Helper: init global ModelStore, save an artifact, return its uid."""
    from spectra_sherpa.app.services import model_store as _ms_mod
    from spectra_sherpa.app.services.model_store import ModelStore

    store = ModelStore(tmp_path)
    # Set the module-level singleton so get_model_store() works
    _ms_mod._store = store

    metadata, arrays = extract.to_artifact()
    uid = f"test-{model_type}-uid"
    store.save(uid, metadata, arrays)
    return uid, store


def _make_sherpa_dataset_2d(n_samples, n_features, *, seed=42):
    """Create a SherpaDataset from random data for testing."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis

    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_samples, n_features)).astype(np.float64)
    x_axis = SpectralAxis(
        values=np.linspace(400, 4000, n_features),
        units="cm^-1",
        title="Wavenumber",
    )
    return SherpaDataset(X, feature_axis=x_axis, title="Test Dataset")


class TestLoadApplyModelNode:
    """Verify the LoadApplyModelNode for all supported model types."""

    @pytest.fixture()
    def pca_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        rng = np.random.default_rng(42)
        n_features, n_components = 50, 3
        mean = rng.standard_normal(n_features).astype(np.float64)
        loadings = rng.standard_normal((n_components, n_features)).astype(np.float64)

        extract = PCAExtract(
            scores=np.zeros((1, n_components)),
            loadings=loadings,
            explained_variance_ratio=np.array([0.6, 0.25, 0.1]),
            explained_variance=np.array([3.0, 1.25, 0.5]),
            n_components=n_components,
            mean=mean,
        )
        uid, _ = _init_store_and_save(tmp_path, "pca", extract)
        return uid, extract

    @pytest.fixture()
    def pls_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract

        rng = np.random.default_rng(42)
        n_features, n_targets = 50, 1
        extract = PLSExtract(
            x_scores=None,
            y_scores=None,
            x_loadings=None,
            y_loadings=None,
            coef=rng.standard_normal((n_features, n_targets)),
            n_components=3,
            x_mean=rng.standard_normal(n_features),
            y_mean=rng.standard_normal(n_targets),
        )
        uid, _ = _init_store_and_save(tmp_path, "pls", extract)
        return uid, extract

    @pytest.fixture()
    def plsda_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PLSDAExtract

        rng = np.random.default_rng(42)
        n_features, n_classes = 50, 3
        extract = PLSDAExtract(
            coef=rng.standard_normal((n_features, n_classes)),
            x_mean=rng.standard_normal(n_features),
            y_mean=np.array([1 / 3, 1 / 3, 1 / 3]),
            classes=["A", "B", "C"],
            n_components=3,
        )
        uid, _ = _init_store_and_save(tmp_path, "plsda", extract)
        return uid, extract

    @pytest.fixture()
    def knn_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract

        rng = np.random.default_rng(42)
        n_train, n_features = 30, 50
        extract = KNNExtract(
            X_train=rng.standard_normal((n_train, n_features)),
            y_train_encoded=rng.integers(0, 3, size=n_train).astype(np.int64),
            classes=["cat", "dog", "bird"],
            k=5,
        )
        uid, _ = _init_store_and_save(tmp_path, "knn", extract)
        return uid, extract

    @pytest.fixture()
    def simca_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract

        rng = np.random.default_rng(42)
        n_features, n_comp = 50, 2
        classes = ["red", "blue"]
        class_loadings = {}
        class_eigenvalues = {}
        class_means = {}
        for label in classes:
            class_loadings[label] = rng.standard_normal((n_comp, n_features))
            class_eigenvalues[label] = np.array([2.0, 0.5])
            class_means[label] = rng.standard_normal(n_features)

        extract = SIMCAExtract(
            class_loadings=class_loadings,
            class_eigenvalues=class_eigenvalues,
            class_means=class_means,
            classes=classes,
            T2_limits={"red": 6.0, "blue": 6.0},
            Q_limits={"red": 2.0, "blue": 2.0},
            n_components=n_comp,
        )
        uid, _ = _init_store_and_save(tmp_path, "simca", extract)
        return uid, extract

    @pytest.fixture()
    def mcr_uid(self, tmp_path):
        from spectra_sherpa.app.lib.adapters.scp_extractors import MCRExtract

        rng = np.random.default_rng(42)
        extract = MCRExtract(
            C=rng.standard_normal((20, 3)),
            St=rng.standard_normal((3, 50)),
            n_components=3,
        )
        uid, _ = _init_store_and_save(tmp_path, "mcr", extract)
        return uid, extract

    def _create_node(self, model_id=""):
        from spectra_sherpa.app.services.dag import node_registry

        return node_registry.create_node(
            node_type="model.load_apply",
            node_id="load_apply_test",
            parameters={"model_id": model_id},
        )

    @pytest.mark.asyncio
    async def test_pca_transform(self, pca_uid):
        uid, extract = pca_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert "result" in result
        assert result["model_id"] == uid
        assert result["metadata"]["type"] == "PCA"
        assert result["metadata"]["output_type"] == "decomposition"

        # Verify numeric output matches extract.transform()
        X_data = np.asarray(X_ds.data, dtype=np.float64)
        expected = extract.transform(X_data)
        np.testing.assert_allclose(result["result"], expected, atol=1e-12)

    @pytest.mark.asyncio
    async def test_pls_predict(self, pls_uid):
        uid, extract = pls_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert "result" in result
        assert "y_pred" in result
        assert result["metadata"]["type"] == "PLS"
        assert result["metadata"]["output_type"] == "regression"

        X_data = np.asarray(X_ds.data, dtype=np.float64)
        expected = extract.predict(X_data)
        np.testing.assert_allclose(result["result"], expected, atol=1e-12)

    @pytest.mark.asyncio
    async def test_plsda_classification(self, plsda_uid):
        uid, extract = plsda_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert "labels" in result
        assert "result" in result
        assert result["metadata"]["type"] == "PLSDA"
        assert result["metadata"]["output_type"] == "classification"
        assert result["metadata"]["classes"] == ["A", "B", "C"]

        X_data = np.asarray(X_ds.data, dtype=np.float64)
        expected_labels, expected_probs = extract.predict(X_data)
        assert result["labels"] == list(expected_labels)
        np.testing.assert_allclose(result["result"], expected_probs, atol=1e-12)

    @pytest.mark.asyncio
    async def test_knn_classification(self, knn_uid):
        uid, extract = knn_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert "labels" in result
        assert result["metadata"]["type"] == "KNN"
        assert all(label in ["cat", "dog", "bird"] for label in result["labels"])

    @pytest.mark.asyncio
    async def test_simca_classification(self, simca_uid):
        uid, extract = simca_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert "labels" in result
        assert result["metadata"]["type"] == "SIMCA"
        assert all(label in ["red", "blue", "unassigned"] for label in result["labels"])

    @pytest.mark.asyncio
    async def test_mcr_transform(self, mcr_uid):
        uid, extract = mcr_uid
        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds)

        assert result["metadata"]["type"] == "MCR"
        assert result["metadata"]["output_type"] == "decomposition"

        X_data = np.asarray(X_ds.data, dtype=np.float64)
        expected = extract.transform(X_data)
        np.testing.assert_allclose(result["result"], expected, atol=1e-10)

    @pytest.mark.asyncio
    async def test_model_ref_port_overrides_parameter(self, pca_uid):
        """model_ref input port should take priority over model_id parameter."""
        uid, extract = pca_uid
        node = self._create_node(model_id="wrong-uid-should-be-ignored")
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        # Pass model_ref as a string (direct model_id)
        result = await node.execute(X_new=X_ds, model_ref=uid)

        assert result["model_id"] == uid

    @pytest.mark.asyncio
    async def test_model_ref_as_dict(self, pca_uid):
        """model_ref can be a dict with 'model_id' key (from training node output)."""
        uid, extract = pca_uid
        node = self._create_node()
        X_ds = _make_sherpa_dataset_2d(5, 50, seed=99)

        result = await node.execute(X_new=X_ds, model_ref={"model_id": uid})

        assert result["model_id"] == uid

    @pytest.mark.asyncio
    async def test_missing_model_id_raises(self, tmp_path):
        from spectra_sherpa.app.services import model_store as _ms_mod
        from spectra_sherpa.app.services.model_store import ModelStore

        _ms_mod._store = ModelStore(tmp_path)

        node = self._create_node(model_id="")
        X_ds = _make_sherpa_dataset_2d(5, 50)

        with pytest.raises(ValueError, match="No model specified"):
            await node.execute(X_new=X_ds)

    @pytest.mark.asyncio
    async def test_nonexistent_model_raises(self, tmp_path):
        from spectra_sherpa.app.services import model_store as _ms_mod
        from spectra_sherpa.app.services.model_store import ModelStore

        _ms_mod._store = ModelStore(tmp_path)

        node = self._create_node(model_id="nonexistent-uid-12345")
        X_ds = _make_sherpa_dataset_2d(5, 50)

        with pytest.raises(ValueError, match="not found"):
            await node.execute(X_new=X_ds)

    @pytest.mark.asyncio
    async def test_feature_count_mismatch_raises(self, pca_uid):
        uid, _ = pca_uid
        # Save with n_features in manifest
        from spectra_sherpa.app.services.model_store import get_model_store

        store = get_model_store()
        manifest = store.load_manifest(uid)
        manifest["n_features"] = 50
        # Re-save with n_features set
        import json

        manifest_path = store.models_dir / uid / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        node = self._create_node(model_id=uid)
        # Input with wrong number of features (30 instead of 50)
        X_ds = _make_sherpa_dataset_2d(5, 30, seed=99)

        with pytest.raises(ValueError, match="Feature count mismatch"):
            await node.execute(X_new=X_ds)

    @pytest.mark.asyncio
    async def test_efa_model_raises(self, tmp_path):
        """EFA is diagnostic-only — LoadApplyModelNode should refuse it."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import EFAExtract

        rng = np.random.default_rng(42)
        extract = EFAExtract(
            forward_ev=rng.standard_normal((20, 3)),
            backward_ev=rng.standard_normal((20, 3)),
            n_components=3,
        )
        uid, _ = _init_store_and_save(tmp_path, "efa", extract)

        node = self._create_node(model_id=uid)
        X_ds = _make_sherpa_dataset_2d(5, 50)

        with pytest.raises(ValueError, match="diagnostic"):
            await node.execute(X_new=X_ds)

    def test_node_registered(self):
        """LoadApplyModelNode should be discoverable in the node registry."""
        from spectra_sherpa.app.services.dag import node_registry

        node = node_registry.create_node(
            node_type="model.load_apply",
            node_id="reg_test",
            parameters={},
        )
        assert node.metadata.node_type == "model.load_apply"
        assert node.metadata.category == "regression"

    def test_node_has_expected_ports(self):
        from spectra_sherpa.app.services.dag import node_registry

        node = node_registry.create_node(
            node_type="model.load_apply",
            node_id="port_test",
            parameters={},
        )
        input_names = {p.name for p in node.metadata.input_ports}
        output_names = {p.name for p in node.metadata.output_ports}

        assert "X_new" in input_names
        assert "model_ref" in input_names
        assert "result" in output_names
        assert "labels" in output_names
        assert "model_id" in output_names


# ---------------------------------------------------------------------------
# Audit DATA-1/2/3/4: model-artifact store durability & integrity
# ---------------------------------------------------------------------------


class TestModelStoreDurability:
    """Atomic save, verified load, orphan reconcile, import-collision safety."""

    @pytest.fixture()
    def store(self, tmp_path):
        from spectra_sherpa.app.services.model_store import ModelStore

        return ModelStore(tmp_path)

    @pytest.fixture()
    def manifest(self):
        return {"model_type": "pls", "n_features": 10, "n_components": 2}

    @pytest.fixture()
    def arrays(self):
        rng = np.random.default_rng(7)
        return {"coef": rng.standard_normal((2, 10)).astype(np.float64)}

    # ── DATA-1: atomic save ──────────────────────────────────────────

    def test_save_leaves_no_staging_dir(self, store, manifest, arrays):
        store.save("uid-clean", manifest, arrays)
        children = sorted(p.name for p in store.models_dir.iterdir())
        assert children == ["uid-clean"]
        assert not any(c.startswith(".staging-") or ".old-" in c for c in children)

    def test_failed_save_preserves_prior_artifact(self, store, manifest, arrays, monkeypatch):
        # First save succeeds.
        store.save("uid-keep", dict(manifest), dict(arrays))
        good_hash = store.load_manifest("uid-keep")["integrity_hash"]

        # A re-save that blows up after staging the npz but before
        # promotion must leave the original artifact fully intact and
        # leave no scratch dirs behind (audit DATA-1).
        from spectra_sherpa.app.services import model_store as ms

        def boom(_path):
            raise RuntimeError("disk full mid-save")

        monkeypatch.setattr(ms, "_sha256_file", boom)
        with pytest.raises(RuntimeError, match="disk full"):
            store.save("uid-keep", {"model_type": "tampered"}, {"x": np.zeros(3)})
        monkeypatch.undo()

        manifest_after, arrays_after = store.load("uid-keep")
        assert manifest_after["model_type"] == "pls"
        assert manifest_after["integrity_hash"] == good_hash
        np.testing.assert_array_equal(arrays_after["coef"], arrays["coef"])
        assert store.verify_integrity("uid-keep") is True
        children = [p.name for p in store.models_dir.iterdir()]
        assert children == ["uid-keep"]

    def test_resave_overwrites_atomically(self, store, manifest):
        store.save("uid-rs", dict(manifest), {"coef": np.ones((2, 10))})
        new = {"coef": np.full((2, 10), 9.0)}
        store.save("uid-rs", dict(manifest), new)
        loaded_manifest, loaded_arrays = store.load("uid-rs")
        np.testing.assert_array_equal(loaded_arrays["coef"], new["coef"])
        assert store.verify_integrity("uid-rs") is True
        assert [p.name for p in store.models_dir.iterdir()] == ["uid-rs"]

    # ── DATA-3: verified load ────────────────────────────────────────

    def test_load_raises_on_corrupt_npz(self, store, manifest, arrays):
        from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError

        store.save("uid-corrupt", manifest, arrays)
        npz_path = store._artifact_dir("uid-corrupt") / "arrays.npz"
        # Realistic corruption: a still-parseable npz with different
        # content (bit-rot / partial overwrite).  np.load succeeds but
        # the hash no longer matches — exactly what verify must catch
        # and np.load alone would not.
        buf = io.BytesIO()
        np.savez_compressed(buf, coef=np.zeros((2, 10)))
        npz_path.write_bytes(buf.getvalue())

        with pytest.raises(ModelArtifactIntegrityError, match="corrupt"):
            store.load("uid-corrupt")
        # Explicit opt-out still returns the (now-wrong) arrays for tooling.
        manifest_only, arrays_only = store.load("uid-corrupt", verify=False)
        assert manifest_only["model_type"] == "pls"
        np.testing.assert_array_equal(arrays_only["coef"], np.zeros((2, 10)))
        assert store.verify_integrity("uid-corrupt") is False

        # A totally unparseable npz is also rejected by verified load.
        npz_path.write_bytes(b"not a real npz")
        with pytest.raises(ModelArtifactIntegrityError, match="corrupt"):
            store.load("uid-corrupt")

    def test_load_raises_when_manifest_has_no_hash(self, store, manifest, arrays):
        from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError

        store.save("uid-nohash", manifest, arrays)
        mpath = store._artifact_dir("uid-nohash") / "manifest.json"
        mpath.write_text(json.dumps({"model_type": "pls"}))
        with pytest.raises(ModelArtifactIntegrityError, match="no integrity_hash"):
            store.load("uid-nohash")

    async def test_load_apply_node_rejects_corrupt_model(self, store, manifest, monkeypatch):
        from spectra_sherpa.app.services import model_store as ms
        from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import (
            LoadApplyModelNode,
        )

        store.save("uid-bad", {"model_type": "pls", "n_features": 3}, {"coef": np.ones((1, 3))})
        (store._artifact_dir("uid-bad") / "arrays.npz").write_bytes(b"garbage")
        monkeypatch.setattr(ms, "_store", store)

        node = LoadApplyModelNode(node_id="n1", parameters={"model_id": "uid-bad"})
        with pytest.raises(ValueError, match="corrupt"):
            await node.execute(X_new=np.zeros((2, 3)))

    # ── DATA-2: orphan reconcile ─────────────────────────────────────

    async def test_reconcile_orphan_artifacts(self, store, test_session, test_user):
        from spectra_sherpa.app.models.model_artifact import ModelArtifact
        from spectra_sherpa.app.services.model_store import reconcile_orphan_artifacts

        # Referenced artifact (has a DB row) — must be kept.
        store.save("uid-referenced", {"model_type": "pls"}, {"a": np.ones(2)})
        test_session.add(
            ModelArtifact(
                artifact_uid="uid-referenced",
                user_id=test_user.id,
                node_id="n",
                model_type="pls",
                name="ref",
                artifact_dir=str(store._artifact_dir("uid-referenced")),
                integrity_hash="x",
                n_features=2,
            )
        )
        # Soft-deleted artifact (inactive DB row) — its files are no longer
        # user-visible and should be reaped after the grace window.
        store.save("uid-inactive", {"model_type": "pls"}, {"a": np.ones(2)})
        test_session.add(
            ModelArtifact(
                artifact_uid="uid-inactive",
                user_id=test_user.id,
                node_id="n",
                model_type="pls",
                name="inactive",
                artifact_dir=str(store._artifact_dir("uid-inactive")),
                integrity_hash="x",
                n_features=2,
                is_active=False,
            )
        )
        await test_session.commit()

        # Old orphan (no DB row) — must be reaped.
        store.save("uid-orphan-old", {"model_type": "pls"}, {"a": np.ones(2)})
        # Recent orphan — within grace, must be kept.
        store.save("uid-orphan-new", {"model_type": "pls"}, {"a": np.ones(2)})
        # Abandoned staging scratch — swept once past grace.
        (store.models_dir / ".staging-uid-x-abcd").mkdir()
        # A *stale* .old- backup whose canonical artifact is present —
        # the promote completed, so this is genuine scratch and is reaped.
        store.save("uid-stale", {"model_type": "pls"}, {"a": np.ones(2)})
        (store.models_dir / "uid-stale.old-deadbeef").mkdir()

        old = time.time() - 7200
        for name in ("uid-inactive", "uid-orphan-old", ".staging-uid-x-abcd", "uid-stale.old-deadbeef"):
            os.utime(store.models_dir / name, (old, old))

        removed = await reconcile_orphan_artifacts(test_session, store=store, grace_seconds=3600)

        assert set(removed) == {"uid-inactive", "uid-orphan-old", ".staging-uid-x-abcd", "uid-stale.old-deadbeef"}
        assert store._artifact_dir("uid-referenced").exists()
        assert store._artifact_dir("uid-orphan-new").exists()
        assert store._artifact_dir("uid-stale").exists()
        assert not store._artifact_dir("uid-inactive").exists()
        assert not store._artifact_dir("uid-orphan-old").exists()

    async def test_reconcile_recovers_artifact_from_interrupted_resave(self, store, manifest, arrays, test_session):
        """Audit DATA-1 crash safety: a hard kill between _promote's two
        renames leaves the canonical dir gone and only ``<uid>.old-<hex>``
        (with its original, pre-grace mtime).  Reconcile must RESTORE it,
        never reap it — otherwise the sole good copy is destroyed."""
        from spectra_sherpa.app.services.model_store import reconcile_orphan_artifacts

        store.save("uid-rs", dict(manifest), dict(arrays))
        good_hash = store.load_manifest("uid-rs")["integrity_hash"]

        # Reproduce the post-rename1 / pre-rename2 on-disk state exactly.
        canonical = store._artifact_dir("uid-rs")
        backup = store.models_dir / "uid-rs.old-deadbeef"
        os.replace(canonical, backup)
        # The renamed backup keeps the original (old) mtime — prove grace
        # does not gate recovery by making it ancient and the canonical
        # absent.  Also leave the unpromoted staging scratch behind.
        ancient = time.time() - 7200
        os.utime(backup, (ancient, ancient))
        staging = store.models_dir / ".staging-uid-rs-tmp"
        staging.mkdir()
        os.utime(staging, (ancient, ancient))
        assert not canonical.exists()

        removed = await reconcile_orphan_artifacts(test_session, store=store, grace_seconds=3600)

        # Canonical restored from the backup, fully intact.
        assert canonical.exists()
        assert not backup.exists()
        rec_manifest, rec_arrays = store.load("uid-rs")
        assert rec_manifest["integrity_hash"] == good_hash
        np.testing.assert_array_equal(rec_arrays["coef"], arrays["coef"])
        assert store.verify_integrity("uid-rs") is True
        # The backup was recovered (not in removed); staging reaped.
        assert "uid-rs.old-deadbeef" not in removed
        assert ".staging-uid-rs-tmp" in removed

    # ── DATA-4: import collision safety ──────────────────────────────

    def test_remap_model_uids_in_snapshot(self):
        from spectra_sherpa.app.api.v1.routes.projects import (
            _remap_model_uids_in_snapshot,
        )

        snap = {
            "models": [{"artifact_uid": "old1"}, {"artifact_uid": "untouched"}],
            "workflows": [
                {
                    "nodes": [
                        {"parameters": {"model_id": "old1"}},
                        {"parameters": {"threshold": 5}},
                        {"parameters": None},
                    ]
                }
            ],
        }
        _remap_model_uids_in_snapshot(snap, {"old1": "new1"})
        assert snap["models"][0]["artifact_uid"] == "new1"
        assert snap["models"][1]["artifact_uid"] == "untouched"
        assert snap["workflows"][0]["nodes"][0]["parameters"]["model_id"] == "new1"
        assert snap["workflows"][0]["nodes"][1]["parameters"] == {"threshold": 5}

        # Empty remap is a no-op.
        frozen = json.loads(json.dumps(snap))
        _remap_model_uids_in_snapshot(snap, {})
        assert snap == frozen

    def test_purge_artifacts(self, store, manifest, arrays, monkeypatch):
        from spectra_sherpa.app.api.v1.routes import projects as proj
        from spectra_sherpa.app.services import model_store as ms

        store.save("uid-p1", dict(manifest), dict(arrays))
        store.save("uid-p2", dict(manifest), dict(arrays))
        monkeypatch.setattr(ms, "_store", store)

        proj._purge_artifacts([])  # no-op, no error
        proj._purge_artifacts(["uid-p1", "uid-missing"])  # missing uid tolerated

        assert not store._artifact_dir("uid-p1").exists()
        assert store._artifact_dir("uid-p2").exists()
