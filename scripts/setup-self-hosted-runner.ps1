# scripts/setup-self-hosted-runner.ps1
#
# One-time / idempotent bootstrap for a Windows self-hosted GitHub Actions
# runner so that workflows authored against an Ubuntu-style PATH (bash,
# python3.12) succeed when routed to it.
#
# Requirements expected to be pre-installed (per-machine or per-user):
#   * Git for Windows  -> provides bash.exe at "C:\Program Files\Git\bin\bash.exe"
#   * Python 3.12      -> install location passed via -PythonHome (default:
#                         "C:\Users\preus\AppData\Local\Programs\Python\Python312").
#
# What this does:
#   1. Appends Git\bin and the Python 3.12 install + Scripts dirs to the MACHINE
#      PATH (idempotent — already-present entries are skipped).
#   2. Restarts each `actions.runner.skippALGO-skipp-algo.*` Windows service so
#      the LocalSystem listener picks up the new PATH.
#
# Must be run elevated (Administrator). Designed to be re-runnable.
#
# Why this exists: the `validate` job in `.github/workflows/ci.yml` assumes
# `bash` and `python3.12` are on PATH for the runner service account
# (LocalSystem). Per-user installs do not propagate to MACHINE PATH; this
# script bridges that gap.

[CmdletBinding()]
param(
    [string] $GitBin = 'C:\Program Files\Git\bin',
    [string] $PythonHome = 'C:\Users\preus\AppData\Local\Programs\Python\Python312',
    [string] $ServicePattern = 'actions.runner.skippALGO-skipp-algo.*'
)

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw 'This script must be run elevated (Administrator).'
}

$entries = @($GitBin, $PythonHome, (Join-Path $PythonHome 'Scripts'))

foreach ($e in $entries) {
    if (-not (Test-Path $e)) {
        Write-Warning "PATH entry does not exist on disk, skipping: $e"
    }
}

$current = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$parts = $current.Split(';') | Where-Object { $_ }
$added = @()
foreach ($e in $entries) {
    if ($parts -notcontains $e) {
        $parts += $e
        $added += $e
    }
}

if ($added.Count -gt 0) {
    $newPath = ($parts -join ';')
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'Machine')
    Write-Host "Appended to Machine PATH:"
    $added | ForEach-Object { Write-Host "  + $_" }
} else {
    Write-Host 'Machine PATH already contains all required entries.'
}

$services = Get-Service -Name $ServicePattern -ErrorAction SilentlyContinue
if (-not $services) {
    Write-Warning "No services matched pattern '$ServicePattern'."
    return
}

foreach ($svc in $services) {
    Write-Host "Restarting $($svc.Name)..."
    Restart-Service -Name $svc.Name -Force
}

Write-Host 'Done. Runner listeners now inherit the updated Machine PATH.'
