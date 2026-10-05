#!/usr/bin/env bash
# Called from the public package root on Ubuntu 24.04 x86-64, never as root.
set -euo pipefail
./scripts/rebuild_static.sh
python -m pip install . -r desktop/requirements.txt
python desktop/verify_runtime_attestation.py --output desktop/runtime-provenance.json
npm --prefix desktop/electron ci
npm --prefix desktop/electron test
SPECTRA_DESKTOP_NATIVE_BACKEND=1 pyinstaller --noconfirm --clean --distpath desktop/dist --workpath desktop/build desktop/spectrasherpa.spec
python desktop/verify_optional_exclusions.py desktop/dist/SpectraSherpa
python desktop/verify_native_backend.py desktop/dist/SpectraSherpa/SpectraSherpa
python desktop/ubuntu/provenance.py
npm --prefix desktop/electron run package
python desktop/ubuntu/ci_policy.py \
  desktop/electron/node_modules/electron/dist/electron \
  desktop/electron/out/SpectraSherpa-linux-x64/SpectraSherpa \
  desktop/dist/SpectraSherpa.AppImage > desktop/ubuntu-ci.apparmor
sudo install -m 644 desktop/ubuntu-ci.apparmor /etc/apparmor.d/spectrasherpa-ci
sudo apparmor_parser -r /etc/apparmor.d/spectrasherpa-ci
# Start one isolated desktop session. Secret-store fallback is refused by the app.
dbus-run-session -- xvfb-run -a bash desktop/ubuntu/qualify.sh
