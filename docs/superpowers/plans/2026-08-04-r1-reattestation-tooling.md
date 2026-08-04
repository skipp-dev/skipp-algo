# R1-Re-Attestation-Tooling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Drift-Wächter macht R1-Pin-Rückstand als Issue sichtbar; ein Treiber-Skript baut die beiden Re-Attestation-PRs (Absicht/Messung) deterministisch — gemäß Spec `docs/superpowers/specs/2026-08-04-r1-reattestation-design.md`.

**Architecture:** Drei Bausteine auf bestehender Maschinerie: (1) `scripts/check_r1_pin_drift.py`, rein lesend, vom `workflow-freshness-monitor` täglich aufgerufen, Issue-Mechanik im Workflow-Step; (2) ein Refactor von `scripts/smc_r1_rollout_contract.py`, der `status`/`executionPerformed` aus dem registrierten Artefakt ableitet (neues Feld `executionState`) und `closedSinceRegisteredEvidence` zur Laufzeit auf das aktuell registrierte Artefakt filtert; (3) `scripts/run_r1_reattestation.py` mit `prepare` (PR1) und `measure` (PR2). TV wird ausschließlich über den vorhandenen `tv-save-consumer-source`-Dispatch beschrieben.

**Tech Stack:** Python 3.12 (Repo-.venv), stdlib + `scripts.smc_atomic_write`, GitHub Actions, `gh` CLI (nur in `measure` und im Workflow-Step).

## Global Constraints

- Arbeit in einem Sibling-Worktree off `origin/main` (skipp-pr-flow); NIE in `.claude/worktrees/` oder nested.
- Ledger-Guard IMMER `PYTEST_ADDOPTS="-n 4" ./scripts/run_ledger_drift_guard.sh` (OOM bei `-n auto` auf 16 GB) und IMMER **nach** `git add` (der subprocess-Pin liest den getrackten Baum).
- Ruff separat: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .` — der Guard deckt Ruff nicht ab.
- Niemals `--no-verify`; Push via `run_in_background` (Foreground-Timeout orphant den pre-push-Hook).
- Neue Dateien in `scripts/` treffen vier Ledger gleichzeitig; Registrierung im SELBEN Commit:
  | Auslöser | Ledger |
  |---|---|
  | `# noqa` (S603/S607) | `tests/test_noqa_suppression_ledger.py` `_FROZEN_SITES` (Datei→Anzahl) |
  | `subprocess.run` | `pin_registry.toml` `[[subprocess_shell_injection_pin.sites]]` |
  | `open(...,'a')` auf `$GITHUB_OUTPUT` | `tests/test_atomic_write_call_sites.py` `_ALLOWED_RAW_WRITE_FILES` (Präzedenz: `scripts/hold_r1_attested_sources.py`) |
  | `sys.path`-Mutation | NICHT ledgern — entfernen; Aufruf via `python -m scripts.<name>` aus dem Root |
- Workflow-Edits: `pytest tests/ -k workflow` Pflicht; neue Steps mit `tests/_workflow_step_shell.py::run_step` AUSFÜHREN (Stub loggt nur argv, ohne Exe-Namen). Actions-Expressions (`${{ }}`) gehören in `env:`, nicht in den `run:`-Block, sonst ist der Step untestbar.
- Dateien schreiben mit `from scripts.smc_atomic_write import atomic_write_text` (wie `smc_r1_rollout_contract.py:main`), NICHT mit rohem `open(...,'w')`.
- Datierte Evidenz-Artefakte werden NIE umgeschrieben, nur durch neue superseded.
- Schwelle des Wächters: `>= 3` Versionen (Operator-Entscheid 2026-08-04).
- Interpreter im Plan-Text: `PY=/Users/spreuss/Documents/skipp-algo/.venv/bin/python`.

## Verifizierte Fakten, auf denen die Tasks aufbauen (gemessen 2026-08-04)

- Pin-Zeile: `SMC_Event_Overlay.pine:25` = `import preuss_steffen/smc_micro_profiles_generated/183 as mp`; die Regex dafür existiert in `scripts/smc_r1_rollout_contract.py:108-111`.
- Manifest: `artifacts/tradingview/library_release_manifest.json` → `library.publishedVersion` (int, aktuell 183).
- Contract ist ABGELEITET: `_source()` hasht zur Laufzeit, `_event_library_pin()` parst den Pin zur Laufzeit. `SMC_Exit_Signal.pine`-Target hat KEINEN `libraryPin`.
- Konstanten in `scripts/smc_r1_rollout_contract.py`: `EXECUTION_EVIDENCE` (…`_2026-08-04.json`), `PRIOR_EXECUTION_EVIDENCE` (…`_2026-08-01.json`), `OPEN_GATES: Final = ()` (Zeile 75), `MIN_ATTESTED_SOURCES: Final = 2`.
- `tests/test_smc_r1_rollout_contract.py:44` pinnt `status == "authorized_execution_reattested"`; Zeilen 127–134 pinnen `contract.openGates == OPEN_GATES` und `OPEN_GATES == evidence.openGates − closedSince`.
- `tv-save-consumer-source.yml` triggert auf `workflow_run` (Refresh), Cron 05:17/21:17 UTC (read-only), `workflow_dispatch` mit `mapping`-Input (`JSON array of {"source","scriptName"} pairs`). Merge nach main triggert NICHT.
- `workflow-freshness-monitor.yml`: täglich 06:30 UTC, `permissions: issues: write`, nutzt plain `python`, Issue-Step-Muster „Open / update issue on stale or error" mit `hasIssuesEnabled`-Soft-Degradation.
- Aktuelles Artefakt-Schema (schemaVersion 2), Top-Level-Keys: `schemaVersion, capturedAt, scope, supersedes, supersessionNote, reattestationTrigger, authorization, sources, tradingView, rollback, replay, openGates, limitations, evidenceRuns, repoCommitSha, libraryReleaseVersion`.

---

### Task 1: Drift-Wächter `scripts/check_r1_pin_drift.py`

**Files:**
- Create: `scripts/check_r1_pin_drift.py`
- Test: `tests/test_check_r1_pin_drift.py`

**Interfaces:**
- Consumes: `scripts.smc_r1_rollout_contract.build_rollout_contract()` (targets), `artifacts/tradingview/library_release_manifest.json`.
- Produces: `compute_pin_drift(manifest_path: Path, threshold: int = 3) -> dict` mit Keys `schemaVersion:1, threshold, maxLag:int, drifted:bool, targets:list`; `main(argv) -> int`; Report nach `artifacts/ci/r1_pin_drift.json`; `$GITHUB_OUTPUT`-Keys `drifted` (`"true"|"false"`) und `max_lag`. Task 2 (Workflow) und Task 4 (`prepare`-Hinweistext) verlassen sich auf exakt diese Namen.

- [ ] **Step 1: Fehlschlagende Tests schreiben**

```python
"""Executing tests for the R1 pin-drift watcher.

Fixtures statt Live-Baum: contract targets und Manifest werden als Parameter
injiziert, damit jeder Arm (Drift, kein Drift, pin-los, leer, kaputt)
ausführbar ist. Der Live-Smoke-Test am Ende läuft gegen den echten Baum.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_r1_pin_drift import compute_pin_drift


def _manifest(tmp_path: Path, published: int) -> Path:
    p = tmp_path / "library_release_manifest.json"
    p.write_text(
        json.dumps({"manifestVersion": 2, "library": {"publishedVersion": published}}),
        encoding="utf-8",
    )
    return p


def _targets(pin: int | None) -> list[dict]:
    event: dict = {"path": "SMC_Event_Overlay.pine", "scriptName": "SMC Event Overlay"}
    if pin is not None:
        event["libraryPin"] = {
            "importPath": "preuss_steffen/smc_micro_profiles_generated",
            "version": pin,
        }
    exit_signal = {"path": "SMC_Exit_Signal.pine", "scriptName": "SMC Exit Signal"}
    return [event, exit_signal]


def test_lag_of_three_reports_drift(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 186), targets=_targets(183), threshold=3
    )
    assert report["drifted"] is True
    assert report["maxLag"] == 3


def test_lag_of_two_reports_no_drift(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 185), targets=_targets(183), threshold=3
    )
    assert report["drifted"] is False
    assert report["maxLag"] == 2


def test_pinless_target_is_listed_as_not_drift_capable(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 186), targets=_targets(183), threshold=3
    )
    exit_rows = [t for t in report["targets"] if t["path"] == "SMC_Exit_Signal.pine"]
    assert exit_rows and exit_rows[0]["driftCapable"] is False


def test_empty_target_roster_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        compute_pin_drift(_manifest(tmp_path, 186), targets=[], threshold=3)


def test_all_pinless_roster_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="drift-capable"):
        compute_pin_drift(
            _manifest(tmp_path, 186), targets=_targets(None), threshold=3
        )


def test_unreadable_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises((OSError, json.JSONDecodeError, KeyError)):
        compute_pin_drift(tmp_path / "missing.json", targets=_targets(183), threshold=3)


def test_live_tree_smoke() -> None:
    """Vacuity-Anker: gegen den echten Baum liefert der Wächter ein Verdikt."""
    report = compute_pin_drift(None, targets=None, threshold=3)
    assert report["maxLag"] >= 0
    assert any(t["driftCapable"] for t in report["targets"])
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `$PY -m pytest tests/test_check_r1_pin_drift.py -q --no-header`
Expected: FAIL / Collection-Error mit `ModuleNotFoundError: scripts.check_r1_pin_drift`

- [ ] **Step 3: Implementierung**

```python
#!/usr/bin/env python3
"""Report R1 companion pin drift against the published library version.

Since #4435 the library refresh HOLDS the R1-attested companions, so their
``smc_micro_profiles_generated`` import pin never moves automatically. The
library is the generated micro-profile data, so a growing lag is potentially
trade-relevant, not cosmetic. This watcher makes the lag visible (issue via
workflow-freshness-monitor); moving the pin stays a deliberate re-attestation
(design: docs/superpowers/specs/2026-08-04-r1-reattestation-design.md).

Read-only: reads the rollout contract and the release manifest, writes a
report under artifacts/ci/ and $GITHUB_OUTPUT. Never touches TradingView.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "tradingview" / "library_release_manifest.json"
DEFAULT_REPORT = ROOT / "artifacts" / "ci" / "r1_pin_drift.json"
# >= 3 versions behind (operator decision 2026-08-04): ~2 trading days of
# library movement. Weekend gaps do not trigger; real drift shows within days.
THRESHOLD = 3


def compute_pin_drift(
    manifest_path: Path | None,
    *,
    targets: list[dict] | None = None,
    threshold: int = THRESHOLD,
) -> dict:
    """Pure verdict. ``None`` arguments mean "read the live tree"."""
    if targets is None:
        from scripts.smc_r1_rollout_contract import build_rollout_contract

        targets = build_rollout_contract()["targets"]
    if not targets:
        raise ValueError("refusing an empty target roster — vacuous all-clear")

    manifest = json.loads(
        (manifest_path or MANIFEST).read_text(encoding="utf-8")
    )
    published = manifest["library"]["publishedVersion"]
    if not isinstance(published, int):
        raise ValueError(f"library.publishedVersion is not an int: {published!r}")

    rows: list[dict] = []
    for target in targets:
        pin = target.get("libraryPin")
        if pin is None:
            # Exit_Signal has no library import — by design, not an error.
            rows.append({"path": target["path"], "driftCapable": False})
            continue
        rows.append(
            {
                "path": target["path"],
                "driftCapable": True,
                "pinVersion": pin["version"],
                "publishedVersion": published,
                "lag": published - pin["version"],
            }
        )
    capable = [r for r in rows if r["driftCapable"]]
    if not capable:
        raise ValueError(
            "no drift-capable target left — the watcher would be vacuously "
            "green forever; if the last libraryPin was removed on purpose, "
            "remove this watcher with it"
        )
    max_lag = max(r["lag"] for r in capable)
    return {
        "schemaVersion": 1,
        "threshold": threshold,
        "maxLag": max_lag,
        "drifted": max_lag >= threshold,
        "targets": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--github-output", default=os.environ.get("GITHUB_OUTPUT")
    )
    args = parser.parse_args(argv)

    report = compute_pin_drift(None)
    atomic_write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", args.out)

    verdict = "DRIFTED" if report["drifted"] else "ok"
    print(f"r1 pin drift: {verdict} (maxLag={report['maxLag']}, threshold={report['threshold']})")
    for row in report["targets"]:
        if row["driftCapable"]:
            print(f"  {row['path']}: pin {row['pinVersion']} vs published {row['publishedVersion']}")
        else:
            print(f"  {row['path']}: no libraryPin — not drift-capable (by design)")

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"drifted={'true' if report['drifted'] else 'false'}\n")
            handle.write(f"max_lag={report['maxLag']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Tests laufen lassen**

Run: `$PY -m pytest tests/test_check_r1_pin_drift.py -q --no-header`
Expected: `7 passed`

- [ ] **Step 5: Mutationsproben (beide Richtungen beobachten, nicht behaupten)**

```bash
# a) Schwelle invertiert (>= -> <): test_lag_of_three... und test_lag_of_two... muessen rot werden
$PY - <<'EOF'
from pathlib import Path
p = Path("scripts/check_r1_pin_drift.py"); t = p.read_text()
p.write_text(t.replace('"drifted": max_lag >= threshold', '"drifted": max_lag < threshold'))
EOF
$PY -m pytest tests/test_check_r1_pin_drift.py -q --no-header | tail -2   # erwartet: 2 failed
git checkout -- scripts/check_r1_pin_drift.py
# b) Lag-Berechnung auf 0 gestellt: drift-Tests rot
$PY - <<'EOF'
from pathlib import Path
p = Path("scripts/check_r1_pin_drift.py"); t = p.read_text()
p.write_text(t.replace('"lag": published - pin["version"]', '"lag": 0'))
EOF
$PY -m pytest tests/test_check_r1_pin_drift.py -q --no-header | tail -2   # erwartet: >=1 failed
git checkout -- scripts/check_r1_pin_drift.py
$PY -m pytest tests/test_check_r1_pin_drift.py -q --no-header | tail -1   # erwartet: 7 passed
```

- [ ] **Step 6: Ledger im selben Commit registrieren**

`scripts/check_r1_pin_drift.py` enthält genau EINEN Roh-Write: das `$GITHUB_OUTPUT`-Append. Eintrag in `tests/test_atomic_write_call_sites.py` `_ALLOWED_RAW_WRITE_FILES` nach dem Muster des bestehenden Eintrags für `scripts/hold_r1_attested_sources.py` (Begründung: append-only Handshake-Datei der Actions-Runtime, kein Artefakt). KEIN `# noqa`, KEIN `subprocess`, KEIN `sys.path` — die anderen drei Ledger bleiben unberührt; falls der Guard doch anschlägt, ist das ein Implementierungsfehler, kein Ledger-Fall.

- [ ] **Step 7: Ruff + gezielte Ledger-Tests**

Run: `$PY -m ruff check scripts/check_r1_pin_drift.py tests/test_check_r1_pin_drift.py && $PY -m pytest tests/test_atomic_write_call_sites.py tests/test_noqa_suppression_ledger.py -q --no-header | tail -1`
Expected: ruff clean, Ledger-Tests `passed`

- [ ] **Step 8: Commit**

```bash
git add scripts/check_r1_pin_drift.py tests/test_check_r1_pin_drift.py tests/test_atomic_write_call_sites.py
git commit -m "feat(governance): R1 pin-drift watcher (read-only, threshold >=3)"
```

---

### Task 2: Wächter in `workflow-freshness-monitor.yml` verdrahten

**Files:**
- Modify: `.github/workflows/workflow-freshness-monitor.yml` (nach dem Step „Upload report artifact", vor „Open / update issue on stale or error")
- Test: `tests/test_workflow_freshness_monitor_workflow.py` (bestehende Datei erweitern)

**Interfaces:**
- Consumes: `python -m scripts.check_r1_pin_drift` (Task 1; Outputs `drifted`, `max_lag`), Issue-Step-Muster inkl. `hasIssuesEnabled`-Degradation aus demselben Workflow.
- Produces: Issue mit Label `r1-pin-drift`, Titel-Präfix `r1-pin-drift:`; Schließ-Kommentar bei Heilung. Task 4 verweist Operatoren auf dieses Issue.

- [ ] **Step 1: Fehlschlagende Workflow-Tests schreiben** — in `tests/test_workflow_freshness_monitor_workflow.py` anhängen; das Harness `tests/_workflow_step_shell.py` (`step_by_name`, `run_step`) wird dort bereits benutzt oder ist zu importieren wie in `tests/test_refresh_closes_superseded_bot_prs.py`:

```python
def test_r1_drift_probe_step_runs_the_watcher() -> None:
    step = step_by_name(_WORKFLOW, "R1 pin drift (library pin vs published version)")
    result = run_step(
        step,
        stubs={"python": 0},
        env={"GITHUB_OUTPUT": "/dev/null"},
    )
    assert result.returncode == 0
    assert result.called_with("-m", "scripts.check_r1_pin_drift"), (
        "the step no longer invokes the watcher module — the drift probe is dead"
    )


def test_r1_drift_issue_step_opens_when_drifted() -> None:
    step = step_by_name(_WORKFLOW, "Open / update / close R1 pin-drift issue")
    result = run_step(
        step,
        stubs={
            # gh repo view -> Issues enabled; gh issue list -> kein offenes Issue
            "gh": {"repo": "true", "issue list": "", "issue create": ""},
        },
        env={"R1_DRIFTED": "true", "R1_MAX_LAG": "3", "GH_TOKEN": "t", "GH_REPO": "o/r"},
    )
    assert result.returncode == 0
    assert result.called_with("issue", "create"), "drifted=true muss ein Issue öffnen"


def test_r1_drift_issue_step_closes_when_healed() -> None:
    step = step_by_name(_WORKFLOW, "Open / update / close R1 pin-drift issue")
    result = run_step(
        step,
        stubs={"gh": {"repo": "true", "issue list": "17", "issue close": ""}},
        env={"R1_DRIFTED": "false", "R1_MAX_LAG": "0", "GH_TOKEN": "t", "GH_REPO": "o/r"},
    )
    assert result.returncode == 0
    assert result.called_with("issue", "close"), "geheilter Drift muss das Issue schließen"
```

Hinweis an den Implementierer: Die exakte Stub-Signatur (`stubs=`-Form, Mehrfach-Antworten pro Binary) ist der vorhandenen Nutzung in `tests/test_refresh_closes_superseded_bot_prs.py` zu entnehmen und zu übernehmen — Konvention: der Stub loggt NUR argv, `called_with("issue", "create")` matcht ohne Exe-Namen. Falls das Harness pro Binary nur EINEN Exit-Code stubbt, die `gh`-Antworten als vorab angelegtes Stub-Skript bereitstellen, exakt wie dort für `gh prlist` gelöst.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `$PY -m pytest tests/test_workflow_freshness_monitor_workflow.py -q --no-header 2>&1 | tail -3`
Expected: FAIL mit `no step named 'R1 pin drift …'`

- [ ] **Step 3: Workflow-Steps einfügen** — nach „Upload report artifact":

```yaml
      # R1 companion pin vs published library version. Repo-only reads,
      # sub-second; the deliberate re-attestation stays manual by design
      # (docs/superpowers/specs/2026-08-04-r1-reattestation-design.md).
      - name: R1 pin drift (library pin vs published version)
        id: r1drift
        if: always()
        run: |
          set -euo pipefail
          python -m scripts.check_r1_pin_drift

      - name: Open / update / close R1 pin-drift issue
        if: always() && steps.r1drift.outcome == 'success'
        env:
          GH_TOKEN: ${{ secrets.GH_PAT != '' && secrets.GH_PAT || github.token }}
          GH_REPO: ${{ github.repository }}
          R1_DRIFTED: ${{ steps.r1drift.outputs.drifted }}
          R1_MAX_LAG: ${{ steps.r1drift.outputs.max_lag }}
        run: |
          set -euo pipefail
          # Same soft degradation as the freshness issue step above: disabled
          # Issues must not read as a broken monitor.
          if [ "$(gh repo view "$GH_REPO" --json hasIssuesEnabled --jq '.hasIssuesEnabled')" != "true" ]; then
            echo "::warning title=r1-pin-drift::Issues disabled on ${GH_REPO} — drifted=${R1_DRIFTED}, maxLag=${R1_MAX_LAG}. Step summary is the alert."
            exit 0
          fi
          existing=$(gh issue list --repo "$GH_REPO" --state open \
            --label r1-pin-drift --json number --jq '.[0].number' || echo "")
          if [ "${R1_DRIFTED}" = "true" ]; then
            TITLE="r1-pin-drift: companion pin ${R1_MAX_LAG} versions behind the published library"
            BODY_FILE=$(mktemp)
            {
              echo "The R1 companion library pin lags the published smc_micro_profiles_generated version by **${R1_MAX_LAG}** (threshold 3)."
              echo ""
              echo "Report: see the r1_pin_drift.json artifact of this run."
              echo ""
              echo "Moving the pin is a deliberate re-attestation — run:"
              echo ""
              echo '```bash'
              echo "python -m scripts.run_r1_reattestation prepare"
              echo '```'
              echo ""
              echo "and follow its printed next steps (PR1 -> merge -> mutating dispatch -> measure -> PR2)."
              echo "Design: docs/superpowers/specs/2026-08-04-r1-reattestation-design.md"
            } > "$BODY_FILE"
            if [ -n "$existing" ]; then
              gh issue edit "$existing" --repo "$GH_REPO" --title "$TITLE" --body-file "$BODY_FILE"
              echo "::notice title=r1-pin-drift::updated issue #$existing (maxLag=${R1_MAX_LAG})"
            else
              gh issue create --repo "$GH_REPO" --title "$TITLE" --body-file "$BODY_FILE" --label r1-pin-drift
              echo "::notice title=r1-pin-drift::opened issue (maxLag=${R1_MAX_LAG})"
            fi
          else
            if [ -n "$existing" ]; then
              gh issue close "$existing" --repo "$GH_REPO" \
                --comment "Pin drift healed: maxLag=${R1_MAX_LAG} < 3. Closed by workflow-freshness-monitor."
              echo "::notice title=r1-pin-drift::closed issue #$existing"
            fi
          fi
```

Zwei Vorbedingungen prüfen und ggf. im selben Commit erledigen: (a) das Label `r1-pin-drift` muss existieren — `tests/test_workflow_issue_labels_exist.py` erzwingt das (Label dort registrieren und per `gh label create r1-pin-drift --description "R1 companion pin lags published library" --color D93F0B` anlegen); (b) `tests/test_workflow_freshness_monitor_workflow.py` läuft in fast-gates nur bei Workflow-Diffs mit — dieser PR ändert den Workflow, die Auswahl greift.

- [ ] **Step 4: Tests laufen lassen**

Run: `$PY -m pytest tests/test_workflow_freshness_monitor_workflow.py tests/test_workflow_issue_labels_exist.py -q --no-header 2>&1 | tail -2`
Expected: alle `passed`

- [ ] **Step 5: Mutationsprobe** — den `python -m scripts.check_r1_pin_drift`-Aufruf durch `true` ersetzen → `test_r1_drift_probe_step_runs_the_watcher` rot; zurücksetzen.

- [ ] **Step 6: Voller Workflow-Testlauf**

Run: `$PY -m pytest tests/ -k workflow -q --no-header 2>&1 | tail -1`
Expected: `passed` (Stand 2026-08-04: ~2200), kein FAILED

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/workflow-freshness-monitor.yml tests/test_workflow_freshness_monitor_workflow.py tests/test_workflow_issue_labels_exist.py
git commit -m "feat(ci): freshness monitor reports R1 pin drift as an issue"
```

---

### Task 3: Contract-Refactor — Status aus dem Artefakt ableiten

**Files:**
- Modify: `scripts/smc_r1_rollout_contract.py`
- Modify: `tests/test_smc_r1_rollout_contract.py` (Zeile 44 und Umfeld)

**Interfaces:**
- Consumes: registriertes Artefakt (JSON), neues optionales Feld `executionState: "pending"|"executed"` (fehlend ⇒ `"executed"` — das 2026-08-04-Artefakt bleibt unverändert gültig).
- Produces: `build_rollout_contract()["status"]` ∈ {`authorized_execution_reattested`, `authorized_execution_pending`}, `["executionPerformed"]: bool` — abgeleitet, nicht mehr hartkodiert. `closedSinceRegisteredEvidence`-Einträge tragen `"registeredEvidence": "<relpath>"` und werden zur Laufzeit auf `EXECUTION_EVIDENCE` gefiltert. Tasks 4/5 (prepare/measure) verlassen sich darauf, dass sie NUR die zwei Pfad-Konstanten und `OPEN_GATES` anfassen müssen.

- [ ] **Step 1: Fehlschlagende Tests schreiben** — in `tests/test_smc_r1_rollout_contract.py`:

```python
def test_status_derives_from_execution_state(tmp_path, monkeypatch) -> None:
    """pending im Artefakt => pending im Contract, ohne Code-Edit."""
    import scripts.smc_r1_rollout_contract as contract_mod

    evidence = json.loads(contract_mod.EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    evidence["executionState"] = "pending"
    fake = tmp_path / contract_mod.EXECUTION_EVIDENCE.name
    fake.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(contract_mod, "EXECUTION_EVIDENCE", fake)

    built = contract_mod.build_rollout_contract()
    assert built["status"] == "authorized_execution_pending"
    assert built["executionPerformed"] is False


def test_missing_execution_state_means_executed() -> None:
    """Backward-Kompatibilität: das 2026-08-04-Artefakt hat kein Feld."""
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    built = build_rollout_contract()
    assert built["status"] == "authorized_execution_reattested"
    assert built["executionPerformed"] is True


def test_closed_since_is_scoped_to_the_registered_evidence(tmp_path, monkeypatch) -> None:
    """Einträge für superseded Evidenz fallen ohne Code-Edit heraus."""
    import scripts.smc_r1_rollout_contract as contract_mod

    evidence = json.loads(contract_mod.EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    evidence["executionState"] = "pending"
    evidence["openGates"] = ["mutating consumer save", "post-save verification"]
    fake = tmp_path / "smc_r1_live_rollout_evidence_2026-12-31.json"
    fake.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(contract_mod, "EXECUTION_EVIDENCE", fake)

    built = contract_mod.build_rollout_contract()
    assert built["closedSinceRegisteredEvidence"] == [], (
        "closures recorded against the superseded artifact must not carry over"
    )
```

- [ ] **Step 2: Fehlschlag verifizieren** — Run: `$PY -m pytest tests/test_smc_r1_rollout_contract.py -q --no-header 2>&1 | tail -3`; Expected: die drei neuen Tests FAILED (Status hartkodiert, kein Filter), Bestand grün.

- [ ] **Step 3: Refactor implementieren** — in `build_rollout_contract()`:

```python
    evidence_doc = json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    # Absent field == executed: every artifact before 2026-08-04 documents an
    # executed rollout and is never rewritten to say so.
    execution_state = evidence_doc.get("executionState", "executed")
    if execution_state not in ("pending", "executed"):
        raise RuntimeError(f"unknown executionState: {execution_state!r}")
    registered = EXECUTION_EVIDENCE.relative_to(ROOT).as_posix()
```

`"status"` / `"executionPerformed"` im Rückgabe-Dict ersetzen durch:

```python
        "status": (
            "authorized_execution_reattested"
            if execution_state == "executed"
            else "authorized_execution_pending"
        ),
        "executionPerformed": execution_state == "executed",
```

Jeden Eintrag in `closedSinceRegisteredEvidence` um `"registeredEvidence": "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-04.json"` ergänzen (das ist das Artefakt, GEGEN dessen openGates sie schließen) und die Liste filtern:

```python
        "closedSinceRegisteredEvidence": [
            entry for entry in _CLOSED_SINCE if entry["registeredEvidence"] == registered
        ],
```

(dazu die bisherige Literal-Liste in eine Modul-Konstante `_CLOSED_SINCE: Final = [...]` heben — reine Verschiebung, Inhalt unverändert plus neuer Key).
`tests/test_smc_r1_rollout_contract.py:44` (`assert actual["status"] == "authorized_execution_reattested"`) bleibt bestehen — sie gilt für den aktuellen Baum weiter und ist durch `test_missing_execution_state_means_executed` jetzt begründet statt zufällig.

- [ ] **Step 4: Tests laufen lassen** — Run: `$PY -m pytest tests/test_smc_r1_rollout_contract.py tests/test_check_r1_attested_sources.py tests/test_check_tv_unattested_sources.py tests/test_fast_gates_attested_pine_coverage.py -q --no-header 2>&1 | tail -1`; Expected: alle `passed` (die drei Nachbar-Konsumenten des Contracts mitfahren — sie lesen `targets`, das sich nicht ändert).

- [ ] **Step 5: Commit**

```bash
git add scripts/smc_r1_rollout_contract.py tests/test_smc_r1_rollout_contract.py
git commit -m "refactor(governance): contract status derives from the registered artifact"
```

---

### Task 4: Treiber `prepare` (PR1 — Absicht)

**Files:**
- Create: `scripts/run_r1_reattestation.py`
- Test: `tests/test_run_r1_reattestation_prepare.py`

**Interfaces:**
- Consumes: Manifest (`library.publishedVersion`), Pin-Regex aus `smc_r1_rollout_contract`, Konstanten-Layout aus Task 3.
- Produces: CLI `python -m scripts.run_r1_reattestation prepare [--root PATH] [--date YYYY-MM-DD]`; verändert im Baum: `SMC_Event_Overlay.pine` (Pin), neues `artifacts/governance/smc_r1_live_rollout_evidence_<date>.json` (`executionState: "pending"`), `scripts/smc_r1_rollout_contract.py` (zwei Pfad-Konstanten + `OPEN_GATES`-Tuple). `measure` (Task 5) konsumiert `PENDING_GATES` und das Artefakt-Layout.

- [ ] **Step 1: Fehlschlagende Tests schreiben** — Kernfälle; das Fixture kopiert die echten Dateien in ein `tmp_path`-Repo-Skelett (`SMC_Event_Overlay.pine`, Manifest, Contract-Datei, aktuelles Artefakt), damit `prepare` gegen einen ECHTEN Baum läuft und der Live-Baum unberührt bleibt:

```python
def _skeleton(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in (
        "SMC_Event_Overlay.pine",
        "artifacts/tradingview/library_release_manifest.json",
        "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-04.json",
        "scripts/smc_r1_rollout_contract.py",
    ):
        src = REPO_ROOT / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = root / "artifacts/tradingview/library_release_manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["library"]["publishedVersion"] = 187
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    return root


def test_prepare_bumps_the_pin_to_published(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    rc = prepare(root=root, date="2026-08-05")
    assert rc == 0
    text = (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    assert "import preuss_steffen/smc_micro_profiles_generated/187 as mp" in text
    assert "/183 as mp" not in text


def test_prepare_writes_a_pending_artifact_with_new_shas(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    prepare(root=root, date="2026-08-05")
    artifact = json.loads(
        (root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-05.json")
        .read_text(encoding="utf-8")
    )
    assert artifact["executionState"] == "pending"
    assert artifact["supersedes"].endswith("2026-08-04.json")
    event = [s for s in artifact["sources"] if s["path"] == "SMC_Event_Overlay.pine"][0]
    import hashlib
    expected = hashlib.sha256(
        (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8").encode()
    ).hexdigest()
    assert event["sha256"] == expected, "artifact must hash the BUMPED source"
    assert artifact["openGates"] == list(PENDING_GATES)


def test_prepare_updates_the_contract_constants(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    prepare(root=root, date="2026-08-05")
    text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert 'smc_r1_live_rollout_evidence_2026-08-05.json"' in text
    # der alte EXECUTION-Wert wird der neue PRIOR-Wert:
    assert text.count("2026-08-04.json") >= 1
    compile(text, "contract", "exec")  # der Edit darf die Datei nie zerbrechen


def test_prepare_is_idempotent(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    assert prepare(root=root, date="2026-08-05") == 0
    assert prepare(root=root, date="2026-08-05") != 0  # Pin schon auf Ziel -> Abbruch


def test_prepare_aborts_when_pin_already_current(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    manifest = root / "artifacts/tradingview/library_release_manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["library"]["publishedVersion"] = 183
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    assert prepare(root=root, date="2026-08-05") != 0
```

- [ ] **Step 2: Fehlschlag verifizieren** — Run: `$PY -m pytest tests/test_run_r1_reattestation_prepare.py -q --no-header 2>&1 | tail -2`; Expected: Collection-Error (Modul fehlt).

- [ ] **Step 3: Implementierung** — Gerüst mit den tragenden Teilen (der Implementierer ergänzt argparse-Verkabelung nach dem Muster von `hold_r1_attested_sources.py`):

```python
PIN_RE = re.compile(r"import preuss_steffen/smc_micro_profiles_generated/(\d+) as mp")
PENDING_GATES: Final = (
    "mutating consumer save of SMC_Event_Overlay.pine at the bumped pin",
    "post-save verification (auto-re-verify) green for the bumped pin",
)


def prepare(*, root: Path, date: str) -> int:
    event = root / "SMC_Event_Overlay.pine"
    manifest = json.loads(
        (root / "artifacts/tradingview/library_release_manifest.json").read_text(encoding="utf-8")
    )
    published = manifest["library"]["publishedVersion"]
    text = event.read_text(encoding="utf-8")
    match = PIN_RE.search(text)
    if match is None:
        print("::error::pin line not found", file=sys.stderr); return 1
    current = int(match.group(1))
    if current >= published:
        print(f"pin {current} already at/above published {published} — nothing to prepare", file=sys.stderr)
        return 1
    artifact_path = root / "artifacts" / "governance" / f"smc_r1_live_rollout_evidence_{date}.json"
    if artifact_path.exists():
        print(f"{artifact_path.name} exists — same-day rerun is an operator special case", file=sys.stderr)
        return 1

    atomic_write_text(PIN_RE.sub(f"import preuss_steffen/smc_micro_profiles_generated/{published} as mp", text), event)

    contract_path = root / "scripts" / "smc_r1_rollout_contract.py"
    contract_text = contract_path.read_text(encoding="utf-8")
    old_registered = re.search(r'"(smc_r1_live_rollout_evidence_[0-9-]+\.json)"\n\)\n', contract_text)
    # EXECUTION_EVIDENCE-Konstante: alter Dateiname -> PRIOR, neuer -> EXECUTION.
    # Die beiden Konstanten stehen als vierzeilige ROOT/"artifacts"/... Bloecke da;
    # der Edit ersetzt NUR die Dateinamen-Strings, in Reihenfolge ihres Auftretens:
    #   1. Vorkommen (EXECUTION_EVIDENCE) -> f"smc_r1_live_rollout_evidence_{date}.json"
    #   2. Vorkommen (PRIOR_EXECUTION_EVIDENCE) -> bisheriger EXECUTION-Dateiname
    # danach OPEN_GATES-Literal ersetzen:
    contract_text = re.sub(
        r"OPEN_GATES: Final = \([^)]*\)",
        "OPEN_GATES: Final = (\n    "
        + ",\n    ".join(repr(g) for g in PENDING_GATES)
        + ",\n)",
        contract_text,
        count=1,
    )
    compile(contract_text, str(contract_path), "exec")  # nie eine kaputte Datei schreiben
    atomic_write_text(contract_text, contract_path)

    artifact = {  # ehrlich: Repo gemessen, TV nicht beobachtet
        "schemaVersion": 2,
        "executionState": "pending",
        "capturedAt": _utc_now_iso(),
        "scope": (
            f"Authorization to move the SMC_Event_Overlay.pine library pin {current} -> {published}. "
            "Repository-side measurement only; TradingView is deliberately NOT observed here — "
            "the save has not happened yet. The verify cron may report source drift between "
            "this PR's merge and the dispatch; that is the expected intermediate state."
        ),
        "supersedes": _current_registered_relpath(contract_before_edit),
        "supersessionNote": "Superseded as the CURRENT attestation, not corrected.",
        "sources": [_source_entry(root, "SMC_Event_Overlay.pine"), _source_entry(root, "SMC_Exit_Signal.pine")],
        "tradingView": {"observed": False, "note": "not yet observed — see openGates"},
        "openGates": list(PENDING_GATES),
        "evidenceRuns": [],
        "repoCommitSha": _git_head(root),
        "libraryReleaseVersion": published,
    }
    atomic_write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", artifact_path)

    print("PR1 prepared. Next steps:")
    print("  1. review the diff, commit, push, open PR1, merge it")
    print("  2. dispatch the mutating save:")
    print('     gh workflow run tv-save-consumer-source.yml -f mapping=\'[{"source":"SMC_Event_Overlay.pine","scriptName":"SMC Event Overlay"}]\'')
    print("  3. after save + auto-re-verify: python -m scripts.run_r1_reattestation measure --save-run-id <id> --verify-run-id <id>")
    return 0
```

`_git_head` nutzt `subprocess.run(["git", ...])` → im selben Commit: `pin_registry.toml`-Eintrag + zwei `# noqa` (S603/S607) im noqa-Ledger registrieren (Muster: `scripts/hold_r1_attested_sources.py`).

- [ ] **Step 4: Tests laufen lassen** — Run: `$PY -m pytest tests/test_run_r1_reattestation_prepare.py -q --no-header 2>&1 | tail -1`; Expected: `5 passed`.

- [ ] **Step 5: Mutationsprobe** — im Skelett-Test den Artefakt-Write auskommentieren → `test_prepare_writes_a_pending_artifact…` rot; Pin-Sub durch No-Op ersetzen → `test_prepare_bumps_the_pin…` rot. Beides zurücksetzen, `5 passed` erneut zeigen.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_r1_reattestation.py tests/test_run_r1_reattestation_prepare.py pin_registry.toml tests/test_noqa_suppression_ledger.py
git commit -m "feat(governance): r1 re-attestation driver — prepare builds PR1"
```

---

### Task 5: Treiber `measure` (PR2 — Messung)

**Files:**
- Modify: `scripts/run_r1_reattestation.py` (Subcommand ergänzen)
- Test: `tests/test_run_r1_reattestation_measure.py`

**Interfaces:**
- Consumes: `gh api repos/<repo>/actions/runs/<id>` (Felder `status`, `conclusion`, `created_at`, `name`), Artefakt-/Konstanten-Layout aus Task 4, `PENDING_GATES`.
- Produces: `measure(root, date, save_run_id, verify_run_id) -> int`; neues Artefakt `executionState: "executed"` (grün) bzw. `"pending"` mit Fehlschlags-Befund (rot); Contract-Konstanten weitergedreht; `OPEN_GATES` → `()` nur bei grün.

- [ ] **Step 1: Fehlschlagende Tests schreiben** — `gh` wird als Funktions-Parameter injiziert (`fetch_run: Callable[[str], dict]`), kein Netz im Test:

```python
def test_green_runs_produce_an_executed_artifact(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)  # Task-4-Skelett + prepare() gelaufen
    rc = measure(
        root=root, date="2026-08-06",
        save_run_id="111", verify_run_id="222",
        fetch_run=lambda run_id: {
            "status": "completed", "conclusion": "success",
            "created_at": "2026-08-05T21:00:00Z",
            "name": "tv-save-consumer-source" if run_id == "111" else "tv-save-consumer-source",
        },
    )
    assert rc == 0
    artifact = json.loads((root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-06.json").read_text(encoding="utf-8"))
    assert artifact["executionState"] == "executed"
    assert {r["runId"] for r in artifact["evidenceRuns"]} == {"111", "222"}
    contract_text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert "OPEN_GATES: Final = ()" in contract_text
    assert '2026-08-06.json"' in contract_text


def test_red_save_still_writes_an_artifact_but_stays_pending(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)
    rc = measure(
        root=root, date="2026-08-06", save_run_id="111", verify_run_id="222",
        fetch_run=lambda run_id: {
            "status": "completed",
            "conclusion": "failure" if run_id == "111" else "success",
            "created_at": "2026-08-05T21:00:00Z", "name": "tv-save-consumer-source",
        },
    )
    assert rc != 0
    artifact = json.loads((root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-06.json").read_text(encoding="utf-8"))
    assert artifact["executionState"] == "pending"
    assert "failure" in json.dumps(artifact["evidenceRuns"])
    contract_text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert "OPEN_GATES: Final = ()" not in contract_text, "rote Messung darf keine Gates schließen"


def test_incomplete_runs_write_nothing(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)
    rc = measure(
        root=root, date="2026-08-06", save_run_id="111", verify_run_id="222",
        fetch_run=lambda run_id: {"status": "in_progress", "conclusion": None,
                                  "created_at": "2026-08-05T21:00:00Z", "name": "x"},
    )
    assert rc != 0
    assert not (root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-06.json").exists(), (
        "keine vakuöse Messung: unfertige Läufe schreiben nichts"
    )
```

- [ ] **Step 2: Fehlschlag verifizieren** — Run: `$PY -m pytest tests/test_run_r1_reattestation_measure.py -q --no-header 2>&1 | tail -2`; Expected: FAIL (`measure` existiert nicht).

- [ ] **Step 3: Implementierung** — `measure` im Treiber; Default-`fetch_run` via `gh api` (`subprocess.run(["gh", "api", f"repos/{repo}/actions/runs/{run_id}"], ...)`, Repo aus `git remote get-url origin` abgeleitet); Logik exakt entlang der drei Tests: beide Läufe `status == "completed"` sonst Abbruch VOR jedem Write; `conclusion == "success"` beider Läufe ⇒ `executionState: "executed"`, `OPEN_GATES → ()`, Konstanten weiterdrehen (Muster aus `prepare`); sonst Artefakt mit `executionState: "pending"` + `evidenceRuns` inkl. `conclusion`, Konstanten weiterdrehen (das Mess-Artefakt WIRD registriert — es misst den Fehlschlag), `OPEN_GATES` unverändert lassen, rc 1. Der zusätzliche `gh`-Aufruf erhöht die noqa-Zählung der Datei im Ledger (Datei→Anzahl anpassen) und braucht einen zweiten `pin_registry.toml`-Site-Eintrag.

- [ ] **Step 4: Tests laufen lassen** — Run: `$PY -m pytest tests/test_run_r1_reattestation_prepare.py tests/test_run_r1_reattestation_measure.py -q --no-header 2>&1 | tail -1`; Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_r1_reattestation.py tests/test_run_r1_reattestation_measure.py pin_registry.toml tests/test_noqa_suppression_ledger.py
git commit -m "feat(governance): r1 re-attestation driver — measure builds PR2"
```

---

### Task 6: Ledger-Sweep, voller Guard, PR

**Files:**
- Modify (nur falls der Guard es verlangt): Ledger-Dateien aus der Global-Constraints-Tabelle

- [ ] **Step 1: Bytecode purgen** — `find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null`
- [ ] **Step 2: ALLES stagen, DANN Guard** (der subprocess-Pin liest den getrackten Baum):

```bash
git add -A && git status --porcelain
PYTEST_ADDOPTS="-n 4" ./scripts/run_ledger_drift_guard.sh > /tmp/guard_r1tool.out 2>&1; echo "rc=$?"
grep -c FAILED /tmp/guard_r1tool.out || true
```

Expected: `rc=0`, kein FAILED. Bei Ledger-Rot: Tabelle in Global Constraints anwenden, `--amend` in den Task-Commit, der die Datei einführte, Guard erneut.
- [ ] **Step 3: Ruff komplett** — Run: `$PY -m ruff check .`; Expected: `All checks passed!`
- [ ] **Step 4: Push (Hintergrund!) + PR**

```bash
PYTEST_XDIST_AUTO_NUM_WORKERS=4 PYTEST_ADDOPTS="-n 4" git push -u origin <branch>   # via run_in_background
gh pr create --base main --title "feat(governance): R1 re-attestation tooling (watcher + driver)" \
  --body-file <aus den Commit-Messages von Task 1-5 komponiert; Spec + Plan verlinken>
```

- [ ] **Step 5: Nach Push nicht idlen** — Copilot-Threads lesen, `mergeStateStatus` der offenen PRs prüfen (skipp-pr-flow Step 7).

---

## Self-Review (gelaufen beim Schreiben)

- **Spec-Abdeckung:** Wächter→Task 1+2, Treiber prepare→Task 4, measure→Task 5, Fehlerpfade→Tests in 4/5 (Idempotenz, rote Messung, unfertige Läufe), Nicht-Ziele respektiert (kein neuer Workflow — Task 2 erweitert einen bestehenden; kein TV-Schreibpfad — Treiber druckt nur das Dispatch-Kommando). Contract-Status-Ableitung (Task 3) ist ein Spec-Delta: Das Spec sagt „prepare hängt Status um"; abgeleiteter Status ist die weniger fragile Erfüllung desselben Invariants (ein Artefakt = eine Wahrheit) und wurde deshalb als eigener Task vorgezogen.
- **Platzhalter:** Task-2-Step-1 und Task-5-Step-3 delegieren bewusst die exakte Stub-Signatur bzw. argparse-Verkabelung an benannte, existierende Vorbilder im Repo (Datei genannt) — kein „TBD", aber der Implementierer MUSS die Vorbilder lesen.
- **Typ-Konsistenz:** `compute_pin_drift(manifest_path, *, targets, threshold)` einheitlich; `PENDING_GATES` von Task 4 in Task 5 wiederverwendet; Output-Namen `drifted`/`max_lag` zwischen Task 1 und Task 2 identisch.
