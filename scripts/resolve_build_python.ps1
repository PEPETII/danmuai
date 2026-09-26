# Shared build-Python resolution for Windows release scripts (BUG-P0-002).
# Prefer project .venv-build, then an explicit DANMU_BUILD_PYTHON, then the
# Windows Python launcher. Callers that build or package a release must use
# Assert-BuildPython so the selected interpreter is validated.

function Test-PathStartsWith {
    param(
        [string]$Path,
        [string]$Prefix
    )
    if (-not $Path -or -not $Prefix) {
        return $false
    }
    return $Path.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-BuildPythonCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Root
    )

    $candidates = @(
        [pscustomobject]@{
            Path = (Join-Path $Root ".venv-build\Scripts\python.exe")
            Args = @()
            Label = ".venv-build"
            SkipDependencyInstall = $true
        },
        [pscustomobject]@{
            Path = (Join-Path $Root ".venv-build-312\Scripts\python.exe")
            Args = @()
            Label = ".venv-build-312"
            SkipDependencyInstall = $true
        },
        [pscustomobject]@{
            Path = $env:DANMU_BUILD_PYTHON
            Args = @()
            Label = "DANMU_BUILD_PYTHON"
            SkipDependencyInstall = Test-PathStartsWith -Path $env:DANMU_BUILD_PYTHON -Prefix "E:\cache\codex-runtimes\codex-primary-runtime\dependencies\python"
        }
    )

    foreach ($candidate in $candidates) {
        if ($candidate.Path -and (Test-Path -LiteralPath $candidate.Path)) {
            return $candidate
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Path = "py"
            Args = @("-3.12")
            Label = "py -3.12"
            SkipDependencyInstall = $true
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Path = "python"
            Args = @()
            Label = "python"
            SkipDependencyInstall = $false
        }
    }

    throw "No usable Python launcher found"
}

function Assert-BuildPython {
    param(
        [Parameter(Mandatory)]
        [string]$Root,
        [pscustomobject]$PythonCmd = $null
    )

    if (-not $PythonCmd) {
        $PythonCmd = Resolve-BuildPythonCommand -Root $Root
    }

    $infoCode = "import json,platform,struct,sys; print(json.dumps({'version': platform.python_version(), 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'machine': platform.machine(), 'bits': struct.calcsize('P') * 8}))"
    $infoOutput = & $PythonCmd.Path @($PythonCmd.Args) -c $infoCode 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build Python probe failed (exit $LASTEXITCODE): $infoOutput"
    }
    $infoLine = @($infoOutput | ForEach-Object { "$($_)".Trim() } | Where-Object { $_ }) | Select-Object -Last 1
    try {
        $info = $infoLine | ConvertFrom-Json
    } catch {
        Write-Error "Build Python probe returned invalid JSON: $infoLine"
    }

    if ([int]$info.major -ne 3 -or [int]$info.minor -ne 12) {
        Write-Error "Release builds require Python 3.12.x; selected $($info.version) ($($PythonCmd.Label))"
    }
    if ([int]$info.bits -ne 64) {
        Write-Error "Release builds require a 64-bit Python interpreter; selected $($info.bits)-bit ($($PythonCmd.Label))"
    }
    $machine = "$($info.machine)".ToUpperInvariant()
    if ($machine -notin @("AMD64", "X86_64")) {
        Write-Error "Release builds require Windows x64 Python; selected machine '$machine' ($($PythonCmd.Label))"
    }

    Write-Host "Build Python verified: $($info.version), $machine, $($info.bits)-bit ($($PythonCmd.Label))"
    return $PythonCmd
}

function Invoke-BuildPythonExpression {
    param(
        [Parameter(Mandatory)]
        [string]$Root,
        [Parameter(Mandatory)]
        [string]$Code,
        [pscustomobject]$PythonCmd = $null
    )

    if (-not $PythonCmd) {
        $PythonCmd = Resolve-BuildPythonCommand -Root $Root
    }
    $output = & $PythonCmd.Path @($PythonCmd.Args) -c $Code 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python failed (exit $LASTEXITCODE): $output"
    }
    return $output
}
