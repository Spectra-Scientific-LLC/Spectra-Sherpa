# Spectra Sherpa (open source) Privacy Statement

**Publisher:** Spectra Scientific LLC ("Spectra Scientific", "we")
**Effective date:** October 1, 2026 · **Version:** 1.0

"We" means Spectra Scientific. "You" means the person using Spectra Sherpa.

This statement covers the open-source Spectra Sherpa workbench in two forms:

- **Installers**: the signed Windows and macOS applications, including copies
  from the Microsoft Store, and the Ubuntu AppImage (Part B).
- **Python package**: `spectra-sherpa` installed with `pip`, or run from source
  (Part C).

Part A applies to both. Spectra Scientific hosted products (Pro, Team, Hybrid)
are separate products with their own terms and privacy notices.

## Part A. Commitments in every form

### A1. Your data stays on your computer

Spectra Sherpa is a local scientific data-analysis application. Your datasets,
projects, workflows, sample tables, models, run history, results, folder-watch
settings and pre-upgrade backups are stored in a local profile folder on your
computer. No account or sign-in is required.

### A2. We collect nothing

Spectra Sherpa sends us no telemetry, analytics or crash reports. It performs
no update checks, license checks or automatic cloud sync. We receive none of
your data.

### A3. Outbound connections only for features you use

Spectra Sherpa connects to a third party only when you configure and use one
of these features:

- **AI assistant with your own provider key.** When you send a message, it
  goes directly to the provider you chose (for example OpenAI, Anthropic,
  DeepSeek, or a compatible or local server). The request contains:
  - the text you typed;
  - the name of the workflow you are viewing;
  - a short description of which part of the application is in view, with no
    data values.

  Datasets and results are sent only if you type or paste them into a message.
  The provider's terms and privacy policy govern that data. Nothing is sent
  until you configure a provider.
- **NIST Chemistry WebBook** (`webbook.nist.gov`). This is used only after you
  enable NIST queries in **Settings → Integrations → Data & Privacy** and
  request data.

Part C lists additional options available only in the Python package.

Spectra Sherpa never downloads Eigenvector Research data. If you download
those files yourself and import them, Spectra Sherpa verifies their recorded
file size and checksum before adding them.

### A4. You decide what to share

Nothing else leaves your computer except through your own actions, for
example:

- exporting projects, models, reports or scripts to a location you choose;
- sending us a support email and any files you attach.

We use support requests only to respond to you. Support requests covered by
this statement are retained no later than January 1, 2028.

### A5. Retention

Your data stays on your computer until you delete it. Spectra Sherpa never
uploads it and never deletes it on its own. Pre-upgrade backups are kept until
you remove them. We hold none of your data, so we cannot access, recover or
delete it for you.

Basic AI exchange history is temporary: up to 20 redacted exchanges remain in
memory until the backend exits or you clear them in Logs. Individual records
are size-limited and show when truncated. They include the question, instructions,
response and request details, but not authentication headers. History is not
written to a file unless you choose **Save exchange**. Saved copies remain
where you put them until you delete them.

## Part B. Windows, macOS and Ubuntu applications

The installers add these protections on top of Part A.

| | Windows | macOS | Ubuntu |
|---|---|---|---|
| Profile folder | `%USERPROFILE%\.spectra_sherpa` | `~/.spectra_sherpa` | `~/.spectra_sherpa` |
| API-key protection | Windows Data Protection (DPAPI) | macOS Keychain | Desktop Secret Service or KWallet; plaintext fallback refused |
| Distribution verification | Signed by us | Signed by us and notarized by Apple | Release checksum and build provenance; no platform code signature |

- **No connection to us.** The code that can connect to a Spectra Scientific
  hosted service is not included in the installers. The application refuses
  to enable such a connection, even if an older configuration file asks for
  it.
- **Online features are limited to Part A.** The installers do not download
  HITRAN or Eigenvector data.
- **Saved API keys** are encrypted with a key protected by your operating
  system for your user account. If you copy the profile to another computer or
  account, the keys cannot be read there and you enter them again. If your
  operating system's credential protection is unavailable, the application
  does not store or use API keys at all; analysis keeps working. On Ubuntu this
  includes sessions where Electron selects the insecure `basic_text` fallback.
- **Logs** are written to `logs/desktop.log` in your profile. Known secrets are
  redacted, logs rotate at about 60 MB in total, and they never leave your
  computer unless you send them.
- **Diagnostics.** **Application → Save desktop diagnostics…** writes a small
  local file. It contains only the application, backend, Electron and Chromium
  versions, the operating system, the processor architecture and a timestamp.
  It is never sent anywhere.
- **Internal communication.** The application window and its calculation
  engine communicate only inside your computer. Other devices, and other
  programs on your computer, cannot use that channel.
- **Deletion:**
  - **Application → Delete all local data…** permanently erases everything
    Spectra Sherpa stored in your profile, including saved keys, and restarts
    with an empty workbench. Anything in that folder that Spectra Sherpa cannot
    confirm it created, and any linked file or folder, is kept, and the
    application lists it for you.
  - Windows: the uninstaller always removes the application's temporary
    runtime folder. It then asks whether to delete your profile, and the
    default answer keeps it.
  - macOS: moving the application to the Trash leaves your profile in place.
  - Ubuntu: deleting the AppImage leaves your scientific profile and desktop
    keyring in place. Remove its application-specific AppArmor rule separately
    if you installed one.
- **Crash reports.** The application has none. Windows Error Reporting, Apple
  diagnostics and Microsoft Store statistics are governed by Microsoft's and
  Apple's own privacy statements.

## Part C. Python package (`pip`)

The Python package follows Part A. Because you run and configure it yourself,
it differs from the installers in these ways:

- **Profile folder.** `~/.spectra_sherpa` by default, `./data` in a source
  checkout, or the folder you set with `DATA_DIR`.
- **No hosted enrollment.** The OSS package contains no Hybrid client,
  enrollment UI, remote logging relay, or cloud sync implementation. Hybrid
  is a separate privately distributed product with its own customer terms.
- **HITRAN downloads.** If you install the `hitran` extra, add your own HITRAN
  key and enable HITRAN queries in **Settings → Integrations → Data & Privacy**,
  the package downloads data from HITRAN when you request it.
- **Saved API keys are not protected by the operating system.** Keys are
  stored in your profile, and the encryption key is kept in the profile's
  `.env` file. Your AI provider key is stored in `.env` in plain text. Anyone
  with access to your user account's files can read them. Protect your account
  and profile folder accordingly.
- **Local server.** The workbench runs a local web server. By default it
  accepts connections only from your own computer. If you choose to bind it to
  a network address, other devices on that network can reach it.
- **Logs.** By default, logs are shown in the console only. A log file is
  written only if you configure one.
- **Deletion.** There is no in-app "delete all" action or uninstaller for your
  data. Delete the profile folder to remove it. `pip uninstall spectra-sherpa`
  removes the program but not your data.
- **Signing.** The package is published to PyPI and is not code-signed.

## Children

Spectra Sherpa is a professional scientific tool. It is not directed to
children under 13, or the equivalent minimum age in your jurisdiction.

## Your rights

Because we do not collect your data, you can fulfil most data-protection
requests (access, correction, deletion, portability) directly on your
computer. For information you have sent us, such as support email, contact us
below.

## Changes

If Spectra Sherpa's data practices change, we will update this statement and
its effective date, and describe the change in that release's notes.

## Contact

Spectra Scientific LLC · [privacy@spectrascientific.ai](mailto:privacy@spectrascientific.ai)
