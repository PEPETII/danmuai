# Build DanmuAI Windows folder distribution (PyInstaller onedir).
# Requires: a usable 64-bit Python 3.12 environment with PyInstaller installed.
# Output: dist/<WINDOWS_DIST_DIR>/<WINDOWS_EXE_NAME> (see app.packaging_constants)

param(
    [switch]$AllowUnlockedBuild,
    [switch]$SkipDependencyInstall,
    [switch]$Incremental,
    [string]$OutputRoot = "",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($Incremental -and -not $AllowUnlockedBuild) {
    throw "Incremental builds require -AllowUnlockedBuild; release builds always use --clean."
}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$buildOutputRoot = if ($OutputRoot) { [System.IO.Path]::GetFullPath($OutputRoot) } else { $Root }
$distParent = Join-Path $buildOutputRoot "dist"
$workDir = Join-Path $buildOutputRoot "build"

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")
. (Join-Path $PSScriptRoot "version_parse.ps1")
. (Join-Path $PSScriptRoot "verify_release_lock.ps1")
$packagingPaths = Get-PackagingDistPaths -Root $Root
$distDirName = $packagingPaths.DistDir
$exeName = $packagingPaths.ExeName

$selectedBuildPython = if ($PythonPath) {
    [pscustomobject]@{
        Path = [System.IO.Path]::GetFullPath($PythonPath)
        Args = @()
        Label = "-PythonPath"
        SkipDependencyInstall = $false
    }
} else { $null }
$PythonCmd = Assert-BuildPython -Root $Root -PythonCmd $selectedBuildPython
Write-Host "Using Python: $($PythonCmd.Label) => $($PythonCmd.Path)"
if ($PythonCmd.Path -ne "py" -and $PythonCmd.Path -ne "python") {
    $PythonPrefix = Split-Path -Parent $PythonCmd.Path
    if ($env:PATH -notlike "*$PythonPrefix*") {
        $env:PATH = "$PythonPrefix;$env:PATH"
    }
}

if (-not (Test-Path "resources\icon.ico") -or -not (Test-Path "resources\icon.png")) {
    Write-Host "Generating resources\icon.ico + icon.png ..."
    & $PythonCmd.Path @($PythonCmd.Args) (Join-Path $Root "scripts\generate_app_icon.py")
}

$distDir = Join-Path $distParent $distDirName
$exe = Join-Path $distDir $exeName

function Stop-DanmuAiProcesses {
    $procs = Get-Process -Name "DanmuAI" -ErrorAction SilentlyContinue
    if (-not $procs) {
        return
    }
    Write-Host "Stopping running $exeName (dist output is locked while it runs)..."
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Clear-DistOutput {
    if (-not (Test-Path $distDir)) {
        return
    }
    $resolvedDist = [System.IO.Path]::GetFullPath((Get-Item -LiteralPath $distDir).FullName)
    $allowedParent = [System.IO.Path]::GetFullPath($distParent).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    # A junction in any ancestor can redirect recursive deletion outside OutputRoot.
    $distAncestor = Get-Item -LiteralPath $resolvedDist
    while ($null -ne $distAncestor) {
        if ($distAncestor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to remove dist through a reparse point: $($distAncestor.FullName)"
        }
        $distAncestor = $distAncestor.Parent
    }
    if (-not $resolvedDist.StartsWith($allowedParent, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolvedDist) -ne $distDirName -or
        ((Get-Item -LiteralPath $distDir).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to remove a dist path outside the intended output directory: $resolvedDist"
    }
    try {
        Remove-Item -LiteralPath $resolvedDist -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Error @"
Cannot remove $distDir — files are in use.
Close $exeName / pywebview / tray, then rerun: .\scripts\build_exe.ps1
Original error: $($_.Exception.Message)
"@
    }
}

$useReleaseLock = -not $AllowUnlockedBuild
$reqFiles = if ($useReleaseLock) {
    @("-r", "requirements-release-win-lock.txt")
} else {
    @("-r", "requirements.txt", "-r", "requirements-dev.txt")
}

if ($AllowUnlockedBuild) {
    Write-Warning "Unlocked build explicitly selected (-AllowUnlockedBuild); floating requirements will be used."
} else {
    Assert-ReleaseLockFile -ProjectRoot $Root
}

# Skipping an already completed install never skips the installed lock preflight below.
$shouldInstall = (-not $SkipDependencyInstall) -and ($useReleaseLock `
    -or (-not $PythonCmd.SkipDependencyInstall) `
    -or ($env:DANMU_BUILD_FORCE_PIP_INSTALL -eq "1"))

if (-not $shouldInstall) {
    Write-Host "Skipping pip install for pre-provisioned build Python."
} else {
    if ($useReleaseLock) {
        Write-Host "Installing release lock dependencies..."
    } else {
        Write-Host "Installing build deps..."
    }
    & $PythonCmd.Path @($PythonCmd.Args) -m pip install -q @reqFiles
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed with exit code $LASTEXITCODE"
    }
}

if ($useReleaseLock) {
    Assert-ReleaseDependencyLock -ProjectRoot $Root -PythonCmd $PythonCmd
} else {
    & $PythonCmd.Path @($PythonCmd.Args) -m pip check
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip check failed with exit code $LASTEXITCODE"
    }
}

if (-not $OutputRoot) {
    Stop-DanmuAiProcesses
}
Clear-DistOutput

Write-Host "Building with PyInstaller (onedir)..."
# Qt/dev excludes are in DanmuAI.spec (EXCLUDES); CLI --exclude-module is invalid with .spec.
$pyInstallerArgs = @("-m", "PyInstaller", "--noconfirm", "--distpath", $distParent, "--workpath", $workDir)
if (-not $Incremental) {
    $pyInstallerArgs += "--clean"
}
$pyInstallerArgs += "DanmuAI.spec"
& $PythonCmd.Path @($PythonCmd.Args) @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE. See build\DanmuAI\warn-DanmuAI.txt"
}

if (-not (Test-Path $exe)) {
    Write-Error "Build failed: $exe not found"
}

Write-Host "Auditing source-derived runtime resources in the frozen bundle..."
& $PythonCmd.Path @($PythonCmd.Args) (Join-Path $Root "scripts\audit_release_bundle.py") `
    --source-root $Root `
    --dist-dir $distDir
if ($LASTEXITCODE -ne 0) {
    Write-Error "Release bundle audit failed; inspect the frozen resource contract before packaging."
}

# Credential leak check: supabase-config.js and backup variants must not be in dist output.
$supabaseStaticDist = Join-Path $distDir "web\static"
$leakedConfigs = @()
$leakedConfig = Join-Path $supabaseStaticDist "supabase-config.js"
if (Test-Path $leakedConfig) {
    $leakedConfigs += $leakedConfig
}
Get-ChildItem -Path $supabaseStaticDist -Filter "supabase-config.js.*" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $leakedConfigs += $_.FullName
}
if ($leakedConfigs.Count -gt 0) {
    $listed = ($leakedConfigs | ForEach-Object { "  $_" }) -join [Environment]::NewLine
    Write-Error @"
Credential leak detected in dist output:
$listed
Supabase credential files must NOT be packaged. Remove them from dist and verify DanmuAI.spec excludes them.
"@
}

Write-Host ""
Write-Host "Done: $exe"
Write-Host "Next: .\scripts\publish_windows_release.ps1 for Velopack Setup + Portable release bundle."
