# Build DanmuAI Windows folder distribution (PyInstaller onedir).
# Requires: a usable Python 3.12+ environment with PyInstaller installed.
# Output: dist/DanmuAI/DanmuAI.exe

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-PathStartsWith {
    param(
        [string]$Path,
        [string]$Prefix
    )
    if (-not $Path -or -not $Prefix) {
        return $false
    }
    return $Path.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-PythonCommand {
    $candidates = @(
        [pscustomobject]@{
            Path = (Join-Path $Root ".venv-build\Scripts\python.exe")
            Args = @()
            Label = ".venv-build"
            SkipDependencyInstall = $true
        },
        [pscustomobject]@{
            Path = (Join-Path $Root ".venv-build-312\Scripts\python.exe")
            Args = @()
            Label = ".venv-build-312"
            SkipDependencyInstall = $true
        },
        [pscustomobject]@{
            Path = $env:DANMU_BUILD_PYTHON
            Args = @()
            Label = "DANMU_BUILD_PYTHON"
            SkipDependencyInstall = Test-PathStartsWith -Path $env:DANMU_BUILD_PYTHON -Prefix "E:\cache\codex-runtimes\codex-primary-runtime\dependencies\python"
        }
    )

    foreach ($candidate in $candidates) {
        if ($candidate.Path -and (Test-Path -LiteralPath $candidate.Path)) {
            return $candidate
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Path = "py"
            Args = @("-3.12")
            Label = "py -3.12"
            SkipDependencyInstall = $true
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Path = "python"
            Args = @()
            Label = "python"
            SkipDependencyInstall = $false
        }
    }

    throw "No usable Python launcher found"
}

$PythonCmd = Resolve-PythonCommand
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

$distDir = Join-Path $Root "dist\DanmuAI"
$exe = Join-Path $distDir "DanmuAI.exe"

function Stop-DanmuAiProcesses {
    $procs = Get-Process -Name "DanmuAI" -ErrorAction SilentlyContinue
    if (-not $procs) {
        return
    }
    Write-Host "Stopping running DanmuAI.exe (dist output is locked while it runs)..."
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Clear-DistOutput {
    if (-not (Test-Path $distDir)) {
        return
    }
    try {
        Remove-Item -LiteralPath $distDir -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Error @"
Cannot remove $distDir — files are in use.
Close DanmuAI.exe / pywebview / tray, then rerun: .\scripts\build_exe.ps1
Original error: $($_.Exception.Message)
"@
    }
}

if ($PythonCmd.SkipDependencyInstall -and $env:DANMU_BUILD_FORCE_PIP_INSTALL -ne "1") {
    Write-Host "Skipping pip install for pre-provisioned build Python."
} else {
    Write-Host "Installing build deps..."
    & $PythonCmd.Path @($PythonCmd.Args) -m pip install -q -r requirements.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed with exit code $LASTEXITCODE"
    }
}

Stop-DanmuAiProcesses
Clear-DistOutput

Write-Host "Building with PyInstaller (onedir)..."
# Qt/dev excludes are in DanmuAI.spec (EXCLUDES); CLI --exclude-module is invalid with .spec.
& $PythonCmd.Path @($PythonCmd.Args) -m PyInstaller --noconfirm --clean DanmuAI.spec
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE. See build\DanmuAI\warn-DanmuAI.txt"
}

if (-not (Test-Path $exe)) {
    Write-Error "Build failed: $exe not found"
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
