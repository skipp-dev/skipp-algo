<#
.SYNOPSIS
  Skaliert die Self-Hosted GitHub-Actions-Runner auf dieser Maschine auf
  N parallele Instanzen (Standard 4) und reduziert Defender-Overhead.

.WHY
  Der Host (24C/64GB) ist bei CI mengenmaessig unterausgelastet, weil nur
  2 Runner-Services registriert sind -> max. 2 parallele Jobs, alle weiteren
  Jobs queuen seriell. Mehr Runner -> mehr Parallelitaet -> wall-clock sinkt.
  Zusaetzlich verlangsamt Defender-Realtime-Scanning das File-I/O im
  Runner-Workfolder (pip install, git checkout), obwohl die CPU idle wirkt.

.PARAMETER Token
  GitHub-Runner-Registration-Token (Repo Settings -> Actions -> Runners -> New).
  Pflicht wenn -Count > Anzahl bereits installierter Runner.

.PARAMETER Count
  Ziel-Anzahl Runner-Instanzen (inkl. existierender). Default: 4.

.PARAMETER Labels
  Komma-getrennte Labels, identisch zu existierenden ASUS-Runnern.
  Default: "self-hosted,Windows,X64,asus".

.PARAMETER Repo
  owner/repo. Default: skippALGO/skipp-algo.

.PARAMETER SkipDefender
  Ueberspringt das Setzen der Defender-Exclusions.

.EXAMPLE
  # Elevated PowerShell, Token von GH UI:
  powershell -ExecutionPolicy Bypass -File scripts\ops\add_self_hosted_runners.ps1 -Token AAAA... -Count 4
#>
[CmdletBinding()]
param(
    [string]$Token,
    [int]$Count = 4,
    # Muss zur Konvention in docs/self_hosted_runner_reservation_runbook.md
    # passen, sonst matchen die Resolver-Custom-Labels (priority-cron, gpu,
    # priority-gpu) den Runner nicht und der Runner bleibt idle.
    [string]$Labels = "self-hosted,Windows,X64,priority-cron,gpu,priority-gpu,asus",
    [string]$Repo = "skippALGO/skipp-algo",
    [switch]$SkipDefender
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Error "Bitte in einer ELEVATED PowerShell ausfuehren (Service-Install + Defender-Exclusions brauchen Admin)."
    exit 1
}

$Base       = "C:\Users\preus"
$RunnerVer  = "2.334.0"
$RunnerZip  = "actions-runner-win-x64-$RunnerVer.zip"
$RunnerUrl  = "https://github.com/actions/runner/releases/download/v$RunnerVer/$RunnerZip"
$CacheRoot  = "C:\actions-cache"

# 1) Defender-Exclusions ----------------------------------------------------
if (-not $SkipDefender) {
    Write-Host ">> Defender-Exclusions setzen..." -ForegroundColor Cyan
    $paths = @(
        "$Base\actions-runner",
        "$Base\actions-runner-2",
        "$CacheRoot"
    )
    for ($i = 3; $i -le $Count; $i++) { $paths += "$Base\actions-runner-$i" }
    $procs = @("python.exe","pythonw.exe","pip.exe","git.exe","node.exe","Runner.Worker.exe","Runner.Listener.exe")
    foreach ($p in $paths) { Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue }
    foreach ($p in $procs) { Add-MpPreference -ExclusionProcess $p -ErrorAction SilentlyContinue }
    Write-Host "   ok" -ForegroundColor Green
}

# 2) Wieviele Runner existieren? --------------------------------------------
$existing = @()
$existing += "$Base\actions-runner"
for ($i = 2; $i -le 32; $i++) {
    $p = "$Base\actions-runner-$i"
    if (Test-Path "$p\.runner") { $existing += $p }
}
Write-Host (">> Existierende Runner: " + ($existing.Count)) -ForegroundColor Cyan
if ($Count -le $existing.Count) {
    Write-Host "   Ziel ($Count) bereits erreicht. Nichts zu tun." -ForegroundColor Green
    exit 0
}

if (-not $Token) {
    Write-Error "Brauche -Token (Repo Settings -> Actions -> Runners -> New self-hosted runner)."
    exit 1
}

# 3) Runner-Zip cachen ------------------------------------------------------
$zipPath = "$Base\$RunnerZip"
if (-not (Test-Path $zipPath)) {
    Write-Host ">> Lade Runner-Zip $RunnerVer..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $RunnerUrl -OutFile $zipPath -UseBasicParsing
}

# 4) Neue Runner einrichten -------------------------------------------------
for ($i = ($existing.Count + 1); $i -le $Count; $i++) {
    $dir = "$Base\actions-runner-$i"
    $name = "ASUS-$i"
    Write-Host ">> Setup $name in $dir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $dir -Force

    # .env analog zu ASUS-2 (Caches, UTF-8, pip-leise)
    @"
PIP_CACHE_DIR=$CacheRoot\pip
PIP_DISABLE_PIP_VERSION_CHECK=1
PIP_NO_INPUT=1
PIP_PROGRESS_BAR=off
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
PYTHONUNBUFFERED=1
HF_HOME=$CacheRoot\hf
HUGGINGFACE_HUB_CACHE=$CacheRoot\hf
TRANSFORMERS_CACHE=$CacheRoot\hf
TORCH_HOME=$CacheRoot\torch
XDG_CACHE_HOME=$CacheRoot\xdg
TMP=$CacheRoot\tmp
TEMP=$CacheRoot\tmp
CUDA_MODULE_LOADING=LAZY
PYTEST_XDIST_AUTO_NUM_WORKERS=6
"@ | Set-Content -Path "$dir\.env" -Encoding ASCII

    $svcName = "actions.runner.skippALGO-skipp-algo.$name"
    Push-Location $dir
    try {
        # config.cmd installiert den Service per Default unter NetworkService und
        # versucht ihn zu starten -> Win32-Error 1068 ("Abhaengigkeitsdienst
        # konnte nicht gestartet werden"), weil NetworkService die noetigen
        # Rechte fehlen. Service ist aber bereits angelegt; wir ignorieren den
        # Start-Fehler hier und reparieren das Service-Konto danach.
        & .\config.cmd `
            --unattended `
            --url "https://github.com/$Repo" `
            --token $Token `
            --name $name `
            --labels $Labels `
            --work "_work" `
            --runasservice `
            --replace
        $cfgExit = $LASTEXITCODE
        if (-not (Get-Service $svcName -ErrorAction SilentlyContinue)) {
            throw "config.cmd failed for $name (exit $cfgExit) und Service wurde nicht angelegt"
        }
    } finally {
        Pop-Location
    }

    Write-Host ">> Setze $svcName auf LocalSystem und starte..." -ForegroundColor Cyan
    & sc.exe config $svcName obj= LocalSystem | Out-Null
    Start-Service $svcName
    Write-Host "   $name laeuft" -ForegroundColor Green
}

# 5) Status -----------------------------------------------------------------
Write-Host ">> Aktuelle Runner-Services:" -ForegroundColor Cyan
Get-Service | Where-Object { $_.Name -like 'actions.runner*' } | Format-Table Name,Status -AutoSize
Write-Host "Fertig. Pruefe GH: Repo -> Settings -> Actions -> Runners." -ForegroundColor Green
