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

# Credential leak check: supabase-config.js must not be in the dist output.
$leakedConfig = Join-Path $distDir "web\static\supabase-config.js"
if (Test-Path $leakedConfig) {
    Write-Error @"
Credential leak detected: $leakedConfig exists in dist output.
supabase-config.js contains Supabase credentials and must NOT be packaged.
Remove it from dist and verify DanmuAI.spec excludes it.
"@
}

Write-Host ""
Write-Host "Done: $exe"
Write-Host "Next: .\scripts\publish_windows_release.ps1 for Velopack Setup + Portable release bundle."
