# FUTURE

This document tracks future phases, roadmap items, and extensive refactors not critical for the immediate Digital Ocean deployment.

## 1. Node Standardization Effort (Full Refactor)
**Source**: `NODE_STANDARDIZATION_EFFORT.md`
**Status**: 📅 BACKLOG (Recommended Start: Before Release)

Proposal to convert all 53 nodes to the modern port-based pattern (Option A).
- **Scope**: Convert remaining ~50 nodes (excluding the 3 critical ones fixed in DONE.md).
- **Effort**: Estimated 41-44 hours (~1 week).
- **Goal**: Consistent API, self-documenting ports, better type safety.

## 2. Product Roadmap (Future Capabilities)
**Source**: `docs/future/ROADMAP.md` / `docs/future/FUTURE_CAPABILITIES.md`
**Status**: 📅 PLANNED

- **Q2 2026**: Advanced Chemometrics (MCR-ALS constraints, PLS variable selection).
- **Q3 2026**: Real-time Acquisition (Instrument drivers for Ocean Optics, Bruker).
- **Q4 2026**: Enterprise Features (SAML/SSO, Role-Based Access Control).

## 3. Analysis Canvas (UI Redesign)
**Source**: `docs/future/ANALYSIS_CANVAS_WIREFRAME.md`
**Status**: 📅 CONCEPT

- Redesign of the main workspace interface to support free-form canvas interaction, annotations, and better multi-plot visualization.

## 4. Design of Experiment (DoE)
**Source**: `docs/future/DOE_ENHANCEMENTS.md`
**Status**: 📅 CONCEPT

- Implementation of factorial design generation and analysis within the platform.

## 5. Plugin System
**Source**: `docs/future/plugin_plan_011525.md`
**Status**: 📅 CONCEPT

- Architecture for allowing third-party developers to add custom nodes and visualization widgets.

## 6. Capability Gaps (Low Priority)
**Source**: `docs/current/CAPABILITY_GAP_BACKLOG.md`
**Status**: 📅 BACKLOG

- **Priority 4: Template Unification**: Migrate frontend hardcoded templates to backend API source of truth.
