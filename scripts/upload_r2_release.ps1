# Upload Velopack release to Cloudflare R2 (primary distribution source).
# Credentials via environment variables ONLY - never commit secrets.
#
# Required env:
#   R2_ACCOUNT_ID
#   R2_ACCESS_KEY_ID
#   R2_SECRET_ACCESS_KEY
#   R2_BUCKET
# Optional:
#   R2_RELEASE_DIR  (default: release/velopack)
#
# Requires AWS CLI v2: https://aws.amazon.com/cli/
# Usage: .\scripts\upload_r2_release.ps1

param(
    [string]$ReleaseDir = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $ReleaseDir) {
    $ReleaseDir = $env:R2_RELEASE_DIR
}
if (-not $ReleaseDir) {
    $ReleaseDir = "release\velopack"
}

$releaseFull = Join-Path $Root $ReleaseDir
if (-not (Test-Path $releaseFull)) {
    Write-Error "Missing $releaseFull - run .\scripts\publish_windows_release.ps1 first"
}

function Ensure-AwsCommand {
    $aws = Get-Command aws -ErrorAction SilentlyContinue
    if ($aws) {
        return $aws
    }

    $defaultAwsDir = "C:\Program Files\Amazon\AWSCLIV2"
    $defaultAwsExe = Join-Path $defaultAwsDir "aws.exe"
    if (Test-Path $defaultAwsExe) {
        $env:Path = "$defaultAwsDir;$env:Path"
        return Get-Command aws -ErrorAction SilentlyContinue
    }

    return $null
}

foreach ($var in @("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")) {
    if (-not (Get-Item "env:$var" -ErrorAction SilentlyContinue)) {
        Write-Error "Missing environment variable: $var"
    }
}

$aws = Ensure-AwsCommand
if (-not $aws) {
    Write-Error "AWS CLI not found. Install AWS CLI v2 for S3-compatible R2 uploads."
}

$endpoint = "https://$($env:R2_ACCOUNT_ID).r2.cloudflarestorage.com"
$bucket = $env:R2_BUCKET
$appVersion = (python -c "from app.version import __version__; print(__version__)").Trim()

$setup = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-$appVersion-Setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $setup) {
    $setup = Get-ChildItem -Path $releaseFull -Filter "*-Setup.exe" | Select-Object -First 1
}
$nupkg = Get-ChildItem -Path $releaseFull -Filter "*-full.nupkg" | Select-Object -First 1
$feed = Join-Path $releaseFull "releases.win.json"

if (-not $setup -or -not $nupkg -or -not (Test-Path $feed)) {
    Write-Error "Incomplete Velopack release in $releaseFull (need Setup, full.nupkg, releases.win.json)"
}

$uploads = @(
    @{ Local = $feed; Key = "releases/win/stable/releases.win.json"; Cache = "public, max-age=60" }
    @{ Local = $nupkg.FullName; Key = "releases/win/stable/$($nupkg.Name)"; Cache = "public, max-age=3600" }
    @{ Local = $setup.FullName; Key = "downloads/PEPETII.DanmuAI-$appVersion-Setup.exe"; Cache = "public, max-age=86400" }
    @{ Local = $setup.FullName; Key = "downloads/DanmuAI-Setup.exe"; Cache = "no-cache" }
)

function Invoke-R2Cp {
    param([string]$LocalPath, [string]$Key, [string]$CacheControl)
    $uri = "s3://$bucket/$Key"
    Write-Host "$(if ($DryRun) { '[dry-run] ' })upload: $LocalPath -> $uri"
    if ($DryRun) { return }
    $args = @(
        "s3", "cp", $LocalPath, $uri,
        "--endpoint-url", $endpoint,
        "--cache-control", $CacheControl
    )
    $env:AWS_ACCESS_KEY_ID = $env:R2_ACCESS_KEY_ID
    $env:AWS_SECRET_ACCESS_KEY = $env:R2_SECRET_ACCESS_KEY
    $env:AWS_DEFAULT_REGION = "auto"
    & aws @args
    if ($LASTEXITCODE -ne 0) {
        Write-Error "aws s3 cp failed for $Key"
    }
}

Write-Host "R2 upload -> $bucket @ $endpoint"
Write-Host "Version: $appVersion"
Write-Host "Public URLs (custom domain):"
Write-Host "  https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
Write-Host "  https://updates.qiaoqiao.buzz/releases/win/stable"
Write-Host ""

foreach ($item in $uploads) {
    Invoke-R2Cp -LocalPath $item.Local -Key $item.Key -CacheControl $item.Cache
}

Write-Host ""
Write-Host "Done. GitHub Releases upload is mirror-only: .\scripts\upload_github_release.ps1"
