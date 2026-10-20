# Where truth lives

Start here before changing a shared rule. Paths below are relative to the OSS
package root (the public repo root, or `packages/spectra-sherpa` upstream).
This map points to authorities; it does not replace them.

| Topic | Owning implementation / schema | Normative document | Enforcing tests / checks | Consumers |
| --- | --- | --- | --- | --- |
| Operations, ports and parameters | `app/services/dag/node_base.py`, registered node metadata | [Workflow architecture](architecture/workflows.md) | `tests/test_node_catalog_contract.py` | Execution, node library, generated reference |
| Sample inclusion, labels and classes | `app/lib/axes.py`, `app/lib/sherpa_dataset.py` | [Dataset contract](architecture/sherpa-dataset.md) | `tests/test_sdk_sample_authority.py`, `tests/test_population_authority.py`, `tests/test_axis_semantics.py` | SDK helpers, curation, nodes; never a parallel metadata mask |
| Observation identity | `app/lib/sample_identity.py`, typed sample-table `sample_id` | [Dataset contract](architecture/sherpa-dataset.md) | `tests/test_scientific_identity_authority.py` | Assembly, slicing, application, result labels |
| Specimen independence | `core/specimen_independence.py` | [Validation](chemometrics/validation-application.md) | `tests/test_scientific_authority_rules.py`, `tests/test_canonical_train_test_split.py` | My Dataset, starter admission, split execution |
| Scientific result meaning and coordinates | `app/services/dag/presentation_contract.py` | [Result surfaces](developers/scientific-result-surface-contract.md) | `tests/test_presentation_contract.py`, `frontend/src/test/composables/scientific_plot_parity.test.ts` | Inspector, detail, reports; declared axis bindings |
| Plot/table rendering | `frontend/src/utils/scientific-presentation-renderers.json` | [Result surfaces](developers/scientific-result-surface-contract.md) | `frontend/src/test/utils/featureRulePresentation.test.ts`, `frontend/src/test/modals/QuickPlotModal.test.ts` | Shared result projections |
| Browser acceptance | `frontend/e2e/scientific/`, `frontend/e2e/provider/` | [Journeys and lane boundaries](developers/scientific-browser-acceptance.md) | Independent Data View, Quick Plot, CSV and report assertions | PR smoke, broader qualification; provider lane stays separate |
| Evaluation scope and units | `core/target_units.py`, `app/services/run_validation_summary.py` | [Validation](chemometrics/validation-application.md) | `tests/test_run_validation_summary.py`, `tests/test_scientific_authority_rules.py`, `frontend/src/test/utils/scientificReportSummary.test.ts` | Retained branch projections, reports |
| Method and node help | `frontend/src/utils/documentation.ts`, contract `help_reference` | [Generation boundaries](developers/generated-contracts.md) | `scripts/check_built_help.py`, `frontend/src/test/components/method_help.test.ts`, `frontend/src/test/utils/node_help.test.ts` | MethodHelp, nodeHelp, built docs |
| GUI layout | Shared workspace and result components | [GUI design](developers/gui-workspace-design.md), [result surfaces](developers/scientific-result-surface-contract.md) | Component tests and Chrome acceptance | Data, Workflow, Runs, Report |
| Workspace request ownership | `frontend/src/composables/useScopedRequest.ts`, `frontend/src/stores/projectScopeRegistry.ts` | [Scoped state](developers/scoped-workspace-state.md) | `scopedRequest.test.ts`, `scoped_requests.test.ts`, `e2e/scientific/scoped-workspace.spec.ts` | Data pipes, Inspector, project stores, retained run inspection |
| Product terminology | [Glossary](concepts/glossary.md), bounded rules in `scripts/check_user_copy.py` | [Governance scope](developers/repository-governance.md) | `tests/test_repository_governance.py`, `python scripts/check_user_copy.py` | Static Vue copy and workflow guides, not scientific identifiers |
| Colors and palettes | `frontend/src/assets/tokens.css`, `frontend/src/theme/plotTheme.ts` | [Theme boundary](developers/theme-authority.md) | `theme_authority.test.ts`, `npm run check:theme` | Screen, downloads, reports; legacy colors explicitly scoped |
| Saved model compatibility and custody | `core/contract_compatibility.py`, `sdk/fitted_state_custody.py` | [Model artifacts](architecture/model-artifacts.md) | `tests/test_batch_contract_compatibility.py`, `tests/test_fitted_state_custody.py` | Saved models and application; directional registrations |
| Standalone/upstream boundary | `scripts/run_public_tests.py`, public reference preflight | `OSS_SCOPE.md` at package root | Public test-profile and reference preflight in CI | Public package and upstream qualification |
| REST and node reference projections | Backend response schemas, live node registry | [Generation boundaries](developers/generated-contracts.md) | `make generate-check`, `tests/test_public_openapi_generation.py`, `tests/test_generated_reference.py` | Generated transport types, explicit view adapters, docs tables |
| Saved diagnostic facts | `app/services/diagnostic_review_summary.py` | [Result surfaces](developers/scientific-result-surface-contract.md) | `tests/test_diagnostic_review_summary.py`, `tests/test_plsda_diagnostic_summary.py` | PCA/PLS/PLS-DA retained review; no new diagnostics implied |
| Extension host contract | `frontend/src/extension-contract/` | [Generation boundaries](developers/generated-contracts.md) | Type checking and extension loading tests | OSS host and separately built extensions |
| Evidence and two-repo changes | Existing generators, source/dependency digests and semantic tests | [Repository governance](developers/repository-governance.md) | `make evidence-check`; upstream publication guard and qualification checks | Contributors, agents, reviewers; generation is not qualification |

Python paths abbreviated to `app/`, `core/` or `sdk/` above are under
`src/spectra_sherpa/`. Unmigrated handwritten transport boundaries are not
authorities; generation does not authorize inventing scientific semantics for
untyped records.
