# Generate or verify SHA256SUMS.txt for DanmuAI Velopack release artifacts.
# W-REL-READINESS-006: integrity manifest for publish evidence and pre-upload checks.
# Not a substitute for Authenticode code signing.
#
# Usage:
#   .\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack
#   .\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack -Version 0.3.8
#   .\scripts\write_release_hash_manifest.ps1 -ReleaseDir release\velopack -VerifyOnly

param(
    [string]$ReleaseDir = "",
    [string]$Version = "",
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$PackId = "PEPETII.DanmuAI"
$ManifestFileName = "SHA256SUMS.txt"

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

function Resolve-ManifestVersion {
    param(
        [string]$ExplicitVersion,
        [string]$Dir,
        [string]$Root
    )
    if ($ExplicitVersion) { return $ExplicitVersion.Trim() }
    $fromFile = Get-VersionFromVersionFile -Dir $Dir
    if ($fromFile) { return $fromFile }
    . (Join-Path $PSScriptRoot "resolve_build_python.ps1")
    . (Join-Path $PSScriptRoot "version_parse.ps1")
    $pythonCmd = Resolve-BuildPythonCommand -Root $Root
    return Get-AppVersionFromProject -Root $Root -PythonCmd $pythonCmd
}

function Get-ReleaseManifestFiles {
    param(
        [Parameter(Mandatory)]
        [string]$Dir,
        [Parameter(Mandatory)]
        [string]$AppVersion
    )

    if (-not (Test-Path -LiteralPath $Dir)) {
        Write-Error "Release directory not found: $Dir"
    }

    $requiredPatterns = @(
        "$PackId-$AppVersion-Setup.exe",
        "$PackId-win-Setup.exe",
        "$PackId-win-Portable.zip",
        "$PackId-$AppVersion-full.nupkg",
        "releases.win.json"
    )

    $files = @()
    foreach ($pattern in $requiredPatterns) {
        $item = Get-ChildItem -Path $Dir -Filter $pattern -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $item) {
            Write-Error "Missing required release artifact: $pattern (in $Dir)"
        }
        $files += $item
    }

    $deltaItems = @(Get-ChildItem -Path $Dir -Filter "$PackId-$AppVersion-delta.nupkg" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    if ($deltaItems.Count -gt 0) {
        $files += $deltaItems
    }

    return @($files | Sort-Object Name)
}

function Get-FileSha256Hex {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-ReleaseHashManifest {
    param(
        [Parameter(Mandatory)]
        [string]$Dir,
        [Parameter(Mandatory)]
        [string]$AppVersion
    )

    $files = Get-ReleaseManifestFiles -Dir $Dir -AppVersion $AppVersion
    $lines = @()
    foreach ($file in $files) {
        $hash = Get-FileSha256Hex -Path $file.FullName
        $lines += "$hash  $($file.Name)"
    }

    $manifestPath = Join-Path $Dir $ManifestFileName
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($manifestPath, $lines, $utf8NoBom)
    return $manifestPath
}

function Test-ReleaseHashManifest {
    param(
        [Parameter(Mandatory)]
        [string]$Dir,
        [string]$AppVersion = ""
    )

    $Root = Split-Path -Parent $PSScriptRoot
    if (-not $AppVersion) {
        $AppVersion = Resolve-ManifestVersion -ExplicitVersion "" -Dir $Dir -Root $Root
    }

    $manifestPath = Join-Path $Dir $ManifestFileName
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        Write-Error "Missing $ManifestFileName in $Dir (run publish_windows_release.ps1 or write_release_hash_manifest.ps1 first)"
    }

    $expectedFiles = Get-ReleaseManifestFiles -Dir $Dir -AppVersion $AppVersion
    $expectedByName = @{}
    foreach ($file in $expectedFiles) {
        $expectedByName[$file.Name] = Get-FileSha256Hex -Path $file.FullName
    }

    $manifestLines = @(Get-Content -Encoding UTF8 -LiteralPath $manifestPath | Where-Object { $_.Trim() })
    if ($manifestLines.Count -eq 0) {
        Write-Error "$ManifestFileName is empty: $manifestPath"
    }

    $manifestByName = @{}
    foreach ($line in $manifestLines) {
        if ($line -notmatch '^([0-9a-f]{64})\s{2}(.+)$') {
            Write-Error "Invalid manifest line in ${ManifestFileName}: $line"
        }
        $name = $Matches[2].Trim()
        if ($manifestByName.ContainsKey($name)) {
            Write-Error "Duplicate manifest entry for $name"
        }
        $manifestByName[$name] = $Matches[1]
    }

    foreach ($name in ($expectedByName.Keys | Sort-Object)) {
        if (-not $manifestByName.ContainsKey($name)) {
            Write-Error "Manifest missing required artifact: $name"
        }
        $expected = $expectedByName[$name]
        $listed = $manifestByName[$name]
        if ($listed -ne $expected) {
            Write-Error "Hash mismatch for $name (expected $expected, got $listed)"
        }
    }

    foreach ($name in ($manifestByName.Keys | Sort-Object)) {
        if (-not $expectedByName.ContainsKey($name)) {
            Write-Error "Manifest lists unexpected artifact: $name"
        }
    }

    return $true
}

# When dot-sourced, only export functions.
if ($MyInvocation.InvocationName -eq '.') {
    return
}

$Root = Split-Path -Parent $PSScriptRoot
if (-not $ReleaseDir) {
    $ReleaseDir = Join-Path $Root "release\velopack"
} elseif (-not [System.IO.Path]::IsPathRooted($ReleaseDir)) {
    $ReleaseDir = Join-Path $Root $ReleaseDir
}

$appVersion = Resolve-ManifestVersion -ExplicitVersion $Version -Dir $ReleaseDir -Root $Root

if ($VerifyOnly) {
    Test-ReleaseHashManifest -Dir $ReleaseDir -AppVersion $appVersion | Out-Null
    Write-Host "SHA256 manifest verification passed for version $appVersion"
    exit 0
}

$manifestPath = Write-ReleaseHashManifest -Dir $ReleaseDir -AppVersion $appVersion
Write-Host "Wrote SHA256 manifest: $manifestPath"
exit 0
