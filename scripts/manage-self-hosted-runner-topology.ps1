# scripts/manage-self-hosted-runner-topology.ps1
#
# Inspect and (optionally) reduce the number of actions.runner.* services
# active on this host. All four ASUS{,-2,-3,-4} runners share one physical
# laptop; running >1 in parallel can saturate the box.
#
# Default action: report only (no service state changes).
#
# Usage:
#   # Report current state
#   pwsh -File scripts/manage-self-hosted-runner-topology.ps1
#
#   # Keep only ASUS (the primary), stop the other 3 services
#   pwsh -File scripts/manage-self-hosted-runner-topology.ps1 -KeepOnly ASUS -Apply
#
#   # Keep two runners running, stop the rest
#   pwsh -File scripts/manage-self-hosted-runner-topology.ps1 -KeepOnly ASUS,ASUS-2 -Apply
#
# -Apply additionally sets the stopped services to StartupType=Manual so they
# do not auto-resurrect on reboot. -RestartAuto reverts that.

[CmdletBinding()]
param(
    [string]   $ServicePattern = 'actions.runner.skippALGO-skipp-algo.*',
    [string[]] $KeepOnly,
    [switch]   $Apply,
    [switch]   $RestartAuto
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    --  $msg" -ForegroundColor DarkGray }
function Write-Warn2($msg){ Write-Host "    !!  $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Apply -and -not $isAdmin) { throw '-Apply requires elevated (Administrator) PowerShell.' }

Write-Step 'Discovered runner services'
$svcs = Get-Service -Name $ServicePattern -ErrorAction SilentlyContinue | Sort-Object Name
if (-not $svcs) { Write-Warn2 "No services match $ServicePattern"; return }
$svcs | Format-Table Name,Status,StartType -AutoSize | Out-String | Write-Host

function Get-ShortName([string]$svcName) {
    # actions.runner.skippALGO-skipp-algo.ASUS-2  -> ASUS-2
    return ($svcName -split '\.')[-1]
}

if (-not $Apply -and -not $RestartAuto) {
    Write-Step 'Report mode (no changes). Pass -KeepOnly <name>[,<name>] -Apply to act.'
    Write-Host ''
    Write-Host 'Examples:' -ForegroundColor Cyan
    Write-Host '  pwsh -File scripts/manage-self-hosted-runner-topology.ps1 -KeepOnly ASUS -Apply' -ForegroundColor Gray
    Write-Host '  pwsh -File scripts/manage-self-hosted-runner-topology.ps1 -RestartAuto' -ForegroundColor Gray
    return
}

if ($RestartAuto) {
    Write-Step 'Re-enabling all runner services (StartupType=Automatic, Start)'
    foreach ($s in $svcs) {
        try {
            Set-Service -Name $s.Name -StartupType Automatic
            if ($s.Status -ne 'Running') { Start-Service -Name $s.Name }
            Write-Ok "$($s.Name): Automatic + Running"
        } catch { Write-Warn2 "$($s.Name): $($_.Exception.Message)" }
    }
    return
}

if (-not $KeepOnly -or $KeepOnly.Count -eq 0) {
    throw '-Apply requires -KeepOnly with at least one runner short name (e.g. ASUS).'
}

Write-Step ("Apply mode: keeping " + ($KeepOnly -join ', ') + "; stopping the rest")
foreach ($s in $svcs) {
    $short = Get-ShortName $s.Name
    if ($KeepOnly -contains $short) {
        try {
            Set-Service -Name $s.Name -StartupType Automatic
            if ($s.Status -ne 'Running') { Start-Service -Name $s.Name }
            Write-Ok "$($s.Name) [$short]: kept (Automatic + Running)"
        } catch { Write-Warn2 "$($s.Name): $($_.Exception.Message)" }
    } else {
        try {
            if ($s.Status -eq 'Running') { Stop-Service -Name $s.Name -Force }
            Set-Service -Name $s.Name -StartupType Manual
            Write-Ok "$($s.Name) [$short]: stopped + Manual"
        } catch { Write-Warn2 "$($s.Name): $($_.Exception.Message)" }
    }
}

Write-Step 'Final state'
Get-Service -Name $ServicePattern | Sort-Object Name | Format-Table Name,Status,StartType -AutoSize | Out-String | Write-Host
