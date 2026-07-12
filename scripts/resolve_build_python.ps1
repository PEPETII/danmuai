# Shared build-Python resolution for Windows release scripts (BUG-P0-002).
# Prefer project .venv-build; build_exe.ps1 may fall back to py/python.

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
        [string]$Root
    )

    $pythonCmd = Resolve-BuildPythonCommand -Root $Root
    if ($pythonCmd.Path -eq "py" -or $pythonCmd.Path -eq "python") {
        Write-Error @"
Build Python not found. Create .venv-build first:
  py -3.12 -m venv .venv-build
  .\.venv-build\Scripts\pip install -r requirements.txt -r requirements-dev.txt pyinstaller
"@
    }
    return $pythonCmd
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
