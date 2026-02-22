"""
Domain inference engine for analytical chemistry techniques.

This module provides AI-discoverable domain knowledge through a JSON registry
of techniques and inference rules.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import InferredDomain

logger = logging.getLogger(__name__)


class DomainRegistry:
    """Registry of analytical chemistry techniques with inference rules.

    Loads technique definitions and inference rules from domain_registry.json
    to enable AI-discoverable domain knowledge and technique detection.
    """

    def __init__(self, registry_path: str | Path | None = None):
        """Load domain registry from JSON file.

        Args:
            registry_path: Path to domain_registry.json. If None, uses default.
        """
        if registry_path is None:
            # Default: domain_registry.json in same directory as this file
            registry_path = Path(__file__).parent / "domain_registry.json"
        else:
            registry_path = Path(registry_path)

        if not registry_path.exists():
            raise FileNotFoundError(f"Domain registry not found: {registry_path}")

        with open(registry_path, "r", encoding="utf-8") as f:
            self._registry = json.load(f)

        self.version = self._registry.get("version", "1.0")
        self.categories = self._registry.get("categories", {})

    def infer_technique(self, axis: FeatureAxis | None) -> InferredDomain | None:
        """Infer analytical technique from feature axis characteristics.

        Applies inference rules from the registry to detect the most likely
        technique based on axis type, units, and value range.

        Args:
            axis: Feature axis (SpectralAxis, TimeAxis, MZAxis, etc.)

        Returns:
            InferredDomain with technique guess, confidence, and reasoning,
            or None if no matching rule found.
        """
        if axis is None or axis.values is None:
            return None

        axis_type = axis.axis_type
        axis_range = axis.range
        axis_units = axis.units

        if not axis_type or not axis_range:
            return None

        # Search all categories for matching inference rules
        best_match = None
        best_confidence = 0.0

        for category_name, category_data in self.categories.items():
            rules = category_data.get("inference_rules", [])

            for rule in rules:
                # Check if axis type matches
                if rule.get("axis_type") != axis_type:
                    continue

                # Check if units match
                rule_units = rule.get("units", [])
                if axis_units and rule_units:
                    # Normalize units for comparison
                    normalized_units = axis_units.lower().strip()
                    if not any(u.lower() == normalized_units for u in rule_units):
                        continue

                # Check if axis range overlaps with rule range
                rule_range = rule.get("range")
                if rule_range and len(rule_range) == 2:
                    axis_min, axis_max = axis_range
                    rule_min, rule_max = rule_range

                    # Check if there's significant overlap
                    overlap = (
                        max(0, min(axis_max, rule_max) - max(axis_min, rule_min))
                        / (rule_max - rule_min)
                    )

                    # Require at least 20% overlap
                    if overlap < 0.2:
                        continue

                    # Boost confidence based on overlap
                    confidence = rule.get("confidence", 0.5) * (0.5 + 0.5 * overlap)
                else:
                    confidence = rule.get("confidence", 0.5)

                # Track best match
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = InferredDomain(
                        technique=rule.get("technique"),
                        confidence=confidence,
                        source="domain_registry",
                        reasoning=rule.get("reasoning", ""),
                    )

        return best_match

    def validate_technique(self, name: str, category: str | None = None) -> bool:
        """Check if a technique name is registered.

        Args:
            name: Technique name (e.g., "IR", "HPLC", "LC-MS")
            category: Optional category to narrow search

        Returns:
            True if technique is registered, False otherwise.
        """
        if category:
            category_data = self.categories.get(category)
            if category_data:
                techniques = category_data.get("techniques", [])
                return name in techniques
            return False

        # Search all categories
        for category_data in self.categories.values():
            techniques = category_data.get("techniques", [])
            if name in techniques:
                return True
        return False

    def list_techniques(self, category: str | None = None) -> list[str]:
        """List all registered techniques.

        Args:
            category: Optional category to filter by

        Returns:
            List of technique names.
        """
        if category:
            category_data = self.categories.get(category)
            if category_data:
                return category_data.get("techniques", [])
            return []

        # Return all techniques from all categories
        all_techniques = []
        for category_data in self.categories.values():
            techniques = category_data.get("techniques", [])
            all_techniques.extend(techniques)
        return all_techniques

    def list_categories(self) -> list[str]:
        """List all registered technique categories.

        Returns:
            List of category names.
        """
        return list(self.categories.keys())

    def get_category_description(self, category: str) -> str | None:
        """Get description for a category.

        Args:
            category: Category name

        Returns:
            Description string or None if category not found.
        """
        category_data = self.categories.get(category)
        if category_data:
            return category_data.get("description")
        return None

    def get_inference_rules(self, category: str | None = None) -> list[dict[str, Any]]:
        """Get inference rules for a category.

        Args:
            category: Category name, or None for all rules

        Returns:
            List of inference rule dictionaries.
        """
        if category:
            category_data = self.categories.get(category)
            if category_data:
                return category_data.get("inference_rules", [])
            return []

        # Return all rules from all categories
        all_rules = []
        for category_data in self.categories.values():
            rules = category_data.get("inference_rules", [])
            all_rules.extend(rules)
        return all_rules

    def to_dict(self) -> dict[str, Any]:
        """Export registry as dictionary (for MCP/AI introspection).

        Returns:
            Complete registry as JSON-safe dictionary.
        """
        return self._registry


# Global singleton instance for performance
_default_registry: DomainRegistry | None = None


def get_default_registry() -> DomainRegistry:
    """Get the default domain registry singleton.

    Returns:
        Default DomainRegistry instance.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = DomainRegistry()
    return _default_registry
