# Reset DanmuAI local data to first-run state (settings, API keys, history, stats).
# Quit DanmuAI (tray -> exit or close python main.py) before running.

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dir = Join-Path $env:APPDATA "DanmuAI"

if (-not (Test-Path $dir)) {
    Write-Host "Nothing to reset: $dir does not exist."
    exit 0
}

$patterns = @("config.db", "config.db-wal", "config.db-shm", ".key")
$removed = @()

foreach ($name in $patterns) {
    $path = Join-Path $dir $name
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Force
        $removed += $name
    }
}

if ($removed.Count -eq 0) {
    Write-Host "No config files found under $dir"
} else {
    Write-Host "Removed: $($removed -join ', ')"
    Write-Host "Restart DanmuAI (python main.py) for a fresh first-run experience."
    Write-Host "Settings will show built-in defaults (speed, tracks, freshness, etc.)."
}
