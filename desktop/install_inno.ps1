# Official upstream 6.3.3 asset; digest verified against the GitHub release metadata.
$ErrorActionPreference = 'Stop'
$Uri = 'https://github.com/jrsoftware/issrc/releases/download/is-6_3_3/innosetup-6.3.3.exe'
$ExpectedHash = '0bcb2a409dea17e305a27a6b09555cabe600e984f88570ab72575cd7e93c95e6'
$Installer = Join-Path $env:RUNNER_TEMP 'innosetup-6.3.3.exe'
$InstallDir = Join-Path $env:RUNNER_TEMP ('spectra-inno-' + [guid]::NewGuid().ToString())
try {
    Invoke-WebRequest -Uri $Uri -OutFile $Installer
    if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
        throw 'Inno Setup download checksum mismatch'
    }
    $Process = Start-Process -FilePath $Installer -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$InstallDir`"" -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw 'Inno Setup installation failed' }
    # ISCC's PE version resource is not the compiler engine version. Bind the
    # build to the fresh installation of the checksum-verified asset instead.
    $Compiler = Join-Path $InstallDir 'ISCC.exe'
    if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'Pinned Inno compiler missing' }
    $env:INNO_ISCC_PATH = $Compiler
    "INNO_ISCC_PATH=$Compiler" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
} finally {
    Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue
}
