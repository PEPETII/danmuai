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
# Usage:
#   .\scripts\upload_r2_release.ps1
#   .\scripts\upload_r2_release.ps1 -Version 0.3.1
#   .\scripts\upload_r2_release.ps1 -Version 0.3.1 -DryRun

param(
    [string]$ReleaseDir = "",
    [string]$Version = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")
. (Join-Path $PSScriptRoot "version_parse.ps1")

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

function Get-VersionFromVersionFile {
    param([string]$Dir)
    $versionFile = Join-Path $Dir "VERSION.txt"
    if (-not (Test-Path -LiteralPath $versionFile)) { return $null }
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $versionFile) {
        if ($line -match '^\s*Version:\s*(\S+)\s*$') {
            return $Matches[1]
        }
    }
    return $null
}

function Resolve-UploadVersion {
    param([string]$ExplicitVersion, [string]$Dir)
    if ($ExplicitVersion) { return $ExplicitVersion.Trim() }
    $fromFile = Get-VersionFromVersionFile -Dir $Dir
    if ($fromFile) { return $fromFile }
    $pythonCmd = Resolve-BuildPythonCommand -Root $Root
    return Get-AppVersionFromProject -Root $Root -PythonCmd $pythonCmd
}

function Get-FeedLatestFullVersion {
    param([string]$FeedPath)
    $json = Get-Content -Raw -Encoding UTF8 -LiteralPath $FeedPath | ConvertFrom-Json
    $fullVersions = @(
        $json.Assets |
            Where-Object { $_.Type -eq "Full" } |
            ForEach-Object { [version]$_.Version }
    )
    if ($fullVersions.Count -eq 0) { return $null }
    return ($fullVersions | Sort-Object -Descending | Select-Object -First 1).ToString()
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
$appVersion = Resolve-UploadVersion -ExplicitVersion $Version -Dir $releaseFull
$feed = Join-Path $releaseFull "releases.win.json"

if (-not (Test-Path -LiteralPath $feed)) {
    Write-Error "Missing $feed"
}

$feedLatest = Get-FeedLatestFullVersion -FeedPath $feed
if (-not $feedLatest) {
    Write-Error "releases.win.json has no Full assets"
}
if ($feedLatest -ne $appVersion) {
    Write-Error "Upload version $appVersion does not match feed latest Full version $feedLatest"
}

$setup = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-$appVersion-Setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $setup) {
    $setup = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-win-Setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}
$nupkg = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-$appVersion-full.nupkg" -ErrorAction SilentlyContinue | Select-Object -First 1
$deltaNupkgs = @(Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-$appVersion-delta.nupkg" -ErrorAction SilentlyContinue | Sort-Object Name)
$portable = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-$appVersion-win-Portable.zip" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $portable) {
    $portable = Get-ChildItem -Path $releaseFull -Filter "PEPETII.DanmuAI-win-Portable.zip" -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $setup -or -not $nupkg) {
    Write-Error "Incomplete Velopack release in $releaseFull for version $appVersion (need Setup and full.nupkg)"
}

. (Join-Path $PSScriptRoot "write_release_hash_manifest.ps1")
Test-ReleaseHashManifest -Dir $releaseFull -AppVersion $appVersion | Out-Null
Write-Host "SHA256 manifest verification passed."

$uploads = @(
    @{ Local = $nupkg.FullName; Key = "releases/win/stable/$($nupkg.Name)"; Cache = "public, max-age=3600"; ExpectedSize = $nupkg.Length }
    @{ Local = $setup.FullName; Key = "downloads/PEPETII.DanmuAI-$appVersion-Setup.exe"; Cache = "public, max-age=86400"; ExpectedSize = $setup.Length }
)
foreach ($delta in $deltaNupkgs) {
    $uploads += @{ Local = $delta.FullName; Key = "releases/win/stable/$($delta.Name)"; Cache = "public, max-age=3600"; ExpectedSize = $delta.Length }
}
if ($portable) {
    $portableKey = if ($portable.Name -match "^PEPETII\.DanmuAI-\d") {
        "downloads/$($portable.Name)"
    } else {
        "downloads/PEPETII.DanmuAI-$appVersion-win-Portable.zip"
    }
    $uploads += @{ Local = $portable.FullName; Key = $portableKey; Cache = "public, max-age=86400"; ExpectedSize = $portable.Length }
}
$feedKey = "releases/win/stable/releases.win.json"
$feedAliasKey = "releases/win/stable"
$feedSize = (Get-Item -LiteralPath $feed).Length
$uploads += @{ Local = $feed; Key = $feedKey; Cache = "public, max-age=60"; ExpectedSize = $feedSize; ContentType = "application/json" }
$uploads += @{ Local = $feed; Key = $feedAliasKey; Cache = "public, max-age=60"; ExpectedSize = $feedSize; ContentType = "application/json" }

$manifestPath = Join-Path $releaseFull "SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Error "Missing SHA256SUMS.txt in $releaseFull"
}
$manifestLines = @(Get-Content -Encoding UTF8 -LiteralPath $manifestPath | Where-Object { $_.Trim() })
foreach ($item in $uploads) {
    $basename = [System.IO.Path]::GetFileName($item.Local)
    $manifestPattern = "^[0-9a-f]{64}  $([regex]::Escape($basename))$"
    $manifestEntry = @($manifestLines | Where-Object { $_ -match $manifestPattern } | Select-Object -First 1)
    if ($manifestEntry.Count -eq 0) {
        Write-Error "Upload artifact not listed in SHA256SUMS.txt: $basename"
    }
}

$versionedSetupKey = "downloads/PEPETII.DanmuAI-$appVersion-Setup.exe"
$versionedPortableKey = "downloads/PEPETII.DanmuAI-$appVersion-win-Portable.zip"

function Set-AwsEnv {
    $env:AWS_ACCESS_KEY_ID = $env:R2_ACCESS_KEY_ID
    $env:AWS_SECRET_ACCESS_KEY = $env:R2_SECRET_ACCESS_KEY
    $env:AWS_DEFAULT_REGION = "auto"
}

function Assert-R2Object {
    param([string]$Key, [long]$ExpectedSize)
    if ($DryRun) { return }
    Set-AwsEnv
    $headJson = aws s3api head-object --bucket $bucket --key $Key --endpoint-url $endpoint 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Missing uploaded object: $Key"
    }
    $head = $headJson | ConvertFrom-Json
    if ([long]$head.ContentLength -ne $ExpectedSize) {
        Write-Error "Size mismatch for $Key (expected $ExpectedSize, got $($head.ContentLength))"
    }
}

function Invoke-R2Cp {
    param([string]$LocalPath, [string]$Key, [string]$CacheControl, [long]$ExpectedSize, [string]$ContentType = "")
    $uri = "s3://$bucket/$Key"
    Write-Host "$(if ($DryRun) { '[dry-run] ' })upload: $LocalPath -> $uri"
    if ($DryRun) { return }
    Set-AwsEnv
    $args = @(
        "s3", "cp", $LocalPath, $uri,
        "--endpoint-url", $endpoint,
        "--cache-control", $CacheControl,
        "--cli-read-timeout", "0",
        "--cli-connect-timeout", "120",
        "--only-show-errors"
    )
    if ($ContentType) {
        $args += @("--content-type", $ContentType)
    }
    & aws @args
    if ($LASTEXITCODE -ne 0) {
        Write-Error "aws s3 cp failed for $Key"
    }
    Assert-R2Object -Key $Key -ExpectedSize $ExpectedSize
}

function Invoke-R2LatestAliasCopy {
    param(
        [string]$SourceKey,
        [string]$AliasKey,
        [long]$ExpectedSize
    )
    $uri = "s3://$bucket/$AliasKey"
    Write-Host "$(if ($DryRun) { '[dry-run] ' })copy latest alias: s3://$bucket/$SourceKey -> $uri"
    if ($DryRun) { return }
    Set-AwsEnv
    & aws s3 cp "s3://$bucket/$SourceKey" $uri `
        --endpoint-url $endpoint `
        --cache-control "no-cache" `
        --metadata-directive REPLACE `
        --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        Write-Error "aws s3 cp failed for latest alias $AliasKey"
    }
    Assert-R2Object -Key $AliasKey -ExpectedSize $ExpectedSize
}

Write-Host "R2 upload -> $bucket @ $endpoint"
Write-Host "Version: $appVersion"
Write-Host "Delta package(s): $($deltaNupkgs.Count)"
Write-Host "Public URLs (custom domain):"
Write-Host "  https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe           (主入口)"
if ($portable) {
    Write-Host "  https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip (便携版)"
}
Write-Host "  https://updates.qiaoqiao.buzz/releases/win/stable                   (更新 feed)"
Write-Host ""

if ($uploads.Count -lt 2 -or $uploads[-2].Key -ne $feedKey -or $uploads[-1].Key -ne $feedAliasKey) {
    Write-Error "feed metadata must be uploaded last (got $($uploads[-2].Key), $($uploads[-1].Key))"
}

foreach ($item in $uploads) {
    $contentType = if ($item.ContainsKey("ContentType")) { $item.ContentType } else { "" }
    Invoke-R2Cp -LocalPath $item.Local -Key $item.Key -CacheControl $item.Cache -ExpectedSize $item.ExpectedSize -ContentType $contentType
}

Invoke-R2LatestAliasCopy -SourceKey $versionedSetupKey -AliasKey "downloads/DanmuAI-Setup.exe" -ExpectedSize $setup.Length
if ($portable) {
    Invoke-R2LatestAliasCopy -SourceKey $versionedPortableKey -AliasKey "downloads/PEPETII.DanmuAI-win-Portable.zip" -ExpectedSize $portable.Length
}

Write-Host ""
Write-Host "Done. GitHub Releases upload is mirror-only: .\scripts\upload_github_release.ps1"
