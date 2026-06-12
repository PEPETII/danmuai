# Velopack POC: wrap dist/DanmuAI/ (PyInstaller onedir) into Setup.exe + full.nupkg.
# Prerequisite: .NET SDK + dotnet tool install -g vpk
# Usage: .\scripts\velopack_poc.ps1 [-SkipBuild]

param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$OutDir = Join-Path $Root "release\velopack-poc"

if (-not $SkipBuild) {
    & (Join-Path $Root "scripts\build_exe.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "build_exe.ps1 failed"
    }
}

if (Test-Path $OutDir) {
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}

$result = & (Join-Path $Root "scripts\velopack_pack.ps1") -OutputDir $OutDir

Write-Host ""
Write-Host "POC OK."
Write-Host "  Setup:  $($result.SetupExe)"
Write-Host "  Nupkg:  $($result.FullNupkg)"
Write-Host "  Feed:   $($result.FeedJson)"
