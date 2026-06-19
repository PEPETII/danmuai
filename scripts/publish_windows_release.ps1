# Build DanmuAI Windows x64: PyInstaller onedir -> Velopack release bundle.
# Requires: Windows, Python 3.12+, .NET SDK, vpk (dotnet tool install -g vpk)

param(
    [string]$BootstrapFeedUrl = "https://updates.qiaoqiao.buzz/releases/win/stable",
    [switch]$SkipDeltaBootstrap
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Guard: supabase-config.js contains credentials and must not be packaged.
$supabaseConfigPath = Join-Path $Root "web\static\supabase-config.js"
if (Test-Path $supabaseConfigPath) {
    Write-Error "ABORT: web/static/supabase-config.js exists — it contains credentials and must not be packaged. Remove it before publishing (only supabase-config.example.js should be present)."
}

$ReleaseRoot = Join-Path $Root "release"
$VelopackDir = Join-Path $ReleaseRoot "velopack"
$DistDir = Join-Path $Root "dist\DanmuAI"
$VersionFile = Join-Path $VelopackDir "VERSION.txt"

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

& (Join-Path $Root "scripts\build_exe.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "build_exe.ps1 failed"
}

if (-not (Test-Path (Join-Path $DistDir "DanmuAI.exe"))) {
    Write-Error "Missing $(Join-Path $DistDir 'DanmuAI.exe') after build"
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
$appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()

New-Item -ItemType Directory -Force -Path $VelopackDir | Out-Null

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

$packResult = & (Join-Path $Root "scripts\velopack_pack.ps1") -PackDir $DistDir -OutputDir $VelopackDir

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
        $feedJson = Get-Content -Raw -LiteralPath $packResult.FeedJson | ConvertFrom-Json
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
