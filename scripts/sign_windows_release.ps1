# Optional Windows code-signing helper for DanmuAI.
# Integrated into publish_windows_release.ps1: when DANMU_CODE_SIGN=1, post-pack verification runs automatically.
#
# Default: signing DISABLED. Set DANMU_CODE_SIGN=1 to enable.
# Credentials via environment variables ONLY — never commit PFX, passwords, or PINs.
#
# Docs: docs/operations/WINDOWS_CODE_SIGNING.md
# Assessment: reports/windows-code-signing-assessment.md
#
# Usage:
#   .\scripts\sign_windows_release.ps1 -VerifyOnly     # verify Setup.exe signatures
#   .\scripts\sign_windows_release.ps1                 # print signing prerequisites (no pack)
#
# SIGN-004 (done): velopack_pack.ps1 reads VPK_SIGN_PARAMS / VPK_AZURE_TRUSTED_SIGN_FILE
# when DANMU_CODE_SIGN=1 during vpk pack.
# W-PACK-007 (done): publish_windows_release.ps1 calls this script with -VerifyOnly after pack.

param(
    [string]$ReleaseDir = "",
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($env:DANMU_CODE_SIGN -ne "1") {
    Write-Host "Code signing disabled (DANMU_CODE_SIGN is not 1). No action taken."
    Write-Host "See docs/operations/WINDOWS_CODE_SIGNING.md"
    exit 0
}

if (-not $ReleaseDir) {
    $ReleaseDir = Join-Path $Root "release\velopack"
}

function Find-SignTool {
    $cmd = Get-Command signtool -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $kitsRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidates = Get-ChildItem -Path $kitsRoot -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "x64" } |
            Sort-Object FullName -Descending
        if ($candidates) { return $candidates[0].FullName }
    }
    return $null
}

function Test-SigningConfig {
    $hasParams = [bool](Get-Item "env:VPK_SIGN_PARAMS" -ErrorAction SilentlyContinue)
    $hasAzure = [bool](Get-Item "env:VPK_AZURE_TRUSTED_SIGN_FILE" -ErrorAction SilentlyContinue)
    if (-not $hasParams -and -not $hasAzure) {
        Write-Error @"
DANMU_CODE_SIGN=1 but no signing config found.
Set ONE of:
  VPK_SIGN_PARAMS          (signtool args for vpk pack --signParams)
  VPK_AZURE_TRUSTED_SIGN_FILE  (path to Azure Artifact Signing metadata JSON)
See docs/operations/WINDOWS_CODE_SIGNING.md
"@
    }
    if ($hasAzure) {
        $azureFile = $env:VPK_AZURE_TRUSTED_SIGN_FILE
        if (-not (Test-Path -LiteralPath $azureFile)) {
            Write-Error "VPK_AZURE_TRUSTED_SIGN_FILE not found: $azureFile"
        }
    }
}

function Invoke-VerifySetup {
    param([string]$Dir)

    if (-not (Test-Path -LiteralPath $Dir)) {
        Write-Error "Release directory not found: $Dir (run publish_windows_release.ps1 first)"
    }

    $signtool = Find-SignTool
    if (-not $signtool) {
        Write-Error "signtool.exe not found. Install Windows SDK or add signtool to PATH."
    }

    $setups = Get-ChildItem -Path $Dir -Filter "*-Setup.exe" -ErrorAction SilentlyContinue
    if (-not $setups) {
        Write-Error "No *-Setup.exe in $Dir"
    }

    $failed = $false
    foreach ($setup in $setups) {
        Write-Host "verify: $($setup.FullName)"
        & $signtool verify /pa /v $setup.FullName
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "signtool verify failed for $($setup.Name) (exit $LASTEXITCODE)"
            $failed = $true
        } else {
            Write-Host "  OK"
        }
    }

    if ($failed) {
        Write-Error "One or more Setup.exe files failed Authenticode verification."
    }
    Write-Host "All Setup.exe files verified."
}

if ($VerifyOnly) {
    Invoke-VerifySetup -Dir $ReleaseDir
    exit 0
}

# Non-verify mode: validate config and print next steps (does not invoke vpk pack).
Test-SigningConfig

Write-Host ""
Write-Host "Signing config present. To sign during pack (SIGN-004), velopack_pack.ps1 will pass:"
if ($env:VPK_AZURE_TRUSTED_SIGN_FILE) {
    Write-Host "  --azureTrustedSignFile (from VPK_AZURE_TRUSTED_SIGN_FILE)"
} else {
    Write-Host "  --signParams (from VPK_SIGN_PARAMS)"
}
Write-Host ""
Write-Host "This script does not run vpk pack. Signing is handled by velopack_pack.ps1 (SIGN-004)."
Write-Host "Post-pack verification is integrated into publish_windows_release.ps1 (W-PACK-007)."
Write-Host "To verify existing release artifacts:"
Write-Host "  .\scripts\sign_windows_release.ps1 -VerifyOnly"
