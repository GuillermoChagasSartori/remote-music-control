# Build the Windows installer: dist\RemoteMusicControl-Setup-<version>.exe
#
# Run on Windows from the repository root, on a developer PC or in CI:
#
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Steps: install the build tools (uv's "build" dependency group), bundle the
# app with PyInstaller, fetch Microsoft's WebView2 bootstrapper, and compile
# the installer with Inno Setup. Needs uv and Inno Setup 7 (ISCC.exe).
# ASCII only: Windows PowerShell 5 misreads UTF-8 files without a BOM.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    # Native programs report failure through their exit code, which
    # $ErrorActionPreference doesn't see; stop the build on any failure.
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

Write-Host '== 1/4 Python environment with the build tools'
Invoke-Checked uv @('sync', '--locked', '--group', 'build')
$version = (& uv run python -c "from importlib.metadata import version; print(version('remote-music-control'))").Trim()
Write-Host "version $version"

Write-Host '== 2/4 Bundle the app (PyInstaller)'
Invoke-Checked uv @('run', 'pyinstaller', '--noconfirm', '--clean', '--distpath', 'dist', '--workpath', 'build\pyinstaller', 'packaging\remote-music-control.spec')

Write-Host '== 3/4 WebView2 bootstrapper'
# The small official bootstrapper (about 2 MB). Setup runs it only on PCs
# without WebView2; it downloads the runtime from Microsoft. Microsoft allows
# redistributing it with applications.
$bootstrapper = 'build\MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path $bootstrapper)) {
    New-Item -ItemType Directory -Force build | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper
}
$signature = Get-AuthenticodeSignature $bootstrapper
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') {
    throw "the WebView2 bootstrapper isn't validly signed by Microsoft ($($signature.Status))"
}

Write-Host '== 4/4 Installer (Inno Setup)'
$iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'ISCC.exe (Inno Setup 7) not found' }
Invoke-Checked $iscc @("/DAppVersion=$version", 'packaging\installer.iss')

Get-Item "dist\RemoteMusicControl-Setup-$version.exe" | ForEach-Object {
    Write-Host ("built {0} ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB))
}
