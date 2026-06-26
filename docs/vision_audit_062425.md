# Spectra Sherpa Vision And Current Status Audit

Date: 2026-06-24

This memo captures the agreed product vision for Spectra Sherpa and audits the current mono repo implementation against that vision. It intentionally does not include the commercial chemometrics software integration strategy, which should wait until partner feasibility is verified.

## Executive Summary

Spectra Scientific should position Spectra Sherpa as the UV/VIS/NIR spectroscopy platform and AI company for trusted spectral workflows. The strongest wedge is not "another chemometrics workbench." The wedge is a trust layer for spectroscopy: scientifically meaningful data handling, reviewable workflow provenance, reproducible computation, defensible reporting, and AI assistance that reduces expert burden without pretending to replace scientific judgment.

The agreed strategy has three connected pillars:

1. Win trust in spectroscopy.
2. Add AI where it reduces expert burden.
3. Move upward into regulated model lifecycle and PAT.

The product promise is:

> Sherpa keeps spectral data scientifically meaningful from the moment it enters the system.

The value statement is:

> For spectroscopy teams in pharma, PAT, analytical development, process monitoring, materials, food, chemicals, and instrument OEMs, Spectra Sherpa helps teams convert UV/VIS/NIR spectral data into reproducible, reviewable, AI-assisted scientific decisions, while preserving metadata, provenance, validation history, and model context from raw file through report and deployment.

## Market View

The relevant serviceable available market excludes hardware and focuses on software and AI-enabled workflow spend around UV/VIS/NIR spectroscopy: chemometrics, PAT/model lifecycle, lab data workflows, validation/reporting, scientific AI assistance, and OEM software enablement.

Working SAM estimate, no hardware:

| Segment | Approximate annual SAM |
| --- | ---: |
| Spectroscopy chemometrics workbench | $150M-$350M |
| Analytical lab workflow and data provenance | $250M-$600M |
| PAT, QbD, and model lifecycle | $300M-$800M |
| AI assistant, review, guidance, and training layer | $100M-$300M |
| OEM, embedded, and API licensing | $100M-$200M |

Near-term practical SAM is approximately $0.9B-$2.2B globally. A conservative entry view is $600M-$1.0B. A more aggressive view is $2.5B-$4B if Sherpa becomes a spectroscopy data and workflow control layer across analytical and process labs.

The largest opportunity is not the desktop workbench alone. The larger, stickier business is the trusted spectral data layer plus validated model lifecycle around regulated and production-facing spectroscopy.

## Strategic Pillar 1: Win Trust In Spectroscopy

This is the foundation. Sherpa should be best-in-class at:

- Metadata extraction and preservation.
- Axis and unit handling.
- Data import inspection before committing to My Dataset.
- Provenance tracking from raw file to dataset to workflow to run to report.
- Versioned workflows and immutable runs.
- Validation summaries and defensible report packs.
- Export to Python/Jupyter for transparent computation.
- Human-editable dataset metadata without silent guessing.

This is where trust is earned. It also creates the structured data and context that later AI needs.

The strategic rule is: do not guess scientific meaning when the source data does not support it. If axis quantity, axis units, target meaning, sample semantics, or instrument metadata are present in source metadata, preserve them. If they are not available, leave fields blank for user review in My Dataset. If an axis is an index, say it is an index.

## Strategic Pillar 2: Add AI Where It Reduces Expert Burden

AI should not be sold as a black-box scientist. It should be sold as a scientific reviewer and co-pilot.

High-trust AI use cases:

- Explain PCA, PLS, SIMCA, and MCR outputs.
- Identify missing validation steps.
- Flag suspicious preprocessing choices.
- Compare model versions.
- Draft methods and results sections for reports.
- Summarize datasets and workflow provenance.
- Suggest next checks, not silently execute them.
- Help junior users understand why a workflow is or is not defensible.
- Answer questions using project context, run history, dataset metadata, and user-approved context.

The key design principle is:

> Every AI statement should be grounded in a dataset, workflow, run, model, citation, or user-approved context.

AI becomes valuable because it reduces the time senior scientists spend on review, documentation, interpretation, and training. This is more believable than claiming AI replaces chemometricians.

The trust ladder should be:

1. Summarize and explain.
2. Audit and flag.
3. Recommend next checks.
4. Draft reviewable report content.
5. Execute bounded actions only with explicit user approval and traceable context.

## Strategic Pillar 3: Move Upward Into Regulated Model Lifecycle And PAT

Once Sherpa owns trusted spectral data and reproducible workflows, the natural expansion is model lifecycle.

Capabilities to build toward:

- Model registry for PLS, SIMCA, classification, and calibration models.
- Calibration transfer workflows.
- Instrument-to-instrument comparability.
- Batch and run monitoring.
- Drift detection.
- Validation packs.
- Human approval gates.
- Change history.
- Model deployment records.
- PAT historian, MES, LIMS, and ELN integration.
- Review-ready audit trails.

This is where the business gets larger and stickier. A lab workbench can be replaced. A validated model lifecycle system tied into quality workflows is much harder to remove.

## Competitive Position

Sherpa should avoid a head-on "better algorithm library" competition with established chemometrics tools. Entrenched tools have years of user trust, training material, validated methods, and institutional familiarity.

Sherpa's stronger competitive position is:

> The open, auditable, AI-ready workflow layer for spectral science.

The workbench is the visible entry point. The defensible product is the trusted workflow, provenance, validation, reporting, and lifecycle layer around spectroscopy.

Key differentiation:

- Local-first and open-source core.
- Transparent computation and Python/Jupyter export.
- Explicit metadata, axis, unit, and provenance handling.
- Reviewable workflow versions and immutable execution runs.
- Human-editable dataset metadata instead of silent semantic guessing.
- AI grounded in project artifacts rather than generic chat.
- Path from desktop exploration to regulated model lifecycle and PAT.

## Customer Challenges And Guidance

### Entrenched Chemometrics Players

The challenge is real. Established players are embedded in training, consulting, and regulated customer habits. Sherpa should leave academic footprints and community trust, but should not rely only on replacing existing workbenches.

Best wedge:

- Teaching and reproducibility datasets.
- Transparent workflow export.
- Import inspection and metadata correctness.
- Validation/report packs.
- AI review and explanation.
- Open architecture for labs and instrument makers.

### Diverse Lab Needs

Labs are diverse, and generic lab informatics scope can dilute Sherpa. The near-term beachheads should stay spectroscopy-centered:

- NIR calibration and calibration transfer.
- Pharma PAT, blend uniformity, moisture, identity, and process monitoring.
- UV/VIS assay and reaction monitoring.
- Raman/FTIR identity and library workflows.
- Teaching, reproducibility, and defensible workflow review.

For hyperspectral imaging, Sherpa can first support spectra, derived spectral tables, regions of interest, and extracted feature matrices. Full image-cube analysis should not become the immediate core unless a customer opportunity justifies the R&D.

### Finding Connections

Most useful networks:

- Academic chemometrics and spectroscopy groups.
- PAT and QbD pharma communities.
- NIR spectroscopy societies.
- ASTM, USP, ICH-adjacent quality and validation circles.
- CDMOs, CRO analytical development teams, and process analytical teams.
- Instrument application scientists.
- Process spectroscopy consultants.
- Training communities around chemometrics, NIR, and PAT.

Useful conference and community targets include IFPAC, FACSS SciX, Pittcon, NIR-focused meetings, AAPS, and ISPE.

### AI Trust, Margin, And R&D

Trust is the product. AI should start in deterministic, reviewable support roles:

- Summarize.
- Explain.
- Audit.
- Flag.
- Recommend.
- Draft reviewable text.

Do not lead with autonomous science. Lead with reduced review burden and better documentation. Keep deterministic computation separate from AI commentary, and attach AI outputs to the dataset, workflow, run, model, citation, or user-approved context they used.

### OEM Sales Cycles

OEM interest is valuable but slow. Treat OEM as a parallel track, not the only go-to-market path.

Sell modular pieces that solve immediate pain:

- Metadata extractor and import inspection.
- Workflow and provenance engine.
- Report and validation pack generator.
- Calibration transfer or comparability module.
- White-label or embedded Sherpa Lite.
- Advisor/reviewer layer.
- Conversion and export utilities.

## Adjacent Scientific Software Opportunities

The next three adjacent opportunities for AI-enabled scientific software are:

1. Analytical chemistry AI workbench.
   - LC, GC, HPLC/UPLC, MS-adjacent review workflows, impurity/stability reasoning, and method review.
   - Do not initially replace Empower or Chromeleon. Be the review, interpretation, validation, and documentation layer above them.

2. AI-native scientific data cloud for instrument data.
   - Raw instrument files, spectra, chromatograms, assays, sample context, methods, calibration models, reports, deviations, and decisions.
   - The opportunity is a structured scientific context layer across instruments and workflows.

3. Formulation, materials, and process optimization AI.
   - DOE, Bayesian optimization, and spectral analytics for formulations, polymers, food, coatings, personal care, pharma excipients, catalysis, and specialty chemicals.
   - This becomes stronger after Sherpa has trusted data, provenance, and model lifecycle infrastructure.

## Current Mono Repo Status

Overall assessment:

| Pillar | Current score | Readiness |
| --- | ---: | --- |
| Win trust in spectroscopy | 7.5/10 | Strong foundation, with important validation/reporting gaps. |
| Add AI where it reduces expert burden | 4.5/10 | Good contracts and tool surfaces, but full Advisor intelligence is outside the OSS core. |
| Regulated model lifecycle and PAT | 4/10 | Model artifacts, deployment flags, batch/folder-watch paths, and audit scaffolding exist, but full lifecycle governance is not yet built. |

This assessment is based on the current package state and durable repo structures, not on unmerged commercial partner assumptions.

### Evidence In Repo

Trust foundation:

- `README.md` positions Sherpa as an open chemometrics workbench with reproducible/versioned runs, provenance, export, model artifacts, local-first execution, and denied local-mode egress.
- `src/spectra_sherpa/app/lib/sherpa_dataset.py` defines `SherpaDataset` around typed fields, first-class provenance, domain-aware axes, artifact handles, and fingerprinting.
- `src/spectra_sherpa/app/lib/sherpa_dataset.py` separates `InferredDomain` from authoritative `DomainContext`, preserving the distinction between heuristic hints and user/catalog assertions.
- `src/spectra_sherpa/app/lib/sherpa_dataset.py` defines immutable provenance entries and an append-only provenance log.
- `src/spectra_sherpa/app/lib/io.py` includes `inspect_csv_import_plan`, which previews CSV layout, roles, axis evidence, target candidates, warnings, and shape before commit.
- `src/spectra_sherpa/app/lib/io.py` now explicitly avoids treating numeric headers alone as proof of spectral axis quantity or units.
- `src/spectra_sherpa/app/models/execution_run.py` stores workflow version, parameter snapshot, results summary, diagnostics, node statuses, integrity hash, source metadata, model IDs, run kind, and idempotency key.
- `src/spectra_sherpa/app/models/audit_event.py` establishes append-only audit event schema and a managed-deployment audit-chain contract for ISO 17025 readiness.

AI foundation:

- `src/spectra_sherpa/app/contracts/ai_provider.py` defines the AI provider contract for workflow sync, decisions, peak identification, code generation, report writing, data stories, chat, and tool chat.
- Workflow validation tooling exists in the service layer and gives Sherpa a deterministic substrate for AI review.
- The README frames the commercial Sherpa Advisor and Guidance layers as built on top of the deterministic core.

Model lifecycle foundation:

- `src/spectra_sherpa/app/models/model_artifact.py` stores trained model artifacts with project, workflow, workflow version, source run, training dataset, integrity hash, feature axis, metrics, training data hash, preprocessing summary, lifecycle flags, and tags.
- Existing node coverage includes calibration transfer, validation/deployment-related nodes, batch prediction, and deploy-readiness concepts.
- Execution runs and audit events give the model lifecycle pillar a starting record layer.

## Feature Audit Against The Vision

| Capability | Current status | Notes |
| --- | --- | --- |
| Metadata extraction and preservation | Medium-strong | Core data structures support it. Needs broader real-world file corpus coverage and source-specific metadata extraction hardening. |
| Axis and unit handling | Strong | Recent cleanup aligns with no silent guessing. Continue enforcing metadata-first extraction and blank-if-unknown behavior. |
| Import inspection before My Dataset | Strong | CSV plan inspection and UI previews support review before commit. Extend the same rigor across all import/synthesis/upload/library paths. |
| Provenance raw file to dataset to workflow to report | Medium-strong | Dataset, workflow, run, and audit pieces exist. Report-level provenance should become more formal and inspectable. |
| Versioned workflows | Strong | Central to the product and already represented as a core concept. |
| Immutable runs | Medium-strong | ExecutionRun stores snapshots and hashes. Enforcement should stay strict at route and UI layers. |
| Validation summaries and report packs | Medium | Reporting exists, but defensible validation packs should become a first-class product surface. |
| Python/Jupyter export | Strong | This is a major trust differentiator and should remain visible in the product story. |
| Human-editable dataset metadata | Medium | The principle is right. Next step is auditable metadata edits with change reason and reviewer visibility. |
| AI explanations and review | Medium-low in OSS | Contracts exist, but value depends on grounded commercial Advisor implementation and artifact-linked outputs. |
| Missing validation step checks | Medium | Workflow validation is a good base. Needs domain-aware scientific review rules. |
| Report drafting | Medium-low in OSS | Provider contract supports it. Needs grounded, citation-aware, reviewable output artifacts. |
| Model registry | Medium-strong | ModelArtifact is a good foundation. Needs lifecycle states and approval records. |
| Calibration transfer | Medium | Present as workflow capability. Needs production comparability workflow and validation packaging. |
| Batch/run monitoring | Medium | Batch/folder-watch paths and run records exist. Needs monitoring dashboards and lifecycle metrics. |
| Drift detection | Gap | Important for PAT/model lifecycle expansion. |
| Human approval gates | Gap-medium | Deploy-ready flags exist. Formal approval workflow is not yet visible as a complete lifecycle system. |
| PAT/LIMS/MES/ELN integration | Gap | Strategic future pillar, not yet first-class in the product. |
| Review-ready audit trails | Medium | Audit schema is promising. Needs user-facing export, verification, and reviewer workflows. |

## Priority Roadmap

### Near Term: Make Trust Visible

1. Finish metadata and axis/unit discipline across Import, Synthesis, Upload, and Library.
2. Preserve all source-provided metadata and leave unknown scientific fields blank.
3. Make My Dataset the explicit user review and overwrite point.
4. Add auditable metadata edit history: who changed what, when, why, and from which source value.
5. Make import inspection consistent across raw files, CSV, synthetic/reference data, uploaded data, and library pulls.

### Next: Package Review And Validation

1. Create first-class validation summary objects.
2. Generate defensible report packs from dataset, workflow, run, model, validation metrics, warnings, provenance, and citations.
3. Add reviewer views for preprocessing choices, validation omissions, target leakage risks, sample/axis inconsistencies, and model comparison.
4. Ensure every report section traces back to exact artifacts.

### Then: Grounded AI Reviewer

1. Store AI review outputs as artifacts linked to dataset, workflow, run, model, and report.
2. Require AI outputs to cite the project artifacts and source context used.
3. Start with explanation, missing-check detection, report drafting, and version comparison.
4. Make recommendations reviewable and non-executing by default.

### Expansion: Model Lifecycle And PAT

1. Extend model artifacts into a model registry with lifecycle states.
2. Add approval gates, approved-use scope, reviewer identity, and change reason.
3. Add calibration transfer validation packages.
4. Add deployed model monitoring, drift detection, and batch performance summaries.
5. Build connector strategy for PAT historians, MES, LIMS, and ELN systems after the core lifecycle records are stable.

## Product Principle

Sherpa should earn the right to add AI by first earning trust in spectral data. That means the product should be strict about scientific meaning, generous about preserving source metadata, transparent about uncertainty, and explicit about user review.

The winning sequence is:

1. Win trust in spectroscopy with metadata, provenance, validation, reporting, and transparent computation.
2. Add AI where it reduces expert burden in review, explanation, method checks, comparison, and report drafting.
3. Move upward into regulated model lifecycle and PAT, where trusted data and reproducible workflows become sticky infrastructure.
