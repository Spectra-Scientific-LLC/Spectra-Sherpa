param (
    [switch]$Signed,
    [switch]$NativeShell,
    [string]$DlibPath,
    [string]$MetadataPath
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows_signing.ps1"

# Get the app version dynamically
$AppVersion = python -c "from spectra_sherpa import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or -not $AppVersion) {
    throw "Failed to extract application version from spectra_sherpa.__version__."
}

Write-Host "Compiling installer for Spectra Sherpa v$AppVersion"

$ISCC_ARGS = @(
    "/DAppVersionString=$AppVersion"
)

if ($NativeShell) {
    $NativeExe = "desktop\electron\out\SpectraSherpa-win32-x64\SpectraSherpa.exe"
    if (-not (Test-Path -LiteralPath $NativeExe)) { throw "Missing packaged native shell" }
    node desktop/electron/harden.cjs $NativeExe --verify
    if ($LASTEXITCODE -ne 0) { throw "Native release hardening verification failed" }
    $ISCC_ARGS += "/DNativeShell=1"
}

if ($Signed) {
    if (-not $DlibPath -or -not $MetadataPath) {
        throw "-DlibPath and -MetadataPath are required when -Signed is specified."
    }
    if (-not (Test-Path -LiteralPath $DlibPath) -or -not (Test-Path -LiteralPath $MetadataPath)) {
        throw "Signing library or metadata file does not exist"
    }
    $SignTool = Get-DesktopSignTool
    Write-Host "Adding Azure Code Signing SignTool directive..."
    # Inno expands $q after parsing its command line. Embedded literal quotes
    # can split this /S argument under Windows native argument handling.
    $ISCC_ARGS += ('/SAzureSign=$q{0}$q sign /v /fd SHA256 /tr $qhttp://timestamp.acs.microsoft.com$q /td SHA256 /dlib $q{1}$q /dmdf $q{2}$q $f' -f $SignTool, $DlibPath, $MetadataPath)
    $ISCC_ARGS += "/DSignToolName=AzureSign"
}

$ISCC_PATH = if ($env:INNO_ISCC_PATH) { $env:INNO_ISCC_PATH } else { "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $ISCC_PATH)) {
    throw "ISCC not found at $ISCC_PATH. Please ensure Inno Setup 6 is installed."
}

# Construct the full command to log it before executing
$Command = "& `"$ISCC_PATH`""
foreach ($Arg in $ISCC_ARGS) {
    $Command += " `"$Arg`""
}
$Command += " `"desktop\windows_installer.iss`""

Write-Host "Running: $Command"
if ($Signed) {
    New-Item -ItemType Directory -Force desktop/signing-evidence | Out-Null
    & $ISCC_PATH $ISCC_ARGS "desktop\windows_installer.iss" 2>&1 | Tee-Object -FilePath desktop/signing-evidence/windows-installer-signing.log | Out-Host
} else {
    & $ISCC_PATH $ISCC_ARGS "desktop\windows_installer.iss"
}
if ($LASTEXITCODE -ne 0) {
    throw "ISCC compilation failed with exit code $LASTEXITCODE"
}

Write-Host "Successfully built Windows installer."
