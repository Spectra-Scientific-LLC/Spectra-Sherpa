# Native desktop signing preparation

## Scope

Windows x64 and macOS Apple Silicon use the same public Electron shell and OSS
backend. This slice prepares production hardening and signing; it does not
claim a signed build, notarization receipt, or clean-machine acceptance.

## Order and invariants

1. Build the frontend and pipe-enabled frozen backend, then package the native
   application. Exercise the actual packaged UI before disabling debugging.
2. Run `node desktop/electron/harden.cjs APPLICATION` and repeat with `--verify`.
   The release refuses unknown fuse schemas. Node environment/CLI debugging,
   RunAsNode and arbitrary unpacked application loading are disabled; embedded
   ASAR integrity is enabled.
3. Run `node desktop/electron/hardened-smoke.cjs EXECUTABLE`. This starts the
   production-fused executable without a debugger against disposable data and
   checks that its backend exits after parent termination, reopens the same
   profile through canonical stale-lock recovery, and removes the lock on
   Windows window close or macOS SIGTERM cleanup. The separate pre-fuse
   lifecycle smoke verifies normal desktop controls; SIGTERM is not a Mac
   menu-quit receipt. Windows process observation uses a read-only wait;
   the test never removes the lock to make recovery pass. It is
   a startup/ownership check, not a substitute for scientist GUI acceptance.
4. Sign the hardened application. Windows signs every bundled executable and
   verifies publisher and timestamp. macOS signs nested code inside-out,
   applies Electron JIT entitlement only to Electron executable bundles, and
   retains the existing Python entitlements only for its backend.
5. Package the Windows installer or notarize/staple the Mac app and DMG. Verify
   again before release manifest creation. The release automation integration
   is a separate slice; this change does not switch the published artifacts.

## Installer identity and profile custody

The native Windows installer explicitly retains `AppId=Spectra Sherpa`, the
existing install location, per-user scope, mutex and uninstall/profile policy.
`desktop/verify_windows_identity.ps1` reads an actual installed registry entry
and rejects a changed identity or duplicate installation. Source checks alone
cannot establish the identity of an owner's previously distributed installer.

On a disposable Windows machine, before installing the replacement:

```powershell
./desktop/verify_windows_identity.ps1 | Set-Content previous-install.json
```

After installing the native candidate over that installation:

```powershell
./desktop/verify_windows_identity.ps1 | Set-Content native-install.json
Compare-Object (Get-Content previous-install.json) (Get-Content native-install.json)
```

Expected: one uninstall record `Spectra Sherpa_is1`; same install location,
profile location and publisher, with only the intended version changes. Inspect
any difference before publication. Stop Sherpa and copy the complete profile
before any migration qualification; never test against the sole original.

## Evidence and outstanding owner gates

Local verification: 18 Node contract tests and 10 Python signing tests passed.
A disposable packaged Apple Silicon app accepted the production fuse policy,
started its backend without an inspector, and released its owned profile lock
on termination. That app had only an ad-hoc signature.

Pending: actual Apple Developer ID signing/notarization/stapling, Azure signing,
Windows installed-identity receipts, fresh Mac Gatekeeper and Windows
SmartScreen acceptance, existing-profile qualification on copies, and native
release workflow integration. Secrets belong in the public repository's
protected `desktop-release` environment, never in this repository or evidence.
