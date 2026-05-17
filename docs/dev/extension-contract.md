# Extension Contract Surface

Spectra Sherpa (this OSS package) is designed to run **fully standalone**.
Commercial / proprietary capabilities attach through a small, stable
**injection contract** rather than by modifying OSS code. This page is
the single reference for that surface.

The guiding rule: **the OSS tree should not change shape when a
proprietary internal changes.** Extensions register implementations at
startup; OSS only ever *reads* the contract. If you find yourself
editing OSS source to accommodate an extension, the contract is missing
something — extend the contract, don't fork the behaviour.

All symbols below are exported from the package
`spectra_sherpa.app.contracts` (`src/spectra_sherpa/app/contracts/__init__.py`).
OSS never imports the server; the server is never required for OSS to
boot (enforced by the `Boundary Check` CI workflow).

## How injection works

A server/extension package, in its own startup hook, calls the
`set_*` / `register_*` functions. OSS calls the matching `get_*`
accessor on every request and falls back to a safe default when nothing
is registered. There is no import probe and no optional `try/except
ImportError` on the server package anywhere in OSS.

## Contracts

| Area | Inject with | OSS reads with | OSS default |
|---|---|---|---|
| AI advisor (chat, peak ID, code gen, reports, data story) | `set_sherpa_advisor()` | `get_sherpa_advisor()` | `DisabledAIProvider` (feature-disabled stub) |
| AI exception contract | (raised by impl) | catch `SherpaAdvisorUnavailable` / `SherpaAuthorizationError` / `SubscriptionRequiredError` | n/a |
| User API-key auth | `set_extra_user_api_key_authenticator()` | request auth path | none (local trust) |
| Bearer/JWT subject | `set_extra_bearer_token_resolver()` | WS auth path | none |
| Admin check | `set_extra_admin_resolver()` | `is_admin_user()` | `False` |
| Auth policy flags | `set_registration_enabled()` / `set_registration_requires_code()` | `registration_enabled()` / `registration_requires_code()` | `False` |
| Config overlay (entitlements) | `set_config_overlay_provider()` | `get_config_overlay_provider()` | `None` (no overlay) |
| LLM system-key resolver | `set_extra_key_resolver()` | `get_extra_key_resolver()` | `None` |
| **LLM provider catalog** | `set_llm_provider_catalog()` | `get_llm_provider_catalog()` | static OSS catalog (byte-identical to historical defaults) |
| Public (unauthenticated) paths | `register_public_paths()` | `get_public_paths()` | OSS base path set |
| Demo policy / quota | `set_demo_policy_provider()` / `set_demo_execution_quota_provider()` | `get_demo_policy()` / quota helper | unrestricted |
| WebSocket actions | `WebSocketActionRegistry.register(...)` via an app registrar | dispatch in the WS endpoint | core actions only |

## Stability rules for contract authors

1. **Read-only on the OSS side.** OSS calls accessors; it never inspects
   an implementation's internals or type beyond the declared Protocol /
   dataclass.
2. **Safe defaults.** Every contract returns a benign value when nothing
   is injected, so OSS-only installs run unchanged.
3. **Add, don't reshape.** Extend a Protocol/dataclass with new optional
   members; do not change existing member shapes. Changing a shape is a
   breaking contract change and must be versioned, not slipped in.
4. **Exceptions are part of the contract.** The `AIServiceProvider`
   (`src/spectra_sherpa/app/contracts/ai_provider.py`)
   exception list is normative — implementations signal only those
   types so OSS error handling is stable.

## The LLM provider catalog (worked example)

Historically two hard-coded `PROVIDERS` dicts (in `core/config.py` and
`api/v1/routes/config.py`) duplicated provider-selection policy. Because
the commercial server owns that policy, every server-side change forced
an edit to those OSS dicts — visible churn in the public repo on every
proprietary move.

Now both consumers read `llm_catalog`
(`src/spectra_sherpa/app/contracts/llm_catalog.py`).
The OSS default is byte-identical to the old dicts; a server injects its
own catalog once at startup:

```python
from spectra_sherpa.app.contracts.llm_catalog import (
    LLMProviderMeta,
    set_llm_provider_catalog,
)

set_llm_provider_catalog({
    "acme": LLMProviderMeta(
        id="acme", name="Acme LLM", default_model="acme-1",
        env_var="ACME_API_KEY", base_url="https://api.acme.example",
    ),
})
```

The `/api/v1/config` route reflects the injected catalog at request
time. No OSS file changes when the proprietary catalog changes — that is
the contract working as intended.

See also: [LLM feature contract](llm-feature-contract.md),
[Governance](governance.md).
