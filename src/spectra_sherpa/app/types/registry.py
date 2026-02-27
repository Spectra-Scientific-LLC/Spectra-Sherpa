"""
Type registry for SpectraSherpa graph port types.

Loads type definitions from ``registry.json`` and provides:
- URI-based type resolution
- Compatibility checks (same type, version compat, subtype)
- Category lookup for frontend visual cues
- API serialisation for frontend consumption
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── URI helpers ──────────────────────────────────────────────────────────

_URI_RE = re.compile(r"^spectrasherpa://types/(?P<name>[A-Za-z0-9_]+)/(?P<major>\d+)\.(?P<minor>\d+)$")


def parse_type_ref(type_ref: str) -> tuple[str, int, int]:
    """Parse ``spectrasherpa://types/Name/M.m`` → (name, major, minor).

    Raises ``ValueError`` on malformed URIs.
    """
    m = _URI_RE.match(type_ref)
    if not m:
        raise ValueError(f"Malformed type_ref URI: {type_ref!r}")
    return m.group("name"), int(m.group("major")), int(m.group("minor"))


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass
class TypeDef:
    """Resolved type definition."""

    uri: str
    name: str
    version: str  # "1.0"
    major: int
    minor: int
    category: str  # "dataset", "model", "target", etc.
    parent: Optional[str]  # Parent type *name* (e.g. "Array2D"), or None
    parent_uri: Optional[str] = None
    description: str = ""


# ── Registry ─────────────────────────────────────────────────────────────


class TypeRegistry:
    """Singleton registry of all SpectraSherpa data types."""

    def __init__(self) -> None:
        self._types: Dict[str, TypeDef] = {}  # keyed by URI
        self._by_name: Dict[str, TypeDef] = {}  # keyed by short name
        self._children: Dict[str, Set[str]] = {}  # parent_name → {child_names}
        self.version: str = "0.0"
        self._loaded = False

    # ── Loading ──────────────────────────────────────────────────────

    def load(self, registry_dir: Path) -> None:
        """Load ``registry.json`` from *registry_dir*."""
        registry_path = registry_dir / "registry.json"
        if not registry_path.exists():
            raise FileNotFoundError(f"Type registry not found: {registry_path}")

        with open(registry_path) as f:
            manifest = json.load(f)

        self.version = manifest.get("version", "1.0")
        self._types.clear()
        self._by_name.clear()
        self._children.clear()

        for name, entry in manifest.get("types", {}).items():
            uri = entry["uri"]
            _, major, minor = parse_type_ref(uri)
            parent_name = entry.get("parent")

            td = TypeDef(
                uri=uri,
                name=name,
                version=f"{major}.{minor}",
                major=major,
                minor=minor,
                category=entry.get("category", "dataset"),
                parent=parent_name,
                description=entry.get("description", ""),
            )
            self._types[uri] = td
            self._by_name[name] = td

        # Build parent → children map and resolve parent_uri
        for td in self._types.values():
            if td.parent and td.parent in self._by_name:
                td.parent_uri = self._by_name[td.parent].uri
                self._children.setdefault(td.parent, set()).add(td.name)

        self._loaded = True
        logger.info(
            "Type registry loaded: %d types, version %s",
            len(self._types),
            self.version,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ── Resolution ───────────────────────────────────────────────────

    def resolve(self, type_ref: str) -> TypeDef:
        """Resolve a ``type_ref`` URI to its :class:`TypeDef`.

        Raises ``KeyError`` if the URI is unknown.
        """
        if type_ref in self._types:
            return self._types[type_ref]

        # Try matching by name + major version (allow minor version differences)
        name, major, _minor = parse_type_ref(type_ref)
        for td in self._types.values():
            if td.name == name and td.major == major:
                return td

        raise KeyError(f"Unknown type_ref: {type_ref}")

    def resolve_by_name(self, name: str) -> TypeDef:
        """Resolve by short name (e.g. ``"SpectralDataset"``)."""
        if name not in self._by_name:
            raise KeyError(f"Unknown type name: {name}")
        return self._by_name[name]

    # ── Compatibility ────────────────────────────────────────────────

    def is_compatible(self, source_ref: str, target_ref: str) -> tuple[bool, str]:
        """Check whether *source_ref* output can connect to *target_ref* input.

        Returns ``(is_ok, reason)``.  *reason* is empty on success.
        """
        try:
            src_name, src_major, src_minor = parse_type_ref(source_ref)
        except ValueError as exc:
            return False, f"Cannot resolve source type: {exc}"
        try:
            tgt_name, tgt_major, tgt_minor = parse_type_ref(target_ref)
        except ValueError as exc:
            return False, f"Cannot resolve target type: {exc}"

        # Any wildcard: any source → Any target is always compatible.
        if tgt_name == "Any":
            return True, ""

        # Fast-path version checks on same base type.
        if src_name == tgt_name:
            if src_name not in self._by_name:
                return False, f"Cannot resolve source type: Unknown type_ref: {source_ref}"
            if tgt_name not in self._by_name:
                return False, f"Cannot resolve target type: Unknown type_ref: {target_ref}"
            if src_major == tgt_major:
                return True, ""
            return False, (
                f"Version mismatch: {src_name} {src_major}.{src_minor} → "
                f"{tgt_major}.{tgt_minor} (major version differs)"
            )

        try:
            src = self.resolve(source_ref)
        except (KeyError, ValueError) as exc:
            return False, f"Cannot resolve source type: {exc}"
        try:
            tgt = self.resolve(target_ref)
        except (KeyError, ValueError) as exc:
            return False, f"Cannot resolve target type: {exc}"

        # 1. Exact URI match
        if src.uri == tgt.uri:
            return True, ""

        # 2. Subtype: source is a child of target
        if self.is_subtype(source_ref, target_ref):
            return True, ""

        return False, (f"Type mismatch: {src.name} cannot connect to {tgt.name}")

    def is_subtype(self, child_ref: str, parent_ref: str) -> bool:
        """Return ``True`` if *child_ref* is a (transitive) subtype of *parent_ref*."""
        try:
            child = self.resolve(child_ref)
            parent = self.resolve(parent_ref)
        except (KeyError, ValueError):
            return False

        # Walk up the parent chain
        current = child
        seen: set[str] = set()
        while current.parent:
            if current.parent in seen:
                break  # cycle guard
            seen.add(current.parent)
            if current.parent == parent.name:
                return True
            try:
                current = self.resolve_by_name(current.parent)
            except KeyError:
                break
        return False

    # ── Frontend helpers ─────────────────────────────────────────────

    def to_api_json(self) -> dict:
        """Serialise the registry for the ``GET /type-registry`` endpoint."""
        types_out: dict[str, Any] = {}
        for td in self._types.values():
            types_out[td.name] = {
                "uri": td.uri,
                "version": td.version,
                "parent": td.parent,
                "parent_uri": td.parent_uri,
                "category": td.category,
                "description": td.description,
            }

        subtypes: dict[str, list[str]] = {}
        for parent_name, children in self._children.items():
            subtypes[parent_name] = sorted(children)

        return {
            "version": self.version,
            "types": types_out,
            "subtypes": subtypes,
        }

    # ── Introspection ────────────────────────────────────────────────

    def list_types(self) -> List[TypeDef]:
        """Return all registered types."""
        return list(self._types.values())

    def __len__(self) -> int:
        return len(self._types)

    def __contains__(self, type_ref: str) -> bool:
        try:
            self.resolve(type_ref)
            return True
        except (KeyError, ValueError):
            return False
