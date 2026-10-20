# Where truth lives

Start here before changing a shared rule. Paths below are relative to the OSS
package root (the public repo root, or `packages/spectra-sherpa` upstream).
This map points to authorities; it does not replace them.

| Topic | Authority / consumer boundary | Enforcement |
| --- | --- | --- |
| Operations, ports and parameter admission | `src/spectra_sherpa/app/services/dag/node_base.py` and registered node metadata; frontend consumes the node library | `tests/test_node_catalog_contract.py` |
| Sample inclusion, labels and classes | `app/lib/axes.py` (`SampleAxis`), `app/lib/sherpa_dataset.py`; SDK helpers must use these, not `meta["samples"]` | `tests/test_sdk_sample_authority.py`, `tests/test_population_authority.py`, `tests/test_axis_semantics.py` |
| Observation identity versus display labels | `app/lib/sample_identity.py`; reuse typed sample-table `sample_id` and verified source-row receipts; no IDs invented by a renderer | `tests/test_scientific_identity_authority.py` |
| Independent specimens and cross-block validation | `core/specimen_independence.py`; My Dataset preview, starter admission and split execution share this rule | `tests/test_scientific_authority_rules.py`, `tests/test_canonical_train_test_split.py` |
| Scientific result meaning and coordinates | `app/services/dag/presentation_contract.py`; declared input-axis bindings, not Inspector node-name switches | `tests/test_presentation_contract.py`, `frontend/src/test/composables/scientific_plot_parity.test.ts` |
| Plot/table rendering | `frontend/src/utils/scientific-presentation-renderers.json`; shared projections for Inspector, detail and report | `frontend/src/test/utils/featureRulePresentation.test.ts`, `frontend/src/test/modals/QuickPlotModal.test.ts` |
| Scientific browser acceptance | [Acceptance journeys and lane boundaries](developers/scientific-browser-acceptance.md); original fixture oracles and retained canonical results | `frontend/e2e/scientific/`, explicit `frontend/e2e/provider/`; Data View and Quick Plot are independent gates |
| Run evaluation scope and units | Retained target/validation context; `core/target_units.py` resolves branch-scoped response units, `app/services/run_validation_summary.py` declares summary and row-level facts | `tests/test_run_validation_summary.py`, `tests/test_scientific_authority_rules.py`, `frontend/src/test/utils/scientificReportSummary.test.ts` |
| Method help and node help | `frontend/src/utils/documentation.ts` for curated method topics/base URL; node execution contract `help_reference` via `nodeHelp.ts` | `method_help.test.ts` (anchors), `node_help.test.ts` (contract URLs), under `frontend/src/test` |
| GUI layout and language | [GUI design](developers/gui-workspace-design.md), [result surfaces](developers/scientific-result-surface-contract.md), [glossary](concepts/glossary.md) | Component tests and Chrome acceptance; no claim of a complete prose/style lint gate yet |
| Interface colors and categorical plot palettes | `frontend/src/assets/tokens.css`, `frontend/src/theme/plotTheme.ts`; [theme migration boundary](developers/theme-authority.md) | `theme_authority.test.ts`, `npm run check:theme`; zero-literal baseline outside these authorities |
| Saved model compatibility and custody | `core/contract_compatibility.py`, `sdk/fitted_state_custody.py`; exact directional registrations, not wildcard compatibility | `tests/test_batch_contract_compatibility.py`, `tests/test_fitted_state_custody.py` |
| Standalone/upstream boundary | `OSS_SCOPE.md`, `scripts/run_public_tests.py`; private qualification evidence stays upstream | Public reference preflight and boundary checks in CI |
| REST transport and node reference projections | Backend response schemas and live node registry; [generation boundaries](developers/generated-contracts.md) | `make generate-check`, `tests/test_public_openapi_generation.py`, generated-reference tests |
| Saved diagnostic review facts | `app/services/diagnostic_review_summary.py`; private family projectors preserve retained scientific scope | `tests/test_diagnostic_review_summary.py`, `tests/test_plsda_diagnostic_summary.py` |
| Frontend extension host contract | `frontend/src/extension-contract/`; host and extension consume the same versioned declarations | Type checking and extension loading tests |

Python paths abbreviated to `app/`, `core/` or `sdk/` above are under
`src/spectra_sherpa/`. Unmigrated handwritten transport boundaries are not
authorities; generation does not authorize inventing scientific semantics for
untyped records.
