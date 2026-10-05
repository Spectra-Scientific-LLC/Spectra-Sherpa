# Shared by the release workflow and Inno Setup compiler wrapper.
function Get-DesktopSignTool {
    $Candidates = @(Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue)
    $Selected = $Candidates | Sort-Object { [version]$_.Directory.Parent.Name } -Descending | Select-Object -First 1
    if (-not $Selected) { throw "Windows SDK x64 SignTool was not found" }
    return $Selected.FullName
}

function Assert-DesktopSignature {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSubject)
    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Signature.Status -ne "Valid") { throw "Invalid Authenticode signature: $Path" }
    if ($Signature.SignerCertificate.Subject -ne $ExpectedSubject) { throw "Unexpected signing publisher: $Path" }
    if (-not $Signature.TimeStamperCertificate) { throw "Missing trusted timestamp: $Path" }
    $SignTool = Get-DesktopSignTool
    New-Item -ItemType Directory -Force desktop/signing-evidence | Out-Null
    & $SignTool verify /pa /all /v $Path 2>&1 | Tee-Object -FilePath desktop/signing-evidence/windows-verification.log -Append | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "SignTool verification failed: $Path" }
    return $Signature.SignerCertificate.Thumbprint
}

function Sign-DesktopNativeExecutables {
    param(
        [Parameter(Mandatory)][string]$BundleRoot,
        [Parameter(Mandatory)][string]$DlibPath,
        [Parameter(Mandatory)][string]$MetadataPath,
        [Parameter(Mandatory)][string]$ExpectedSubject
    )
    $ErrorActionPreference = "Stop"
    foreach ($Required in @("SpectraSherpa.exe", "resources\backend\SpectraSherpa.exe")) {
        if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot $Required))) {
            throw "Incomplete native application: $Required"
        }
    }
    node "$PSScriptRoot/electron/harden.cjs" (Join-Path $BundleRoot "SpectraSherpa.exe") --verify
    if ($LASTEXITCODE -ne 0) { throw "Native release fuse policy is not satisfied" }
    $SignTool = Get-DesktopSignTool
    $Receipts = @()
    New-Item -ItemType Directory -Force desktop/signing-evidence | Out-Null
    foreach ($Executable in Get-DesktopNativeBinaries -BundleRoot $BundleRoot) {
        & $SignTool sign /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 /dlib $DlibPath /dmdf $MetadataPath $Executable.FullName 2>&1 | Tee-Object -FilePath desktop/signing-evidence/windows-signing.log -Append | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Native executable signing failed" }
        $Receipt = Get-DesktopSignatureReceipt -Path $Executable.FullName -ExpectedSubject $ExpectedSubject
        $Receipt.relative_path = [System.IO.Path]::GetRelativePath((Resolve-Path $BundleRoot).Path, $Executable.FullName).Replace("\", "/")
        $Receipts += $Receipt
    }
    $Receipts | ConvertTo-Json -Depth 5 -AsArray | Set-Content desktop/signing-evidence/windows-native-signatures.json
}

function Get-DesktopNativeBinaries {
    param([Parameter(Mandatory)][string]$BundleRoot)
    # First-release publisher scope: our app entry point and packaged backend.
    # Do not replace third-party signatures or sign dependency DLL/PYD/NODE files.
    foreach ($RelativePath in @('SpectraSherpa.exe', 'resources/backend/SpectraSherpa.exe')) {
        Get-Item -LiteralPath (Join-Path $BundleRoot $RelativePath) -ErrorAction Stop
    }
}

function Get-DesktopSignatureReceipt {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSubject)
    $Thumbprint = Assert-DesktopSignature -Path $Path -ExpectedSubject $ExpectedSubject
    return @{
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        publisher = $ExpectedSubject
        thumbprint = $Thumbprint
        timestamp_verified = $true
        authenticode_verified = $true
        signtool_verified = $true
    }
}

# Store submissions require trusted signatures on every bundled PE, including
# Python extensions and vendor helpers. Detect the format, not only extensions.
function Get-DesktopPortableExecutables {
    param([Parameter(Mandatory)][string]$BundleRoot)
    $Root = Get-Item -LiteralPath $BundleRoot -ErrorAction Stop
    $Entries = @($Root) + @(Get-ChildItem -LiteralPath $Root.FullName -Recurse -Force)
    foreach ($Entry in $Entries) {
        if ($Entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Store bundle contains a reparse point: $($Entry.FullName)"
        }
    }
    foreach ($File in $Entries | Where-Object { -not $_.PSIsContainer } | Sort-Object FullName) {
        $Stream = [IO.File]::OpenRead($File.FullName)
        $Reader = [IO.BinaryReader]::new($Stream)
        try {
            $IsPE = $false
            if ($Stream.Length -ge 64 -and $Reader.ReadUInt16() -eq 0x5a4d) {
                $Stream.Position = 60
                $Offset = $Reader.ReadUInt32()
                if ($Offset -ge 64 -and $Offset -le ($Stream.Length - 24)) {
                    $Stream.Position = $Offset
                    $IsPE = $Reader.ReadUInt32() -eq 0x00004550
                }
                if (-not $IsPE) { throw "Malformed PE candidate: $($File.FullName)" }
            }
            if ($IsPE) { $File }
            elseif ($File.Extension -in @('.exe', '.dll', '.pyd', '.node', '.sys', '.ocx', '.scr', '.cpl')) {
                throw "Native extension without a PE header: $($File.FullName)"
            }
        } finally { $Reader.Dispose() }
    }
}

function Assert-DesktopStoreBundle {
    param(
        [Parameter(Mandatory)][string]$BundleRoot,
        [Parameter(Mandatory)][string]$ReceiptPath,
        [Parameter(Mandatory)][string]$ExpectedSubject,
        [switch]$SignUnsigned,
        [string]$DlibPath,
        [string]$MetadataPath
    )
    $ErrorActionPreference = 'Stop'
    if ($SignUnsigned -and (-not $DlibPath -or -not $MetadataPath)) {
        throw 'Store signing requires provider DLL and metadata'
    }
    $Root = (Resolve-Path -LiteralPath $BundleRoot).Path
    $SignTool = Get-DesktopSignTool
    $Binaries = @(Get-DesktopPortableExecutables -BundleRoot $Root)
    if (-not $Binaries.Count) { throw 'Store bundle contains no PE files' }
    $Records = foreach ($File in $Binaries) {
        $Before = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $Signature = Get-AuthenticodeSignature -LiteralPath $File.FullName
        $Added = $false
        if ($Signature.Status -eq 'NotSigned' -and $SignUnsigned) {
            & $SignTool sign /fd SHA256 /tr 'http://timestamp.acs.microsoft.com' /td SHA256 /dlib $DlibPath /dmdf $MetadataPath $File.FullName | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "Store PE signing failed: $($File.FullName)" }
            Assert-DesktopSignature -Path $File.FullName -ExpectedSubject $ExpectedSubject | Out-Null
            $Added = $true
            $Signature = Get-AuthenticodeSignature -LiteralPath $File.FullName
        }
        # Never repair a damaged/untrusted vendor signature by overwriting it.
        if ($Signature.Status -ne 'Valid') { throw "Store PE signature is not trusted: $($File.FullName) ($($Signature.Status))" }
        & $SignTool verify /pa /all /v $File.FullName | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Store PE trust verification failed: $($File.FullName)" }
        $After = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if (-not $Added -and $Before -ne $After) { throw 'Vendor-signed bytes changed during verification' }
        [ordered]@{
            relative_path = [IO.Path]::GetRelativePath($Root, $File.FullName).Replace('\', '/')
            sha256_before = $Before
            sha256 = $After
            publisher = $Signature.SignerCertificate.Subject
            thumbprint = $Signature.SignerCertificate.Thumbprint
            signature_added = $Added
            authenticode_verified = $true
            signtool_verified = $true
            timestamp_present = [bool]$Signature.TimeStamperCertificate
        }
    }
    New-Item -ItemType Directory -Force (Split-Path -Parent $ReceiptPath) | Out-Null
    ConvertTo-Json -InputObject @($Records) -Depth 5 | Set-Content -LiteralPath $ReceiptPath
}
