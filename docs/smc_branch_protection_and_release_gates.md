# SMC Branch Protection and Release Gates

This document defines the recommended governance setup for the SMC gate workflows.
It does not change SMC domain logic, heuristics, or workflow architecture.

## 1) Ziel

Die SMC-Gates sollen in der Praxis verbindlich genutzt werden, damit:

- Merges nach `main` nur mit schnellen, stabilen Mindest-Pruefungen erfolgen.
- tiefere Integrationssignale sichtbar bleiben, ohne PR-Flow unnoetig zu blockieren.
- Releases und TradingView-Publishes nur mit strikten, release-spezifischen Gates erfolgen.

## 2) Empfohlene Branch Protection fuer `main`

Empfehlung in GitHub Branch Protection (Settings > Branches > Branch protection rules):

- Require a pull request before merging: `enabled`
- Require status checks to pass before merging: `enabled`
- Required status checks (minimal blocking baseline):
  - `smc-fast-pr-gates / fast-gates`
- Optional zusaetzlich als required (falls Legacy-CI weiter merge-blocking bleiben soll):
  - `CI / validate`
- Require conversation resolution before merging: `enabled` (empfohlen)
- Require linear history: `enabled` (empfohlen)
- Allow squash merge: `enabled` (empfohlen)
- Allow merge commits: `disabled` (empfohlen)
- Allow rebase merge: `optional` nach Team-Praeferenz
- Allow force pushes: `disabled` (empfohlen)
- Allow deletions: `disabled` (empfohlen)

Hinweis: Diese Einstellungen sind Empfehlungen. Sie werden hier dokumentiert, aber nicht automatisch per Repo gesetzt.

## 3) Gate-Kategorien und konkrete Checks

### A) Merge-blocking fuer `main`

- Workflow: `smc-fast-pr-gates`
- Job/Check: `fast-gates`
- Sichtbarer Check-Name in Branch Protection: `smc-fast-pr-gates / fast-gates`

Optional zusaetzlich:

- Workflow: `CI`
- Job/Check: `validate`
- Sichtbarer Check-Name: `CI / validate`

### B) Nicht merge-blocking, aber sichtbar laufen lassen

- Workflow: `smc-deeper-integration-gates`
- Job/Check: `deeper-gates`
- Trigger: `push` auf `main`, `workflow_dispatch`, `schedule` (nightly)
- Zweck: breitere Integrations-/Health-Sichtbarkeit ohne PR-Blocking

### C) Nur vor Release/Publish verpflichtend

- Workflow: `smc-release-gates`
- Job/Check: `release-gates`
- Trigger: `release.published`, `workflow_dispatch`
- Innerhalb dieses Jobs verpflichtend:
  - Strict release gate run via `scripts/run_smc_release_gates.py`
  - Publish-contract verification (im Release-Gate-Skript enthalten)
  - Reference bundle smoke gate (im Release-Gate-Skript enthalten)
  - Release validation test matrix

## 4) Fail vs Warn

- Merge-blocking:
  - Alles, was in required status checks liegt, blockiert Merge bei `fail`.
  - Empfohlen minimal: nur `smc-fast-pr-gates / fast-gates`.
- Sichtbare Warnungen (nicht merge-blocking):
  - `smc-deeper-integration-gates / deeper-gates` liefert tiefe Signale (inkl. degradations/warnings) fuer operative Nachverfolgung.
- Release-blocking:
  - `smc-release-gates / release-gates` ist release-verbindlich.
  - Release/Publish nur durchfuehren, wenn Gate `ok` ist oder Warnungen explizit begruendet und freigegeben sind.

## 5) Praktischer Ablauf fuer Entwickler

1. PR gegen `main` oeffnen.
2. Warten bis `smc-fast-pr-gates / fast-gates` gruen ist.
3. Optional tiefe Signale aus `smc-deeper-integration-gates / deeper-gates` pruefen (falls Lauf vorhanden).
4. Review/Conversation-Resolution abschliessen.
5. Merge (empfohlen: squash).
6. Bei release-relevanten Aenderungen vor Tag/Publish `smc-release-gates` manuell laufen lassen.
7. Erst nach erfolgreichem Release-Gate publizieren.

## 6) Praktischer Ablauf fuer Release/Publish

### Snapshot-/Bundle-bezogene Releases

1. `smc-release-gates / release-gates` erfolgreich ausfuehren (manuell oder per Release-Trigger).
2. Report `artifacts/ci/smc_release_gates_report.json` pruefen.
3. Keine unbegruendeten `degradations_detected`, `missing_artifacts` oder `failures` offen lassen.
4. Sicherstellen, dass Snapshot-Struktur sauber bleibt und `structure_context` nur additiv ist.

### TradingView Library Publish

1. Vor Publish Release-Gate erfolgreich.
2. Publish-Contract-Invarianten erfolgreich (im Release-Gate enthalten; basiert auf `scripts/verify_smc_micro_publish_contract.py`).
3. Referenz-Smoke-Checks erfolgreich (im Release-Gate enthalten).
4. Danach TradingView-Publish-Prozess gemaess Runbook starten.

Bei Warnungen/Degradations:

- Warnungen sind nicht automatisch ignorierbar.
- Fuer Release/Pubish muss jede Warnung begruendet und dokumentiert werden (Issue/PR-Kommentar/Release Notes).

## 7) Diese Checks in GitHub Branch Protection auswaehlen

Empfohlene Auswahl fuer `main`:

- Required: `smc-fast-pr-gates / fast-gates`
- Optional required (strenger): `CI / validate`
- Nicht required, aber beobachten:
  - `smc-deeper-integration-gates / deeper-gates`

Release-/Publish-verbindlich (nicht als PR-required fuer `main`):

- `smc-release-gates / release-gates`

## 8) Release-/Publish-Checklist

Vor Release oder TradingView-Publish:

- [ ] `smc-release-gates / release-gates` ist gruen.
- [ ] Keine unbegruendeten `degradations_detected` oder `missing_artifacts` im Gate-Report.
- [ ] Referenz-Smoke-Checks sind gruen.
- [ ] Snapshot vs `structure_context` ist sauber (kein `structure_context` im Snapshot, nur additiv auf Bundle-Ebene).
- [ ] Publish-Contract-Invarianten sind gruen, wenn TradingView/Micro-Library betroffen ist.
- [ ] Keine lokalen Workspace-/Report-Artefakte im Commit (insb. `artifacts/` und temporaere Reports).
- [ ] Arbeitsbaum ist vor Tag/Release sauber (`git status --short` ohne unbeabsichtigte Aenderungen).
- [ ] Exakter Commit und Tag sind dokumentiert (Release Notes / changelog entry / manifest refs).
