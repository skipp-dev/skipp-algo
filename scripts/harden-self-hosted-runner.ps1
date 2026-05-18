# scripts/harden-self-hosted-runner.ps1
#
# Idempotent stability hardening for Windows self-hosted GitHub Actions
# runners. Targets the recurring "self-hosted runner lost communication
# with the server" failure mode (VssUnauthorizedException raised by the
# Worker during CompleteJobAsync), whose plausible causes on a laptop host
# are:
#
#   1. Modern Standby / connected-standby suspending the Runner.Listener or
#      Runner.Worker process mid-job.
#   2. NIC / USB power-management putting the network interface to sleep.
#   3. System-clock drift > 5 minutes -> JWT validation 401.
#   4. Idle TCP connections being torn down by NAT / router before the
#      default 2-hour Windows KeepAliveTime kicks in.
#
# What this script does (all idempotent, safe to re-run):
#   * Activates the "Ultimate Performance" power plan (creates it if missing)
#     and disables standby/hibernate/disk/USB-selective-suspend on AC and DC.
#   * Registers a powercfg /requestsoverride for each runner service so the
#     OS treats it as actively requesting SYSTEM + AWAYMODE + EXECUTION.
#   * Disables "Allow the computer to turn off this device to save power"
#     on every physical (non-virtual) network adapter.
#   * Lowers TCP KeepAliveTime to 5 min and KeepAliveInterval to 1 s in the
#     registry (effective after reboot; logged either way).
#   * Forces a w32tm resync and reports clock offset.
#   * Registers Windows Defender exclusions for the runner _work directories,
#     the uv / pip caches, the Python install, and the python.exe / pytest.exe
#     / uv.exe processes. Real-time scanning of pytest's many small tmp files
#     is consistently the dominant Windows-side cost in the validate suite.
#
# Must be run elevated. Designed to pair with setup-self-hosted-runner.ps1.

[CmdletBinding()]
param(
    [string] $ServicePattern = 'actions.runner.skippALGO-skipp-algo.*',
    [string[]] $RunnerWorkRoots = @(
        'C:\Users\preus\actions-runner-1\_work',
        'C:\Users\preus\actions-runner-2\_work',
        'C:\Users\preus\actions-runner-3\_work',
        'C:\Users\preus\actions-runner-4\_work'
    ),
    [string[]] $ExtraDefenderPaths = @(
        'C:\Users\preus\AppData\Local\uv',
        'C:\Users\preus\AppData\Local\Programs\Python\Python312',
        'C:\Users\preus\AppData\Local\pip\Cache'
    ),
    [string[]] $DefenderProcessExclusions = @('python.exe','pytest.exe','uv.exe','git.exe','bash.exe')
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    --  $msg" -ForegroundColor DarkGray }
function Write-Warn2($msg){ Write-Host "    !!  $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'This script must be run elevated (Administrator).' }

# ---------------------------------------------------------------- 1) Power plan
Write-Step 'Activating Ultimate Performance power plan'
$ultimateGuid = 'e9a42b02-d5df-448d-aa00-03f14749eb61'
$plans = powercfg /list
if ($plans -notmatch $ultimateGuid) {
    powercfg -duplicatescheme $ultimateGuid | Out-Null
    Write-Ok 'Ultimate Performance plan created'
} else {
    Write-Skip 'Ultimate Performance plan already present'
}
powercfg /setactive $ultimateGuid
Write-Ok 'Ultimate Performance plan active'

Write-Step 'Disabling standby / hibernate / disk-sleep / USB selective suspend'
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change hibernate-timeout-ac 0
powercfg /change hibernate-timeout-dc 0
powercfg /change disk-timeout-ac 0
powercfg /change disk-timeout-dc 0
# USB selective suspend (subgroup 2a737441-1930-4402-8d77-b2bebba308a3, setting 48e6b7a6-50f5-4782-a5d4-53bb8f07e226)
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setdcvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setactive SCHEME_CURRENT
Write-Ok 'Sleep/hibernate/disk/USB-suspend disabled'

# ------------------------------------------------------- 2) Service keep-active
Write-Step "Registering powercfg requestsoverride for $ServicePattern"
$services = Get-Service -Name $ServicePattern -ErrorAction SilentlyContinue
if (-not $services) {
    Write-Warn2 "No services match $ServicePattern"
} else {
    foreach ($svc in $services) {
        # SERVICE overrides take the *service name* (Get-Service .Name), not display name.
        & powercfg /requestsoverride SERVICE $svc.Name SYSTEM AWAYMODE EXECUTION | Out-Null
        Write-Ok "requestsoverride set for $($svc.Name)"
    }
}
Write-Step 'Current powercfg /requestsoverride table'
powercfg /requestsoverride

# ----------------------------------------------------- 3) NIC power management
Write-Step 'Disabling NIC power management on physical adapters'
$adapters = Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne 'Disabled' -and $_.Virtual -eq $false }
if (-not $adapters) { Write-Warn2 'No physical adapters found' }
foreach ($a in $adapters) {
    try {
        $pm = Get-NetAdapterPowerManagement -Name $a.Name -ErrorAction Stop
        $changed = $false
        if ($pm.AllowComputerToTurnOffDevice -ne 'Disabled') {
            $pm.AllowComputerToTurnOffDevice = 'Disabled'
            $changed = $true
        }
        if ($changed) {
            $pm | Set-NetAdapterPowerManagement -ErrorAction Stop
            Write-Ok "$($a.Name): AllowComputerToTurnOffDevice disabled"
        } else {
            Write-Skip "$($a.Name): already disabled"
        }
    } catch {
        Write-Warn2 "$($a.Name): $($_.Exception.Message)"
    }
}

# ------------------------------------------------------------- 4) TCP KeepAlive
Write-Step 'Setting TCP KeepAliveTime=300000ms and KeepAliveInterval=1000ms'
$tcpKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters'
New-ItemProperty -Path $tcpKey -Name 'KeepAliveTime' -Value 300000 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $tcpKey -Name 'KeepAliveInterval' -Value 1000 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $tcpKey -Name 'TcpMaxDataRetransmissions' -Value 5 -PropertyType DWord -Force | Out-Null
Write-Ok 'TCP KeepAlive registry values set (effective after reboot)'

# ---------------------------------------------------------------- 5) Time sync
Write-Step 'Forcing time resync (w32tm)'
$w32 = Get-Service W32Time -ErrorAction SilentlyContinue
if ($w32 -and $w32.Status -ne 'Running') {
    Start-Service W32Time
    Write-Ok 'W32Time service started'
}
try {
    w32tm /resync /force | Out-Null
    Write-Ok 'w32tm resync issued'
} catch { Write-Warn2 "w32tm resync failed: $($_.Exception.Message)" }
w32tm /query /status | Select-String -Pattern 'Source|Last Successful|Phase Offset|Stratum'

# ----------------------------------------------- 6) Defender perf exclusions
Write-Step 'Registering Windows Defender exclusions for runner workloads'
$defenderAvailable = $false
try {
    $null = Get-Command Add-MpPreference -ErrorAction Stop
    $defenderAvailable = $true
} catch {
    Write-Warn2 'Defender cmdlets (Add-MpPreference) not available; skipping exclusions.'
}
if ($defenderAvailable) {
    $pathExclusions = @()
    foreach ($p in $RunnerWorkRoots + $ExtraDefenderPaths) {
        if (Test-Path $p) { $pathExclusions += $p } else { Write-Skip "path not present, skipping: $p" }
    }
    foreach ($p in $pathExclusions) {
        try {
            Add-MpPreference -ExclusionPath $p -ErrorAction Stop
            Write-Ok "ExclusionPath  : $p"
        } catch { Write-Warn2 "ExclusionPath  : $p -> $($_.Exception.Message)" }
    }
    foreach ($proc in $DefenderProcessExclusions) {
        try {
            Add-MpPreference -ExclusionProcess $proc -ErrorAction Stop
            Write-Ok "ExclusionProc  : $proc"
        } catch { Write-Warn2 "ExclusionProc  : $proc -> $($_.Exception.Message)" }
    }
    Write-Step 'Effective Defender exclusion sets'
    $prefs = Get-MpPreference
    'Paths    : ' + (($prefs.ExclusionPath    | Sort-Object -Unique) -join ', ')
    'Processes: ' + (($prefs.ExclusionProcess | Sort-Object -Unique) -join ', ')
}

Write-Host ''
Write-Host 'Hardening complete. TCP-KeepAlive changes require a reboot to take effect.' -ForegroundColor Cyan
Write-Host 'Verify with: powercfg /requestsoverride ; powercfg /requests ; Get-MpPreference | Select ExclusionPath,ExclusionProcess' -ForegroundColor Cyan
