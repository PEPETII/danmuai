# CPU profiling baseline helper for docs/cpu-performance-audit-report.md §6
# Requires: pip install py-spy (Windows attach may need elevated shell)
# Usage:
#   1. Start DanmuAI: python main.py  (or --web-browser for DevTools)
#   2. Configure scenario A/B/C below, idle 5 minutes
#   3. Note python.exe PID from Task Manager
#   4. Run: .\scripts\profile_cpu_baseline.ps1 -Pid <PID> -Scenario B -DurationSec 120

param(
    [Parameter(Mandatory = $true)]
    [int]$Pid,
    [ValidateSet('A', 'B', 'C')]
    [string]$Scenario = 'B',
    [int]$DurationSec = 120,
    [string]$OutputDir = '.\.local-ai\profiles'
)

$ErrorActionPreference = 'Stop'

function Resolve-PySpy {
    $cmd = Get-Command py-spy -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $scripts = Join-Path (python -c "import sys; print(sys.prefix)") 'Scripts\py-spy.exe'
    if (Test-Path $scripts) { return $scripts }
    throw 'py-spy not found. Install: python -m pip install py-spy'
}

$scenarios = @{
    A = 'Overlay only: Web closed, pet hidden, engine running, idle 5min'
    B = 'Typical: Web console open + WS connected + pet visible, engine running'
    C = 'Stress: B + multi-screen + danmu-pool page + manually close WS for HTTP fallback'
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$pySpy = Resolve-PySpy
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$svg = Join-Path $OutputDir "profile-6x-scenario-$Scenario-$stamp.svg"

Write-Host "Scenario $($Scenario): $($scenarios[$Scenario])"
Write-Host "PID=$Pid Duration=${DurationSec}s"
Write-Host "py-spy: $pySpy"
Write-Host ''
Write-Host '=== 6.1 main-thread hotspots (Qt) ==='
Write-Host 'Watch: _maybe_pool_topup, _publish_live_status, publish_status,'
Write-Host '       build_status_snapshot, _on_topmost_health_tick, PetWindow._on_anim_tick'
Write-Host ''
Write-Host '=== 6.2 uvicorn thread (use --subprocesses if needed) ==='
Write-Host 'Watch: GET /api/status, GET /api/logs/recent when WS degraded'
Write-Host 'DevTools Network: count api/* requests over 60s (WS connected vs ws.close())'
Write-Host ''

& $pySpy top --pid $Pid --duration $DurationSec
& $pySpy record -o $svg --pid $Pid --duration $DurationSec
Write-Host "Flame graph: $svg"
