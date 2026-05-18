# Self-Hosted Runner Stability Runbook

**Scope:** Windows self-hosted GitHub Actions runners
(`actions.runner.skippALGO-skipp-algo.{ASUS,ASUS-2,ASUS-3,ASUS-4}`) hosting the
`validate` job from `.github/workflows/ci.yml`.

**Pairs with:**
- [scripts/setup-self-hosted-runner.ps1](../scripts/setup-self-hosted-runner.ps1)
  (PATH bootstrap: bash, python3.12)
- [scripts/harden-self-hosted-runner.ps1](../scripts/harden-self-hosted-runner.ps1)
  (this runbook)
- [self_hosted_runner_reservation_runbook.md](self_hosted_runner_reservation_runbook.md)
  (job-routing / reservation policy)

---

## 1. Symptom

CI `validate` job fails with annotation:

> The self-hosted runner lost communication with the server. Verify the machine
> is running and has a healthy network connection. Anything in your workflow
> that terminates the runner process, starves it for CPU/Memory, or blocks its
> network access can cause this error.

In the runner's `_diag\Worker_*.log` the actual exception is always:

```
GitHub.Services.Common.VssUnauthorizedException: You are not authorized to
access https://run-actions-1-azure-eastus.actions.githubusercontent.com.
   ...
   at GitHub.Runner.Worker.JobRunner.CompleteJobAsync(...)
```

i.e. the Worker successfully runs the job steps, then gets HTTP 401 when it
tries to report job completion. Observed in PRs #2266, runs 26010619725 /
26015821360 with drops 14–96 minutes into the job.

## 2. Root-cause hypotheses (host-side)

| # | Hypothesis                                          | Why it produces 401      |
|---|-----------------------------------------------------|--------------------------|
| 1 | Modern Standby / connected standby suspends Runner  | Worker/Listener frozen, token refresh missed, control connection dies |
| 2 | NIC / USB selective-suspend power management        | TCP RST on resume, auth handshake fails |
| 3 | System-clock drift > 5 minutes                      | JWT `nbf`/`exp` validation fails server-side -> 401 |
| 4 | Idle TCP connections torn down by NAT/router        | Windows default `KeepAliveTime` = 2 h is longer than most NATs' idle window |

GitHub-side OAuth-token TTL is **not** under our control and is normally long
enough; the 401 is consistent with a *local* event invalidating the channel.

## 3. Mitigation: `scripts/harden-self-hosted-runner.ps1`

Idempotent PowerShell script that addresses all four hypotheses on the host.
**Must be run elevated.**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harden-self-hosted-runner.ps1
```

### What it changes (all reversible)

| Area              | Setting                                                                | Effect |
|-------------------|------------------------------------------------------------------------|--------|
| Power plan        | Activates "Ultimate Performance" (creates if missing)                  | No CPU throttling |
| Sleep timers      | `standby-timeout-{ac,dc}=0`, `hibernate-timeout-{ac,dc}=0`, `disk-timeout-{ac,dc}=0` | OS never sleeps |
| USB suspend       | `SCHEME_CURRENT 2a737441-...-308a3 48e6b7a6-...-e226 = 0`              | USB NICs/dongles stay powered |
| Service keepalive | `powercfg /requestsoverride SERVICE <runner> SYSTEM AWAYMODE EXECUTION` (one per runner service) | OS treats each runner as actively requesting power |
| NIC power mgmt    | `Set-NetAdapterPowerManagement -AllowComputerToTurnOffDevice Disabled` on every physical adapter | NIC stays alive on idle |
| TCP KeepAlive     | `HKLM\...\Tcpip\Parameters\KeepAliveTime=300000` (5 min), `KeepAliveInterval=1000`, `TcpMaxDataRetransmissions=5` | Idle TCP probed every 5 min instead of 2 h (effective after reboot) |
| Time sync         | Starts `W32Time` if stopped, `w32tm /resync /force`, prints status     | Clock drift < 5 min |

### Reboot semantics

- Power plan + `requestsoverride` + NIC settings + `w32tm`: **effective immediately**.
- TCP KeepAlive registry values: **effective after reboot**.

## 4. Verification

After running the script:

```powershell
# 1. Confirm power plan active
powercfg /getactivescheme    # GUID should be e9a42b02-d5df-448d-aa00-03f14749eb61

# 2. Confirm permanent service overrides
powercfg /requestsoverride
# expect one row per runner service with [SYSTEM,AWAYMODE,EXECUTION]

# 3. Confirm runner is currently holding a request when a job is running
powercfg /requests

# 4. Confirm NIC settings
Get-NetAdapter -Physical | Get-NetAdapterPowerManagement | Format-Table Name,AllowComputerToTurnOffDevice

# 5. Confirm TCP KeepAlive
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' |
    Select-Object KeepAliveTime,KeepAliveInterval,TcpMaxDataRetransmissions

# 6. Confirm clock sync
w32tm /query /status | Select-String 'Source|Last Successful|Phase Offset|Stratum'
```

## 5. Smoke test

After hardening + reboot:

1. Push a no-op commit to a branch that triggers `validate` (or rerun the last
   PR that hit the drop).
2. Watch the run: `gh run watch <id> --exit-status`.
3. On success: confirm in `_diag\Worker_*.log` of the chosen runner that there
   is no `VssUnauthorizedException` at job-completion time.
4. On recurrence: open / update an incident note linking the new run id and
   the worker log timestamp; consider rotating to a different runner host
   (the four ASUS hosts are independent so a host-specific failure is
   informative).

## 6. Reverting

Each change can be undone:

```powershell
# Power plan: switch back to Balanced
powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e

# Re-enable standby (e.g. 30 min)
powercfg /change standby-timeout-ac 30

# Drop service overrides
Get-Service actions.runner.* | ForEach-Object {
    powercfg /requestsoverride SERVICE $_.Name
}

# Re-enable NIC power mgmt
Get-NetAdapter -Physical | Get-NetAdapterPowerManagement | ForEach-Object {
    $_.AllowComputerToTurnOffDevice = 'Enabled'
    $_ | Set-NetAdapterPowerManagement
}

# Restore TCP KeepAlive defaults (delete the values; OS falls back to 2 h)
Remove-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name KeepAliveTime,KeepAliveInterval,TcpMaxDataRetransmissions -ErrorAction SilentlyContinue
```

## 7. Open questions / follow-ups

- Re-evaluate after one week of green validate runs whether the chronic drop
  is fully resolved. If a 401 reappears, capture exact `Worker_*.log` and
  `Runner_*.log` excerpts and re-open the investigation focused on
  GitHub-side token TTL.
- Consider a scheduled `gh actions cache` cleanup and runner-listener auto-
  restart (e.g. weekly) to catch any slow degradation.
- If the laptop hosts ever migrate to a desktop / VM, most of section 3 stays
  relevant; only Modern Standby is laptop-specific.
