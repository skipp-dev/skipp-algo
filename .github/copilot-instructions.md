# GitHub Copilot Repository Instructions

## STOP-Regeln (reflexartig, keine Analyse-Phase)

| Signal | Sofort-Aktion |
|---|---|
| `mergeStateStatus == "DIRTY"` | `git fetch origin main && git rebase origin/main` → Konflikte lösen → `git push --force-with-lease` |
| `mergeStateStatus == "BEHIND"` | `git fetch origin main && git rebase origin/main && git push --force-with-lease` |
| `git push` → `[remote rejected]` | `git fetch origin <branch> && git rebase origin/<branch> && git push --force-with-lease` |
| Pre-commit Hook: falscher Branch | Checkout korrigieren → cherry-pick → neu committen |

**DIRTY ≠ CI-Fehler.** DIRTY = Merge-Konflikt. Sofort rebasen. Kein "let me check", kein Warten auf CI.

---

## Pre-Push-Checkliste (vor jedem `git push`)

```bash
# 1. Branch + Commit im selben &&-Block
git branch --show-current && git add <files> && git commit -m "..."

# 2. Stale Bytecode entfernen (verhindert Phantomfehler aus veralteten .pyc)
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 3. Ruff
.venv/bin/python -m ruff check --fix . && .venv/bin/python -m ruff check .

# 4. Alle 7 Ledger-Pins (~15s) — VOLLSTÄNDIG, nicht kürzen
.venv/bin/python -m pytest \
  tests/test_global_statement_budget.py \
  tests/test_noqa_budget.py \
  tests/test_noqa_suppression_ledger.py \
  tests/test_subprocess_shell_injection_pin.py \
  tests/test_type_ignore_budget.py \
  tests/test_path_text_io_encoding_ledger.py \
  tests/test_atomic_write_call_sites.py \
  tests/test_hmac_auth_zero_surface.py \
  -q --no-header 2>&1 | tail -5
```

Niemals pushen mit bekannten Ruff-Fehlern oder Ledger-Brüchen.

### Neue Suppressions → Ledger-Pflicht (VOR dem Push)

| Hinzugefügt | Datei updaten |
|---|---|
| `# noqa` in `scripts/` | `tests/test_noqa_suppression_ledger.py` `_FROZEN_SITES` |
| `# noqa` in anderen Dirs | `tests/test_noqa_budget.py` `_FROZEN_SITES` |
| `subprocess.run(...)` | `pin_registry.toml` `[[subprocess_shell_injection_pin.sites]]` |
| `# type: ignore` | `tests/test_type_ignore_budget.py` `_FROZEN_FILE_COUNTS` |
| `global <var>` | `tests/test_global_statement_budget.py` Ledger |

Muster: Ledger-Update + Suppression im **selben Commit**.

---

## Nach jedem `git push` — kein Idle, immer Parallelarbeit

CI läuft ~5–20min. In dieser Zeit **immer** eine dieser Aktionen:

1. Copilot-Inline-Threads für den PR lesen und fixen:
```bash
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
  | python3 -c "import sys,json; [print(f\"{c['path']}:{c.get('line')} {c['body'][:120]}\") for c in json.load(sys.stdin,strict=False) if 'opilot' in c['user']['login'].lower()]"
```
2. Andere offene PRs auf `mergeStateStatus` prüfen (s. PR-Housekeeping)
3. Nächsten Task aus dem Backlog starten

**Copilot-Review ist async** (~7–10min nach Push). Nach schnellem CI-Grün (~4min): PR nochmals auf neue Copilot-Threads prüfen, bevor "done" ausgerufen wird.

CI-Ergebnis auswerten:
- Grün + keine offenen Threads → merge (s. PR-Housekeeping)
- Rot → `gh api repos/skippALGO/skipp-algo/actions/jobs/<job-id>/logs | grep -E "FAILED|Found [0-9]+ error" | head -10` → direkt fixen

---

## PR-Housekeeping

**Pflicht-Sequenz vor jedem Merge-Versuch** — NIEMALS blind `gh pr merge` aufrufen:

```bash
gh pr view <N> --json mergeStateStatus,autoMergeRequest,reviewDecision
```

| `mergeStateStatus` | Aktion |
|---|---|
| `BEHIND` | `gh api repos/skippALGO/skipp-algo/pulls/<N>/update-branch -X PUT` → `gh pr merge <N> --squash --auto` → **weitermachen** (kein manuelles CI-Warten) |
| `DIRTY` | STOP-Regel oben (rebase) |
| `BLOCKED` | Fehlende Checks abwarten — arm `--auto` wenn noch nicht gesetzt |
| `MERGEABLE` + Checks grün | `gh pr merge <N> --squash` |

**Kontrakt:** Nach `--auto` oder `update-branch` nie idle warten. Sofort nächste Aufgabe.

**Alle PRs scannen:**
```bash
gh pr list --repo skippALGO/skipp-algo --state open \
  --json number,title,mergeable,mergeStateStatus,isDraft,headRefName \
  | python3 -c "import sys,json; [print(f\"#{p['number']} {p['title'][:50]} | {p['mergeStateStatus']} | draft={p['isDraft']}\") for p in json.load(sys.stdin)]"
```

---

## Pre-Push-Checkliste (vor jedem `git push`)

Jedes `.github/workflows/*.yml` muss mit diesem Skeleton beginnen:

```yaml
# live-window: any-trigger  # <feature-flag-id> (<YYYY-MM-DD>)
name: "<replace>"
on: <replace>
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
env:
  PYTHONUNBUFFERED: "1"
  PYTHONPATH: ${{ github.workspace }}
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
defaults:
  run:
    shell: bash
jobs:
  my-job:
    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
    timeout-minutes: 20
```

Startpunkt: `.github/workflow-templates/python-job.yml` oder `docs-lint.yml`.

**Pflichtregeln:**
- `defaults: run: shell: bash` vor `jobs:` — `fast-gates` blockt sonst.
- `permissions: contents: read` auf Workflow-Ebene; nur jobweise eskalieren.
- `timeout-minutes` auf jedem Job (Lint 5–10 min, Tests 20–45 min, Cron 20–30 min).
- Runner: `${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}` für Standard-Jobs. Routed-Workflows (GPU/Windows) nutzen `select-runner` + `fromJson(needs.select-runner.outputs.runs_on_json)`.
- Niemals `ubuntu-latest-l` oder `ubuntu-latest-m` — beide Labels retired.
- Python-Setup: `./.github/actions/setup-python-pinned` (nicht raw `actions/setup-python`).
- Bot-PRs (`bot/*`): `run_heavy=false` Gate vor allen schweren Steps.

---

## Code authoring rules

**Dependencies:** `requirements.txt` ist Source of Truth. `uv add` / `pip install` verboten. Neue Deps: `requirements.txt` editieren → `python scripts/regenerate_requirements_lock.py`.

**Atomic writes:** `mkstemp + fdopen + os.replace` für alle File-Writes in `scripts/`. Raw `open(..., 'w')` schlägt in CI an (`test_atomic_write_call_sites.py`).

**Imports:** Kein Import von `terminal_*` aus `smc_integration/`. Kein Import von `smc_integration/` aus Pine-Scripts. Check: `python scripts/check_layer_violations.py`.

**Pine:** Jede Datei beginnt mit `//@version=6`. Kein `request.security(syminfo.tickerid, timeframe.period, ...)`.

**TDD:** Test zuerst (RED) → Implementation (GREEN) → Refactor. Nie Production-Code ohne vorherigen failing Test.

**Tests:**
- Kein `time.sleep`, kein Live-API-Call, kein Network-I/O.
- Einzeldatei serial: `python -m pytest -q <file>`. Kein xdist für Einzeldateien.
- Lokaler Fast-Sweep: `python -m pytest -q --maxfail=1 -n 8 --dist=worksteal tests`
- CI-Parity: `python -m pytest -q --maxfail=1 -n auto --dist=worksteal tests`

---

## Git-Disziplin

- Branch-Prüfung immer im selben `&&`-Block wie `git commit` (nicht separat vorher).
- Kein direkter Commit auf `main`/`master` — pre-commit Hook blockiert.
- Jeder abgeschlossene Schritt = eigener Commit. >1 Datei pro Commit = Signal zum Aufteilen.
- Nach Merge: Worktree entfernen (`git worktree remove --force`) und Branch löschen.
- Env-Vars niemals umbenennen ohne explizite User-Freigabe. Vor Änderung: alle Consumer grepen.

---

## Verifikation & Debugging

- Niemals annehmen, dass Code funktioniert — immer ausführen und Output prüfen.
- Kein Fix ohne Root-Cause: Stack Trace lesen → reproduzieren → eine Hypothese → kleinstmögliche Änderung.
- "Quick fix for now", mehrere gleichzeitige Änderungen, 2+ Versuche ohne neuen Fund → zurück zu Root-Cause-Analyse.

### Code-Behauptungen immer mit Beleg

Vor jeder Aussage über Code-Verhalten, API-Nutzung, Tier-Anforderungen, Zeilennummern oder
Dateiinhalte: **erst grepen/lesen, dann behaupten.**

```bash
# Beispiel: Bevor ich sage "X wird nur in Datei Y verwendet"
grep -rn "X" --include="*.py" --include="*.pine" . | head -20
```

- Nie aus Kontext-Gedächtnis oder Gesprächszusammenfassung antworten, wenn die Aussage
  verifizierbar ist.
- Wenn ich eine Aussage nicht belegen kann: explizit sagen "ich bin unsicher, ich prüfe das"
  → dann prüfen → dann antworten.
- User-Signal **"Zeig mir den Beweis"** / **"Woher weißt du das?"** = sofort Code-Suche,
  keine weitere Erklärung ohne Fundstelle.

---

## Kommunikation & Status

git branch --show-current && git add <files> && git commit -m "..."

# 2. Stale Bytecode entfernen (verhindert Phantomfehler aus veralteten .pyc)
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 3. Ruff
.venv/bin/python -m ruff check --fix . && .venv/bin/python -m ruff check .

# 4. Alle 7 Ledger-Pins (~15s) — VOLLSTÄNDIG, nicht kürzen
.venv/bin/python -m pytest \
  tests/test_global_statement_budget.py \
  tests/test_noqa_budget.py \
  tests/test_noqa_suppression_ledger.py \
  tests/test_subprocess_shell_injection_pin.py \
  tests/test_type_ignore_budget.py \
  tests/test_path_text_io_encoding_ledger.py \
  tests/test_atomic_write_call_sites.py \
  tests/test_hmac_auth_zero_surface.py \
  -q --no-header 2>&1 | tail -5
```

Niemals pushen mit bekannten Ruff-Fehlern oder Ledger-Brüchen.

### Neue Suppressions → Ledger-Pflicht (VOR dem Push)

| Hinzugefügt | Datei updaten |
|---|---|
| `# noqa` in `scripts/` | `tests/test_noqa_suppression_ledger.py` `_FROZEN_SITES` |
| `# noqa` in anderen Dirs | `tests/test_noqa_budget.py` `_FROZEN_SITES` |
| `subprocess.run(...)` | `pin_registry.toml` `[[subprocess_shell_injection_pin.sites]]` |
| `# type: ignore` | `tests/test_type_ignore_budget.py` `_FROZEN_FILE_COUNTS` |
| `global <var>` | `tests/test_global_statement_budget.py` Ledger |

Muster: Ledger-Update + Suppression im **selben Commit**.

---

## Nach jedem `git push` — kein Idle, immer Parallelarbeit

CI läuft ~5–20min. In dieser Zeit **immer** eine dieser Aktionen:

1. Copilot-Inline-Threads für den PR lesen und fixen:
```bash
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
  | python3 -c "import sys,json; [print(f\"{c['path']}:{c.get('line')} {c['body'][:120]}\") for c in json.load(sys.stdin,strict=False) if 'opilot' in c['user']['login'].lower()]"
```
2. Andere offene PRs auf `mergeStateStatus` prüfen (s. PR-Housekeeping)
3. Nächsten Task aus dem Backlog starten

**Copilot-Review ist async** (~7–10min nach Push). Nach schnellem CI-Grün (~4min): PR nochmals auf neue Copilot-Threads prüfen, bevor "done" ausgerufen wird.

CI-Ergebnis auswerten:
- Grün + keine offenen Threads → merge (s. PR-Housekeeping)
- Rot → `gh api repos/skippALGO/skipp-algo/actions/jobs/<job-id>/logs | grep -E "FAILED|Found [0-9]+ error" | head -10` → direkt fixen

---

## PR-Housekeeping

**Pflicht-Sequenz vor jedem Merge-Versuch** — NIEMALS blind `gh pr merge` aufrufen:

```bash
gh pr view <N> --json mergeStateStatus,autoMergeRequest,reviewDecision
```

| `mergeStateStatus` | Aktion |
|---|---|
| `BEHIND` | `gh api repos/skippALGO/skipp-algo/pulls/<N>/update-branch -X PUT` → `gh pr merge <N> --squash --auto` → **weitermachen** (kein manuelles CI-Warten) |
| `DIRTY` | STOP-Regel oben (rebase) |
| `BLOCKED` | Fehlende Checks abwarten — arm `--auto` wenn noch nicht gesetzt |
| `MERGEABLE` + Checks grün | `gh pr merge <N> --squash` |

**Kontrakt:** Nach `--auto` oder `update-branch` nie idle warten. Sofort nächste Aufgabe.

**Alle PRs scannen:**
```bash
gh pr list --repo skippALGO/skipp-algo --state open \
  --json number,title,mergeable,mergeStateStatus,isDraft,headRefName \
  | python3 -c "import sys,json; [print(f\"#{p['number']} {p['title'][:50]} | {p['mergeStateStatus']} | draft={p['isDraft']}\") for p in json.load(sys.stdin)]"
```

---

## Workflow authoring rules

Jedes `.github/workflows/*.yml` muss mit diesem Skeleton beginnen:

```yaml
# live-window: any-trigger  # <feature-flag-id> (<YYYY-MM-DD>)
name: "<replace>"
on: <replace>
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
env:
  PYTHONUNBUFFERED: "1"
  PYTHONPATH: ${{ github.workspace }}
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
defaults:
  run:
    shell: bash
jobs:
  my-job:
    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
    timeout-minutes: 20
```

Startpunkt: `.github/workflow-templates/python-job.yml` oder `docs-lint.yml`.

**Pflichtregeln:**
- `defaults: run: shell: bash` vor `jobs:` — `fast-gates` blockt sonst.
- `permissions: contents: read` auf Workflow-Ebene; nur jobweise eskalieren.
- `timeout-minutes` auf jedem Job (Lint 5–10 min, Tests 20–45 min, Cron 20–30 min).
- Runner: `${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}` für Standard-Jobs. Routed-Workflows (GPU/Windows) nutzen `select-runner` + `fromJson(needs.select-runner.outputs.runs_on_json)`.
- Niemals `ubuntu-latest-l` oder `ubuntu-latest-m` — beide Labels retired.
- Python-Setup: `./.github/actions/setup-python-pinned` (nicht raw `actions/setup-python`).
- Bot-PRs (`bot/*`): `run_heavy=false` Gate vor allen schweren Steps.

---

## Code authoring rules

**Dependencies:** `requirements.txt` ist Source of Truth. `uv add` / `pip install` verboten. Neue Deps: `requirements.txt` editieren → `python scripts/regenerate_requirements_lock.py`.

**Atomic writes:** `mkstemp + fdopen + os.replace` für alle File-Writes in `scripts/`. Raw `open(..., 'w')` schlägt in CI an (`test_atomic_write_call_sites.py`).

**Imports:** Kein Import von `terminal_*` aus `smc_integration/`. Kein Import von `smc_integration/` aus Pine-Scripts. Check: `python scripts/check_layer_violations.py`.

**Pine:** Jede Datei beginnt mit `//@version=6`. Kein `request.security(syminfo.tickerid, timeframe.period, ...)`.

**TDD:** Test zuerst (RED) → Implementation (GREEN) → Refactor. Nie Production-Code ohne vorherigen failing Test.

**Tests:**
- Kein `time.sleep`, kein Live-API-Call, kein Network-I/O.
- Einzeldatei serial: `python -m pytest -q <file>`. Kein xdist für Einzeldateien.
- Lokaler Fast-Sweep: `python -m pytest -q --maxfail=1 -n 8 --dist=worksteal tests`
- CI-Parity: `python -m pytest -q --maxfail=1 -n auto --dist=worksteal tests`

---

## Git-Disziplin

- Branch-Prüfung immer im selben `&&`-Block wie `git commit` (nicht separat vorher).
- Kein direkter Commit auf `main`/`master` — pre-commit Hook blockiert.
- Jeder abgeschlossene Schritt = eigener Commit. >1 Datei pro Commit = Signal zum Aufteilen.
- Nach Merge: Worktree entfernen (`git worktree remove --force`) und Branch löschen.
- Env-Vars niemals umbenennen ohne explizite User-Freigabe. Vor Änderung: alle Consumer grepen.

---

## Verifikation & Debugging

- Niemals annehmen, dass Code funktioniert — immer ausführen und Output prüfen.
- Kein Fix ohne Root-Cause: Stack Trace lesen → reproduzieren → eine Hypothese → kleinstmögliche Änderung.
- "Quick fix for now", mehrere gleichzeitige Änderungen, 2+ Versuche ohne neuen Fund → zurück zu Root-Cause-Analyse.

### Code-Behauptungen immer mit Beleg

Vor jeder Aussage über Code-Verhalten, API-Nutzung, Tier-Anforderungen, Zeilennummern oder
Dateiinhalte: **erst grepen/lesen, dann behaupten.**

```bash
# Beispiel: Bevor ich sage "X wird nur in Datei Y verwendet"
grep -rn "X" --include="*.py" --include="*.pine" . | head -20
```

- Nie aus Kontext-Gedächtnis oder Gesprächszusammenfassung antworten, wenn die Aussage
  verifizierbar ist.
- Wenn ich eine Aussage nicht belegen kann: explizit sagen "ich bin unsicher, ich prüfe das"
  → dann prüfen → dann antworten.
- User-Signal **"Zeig mir den Beweis"** / **"Woher weißt du das?"** = sofort Code-Suche,
  keine weitere Erklärung ohne Fundstelle.

---

## Kommunikation & Status

- Immer auf Deutsch antworten (außer User schreibt Englisch). Commits/PR-Titel/Code-Kommentare bleiben Englisch.
- Nach mehrstufigem Task: 3–5 Zeilen Status (erledigt / offen / blockiert).
- JEDES entdeckte Issue erwähnen — auch pre-existing, auch out-of-scope. Kein stilles Ignorieren.
- Terminal-Output immer mit `| head -N` oder `| tail -N` (N ≤ 20) begrenzen.
- Nach langem Task: "💡 Guter Zeitpunkt für `/compact`" (eine Zeile).

---

## Runner- & CI-Policy

Variable `SMC_GH_HOSTED_RUNNER`, currently
`ubuntu-latest` (GitHub-hosted default). Routierte Workflows nutzen `select-runner`.

**GitHub Copilot Code Review / Copilot reviewer:** GitHub-managed dynamic workflow named `Copilot`.
Do **not** create or edit repository workflows to route Copilot review jobs.
The AI reviewer should execute on GitHub-managed infrastructure.

This includes `ci.yml`. CI validate is intentionally GitHub-hosted.
Routing via `--inventory-unavailable-fallback required-self-hosted` only
unless the workflow truly cannot run on GitHub-hosted infrastructure.

**Kill switch — force GitHub-hosted everywhere:** Set the repository variable
`SMC_FORCE_GH_HOSTED=1` (or pass `--force-hosted` to
`scripts/resolve_workflow_runner.py`). The `select-runner` job then resolves to
the GitHub-hosted runner unconditionally, bypassing the self-hosted inventory and
every self-hosted fallback (including `--inventory-unavailable-fallback
required-self-hosted`). Use it when the self-hosted pool is offline; unset the
variable to restore self-hosted-primary routing.

---

## Runner- & CI-Policy

Variable `SMC_GH_HOSTED_RUNNER`, currently
`ubuntu-latest` (GitHub-hosted default). Routierte Workflows nutzen `select-runner`.

**GitHub Copilot Code Review / Copilot reviewer:** GitHub-managed dynamic workflow named `Copilot`.
Do **not** create or edit repository workflows to route Copilot review jobs.
The AI reviewer should execute on GitHub-managed infrastructure.

This includes `ci.yml`. CI validate is intentionally GitHub-hosted.
Routing via `--inventory-unavailable-fallback required-self-hosted` only
unless the workflow truly cannot run on GitHub-hosted infrastructure.

---

## Session-Start

Beim ersten Turn: prüfe ob `spec/agent_handover.md` auf main existiert. Falls ja: lesen, Stand bestätigen, loslegen.
