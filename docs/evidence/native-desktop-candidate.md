# Native desktop candidate evidence

Plan: #1129. This is an internal prototype, not a signed release qualification.

## Implemented and checked

- Public Electron44.4.5 shell using the shared OSS frontend and backend.
- Eight Node tests cover actual private pipes, authenticated health, malformed
  and oversized frames, startup refusal, owned child cleanup, endpoint routing
  and credential revocation.
- Apple Silicon development smoke opened the real dashboard with zero page
  errors, verified the sandbox has no renderer `process`/`require`, authenticated
  HTTP/WS and unauthenticated HTTP refusal, then quit and verified no backend
  listener or profile lock remained. Python3.12 was used in this local check;
  CI uses the existing Python3.11.9 build authority.
- Apple Silicon frozen-backend smoke and actual packaged `.app` smoke also
  passed the same HTTP/WS/sandbox/quit assertions. The packaged check exercises
  `app.isPackaged` and `process.resourcesPath`, using the standard `DATA_DIR`
  override for its disposable profile. No owner profile was opened.
- Native CI covers Windows x64 and Apple Silicon frozen backends. A receipt is
  required from each target; adding a workflow is not a passing build receipt.

## Remaining qualification

- Windows x64 native frozen build and packaged smoke; exact-head CI receipts.
- Real Apple Developer ID signing/notarization spike with nested native libraries.
- Existing Windows installer identity and old-to-new installation on an actual
  copy of the owner's installed profile.
- Security expansion, file/export lifecycle and active-watch/analysis close
  choices, then production signing/release integration per later plan slices.

The current public browser installer remains the fallback. No signing authority,
clean-machine acceptance, or successful Windows profile repair is claimed here.
