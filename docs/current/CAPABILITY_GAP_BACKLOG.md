# Capability Gap Backlog (Follow-Up)

Last updated: 2026-02-08
Source: static verification against `docs/current/CURRENT_CAPABILITIES.md`

## Priority 1 (Critical)

- [x] Enterprise graceful degradation/offline behavior does not match matrix claim.
  - Doc claim: `docs/current/CURRENT_CAPABILITIES.md:20`
  - Evidence: network health monitor runs only in hybrid mode.
  - Code refs: `src/spectra_sherpa/app/services/network_health.py:228`, `src/spectra_sherpa/app/services/network_health.py:229`, `src/spectra_sherpa/app/services/network_health.py:259`
  - Follow-up: either implement enterprise degradation path or revise docs to hybrid-only.
  - Resolution (2026-02-08): **Closed via documentation alignment**. Matrix now states enterprise is `Rate-limited cloud (no auto-fallback)` in `docs/current/CURRENT_CAPABILITIES.md:22`.

## Priority 2 (High)

- [x] Enterprise "tiered egress + audit" claim is not aligned with current remote audit implementation.
  - Doc claim: `docs/current/CURRENT_CAPABILITIES.md:19`
  - Evidence: remote audit handler is configured only in hybrid mode.
  - Code refs: `src/spectra_sherpa/app/core/logging.py:276`, `src/spectra_sherpa/app/core/logging.py:277`, `src/spectra_sherpa/app/api/v1/routes/logs.py:45`
  - Follow-up: decide whether enterprise should support remote audit. Implement or update matrix wording.
  - Resolution (2026-02-08): **Closed via documentation alignment**. Matrix now differentiates `Hybrid: tiered egress + remote audit` vs `Enterprise: tiered egress (local audit only)` at `docs/current/CURRENT_CAPABILITIES.md:21`.

- [x] "Implemented and tested across local/hybrid/enterprise" is overstated vs current visible test coverage.
  - Doc claim: `docs/current/CURRENT_CAPABILITIES.md:3`, `docs/current/CURRENT_CAPABILITIES.md:4`
  - Current tests are narrow (experiments CRUD, selected modeling nodes, one hybrid gateway key path).
  - Code refs: `tests/test_experiments.py:13`, `tests/test_modeling_nodes.py:35`, `tests/test_gateway_user_api_key.py:14`, `tests/test_data_loading_golden.py:70`
  - Follow-up: add mode-matrix tests and capability-specific tests before claiming cross-mode validation.
  - Resolution (2026-02-08): **Closed via documentation alignment**. Intro and `Testing Status` section now explicitly describe limited hybrid/enterprise automated coverage (`docs/current/CURRENT_CAPABILITIES.md:3`, `docs/current/CURRENT_CAPABILITIES.md:157`).

## Priority 3 (Medium)

- [ ] Rate-limit response header behavior is inconsistent with doc wording.
  - Doc claim: `docs/current/CURRENT_CAPABILITIES.md:85`
  - Evidence: `X-RateLimit-*` headers set in execution middleware path, but not in LLM/NIST endpoints.
  - Code refs: `src/spectra_sherpa/app/core/enterprise_enforcement.py:116`, `src/spectra_sherpa/app/core/enterprise_enforcement.py:117`, `src/spectra_sherpa/app/api/v1/routes/llm.py:42`, `src/spectra_sherpa/app/api/v1/routes/nist.py:44`
  - Follow-up: standardize response headers across all rate-limited endpoints, or narrow doc language.

- [ ] Feature-flag source-of-truth claim is stricter than current frontend behavior.
  - Doc claim: `docs/current/CURRENT_CAPABILITIES.md:142`, `docs/current/CURRENT_CAPABILITIES.md:146`
  - Evidence: frontend applies hardcoded fallback config when `/config` load fails.
  - Code refs: `frontend/src/composables/useAppConfig.ts:33`, `frontend/src/composables/useAppConfig.ts:94`
  - Follow-up: centralize fallback semantics with explicit backend contract and enforce use of `isFeatureEnabled`.

## Priority 4 (Low)

- [ ] Template systems are intentionally not unified yet (documented), but drift risk remains.
  - Doc note: `docs/current/CURRENT_CAPABILITIES.md:121`, `docs/current/CURRENT_CAPABILITIES.md:125`
  - Evidence: backend seeded templates and frontend hardcoded templates are maintained separately.
  - Code refs: `src/spectra_sherpa/app/core/workflow_templates.py:7`, `frontend/src/stores/workflow.ts:437`
  - Follow-up: pick canonical source (API-backed templates recommended) and migrate UI.

## Validation Notes

- Runtime tests were not executed in this environment because required test tooling/deps were missing at verification time.
  - `pytest` not found.
  - `python3 -m pytest` failed due to missing module `httpx`.

## Suggested Follow-Up Order

1. Resolve remaining Priority 3 items (rate-limit contract, feature-flag contract).
2. Add test coverage proving local/hybrid/enterprise behavior for matrix-listed features.
3. Unify template source when product workflow allows.
