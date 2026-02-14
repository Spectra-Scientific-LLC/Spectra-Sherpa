# FUTURE

Future phases, roadmap items, and extensive refactors beyond the current release.

## 1. Cloud AlgorithmRegistry
**Status**: PLANNED (~12-15 hours)

Federated node registry allowing the SpectraSherpa cloud to discover, serve, and update node definitions for Repo 2. Follows existing ToolRegistry/NodeRegistry patterns.

## 2. Node Standardization (Full Refactor)
**Source**: `NODE_STANDARDIZATION_EFFORT.md`
**Status**: BACKLOG

Convert remaining ~50 nodes to the modern port-based pattern. ~41-44 hours estimated.

## 3. Plugin System
**Source**: `docs/future/plugin_plan_011525.md`
**Status**: CONCEPT

Third-party node and visualization widget architecture. Plugin manifest, registry, sandboxed execution.

## 4. Product Roadmap
**Source**: `docs/future/FUTURE_CAPABILITIES.md`
**Status**: PLANNED

- **Q2 2026**: Advanced Chemometrics (MCR-ALS constraints, PLS variable selection)
- **Q3 2026**: Real-time Acquisition (Instrument drivers for Ocean Optics, Bruker)
- **Q4 2026**: Enterprise Features (SAML/SSO, RBAC)

## 5. Analysis Canvas (UI Redesign)
**Source**: `docs/future/ANALYSIS_CANVAS_WIREFRAME.md`
**Status**: CONCEPT

Free-form canvas interaction, annotations, multi-plot visualization redesign.

## 6. Python Export — Remaining Phases (4-6)
**Status**: BACKLOG

- Phase 4: Modeling nodes (17 nodes) — `generate_python()` annotations
- Phase 5: Remaining nodes (26 nodes) — classification, output, blend, custom
- Phase 6: Integration tests — end-to-end export + execution validation
- Phases 0-3 complete and working. Remaining nodes return `supports_python_export() = False`.

## 7. Capability Gaps (Priority 3-4)
**Status**: BACKLOG

- Rate-limited response headers (consistent X-RateLimit-* across all endpoints)
- Feature flag contract (centralize /config fallback semantics)
- Template unification (backend API source of truth for templates)
