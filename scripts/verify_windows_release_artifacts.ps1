# Verify Windows Velopack release artifacts (CI + local smoke).
# W-REL-READINESS-005: Portable layout, no MSI, feed latest Full, delta consistency.
#
# Usage:
#   .\scripts\verify_windows_release_artifacts.ps1
#   .\scripts\verify_windows_release_artifacts.ps1 -ReleaseDir "release\velopack"
#   .\scripts\verify_windows_release_artifacts.ps1 -ReleaseDir "path\to\fixture" -Version 0.3.8 -SkipDistCheck

param(
    [string]$ReleaseDir = "release\velopack",
    [string]$Version = "",
    [switch]$SkipDistCheck
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")
. (Join-Path $PSScriptRoot "version_parse.ps1")

if ([System.IO.Path]::IsPathRooted($ReleaseDir)) {
    $releaseFull = [System.IO.Path]::GetFullPath($ReleaseDir)
} else {
    $releaseFull = Join-Path $Root $ReleaseDir
}
if (-not (Test-Path -LiteralPath $releaseFull)) {
    Write-Error "Missing release directory: $releaseFull"
}

$BuildPython = Assert-BuildPython -Root $Root
if ($Version) {
    $appVersion = $Version.Trim()
} else {
    $appVersion = Get-AppVersionFromProject -Root $Root -PythonCmd $BuildPython
}
$appVersion = Normalize-AppSemVersion -Version $appVersion

$packIdOut = Invoke-BuildPythonExpression -Root $Root -Code "from app.packaging_constants import VELOPACK_PACK_ID; print(VELOPACK_PACK_ID)" -PythonCmd $BuildPython
$packId = (Get-PythonVersionOutputLine -VersionOutput $packIdOut)
if (-not $packId) {
    Write-Error "Unable to resolve VELOPACK_PACK_ID from app.packaging_constants"
}

$exeName = Get-PackagingExeName -Root $Root
$packagingPaths = Get-PackagingDistPaths -Root $Root

function Get-FeedLatestFullVersion {
    param([string]$FeedPath)
    $json = Get-Content -Raw -Encoding UTF8 -LiteralPath $FeedPath | ConvertFrom-Json
    $fullVersions = @(
        $json.Assets |
            Where-Object { $_.Type -eq "Full" -and $_.Version } |
            ForEach-Object { [string]$_.Version }
    )
    if ($fullVersions.Count -eq 0) { return $null }
    return (Get-LatestAppSemVersion -Versions $fullVersions)
}

# --- MSI must not be present (W-REL-CLEANUP-001) ---
$msiFiles = @(Get-ChildItem -Path $releaseFull -Filter "*.msi" -ErrorAction SilentlyContinue)
if ($msiFiles.Count -gt 0) {
    $names = ($msiFiles | ForEach-Object { $_.Name }) -join ", "
    Write-Error "Unexpected MSI artifacts in ${releaseFull}: $names"
}

# --- Core Velopack outputs (legacy CI checks) ---
$setupPath = Join-Path $releaseFull "$packId-win-Setup.exe"
if (-not (Test-Path -LiteralPath $setupPath)) {
    Write-Error "Missing Setup.exe: $setupPath"
}

$fullNupkgPath = Join-Path $releaseFull "$packId-$appVersion-full.nupkg"
if (-not (Test-Path -LiteralPath $fullNupkgPath)) {
    Write-Error "Missing full.nupkg: $fullNupkgPath"
}

$feedPath = Join-Path $releaseFull "releases.win.json"
if (-not (Test-Path -LiteralPath $feedPath)) {
    Write-Error "Missing releases.win.json: $feedPath"
}

if (-not $SkipDistCheck) {
    $distExe = Join-Path $Root ("dist\" + $packagingPaths.DistDir + "\" + $packagingPaths.ExeName)
    if (-not (Test-Path -LiteralPath $distExe)) {
        Write-Error "Missing PyInstaller exe: $distExe"
    }
}

# --- Portable zip root layout (PyInstaller onedir) ---
$portableZip = Join-Path $releaseFull "$packId-win-Portable.zip"
if (-not (Test-Path -LiteralPath $portableZip)) {
    Write-Error "Missing Portable zip: $portableZip"
}

$portableTemp = Join-Path $env:TEMP ("danmu-portable-verify-" + [guid]::NewGuid().ToString())
try {
    New-Item -ItemType Directory -Force -Path $portableTemp | Out-Null
    Expand-Archive -LiteralPath $portableZip -DestinationPath $portableTemp -Force

    $portableExe = Join-Path $portableTemp $exeName
    if (-not (Test-Path -LiteralPath $portableExe -PathType Leaf)) {
        Write-Error "Portable zip root missing $exeName (expected directly under zip root)"
    }

    $internalDir = Join-Path $portableTemp "_internal"
    if (-not (Test-Path -LiteralPath $internalDir -PathType Container)) {
        Write-Error "Portable zip root missing _internal/ directory"
    }
} finally {
    if (Test-Path -LiteralPath $portableTemp) {
        Remove-Item -LiteralPath $portableTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- Feed latest Full must match app version ---
$feedAssets = @()
try {
    $feedJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $feedPath | ConvertFrom-Json
    if ($feedJson.PSObject.Properties.Name -contains "Assets") {
        $feedAssets = @($feedJson.Assets)
    }
} catch {
    Write-Error "Unable to parse $feedPath : $($_.Exception.Message)"
}

$feedLatest = Get-FeedLatestFullVersion -FeedPath $feedPath
if (-not $feedLatest) {
    Write-Error "releases.win.json has no Full assets"
}
if ((Compare-AppSemVersion -Left $feedLatest -Right $appVersion) -ne 0) {
    Write-Error "Feed latest Full version $feedLatest does not match app version $appVersion"
}

# --- Delta nupkg present => feed must list Delta entries ---
$deltaNupkgs = @(Get-ChildItem -Path $releaseFull -Filter "$packId-$appVersion-delta.nupkg" -ErrorAction SilentlyContinue)
$deltaFeedCount = @($feedAssets | Where-Object { $_.Type -eq "Delta" }).Count
if ($deltaNupkgs.Count -gt 0 -and $deltaFeedCount -eq 0) {
    Write-Error "Expected releases.win.json to contain delta entries when delta packages were generated"
}

Write-Host "Release artifact verification passed for version $appVersion"
Write-Host "  Release dir: $releaseFull"
Write-Host "  Setup:       $setupPath"
Write-Host "  Full nupkg:  $fullNupkgPath"
Write-Host "  Portable:    $portableZip"
Write-Host "  Feed latest: $feedLatest"
Write-Host "  Delta file(s): $($deltaNupkgs.Count)"
