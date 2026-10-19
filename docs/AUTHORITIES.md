# Where truth lives

Start here before changing a shared rule. Paths below are relative to the OSS
package root (the public repo root, or `packages/spectra-sherpa` upstream).
This map points to authorities; it does not replace them.

| Topic | Authority / consumer boundary | Enforcement |
| --- | --- | --- |
| Operations, ports and parameter admission | `src/spectra_sherpa/app/services/dag/node_base.py` and registered node metadata; frontend consumes the node library | `tests/test_node_catalog_contract.py` |
| Sample inclusion, labels and classes | `app/lib/axes.py` (`SampleAxis`), `app/lib/sherpa_dataset.py`; SDK helpers must use these, not `meta["samples"]` | `tests/test_sdk_sample_authority.py`, `tests/test_population_authority.py`, `tests/test_axis_semantics.py` |
| Scientific result meaning and coordinates | `app/services/dag/presentation_contract.py`; declared input-axis bindings, not Inspector node-name switches | `tests/test_presentation_contract.py`, `frontend/src/test/composables/scientific_plot_parity.test.ts` |
| Plot/table rendering | `frontend/src/utils/scientific-presentation-renderers.json`; shared projections for Inspector, detail and report | `frontend/src/test/utils/featureRulePresentation.test.ts`, `frontend/src/test/modals/QuickPlotModal.test.ts` |
| Run evaluation scope and units | Retained target/validation context, `app/services/run_validation_summary.py`; presentation labels in `frontend/src/utils/scientificMetricRows.ts` | `tests/test_run_validation_summary.py`, `frontend/src/test/utils/scientificMetricRows.test.ts` |
| Method help and node help | `frontend/src/utils/documentation.ts` for curated method topics/base URL; node execution contract `help_reference` via `nodeHelp.ts` | `method_help.test.ts` (anchors), `node_help.test.ts` (contract URLs), under `frontend/src/test` |
| GUI layout and language | [GUI design](developers/gui-workspace-design.md), [result surfaces](developers/scientific-result-surface-contract.md), [glossary](concepts/glossary.md) | Component tests and Chrome acceptance; no claim of a complete prose/style lint gate yet |
| Saved model compatibility and custody | `core/contract_compatibility.py`, `sdk/fitted_state_custody.py`; exact directional registrations, not wildcard compatibility | `tests/test_batch_contract_compatibility.py`, `tests/test_fitted_state_custody.py` |
| Standalone/upstream boundary | `OSS_SCOPE.md`, `scripts/run_public_tests.py`; private qualification evidence stays upstream | Public reference preflight and boundary checks in CI |

Python paths abbreviated to `app/`, `core/` or `sdk/` above are under
`src/spectra_sherpa/`. The main REST types, design tokens and generated node
documentation still need the planned follow-on cohesion work; do not treat
handwritten mirrors as newly authoritative because they appear in this map.
