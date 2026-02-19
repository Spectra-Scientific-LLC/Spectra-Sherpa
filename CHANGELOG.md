# Changelog

All notable changes to SpectraSherpa are documented in this file.

## [1.4.0] - 2026-02-18

### Sherpa AI Advisor Integration

SpectraSherpa now supports cloud-powered AI features through the Sherpa AI Advisor,
available via subscription in hybrid and enterprise modes. The OSS core remains fully
functional in local mode without any cloud dependencies.

#### Added

- **Sherpa AI Advisor proxy** — Cloud client (`sherpa_advisor.py`) that forwards
  requests to the SpectraSherpa server for AI-powered analysis. Includes workflow
  sync, follow-up chat, and streaming responses.
- **Subscription-gated features** via WebSocket proxy:
  - Peak identification (`sherpa_identify_peaks`)
  - Code generation (`sherpa_generate_code`)
  - Report narrative writing (`sherpa_write_report`)
  - Agentic chat with tool use (`sherpa_chat_with_tools`)
- **Feature flag system** — Server-sourced subscription entitlements drive frontend
  UI visibility. Free tier shows BYOK chat; paid features appear only with active
  subscription.
- **Upgrade prompts** — `SherpaUpgradeModal` component with feature-specific
  messaging and plan selection, driven by `useSherpaUpgrade` composable.
- **Demo mode** — Production-ready demo profile (`SITE_PROFILE=demo`) with:
  - Configurable execution limits (default: 25 per session)
  - Configurable Sherpa interaction limits (default: 20 per session)
  - `DemoBanner` component with real-time quota display and severity indicators
  - `DemoUpgradeModal` with plan chips and upgrade URL
  - File-backed rate limiting for multi-process consistency
  - API interceptor handles 429 responses and updates quota counters
- **DAG context tiering** — `EgressTier` (structure / summaries / full) controls
  how much workflow data is sent to the cloud Sherpa, respecting user privacy
  preferences.
- **Report page** — Assemble, preview, and export analysis reports as HTML,
  Markdown, or JSON. AI narrative section available with Sherpa subscription.
- **Agentic tools toggle** — Chat panel supports tool-augmented Sherpa responses
  with real-time tool execution status display.

#### Changed

- **Privacy controls** — `ensure_egress_defaults()` is now mode-aware. Hybrid mode
  enables cloud sync by default for new users; existing opt-outs are respected.
  Hybrid activation no longer force-enables cloud sync.
- **LLM chat** — `chatAssistant` feature flag depends solely on BYOK key presence,
  cleanly separated from subscription features.
- **WebSocket handlers** — All Sherpa proxy handlers use shared `_sherpa_proxy_preamble`
  for permission checks, demo limit enforcement, and availability verification.
  Error responses from the advisor are properly routed to `_error` message types
  instead of being emitted as false successes.

#### Removed

- **Local Sherpa Engine** — The bundled `SherpaEngine` (local LLM agent) has been
  completely removed. All AI-powered analysis now routes through the cloud proxy.
  Zero references to `SherpaEngine`, `sherpa_engine.py`, or `SHERPA_ENGINE_API_KEY`
  remain in the codebase.
- **Local report narrative fallback** — The `/llm/data-story` fallback for report
  generation has been removed. Report narratives are now exclusively a paid feature
  via the Sherpa cloud proxy.

#### Security

- Per-user egress permissions enforced for all cloud-bound requests
- Subscription entitlements validated server-side (not trusting client claims)
- Demo limits use file-backed rate limiters resistant to session manipulation
- No cloud URLs are contacted in local mode

### OSS Health

The open-source distribution is fully functional without cloud connectivity:

- All cloud module imports are lazy (inside functions, not at module level)
- `SherpaAdvisorService.is_available` returns `False` in local mode
- All advisor methods return safe defaults when unavailable
- Frontend feature flags default to `false` for missing features
- `httpx` remains a core dependency (used for multiple purposes beyond Sherpa)
- 712 backend tests pass; 0 frontend TypeScript errors

## [1.3.0] - 2026-02-14

### Added

- Penalized least-squares baselines (Whittaker, ALS, arPLS)
- New smoothing methods (Savitzky-Golay, moving average, Gaussian)
- Parallelism support for batch processing
- My Dataset node redesigned to load all files as a merged portfolio

### Changed

- Documentation site launched at docs.spectrascientific.ai
- Demo experience with sidebar docs links and user menu integration

### Removed

- Dead code and ad-hoc scripts cleaned up

## [1.2.0] - 2026-02-10

Initial OSS release under AGPL-3.0.
