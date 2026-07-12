# Shared SemVer subset for Windows release scripts (W-PACK-008 / BUG-V2-011).
# Supported: x.y.z[-identifier[.identifier...]]. Build metadata is out of scope.

$AppVersionPattern = '^\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
$AppVersionParsePattern = '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)(?:-(?<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
$VersionPyCapturePattern = '__version__\s*=\s*["''](\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)["'']'

function Normalize-AppSemVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Version
    )

    $normalized = ([string]$Version).Trim()
    if ($normalized.StartsWith('v', [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(1)
    }
    if (-not $normalized -or $normalized -notmatch $AppVersionPattern) {
        throw "Invalid version '$Version' (expected x.y.z[-identifier[.identifier...]])"
    }
    return $normalized
}

function ConvertTo-AppSemVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Version
    )

    $normalized = Normalize-AppSemVersion -Version $Version
    $match = [regex]::Match($normalized, $AppVersionParsePattern)
    if (-not $match.Success) {
        throw "Invalid version '$Version' (expected x.y.z[-identifier[.identifier...]])"
    }

    $prerelease = $match.Groups['prerelease'].Value
    $identifiers = if ($prerelease) { @($prerelease.Split('.')) } else { @() }
    return [pscustomobject]@{
        Normalized = $normalized
        Major = $match.Groups['major'].Value
        Minor = $match.Groups['minor'].Value
        Patch = $match.Groups['patch'].Value
        Prerelease = $prerelease
        PrereleaseIdentifiers = $identifiers
    }
}

function Compare-AppSemVersionNumericIdentifier {
    param(
        [Parameter(Mandatory)]
        [string]$Left,
        [Parameter(Mandatory)]
        [string]$Right
    )

    $leftNormalized = $Left.TrimStart('0')
    $rightNormalized = $Right.TrimStart('0')
    if (-not $leftNormalized) { $leftNormalized = '0' }
    if (-not $rightNormalized) { $rightNormalized = '0' }
    if ($leftNormalized.Length -lt $rightNormalized.Length) { return -1 }
    if ($leftNormalized.Length -gt $rightNormalized.Length) { return 1 }
    $comparison = [string]::CompareOrdinal($leftNormalized, $rightNormalized)
    if ($comparison -lt 0) { return -1 }
    if ($comparison -gt 0) { return 1 }
    return 0
}

function Compare-AppSemVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Left,
        [Parameter(Mandatory)]
        [string]$Right
    )

    $leftVersion = ConvertTo-AppSemVersion -Version $Left
    $rightVersion = ConvertTo-AppSemVersion -Version $Right
    foreach ($property in @('Major', 'Minor', 'Patch')) {
        $comparison = Compare-AppSemVersionNumericIdentifier -Left $leftVersion.$property -Right $rightVersion.$property
        if ($comparison -ne 0) { return $comparison }
    }

    if (-not $leftVersion.Prerelease -and -not $rightVersion.Prerelease) { return 0 }
    if (-not $leftVersion.Prerelease) { return 1 }
    if (-not $rightVersion.Prerelease) { return -1 }

    $leftIdentifiers = @($leftVersion.PrereleaseIdentifiers)
    $rightIdentifiers = @($rightVersion.PrereleaseIdentifiers)
    $sharedCount = [Math]::Min($leftIdentifiers.Count, $rightIdentifiers.Count)
    for ($index = 0; $index -lt $sharedCount; $index++) {
        $leftIdentifier = [string]$leftIdentifiers[$index]
        $rightIdentifier = [string]$rightIdentifiers[$index]
        $leftNumeric = $leftIdentifier -match '^\d+$'
        $rightNumeric = $rightIdentifier -match '^\d+$'

        if ($leftNumeric -and $rightNumeric) {
            $comparison = Compare-AppSemVersionNumericIdentifier -Left $leftIdentifier -Right $rightIdentifier
        } elseif ($leftNumeric) {
            $comparison = -1
        } elseif ($rightNumeric) {
            $comparison = 1
        } else {
            $ordinal = [string]::CompareOrdinal($leftIdentifier, $rightIdentifier)
            $comparison = if ($ordinal -lt 0) { -1 } elseif ($ordinal -gt 0) { 1 } else { 0 }
        }
        if ($comparison -ne 0) { return $comparison }
    }

    if ($leftIdentifiers.Count -lt $rightIdentifiers.Count) { return -1 }
    if ($leftIdentifiers.Count -gt $rightIdentifiers.Count) { return 1 }
    return 0
}

function Get-LatestAppSemVersion {
    param(
        [Parameter(Mandatory)]
        [object[]]$Versions
    )

    $items = @($Versions)
    if ($items.Count -eq 0) { return $null }
    $latest = Normalize-AppSemVersion -Version ([string]$items[0])
    for ($index = 1; $index -lt $items.Count; $index++) {
        $candidate = Normalize-AppSemVersion -Version ([string]$items[$index])
        if ((Compare-AppSemVersion -Left $candidate -Right $latest) -gt 0) {
            $latest = $candidate
        }
    }
    return $latest
}

function Get-PythonVersionOutputLine {
    param([object]$VersionOutput)
    if (-not $VersionOutput) { return "" }
    $lines = @($VersionOutput | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($lines.Count -eq 0) { return "" }
    return $lines[-1]
}

function Get-PackagingExeName {
    param(
        [Parameter(Mandatory)]
        [string]$Root
    )
    $out = Invoke-BuildPythonExpression -Root $Root -Code "from app.packaging_constants import WINDOWS_EXE_NAME; print(WINDOWS_EXE_NAME)"
    return (Get-PythonVersionOutputLine -VersionOutput $out)
}

function Get-PackagingDistPaths {
    param(
        [Parameter(Mandatory)]
        [string]$Root
    )
    $out = Invoke-BuildPythonExpression -Root $Root -Code "from app.packaging_constants import WINDOWS_DIST_DIR, WINDOWS_EXE_NAME; print(WINDOWS_DIST_DIR); print(WINDOWS_EXE_NAME)"
    $lines = @($out | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($lines.Count -lt 2) {
        Write-Error "Expected WINDOWS_DIST_DIR and WINDOWS_EXE_NAME from app.packaging_constants, got: $out"
    }
    return @{
        DistDir = $lines[0]
        ExeName = $lines[1]
    }
}

function Get-AppVersionFromProject {
    param(
        [Parameter(Mandatory)]
        [string]$Root,
        [pscustomobject]$PythonCmd = $null
    )

    if (-not $PythonCmd) {
        $PythonCmd = Assert-BuildPython -Root $Root
    }

    $versionOutput = & $PythonCmd.Path @($PythonCmd.Args) -c "from app.version import __version__; print(__version__)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $parsed = Get-PythonVersionOutputLine -VersionOutput $versionOutput
        if ($parsed -match $AppVersionPattern) {
            return $parsed
        }
    }

    $versionFile = Join-Path $Root "app\version.py"
    if (Test-Path -LiteralPath $versionFile) {
        $content = Get-Content -LiteralPath $versionFile -Raw
        if ($content -match $VersionPyCapturePattern) {
            return $Matches[1]
        }
    }

    $gitDescribe = git describe --tags --abbrev=0 2>$null
    if ($LASTEXITCODE -eq 0 -and $gitDescribe) {
        $tag = $gitDescribe.Trim().TrimStart('v')
        if ($tag -match $AppVersionPattern) {
            return $tag
        }
    }

    $detail = if ($versionOutput) { (Get-PythonVersionOutputLine -VersionOutput $versionOutput) } else { "(no python output)" }
    Write-Error "Failed to determine app version (python import, app/version.py regex, and git describe all failed). Python output: $detail"
}
