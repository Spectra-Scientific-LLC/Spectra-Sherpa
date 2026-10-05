# Native desktop candidate

This is the public Electron shell for the existing OSS frontend and scientific
backend. Supported candidates: Windows x64 and Apple Silicon macOS. The current
browser installer remains the release lane until native signing, installer
replacement and scientist acceptance are qualified.

## Build an internal candidate

Run from the OSS package root on the target platform (PowerShell users can set
`$env:SPECTRA_DESKTOP_NATIVE_BACKEND = "1"` before the PyInstaller command):

```bash
./scripts/rebuild_static.sh
python -m pip install . -r desktop/requirements.txt
npm --prefix desktop/electron ci
SPECTRA_DESKTOP_NATIVE_BACKEND=1 pyinstaller --noconfirm --clean \
  --distpath desktop/dist --workpath desktop/build desktop/spectrasherpa.spec
npm --prefix desktop/electron test
npm --prefix desktop/electron run smoke
npm --prefix desktop/electron run package
```

Expected: the smoke harness opens the actual workbench in Chromium, verifies
HTTP and WebSocket authentication and renderer isolation, quits, checks that
the backend stopped, and removes its disposable profile. The packaged internal
candidate appears under `desktop/electron/out/`. It is **unsigned**, not a public
release. A real Mac signing spike is still required before lifecycle polish.

Development can select `SPECTRA_DESKTOP_DEV_PYTHON` and a disposable
`SPECTRA_DESKTOP_DEV_PROFILE`; packaged apps ignore both variables and launch
only their bundled backend. Normal launches let the existing Python profile
resolver choose the established data directory. No separate Electron database
or migrated profile location is introduced.

## Boundaries and lifecycle

- Electron and packaging versions are exact pins in the lockfile.
- The main process launches one owned backend, sends its random secret through
  a private pipe, and waits for authenticated readiness before loading the UI.
- Only that window's requests to the reported HTTP/WebSocket authority receive
  the credential. The renderer never receives it through JavaScript or IPC.
- The session connects directly, refuses unrelated destinations and permissions,
  and uses sandboxing, context isolation, no Node integration and no webviews.
- A second launch focuses the existing application. Quit closes the ownership
  pipe and waits for backend shutdown. A failed startup has a visible recovery
  page and Application → Restart workbench action.
- There are no network update checks, downloads or install/update feed.

The deeper security matrix, active-analysis/watch quit choices, export and
support-bundle UX are later slices in #1129. Do not use this internal candidate
to qualify background inference yet. Actual Windows-profile recovery, signed
Mac notarization and Windows installer identity require platform receipts;
source tests and an unsigned Mac development run are not substitutes.

## Automated checks

`npm test` covers protocol parsing, refusal, child cleanup, exact endpoint
routing and credential lifetime using real child processes. `npm run smoke`
uses the actual bundled backend and shared frontend on each native runner.
After packaging, CI repeats it with `SPECTRA_DESKTOP_SMOKE_APP` pointing to the
packaged executable. This exercises the packaged resource path on a disposable
`DATA_DIR`; no developer-only profile switch is needed inside the application.
The monorepo `Native desktop candidate` workflow retains internal artifacts;
it does not change the public tagged release workflow.


## Desktop controls

- **Close window:** when analyses or watches are active, choose Cancel, Keep
  running in background, or Stop work and quit. Background operation has a
  visible tray icon; use it to reopen the window or quit.
- **Quit:** confirms interruption of active work. Watching pauses while the app
  is closed and resumes according to its saved enabled state on the next launch.
- **Restart workbench:** confirms interruption and respects unsaved workflow
  edits before replacing the backend. Return to the workbench to save edits,
  or explicitly discard them. The backend stays alive when you cancel.
- **Choose folder:** the Deploy watch editor opens the system folder chooser.
  Cancelling keeps the previous path. Browser installations retain path entry.
- **Import/export:** the existing file input uses Chromium's native file picker;
  exports use the system save chooser. Failed downloads report a visible error.
- **Save desktop diagnostics:** produces a small JSON report with application,
  runtime and platform versions. It excludes logs, environment, spectra, chat,
  filesystem paths and credentials.

`npm run smoke:lifecycle` exercises the real preload bridge, exported CSV bytes,
unsaved-edit cancellation and restart. It substitutes only the operating-system
chooser and prompt responses; the renderer, backend and process lifecycle are
real. Run and folder-watch scientific qualification on clean signed machines
remains part of release acceptance.
