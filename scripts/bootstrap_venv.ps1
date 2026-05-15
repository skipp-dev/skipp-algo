[CmdletBinding()]
param(
    [string]$VenvPath = $(if ($env:SKIPP_VENV) { $env:SKIPP_VENV } else { Join-Path (Get-Location).Path '.venv' }),
    [string]$PythonPreference = '3.12'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReqFile = Join-Path $RepoRoot 'requirements.txt'

if (-not (Test-Path $ReqFile)) {
    throw "requirements.txt not found at $ReqFile"
}

function Resolve-PythonExecutable {
    param([string]$RequestedVersion)

    $candidates = @(
        @{ Name = 'py'; Args = @("-$RequestedVersion", '-c', 'import sys; print(sys.executable)') },
        @{ Name = 'py'; Args = @('-3', '-c', 'import sys; print(sys.executable)') },
        @{ Name = 'python'; Args = @('-c', 'import sys; print(sys.executable)') }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Name -ErrorAction SilentlyContinue)) {
            continue
        }

        $output = & $candidate.Name @($candidate.Args) 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            return ($output | Select-Object -First 1).Trim()
        }
    }

    throw "No usable Python interpreter found. Install Python 3.12+ or ensure 'py'/'python' is available."
}

$ResolvedVenvPath = if ([System.IO.Path]::IsPathRooted($VenvPath)) {
    $VenvPath
} else {
    Join-Path $RepoRoot $VenvPath
}

$BootstrapPython = Resolve-PythonExecutable -RequestedVersion $PythonPreference

if (-not (Test-Path $ResolvedVenvPath)) {
    Write-Host "▶ creating venv at $ResolvedVenvPath"
    & $BootstrapPython -m venv $ResolvedVenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create venv at $ResolvedVenvPath"
    }
} else {
    Write-Host "▶ reusing venv at $ResolvedVenvPath"
}

$VenvPythonCandidates = @(
    (Join-Path $ResolvedVenvPath 'Scripts\python.exe'),
    (Join-Path $ResolvedVenvPath 'bin\python')
)
$VenvPython = $VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $VenvPython) {
    throw "Could not find the virtualenv Python executable under $ResolvedVenvPath"
}

Write-Host "▶ upgrading pip / setuptools / wheel"
& $VenvPython -m pip install --quiet --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to upgrade pip/setuptools/wheel'
}

Write-Host "▶ installing requirements.txt (runtime + test deps)"
& $VenvPython -m pip install --quiet -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install requirements.txt'
}

$verifyCode = @'
import importlib
import sys

REQUIRED = [
    "httpx",
    "databento",
    "tradingview_ta",
    "pandas",
    "pytest",
    "dotenv",
    "yfinance",
]
missing = []
for mod in REQUIRED:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        missing.append(f"  - {mod}: {type(exc).__name__}: {exc}")

if missing:
    print("❌ missing or broken modules after install:", file=sys.stderr)
    print("\n".join(missing), file=sys.stderr)
    sys.exit(1)

print("✅ all required provider modules importable")
'@

Write-Host "▶ verifying provider imports"
& $VenvPython -c $verifyCode
if ($LASTEXITCODE -ne 0) {
    throw 'Provider import verification failed'
}

Write-Host ''
Write-Host '✅ bootstrap complete'
Write-Host "    venv:     $ResolvedVenvPath"
Write-Host "    activate: $ResolvedVenvPath\Scripts\Activate.ps1"
