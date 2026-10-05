# Ubuntu AppImage build and acceptance

The Ubuntu target is **Ubuntu 24.04 LTS, x86-64**, using the same OSS frontend,
Python backend and Electron window as Windows/macOS. It produces one
`SpectraSherpa-VERSION-ubuntu-x86_64.AppImage`. It has release checksums and GitHub
build provenance; it is not an Apple- or Azure-signed artifact. Availability
begins only when an accepted release is published.

## Build and release

The shared build is `desktop/ubuntu/build.sh`, called by both the monorepo native
candidate workflow and the public repository's tag release workflow. The latter
waits for Ubuntu before starting the signed Mac/Windows builds. All three
artifacts must match the tag and source commit before a draft release is created.

The Ubuntu runner installs its desktop libraries, a display and a Secret Service
provider, builds the frozen backend and Electron application, verifies local-only
bundle exclusions, and runs the native frontend/lifecycle checks. It hardens the
Electron fuses before packing and then runs the final AppImage itself through
startup, crash recovery and restart checks. Missing qualification evidence fails
the job. `desktop/ubuntu/tools.json` pins the packaging tool and embedded runtime
by release URL and SHA-256; neither silently follows a continuous release.

**Expected:** an AppImage plus `ubuntu-desktop-evidence`, containing its checksum,
build tool identities and a qualification receipt. A passing runner is not
clean-machine acceptance. Never replace a published release's bytes.

## First installation on a clean Ubuntu desktop

Download the AppImage and `SHA256SUMS` from the same accepted release. In the
download directory, set the actual version and verify the downloaded file:

```bash
VERSION=0.6.0
IMAGE="SpectraSherpa-$VERSION-ubuntu-x86_64.AppImage"
grep "  $IMAGE$" SHA256SUMS > ubuntu-checksum.txt
sha256sum --check ubuntu-checksum.txt
mkdir -p "$HOME/Applications"
mv -- "$IMAGE" "$HOME/Applications/SpectraSherpa.AppImage"
chmod +x "$HOME/Applications/SpectraSherpa.AppImage"
```

**Expected:** `OK` for exactly that AppImage. Keep this stable application path
when replacing the app with a verified later version. This does not modify the
scientific profile in `~/.spectra_sherpa`.

Ubuntu 24.04 restricts unprivileged user namespaces, which Chromium needs for its
sandbox. Use an application-specific AppArmor rule; do not disable Chromium's
sandbox or change the global namespace policy. This one-time administrator step
allows this exact executable path to create its sandbox:

```bash
sudo apt-get install libfuse2t64
"$HOME/Applications/SpectraSherpa.AppImage" --print-sandbox-policy > /tmp/spectrasherpa-appimage.policy
cat /tmp/spectrasherpa-appimage.policy
sudo install -m 644 /tmp/spectrasherpa-appimage.policy /etc/apparmor.d/spectrasherpa-appimage
sudo apparmor_parser -r /etc/apparmor.d/spectrasherpa-appimage
"$HOME/Applications/SpectraSherpa.AppImage"
```

**Expected:** the printed policy names only your stable AppImage path; the app
opens its own window. Afterwards launch it from the file manager. Do not run the
application as root. If your institution prohibits this per-app rule, stop and
ask its administrator; there is no `--no-sandbox` fallback. Moving the executable
requires updating the rule to its new exact path.

The normal Ubuntu GNOME login provides a Secret Service keyring. Saved provider
keys require a working secure keyring. If it is unavailable or Electron chooses
`basic_text`, Sherpa refuses credential storage/use while local scientific work
remains available. Never treat the plaintext fallback as encrypted storage.

## Acceptance on a fresh machine

Use a disposable profile and the same synthetic calibration/prediction files in
[the native acceptance procedure](native-desktop-release.md#e1-a-small-reproducible-model-round-trip).
Record the exact source
commit, AppImage checksum, Ubuntu version and session type.

1. Disconnect networking before first application launch. Expect its own window,
   no runtime download and no manually managed browser or port.
2. Import the synthetic data, fit/save/reopen its workflow, and reproduce the
   expected predictions. Record actual values and sample identities.
3. Perform an ordinary saved-model watch dry run, review predictions and save
   its receipt, then enable monitoring. Check a new matching file is processed.
4. Close normally, reopen, and verify saved data and watch configuration. Confirm
   no owned backend remains after exit. Re-run after an owned application crash.
5. In a normal secure-keyring session, save a disposable BYOK credential, restart
   and verify it can be used. In a session without a secure keyring, verify a
   clear credential refusal and successful local analysis; never save real keys
   in a test session.
6. Delete only the AppImage and confirm the scientific profile remains. The
   in-app **Delete all local data** action is separately destructive and requires
   its confirmation. Remove the per-app AppArmor rule only when uninstalling.

**Expected:** all six observations recorded, plus offline network observations.
Do not claim this acceptance from unit tests or the CI display session alone.
The operator publishes the existing draft only after Ubuntu and the signed
Mac/Windows acceptance records all pass.

Reference: [Ubuntu AppArmor user namespaces](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/),
[AppImage packaging](https://github.com/AppImage/appimagetool), and
[Electron secure storage](https://www.electronjs.org/docs/latest/api/safe-storage).
