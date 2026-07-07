# Shared semver patterns for Windows release scripts (W-PACK-008).
# Aligns with app/version_compare.py prerelease handling.

$AppVersionPattern = '^\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$'
$VersionPyCapturePattern = '__version__\s*=\s*["''](\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)["'']'

function Get-PythonVersionOutputLine {
    param([object]$VersionOutput)
    if (-not $VersionOutput) { return "" }
    $lines = @($VersionOutput | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($lines.Count -eq 0) { return "" }
    return $lines[-1]
}

function Get-PackagingExeName {
    $out = python -c "from app.packaging_constants import WINDOWS_EXE_NAME; print(WINDOWS_EXE_NAME)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to read WINDOWS_EXE_NAME from app.packaging_constants (exit $LASTEXITCODE): $out"
    }
    return (Get-PythonVersionOutputLine -VersionOutput $out)
}

function Get-PackagingDistPaths {
    $out = python -c "from app.packaging_constants import WINDOWS_DIST_DIR, WINDOWS_EXE_NAME; print(WINDOWS_DIST_DIR); print(WINDOWS_EXE_NAME)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to read packaging constants from app.packaging_constants (exit $LASTEXITCODE): $out"
    }
    $lines = @($out | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($lines.Count -lt 2) {
        Write-Error "Expected WINDOWS_DIST_DIR and WINDOWS_EXE_NAME from app.packaging_constants, got: $out"
    }
    return @{
        DistDir = $lines[0]
        ExeName = $lines[1]
    }
}
