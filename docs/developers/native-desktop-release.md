# Windows and macOS: live signing and installer validation

Use this document from credential setup through approval of the actual downloaded
installers. It covers **Windows x64** and **Apple Silicon macOS (arm64)** from one
public OSS commit. Ubuntu 24.04 x86-64 AppImage build and acceptance are covered in
[the Ubuntu procedure](ubuntu-desktop-release.md). Intel Mac, MSI and an in-app updater
are outside this release lane.

**Current evidence boundary:** merged code and unsigned native CI are qualified.
That does not establish a successful live signing run, Gatekeeper/SmartScreen
acceptance, or preservation of the owner's existing Windows profile. Complete
and retain the checks below before publishing a release.

**First-release signing scope:** on Windows, sign only the SpectraSherpa app
executable, packaged backend, installer and uninstaller. Leave third-party
executables and DLL/PYD/NODE dependencies unchanged. macOS retains the nested-code
signing needed for notarization, plus the app and DMG. Dependency-wide Windows
signing is deferred for this direct-download lane. For Microsoft Store EXE submissions, use the manual workflow input `store_candidate=true`: every bundled PE is verified, unsigned dependencies are signed, and valid vendor signatures are preserved. Invalid signatures fail the candidate. This is an explicit Store exception to the scope above.

## Route through the procedure

| When | Steps | Completion condition |
| --- | --- | --- |
| Once, or when credentials change | A1–A4 | Public GitHub environment, Apple identity and Azure federation configured |
| Every candidate | B1–B3 | Reviewed public commit produces two signed installers, one Ubuntu AppImage and a draft release |
| Each exact candidate on clean machines | C, D, E | Windows, Mac and scientific acceptance receipts recorded |
| Before public availability | F | Owner approves those exact bytes and publishes the existing draft |
| If a step differs from expectations | G | Report step ID, version/SHA, observed result and evidence; leave draft unpublished |

Commands labelled **operator Bash** run in Bash on an administration workstation
with Git and authenticated GitHub CLI (`gh`). **Windows PowerShell** commands run
on the Windows test machine. Application users do not need Git, Python, Node,
GitHub CLI or a separate browser to run the installed app. The browser is used
below only to download installers and exercise normal download trust checks.

Replace values marked `REPLACE_…` before running a block. Use a new evidence folder
for each candidate. Do not paste passwords, certificates, private keys or tokens
into a PR, terminal command argument, or acceptance report.

## A. One-time live signing setup

### A1. Protect the environment in the public repository

**Action.** In the public
[Spectra-Sherpa environment settings](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/settings/environments),
create `desktop-release`. This is **not** the private `spectra` monorepo.

1. Add a required reviewer who can approve release jobs. If self-review is
   disabled, ensure a second authorized person is available.
2. Under **Deployment branches and tags**, choose **Selected branches and tags**.
3. Add exactly one rule: type **Tag**, pattern `spectra-sherpa-v*`. Add no branch
   rules, including `main`. Keep credentials in this environment, not broad
   repository secrets shared with branch workflows.
4. Confirm GitHub Actions is enabled in the public repository.

**Verify — operator Bash:**

```bash
REPO='Spectra-Scientific-LLC/Spectra-Sherpa'
gh auth status
gh api "repos/$REPO/environments/desktop-release" \
  --jq '{deployment_branch_policy, protection_rules}'
gh api "repos/$REPO/environments/desktop-release/deployment-branch-policies" \
  --jq '[.branch_policies[] | {name, type}]'
```

**Expected.** A required-reviewer rule is present; `custom_branch_policies` is
`true`, `protected_branches` is `false`; the second response is exactly:

```json
[{"name":"spectra-sherpa-v*","type":"tag"}]
```

Only matching tags may reach environment approval. The workflow also checks
source identity. See [GitHub environment rules](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

### A2. Configure Apple signing and team notarization

**Action — on the credential owner's Mac and in Apple's portals.**

1. Confirm the Apple Developer membership and relevant agreements are active.
2. In Keychain Access → **My Certificates**, locate the valid **Developer ID
   Application** certificate for the intended team. Expand it and confirm its
   private key is present. Export that identity, including its private key, as
   a password-protected `.p12` outside the checkout. A `.cer` alone is insufficient.
3. In App Store Connect → **Users and Access → Integrations → App Store Connect
   API**, create or select a **team API key** authorized for notarization. Record
   its Key ID and Issuer ID. Download the `.p8` once and keep it in private storage.
   The API key authenticates notarization; it does not replace the Developer ID
   signing certificate. Do not substitute an individual API key or an Apple-ID
   app-specific password for this lane.
4. In the public `desktop-release` environment, set these **secrets**:

| Secret | Value/source |
| --- | --- |
| `APPLE_CERTIFICATE_P12_BASE64` | Base64 of the exported Developer ID certificate **and private key** |
| `APPLE_CERTIFICATE_PASSWORD` | Password chosen when exporting the `.p12` |
| `APPLE_TEAM_ID` | Ten-character team ID matching the Developer ID identity |
| `APPLE_NOTARY_KEY_P8_BASE64` | Base64 of the team API key `.p8` |
| `APPLE_NOTARY_KEY_ID` | That API key's Key ID |
| `APPLE_NOTARY_ISSUER_ID` | That team's App Store Connect Issuer ID |

To upload file contents without displaying them, use **operator Bash on macOS**:

```bash
set +x
REPO='Spectra-Scientific-LLC/Spectra-Sherpa'
CERT_FILE='/REPLACE_PRIVATE_PATH/developer-id.p12'
KEY_FILE='/REPLACE_PRIVATE_PATH/AuthKey.p8'
test -f "$CERT_FILE" && test -f "$KEY_FILE" || exit 1
base64 < "$CERT_FILE" | gh secret set APPLE_CERTIFICATE_P12_BASE64 --repo "$REPO" --env desktop-release
base64 < "$KEY_FILE" | gh secret set APPLE_NOTARY_KEY_P8_BASE64 --repo "$REPO" --env desktop-release
gh secret set APPLE_CERTIFICATE_PASSWORD --repo "$REPO" --env desktop-release
gh secret set APPLE_TEAM_ID --repo "$REPO" --env desktop-release
gh secret set APPLE_NOTARY_KEY_ID --repo "$REPO" --env desktop-release
gh secret set APPLE_NOTARY_ISSUER_ID --repo "$REPO" --env desktop-release
gh secret list --repo "$REPO" --env desktop-release
```

The four commands without file input prompt for their values. Alternatively,
enter those four secrets in GitHub's environment UI. Keep the original private
files in the owner's credential vault, never in the repository or release assets.

**Expected.** All six secret **names** appear. No secret values are printed.
The first signed run must still prove certificate import, team matching and
notarization authorization; merely listing secrets cannot establish that.

Sources: [Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates),
[team API keys](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api),
and [notarization authentication](https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool).

### A3. Configure Azure Artifact Signing and federation

**Action — Azure portal.** Use the existing signing resources where available.

1. Confirm the Artifact Signing account's identity validation is approved and
   select the intended **Public Trust** certificate profile. Record its region
   endpoint, account name, profile name and full certificate subject DN.
2. Create or select the Microsoft Entra application/service principal that this
   GitHub workflow will use. Record its **Application (client) ID**, tenant ID
   and the signing subscription ID. Do not confuse the application's object ID
   with its client ID.
3. Assign **Artifact Signing Certificate Profile Signer** to this service
   principal at the intended certificate profile scope. Some interfaces still
   use the older Trusted Signing name. Subscription access alone does not grant
   certificate signing. Allow role assignments time to propagate.
4. On that application's **Certificates & secrets → Federated credentials**, add
   a GitHub Actions credential for the public repository and environment:

| Field | Exact value |
| --- | --- |
| Issuer | `https://token.actions.githubusercontent.com` |
| Audience | `api://AzureADTokenExchange` |
| Subject | `repo:Spectra-Scientific-LLC/Spectra-Sherpa:environment:desktop-release` |

No Azure client secret is required. Names and case must match. A subject naming
`spectra`, `main`, or another environment will not match. This assumes GitHub's
default environment-based OIDC subject; resolve any organization-level subject
customization before proceeding, without logging raw identity tokens.

In GitHub's public `desktop-release` environment, add these **variables**:

| Variable | Value/source |
| --- | --- |
| `AZURE_CLIENT_ID` | Entra application client ID from step 2 |
| `AZURE_TENANT_ID` | Tenant containing that application and signing authority |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the signing resource |
| `AZURE_ENDPOINT` | Account's regional signing endpoint, copied from Azure |
| `AZURE_ACCOUNT_NAME` | Artifact Signing account name |
| `AZURE_CERTIFICATE_PROFILE_NAME` | Public Trust certificate profile name |
| `WINDOWS_SIGNING_SUBJECT` | Full expected certificate subject DN, including punctuation and order |

**Verify — operator Bash:**

```bash
REPO='Spectra-Scientific-LLC/Spectra-Sherpa'
gh variable list --repo "$REPO" --env desktop-release
```

Compare all seven values with Azure. Compare the federation's issuer, audience
and subject with the table. Do not use the rotating leaf certificate thumbprint
as `WINDOWS_SIGNING_SUBJECT`.

**Expected.** The selected service principal has signing permission on the
correct profile, and GitHub values identify those resources. The live job must
still pass both Azure login **and** signing; a successful login alone is not
proof of the profile role.

Sources: [Artifact Signing roles](https://learn.microsoft.com/en-us/azure/artifact-signing/concept-resources-roles),
[Azure OIDC setup](https://github.com/Azure/artifact-signing-action/blob/main/docs/OIDC.md).

### A4. Prepare acceptance machines and ownership

**Action.** Reserve a clean Windows x64 machine and an Apple Silicon Mac, or
fresh VM snapshots where supported. Record the exact OS versions. Use dedicated
test accounts with no previous Sherpa profile or prior trust override. Keep
normal SmartScreen/Gatekeeper and institutional policies enabled.

For this first release, prepare a separate upgrade-test snapshot with the
existing unsigned Windows installation and a complete, disposable copy of its
affected profile. Future releases use the prior signed installer as well. Stop the
source application before copying its entire profile, including external
assets and database sidecars. Keep the sole original untouched.

Name the release maintainer and acceptance approver. The maintainer owns weekly
dependency review, maintenance releases and urgent security triage. Updates are
signed installers chosen by the user or IT; the app has no update feed.

**Expected.** Clean-install and upgrade tests have separate recoverable test
states. No test requires the owner's only profile or a production folder watch.

## B. Build each signed candidate

### B1. Publish reviewed source to the public repository

**Action — release maintainer with monorepo access.** Confirm the intended version
and changelog are committed, required CI is green, and the package includes the
reviewed signing changes. From an operator workstation:

```bash
gh workflow run oss-publish.yml --repo Spectra-Scientific-LLC/spectra --ref main -f confirm=publish
gh run list --repo Spectra-Scientific-LLC/spectra --workflow oss-publish.yml --limit 5
```

Open that run. Inspect its `oss-release` plan/report and exact `oss-release.diff`
**before** approving the `oss-publish` environment. Publication is curated and
append-only. After publication, merge the corresponding release-map PR through
its normal review and verify public repository CI.

**Expected.** The reviewed code reaches the public repo, where
`.github/workflows/desktop-release.yml` is at repository root. A workflow inside
`packages/spectra-sherpa/.github/` in the monorepo cannot itself run a public
release. Do not tag until public CI and publication review are complete.

### B2. Tag the exact public commit

**Action — operator Bash in a clean public-repository checkout.** Clone the public
repo once if needed, then use its checkout for this block:

```bash
git remote get-url origin
git fetch origin --tags
git switch main
git pull --ff-only
REPO='Spectra-Scientific-LLC/Spectra-Sherpa'
VERSION='REPLACE_WITH_REVIEWED_VERSION'
TAG="spectra-sherpa-v$VERSION"
SOURCE_COMMIT=$(git rev-parse HEAD)
test -z "$(git status --porcelain)" || { echo 'Checkout must be clean'; exit 1; }
git grep -n -E '^version =|__version__ =|"version":' -- pyproject.toml src/spectra_sherpa/__init__.py desktop/electron/package.json
printf 'Candidate: %s\nSource: %s\n' "$TAG" "$SOURCE_COMMIT"
```

**Expected.** `origin` is the public repository, the printed source matches the
approved public commit, and the Python and Electron versions equal `VERSION`.
Use an actual release version, not the placeholder. If any differs, stop and
correct/review the version before tagging.

After that comparison, create the tag:

```bash
if git rev-parse --verify --quiet "refs/tags/$TAG" >/dev/null; then
  echo 'Tag exists: do not move or reuse it'; exit 1
fi
git tag -a "$TAG" -m "Signed desktop candidate $VERSION" "$SOURCE_COMMIT"
git push origin "refs/tags/$TAG"
gh run list --repo "$REPO" --workflow desktop-release.yml --limit 5
```

**Expected.** A tag-push run first qualifies the Ubuntu AppImage, then starts two protected signed builds: `macos-arm64` and
`windows-x86_64`. Review the tag/source and approve their `desktop-release`
environment requests. A later upload job may require another environment
approval. The run creates a **draft**, never public availability automatically.

For a deliberately artifact-only rehearsal, the workflow can be dispatched from
an **existing tag**, with that same tag as the input. Branch dispatch is refused.
Manual dispatch does not create a draft release; use the tag-push route above
for the normal candidate procedure. Do not run both routes unnecessarily.

### B3. Verify the run and retain its evidence

**Action — operator Bash.** Select the run associated with the intended tag:

```bash
RUN_ID='REPLACE_WITH_RUN_ID'
gh run watch "$RUN_ID" --repo "$REPO" --exit-status
gh run view "$RUN_ID" --repo "$REPO" --json headSha,conclusion,url
mkdir -p "evidence/$TAG"
gh run download "$RUN_ID" --repo "$REPO" --pattern 'signing-evidence-*' --dir "evidence/$TAG/signing"
gh run view "$RUN_ID" --repo "$REPO" --log > "evidence/$TAG/build.log"
gh release view "$TAG" --repo "$REPO" --json isDraft,assets,url
```

**Expected results:**

| Gate | Required outcome |
| --- | --- |
| Identity | Run's `headSha` equals the approved public `SOURCE_COMMIT` |
| Native checks | Actual packaged frontend, authenticated backend and lifecycle checks pass on both platforms |
| Windows | App/backend/installer/uninstaller signatures, expected publisher, trusted timestamps, installer and uninstaller verification pass |
| macOS | Developer ID signatures, hardened runtime, accepted app and DMG notarization, stapling and platform verification pass |
| Evidence | Mac: both accepted notarization JSON receipts. Windows: native signature inventory, installer/uninstaller receipts, signing/verification logs and install-identity receipt |
| Draft | `isDraft: true`; exactly the four files listed below, bound to one source/version |

Draft files:

- `SpectraSherpa-VERSION-windows-x86_64.exe`
- `SpectraSherpa-VERSION-macos-arm64.dmg`
- `SpectraSherpa-VERSION-ubuntu-x86_64.AppImage`
- `SHA256SUMS`
- `desktop-manifest.json`

In both manifest records, compare tag, source commit, version, size and checksum.
The manifest also records Electron/Python versions and scoped dependency evidence:
the resolved build environment is **not** an exact frozen-file inventory.
Retain the workflow artifacts now: signing evidence expires after 30 days and
candidate build artifacts after 14 days under the current workflow.

A green run is necessary but not sufficient. Continue on the clean machines.

## C. Windows: validate the actual signed installer

### C1. Browser download and checksum

**Action.** On the clean Windows x64 test account, use a normal browser to open
the draft release while signed in with repository access. Download the `.exe`,
`SHA256SUMS` and manifest into the same new folder. Keep the browser's downloaded
files: CLI copies may omit the Mark of the Web needed for realistic SmartScreen
validation. Do not unblock the executable or disable protection.

**Windows PowerShell**, with the actual download folder and version:

```powershell
$ErrorActionPreference = 'Stop'
$Version = 'REPLACE_WITH_REVIEWED_VERSION'
$CandidateDir = 'C:\REPLACE_WITH_DOWNLOAD_FOLDER'
$Installer = Join-Path $CandidateDir "SpectraSherpa-$Version-windows-x86_64.exe"
$Leaf = Split-Path $Installer -Leaf
$Lines = @(Get-Content (Join-Path $CandidateDir 'SHA256SUMS') | Where-Object { $_ -match ('\s+\*?' + [regex]::Escape($Leaf) + '$') })
if ($Lines.Count -ne 1) { throw 'Expected exactly one checksum entry' }
$ExpectedHash = ($Lines[0] -split '\s+')[0]
$ActualHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
if ($ActualHash -ne $ExpectedHash) { throw 'Installer checksum mismatch' }
Get-Content -LiteralPath $Installer -Stream Zone.Identifier
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture
```

**Expected.** Hash matches; OS is x64; the browser download carries Internet-zone
metadata. If zone metadata is absent, document the transport and repeat the
browser-download trust test; do not substitute a successful CLI launch for it.

### C2. Install and launch normally, then verify the publisher

**Action.** Double-click the downloaded installer. Capture the first SmartScreen
and installer screens. Follow normal installation, then launch from Start Menu.
Do not use a terminal, browser URL, Python or Node to start the application.

**Expected.** The installer identifies the intended publisher; the native app
window opens with no browser/port/runtime setup. Unknown-publisher, damaged-file,
policy-block or reputation warnings are deviations to record, not prompts to
bypass and count as a clean pass. A reputation warning can occur despite a valid
signature; distinguish it from a cryptographic failure in the report.

After the first-launch observation, verify signatures in **Windows PowerShell**:

```powershell
$ExpectedPublisher = 'REPLACE_WITH_FULL_WINDOWS_SIGNING_SUBJECT'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\SpectraSherpa'
$Files = @((Get-Item -LiteralPath $Installer))
foreach ($RelativePath in @('SpectraSherpa.exe', 'resources/backend/SpectraSherpa.exe', 'unins000.exe')) {
  $Files += Get-Item -LiteralPath (Join-Path $InstallRoot $RelativePath) -ErrorAction Stop
}
$Results = foreach ($File in $Files) {
  $Sig = Get-AuthenticodeSignature -LiteralPath $File.FullName
  if ($Sig.Status -ne 'Valid' -or $Sig.SignerCertificate.Subject -ne $ExpectedPublisher -or -not $Sig.TimeStamperCertificate) {
    throw "Signature, publisher or timestamp failure: $($File.FullName)"
  }
  [pscustomobject]@{ Path = $File.FullName; Status = $Sig.Status; Publisher = $Sig.SignerCertificate.Subject; Thumbprint = $Sig.SignerCertificate.Thumbprint; SHA256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash }
}
$Results | Export-Csv (Join-Path $CandidateDir 'windows-signatures.csv') -NoTypeInformation
```

**Expected.** These four publisher-owned files verify
with the expected publisher and a timestamp. CI separately retains SignTool
`/pa /all` verification. Customers do not need a Windows SDK installed.

Third-party dependencies are outside this publisher check. If a customer later
reports a WDAC/AppLocker dependency block, capture its policy/event evidence and
assess broader signing then; it is not a first-release acceptance requirement.

### C3. Upgrade and uninstall on disposable state

**Action.** This is the first signed release: no previous signed release is
required. On a separate snapshot, use the existing unsigned Windows installation
and a disposable copy of its profile as the migration baseline. Record it and
quit, then install the candidate over it without uninstalling first. Launch
normally. For future releases, repeat using the previous signed version.

On the operator's reviewed public checkout, the read-only helper
`desktop/verify_windows_identity.ps1` can be copied to the test machine. Record
its source commit and run it before and after replacement:

```powershell
# Run once before replacement, then again with $Phase = 'after'.
$Phase = 'before'
.\verify_windows_identity.ps1 | Set-Content -Encoding utf8 "windows-install-identity-$Phase.json"
```

**Expected.** Exactly one `Spectra Sherpa_is1` installation; retained AppId,
per-user install/profile locations and intended publisher; only the expected
version change. Profiles open and intended migrations are explained. Complete
E's custody checks, including the affected classifier profile, before accepting.

Uninstall through Windows Settings → Installed apps on this disposable account.
Decline optional profile deletion if offered. Confirm the application entry and
binaries are removed, while the complete profile and its saved work remain.
Reinstall the same candidate and confirm the saved work reopens.

## D. macOS: validate the actual signed DMG

### D1. Browser download, checksum and normal installation

**Action.** On a clean Apple Silicon test account, download the DMG, `SHA256SUMS`
and manifest from the same draft with Safari or another normal browser. Preserve
quarantine metadata; do not remove it or use a Gatekeeper override.

**macOS Terminal** (Bash-compatible):

```bash
VERSION='REPLACE_WITH_REVIEWED_VERSION'
CANDIDATE_DIR='/REPLACE_WITH_DOWNLOAD_FOLDER'
DMG="$CANDIDATE_DIR/SpectraSherpa-$VERSION-macos-arm64.dmg"
uname -m
sw_vers
cd "$CANDIDATE_DIR"
grep "  SpectraSherpa-$VERSION-macos-arm64.dmg$" SHA256SUMS > macos-checksum.txt
test "$(wc -l < macos-checksum.txt | tr -d ' ')" = 1 || exit 1
shasum -a 256 -c macos-checksum.txt
xattr -p com.apple.quarantine "$DMG"
```

**Expected.** Architecture is `arm64`, checksum is `OK`, and quarantine metadata
is present. Record the OS version and values.

Double-click the DMG in Finder, drag SpectraSherpa to Applications, eject the
image, and launch the installed app from Applications. Capture the first-open
system dialog. A normal Internet-download confirmation can be expected; an
unidentified-developer, damaged-app or malware refusal is a failed gate. Do not
use “Open Anyway” or disable Gatekeeper to turn a refusal into a pass.

**Expected.** The native workbench starts without a terminal, separate browser,
manual port selection or runtime installation.

### D2. Verify the installed app, DMG and stapled tickets

After recording first-open behavior, use **macOS Terminal**:

```bash
APP='/Applications/SpectraSherpa.app'
codesign --verify --deep --strict "$APP"
codesign -dv --verbose=4 "$APP" 2>&1 | tee "$CANDIDATE_DIR/macos-signing-identity.txt"
spctl --assess --type execute --verbose=2 "$APP"
codesign --verify --strict "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
```

**Expected.** Verification succeeds; the displayed authority is the intended
Developer ID Application identity and TeamIdentifier equals `APPLE_TEAM_ID`;
the runtime flag is present; assessments accept the app and disk image.

On a signing-validation Mac with Xcode Command Line Tools available, also run:

```bash
xcrun stapler validate "$APP"
xcrun stapler validate "$DMG"
```

**Expected.** Both tickets validate. These diagnostic tools are not an app
runtime requirement. If the clean machine lacks them, retain its untouched
first-launch observation and perform this diagnostic on the same checksummed
artifact on the validation Mac; retain the CI stapling receipts as well.

### D3. Upgrade and uninstall on disposable state

**Action.** On an upgrade-test snapshot, quit the old app, preserve a complete
copy of its profile, and replace the old Applications bundle with the candidate
through Finder. Launch normally and perform E's custody checks.

For the first Electron transition, test the prior browser-shell installation.
For subsequent releases, test the prior Electron release too. If no previous
signed native release exists yet, mark native-to-native upgrade as **not yet
applicable**, not “passed.”

Quit the app, move only its application bundle to Trash, and leave
`~/.spectra_sherpa` intact. Reinstall the same candidate and reopen the saved work.

**Expected.** The old bundle is replaced, saved data remains, and no backend from
the old app stays running. Reinstallation opens the retained profile.

## E. Shared scientific and lifecycle acceptance

Run this section separately on Windows and Mac. Record the exact input files,
workflow/model settings, run IDs and output files so a deviation can be replayed.
Use synthetic or approved public fixtures; private owner data stays local.

### E1. A small reproducible model round trip

Create `training.csv` with this content (a text editor is sufficient):

```csv
sample_id,x1,x2,response
S01,0,1,3
S02,1,0,5
S03,2,3,7
S04,3,1,9
S05,4,4,11
S06,5,2,13
S07,6,5,15
S08,7,0,17
```

Create `prediction.csv`:

```csv
sample_id,x1,x2
P01,8,2
P02,9,4
```

Import through the app's normal data controls. Explicitly assign `sample_id` as
sample identity, `x1`/`x2` as features, and `response` as the regression target.
If the importer requires separate feature/target files, split the columns using
its documented path and retain those exact files and bindings. Never treat
`response` as an input feature or the label column as numeric data.

1. Inspect the table: eight samples, two features, one target; no missing values.
2. Fit PLS regression with two components and mean centering, without an extra
   normalization or derivative. Save the workflow/run and record effective
   parameters and sample/feature mappings.
3. Apply the model to the two prediction rows with the same feature order.
   The synthetic relation is `response = 2*x1 + 3`: expected predictions are
   **P01 = 19, P02 = 21**, with absolute error at most `1e-6` for this fixture.
4. Export the fitted model, import it into a new local project, and predict those
   same two rows. Compare row identities, target meaning and predictions with
   step 3, using the same tolerance. Save both exports.
5. Quit normally, reopen from Start Menu/Applications, and verify the saved
   project, workflow, model and result are still available.

**Expected.** The scientific path completes through native controls, with matching
predictions and retained identities. Missing import/export controls, unexplained
parameter changes, feature-order mismatches or inability to bind the target are
acceptance findings; do not route around them with a backend script and mark the
GUI journey passed. This small fixture establishes transport/lifecycle behavior,
not broad chemometric method validation.

### E2. Folder watch, close behavior and recovery

| Action | Expected result |
| --- | --- |
| Configure a watch using the imported model and a new disposable input/output folder; record parser/header settings | Native folder chooser works; watch configuration is visible |
| Copy `prediction.csv` into the input folder after enabling the watch | Completed predictions identify P01/P02 and match E1; output is retained |
| Close the window with the watch enabled; choose background operation | Explicit choice, visible tray/menu-bar access, watch continues |
| Restore the window, then explicitly quit | Watch stops; owned backend exits; no silent resident worker |
| Restart normally | Saved watch configuration and prior results remain; inspect its enabled state before adding more files |
| Edit a workflow, attempt to close, then cancel | Unsaved edits and running backend remain |
| Launch the app a second time | Existing window focuses; no competing backend writes to the same profile |
| On disposable state only, terminate the specific owned backend PID in Task Manager/Activity Monitor | App reports loss, retains the window for unsaved work, offers recovery; restart restores service |

Confirm process ownership by installed executable path before the intentional
crash. Never terminate all processes by a shared name or clear a busy port.

### E3. Offline and profile-custody checks

**Offline.** On a fresh snapshot, download the same checksummed candidate, then
disconnect networking **before installation and first application launch**.
Install it offline and launch normally.
Repeat local import, prediction, save/reopen and folder watch. Observe for at
least five minutes using OS/IT network monitoring. Expect no update-feed or
runtime-download requirement. Features intentionally configured for online
access, such as BYOK, are a separate online test. Record any network attempt
rather than assuming offline success proves that none occurred.

**Local-only privacy gate (release blocker).** On a connected snapshot with
OS/IT network monitoring or a logging firewall, launch the installed app from a
fresh profile, import local data, run a workflow, open Settings and quit. Without
configuring a BYOK provider or enabling reference downloads, expect **no**
outbound connection other than OS/Store services. Then confirm:

- Settings → Integrations shows no Spectra Scientific cloud connection.
- `%USERPROFILE%\.spectra_sherpa` (or `~/.spectra_sherpa`) contains
  `credential-key.protected` and no `MASTER_ENCRYPTION_KEY` or plaintext
  `CHAT_ENDPOINT_KEY` in `.env` after saving an AI provider key.
- **Application → Delete all local data…** removes the profile and restarts a
  fresh workbench.

Record the observed destinations. Any unexplained destination blocks release
until the [privacy statement](../support/privacy.md) and the outbound-network allowlist test agree.

**Custody.** With the application stopped, inventory the disposable upgrade
profile before and after: relative paths, sizes and SHA-256 of datasets, raw
spectra, saved models and retained result/export files. Compare the actual
projects, workflows, node/edge identities, run history and provenance records.
List intended schema/classifier migrations separately. Database file hashes may
change legitimately; a matching SQLite byte hash is not the acceptance rule.

For the affected Windows KNN/PLS-DA/SIMCA profile, verify it opens, retained work
is editable, repair notices explain changed validation semantics, and unrelated
artifacts remain unchanged. Check the generated `.profile-upgrades` snapshot
and receipt when an upgrade occurs. A synthetic fresh install cannot substitute
for this copied-profile check.

**Expected.** No unexplained loss or reinterpretation; backups and originals
remain intact. If recovery is needed, use the reviewed
[profile recovery procedure](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/blob/main/desktop/README.md#local-profile-upgrade-and-recovery)
on a separate copy. Reinstalling an older executable is not a database downgrade.

## F. Approval and publication

Create one acceptance record per candidate. Use this template, with evidence
paths or links and explicit `PASS`, `FAIL`, `PENDING`, or justified `N/A`:

| Field/check | Windows | macOS |
| --- | --- | --- |
| Operator / date / OS / architecture | | |
| Version / tag / public source SHA / run URL | | |
| Installer filename / SHA-256 | | |
| Publisher or Developer ID / Team ID | | |
| CI signatures, receipts and manifest checked | | |
| Browser download origin metadata retained | | |
| Normal first install and first launch | | |
| Signature / timestamp or notarization / staple checks | | |
| E1 model round trip and saved-work reopening | | |
| E2 watch / background / cancel / second launch / crash | | |
| E3 offline first launch and network observations | | |
| Old-installer replacement / copied-profile custody | | |
| Native-to-native upgrade (when applicable) | | |
| Uninstall preserves profile; reinstall opens it | | |
| Institutional application-control policy, if in scope | | |
| Deviations / evidence / disposition | | |
| Owner approval of exact candidate bytes | | |

**Action.** Publish only after the owner accepts both target receipts and resolves
any required `FAIL` or `PENDING` item. Keep private profile details and credentials
out of public release notes; summarize the qualification and retained evidence.

**Operator Bash — deliberate publication of the existing draft:**

```bash
REPO='Spectra-Scientific-LLC/Spectra-Sherpa'
TAG='spectra-sherpa-vREPLACE_WITH_ACCEPTED_VERSION'
gh release view "$TAG" --repo "$REPO" --json isDraft,assets,url
gh release edit "$TAG" --repo "$REPO" --draft=false
gh release view "$TAG" --repo "$REPO" --json isDraft,assets,url
```

**Expected.** The same accepted files become public, `isDraft` becomes `false`,
and downloads/checksums remain unchanged. Check the public download surface links
to those assets. Do not rebuild, replace assets or move the tag at publication.

## G. Deviation handling and safe retry

| Observed deviation | Next action |
| --- | --- |
| Environment approval unavailable or branch rejected | Check A1 and use the intended tag; do not widen rules to branches |
| Azure reports no matching federated identity | Compare A3 issuer/audience/exact subject and actual public repository/environment |
| Azure login succeeds but signing is denied | Check profile signer role, tenant, regional endpoint, account/profile and propagation |
| Apple identity missing or team mismatch | Check Developer ID Application certificate plus private key, export password and Team ID |
| Notarization unauthorized or rejected | Check team API key/issuer/permissions, agreements, and retained Apple receipt; do not treat exit zero as acceptance |
| Checksum, signing evidence or native-library signature failure | Stop; preserve logs and exact failed run. Do not skip the gate |
| Valid Windows signature but SmartScreen warning | Record reputation versus policy versus signature failure; resolve the first-launch experience before claiming clean acceptance |
| macOS trust refusal or missing ticket | Preserve quarantine and system message; inspect app/DMG receipts and staples |
| Profile migration or scientific mismatch | Stop using that copy; preserve it and the backup. Report E step, inputs, settings and retained run |
| Existing draft causes upload refusal | Inspect the existing draft and run evidence first; do not clobber assets or silently replace accepted bytes |

For a transient infrastructure or credential-configuration failure, an operator
may rerun failed jobs for the **same immutable source/tag** if no conflicting
draft was created. Any source change needs a new reviewed version/tag and fresh
acceptance. If a failed run left a draft, keep it unpublished and explicitly
review its disposition before retrying; no deletion or overwrite is automatic.

Report: **step ID, tag, public SHA, workflow/run URL, OS, expected result, observed
result, error text and evidence path**. Redact credentials and private scientific
inputs. This makes each deviation actionable without treating an incomplete
signed release as ready.
