# Build DanmuAI Windows folder distribution (PyInstaller onedir).
# Requires: pip install -r requirements.txt -r requirements-dev.txt
# Output: dist/DanmuAI/DanmuAI.exe

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "resources\icon.ico") -or -not (Test-Path "resources\icon.png")) {
    Write-Host "Generating resources\icon.ico + icon.png ..."
    python (Join-Path $Root "scripts\generate_app_icon.py")
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

Write-Host "Installing build deps..."
python -m pip install -q -r requirements.txt -r requirements-dev.txt

Stop-DanmuAiProcesses
Clear-DistOutput

Write-Host "Building with PyInstaller (onedir)..."
# Qt/dev excludes are in DanmuAI.spec (EXCLUDES); CLI --exclude-module is invalid with .spec.
python -m PyInstaller --noconfirm --clean DanmuAI.spec
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE. See build\DanmuAI\warn-DanmuAI.txt"
}

if (-not (Test-Path $exe)) {
    Write-Error "Build failed: $exe not found"
}

Write-Host ""
Write-Host "Done: $exe"
Write-Host "Zip dist\DanmuAI\ for distribution. End users need WebView2 Runtime (usually preinstalled on Windows 10/11)."
