# CONTINUE.md — SkippALGO Projekt-Guide

> **Zweck:** Schneller, evidenzbasierter Einstieg. Ergaenzt — ersetzt aber NICHT — die
> verbindlichen Arbeitsanweisungen in `.github/copilot-instructions.md` (Source of Truth)
> und `CLAUDE.md` (Pine-Library-Pflege). Bei Konflikten gilt die striktere Repo-Disziplin.

---

## 1. Projekt-Ueberblick

**SkippALGO** ist eine modulare Trading-Intelligence-Plattform. Positionierung:
**Research & Monitoring Terminal** mit Fokus auf *News Intelligence + Alerting*.
Keine personalisierten Anlageempfehlungen, standardmaessig keine Auto-Trade-Execution.

Drei Kernsysteme:
1. **Pine Script v6 Signal Engine** — non-repainting Signal-Engine mit decision-first HUD,
   Lite-Outlook- und Forecast-Panels. Dateien: `SMC_*.pine`, Libs in `SMC++/`, `pine/generated/`.
2. **Real-Time News Intelligence Dashboard** — Streamlit-Terminal mit 11 Tabs.
   Einstieg: `streamlit_terminal.py` + `terminal_*.py` + `terminal_tabs/`.
3. **Open-Prep Pipeline** — Pre-Open-Briefing mit Kandidaten-Ranking, Makro, Trade-Cards.
   Paket: `open_prep/`.

**Stack:** Python >=3.12 (Hauptsprache), Pine Script v6, TypeScript. Streamlit,
FastAPI/Uvicorn, pandas/pyarrow. Optional: XGBoost/LightGBM/SHAP/Optuna (ML), PPO/SAC +
PyTorch (RL). Provider: Databento, yfinance, tradingview-ta, Finnhub/FMP/NewsAPI.

**Architektur:** Flat-Layout mit expliziten Install-Paketen (`pyproject.toml ->
[tool.setuptools] packages`). Top-Level-Standalone-Module (`terminal_*`, `databento_*`)
werden NICHT per `pip install -e .` ausgeliefert, sondern ueber `pythonpath=["."]`
(pytest) bzw. direkte CLI-Aufrufe erreicht.

---

## 2. Getting Started

**Voraussetzungen:** Python >=3.12; Node.js+npm (nur fuer TV-Automation); Git.

**Installation (kanonisch — NICHT `pip install -e .`):**
> `pyproject.toml` deklariert nur das optionale `vol-regime`-Extra; Runtime-Deps leben
> ausschliesslich in `requirements.txt`. Ein venv via `pip install -e .` ist still
> unvollstaendig.

```bash
# macOS / Linux
SKIPP_VENV=.venv ./scripts/bootstrap_venv.sh
# Windows PowerShell
./scripts/bootstrap_venv.ps1 -VenvPath .venv
```

**Optionale Stacks:** `requirements-gpu.txt` (CuPy), `requirements-ml.txt` (XGBoost/
LightGBM/SHAP/Optuna), `requirements-rl.txt` (PPO/SAC), `requirements-rl-gpu.txt`
(CUDA-torch, nach rl.txt installieren).

**Nutzung:**
```bash
.venv/bin/streamlit run streamlit_terminal.py
OPEN_PREP_FI_BACKEND=gpu .venv/bin/python -m open_prep.feature_importance_report --lookback 30
```

**Tests:**
```bash
# Einzeldatei IMMER seriell (kein xdist; pdb greift sonst nicht)
.venv/bin/python -m pytest -q tests/test_<name>.py
# Fast-Sweep / CI-Paritaet
.venv/bin/python -m pytest -q --maxfail=1 -n 8 --dist=worksteal tests
```
Regeln: kein `time.sleep`, keine Live-APIs, kein Network-I/O. `slow`-Marker via
`conftest.py`; FAST-Inventar in `tests/_fast_inventory.py`.

---

## 3. Projektstruktur

| Pfad | Zweck |
|---|---|
| `open_prep/` | Pre-Open-Briefing (Ranking, Makro, Trade-Cards, Feature-Importance, Outcomes) |
| `smc_core/` | SMC-Kernlogik (BOS, OB, FVG, SWEEP) |
| `smc_integration/`, `smc_adapters/`, `smc_tv_bridge/` | SMC <-> TradingView |
| `terminal_tabs/`, `terminal_*.py`, `streamlit_terminal.py` | News-Dashboard (11 Tabs) |
| `databento_*.py` | Databento-Provider |
| `ml/`, `rl/` | Family-Model- bzw. Execution-Agent-Research |
| `dashboard/`, `governance/`, `newsstack_fmp/` | Dashboard, Governance, FMP-News |
| `scripts/` | ~800 CLI-/Ops-Skripte |
| `tests/` | ~1647 Testdateien inkl. Guard-/Ledger-Tests |
| `SMC++/`, `pine/generated/` | Hand-authorierte bzw. generierte Pine-Libs |
| `spec/`, `docs/` | JSON-Schemas, Sprint-Templates, `GLOSSARY.md` |
| `.github/workflows/` | 68 Workflows |

**Konfig:** `requirements.txt` (Source of Truth), `pyproject.toml` (Pakete/pytest/Ruff,
line-length 120), `pin_registry.toml` (Subprocess-Pins), `conftest.py`, `uv.lock` /
`requirements*.lock`, `.pre-commit-config.yaml`.

---

## 4. Development Workflow

> Verbindlich: `.github/copilot-instructions.md`.

**Coding-Standards:**
- Ruff (py312, line-length 120): `.venv/bin/python -m ruff check --fix . && ... ruff check .`
- Atomic writes in `scripts/`: `mkstemp + fdopen + os.replace` (raw `open(...,'w')`
  scheitert in CI).
- Layer: kein `terminal_*`-Import aus `smc_integration/`; kein `smc_integration/`-Import
  aus Pine. Check: `python scripts/check_layer_violations.py`.
- Pine: jede Datei beginnt mit `//@version=6`; kein `request.security(syminfo.tickerid,
  timeframe.period, ...)`.
- Deps: `requirements.txt` editieren -> `python scripts/regenerate_requirements_lock.py`.

**TDD & Guards:** Test zuerst (RED) -> Impl (GREEN) -> Refactor. Neue Suppressions
erfordern Ledger-Update im selben Commit:
- `# noqa` in `scripts/` -> `tests/test_noqa_suppression_ledger.py`
- `# noqa` sonst -> `tests/test_noqa_budget.py`
- `subprocess.run(...)` -> `pin_registry.toml`
- `# type: ignore` -> `tests/test_type_ignore_budget.py`
- `global <var>` -> `tests/test_global_statement_budget.py`

**Branch/PR:** kein Commit auf `main` (pre-commit blockt). Branch-Pruefung im selben
`&&`-Block wie `git commit`/`push`. `mergeStateStatus==DIRTY` -> rebase; `==BEHIND` ->
update-branch/rebase. DIRTY != CI-Fehler. Schreibarbeit in Worktree unter
`../skipp-algo.worktrees/<topic>`.

**Build/Deploy:** Docker (`Dockerfile`, `Dockerfile.dashboard`, `docker-compose.yml`).
CI: `ci.yml` (validate), `smc-fast-pr-gates.yml` (Merge-Gate), Pine-Publishing via
`smc-library-refresh.yml` / `smc-overlay-library-publish.yml`.

---

## 5. Key Concepts

- **SMC:** `BOS`, `OB` (Order Block), `FVG` (Fair Value Gap), `SWEEP` -> `docs/GLOSSARY.md`.
- **Phasen:** `paper` / `live_small` / `live_full`. **Sprint-Codes:** `C13`, `C14`.
- **Ledger-/Guard-Pattern:** gefrorene Site-Listen pinnen riskante Muster (Suppressions,
  Subprocess, `global`, `type: ignore`) und machen Aenderungen reviewbar.
- **Device-Aufloesung:** `SKIPP_ML_DEVICE`/`SKIPP_RL_DEVICE`/`OPEN_PREP_FI_BACKEND` =
  angefordert; Ergebnis in `resolved_devices`/`device_fallback_reason` pruefen.
- **Pine-SSOT:** Repo ist Source of Truth; Richtung repo -> TradingView. Kein TV->repo-Sync.

---

## 6. Common Tasks

- **Neue Dep:** `requirements.txt` -> `regenerate_requirements_lock.py` -> Dep-Budget-Tests.
- **Workflow aendern:** Skeleton einhalten (`permissions: contents: read`,
  `defaults: run: shell: bash` vor `jobs:`, `timeout-minutes` pro Job, Runner
  `vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest'`; niemals `-l`/`-m`). Guard:
  `tests/test_ci_workflow_structural_pin.py`.
- **Riskantes Muster:** passenden Guard/Ledger im selben Commit aktualisieren.
- **Pine publizieren:** `SMC++/` via `scripts/tv_publish_*_library.ts`; generiert via
  `smc-library-refresh.yml` / `smc-overlay-library-publish.yml`.

---

## 7. Troubleshooting

| Symptom | Ursache | Loesung |
|---|---|---|
| `ModuleNotFoundError` nach `pip install -e .` | venv ohne `requirements.txt` | Bootstrap-Skript nutzen |
| `rootdir: .../Documents` bei pytest | falscher cwd | aus Repo-Root ausfuehren |
| pdb greift nicht | xdist-Worker | Einzeldatei seriell (ohne `-n`) |
| CI fail bei `open(...,'w')` | kein atomic write | `mkstemp + os.replace` |
| Push rejected / BEHIND / DIRTY | stale/Konflikt | STOP-Regeln in copilot-instructions |
| "cuda nicht genutzt" | Anforderung != Aufloesung | `resolved_devices` pruefen |
| Phantom-Fehler | stale Bytecode | `find . -type d -name __pycache__ -exec rm -rf {} +` |

Kein Fix ohne Root-Cause. Code-Behauptungen erst per grep/read belegen, dann behaupten.

---

## 8. References

- Arbeitsanweisungen (verbindlich): `.github/copilot-instructions.md`
- Pine-Pflege: `CLAUDE.md`, `pine/PINE_LIBRARIES_AUDIT.md`
- Glossar: `docs/GLOSSARY.md`; Backtesting: `BACKTEST_QUICK_START.md`
- Schemas/Sprints: `spec/` (JSON-Schemas, `sprint_template.md`, `sprints/`)
- Workflow-Template: `.github/workflow-templates/python-job.yml`

> Hinweis: Guard-/Ledger-Testnamen und Workflow-Regeln stammen aus
> `.github/copilot-instructions.md` (dort Source of Truth).
