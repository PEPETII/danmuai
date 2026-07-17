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

$MinimumSetupBytes = 8MB
$MinimumPortableBytes = 8MB
$MagicProbeBytes = 4KB
$ZipTailProbeBytes = 1MB

Add-Type -AssemblyName System.Net.Http

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

function Invoke-BoundedRangeGet {
    param(
        [string]$Url,
        [string]$RangeHeader,
        [int]$MaximumBytes
    )

    if ($MaximumBytes -le 0) {
        throw 'Range maximum must be positive.'
    }
    $rangeMatch = [regex]::Match($RangeHeader, '^bytes=(?:(\d+)-(\d+)|-(\d+))$')
    if (-not $rangeMatch.Success) {
        throw "Range header is not a supported bounded form: $RangeHeader"
    }

    $client = $null
    $request = $null
    $response = $null
    $stream = $null
    $cancellation = $null
    try {
        $deadlineUtc = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
        $cancellation = [System.Threading.CancellationTokenSource]::new()
        $cancellation.CancelAfter([TimeSpan]::FromSeconds($TimeoutSec))
        $request = [System.Net.Http.HttpRequestMessage]::new(
            [System.Net.Http.HttpMethod]::Get,
            [Uri]$Url
        )
        if (-not $request.Headers.TryAddWithoutValidation('Range', $RangeHeader)) {
            throw "Range header rejected: $RangeHeader"
        }

        $response = $client.SendAsync(
            $request,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead,
            $cancellation.Token
        ).GetAwaiter().GetResult()
        $statusCode = [int]$response.StatusCode
        $throwInvalidResponse = {
            param([string]$Message)
            $exception = [System.IO.InvalidDataException]::new($Message)
            $exception.Data['HttpStatus'] = $statusCode
            throw $exception
        }
        if ($statusCode -ne 206) {
            & $throwInvalidResponse "Range request requires HTTP 206; received HTTP $statusCode"
        }

        $contentRange = $response.Content.Headers.ContentRange
        if ($null -eq $contentRange -or -not $contentRange.HasRange -or -not $contentRange.HasLength) {
            & $throwInvalidResponse 'Range response is missing a complete Content-Range header.'
        }

        $totalLength = [long]$contentRange.Length
        $rangeStart = [long]$contentRange.From
        $rangeEnd = [long]$contentRange.To
        if ($totalLength -le 0) {
            & $throwInvalidResponse 'Range response reported a non-positive total length.'
        }

        if ($rangeMatch.Groups[3].Success) {
            $suffixLength = [long]::Parse($rangeMatch.Groups[3].Value)
            if ($suffixLength -le 0) {
                & $throwInvalidResponse 'Range suffix length must be positive.'
            }
            $expectedStart = [Math]::Max([long]0, $totalLength - $suffixLength)
            $expectedEnd = $totalLength - 1
        }
        else {
            $requestedStart = [long]::Parse($rangeMatch.Groups[1].Value)
            $requestedEnd = [long]::Parse($rangeMatch.Groups[2].Value)
            if ($requestedStart -gt $requestedEnd -or $requestedStart -ge $totalLength) {
                & $throwInvalidResponse 'Range response cannot satisfy the requested byte interval.'
            }
            $expectedStart = $requestedStart
            $expectedEnd = [Math]::Min($requestedEnd, $totalLength - 1)
        }

        if ($rangeStart -ne $expectedStart -or $rangeEnd -ne $expectedEnd) {
            & $throwInvalidResponse (
                "Range response interval mismatch: received bytes $rangeStart-$rangeEnd/$totalLength; " +
                "expected $expectedStart-$expectedEnd/$totalLength."
            )
        }
        $expectedBytes = $expectedEnd - $expectedStart + 1
        if ($expectedBytes -gt $MaximumBytes) {
            & $throwInvalidResponse "Range response interval exceeds the $MaximumBytes-byte read limit."
        }

        $declaredLength = $response.Content.Headers.ContentLength
        if ($null -ne $declaredLength -and [long]$declaredLength -ne $expectedBytes) {
            & $throwInvalidResponse (
                "Range response Content-Length mismatch: received $declaredLength; expected $expectedBytes."
            )
        }

        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        if (-not $stream.CanTimeout) {
            & $throwInvalidResponse 'Range response stream does not support a bounded read timeout.'
        }
        $setRemainingReadTimeout = {
            $remainingMs = [Math]::Ceiling(($deadlineUtc - [DateTime]::UtcNow).TotalMilliseconds)
            if ($remainingMs -le 0) {
                & $throwInvalidResponse "Range response body exceeded the $TimeoutSec-second timeout."
            }
            $stream.ReadTimeout = [int][Math]::Min([double][int]::MaxValue, $remainingMs)
        }

        $buffer = [byte[]]::new($MaximumBytes)
        $bytesRead = 0
        while ($bytesRead -lt $MaximumBytes) {
            & $setRemainingReadTimeout
            try {
                $read = $stream.Read($buffer, $bytesRead, $MaximumBytes - $bytesRead)
            }
            catch {
                & $throwInvalidResponse "Range response body read failed: $($_.Exception.Message)"
            }
            if ($read -le 0) { break }
            $bytesRead += $read
        }

        $extra = [byte[]]::new(1)
        & $setRemainingReadTimeout
        try {
            $extraRead = $stream.Read($extra, 0, 1)
        }
        catch {
            & $throwInvalidResponse "Range response body read failed: $($_.Exception.Message)"
        }
        if ($extraRead -gt 0) {
            & $throwInvalidResponse "Range response exceeds the $MaximumBytes-byte read limit."
        }
        if ($bytesRead -ne $expectedBytes) {
            & $throwInvalidResponse (
                "Range response body was truncated: received $bytesRead bytes; expected $expectedBytes."
            )
        }

        $bytes = [byte[]]::new($bytesRead)
        if ($bytesRead -gt 0) {
            [Array]::Copy($buffer, 0, $bytes, 0, $bytesRead)
        }

        return [ordered]@{
            HttpStatus = $statusCode
            TotalLength = $totalLength
            RangeStart = $rangeStart
            RangeEnd = $rangeEnd
            Bytes = $bytes
        }
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $request) { $request.Dispose() }
        if ($null -ne $client) { $client.Dispose() }
        if ($null -ne $cancellation) { $cancellation.Dispose() }
    }
}

function Get-UInt16LittleEndian {
    param(
        [byte[]]$Bytes,
        [int]$Offset
    )
    return [uint16](
        [uint32]$Bytes[$Offset] -bor
        ([uint32]$Bytes[$Offset + 1] -shl 8)
    )
}

function Get-UInt32LittleEndian {
    param(
        [byte[]]$Bytes,
        [int]$Offset
    )
    return [uint32](
        [uint32]$Bytes[$Offset] -bor
        ([uint32]$Bytes[$Offset + 1] -shl 8) -bor
        ([uint32]$Bytes[$Offset + 2] -shl 16) -bor
        ([uint32]$Bytes[$Offset + 3] -shl 24)
    )
}

function Test-ZipPortableLayout {
    param(
        [byte[]]$TailBytes,
        [long]$TotalLength
    )

    $invalid = {
        param([string]$Detail)
        return [ordered]@{ Ok = $false; Detail = $Detail }
    }

    if ($TailBytes.Length -lt 22) {
        return (& $invalid 'ZIP layout invalid: tail is too short for EOCD.')
    }

    $minimumIndex = [Math]::Max(0, $TailBytes.Length - 65557)
    $eocdIndex = -1
    for ($index = $TailBytes.Length - 22; $index -ge $minimumIndex; $index--) {
        if (
            $TailBytes[$index] -eq 0x50 -and
            $TailBytes[$index + 1] -eq 0x4B -and
            $TailBytes[$index + 2] -eq 0x05 -and
            $TailBytes[$index + 3] -eq 0x06
        ) {
            $commentLength = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($index + 20)
            if ($index + 22 + $commentLength -eq $TailBytes.Length) {
                $eocdIndex = $index
                break
            }
        }
    }
    if ($eocdIndex -lt 0) {
        return (& $invalid 'ZIP layout invalid: EOCD not found in bounded tail probe.')
    }

    $diskNumber = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 4)
    $directoryDisk = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 6)
    $entriesOnDisk = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 8)
    $entryCount = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 10)
    $directorySize = [long](Get-UInt32LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 12))
    $directoryOffset = [long](Get-UInt32LittleEndian -Bytes $TailBytes -Offset ($eocdIndex + 16))
    if ($diskNumber -ne 0 -or $directoryDisk -ne 0 -or $entriesOnDisk -ne $entryCount) {
        return (& $invalid 'ZIP layout invalid: multi-disk archives are unsupported.')
    }
    if ($entryCount -le 0) {
        return (& $invalid 'ZIP layout invalid: central directory has no entries.')
    }

    $tailStart = $TotalLength - $TailBytes.LongLength
    $directoryEnd = $directoryOffset + $directorySize
    $eocdAbsolute = $tailStart + $eocdIndex
    if ($directoryOffset -lt $tailStart -or $directoryEnd -gt $eocdAbsolute) {
        return (& $invalid 'ZIP layout invalid: central directory exceeds the bounded tail probe.')
    }

    $cursor = [int]($directoryOffset - $tailStart)
    $directoryEndRelative = [int]($directoryEnd - $tailStart)
    $names = [System.Collections.Generic.List[string]]::new()
    for ($entryIndex = 0; $entryIndex -lt $entryCount; $entryIndex++) {
        if ($cursor + 46 -gt $directoryEndRelative) {
            return (& $invalid 'ZIP layout invalid: truncated central directory header.')
        }
        if (
            $TailBytes[$cursor] -ne 0x50 -or
            $TailBytes[$cursor + 1] -ne 0x4B -or
            $TailBytes[$cursor + 2] -ne 0x01 -or
            $TailBytes[$cursor + 3] -ne 0x02
        ) {
            return (& $invalid 'ZIP layout invalid: central directory signature mismatch.')
        }

        $nameLength = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($cursor + 28)
        $extraLength = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($cursor + 30)
        $entryCommentLength = Get-UInt16LittleEndian -Bytes $TailBytes -Offset ($cursor + 32)
        $nextCursor = $cursor + 46 + $nameLength + $extraLength + $entryCommentLength
        if ($nextCursor -gt $directoryEndRelative) {
            return (& $invalid 'ZIP layout invalid: truncated central directory entry.')
        }

        $name = [System.Text.Encoding]::UTF8.GetString($TailBytes, $cursor + 46, $nameLength)
        $names.Add($name.Replace('\', '/'))
        $cursor = $nextCursor
    }

    if ($cursor -ne $directoryEndRelative) {
        return (& $invalid 'ZIP layout invalid: central directory size mismatch.')
    }

    $hasRootExe = $false
    $hasInternal = $false
    $hasVelopackStubMarker = $false
    foreach ($name in $names) {
        if ($name.Equals('DanmuAI.exe', [StringComparison]::OrdinalIgnoreCase)) {
            $hasRootExe = $true
        }
        if ($name.StartsWith('_internal/', [StringComparison]::OrdinalIgnoreCase)) {
            $hasInternal = $true
        }
        if (
            $name.Equals('.portable', [StringComparison]::OrdinalIgnoreCase) -or
            $name.Equals('Update.exe', [StringComparison]::OrdinalIgnoreCase) -or
            $name.Equals('current/DanmuAI.exe', [StringComparison]::OrdinalIgnoreCase)
        ) {
            $hasVelopackStubMarker = $true
        }
    }

    if ($hasVelopackStubMarker) {
        return (& $invalid 'ZIP layout invalid: Velopack portable-stub markers detected.')
    }
    if (-not $hasRootExe -or -not $hasInternal) {
        return (& $invalid 'ZIP layout invalid: expected root DanmuAI.exe and _internal/ content.')
    }

    return [ordered]@{
        Ok = $true
        Detail = "ZIP layout valid; entries=$entryCount"
    }
}

function Test-SetupEndpoint {
    param([string]$Url)

    $result = [ordered]@{
        Name          = 'Setup'
        Url           = $Url
        HttpStatus    = 0
        ContentLength = $null
        Detail        = ''
        Ok            = $false
    }

    try {
        $probe = Invoke-BoundedRangeGet -Url $Url -RangeHeader "bytes=0-$($MagicProbeBytes - 1)" -MaximumBytes $MagicProbeBytes
        $result.HttpStatus = $probe.HttpStatus
        $result.ContentLength = $probe.TotalLength
        if ($probe.TotalLength -lt $MinimumSetupBytes) {
            $result.Detail = "Setup content invalid: too small ($($probe.TotalLength) bytes; minimum=$MinimumSetupBytes)."
            return $result
        }
        if ($probe.Bytes.Length -lt 2 -or $probe.Bytes[0] -ne 0x4D -or $probe.Bytes[1] -ne 0x5A) {
            $result.Detail = 'Setup content invalid: MZ magic missing.'
            return $result
        }

        $result.Detail = 'MZ valid; bounded Range probe.'
        $result.Ok = $true
        return $result
    }
    catch {
        if ($_.Exception.Data.Contains('HttpStatus')) {
            $result.HttpStatus = [int]$_.Exception.Data['HttpStatus']
        }
        $result.Detail = "Setup content invalid: $($_.Exception.Message)"
        return $result
    }
}

function Test-PortableEndpoint {
    param([string]$Url)

    $result = [ordered]@{
        Name          = 'Portable'
        Url           = $Url
        HttpStatus    = 0
        ContentLength = $null
        Detail        = ''
        Ok            = $false
    }

    try {
        $prefix = Invoke-BoundedRangeGet -Url $Url -RangeHeader "bytes=0-$($MagicProbeBytes - 1)" -MaximumBytes $MagicProbeBytes
        $result.HttpStatus = $prefix.HttpStatus
        $result.ContentLength = $prefix.TotalLength
        if ($prefix.TotalLength -lt $MinimumPortableBytes) {
            $result.Detail = "Portable content invalid: too small ($($prefix.TotalLength) bytes; minimum=$MinimumPortableBytes)."
            return $result
        }
        if (
            $prefix.Bytes.Length -lt 4 -or
            $prefix.Bytes[0] -ne 0x50 -or
            $prefix.Bytes[1] -ne 0x4B -or
            $prefix.Bytes[2] -ne 0x03 -or
            $prefix.Bytes[3] -ne 0x04
        ) {
            $result.Detail = 'Portable content invalid: ZIP local-file magic missing.'
            return $result
        }

        $tail = Invoke-BoundedRangeGet -Url $Url -RangeHeader "bytes=-$ZipTailProbeBytes" -MaximumBytes $ZipTailProbeBytes
        if ($tail.TotalLength -ne $prefix.TotalLength) {
            $result.Detail = 'Portable content invalid: asset length changed between Range probes.'
            return $result
        }
        $layout = Test-ZipPortableLayout -TailBytes $tail.Bytes -TotalLength $tail.TotalLength
        if (-not $layout.Ok) {
            $result.Detail = "Portable content invalid: $($layout.Detail)"
            return $result
        }

        $result.Detail = "$($layout.Detail); bounded Range probes."
        $result.Ok = $true
        return $result
    }
    catch {
        if ($_.Exception.Data.Contains('HttpStatus')) {
            $result.HttpStatus = [int]$_.Exception.Data['HttpStatus']
        }
        $result.Detail = "Portable content invalid: $($_.Exception.Message)"
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
    (Test-SetupEndpoint -Url $SetupUrl)
    (Test-PortableEndpoint -Url $PortableUrl)
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
