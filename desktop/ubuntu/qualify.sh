#!/usr/bin/env bash
set -euo pipefail
mkdir -p desktop/ubuntu-evidence
qualification_stage=credential_store
record_failure() {
  local status=$?
  printf '{"platform":"ubuntu-24.04-x86_64","native_startup_and_restart":"failed","stage":"%s","clean_machine_acceptance":"pending"}\n' "$qualification_stage" > desktop/ubuntu-evidence/qualification.json
  exit "$status"
}
trap record_failure ERR
printf '\n' | gnome-keyring-daemon --unlock --components=secrets
qualification_stage=development_smoke
npm --prefix desktop/electron run smoke
npm --prefix desktop/electron run smoke:lifecycle
export SPECTRA_DESKTOP_SMOKE_APP="$PWD/desktop/electron/out/SpectraSherpa-linux-x64/SpectraSherpa"
npm --prefix desktop/electron run smoke
npm --prefix desktop/electron run smoke:lifecycle
node desktop/electron/harden.cjs "$SPECTRA_DESKTOP_SMOKE_APP"
node desktop/electron/harden.cjs "$SPECTRA_DESKTOP_SMOKE_APP" --verify
qualification_stage=hardened_application
node desktop/electron/hardened-smoke.cjs "$SPECTRA_DESKTOP_SMOKE_APP"
qualification_stage=appimage_packaging
python desktop/ubuntu/package.py
# Exercise the distributed AppImage itself with its production fuses and runtime.
qualification_stage=distributed_appimage
node desktop/electron/hardened-smoke.cjs "$PWD/desktop/dist/SpectraSherpa.AppImage"
qualification_stage=retained_evidence
sha256sum desktop/dist/SpectraSherpa.AppImage > desktop/ubuntu-evidence/SHA256SUMS
cp desktop/ubuntu/tools.json desktop/ubuntu-evidence/
printf '{"platform":"ubuntu-24.04-x86_64","native_startup_and_restart":"passed","sandbox_bypass":false,"clean_machine_acceptance":"pending"}\n' > desktop/ubuntu-evidence/qualification.json
