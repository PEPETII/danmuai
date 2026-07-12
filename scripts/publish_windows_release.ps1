# Build DanmuAI Windows x64: PyInstaller onedir -> Velopack release bundle.
# Requires: Windows, Python 3.12+, .NET SDK, vpk (dotnet tool install -g vpk)

param(
    [string]$BootstrapFeedUrl = "https://updates.qiaoqiao.buzz/releases/win/stable",
    [switch]$SkipDeltaBootstrap,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")
. (Join-Path $PSScriptRoot "version_parse.ps1")

# Guard: any file containing 'supabase-config' (except allowlist) contains credentials
# and must not be packaged. Default-deny (BUG-005): the previous -Filter "supabase-config.js.*"
# missed creative variants like supabase-config-local.js or my-supabase-config.js.
$supabaseStaticDir = Join-Path $Root "web\static"
$allowedSupabaseFiles = @("supabase-config.example.js", "supabase-client.js")
$forbiddenSupabaseConfigs = @()
Get-ChildItem -Path $supabaseStaticDir -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like "*supabase-config*" -and $_.Name -notin $allowedSupabaseFiles
} | ForEach-Object {
    $forbiddenSupabaseConfigs += $_.FullName
}
if ($forbiddenSupabaseConfigs.Count -gt 0) {
    $listed = ($forbiddenSupabaseConfigs | ForEach-Object { "  $_" }) -join [Environment]::NewLine
    Write-Error @"
ABORT: credential-bearing Supabase config files must not be present before publishing:
$listed
Remove them before publishing (only supabase-config.example.js and supabase-client.js should be present).
"@
}

$ReleaseRoot = Join-Path $Root "release"
$VelopackDir = Join-Path $ReleaseRoot "velopack"
$packagingPaths = Get-PackagingDistPaths -Root $Root
$DistDir = Join-Path $Root ("dist\" + $packagingPaths.DistDir)
$PackagingExeName = $packagingPaths.ExeName
$VersionFile = Join-Path $VelopackDir "VERSION.txt"
$BuildPython = Assert-BuildPython -Root $Root

function Ensure-Vpk {
    $vpk = Get-Command vpk -ErrorAction SilentlyContinue
    if ($vpk) { return }
    $dotnetTools = Join-Path $env:USERPROFILE ".dotnet\tools"
    if (Test-Path (Join-Path $dotnetTools "vpk.exe")) {
        $env:Path = "$dotnetTools;" + $env:Path
        return
    }
    Write-Error @"
vpk CLI not found. Install .NET SDK then:
  dotnet tool install -g vpk
See docs/operations/PACKAGING_WINDOWS.md
"@
}

function Get-AppVersion {
    return Get-AppVersionFromProject -Root $Root -PythonCmd $BuildPython
}

$appVersion = Get-AppVersion

if ($DryRun) {
    Write-Host "[DryRun] App version: $appVersion"
    Write-Host "[DryRun] Supabase guard passed. Skipping build/pack."
    exit 0
}

& (Join-Path $Root "scripts\build_exe.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "build_exe.ps1 failed"
}

if (-not (Test-Path (Join-Path $DistDir $PackagingExeName))) {
    Write-Error "Missing $(Join-Path $DistDir $PackagingExeName) after build"
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
New-Item -ItemType Directory -Force -Path $VelopackDir | Out-Null

function Test-FileLocked {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        [IO.File]::Open($Path, 'Open', 'ReadWrite', 'None').Close()
        return $false
    } catch {
        return $true
    }
}

function Test-DirectoryFilesLocked {
    param([string]$Dir)
    if (-not (Test-Path -LiteralPath $Dir)) { return @() }
    $locked = @()
    Get-ChildItem -LiteralPath $Dir -File -ErrorAction SilentlyContinue | ForEach-Object {
        if (Test-FileLocked -Path $_.FullName) {
            $locked += $_.Name
        }
    }
    return $locked
}

$lockedFiles = Test-DirectoryFilesLocked -Dir $VelopackDir
if ($lockedFiles.Count -gt 0) {
    Write-Warning "Locked files in $VelopackDir (may be held by antivirus, explorer, or another process):"
    $lockedFiles | ForEach-Object { Write-Warning "  $_" }
    Write-Error "Cannot clean release directory — close applications locking these files and rerun."
}

$currentVersionPatterns = @(
    "PEPETII.DanmuAI-win-Setup.exe",
    "PEPETII.DanmuAI-$appVersion-Setup.exe",
    "PEPETII.DanmuAI-$appVersion-full.nupkg",
    "PEPETII.DanmuAI-$appVersion-delta.nupkg",
    "PEPETII.DanmuAI-$appVersion-win-Portable.zip",
    "releases.win.json",
    "VERSION.txt"
)
foreach ($pattern in $currentVersionPatterns) {
    Get-ChildItem -Path $VelopackDir -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }
}
Get-ChildItem -Path $VelopackDir -Filter "*.msi" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
}

$existingFull = @(Get-ChildItem -Path $VelopackDir -Filter "*-full.nupkg" -ErrorAction SilentlyContinue)
if (-not $SkipDeltaBootstrap -and $existingFull.Count -eq 0 -and $BootstrapFeedUrl) {
    Ensure-Vpk
    Write-Host "Bootstrapping previous Velopack releases from $BootstrapFeedUrl"
    & vpk download http --url $BootstrapFeedUrl --outputDir $VelopackDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "vpk download http failed (exit $LASTEXITCODE)"
    }
}

$packResult = & (Join-Path $Root "scripts\velopack_pack.ps1") -PackDir $DistDir -OutputDir $VelopackDir -BuildPython $BuildPython

$gitSha = "unknown"
try {
    $gitSha = (git -C $Root rev-parse --short HEAD 2>$null)
} catch { }
$builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$appVersion = $packResult.Version
$deltaNupkgs = @($packResult.DeltaNupkgs)
$deltaCount = $deltaNupkgs.Count

$feedAssets = @()
if (Test-Path -LiteralPath $packResult.FeedJson) {
    try {
        $feedJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $packResult.FeedJson | ConvertFrom-Json
        if ($feedJson.PSObject.Properties.Name -contains "Assets") {
            $feedAssets = @($feedJson.Assets)
        }
    } catch {
        Write-Error "Unable to parse $($packResult.FeedJson): $($_.Exception.Message)"
    }
}
$deltaFeedCount = @($feedAssets | Where-Object { $_.Type -eq "Delta" }).Count
if ($deltaCount -gt 0 -and $deltaFeedCount -eq 0) {
    Write-Error "Expected releases.win.json to contain delta entries when delta packages were generated"
}

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
    "  PEPETII.DanmuAI-$appVersion-delta.nupkg (when prior release metadata is available)"
    "  PEPETII.DanmuAI-win-Portable.zip"
    "  releases.win.json"
    ""
    "Delta packages generated: $deltaCount"
    ""
    "Primary download (after R2 upload): https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
    "Portable download: https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip"
    "Update feed: https://updates.qiaoqiao.buzz/releases/win/stable"
) | Set-Content -LiteralPath $VersionFile -Encoding utf8

# Post-pack signature verification (W-PACK-007).
if ($env:DANMU_CODE_SIGN -eq "1") {
    Write-Host "Verifying release signatures..."
    & (Join-Path $Root "scripts\sign_windows_release.ps1") -VerifyOnly -ReleaseDir $VelopackDir
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed — see above for details"
    }
    Write-Host "Signature verification passed."
}

& (Join-Path $Root "scripts\write_release_hash_manifest.ps1") -ReleaseDir $VelopackDir -Version $appVersion
if ($LASTEXITCODE -ne 0) {
    Write-Error "write_release_hash_manifest.ps1 failed (exit $LASTEXITCODE)"
}
$manifestPath = Join-Path $VelopackDir "SHA256SUMS.txt"

Write-Host ""
Write-Host "Done."
Write-Host "  Output:   $VelopackDir"
Write-Host "  Setup:    $($packResult.SetupExe)"
Write-Host "  Versioned Setup: $($packResult.VersionedSetup)"
Write-Host "  Nupkg:    $($packResult.FullNupkg)"
Write-Host "  Delta(s): $deltaCount"
Write-Host "  Feed:     $($packResult.FeedJson)"
if ($packResult.PortableZip) {
    Write-Host "  Portable: $($packResult.PortableZip)"
}
Write-Host "  SHA256:   $manifestPath"
