"""
Tests for the Type Registry (Phase 1).

Covers:
- Loading registry.json + all JSON schemas
- URI parsing
- Type resolution (by URI, by name, version tolerance)
- Compatibility checks (same type, subtype, version, cross-type)
- Port category mapping
- API serialisation

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_type_registry.py -v --no-cov
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectra_sherpa.app.types.registry import TypeRegistry, parse_type_ref

TYPES_DIR = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "types"

# Read expected count from registry.json so the test stays in sync automatically.
_REGISTRY_JSON = TYPES_DIR / "registry.json"
_EXPECTED_TYPE_COUNT = len(json.loads(_REGISTRY_JSON.read_text())["types"])


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def registry() -> TypeRegistry:
    """Fresh registry loaded from disk."""
    reg = TypeRegistry()
    reg.load(TYPES_DIR)
    return reg


# ── URI parsing ───────────────────────────────────────────────────────────


class TestParseTypeRef:
    def test_valid_uri(self):
        name, major, minor = parse_type_ref("spectrasherpa://types/SpectralDataset/1.0")
        assert name == "SpectralDataset"
        assert major == 1
        assert minor == 0

    def test_higher_version(self):
        name, major, minor = parse_type_ref("spectrasherpa://types/Array2D/2.3")
        assert name == "Array2D"
        assert major == 2
        assert minor == 3

    def test_malformed_raises(self):
        with pytest.raises(ValueError, match="Malformed"):
            parse_type_ref("not-a-uri")

    def test_missing_version_raises(self):
        with pytest.raises(ValueError, match="Malformed"):
            parse_type_ref("spectrasherpa://types/Foo")


# ── Loading ───────────────────────────────────────────────────────────────


class TestRegistryLoading:
    def test_loads_all_types(self, registry: TypeRegistry):
        assert len(registry) == _EXPECTED_TYPE_COUNT

    def test_is_loaded_flag(self, registry: TypeRegistry):
        assert registry.is_loaded is True

    def test_version(self, registry: TypeRegistry):
        assert registry.version == "1.0"

    def test_all_types_have_category(self, registry: TypeRegistry):
        """Every type should have a non-empty category."""
        for td in registry.list_types():
            assert td.category, f"Type {td.name} has no category"

    def test_file_not_found_raises(self):
        reg = TypeRegistry()
        with pytest.raises(FileNotFoundError):
            reg.load(Path("/nonexistent"))


# ── Resolution ────────────────────────────────────────────────────────────


class TestResolution:
    def test_resolve_exact_uri(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/SpectralDataset/1.0")
        assert td.name == "SpectralDataset"
        assert td.major == 1
        assert td.minor == 0

    def test_resolve_all_known_types(self, registry: TypeRegistry):
        """Every type in registry.json should be resolvable."""
        for td in registry.list_types():
            resolved = registry.resolve(td.uri)
            assert resolved.name == td.name

    def test_resolve_unknown_raises(self, registry: TypeRegistry):
        with pytest.raises(KeyError, match="Unknown type_ref"):
            registry.resolve("spectrasherpa://types/NonExistent/1.0")

    def test_resolve_by_name(self, registry: TypeRegistry):
        td = registry.resolve_by_name("Scalar")
        assert td.uri == "spectrasherpa://types/Scalar/1.0"

    def test_resolve_by_name_unknown_raises(self, registry: TypeRegistry):
        with pytest.raises(KeyError, match="Unknown type name"):
            registry.resolve_by_name("Bogus")

    def test_contains_operator(self, registry: TypeRegistry):
        assert "spectrasherpa://types/Scalar/1.0" in registry
        assert "spectrasherpa://types/Nonexistent/1.0" not in registry


# ── Compatibility ─────────────────────────────────────────────────────────


class TestCompatibility:
    """Core compatibility matrix tests."""

    def test_same_uri(self, registry: TypeRegistry):
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is True
        assert reason == ""

    def test_same_name_same_major(self, registry: TypeRegistry):
        """Same name + same major version → compatible (minor ignored)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/SpectralDataset/1.7",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is True

    def test_same_name_major_mismatch(self, registry: TypeRegistry):
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/SpectralDataset/2.0",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is False
        assert "version mismatch" in reason.lower()

    def test_subtype_child_to_parent(self, registry: TypeRegistry):
        """ScoreMatrix → Array2D (child can connect to parent)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/ScoreMatrix/1.0",
            "spectrasherpa://types/Array2D/1.0",
        )
        assert ok is True

    def test_subtype_parent_to_child_fails(self, registry: TypeRegistry):
        """Array2D → ScoreMatrix (parent cannot connect to child)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/Array2D/1.0",
            "spectrasherpa://types/ScoreMatrix/1.0",
        )
        assert ok is False

    def test_cross_type_fails(self, registry: TypeRegistry):
        """SpectralDataset → FittedModel (unrelated types)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is False
        assert "mismatch" in reason.lower()

    def test_decomposition_to_fitted_model(self, registry: TypeRegistry):
        """DecompositionResult → FittedModel (subtype)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/DecompositionResult/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is True

    def test_regression_to_fitted_model(self, registry: TypeRegistry):
        """RegressionModel → FittedModel (subtype)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/RegressionModel/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is True

    def test_classification_to_fitted_model(self, registry: TypeRegistry):
        """ClassificationModel → FittedModel (subtype)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/ClassificationModel/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is True

    def test_spectrum_to_array1d(self, registry: TypeRegistry):
        """Spectrum → Array1D (subtype)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/Spectrum/1.0",
            "spectrasherpa://types/Array1D/1.0",
        )
        assert ok is True

    def test_spectral_dataset_to_array2d(self, registry: TypeRegistry):
        """SpectralDataset → Array2D (subtype)."""
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/Array2D/1.0",
        )
        assert ok is True

    def test_any_wildcard_accepts_all(self, registry: TypeRegistry):
        """Any target accepts any source type."""
        for source in [
            "spectrasherpa://types/ScoreMatrix/1.0",
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/FittedModel/1.0",
            "spectrasherpa://types/Scalar/1.0",
        ]:
            ok, reason = registry.is_compatible(source, "spectrasherpa://types/Any/1.0")
            assert ok is True, f"Expected {source} → Any to be compatible, got: {reason}"

    def test_unresolvable_source(self, registry: TypeRegistry):
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/NonExistent/1.0",
            "spectrasherpa://types/Scalar/1.0",
        )
        assert ok is False
        assert "resolve" in reason.lower()

    def test_unresolvable_target(self, registry: TypeRegistry):
        ok, reason = registry.is_compatible(
            "spectrasherpa://types/Scalar/1.0",
            "spectrasherpa://types/NonExistent/1.0",
        )
        assert ok is False


class TestSubtype:
    def test_direct_subtype(self, registry: TypeRegistry):
        assert (
            registry.is_subtype(
                "spectrasherpa://types/ScoreMatrix/1.0",
                "spectrasherpa://types/Array2D/1.0",
            )
            is True
        )

    def test_not_subtype(self, registry: TypeRegistry):
        assert (
            registry.is_subtype(
                "spectrasherpa://types/Scalar/1.0",
                "spectrasherpa://types/Array2D/1.0",
            )
            is False
        )

    def test_reflexive_not_subtype(self, registry: TypeRegistry):
        """A type is NOT a subtype of itself."""
        assert (
            registry.is_subtype(
                "spectrasherpa://types/Scalar/1.0",
                "spectrasherpa://types/Scalar/1.0",
            )
            is False
        )

    def test_reversed_not_subtype(self, registry: TypeRegistry):
        """Array2D is NOT a subtype of ScoreMatrix."""
        assert (
            registry.is_subtype(
                "spectrasherpa://types/Array2D/1.0",
                "spectrasherpa://types/ScoreMatrix/1.0",
            )
            is False
        )


# ── Category from TypeDef ─────────────────────────────────────────────────


class TestTypeCategory:
    def test_dataset_category(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/SpectralDataset/1.0")
        assert td.category == "dataset"

    def test_model_category(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/FittedModel/1.0")
        assert td.category == "model"

    def test_target_category(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/Categorical/1.0")
        assert td.category == "target"

    def test_number_category(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/Scalar/1.0")
        assert td.category == "number"

    def test_visualization_category(self, registry: TypeRegistry):
        td = registry.resolve("spectrasherpa://types/Visualization/1.0")
        assert td.category == "visualization"


# ── API JSON ──────────────────────────────────────────────────────────────


class TestApiJson:
    def test_structure(self, registry: TypeRegistry):
        data = registry.to_api_json()
        assert "version" in data
        assert "types" in data
        assert "subtypes" in data

    def test_all_types_included(self, registry: TypeRegistry):
        data = registry.to_api_json()
        assert len(data["types"]) == _EXPECTED_TYPE_COUNT

    def test_type_entry_shape(self, registry: TypeRegistry):
        data = registry.to_api_json()
        entry = data["types"]["SpectralDataset"]
        assert entry["uri"] == "spectrasherpa://types/SpectralDataset/1.0"
        assert entry["parent"] == "Array2D"
        assert entry["category"] == "dataset"
        assert entry["version"] == "1.0"

    def test_subtypes_map(self, registry: TypeRegistry):
        data = registry.to_api_json()
        # Array2D should have children
        assert "Array2D" in data["subtypes"]
        assert "SpectralDataset" in data["subtypes"]["Array2D"]
        assert "ScoreMatrix" in data["subtypes"]["Array2D"]
