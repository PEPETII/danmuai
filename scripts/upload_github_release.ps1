# Upload Velopack release assets to GitHub Release (mirror; primary source is R2).
# Requires: gh auth login or GH_TOKEN
# Usage:
#   .\scripts\upload_github_release.ps1
#   .\scripts\upload_github_release.ps1 -Tag v0.3.0 -NotesFile docs\release\2026-05-29.md
#   .\scripts\upload_github_release.ps1 -Version 0.3.1 -Tag v0.3.1

param(
    [string]$Tag = "",
    [string]$Title = "",
    [string]$NotesFile = "",
    [string]$Version = "",
    [string]$ReleaseDir = "release\velopack",
    [string]$Repo = "PEPETII/danmuai"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) not found. Install: https://cli.github.com/"
}

$releaseFull = Join-Path $Root $ReleaseDir
if (-not (Test-Path $releaseFull)) {
    Write-Error "Missing release dir: $releaseFull`nRun: .\scripts\publish_windows_release.ps1"
}

function Get-VersionFromVersionFile {
    param([string]$Dir)
    $versionFile = Join-Path $Dir "VERSION.txt"
    if (-not (Test-Path -LiteralPath $versionFile)) { return $null }
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $versionFile) {
        if ($line -match '^\s*Version:\s*(\S+)\s*$') {
            return $Matches[1]
        }
    }
    return $null
}

function Resolve-UploadVersion {
    param([string]$ExplicitVersion, [string]$Dir)
    if ($ExplicitVersion) { return $ExplicitVersion.Trim() }
    $fromFile = Get-VersionFromVersionFile -Dir $Dir
    if ($fromFile) { return $fromFile }
    return (python -c "from app.version import __version__; print(__version__)").Trim()
}

$appVersion = Resolve-UploadVersion -ExplicitVersion $Version -Dir $releaseFull
if (-not $Tag) {
    $Tag = "v$appVersion"
}
if (-not $Title) {
    $Title = "DanmuAI $appVersion"
}
if (-not $NotesFile) {
    $versionNotes = "docs\release\v$appVersion.md"
    if (Test-Path -LiteralPath (Join-Path $Root $versionNotes)) {
        $NotesFile = $versionNotes
    }
}

$assets = @()
$assetFiles = @(
    "PEPETII.DanmuAI-win-Setup.exe",
    "PEPETII.DanmuAI-$appVersion-Setup.exe",
    "PEPETII.DanmuAI-win-Portable.zip",
    "PEPETII.DanmuAI-$appVersion-full.nupkg",
    "PEPETII.DanmuAI-$appVersion-delta.nupkg",
    "releases.win.json"
)
foreach ($name in $assetFiles) {
    $path = Join-Path $releaseFull $name
    if (Test-Path -LiteralPath $path) {
        $assets += $path
    }
}
if ($assets.Count -eq 0) {
    Write-Error "No Velopack assets found in $releaseFull"
}

$notesFull = ""
$hasNotes = $false
if ($NotesFile) {
    $notesFull = Join-Path $Root $NotesFile
    $hasNotes = Test-Path -LiteralPath $notesFull
    if (-not $hasNotes) {
        Write-Warning "Release notes not found: $notesFull — publishing without notes"
    }
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
    if ($hasNotes) {
        gh release create $Tag @assets `
            --repo $Repo `
            --title $Title `
            --notes-file $notesFull `
            --target main
    } else {
        gh release create $Tag @assets `
            --repo $Repo `
            --title $Title `
            --notes "Release $Tag" `
            --target main
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "gh release failed (exit $LASTEXITCODE)"
}

Write-Host ""
Write-Host "Done (GitHub mirror): https://github.com/$Repo/releases/tag/$Tag"
Write-Host "Primary download: https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
Write-Host "Portable download: https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip"
