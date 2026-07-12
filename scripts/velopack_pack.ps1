# Shared Velopack pack step for DanmuAI (PyInstaller onedir -> Setup + nupkg + feed + Portable).
# Dotnet SDK + vpk required: dotnet tool install -g vpk
# Called by velopack_poc.ps1 and publish_windows_release.ps1.

param(
    [string]$PackDir = "",
    [string]$OutputDir = "",
    [string]$PackId = "PEPETII.DanmuAI",
    [string]$MainExe = "",
    [string]$PackTitle = "DanmuAI",
    [pscustomobject]$BuildPython = $null
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")
. (Join-Path $PSScriptRoot "version_parse.ps1")
if (-not $MainExe) {
    $MainExe = Get-PackagingExeName -Root $Root
}
if (-not $PackDir) {
    $packagingPaths = Get-PackagingDistPaths -Root $Root
    $PackDir = Join-Path $Root ("dist\" + $packagingPaths.DistDir)
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

if (-not $BuildPython) {
    $BuildPython = Assert-BuildPython -Root $Root
}
$versionOutput = Invoke-BuildPythonExpression -Root $Root -Code "from app.version import __version__; print(__version__)" -PythonCmd $BuildPython
$appVersion = Get-PythonVersionOutputLine -VersionOutput $versionOutput
if (-not $appVersion -or $appVersion -notmatch $AppVersionPattern) {
    Write-Error "Invalid version string from app.version.__version__: '$appVersion' (expected semver x.y.z or x.y.z-prerelease)"
}
$icon = Join-Path $Root "resources\icon.ico"
$iconArg = @()
if (Test-Path $icon) {
    $iconArg = @("--icon", $icon)
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Code signing gate (SIGN-004 / W-PACK-001).
# When DANMU_CODE_SIGN=1, pass signing params to vpk pack.
# Credentials via environment variables ONLY — never commit PFX, passwords, or PINs.
# See docs/operations/PACKAGING_WINDOWS.md（「代码签名（可选）」章节）
$signArgs = @()
if ($env:DANMU_CODE_SIGN -eq "1") {
    if ($env:VPK_AZURE_TRUSTED_SIGN_FILE) {
        $signArgs = @("--azureTrustedSignFile", $env:VPK_AZURE_TRUSTED_SIGN_FILE)
        Write-Host "Code signing enabled: Azure Artifact Signing"
    } elseif ($env:VPK_SIGN_PARAMS) {
        $signArgs = @("--signParams", $env:VPK_SIGN_PARAMS)
        Write-Host "Code signing enabled: signtool (--signParams)"
    } else {
        Write-Error "DANMU_CODE_SIGN=1 but neither VPK_SIGN_PARAMS nor VPK_AZURE_TRUSTED_SIGN_FILE is set. See docs/operations/PACKAGING_WINDOWS.md（「代码签名（可选）」章节）"
    }
}

Write-Host "Velopack pack: packId=$PackId version=$appVersion"
& vpk pack `
    --packId $PackId `
    --packVersion $appVersion `
    --packDir $PackDir `
    --mainExe $MainExe `
    --packTitle $PackTitle `
    --outputDir $OutputDir `
    --instLocation Either `
    @iconArg `
    @signArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "vpk pack failed (exit $LASTEXITCODE)"
}

$setup = Get-ChildItem -Path $OutputDir -Filter "$PackId-win-Setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$nupkg = Get-ChildItem -Path $OutputDir -Filter "$PackId-$appVersion-full.nupkg" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $setup -or -not $nupkg) {
    Write-Error "Velopack output incomplete in $OutputDir (need Setup.exe and full.nupkg)"
}
$deltaNupkgs = @(Get-ChildItem -Path $OutputDir -Filter "$PackId-$appVersion-delta.nupkg" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)

# Contract naming for R2 / download entry (W-REL-R2V-002)
$versionedSetup = Join-Path $OutputDir "PEPETII.DanmuAI-$appVersion-Setup.exe"
Copy-Item -LiteralPath $setup.FullName -Destination $versionedSetup -Force

# Replace Velopack portable stub with a plain PyInstaller onedir archive.
# Users should launch the real app exe, not the portable stub at zip root.
$portableZip = Join-Path $OutputDir "$PackId-win-Portable.zip"
if (Test-Path -LiteralPath $portableZip) {
    Remove-Item -LiteralPath $portableZip -Force
}
$portableItems = Get-ChildItem -LiteralPath $PackDir -Force | Select-Object -ExpandProperty FullName
if (-not $portableItems -or $portableItems.Count -eq 0) {
    Write-Error "Portable package source is empty: $PackDir"
}
Compress-Archive -LiteralPath $portableItems -DestinationPath $portableZip -CompressionLevel Optimal

return @{
    Version        = $appVersion
    OutputDir      = $OutputDir
    SetupExe       = $setup.FullName
    VersionedSetup = $versionedSetup
    FullNupkg      = $nupkg.FullName
    DeltaNupkgs    = $deltaNupkgs
    FeedJson       = Join-Path $OutputDir "releases.win.json"
    PortableZip    = $portableZip
}
