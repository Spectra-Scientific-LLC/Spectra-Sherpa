# Desktop downloads and installation

The desktop application runs the local SpectraSherpa workbench in its own application window, without a browser or separate
Python installation. Local scientific work does not require a cloud account.

## Download availability

[Open the official releases](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/releases).
Choose a release containing **`desktop-manifest.json`**, **`SHA256SUMS`**, and an
installer for your platform. A source-code release alone is not an installer
release. If these desktop assets are absent, an installer for that version has
not been published. Unsigned Actions smoke artifacts are development candidates.

| Computer | Release asset (`VERSION` is the selected release version) |
| --- | --- |
| Apple Silicon Mac | `SpectraSherpa-VERSION-macos-arm64.dmg` |
| Windows x64 | `SpectraSherpa-VERSION-windows-x86_64.exe` |

Check **About This Mac** for Apple Silicon. This is not a universal binary.
The native release targets Windows x64 and Apple Silicon macOS only; Intel Mac
and Linux users can use the [pip installation](../onboarding/local-30-minutes.md).
Consult the selected release's clean-machine acceptance notes for supported OS
versions. CI build hosts alone do not establish desktop compatibility.

## Verify your download

Compare the file's SHA-256 with its entry in `SHA256SUMS` from the same release.

```powershell
# Windows PowerShell; substitute the actual downloaded filename.
Get-FileHash .\SpectraSherpa-VERSION-windows-x86_64.exe -Algorithm SHA256
Get-AuthenticodeSignature .\SpectraSherpa-VERSION-windows-x86_64.exe
```

```bash
# macOS; substitute the actual downloaded filename.
shasum -a 256 SpectraSherpa-VERSION-macos-arm64.dmg
```

On macOS, normal opening uses Gatekeeper verification. If you already have Apple
developer tools, `xcrun stapler validate <downloaded-file.dmg>` is an additional
optional ticket check; installing developer tools is not required to use the app.

Windows signature status should be **Valid** with the publisher named in the
release notes. The manifest identifies the exact source commit and artifact
hash. Report a checksum or signature mismatch with the release version and file
name; do not bypass platform signature protection to proceed.

## Install and start

### Windows

Run the signed `.exe`. Installation uses your user profile, normally
`%LOCALAPPDATA%\Programs\SpectraSherpa`, without requiring administrator rights.
Launch SpectraSherpa from the Start Menu.

### macOS

Open the notarized DMG and copy `SpectraSherpa.app` to Applications. If the shared
Applications folder is not writable, use your own `~/Applications` folder.
Launch the copied application. SpectraSherpa opens its own native window.

## Your data and logs

The packaged application's default data location is:

- Windows: `%USERPROFILE%\.spectra_sherpa`
- macOS/Linux: `~/.spectra_sherpa`

For managed desktop setups, `DATA_DIR` overrides that default. The pip CLI
also accepts `--data-dir`. Keep this
data directory separate from the installed application. The rotating application
log is `<data-dir>/logs/desktop.log`; include the version/build identity and the
relevant log excerpt when reporting an issue, without keys or private spectra.

Before upgrading, stop the application and back up your data directory. Keep
that backup until you have reopened and checked your saved work with the new
version. Reinstalling application files is not a data backup.

## Offline science and optional AI

After installation, disconnect the network and check a local import, workflow
execution, save/reopen and result export. These operations use local computation.
Reference downloads and remote AI providers need a network connection and
explicit configuration. The base installer excludes optional SpectroChemPy;
see [optional SpectroChemPy nodes](../nodes/spectrochempy.md) for that separate
installation path. That creates a separate Python environment; it does not add
SpectroChemPy to this frozen desktop installer.

BYOK Assistance is optional. Use the workbench's provider/key settings for your
chosen provider; no AI key is bundled. Leave it unconfigured for offline
scientific work. See [Cloud vs Local OSS](../introduction/cloud-vs-local.md) for
the distinction between local Assistance and paid Sherpa Advisor.

## Uninstall while retaining your work

On Windows, use Apps & features or the installed uninstaller. Keep the default
choice to retain data; deleting data is a separate, explicit choice. Silent
uninstall retains data. On macOS, remove the application; on Linux, remove the
extracted application folder. Your separate data directory remains available.
Do not remove your data directory as a routine reinstall step.

## Updating the app

Download and install a newer signed release after quitting SpectraSherpa and
backing up the complete data directory. There is no automatic update feed or
in-app updater. Opening a newer version may upgrade its local database; keep
the backup for recovery. On first launch, wait for database preparation to
finish. If startup refuses the profile, retain the displayed diagnostic and
use a disposable copy for troubleshooting.


## Ubuntu 24.04 LTS (x86-64)

The Ubuntu candidate is `SpectraSherpa-VERSION-ubuntu-x86_64.AppImage`.
It is available only after clean-machine acceptance and publication alongside
`SHA256SUMS` and `desktop-manifest.json`. Follow the
[Ubuntu installation and acceptance steps](../developers/ubuntu-desktop-release.md).
Ubuntu 24.04 needs a one-time, per-application sandbox policy; there is no
sandbox-disabled fallback. After installation, launch the AppImage's own window.
A secure desktop keyring is required for saved AI/provider credentials. Your
scientific files remain in `~/.spectra_sherpa` when the AppImage is removed.
