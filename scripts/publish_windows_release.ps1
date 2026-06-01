# Build DanmuAI Windows x64 onedir and publish to release/DanmuAI-windows-x64 (+ zip).
# Requires: Windows, Python 3.12+, repo root as cwd context.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ReleaseName = "DanmuAI-windows-x64"
$ReleaseDir = Join-Path $Root "release\$ReleaseName"
$ReleaseRoot = Join-Path $Root "release"
$DistDir = Join-Path $Root "dist\DanmuAI"
$ZipPath = Join-Path $ReleaseRoot "$ReleaseName.zip"
$VersionFile = Join-Path $ReleaseDir "VERSION.txt"

& (Join-Path $Root "scripts\build_exe.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "build_exe.ps1 failed"
}

if (-not (Test-Path (Join-Path $DistDir "DanmuAI.exe"))) {
    Write-Error "Missing $(Join-Path $DistDir 'DanmuAI.exe') after build"
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}

Write-Host "Publishing to $ReleaseDir ..."
Copy-Item -LiteralPath $DistDir -Destination $ReleaseDir -Recurse

$gitSha = ""
try {
    $gitSha = (git -C $Root rev-parse --short HEAD 2>$null)
} catch {
    $gitSha = "unknown"
}
$builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()
@(
    "DanmuAI Windows x64 (PyInstaller onedir)"
    "Version: $appVersion"
    "Release folder: $ReleaseName"
    "Built (UTC): $builtAt"
    "Git: $gitSha"
    "Changelog: docs/CHANGELOG.md"
    ""
    "Run DanmuAI.exe inside this folder. Requires WebView2 Runtime on Windows 10/11."
    "Fallback: DanmuAI.exe --web-browser"
) | Set-Content -LiteralPath $VersionFile -Encoding utf8

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Write-Host "Creating $ZipPath ..."
Compress-Archive -LiteralPath $ReleaseDir -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "Done."
Write-Host "  Folder: $ReleaseDir"
Write-Host "  Zip:    $ZipPath"
$exe = Join-Path $ReleaseDir "DanmuAI.exe"
$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host "  Exe:    $exe ($sizeMb MB)"
