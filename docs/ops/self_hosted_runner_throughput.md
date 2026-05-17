# Self-Hosted-Runner Durchsatz auf ASUS-Host

## Symptom
Self-hosted CI fuehlt sich langsam an, obwohl `Get-Counter` zeigt:
- CPU < 30 % ueber alle 24 logischen Kerne
- > 40 GB RAM frei
- Disk-Queue niedrig

## Ursache
1. **Nur 2 Runner-Services** (`actions.runner.skippALGO-skipp-algo.ASUS`,
   `.ASUS-2`) sind auf der Maschine registriert. Ein Runner-Service kann
   pro Zeitpunkt **genau einen** Job ausfuehren. Sobald > 2 Jobs scheduled
   werden (z. B. `select-runner` + `validate` mehrerer Workflows
   parallel), serialisiert GitHub Actions die uebrigen -> wall-clock
   waechst, CPU bleibt idle.
2. **Defender-Realtime-Scanning** des Runner-Workfolders fuegt pro
   File-Open Latenz hinzu. Das schlaegt vor allem bei `pip install`,
   `git checkout` und `pytest`-Collection durch (tausende kleine Files).
   CPU% wirkt niedrig, weil die Threads auf I/O warten, nicht rechnen.

## Fix
1. **Mehr Runner-Instanzen** (Faustregel: 1 Runner pro 4-6 logische Kerne
   bei ML/Pytest-Workloads -> 4 Runner auf 24 Kernen).
2. **Defender-Exclusions** fuer Runner-Workfolders, Caches und
   `python.exe`/`git.exe`/`Runner.Worker.exe`.

Beides erledigt das Skript:

```powershell
# 1. Token holen: https://github.com/skippALGO/skipp-algo/settings/actions/runners/new
# 2. ELEVATED PowerShell oeffnen (Service-Install braucht Admin)
cd C:\Users\preus\skipp-algo\skipp-algo
powershell -ExecutionPolicy Bypass -File scripts\ops\add_self_hosted_runners.ps1 -Token <REG_TOKEN> -Count 4
```

Das Skript ist idempotent: existierende Runner werden nicht angefasst,
nur fehlende (`actions-runner-3`, `actions-runner-4`, ...) werden mit
identischen Labels wie ASUS-2 registriert und als Windows-Service
installiert.

## Verifikation
Nach dem Setup:
```powershell
Get-Service | Where-Object { $_.Name -like 'actions.runner*' } | Format-Table Name,Status
# Erwartet: 4 Eintraege, alle Running
```

Im naechsten CI-Lauf sollte ein Workflow mit 4+ Jobs sichtbar bis zu
4 Jobs parallel auf dem Host fahren (vorher max. 2).

## Wann mehr als 4?
- Reine I/O-/Subprocess-Workloads (linting, Pine-checks): bis 8 sinnvoll.
- ML-Training / `pytest -n auto`: nicht ueber 4, weil jeder Job intern
  bereits alle Kerne nutzt -> sonst Thread-Thrashing.

## Worker-Cap fuer pytest-xdist

Default `pytest -n auto` = `os.cpu_count()` = 24 Worker pro Job.
Bei 4 parallelen Jobs sind das 96 Worker auf 24 logischen Kernen ->
Context-Switching kostet mehr als es bringt.

Loesung: jede Runner-`.env` setzt
```
PYTEST_XDIST_AUTO_NUM_WORKERS=6
```
Damit nimmt jeder `pytest -n auto` nur 6 Worker. Rechnung:
- 4 Runner x 6 Worker = 24  -> volle Auslastung, keine Ueberbuchung
- 6 Runner x 4 Worker = 24  -> noch mehr Workflow-Parallelitaet bei Queue

Das Setup-Skript schreibt den Cap automatisch in jede neue Runner-`.env`.
Bestandsrunner muessen einmal neu gestartet werden, damit die `.env`
eingelesen wird:
```powershell
# elevated
Get-Service | Where-Object { $_.Name -like 'actions.runner*' } | Restart-Service
```
