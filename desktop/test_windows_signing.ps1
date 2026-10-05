# Orchestration regression only: provider and OS signature calls are synthetic.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/windows_signing.ps1"
$Scratch = Join-Path $env:RUNNER_TEMP ([guid]::NewGuid().ToString())
New-Item -ItemType Directory $Scratch | Out-Null
Push-Location $Scratch
try {
    $script:Signed = @()
    $script:InvalidTimestamp = $false
    $script:RefuseSign = $false
    function Get-DesktopSignTool { return 'Invoke-FakeSignTool' }
    function Invoke-FakeSignTool {
        $global:LASTEXITCODE = 0
        if ($args[0] -eq 'sign') {
            $script:Signed += $args[-1]
            if ($script:RefuseSign) { $global:LASTEXITCODE = 1 }
        }
        Write-Output 'synthetic provider output'
    }
    function node { $global:LASTEXITCODE = 0 }
    function Get-AuthenticodeSignature {
        param([string]$LiteralPath)
        return [pscustomobject]@{
            Status = 'Valid'
            SignerCertificate = [pscustomobject]@{ Subject = 'synthetic publisher'; Thumbprint = ('a' * 40) }
            TimeStamperCertificate = $(if ($script:InvalidTimestamp) { $null } else { 'synthetic timestamp' })
        }
    }
    $Bundle = Join-Path $Scratch 'bundle'
    foreach ($Name in @('SpectraSherpa.exe', 'resources/backend/SpectraSherpa.exe', 'electron.dll', 'numpy.pyd', 'addon.node', 'upper.DLL', 'vendor.exe', 'readme.txt')) {
        $Path = Join-Path $Bundle $Name
        New-Item -ItemType Directory -Force (Split-Path $Path) | Out-Null
        Set-Content -LiteralPath $Path -Value 'synthetic PE fixture'
    }
    Sign-DesktopNativeExecutables -BundleRoot $Bundle -DlibPath synthetic.dll -MetadataPath synthetic.json -ExpectedSubject 'synthetic publisher'
    if ($script:Signed.Count -ne 2) { throw 'Expected exactly two owned executables' }
    $Expected = @('SpectraSherpa.exe', 'resources/backend/SpectraSherpa.exe') | ForEach-Object { (Get-Item (Join-Path $Bundle $_)).FullName }
    if (@(Compare-Object $Expected $script:Signed).Count) { throw 'Signed a dependency or missed an owned executable' }
    if ($script:Signed | Where-Object { $_.EndsWith('.txt') }) { throw 'Signed non-native data' }
    $Records = @(Get-Content desktop/signing-evidence/windows-native-signatures.json -Raw | ConvertFrom-Json)
    if ($Records.Count -ne 2) { throw 'Missing signature receipts' }
    if (@($Records | Where-Object { $_.sha256.Length -ne 64 -or -not $_.timestamp_verified }).Count) { throw 'Invalid receipt' }
    if (-not (Test-Path desktop/signing-evidence/windows-verification.log)) { throw 'Missing verification output' }
    $script:InvalidTimestamp = $true
    $Rejected = $false
    try { Assert-DesktopSignature -Path "$Bundle/SpectraSherpa.exe" -ExpectedSubject 'synthetic publisher' | Out-Null }
    catch { if ($_.Exception.Message -notlike 'Missing trusted timestamp:*') { throw }; $Rejected = $true }
    if (-not $Rejected) { throw 'Accepted missing timestamp' }
    $script:InvalidTimestamp = $false
    $script:RefuseSign = $true
    $Rejected = $false
    try { Sign-DesktopNativeExecutables -BundleRoot $Bundle -DlibPath synthetic.dll -MetadataPath synthetic.json -ExpectedSubject 'synthetic publisher' }
    catch { if ($_.Exception.Message -ne 'Native executable signing failed') { throw }; $Rejected = $true }
    if (-not $Rejected) { throw 'Ignored provider signing failure' }
    # The refused-provider case deliberately sets a nonzero native status.
    # Clear it only after its expected exception has been asserted above.
    $global:LASTEXITCODE = 0
    $script:RefuseSign = $false
    $script:Signed = @()
    $script:BrokenVendor = $false
    function Get-AuthenticodeSignature {
        param([string]$LiteralPath)
        $Unsigned = $LiteralPath.EndsWith('numpy.pyd') -and $LiteralPath -notin $script:Signed
        $Status = if ($script:BrokenVendor) { 'HashMismatch' } elseif ($Unsigned) { 'NotSigned' } else { 'Valid' }
        $Subject = if ($LiteralPath -in $script:Signed) { 'synthetic publisher' } else { 'vendor publisher' }
        [pscustomobject]@{
            Status = $Status
            SignerCertificate = [pscustomobject]@{ Subject = $Subject; Thumbprint = ('a' * 40) }
            TimeStamperCertificate = 'synthetic timestamp'
        }
    }
    $PE = [byte[]]::new(128)
    $PE[0] = 0x4d; $PE[1] = 0x5a; $PE[60] = 64; $PE[64] = 0x50; $PE[65] = 0x45
    foreach ($File in Get-ChildItem $Bundle -Recurse -File | Where-Object Extension -ne '.txt') {
        [IO.File]::WriteAllBytes($File.FullName, $PE)
    }
    [IO.File]::WriteAllBytes((Join-Path $Bundle 'extensionless-helper'), $PE)
    if (@(Get-DesktopPortableExecutables $Bundle).Count -ne 8) { throw 'PE inventory missed a native file' }
    $Rejected = $false
    try { Assert-DesktopStoreBundle $Bundle 'desktop/signing-evidence/store.json' 'synthetic publisher' }
    catch { if ($_.Exception.Message -notlike 'Store PE signature is not trusted:*') { throw }; $Rejected = $true }
    if (-not $Rejected) { throw 'Store audit accepted unsigned PE' }
    Assert-DesktopStoreBundle $Bundle 'desktop/signing-evidence/store.json' 'synthetic publisher' -SignUnsigned -DlibPath synthetic.dll -MetadataPath synthetic.json
    if ($script:Signed.Count -ne 1 -or -not $script:Signed[0].EndsWith('numpy.pyd')) { throw 'Store signing modified a valid vendor signature' }
    $StoreRecords = @(Get-Content desktop/signing-evidence/store.json -Raw | ConvertFrom-Json)
    if ($StoreRecords.Count -ne 8) { throw 'Store receipt missed a PE' }
    $script:BrokenVendor = $true
    $Rejected = $false
    try { Assert-DesktopStoreBundle $Bundle 'desktop/signing-evidence/store.json' 'synthetic publisher' -SignUnsigned -DlibPath synthetic.dll -MetadataPath synthetic.json }
    catch { if ($_.Exception.Message -notlike 'Store PE signature is not trusted:*') { throw }; $Rejected = $true }
    if (-not $Rejected -or $script:Signed.Count -ne 1) { throw 'Store signing accepted or replaced an invalid vendor signature' }
    Write-Host 'Windows signing orchestration regression passed (synthetic authority only)'
} finally {
    Pop-Location
    Remove-Item -LiteralPath $Scratch -Recurse -Force
}
