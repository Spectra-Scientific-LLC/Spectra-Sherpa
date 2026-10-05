# Desktop build and release operations

This directory packages the existing local SpectraSherpa workbench with
PyInstaller. Local build commands produce unsigned candidates. The release
workflow adds signing and notarization; public distribution follows native
verification and clean-machine acceptance.

## Build on the target operating system

Use a clean Python 3.11 or 3.12 environment on the OS and architecture being
packaged. Build artifacts must never be cross-compiled.

```bash
cd packages/spectra-sherpa
# macOS: isolate source-built cryptography from Python's own OpenSSL.
if [ "$(uname -s)" = "Darwin" ]; then
  export OPENSSL_STATIC=1 OPENSSL_DIR="$(brew --prefix openssl@3)" PIP_NO_CACHE_DIR=1
fi
python -m pip install .
python -m pip install -r desktop/requirements.txt
pyinstaller --noconfirm --clean --distpath desktop/dist --workpath desktop/build desktop/spectrasherpa.spec
```

The bundle is intentionally unsigned. Do not publish it, call it an installer,
or use it as a release artifact. The signing/notarization and fresh-machine
acceptance gates are defined in the
[M1 desktop-delivery section of the managed-optimization execution plan](../../../docs/plan/managed-optimization-execution-plan.md#m1--oss-assistance-and-academic-entry-path).

## Included HITRAN clients

Windows, macOS and Ubuntu installers include **HAPI 1.3.0.0 (MIT)** and
**HAPI2 0.2.2 (GPLv3)**. No extra pip installation is needed. A personal HITRAN
API key and explicit network permission are still needed for live acquisition.
Set the key through Settings → API Keys and enable HITRAN queries under
Settings → Integrations; the desktop's existing protected credential storage applies. Bundling the client does not enable downloads by default.

The build downloads hash-pinned upstream **code archives**, verifies their
Python source against the installed clients, and places their original licenses
and source alongside the backend. It does not fetch HITRAN spectra or user keys.
Find `third_party/hitran/` inside the packaged backend's `_internal/` directory
(`resources/backend/_internal/` on Windows/Linux; inside
`SpectraSherpa.app/Contents/Resources/backend/_internal/` on macOS). The standalone
PyInstaller `.app` uses `Contents/Resources/third_party/hitran/`. HAPI2's original
source tarball includes its build configuration; the HAPI wheel contains its
unmodified Python source. `manifest.json` records their versions and hashes.

Every desktop build invokes `verify_optional_exclusions.py`, which now also
verifies the retained source and notices, then starts the **frozen executable**
in a disposable cache with network connections refused. The check imports both
clients, tests a Lorentz profile against its analytical values, exercises HAPI2's
SQLite backend, compiles a HAPI2 Numba profile against a SciPy reference, and
checks its acquisition entry points. HAPI2 is loaded from real Python source;
its JIT cache lives under the user's synthesis cache, never in the signed app.
The verifier uses a fresh cache and ignores developer Numba overrides. A missing dependency,
license or source archive fails the build before signing. Output is retained in
the build log. This is offline packaging qualification, not a live HITRAN service test.

On each clean-machine acceptance run, use a personal key, allow HITRAN access,
and acquire a narrow spectral range through Synthesis. Confirm the resulting
axis and spectrum appear, then disable downloads and confirm the acquired local
spectrum remains usable. Do not put the key or downloaded data in CI evidence.

Other optional extras, including SpectroChemPy, remain excluded from desktop
installers under the current product packaging policy; pip extras are unchanged.

Application logs are written to `<data-dir>/logs/desktop.log` (and rotate
there). With no `--data-dir`, the existing platform local-data default applies.

## Local smoke check

On a clean target machine, disconnect the network and run the artifact. It
must start on loopback, open the workbench, and make the health endpoint
available. The desktop launcher chooses an ephemeral port and never invokes
the CLI's fixed default port. It permits one running desktop
process per data directory; a second launch fails safely and tells the user to
close the existing workbench or choose another `--data-dir`.

```bash
# macOS/Linux example; Windows uses SpectraSherpa.exe in the generated folder.
desktop/dist/SpectraSherpa/SpectraSherpa --no-browser
```

With an explicit port, verify `GET /api/health` returns `{"status":"ok"}`.

The native smoke workflow automates startup, frontend serving, restart and
local persistence. Signed clean-machine acceptance additionally verifies the
scientific import, workflow and export journey.

## Release signing qualification

The public-repository release workflow is maintained at
`.github/workflows/desktop-release.yml` inside this package and exported through
the curated OSS publisher. It does not execute at the monorepo root.

macOS uses `sign_macos.py` after provenance is written. It signs physical inner
Mach-O code and framework seals before the outer application with hardened
runtime, verifies the result, notarizes/staples the app, then packages, signs,
notarizes and staples the DMG. The copied app therefore carries its own ticket.
The temporary keychain is removed on success or failure; credentials are never
written into build artifacts. `desktop/signing-evidence/` retains Apple's JSON
acceptance receipts as separate CI evidence, excluded from release asset upload.
The checked-in entitlements are retained pending real scientific-library tests;
they are not a claim of a completed entitlement minimization review.

Windows uses Azure Artifact Signing via federated GitHub OIDC. For the first
release, we sign only the SpectraSherpa app executable, packaged backend, installer
and uninstaller, verifying our publisher and timestamp. Third-party executables,
DLLs, PYD and NODE modules retain their existing bytes and signatures. Broader
dependency signing is deferred unless a real institutional policy requires it.
This does not establish WDAC/AppLocker acceptance. macOS retains nested signing
required for notarization.
`desktop/windows_signing.ps1` discovers an installed x64 Windows SDK SignTool
and verifies the application, installer and signed uninstaller, including a
trusted timestamp and an exact expected publisher subject. Set the release
environment variable `WINDOWS_SIGNING_SUBJECT` to the certificate's full subject
(public information, not its private key). Do not pin the rotating Azure leaf
certificate thumbprint as the publisher policy. The thumbprint remains useful
provenance for each specific binary.

Before adding credentials, protect the **public repository's** `desktop-release`
environment with a required reviewer and **Selected branches and tags**. Add
only a **Tag** rule named `spectra-sherpa-v*`; allow no branch rules. Keep Apple
secrets in that environment. The Azure federated credential must use:

- Issuer: `https://token.actions.githubusercontent.com`
- Audience: `api://AzureADTokenExchange`
- Subject: `repo:Spectra-Scientific-LLC/Spectra-Sherpa:environment:desktop-release`

The public repository and environment names must match exactly, including case.
A monorepo or branch subject does not match the signing job's identity. Follow
[the setup and verification procedure](../docs/developers/native-desktop-release.md#a-one-time-live-signing-setup)
before the first signed run.

Apple secrets are `APPLE_CERTIFICATE_P12_BASE64`, `APPLE_CERTIFICATE_PASSWORD`,
`APPLE_TEAM_ID`, `APPLE_NOTARY_KEY_P8_BASE64`, `APPLE_NOTARY_KEY_ID`, and
`APPLE_NOTARY_ISSUER_ID`. Use a **team** App Store Connect API key; the `.p8`
private key is base64-encoded in the environment secret, written only to a
private temporary file, imported into the temporary keychain, and removed.
The Developer ID signing certificate remains required. Personal Apple-ID
credentials are not used by this release lane. Azure environment
variables are `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
`AZURE_ENDPOINT`, `AZURE_ACCOUNT_NAME`, and `AZURE_CERTIFICATE_PROFILE_NAME`.
If the signing certificate uses another provider, configure its adapter before
running this workflow; do not upload private keys into source or issue comments.

Source tests exercise command safety, ordering and refused notarization states.
Only a real signing-environment run followed by a clean-machine download/install
can establish notarization, Gatekeeper/SmartScreen and offline acceptance. No
such receipt is implied by the presence of these scripts.

## Candidate and release delivery

After the workflow is exported into the public repository, use **Desktop
Release → Run workflow** selecting the same tag in the workflow ref selector
and tag input, with an existing exact `spectra-sherpa-v…` tag that
contains these scripts. This builds and retains candidates without publishing a
Release. The version tag must equal the bundled package version. Builds run
natively for three targets: Ubuntu 24.04 x86-64 (`ubuntu-x86_64`) first, then
Apple Silicon macOS (`macos-arm64`) and Windows x64 (`windows-x86_64`). The
Mac artifact is an arm64 DMG, not a universal binary. Intel Mac remains outside
this lane. Ubuntu produces a checksum/provenance-verified AppImage, without
Apple or Azure code signing.

Tag-push release runs use the same verified build steps. Every target produces
an asset plus a manifest binding its exact source commit, version, target, byte
size and SHA-256. The upload job requires all three targets, rejects altered or
unexpected files, and uploads a complete draft Release. After clean-machine
signed acceptance, the release owner publishes that same draft through GitHub Releases; no rebuild
or asset replacement is needed. An existing
Release is never clobbered. If an interrupted run leaves a draft, inspect its
receipts and remove that draft explicitly before retrying; do not overwrite an
already advertised binary. GitHub provenance attestations supplement platform
signatures; neither replaces a clean-machine acceptance run.

The monorepo owner must first run the curated OSS dry-run, review the exported
diff, and use the existing approved OSS publication procedure. Merely merging
this package-local workflow does not install a root workflow in either repo.
Check the public repository's Actions list before attempting candidate builds.

Signed release bytes are accompanied by `SHA256SUMS` and
`desktop-manifest.json`. Verify the checksum and platform publisher identity of
the downloaded installer, then perform the documented offline scientific smoke
and uninstall/data-preservation checks. A static manifest or a source test is
not evidence that those real installation checks passed.

## Local profile upgrade and recovery

Pip and desktop startup use the same SQLite upgrade path and existing data
location. Schema initialization and migration run in one transaction. Before
changing an existing local database, startup checks that its Alembic revision
belongs to this application, checks available disk space, blocks other database
writers, and creates a verified SQLite backup including committed WAL pages.

Backups live beside the configured database under
`.profile-upgrades/<snapshot-id>/`. Each contains `database.sqlite3` and
`manifest.json` with source/target schema revisions, application version, size,
SHA-256 and scope. Startup exercises restore to a temporary copy before allowing
migration. External datasets, models and exports are not modified by schema
migrations and stay in their existing locations. Backups are **never automatically
pruned**. Keep the latest known-good pre-upgrade snapshot until the new application
and its data have been qualified; remove older snapshots only deliberately.

Startup failure codes:

| Code | Action and expected result |
| --- | --- |
| `schema_incompatible` | Open the profile with its matching/newer application. No schema downgrade is attempted. |
| `insufficient_space` | Free the stated space and retry. Migration has not started. |
| `backup_failed` | Check permissions and space at the reported snapshot path, then retry. Migration has not started. |
| `migration_failed` | Preserve the profile and named verified snapshot. The schema transaction rolled back; retry with a corrected build or restore to a separate copy. |

For support with a Python installation, restore to a **new file**:

```sh
python -m spectra_sherpa.app.db.profile_upgrade \
  "/path/to/profile/.profile-upgrades/SNAPSHOT_ID" \
  "/path/to/disposable-profile/restored.sqlite3"
```

Expected result: `Verified database copy: ...`. An existing destination, digest
mismatch or corrupt backup is refused. Do not replace a running database, copy
only a live SQLite main file, or test recovery on your only profile copy. Stop
Sherpa and copy the complete profile before any manual recovery. This command
restores only the database; retain the profile's external asset directories too.
Electron will consume the same startup errors and recovery authority through its
launch contract; graphical recovery controls belong to the native-shell slice.
## Native-parent launch protocol (version 1)

Build the pipe-enabled child with `SPECTRA_DESKTOP_NATIVE_BACKEND=1` when
invoking the existing PyInstaller spec. On Windows this preserves inherited
stdio; the native parent must use `windowsHide: true`. The default standalone
browser bundle remains windowed. A previously built windowed executable does
not supply this private pipe contract and must not be used as the native child.

The native shell launches the pipe-enabled desktop executable with
`--desktop-ipc --data-dir <profile>`. This private mode forces local SQLite in
that profile, disables external browser launch, and lets Uvicorn bind an ephemeral
IPv4 loopback port. Ordinary CLI/browser launch behavior is unchanged.

Use private stdin/stdout pipes. Send one newline-terminated JSON launch frame:

```json
{"protocol":1,"type":"launch","secret":"<fresh cryptographically random token_urlsafe(32)>"}
```

The secret must be fresh for each child process. It is never a command argument,
environment setting, URL, readiness field, or saved project property. The parent
must retain it outside renderer JavaScript and inject `X-Spectra-Desktop-Token`
only into requests to the exact returned loopback endpoint. Use a direct
connection, without a proxy. HTTP, static assets, health and WebSocket handshakes
all require this header. Host must match the bound loopback endpoint; any supplied
Origin must also match. A new session invalidates the previous session's secret.

Protocol stdout contains newline-terminated JSON frames:

- `starting`: profile/application initialization has begun.
- `ready`: `endpoint` and application `version`, emitted only after ASGI startup
  (including database setup) succeeds and the actual listening socket is bound.
- `error`: bounded `code` and `message`; never a protocol traceback.
- `stopped`: shutdown completed.

Human-readable CLI/library output goes to stderr, not the readiness protocol.
Incoming frames are capped at 4096 bytes. A launch protocol mismatch is refused.

Send `{"protocol":1,"type":"shutdown"}` or close the parent's stdin pipe to
revoke the session and request shutdown. A broken channel also stops the owned
backend. A 15-second deadline bounds hung startup/shutdown; it exits only this
backend process, never a discovered PID. The parent must apply its own startup
deadline and own-child cleanup. Native process-tree and signed executable tests
remain target-platform release gates, alongside clean-machine acceptance.

The existing desktop lock uses a read-only Windows process handle probe;
`os.kill(pid, 0)` must never be used for Windows liveness, because Python maps it
to process termination on that platform.

## Native signed release

The Electron release lane targets Ubuntu x86-64, Windows x64 and Apple Silicon macOS, with
manual signed-installer updates. See [the native release procedure](../docs/developers/native-desktop-release.md)
for public-repository setup, each candidate's expected outcomes and owner
acceptance. Real signing and clean-machine receipts remain release gates.

### Release supply-chain and evidence controls

Release actions are pinned to reviewed full commit SHAs. Inno Setup 6.3.3 is
downloaded from its upstream release and checked against a committed SHA-256
before execution. Updating a tool requires reviewing and updating its pin.
Build jobs have read-only repository access plus OIDC/attestation permissions;
only the upload job has repository write access.

Signed builds require both accepted Apple notarization receipts, or Windows
per-binary hash/publisher/timestamp receipts, installer/uninstaller verification,
and signing/verification logs. A nonempty evidence directory alone does not
pass. Missing evidence blocks manifest preparation and release upload.


## Ubuntu native AppImage

The Ubuntu 24.04 x86-64 target now uses the same Electron shell and frozen OSS
backend. See [Ubuntu build, installation and acceptance](../docs/developers/ubuntu-desktop-release.md).
Its artifact is checksum/provenance verified; the Mac and Windows artifacts keep
their existing signing requirements. Release publication requires all three.
