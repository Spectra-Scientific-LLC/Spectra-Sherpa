# /vendor/ — cross-bundle import shims

The server-provided frontend modules (`/ui/auth.js`, `/ui/admin.js`)
declare Vue, Vue-Router, Pinia, and PrimeVue as **Vite externals** so
at runtime they reuse the OSS bundle's already-loaded instances —
critical for Pinia store sharing, router identity, and Vue reactivity
to cross the cross-bundle boundary.

When the browser loads a server module, it sees imports like:

```js
import { ref } from "vue";
import Button from "primevue/button";
```

The **import map** in `index.html` maps those bare specifiers to the
shim files in this directory:

- `vue.js` → re-exports `window.__OSS_VENDOR__.vue` named members
- `vue-router.js` → re-exports `window.__OSS_VENDOR__.vueRouter`
- `pinia.js` → re-exports `window.__OSS_VENDOR__.pinia`
- `primevue/*.js` → per-component shims re-exporting from
  `window.__OSS_VENDOR__.primevue[<component>]`

OSS's `src/main.ts` populates `window.__OSS_VENDOR__` during
bootstrap, before any dynamic `/ui/*.js` import runs.

## Status (commit 4 of Phase 1b)

These shims are **scaffolding**. The exhaustive list of named exports
they need to cover will be determined in commit 4 when the boot
sequence is wired and the first real `/ui/auth.js` load is exercised
in a dev environment. Commit 4 populates the complete set; this
README exists so future contributors understand why the shims are
shaped this way.
