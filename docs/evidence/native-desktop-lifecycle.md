# Native desktop lifecycle evidence

Internal #1129 lifecycle slice. No signed release or owner-profile acceptance
is claimed.

- 17 Node tests pass: process/authentication boundaries plus explicit background,
  cancellation, restart ordering, unavailable activity disclosure, restricted
  folder IPC and diagnostics allowlist.
- Shared frontend TypeScript check and production build pass.
- Actual Electron/OSS smoke passes on Apple Silicon with a disposable profile.
- Actual lifecycle smoke passes: native folder bridge, exact CSV export bytes,
  unsaved-edit cancellation preserves the active backend, and accepted restart
  removes the old backend before the new workbench is used.
- Native CI repeats smoke and lifecycle smoke before and after packaging for
  Windows x64 and Apple Silicon. Native chooser/prompt responses are substituted
  by the test; manual appearance and signed-platform behavior remain acceptance
  checks.

The close decision uses authoritative job status and enabled watches from the
local backend. A failed status read is disclosed and defaults to Cancel. Only
an explicit background choice hides the window; a tray control remains visible.
Renderer beforeunload runs before backend shutdown, so cancellation can preserve
unsaved work. Backend crashes do not replace the frontend and discard its edits.
