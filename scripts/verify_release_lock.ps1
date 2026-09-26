# Read-only preflight for the Windows release dependency lock.
# Verifies the selected Python runtime, pip consistency, and exact installed
# package versions without installing packages or contacting external services.

param(
    [string]$Root = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $Root) {
    $Root = Split-Path -Parent $PSScriptRoot
}

. (Join-Path $PSScriptRoot "resolve_build_python.ps1")

function Get-ReleaseLockPath {
    param([Parameter(Mandatory)][string]$ProjectRoot)
    return Join-Path $ProjectRoot "requirements-release-win-lock.txt"
}

function Get-ReleaseLockEntries {
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $lockPath = Get-ReleaseLockPath -ProjectRoot $ProjectRoot
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        Write-Error "Release lock file not found: $lockPath"
    }

    $entries = @{}
    $invalid = @()
    foreach ($line in Get-Content -LiteralPath $lockPath -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch '^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;]+)\s*$') {
            $invalid += $trimmed
            continue
        }
        $name = $Matches[1].ToLowerInvariant() -replace '[_.]+', '-'
        if ($entries.ContainsKey($name)) {
            Write-Error "Duplicate release lock entry: $name"
        }
        $entries[$name] = $Matches[2]
    }

    if ($invalid.Count -gt 0) {
        Write-Error "Release lock contains non-exact entries: $($invalid -join '; ')"
    }
    if ($entries.Count -eq 0) {
        Write-Error "Release lock contains no package entries: $lockPath"
    }
    return $entries
}

function Assert-ReleaseLockFile {
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $entries = Get-ReleaseLockEntries -ProjectRoot $ProjectRoot
    $lockPath = Get-ReleaseLockPath -ProjectRoot $ProjectRoot
    Write-Host "Release lock file verified: $lockPath ($($entries.Count) exact packages)"
}

function Assert-ReleaseDependencyLock {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [pscustomobject]$PythonCmd = $null
    )

    $expected = Get-ReleaseLockEntries -ProjectRoot $ProjectRoot
    if (-not $PythonCmd) {
        $PythonCmd = Assert-BuildPython -Root $ProjectRoot
    } else {
        Assert-BuildPython -Root $ProjectRoot -PythonCmd $PythonCmd | Out-Null
    }

    $pipCheckOutput = & $PythonCmd.Path @($PythonCmd.Args) -m pip check 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip check failed (exit $LASTEXITCODE): $pipCheckOutput"
    }

    $lockPath = Get-ReleaseLockPath -ProjectRoot $ProjectRoot
    $comparisonCode = @'
import importlib.metadata as metadata
import json
import re
import sys

lock_path = sys.argv[1]

def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()

expected = {}
for raw_line in open(lock_path, encoding='utf-8'):
    line = raw_line.strip()
    if not line or line.startswith('#'):
        continue
    match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;]+)', line)
    if not match:
        raise SystemExit(f'non-exact lock entry: {line}')
    expected[normalize(match.group(1))] = match.group(2)

installed = {}
for distribution in metadata.distributions():
    name = distribution.metadata.get('Name')
    if name:
        installed[normalize(name)] = distribution.version

missing = sorted(name for name in expected if name not in installed)
mismatched = sorted(
    f'{name} expected={expected[name]} actual={installed[name]}'
    for name in expected
    if name in installed and installed[name] != expected[name]
)
# pip is the bootstrap tool used to install the lock and is not a project dependency.
unexpected = sorted(name for name in installed if name not in expected and name != 'pip')

result = {
    'expected': len(expected),
    'missing': missing,
    'mismatched': mismatched,
    'unexpected': unexpected,
}
print(json.dumps(result, sort_keys=True))
sys.exit(1 if missing or mismatched or unexpected else 0)
'@

    $comparisonOutput = & $PythonCmd.Path @($PythonCmd.Args) -c $comparisonCode $lockPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Installed packages do not match the release lock: $comparisonOutput"
    }

    Write-Host "Release lock dependency check passed: $($expected.Count) exact packages; pip check passed."
}

# When dot-sourced, export functions only.
if ($MyInvocation.InvocationName -eq '.') {
    return
}

$pythonCmd = Assert-BuildPython -Root $Root
Assert-ReleaseDependencyLock -ProjectRoot $Root -PythonCmd $pythonCmd
exit 0
