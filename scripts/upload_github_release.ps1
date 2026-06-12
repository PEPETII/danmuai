# Upload Velopack release assets to GitHub Release (mirror; primary source is R2).
# Requires: gh auth login or GH_TOKEN
# Usage:
#   .\scripts\upload_github_release.ps1
#   .\scripts\upload_github_release.ps1 -Tag v0.3.0 -NotesFile docs\release\2026-05-29.md

param(
    [string]$Tag = "",
    [string]$Title = "",
    [string]$NotesFile = "",
    [string]$ReleaseDir = "release\velopack",
    [string]$Repo = "PEPETII/danmuai"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) not found. Install: https://cli.github.com/"
}

$releaseFull = Join-Path $Root $ReleaseDir
if (-not (Test-Path $releaseFull)) {
    Write-Error "Missing release dir: $releaseFull`nRun: .\scripts\publish_windows_release.ps1"
}

$appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()
if (-not $Tag) {
    $Tag = "v$appVersion"
}
if (-not $Title) {
    $Title = "DanmuAI $appVersion"
}
if (-not $NotesFile) {
    $NotesFile = "docs\release\2026-05-29.md"
}

$assets = @()
$patterns = @(
    "*-Setup.exe",
    "PEPETII.DanmuAI-*-Setup.exe",
    "*-full.nupkg",
    "releases.win.json",
    "*-Portable.zip"
)
foreach ($pat in $patterns) {
    Get-ChildItem -Path $releaseFull -Filter $pat -ErrorAction SilentlyContinue | ForEach-Object {
        if ($assets -notcontains $_.FullName) {
            $assets += $_.FullName
        }
    }
}
if ($assets.Count -eq 0) {
    Write-Error "No Velopack assets found in $releaseFull"
}

$notesFull = Join-Path $Root $NotesFile
if (-not (Test-Path -LiteralPath $notesFull)) {
    Write-Error "Missing release notes: $notesFull"
}

gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Not logged in. Run: gh auth login`nOr set GH_TOKEN with repo scope."
}

$existing = gh release view $Tag --repo $Repo 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Release $Tag exists — uploading assets ..."
    foreach ($asset in $assets) {
        Write-Host "  upload: $(Split-Path -Leaf $asset)"
        gh release upload $Tag $asset --repo $Repo --clobber
        if ($LASTEXITCODE -ne 0) {
            Write-Error "gh release upload failed for $asset"
        }
    }
} else {
    Write-Host "Creating release $Tag with $($assets.Count) asset(s) ..."
    $assetArgs = $assets -join " "
    gh release create $Tag @assets `
        --repo $Repo `
        --title $Title `
        --notes-file $notesFull `
        --target main
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "gh release failed (exit $LASTEXITCODE)"
}

Write-Host ""
Write-Host "Done (GitHub mirror): https://github.com/$Repo/releases/tag/$Tag"
Write-Host "Primary download: https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
