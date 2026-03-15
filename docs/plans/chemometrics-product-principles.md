# Chemometrics Product Principles And Priorities

## Purpose

This document captures the product principles SpectraSherpa should enforce if it aims to become a best-in-class chemometrics platform rather than a collection of analysis widgets.

The standard is not "can a user get a result today?" but "can a scientist trust, revisit, extend, and deploy that result six months later — whether the workflow was built by hand, by script, or by an LLM agent?"

## Core Principles

### 1. The workflow is a scientific object

The workflow must be treated as the canonical scientific object, not as a temporary UI session.

- Every operation must be explicit, serializable, reproducible, and exportable.
- GUI and Python export must describe the same workflow semantics.
- The workflow graph, not ad hoc session state, must be the source of truth.
- An LLM agent that constructs or modifies a workflow must produce the same auditable artifact a human would.

### 2. Data semantics must be first-class

Spectra, targets, sample metadata, feature axes, selection masks, preprocessing state, and domain assertions must live in typed data structures.

- Raw arrays are not enough.
- Side tables and hidden metadata create both scientific and software debt.
- Sample and feature inclusion state must be explicit and portable.

### 3. Leakage-safe analysis must be the default

The platform should make scientifically valid workflows easy and invalid workflows difficult.

- Preprocessing, variable selection, and model tuning must have fit-time vs. apply-time semantics.
- Validation must know whether upstream operations were nested correctly.
- Full-dataset transformations before splitting or cross-validation should be visibly unsafe.
- These guardrails must apply equally whether the workflow is built by a human or assembled by an LLM agent. An agent that silently introduces leakage is worse than no agent at all.

### 4. Selection is central, not optional

In chemometrics, choosing the right samples and the right variables is often more important than choosing between adjacent algorithms.

- Sample partitioning and representative subset selection are first-class model-design operations.
- Feature and wavelength selection are first-class model-design operations.
- Selection steps must emit explicit masks or indices, not just transformed datasets.

### 5. Interpretation must be operational and machine-legible

Interpretability outputs should drive the next step in the workflow, not stop at a plot.

- VIP, loadings, selectivity metrics, leverage, residuals, and outlier diagnostics must be consumable by downstream nodes.
- Peak-derived regions should be able to become candidate variable sets.
- Model interpretation should support model design and deployment decisions.
- Interpretability artifacts must be structured for programmatic consumption, not just visual rendering. An LLM agent reasoning about "which wavelengths matter and why" needs typed, queryable diagnostics — not a matplotlib figure.

### 6. Auto must be transparent

"Auto" is acceptable only when the system explains what it chose and why.

- Every auto-decision must be inspectable.
- Heuristics must be documented and surfaced.
- Silent expert heuristics are bad UX and bad DX.
- When an LLM agent makes a modeling choice on behalf of a user, the same transparency requirement applies: the agent must surface what it chose, what alternatives existed, and why.

### 7. Artifacts must carry applicability, not just parameters

A saved model is not just coefficients and latent variables.

- Artifacts must carry axis identity, selected features, preprocessing chain, calibration domain, and failure conditions.
- Deployment should validate compatibility by meaning, not just shape.
- Feature-count checks alone are insufficient.

### 8. Progressive disclosure beats dual products

Good chemometrics software should not force a choice between novice usability and expert rigor.

- The UI should surface sane defaults first.
- Advanced controls should be available without overwhelming the basic path.
- The developer surface should follow the same pattern: simple defaults, precise extensibility.
- In a conversational interface, progressive disclosure requires explicit user modes, safe defaults, and assumption disclosure. An agent should ask or infer conservatively and never silently escalate complexity. The scientist remains in charge; the agent assists within the boundaries the platform defines.

### 9. Failure UX matters as much as success UX

The system should explain why a workflow is unsafe, unstable, or inapplicable.

- Spectral misalignment, extrapolation, rank deficiency, class imbalance, unstable selection, and poor calibration coverage should be surfaced explicitly.
- A chemometric platform should teach users when they are about to fool themselves.
- Scientifically consequential failures (leakage, extrapolation, rank deficiency, domain violations) must be structured data with typed schemas. Incidental UX warnings can remain human-readable strings. The distinction matters: schema bureaucracy for low-value messages is waste.

### 10. Every scientifically consequential abstraction must have a stable, typed, queryable contract

The chemometric core must be rigorous, typed, and auditable on its own terms. LLM agents, the GUI, Python export, and deployment all consume the same contract.

- Node signatures, parameter schemas, and valid connection types must be introspectable at runtime because scientific reproducibility demands it, not because an agent needs it.
- Diagnostics and interpretability outputs must have typed schemas, not just display methods, because structured diagnostics are better science.
- Workflow state must be queryable — "what preprocessing has been applied upstream of this node?" — because auditability requires it.
- A platform built this way is inherently consumable by LLM agents, but the design target is the science. Agents are volatile. Workflow contracts are durable.

## Anti-Patterns To Ban

- Hidden preprocessing state
- Manual interpretation that cannot be captured in workflow state
- Selection steps that do not emit masks or indices
- Validation that cannot tell whether selection and preprocessing were nested correctly
- Deployment compatibility checks based only on feature count
- GUI-only capability with no clean exported equivalent
- "Auto" behavior with no explanation
- Multiple overlapping nodes with inconsistent semantics for the same chemometric operation
- Interpretability outputs that exist only as plots with no structured backing data
- LLM agent actions that bypass leakage guards or skip transparency requirements

## SpectraSherpa Evaluation

### Current strengths

SpectraSherpa already has the right architectural center of gravity.

- The DAG workflow is the core execution model.
- `SherpaDataset` is already a strong canonical runtime container with feature axes, sample axes, target context, domain context, provenance, and quality state.
- Axes are typed and slice-aware.
- Model artifacts already have a formal persistence layer.
- The node system already supports consolidated nodes and declarative node authoring.

This means SpectraSherpa is not blocked by a missing foundation. It already has more structural integrity than many chemometrics tools.

### Current weaknesses

The current gaps are not basic infrastructure gaps. They are chemometric design gaps.

#### 1. Sample selection is still generic ML, not chemometrics

The existing split node supports random, stratified, and sequential splitting, but not representative-space partitioning such as Kennard-Stone or DUPLEX.

Impact:

- Calibration design is weaker than it should be.
- Users are pushed toward convenience splits rather than defensible X-space coverage.
- The platform does not yet encode a core chemometric judgment.

#### 2. Feature selection is manual or absent

Spectral region selection currently exists as generic clipping, and the region-selection template is based on that manual clipping step.

Impact:

- Wavelength selection is not a first-class capability.
- Peak-derived windows, VIP-derived masks, and interval-based selection are not represented cleanly.
- Interpretability outputs cannot yet drive model design in a closed loop.

#### 3. Feature selection needs a stable contract, not just discipline

Sample inclusion already has a home in `SampleAxis.include_mask`, but there is no equally strong canonical feature-selection contract.

Feature selection needs a stable, queryable contract that composes with preprocessing and supports deployment validation. The initial implementation may be artifact schema + provenance + explicit outputs; it can graduate to a first-class type in the registry if and when the pattern proves stable. Forcing a new typed registry object before the selection family exists risks over-engineering.

Impact:

- Variable selection risks becoming a chain of destructive column slicing operations.
- Provenance is present, but explicit reusable selection state is weak.
- Downstream deployment and artifact validation will remain underspecified.

#### 4. Leakage-safe model-design semantics are not yet enforced strongly enough

The architecture is good enough to support leakage-safe workflows, but the product does not yet make them unavoidable.

Impact:

- Future feature selection work could be implemented in a scientifically unsafe way if fit/apply semantics are not hardened.
- Validation currently emphasizes structural correctness more than chemometric nesting correctness.
- An LLM agent assembling a workflow has no programmatic way to verify leakage safety before execution.

#### 5. Artifacts need stronger applicability metadata

Artifacts have a strong storage layer, but long-term deployment safety requires more than storing arrays and manifests.

Impact:

- Future selected-wavelength models need axis-aware deployment checks.
- Applicability domain and preprocessing requirements are not yet formal enough.
- A model that works in development but silently produces garbage on a different instrument is the most damaging failure mode in practice.

#### 6. Batch effects and instrument transfer are absent

Calibration transfer, standardization (PDS, SBC, etc.), and batch-effect correction matter in industrial reality. However, this gap is secondary to selection and leakage-safe contracts. If the platform is not yet excellent for single-instrument, single-domain, scientifically valid workflows, multi-instrument transfer is premature.

Impact:

- Models built on one instrument cannot be safely deployed on another without manual intervention outside the platform.
- This gap will become more visible as artifact applicability contracts mature, but it should not compete with selection work for near-term attention.

## Priority Ranking

### Priority 1: Leakage-safe model-design contracts

Before adding a large family of selection algorithms, the platform should make the semantics of fit-time vs. apply-time explicit for:

- preprocessing
- sample selection
- feature selection
- validation

This is not a major rewrite. It is a contract-hardening step.

### Priority 2: First-class sample selection

Add a dedicated sample-selection node family with:

- random
- stratified
- sequential
- Kennard-Stone
- DUPLEX

Later: SPXY, grouped and batch-aware variants.

Sample selection is immediately valuable and mostly orthogonal to feature-axis deployment compatibility. It should not wait on a broader artifact redesign.

### Priority 3: First-class feature selection

Add a dedicated feature-selection family with a practical initial set:

- interval or region selection
- peak-window selection
- VIP-based selection
- coefficient-magnitude selection
- selectivity-ratio selection

Later:

- iPLS / biPLS / siPLS
- CARS
- SPA
- UVE / MC-UVE

### Priority 4: Stable feature-selection contract and artifact applicability

Feature selection needs a stable, queryable contract. The initial implementation should be artifact schema + provenance + explicit mask/index outputs. It can graduate to a first-class typed object in the registry if the pattern proves stable and the selection family demands it.

Artifact applicability becomes critical at this stage — once feature selection starts altering wavelength identity, artifacts must carry:

- feature-axis identity or fingerprint
- selected-feature mask or intervals
- preprocessing chain
- calibration domain summary
- compatibility rules for deployment

### Priority 5: Batch effects and calibration transfer

Add a calibration-transfer and standardization family:

- PDS (piecewise direct standardization)
- SBC (slope/bias correction)
- instrument-profile metadata on datasets and artifacts

This is not urgent for the selection layer, but it completes the story for deployment and multi-instrument use.

## Sequencing Recommendation

### Short answer

Yes, sample and feature selection are the right next step.

But they should not be built on top of loose contracts.

### Correct sequencing

Do not pause for a broad data-structure rewrite. The current data foundation is already good enough.

Instead, do this:

1. Harden fit/apply and selection contracts.
2. Implement sample selection as a first-class family.
3. Implement feature selection as a first-class family with a stable selection contract (artifact schema + provenance + explicit outputs initially; first-class type if needed later).
4. Harden artifact applicability once feature selection starts altering wavelength identity.
5. Address calibration transfer and batch effects once single-instrument workflows are excellent.

### What not to do

Do not spend a cycle rewriting `SherpaDataset` or the axis system in the abstract.

That would likely be architecture drift rather than progress. The existing data model is already strong enough to support the next chemometric layer.

### What to refine now, before or alongside selection work

These are the only structural refinements that should happen immediately:

- make selection outputs explicit as masks or indices
- formalize fit-time vs. apply-time semantics for selection-driven nodes
- define what a deployed model must know about selected features
- ensure node signatures, diagnostics, and selection state are introspectable

This is targeted refinement, not foundational rework.

## Recommendation

The next major product move should be:

**Selection as a first-class chemometric layer**

That means:

- sample selection
- feature selection
- leakage-safe validation of both
- artifact-level persistence of both
- stable, queryable contracts for both

If SpectraSherpa does this well, it will stop feeling like a spectral workflow builder with chemometric nodes and start feeling like a real chemometric operating system — one that a scientist can trust and a deployment pipeline can validate.
