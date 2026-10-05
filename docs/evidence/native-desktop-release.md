# Native release automation preparation

The public `desktop-release.yml` now builds the Electron workbench for Windows
x64 and Apple Silicon macOS. It retains tag/checkout equality, protected signing
environment, source-bound manifests, checksums, attestations, draft creation and
refusal to overwrite an existing release.

## Automated contract

- Frontend and frozen OSS backend come from one checkout; the native backend is
  built with inherited pipes. Python and shell versions must match the tag.
- Packaged UI and lifecycle smoke checks precede production fuse hardening.
- Post-hardening startup uses no debugger; signing verifies the same fuse policy.
- Windows signs bundled executables and installer/uninstaller, then checks the
  installed application and retained generated profile files across uninstall.
- Mac signs/notarizes/staples the app and DMG, then starts the mounted native app.
- Schema 2 declares an Electron shell and requires exactly Windows x64 plus Mac
  arm64. Browser declarations, incomplete sets, changed hashes and source
  mismatches are refused.

Twenty-one release, delivery and download contract tests passed locally. These
checks validate automation structure and refusal behavior; they do not establish
that credentials, hosted signing services or platform acceptance work.

A disposable production-fused Apple Silicon application also passed startup
and owned-backend shutdown while retaining its newly generated profile for
installer-preservation evidence. It was ad-hoc signed, not Developer ID signed.

## Owner boundary

See [the release procedure](../developers/native-desktop-release.md). The first real
signed run remains necessary, on the public repository after OSS publication.
Both clean-machine receipts must identify the exact draft bytes before the owner
publishes. Existing-profile migration uses copies. No automatic updater/feed is
introduced. Intel Mac and Linux native artifacts are outside this release scope;
pip remains available for those environments.
