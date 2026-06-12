# Shared Velopack pack step for DanmuAI (PyInstaller onedir -> Setup + nupkg + feed).
# Dotnet SDK + vpk required: dotnet tool install -g vpk
# Called by velopack_poc.ps1 and publish_windows_release.ps1.

param(
    [string]$PackDir = "",
    [string]$OutputDir = "",
    [string]$PackId = "PEPETII.DanmuAI",
    [string]$MainExe = "DanmuAI.exe",
    [string]$PackTitle = "DanmuAI"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $PackDir) {
    $PackDir = Join-Path $Root "dist\DanmuAI"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "release\velopack"
}

if (-not (Test-Path (Join-Path $PackDir $MainExe))) {
    Write-Error "Missing $(Join-Path $PackDir $MainExe)"
}

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

Ensure-Vpk

$appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()
$icon = Join-Path $Root "resources\icon.ico"
$iconArg = @()
if (Test-Path $icon) {
    $iconArg = @("--icon", $icon)
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Velopack pack: packId=$PackId version=$appVersion"
& vpk pack `
    --packId $PackId `
    --packVersion $appVersion `
    --packDir $PackDir `
    --mainExe $MainExe `
    --packTitle $PackTitle `
    --outputDir $OutputDir `
    @iconArg

if ($LASTEXITCODE -ne 0) {
    Write-Error "vpk pack failed (exit $LASTEXITCODE)"
}

$setup = Get-ChildItem -Path $OutputDir -Filter "*-Setup.exe" | Select-Object -First 1
$nupkg = Get-ChildItem -Path $OutputDir -Filter "*-full.nupkg" | Select-Object -First 1
if (-not $setup -or -not $nupkg) {
    Write-Error "Velopack output incomplete in $OutputDir"
}

# Contract naming for R2 / download entry (W-REL-R2V-002)
$versionedSetup = Join-Path $OutputDir "PEPETII.DanmuAI-$appVersion-Setup.exe"
Copy-Item -LiteralPath $setup.FullName -Destination $versionedSetup -Force

return @{
    Version       = $appVersion
    OutputDir     = $OutputDir
    SetupExe      = $setup.FullName
    VersionedSetup = $versionedSetup
    FullNupkg     = $nupkg.FullName
    FeedJson      = Join-Path $OutputDir "releases.win.json"
    PortableZip   = (Get-ChildItem -Path $OutputDir -Filter "*-Portable.zip" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
}
