param([string]$ExpectedInstallLocation)
$ErrorActionPreference = "Stop"
# Read-only receipt from an actual installation; do not infer identity from source.
$Roots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
)
$Records = @()
foreach ($Root in $Roots) {
    if (-not (Test-Path $Root)) { continue }
    foreach ($Key in Get-ChildItem $Root) {
        $Record = Get-ItemProperty -LiteralPath $Key.PSPath
        if ($Record.DisplayName -like "Spectra Sherpa*") {
            if ($Key.PSChildName -ne "Spectra Sherpa_is1") { throw "Unexpected installed application identity" }
            if ($ExpectedInstallLocation -and
                $Record.InstallLocation.TrimEnd('\') -ne $ExpectedInstallLocation.TrimEnd('\')) {
                throw "Installed application location changed"
            }
            if (-not (Test-Path -LiteralPath (Join-Path $Record.InstallLocation "SpectraSherpa.exe"))) {
                throw "Installed entry executable is missing"
            }
            $Records += [ordered]@{
                registry_scope = $Root
                app_id = "Spectra Sherpa"
                uninstall_key = $Key.PSChildName
                install_location = $Record.InstallLocation
                version = $Record.DisplayVersion
                publisher = $Record.Publisher
                uninstall_command = $Record.UninstallString
                profile_location = (Join-Path $env:USERPROFILE ".spectra_sherpa")
            }
        }
    }
}
if ($Records.Count -ne 1) { throw "Expected exactly one installed Spectra Sherpa application" }
$Records[0] | ConvertTo-Json
