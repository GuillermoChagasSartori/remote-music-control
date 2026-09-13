# Install Inno Setup 7 for the current user (no administrator rights needed).
# Used by CI before packaging\build.ps1; works on a developer PC too.
# ASCII only: Windows PowerShell 5 misreads UTF-8 files without a BOM.

$ErrorActionPreference = 'Stop'
$version = '7.1.0'
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
if (Test-Path $iscc) {
    Write-Host "Inno Setup already installed: $iscc"
    exit 0
}

$tag = 'is-' + $version.Replace('.', '_')
$setup = Join-Path $env:TEMP "innosetup-$version-x64.exe"
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/jrsoftware/issrc/releases/download/$tag/innosetup-$version-x64.exe" -OutFile $setup

# Refuse to run a download whose digital signature is missing or broken.
$signature = Get-AuthenticodeSignature $setup
if ($signature.Status -ne 'Valid') { throw "Inno Setup installer signature is $($signature.Status)" }
Write-Host "signed by: $($signature.SignerCertificate.Subject)"

$process = Start-Process $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER', '/NORESTART', '/SP-' -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path $iscc)) { throw "Inno Setup install failed (exit code $($process.ExitCode))" }
Write-Host "installed $iscc"
