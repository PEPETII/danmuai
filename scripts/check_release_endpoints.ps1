#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only HTTP health checks for DanmuAI public release endpoints.

.DESCRIPTION
  Performs GET/HEAD requests only. Does not use R2 write credentials, Supabase
  anon keys, or GitHub tokens. Safe for scheduled tasks and post-release smoke.

.PARAMETER ExpectedVersion
  Optional semver; when set, feed latest Full must match (v prefix ignored).

.PARAMETER TimeoutSec
  Per-request timeout in seconds (default 30).

.EXAMPLE
  .\scripts\check_release_endpoints.ps1
  .\scripts\check_release_endpoints.ps1 -ExpectedVersion "0.3.8"
#>
[CmdletBinding()]
param(
    [string]$ExpectedVersion = '',
    [string]$FeedUrl = 'https://updates.qiaoqiao.buzz/releases/win/stable',
    [string]$SetupUrl = 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',
    [string]$PortableUrl = 'https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip',
    [string]$GitHubReleasesUrl = 'https://github.com/PEPETII/danmuai/releases',
    [string]$GitHubApiLatestUrl = 'https://api.github.com/repos/PEPETII/danmuai/releases/latest',
    [int]$TimeoutSec = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'version_parse.ps1')

if ($PSVersionTable.PSVersion.Major -lt 6) {
    $ProgressPreference = 'SilentlyContinue'
}

function Write-CheckLine {
    param(
        [string]$Name,
        [string]$Url,
        [int]$HttpStatus,
        [Nullable[long]]$ContentLength,
        [string]$Detail = '',
        [bool]$Ok
    )
    $lenText = if ($null -eq $ContentLength) { '-' } else { $ContentLength.ToString() }
    $status = if ($Ok) { 'OK' } else { 'FAIL' }
    Write-Host ("{0,-10} HTTP={1,3} Size={2,12} {3,-4} {4} {5}" -f $Name, $HttpStatus, $lenText, $status, $Detail, $Url)
}

function Normalize-Semver {
    param([string]$Version)
    return (Normalize-AppSemVersion -Version $Version)
}

function Get-FeedLatestFullVersion {
    param($FeedObject)
    if ($null -eq $FeedObject) { return $null }
    $assets = $FeedObject.Assets
    if ($null -eq $assets) { return $null }
    $fullVersions = @(
        $assets |
            Where-Object { $_.Type -eq 'Full' -and $_.Version } |
            ForEach-Object { Normalize-Semver $_.Version }
    )
    if ($fullVersions.Count -eq 0) { return $null }
    return (Get-LatestAppSemVersion -Versions $fullVersions)
}

function Invoke-ReadOnlyHttpProbe {
    param(
        [string]$Name,
        [string]$Url,
        [ValidateSet('Head', 'Get')]
        [string]$PreferredMethod = 'Head'
    )

    $result = [ordered]@{
        Name          = $Name
        Url           = $Url
        HttpStatus    = 0
        ContentLength = $null
        Detail        = ''
        Ok            = $false
    }

    try {
        $params = @{
            Uri             = $Url
            Method          = $PreferredMethod
            TimeoutSec      = $TimeoutSec
            UseBasicParsing = $true
        }
        $response = Invoke-WebRequest @params
        $result.HttpStatus = [int]$response.StatusCode
        if ($response.Headers['Content-Length']) {
            $result.ContentLength = [long]$response.Headers['Content-Length']
        }
        elseif ($null -ne $response.RawContentLength) {
            $result.ContentLength = [long]$response.RawContentLength
        }

        if ($result.HttpStatus -lt 200 -or $result.HttpStatus -ge 300) {
            $result.Detail = 'non-2xx'
            return $result
        }

        if ($PreferredMethod -eq 'Head' -and $null -eq $result.ContentLength) {
            $getResponse = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec $TimeoutSec -UseBasicParsing
            $result.HttpStatus = [int]$getResponse.StatusCode
            if ($getResponse.Headers['Content-Length']) {
                $result.ContentLength = [long]$getResponse.Headers['Content-Length']
            }
            else {
                $bytes = $getResponse.RawContentStream
                if ($bytes) {
                    $result.ContentLength = [long]$bytes.Length
                }
                elseif ($null -ne $getResponse.Content) {
                    $result.ContentLength = [long][System.Text.Encoding]::UTF8.GetByteCount([string]$getResponse.Content)
                }
            }
        }

        if ($null -eq $result.ContentLength -or $result.ContentLength -le 0) {
            $result.Detail = 'empty-body'
            return $result
        }

        $result.Ok = $true
        return $result
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp -and $resp.StatusCode) {
            $result.HttpStatus = [int]$resp.StatusCode
            $result.Detail = $_.Exception.Message
        }
        else {
            $result.Detail = $_.Exception.Message
        }
        return $result
    }
}

function Test-FeedEndpoint {
    param(
        [string]$Url,
        [string]$ExpectedVersionNormalized
    )

    $result = [ordered]@{
        Name          = 'Feed'
        Url           = $Url
        HttpStatus    = 0
        ContentLength = $null
        Detail        = ''
        Ok            = $false
    }

    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $TimeoutSec
        $result.HttpStatus = 200
        $json = $response | ConvertTo-Json -Depth 8 -Compress
        $result.ContentLength = [long][System.Text.Encoding]::UTF8.GetByteCount($json)
        $latest = Get-FeedLatestFullVersion -FeedObject $response
        if (-not $latest) {
            $result.Detail = 'no Full asset'
            return $result
        }
        $result.Detail = "FeedLatestFull=$latest"
        if ($ExpectedVersionNormalized -and (Normalize-Semver $latest) -ne $ExpectedVersionNormalized) {
            $result.Detail = "FeedLatestFull=$latest expected=$ExpectedVersionNormalized"
            return $result
        }
        $result.Ok = $true
        return $result
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp -and $resp.StatusCode) {
            $result.HttpStatus = [int]$resp.StatusCode
        }
        $result.Detail = $_.Exception.Message
        return $result
    }
}

function Test-GitHubLatestTag {
    param(
        [string]$ApiUrl,
        [string]$ExpectedVersionNormalized
    )

    $result = [ordered]@{
        Name          = 'GitHubAPI'
        Url           = $ApiUrl
        HttpStatus    = 0
        ContentLength = $null
        Detail        = ''
        Ok            = $false
    }

    try {
        $headers = @{ 'User-Agent' = 'DanmuAI-release-monitor' }
        $release = Invoke-RestMethod -Uri $ApiUrl -Method Get -TimeoutSec $TimeoutSec -Headers $headers
        $result.HttpStatus = 200
        $tag = [string]$release.tag_name
        $result.Detail = "tag=$tag"
        if ($ExpectedVersionNormalized) {
            if ((Normalize-Semver $tag) -ne $ExpectedVersionNormalized) {
                $result.Detail = "tag=$tag expected=$ExpectedVersionNormalized"
                return $result
            }
        }
        $result.Ok = $true
        return $result
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp -and $resp.StatusCode) {
            $result.HttpStatus = [int]$resp.StatusCode
        }
        $result.Detail = $_.Exception.Message
        return $result
    }
}

$expectedNormalized = ''
if ($ExpectedVersion) {
    $expectedNormalized = Normalize-Semver $ExpectedVersion
    Write-Host "ExpectedVersion: $expectedNormalized"
}

Write-Host ''
Write-Host 'DanmuAI release endpoint monitor (read-only GET/HEAD)'
Write-Host ''

$checks = @(
    (Test-FeedEndpoint -Url $FeedUrl -ExpectedVersionNormalized $expectedNormalized)
    (Invoke-ReadOnlyHttpProbe -Name 'Setup' -Url $SetupUrl -PreferredMethod Head)
    (Invoke-ReadOnlyHttpProbe -Name 'Portable' -Url $PortableUrl -PreferredMethod Head)
    (Invoke-ReadOnlyHttpProbe -Name 'GitHub' -Url $GitHubReleasesUrl -PreferredMethod Get)
    (Test-GitHubLatestTag -ApiUrl $GitHubApiLatestUrl -ExpectedVersionNormalized $expectedNormalized)
)

$failed = 0
foreach ($check in $checks) {
    Write-CheckLine @check
    if (-not $check.Ok) { $failed++ }
}

Write-Host ''
Write-Host 'Supabase app_updates: verify manually (Table Editor or GET /api/update/channels with env vars).'
Write-Host '  release_url should match Setup alias:'
Write-Host "  $SetupUrl"
Write-Host ''
Write-Host 'Reminder: local release/velopack/ artifacts ready != online feed/alias healthy.'
Write-Host ''

if ($failed -gt 0) {
    Write-Host "FAILED: $failed check(s) require attention."
    exit 1
}

Write-Host 'All automated checks passed.'
exit 0
