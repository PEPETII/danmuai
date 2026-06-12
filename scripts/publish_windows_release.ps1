# Build DanmuAI Windows x64: PyInstaller onedir -> Velopack release bundle.
# Requires: Windows, Python 3.12+, .NET SDK, vpk (dotnet tool install -g vpk)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ReleaseRoot = Join-Path $Root "release"
$VelopackDir = Join-Path $ReleaseRoot "velopack"
$DistDir = Join-Path $Root "dist\DanmuAI"
$VersionFile = Join-Path $VelopackDir "VERSION.txt"

& (Join-Path $Root "scripts\build_exe.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "build_exe.ps1 failed"
}

if (-not (Test-Path (Join-Path $DistDir "DanmuAI.exe"))) {
    Write-Error "Missing $(Join-Path $DistDir 'DanmuAI.exe') after build"
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
if (Test-Path $VelopackDir) {
    Remove-Item -LiteralPath $VelopackDir -Recurse -Force
}

$packResult = & (Join-Path $Root "scripts\velopack_pack.ps1") -PackDir $DistDir -OutputDir $VelopackDir

$gitSha = "unknown"
try {
    $gitSha = (git -C $Root rev-parse --short HEAD 2>$null)
} catch { }
$builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$appVersion = $packResult.Version

@(
    "DanmuAI Windows x64 (PyInstaller onedir + Velopack)"
    "Version: $appVersion"
    "Built (UTC): $builtAt"
    "Git: $gitSha"
    "Changelog: docs/operations/CHANGELOG.md"
    ""
    "Velopack outputs in this folder:"
    "  PEPETII.DanmuAI-win-Setup.exe"
    "  PEPETII.DanmuAI-$appVersion-Setup.exe"
    "  PEPETII.DanmuAI-$appVersion-full.nupkg"
    "  releases.win.json"
    ""
    "Primary download (after R2 upload): https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
    "Update feed: https://updates.qiaoqiao.buzz/releases/win/stable"
) | Set-Content -LiteralPath $VersionFile -Encoding utf8

Write-Host ""
Write-Host "Done."
Write-Host "  Output:   $VelopackDir"
Write-Host "  Setup:    $($packResult.SetupExe)"
Write-Host "  Versioned: $($packResult.VersionedSetup)"
Write-Host "  Nupkg:    $($packResult.FullNupkg)"
Write-Host "  Feed:     $($packResult.FeedJson)"
if ($packResult.PortableZip) {
    Write-Host "  Portable: $($packResult.PortableZip)"
}
