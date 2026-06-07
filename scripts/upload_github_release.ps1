# Upload DanmuAI-windows-x64.zip to a GitHub Release (requires: gh auth login or GH_TOKEN).
# Usage (repo root):
#   .\scripts\upload_github_release.ps1
#   .\scripts\upload_github_release.ps1 -Tag v2026.05.29 -NotesFile docs\release\2026-05-29.md

param(
    [string]$Tag = "v2026.05.29",
    [string]$Title = "DanmuAI 2026-05-29",
    [string]$NotesFile = "docs\release\2026-05-29.md",
    [string]$ZipPath = "release\DanmuAI-windows-x64.zip",
    [string]$Repo = "PEPETII/danmuai"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) not found. Install: https://cli.github.com/"
}

$zipFull = Join-Path $Root $ZipPath
if (-not (Test-Path -LiteralPath $zipFull)) {
    Write-Error "Missing zip: $zipFull`nRun: .\scripts\publish_windows_release.ps1"
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
    Write-Host "Release $Tag exists — uploading asset only ..."
    gh release upload $Tag $zipFull --repo $Repo --clobber
} else {
    Write-Host "Creating release $Tag ..."
    gh release create $Tag $zipFull `
        --repo $Repo `
        --title $Title `
        --notes-file $notesFull `
        --target main
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "gh release failed (exit $LASTEXITCODE)"
}

Write-Host ""
Write-Host "Done: https://github.com/$Repo/releases/tag/$Tag"
