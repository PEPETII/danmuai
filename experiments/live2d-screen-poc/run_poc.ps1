# Live2D screen POC launcher (isolated). Does not start DanmuAI.
param(
    [Parameter(Mandatory = $false)]
    [string]$Model = "",

    [Parameter(Mandatory = $false)]
    [string]$Config = "",

    [Parameter(Mandatory = $false)]
    [double]$DemoSeconds = 0,

    [Parameter(Mandatory = $false)]
    [switch]$ValidateOnly,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

if (-not $Model -and -not $Config) {
    Write-Host "Usage:"
    Write-Host '  .\run_poc.ps1 -Model "E:\path\to\Model.model3.json"'
    Write-Host '  .\run_poc.ps1 -Model "E:\path\to\Model.model3.json" -DemoSeconds 10'
    Write-Host '  .\run_poc.ps1 -Config ".\config.local.json"'
    Write-Host '  .\run_poc.ps1 -Model "..." -ValidateOnly'
    Write-Host ""
    Write-Host "Hotkeys: drag LMB | wheel scale | Ctrl+/- scale | Ctrl+[/] opacity | Ctrl+T click-through | Ctrl+Shift+F8 recover | Ctrl+M motion | Ctrl+E expression | Esc quit"
    exit 2
}

$pyArgs = @("-m", "src.main")
if ($Model) { $pyArgs += @("--model", $Model) }
if ($Config) { $pyArgs += @("--config", $Config) }
if ($DemoSeconds -gt 0) { $pyArgs += @("--demo-seconds", "$DemoSeconds") }
if ($ValidateOnly) { $pyArgs += @("--validate-only") }
if ($ExtraArgs) { $pyArgs += $ExtraArgs }

Write-Host "python $($pyArgs -join ' ')"
& python @pyArgs
exit $LASTEXITCODE
