# GitHub Copilot Repository Instructions

## Workflow authoring rules

### Mandatory boilerplate (every workflow file)

Every `.github/workflows/*.yml` must open with this skeleton — fill in the
`<replace>` placeholders:

```yaml
# live-window: any-trigger  # <feature-flag-id> (<YYYY-MM-DD>)
name: "<replace: workflow name>"

on:
  <replace: trigger>

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

Use `.github/workflow-templates/python-job.yml` or `docs-lint.yml` as a
copy-paste starting point for the two most common job shapes.

---

### Shell default (enforced by fast-gates lint)

Every workflow must have `defaults: run: shell: bash` before `jobs:`.  Most jobs
run on native GitHub-hosted Linux (`SMC_GH_HOSTED_RUNNER`, currently
`ubuntu-latest`), while a few explicitly routed workloads may run on Windows
self-hosted runners. Without this declaration, any job that does land on
Windows defaults to PowerShell (`pwsh`), which cannot parse bash syntax
(`[[ ]]`, `set -o pipefail`, heredocs, etc.). On `ubuntu-latest` the block is a
no-op.

The `fast-gates` required status check blocks any PR that adds a workflow file
missing this declaration.

### Runner contract

Use one of these patterns:

1. **Hosted/default workflows** keep the direct hosted expression:

```yaml
runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
```

This includes `ci.yml`. CI validate is intentionally GitHub-hosted; do not route
it through a self-hosted selector.

2. **GitHub Copilot Code Review / Copilot reviewer** is a GitHub-managed
  dynamic workflow named `Copilot`, not a repository-authored workflow file.
  Do **not** create or edit repository workflows to route Copilot review jobs
  to `self-hosted`, and do not document Copilot reviewer as using the local
  Windows runner. The AI reviewer should execute on GitHub-managed
  infrastructure.

3. **Routed workflows that genuinely need local Windows/GPU/cache
  characteristics** may use a hosted `select-runner` control-plane job plus a
  resolved worker runner:

```yaml
jobs:
  select-runner:
    runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}

  validate:
    needs: select-runner
    runs-on: ${{ fromJson(needs.select-runner.outputs.runs_on_json) }}
```

The selector uses `scripts/resolve_workflow_runner.py` to prefer an idle
`self-hosted/windows/x64` runner (plus optional `vars.SMC_SELF_HOSTED_LABEL`)
and falls back to the hosted runner defined by `SMC_GH_HOSTED_RUNNER`.
Do not add `--inventory-unavailable-fallback required-self-hosted` or
`--no-idle-fallback required-self-hosted` unless the workflow truly cannot run
correctly on GitHub-hosted infrastructure.

Priority cron workflows use `vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL`
(target value: `priority-cron`). GPU-backed Open-Prep feature-importance
workflows (`feature-importance-daily.yml`, `open-prep-outcome-backfill.yml`)
prefer `vars.SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` (target value:
`priority-gpu`) and install `requirements-gpu.txt` on the self-hosted
runner before forcing `OPEN_PREP_FI_BACKEND=gpu`. Keep the generated report
artifact path aligned with `open_prep.feature_importance_report.FI_REPORT_DIR`
(`artifacts/open_prep/feature_importance/`), not the raw sample directory under
`artifacts/open_prep/outcomes/feature_importance/`.

The GPU research workflows follow the same routed-runner contract:

- `ml-family-research.yml` exposes `mode=train|explainability|tune` over the
  synthetic `ml/` dataset scaffold and prefers
  `vars.SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL` whenever `prefer_gpu=true`.
  The workflow must probe the selected backend first and then surface the
  actual `resolved_devices` plus any `device_fallback_reason` values in the
  step summary / artifact contract.
- `rl-research-training.yml` trains the research-only PPO/SAC agents from
  `rl/` against the synthetic execution env and also prefers the GPU label
  when `prefer_gpu=true`.

`rl-research-training.yml` must install `requirements-rl-gpu.txt` on the
self-hosted GPU runner and only set `SKIPP_RL_DEVICE=cuda` after probing
that `torch.cuda.is_available()` is actually true. The generic
`requirements-rl.txt` torch dependency alone is not sufficient on Windows
because the PyPI wheel is CPU-only.

Their entrypoints are `scripts/run_ml_family_training.py`,
`scripts/run_ml_explainability_report.py`, `scripts/run_ml_optuna_tuning.py`,
and `scripts/run_rl_research_training.py`. Keep them synthetic/offline unless
the live dataset swap is implemented deliberately.

`SMC_GH_HOSTED_RUNNER` is the **hosted fallback** runner label (currently
`ubuntu-latest`). Repository-variable fallback is **not** availability fallback;
do not point it at `self-hosted` and assume GitHub will fail over automatically.

**Never** use `ubuntu-latest-l` or `ubuntu-latest-m` — both labels are retired.

### Permissions

Declare `permissions: contents: read` at the workflow level (least-privilege).
Only escalate individual jobs that genuinely need it:

```yaml
jobs:
  comment:
    permissions:
      pull-requests: write
```

Never rely on the implicit default (it grants broad write access to the token).

### Timeouts

Always set `timeout-minutes` on every job. Guideline by type:

| Job type | Recommended limit |
|---|---|
| Lint / docs | 5–10 min |
| Python tests (targeted) | 20–35 min |
| Full pytest suite | 45 min |
| Data export / cron batch | 20–30 min |

### Bot / data-only PR short-circuit

For required status checks, add the bot-detection gate so pure-data PRs
(e.g. `bot/run-open-prep-*`) don't burn runner minutes:

```yaml
- name: Determine if heavy steps should run
  id: gate
  run: |
    if [[ "${{ github.event_name }}" == "pull_request" && \
          "${{ github.head_ref }}" == bot/* ]]; then
      echo "run_heavy=false" >> "$GITHUB_OUTPUT"
    else
      echo "run_heavy=true" >> "$GITHUB_OUTPUT"
    fi
```

Then add `if: steps.gate.outputs.run_heavy == 'true'` to every subsequent step.

### Python setup

For hosted-only workflows, use the composite action for a consistent, pinned
Python version:

```yaml
- name: Set up Python
  uses: ./.github/actions/setup-python-pinned
```

For merge-critical routed workflows, split bootstrap by runner environment:

```yaml
- name: Set up pinned Python (GitHub-hosted)
  if: needs.select-runner.outputs.runner_environment == 'github-hosted'
  uses: ./.github/actions/setup-python-pinned

- name: Resolve Python 3.12 interpreter
  run: |
    # export SMC_PYTHON_BIN here; self-hosted Windows falls back to py -3.12
```

The routed worker must export `SMC_PYTHON_BIN` and use that interpreter to
create the venv or invoke standalone scripts. The loud failure message for a
missing self-hosted Python 3.12 interpreter is part of the contract.

Only use raw `actions/setup-python@...` inside the composite action itself.

---

## Code authoring rules

### Python environment

**Package management — `requirements.txt` is the Source of Truth.**
- Add a new runtime dependency by editing `requirements.txt`, then run
  `python scripts/regenerate_requirements_lock.py` to re-pin `requirements.lock`.
- Never use `uv add` or `pip install` directly — both bypass the lock workflow.
- Run scripts and tools with `uv run <command>` (e.g. `uv run pytest`) or
  directly via `.venv/bin/python -m <module>`.
- The `.venv` is created by `bootstrap_venv.sh`; do not create or activate a venv manually.
- For local Python work in VS Code, the repo-local `.venv` (managed by uv) is
  used by tasks, the Testing panel, and terminal commands.
- Bootstrap on Windows with
  `./scripts/bootstrap_venv.ps1 -VenvPath .venv`.
- Bootstrap on macOS/Linux with
  `SKIPP_VENV=.venv ./scripts/bootstrap_venv.sh`.
- The workspace uses `.env` from the repo root for local secrets; never commit
  real credentials.
- Optional local GPU backend for Open Prep feature-importance:
  install `requirements-gpu.txt` into `.venv` and set
  `OPEN_PREP_FI_BACKEND=gpu`. Accepted values are `auto|cpu|gpu`; use
  `OPEN_PREP_FI_GPU_DEVICE=<index>` when the runner has multiple visible GPUs.
- Optional ML research stack: install `requirements-ml.txt` and use
  `SKIPP_ML_DEVICE=auto|cpu|cuda` with the `run_ml_*` scripts. Treat `cuda`
  as a request and inspect `resolved_devices` / `device_fallback_reason`
  instead of assuming the backend really stayed on GPU.
- Optional RL research stack: install `requirements-rl.txt` and use
  `SKIPP_RL_DEVICE=auto|cpu|cuda` with `scripts/run_rl_research_training.py`.
- For CUDA-enabled RL locally or on the self-hosted runner, install
  `requirements-rl-gpu.txt` after `requirements-rl.txt` with
  `python -m pip install --force-reinstall -r requirements-rl-gpu.txt`.

### Testing

**TDD workflow (mandatory order):**
1. Write the test first — it must fail (RED).
2. Implement the feature — the test must pass (GREEN).
3. Only then refactor.
Never write production code before at least a skeleton failing test exists.

- Every new Python module must have a corresponding test file in `tests/`.
- Tests must be deterministic — no live API calls, no network I/O, no `time.sleep`.
- Mark timing-sensitive tests with `@pytest.mark.flaky(reruns=2)`.
- Focused suite / current file / VS Code Testing panel: run serial
  (`python -m pytest -q <file>`). Do not add xdist for single-file or debug
  runs.
- Debug current file with `python -m pytest -vv -s --maxfail=1 <file>`.
- Local fast sweep: `python -m pytest -q --maxfail=1 -n 8 --dist=worksteal tests`.
- CI parity (PR-like local run):
  `python -m pytest -q --maxfail=1 -n auto --dist=worksteal tests`.
- Push-like local coverage run:
  `python -m pytest -q --maxfail=1 -n auto --dist=worksteal --cov --cov-report=term-missing:skip-covered tests`.
- Prefer the matching VS Code tasks when available:
  `python: bootstrap repo .venv`, `pytest: focused current file`,
  `pytest: debug current file`, `pytest: local fast (8 workers)`,
  `pytest: CI parity (PR)`, `pytest: push-like coverage`.
- Do not reintroduce a global xdist default in `pyproject.toml`; focused runs
  are intentionally serial because the repo has many very large test files.

### Imports / layer violations

- Do not import `terminal_*` modules from `smc_integration/`.
- Do not import `smc_integration/` from Pine-adjacent scripts in `scripts/`.
- Verify locally: `python scripts/check_layer_violations.py`.

### Pine scripts

- All Pine files must begin with `//@version=6`.
- Do not add `request.security(syminfo.tickerid, timeframe.period, ...)` — this
  is a redundant no-op caught by the T-3 guard in `fast-gates`.

### Atomic file writes

Use `mkstemp + fdopen + os.replace` for all file writes in `scripts/`. Raw
`open(..., 'w')` calls are guarded by `tests/test_atomic_write_call_sites.py`
and will fail CI.

### Commit-Disziplin

- Commit früh und oft — viele kleine Commits sind besser als wenige große.
- Jeder abgeschlossene Schritt (Feature, Bugfix, Refactor) bekommt sofort
  einen eigenen Commit, auch wenn nur eine Datei betroffen ist.
- Faustregel: Mehr als eine Datei in einem Commit ist ein Signal, den Commit
  aufzuteilen.
- Jedes neue Feature auf einem eigenen Branch; erst nach Review und grünen
  Checks in `main` mergen.
- Vor jedem Commit: `uv run ruff check` und `uv run ruff format --check`.

### Pre-CI-Gate (Pflicht vor jedem `git push`)

**Bevor der Agent `git push` ausführt oder CI anstößt**, muss er
selbständig folgende Checks lokal ausführen und alle Fehler direkt fixen:

**1. Ruff-Lint + Auto-Fix:**
```bash
cd /Users/spreuss/Documents/skipp-algo
.venv/bin/python -m ruff check --fix .
.venv/bin/python -m ruff check .          # must exit 0
```
Wenn nach `--fix` noch Fehler bleiben: manuell fixen, commit, dann erst pushen.

**2. Ledger-Pin-Tests (targeted, ~10s):**
```bash
.venv/bin/python -m pytest \
  tests/test_global_statement_budget.py \
  tests/test_noqa_suppression_ledger.py \
  tests/test_path_text_io_encoding_ledger.py \
  tests/test_atomic_write_call_sites.py \
  -q --no-header 2>&1 | tail -5
```
Bei Failure: Ledger-Einträge ergänzen oder die auslösende Änderung
korrigieren — erst dann pushen.

**Niemals pushen mit bekannten Ruff-Fehlern oder Ledger-Brüchen.**
Ein CI-Run mit Ruff/Ledger-Failure ist ein Regelverstoß, der durch
30 Sekunden lokale Prüfung vermeidbar gewesen wäre.

### Verifikationsregel

Niemals davon ausgehen, dass Code funktioniert. Immer ausführen und Output
prüfen. Kein Artefakt, kein Skript, kein Workflow-Schritt gilt als erledigt,
bis er tatsächlich gelaufen ist und die Ausgabe bestätigt wurde.

### Debugging-Disziplin

**Eisernes Gesetz: Keine Fixes ohne Root-Cause-Analyse.**

Symptom-Fixes sind kein Erfolg — sie verbergen das eigentliche Problem.

**Die 4 Phasen (in dieser Reihenfolge, keine Abkürzungen):**

1. **Root Cause Investigation** — Fehlermeldungen vollständig lesen (Stack
   Trace, Zeilennummern, Fehlercodes). Fehler reproduzierbar machen. Letzte
   Änderungen prüfen (`git diff`, recent commits). Bei Multi-Komponenten-Systemen
   (CI → Build → Test → Deploy) zuerst Diagnose-Logging an jeder Komponenten-
   Grenze hinzufügen und einen Lauf sammeln — erst dann analysieren.
2. **Pattern Analysis** — Funktionierendes ähnliches Code im gleichen Repo
   suchen. Unterschiede zwischen "works" und "broken" explizit auflisten.
3. **Hypothesis & Test** — Genau eine Hypothese formulieren: *"Ich denke X
   ist die Root Cause, weil Y."* Kleinstmögliche Änderung testen — eine
   Variable auf einmal.
4. **Implementation** — Erst einen failing Test schreiben, dann den Fix, dann
   verifizieren (alle Tests grün, kein Regresssion).

**Stoppsignale — sofort zurück zu Phase 1:**
- "Quick fix for now" — nicht akzeptabel.
- Mehrere Änderungen auf einmal — verboten.
- 2+ Fix-Versuche ohne neuen Root-Cause-Fund → Architektur hinterfragen,
  nicht einen weiteren Fix stapeln.
- "Ich verstehe es nicht ganz, aber das könnte helfen" → kein Fix ohne
  Verständnis.

## Token-efficiency rules

### Terminal output size

When running commands that produce large output (CI logs, workflow runs,
grep over big files), always pipe through `| head -N` or `| tail -N`
(default N ≤ 20) to keep terminal-notification payloads small. Never dump
full `gh run view --log` output unfiltered — always combine with `grep` AND
a `head`/`tail` cap.

### Subagent delegation

Use the `Explore` subagent (or `search_subagent`) for exploratory reads:
"find all files matching X", "how does module Y work", "locate references
to Z". The subagent runs in its own context and returns only a compact
summary — its file-read tokens do not accumulate in the main session.

### Compaction reminder

After completing a multi-step task (todo list fully done, PR merged, or
major milestone reached), remind the user to run `/compact` if the
conversation has been going for a while. Keep the reminder to one short
line, e.g.: "💡 Guter Zeitpunkt für `/compact` — Session ist lang."

## Kommunikationsregeln

- Antworte IMMER auf Deutsch, es sei denn der User schreibt explizit auf
  Englisch.
- Erkläre fachliche Ergebnisse nutzerfreundlich — keine reinen
  PR-/Commit-Referenzen als Antwort. Wenn der User nach dem Stand fragt,
  liefere Klartext-Zusammenfassung, nicht nur Nummern.
- Git-Commits, PR-Titel und Code-Kommentare bleiben auf Englisch
  (Repo-Konvention).

## PR-Housekeeping

Wenn der User "merge", "mergeable machen" oder "Konflikte lösen" sagt:

1. `gh pr list --state open --json number,title,mergeable,headRefName | head -20`
2. Für jeden MERGEABLE PR: `gh pr checks <N>` — nur mergen wenn alle
   required checks grün.
3. Für CONFLICTING PRs: rebase auf main, Konflikte lösen, force-push.
4. Copilot-Review-Comments prüfen (inline + threads via API, nicht nur
   `gh pr view`).
5. Ergebnis als kompakte Tabelle ausgeben: `PR# | Status | Aktion`.

## CI-Warte-Regel (nie idle warten)

Wenn nach einem Push auf CI-Ergebnis gewartet werden muss:
**Niemals idle warten.** Stattdessen sofort:

0. **Branch-Aktualität prüfen — bevor man überhaupt auf CI wartet:**
   ```bash
   gh pr view <N> --json mergeable,mergeStateStatus \
     --jq '{mergeable, mergeStateStatus}'
   ```
   Wenn `mergeStateStatus == "BEHIND"` (GitHub-Meldung: "The head branch is
   not up to date with the base branch"): sofort rebasen und pushen.
   Ein CI-Lauf auf einem outdated Branch ist verschwendete Zeit und blockiert
   ohnehin den Merge:
   ```bash
   git fetch origin main
   git rebase origin/main
   git push --force-with-lease origin <branch>
   ```
   Erst nach dem Push des aktualisierten Branch den neuen CI-Lauf abwarten.

1. Alle offenen Review-Threads des PRs holen (inline + GraphQL, nicht nur
   `gh pr view`):
   ```bash
   gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
     | python3 -c "import sys,json; [print(f\"{c['path']}:{c.get('line')} {c['body'][:120]}\") for c in json.load(sys.stdin) if 'opilot' in c['user']['login'].lower()]"
   ```
2. Für jeden offenen Thread: sofort fixen oder als stale/won't-fix
   einordnen und auflösen.
3. Ruff/Ledger-Validierung lokal durchführen, solange CI noch läuft.
4. Erst wenn Review-Backlog leer UND CI-Ergebnis verfügbar: Ergebnis
   auswerten und ggf. nächste Fix-Runde starten.

**Begründung:** CI-Läufe dauern 3–8 Minuten. Jede Minute, die danach
für Review-Comment-Analyse benötigt wird, ist verschwendete Wartezeit.
Review-Fixes, die nach dem Push entdeckt werden, erzwingen einen
weiteren Commit + weiteren CI-Lauf. Review-Analyse parallel zu CI
eliminiert diese zweite Runde.

**Gilt immer:** nach jedem `git push`, nicht nur bei explizitem
"warte auf CI"-Hinweis vom User.

### Worktree-Cleanup

Nach dem Mergen eines PRs den zugehörigen Worktree entfernen:
```bash
git worktree remove /path/to/worktree --force
git branch -d <branch-name>   # lokal
```
Kein gemergter PR darf einen ungenutzten Worktree zurücklassen.

## Keine Idle-Zeit — Produktive Wartezeit nutzen

**Grundregel:** Der Agent wartet nie passiv. Nach jedem `git push` oder
wann immer CI läuft, wird die Wartezeit vollständig produktiv genutzt.

### Nach jedem `git push` sofort ausführen (parallel zu CI):

**1. Offene Copilot-Review-Threads holen** (inline + unresolved):
```bash
# Inline-Comments (pro Zeile):
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
  | python3 -c "import sys,json; [print(f\"{c['path']}:{c.get('line')} — {c['body'][:120]}\") for c in json.load(sys.stdin,strict=False) if 'opilot' in c['user']['login'].lower()]"

# Unresolved Threads (GraphQL):
gh api graphql -f query='query{repository(owner:"skippALGO",name:"skipp-algo"){pullRequest(number:<N>){reviewThreads(first:100){nodes{id isResolved isOutdated path line comments(first:1){nodes{author{login} body}}}}}}}' \
  | python3 -c "import sys,json; d=json.loads(sys.stdin.read(),strict=False); [print(t['id'],t['path'],t['comments']['nodes'][0]['body'][:100]) for t in d['data']['repository']['pullRequest']['reviewThreads']['nodes'] if not t['isResolved'] and not t['isOutdated']]"
```

**2. Alle offenen PRs scannen:**
```bash
gh pr list --repo skippALGO/skipp-algo --state open \
  --json number,title,mergeable,isDraft,reviewDecision,headRefName \
  | python3 -c "import sys,json; [print(f\"#{p['number']} {p['title'][:60]} | merge={p['mergeable']} | review={p['reviewDecision']}\") for p in json.load(sys.stdin)]"
```

**3. Fehlgeschlagene CI-Runs auf dem aktuellen Branch prüfen:**
```bash
gh run list --repo skippALGO/skipp-algo --branch <branch> --limit 3 \
  --json status,conclusion,headSha,name \
  | python3 -c "import sys,json; [print(f\"{r['name']}: {r['conclusion']} @ {r['headSha'][:8]}\") for r in json.load(sys.stdin)]"
```

### Priorisierung während Wartezeit:

| Priorität | Aktion |
|-----------|--------|
| 1 | Offene Copilot-Threads fixen oder als stale resolven |
| 2 | Andere offene PRs auf Conflicts/Failures prüfen |
| 3 | Lokale Ruff/Ledger-Validierung auf geänderten Dateien |
| 4 | Stale Threads resolven (bereits gefixt, nur noch auflösen) |
| 5 | Wenn alles erledigt: kurze Status-Zusammenfassung ausgeben |

### Wann CI-Ergebnis auswerten:

Erst NACH dem Review-Backlog-Durchlauf das CI-Ergebnis prüfen:
- Grün + kein offener Thread → merge (oder auto-merge bestätigen)
- Rot → `gh run view <id> --log-failed | tail -60` → direkt fixen
- Neue Copilot-Threads nach CI → Runde wiederholen

**Niemals:** "Ich warte auf CI-Ergebnis" ohne gleichzeitig Punkte 1–4
abzuarbeiten. Jede Idle-Aussage ist ein Regelverstoß.

## Env-Var-Disziplin

- NIEMALS eine bestehende Env-Var umbenennen ohne explizite User-Freigabe.
- Vor jeder Env-Var-Änderung:
  `grep -rn "ENV_VAR_NAME" --include="*.py" --include="*.yml"` um ALLE
  Consumers zu identifizieren.
- Wenn Python-Code und Workflow unterschiedliche Namen verwenden: den
  Python-Namen als kanonisch behandeln, Workflow anpassen.

## Proaktive Status-Updates

- Nach Abschluss eines mehrstufigen Tasks: automatisch eine 3–5 Zeilen
  Status-Zusammenfassung geben (was erledigt, was offen, was blockiert).
- Bei "was ist der Stand" / "nächste Schritte": Session-Memory und
  Todo-Liste prüfen, dann kompakte Tabelle ausgeben.
- Keine Filler-Texte — direkt die Fakten.

## Finding-Transparenz (keine silently ignorierten Issues)

- JEDES während der Arbeit entdeckte Issue MUSS in der
  Abschluss-Zusammenfassung erscheinen — auch wenn es:
  - nicht Teil des Auftrags/Prompts war,
  - pre-existing ist (nicht vom Agenten verursacht),
  - bewusst NICHT gefixt wurde (out of scope, fremde Session, Risiko).
- Das gilt für alle Arten von Befunden: Bugs, fehlschlagende/flaky Tests,
  Lint-Fehler, tote/nie gelaufene Workflows, stale Doku, Sicherheits- und
  Konsistenzprobleme, verdächtige Daten/Artefakte.
- Format in der Summary: eigener Abschnitt **"Weitere Befunde (nicht Teil
  des Auftrags)"** mit je Befund: Fundort (Datei/Workflow/PR), 1-Satz-
  Beschreibung, Einschätzung (pre-existing/neu, Schweregrad), und ob/warum
  nicht gefixt.
- "Nicht fixen" ist oft die richtige Entscheidung — "nicht erwähnen" nie.
  Der User entscheidet, ob ein Befund ein Follow-up bekommt, nicht der
  Agent durch Weglassen.
- Bei wiederkehrenden oder strukturellen Befunden zusätzlich einen
  Eintrag im Repo-Memory (`/memories/repo/`) anlegen.

## Session-Start

- Beim ersten Turn einer neuen Session: prüfe ob ein Handover-Dokument
  (z. B. `spec/agent_handover.md`) auf main existiert. Falls ja: lesen und
  als Arbeitskontext übernehmen, aktuellen Stand kurz bestätigen.
- Frage nicht nach — einfach lesen und loslegen.

## Exploration & Subagents

- Für Codebase-Fragen (z. B. "finde alle Consumer von X", "wo wird Y
  referenziert") bevorzugt `@Explore` Subagent verwenden statt serielle
  Terminal-Greps. Ein `@Explore`-Aufruf ersetzt 5-10 manuelle grep/find/read
  Ketten und spart Kontext.
- Für Audit-Aufgaben ("prüfe alle Workflows", "stelle sicher dass..."):
  Subagent starten statt 20+ Terminal-Befehle nacheinander auszuführen.
- `search_subagent` für schnelle Dateisuche, `runSubagent` mit
  `agentName: "Explore"` für tiefere Analyse.
