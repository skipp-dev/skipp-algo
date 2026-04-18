# Freeze-Exit Operator Pack

Stand: 2026-04-18 (WP-24)

> Kompaktes Operator-Pack für den Exit-Tag.
> Dieses Dokument fasst alle vorhandenen Freeze-Exit-Bausteine zusammen.
> Es definiert keine neuen Regeln — es operationalisiert die bestehenden.

---

## Exit-Day Run Order (10 Schritte)

| # | Schritt | Typ | Kommando / Aktion | Erwartet |
|---|---------|-----|-------------------|----------|
| 1 | **Lokale Suite grün** | Automatisiert | `python -m pytest --tb=short -q` | 0 failures |
| 2 | **Freeze-Exit-Check** | Automatisiert | `python -m scripts.run_freeze_exit_check --output-json artifacts/ci/freeze_exit_verdict.json --output-md artifacts/ci/freeze_exit_verdict.md` | `freeze_exit_ready: true` |
| 3 | **Publish-Drift-Check** | Automatisiert | `python -m scripts.detect_publish_drift --reconcile` | Kein Drift, kein `publish_outstanding` |
| 4 | **Library-Refresh ≥ 56** | Manuell prüfen | `gh run list --workflow smc-library-refresh --limit 80 --json conclusion \| jq '[.[] \| select(.conclusion=="success")] \| length'` | ≥ 56 |
| 5 | **Deeper-Integration ≥ 80%** | Manuell prüfen | `gh run list --workflow smc-deeper-integration-gates --limit 40 --json conclusion` | ≥ 80% success |
| 6 | **Measurement-Benchmarks ≥ 2** | Manuell prüfen | `gh run list --workflow smc-measurement-benchmark --json conclusion` | ≥ 2 success |
| 7 | **CI auf HEAD grün** | Manuell prüfen | `gh run list --workflow CI --limit 1 --json conclusion` | success |
| 8 | **Kein kritischer Bug** | Manuell prüfen | `gh issue list --label critical --state open` | 0 issues |
| 9 | **Branch-Protection-Status** | Manuell prüfen | Ruleset `main-protection` aktiv in GitHub UI | PR-Pflicht + Status-Checks aktiv |
| 10 | **Owner-Entscheidung** | Manuell | Owner bestätigt Exit oder Verlängerung | Explizite Entscheidung |

---

## Quellen pro Schritt

| # | Quelle / Baustein | Datei |
|---|-------------------|-------|
| 1 | Test-Suite | `pyproject.toml` (pytest config) |
| 2 | Freeze-Exit-Check | `scripts/run_freeze_exit_check.py` (WP-16/18) |
| 3 | Publish-Drift | `scripts/detect_publish_drift.py` (WP-10/17) |
| 4–6 | Stabilitätskriterien | `docs/freeze_exit_stability_criteria.md` §2 |
| 7 | CI-Status | GitHub Actions |
| 8 | Bug-Tracking | GitHub Issues |
| 9 | Branch Protection | `docs/branch_protection_wp20.md` (WP-23) |
| 10 | Governance | Owner Review |

---

## Fail-Triage

Was tun, wenn nur 1 von 10 Punkten rot ist?

| Roter Punkt | Bewertung | Aktion |
|-------------|-----------|--------|
| Lokale Suite | **Blocker** | Fix identifizieren, kein Exit |
| Freeze-Exit-Check blocked | **Blocker** | Blocking-Criterion aus JSON lesen, gezielt fixen |
| Publish-Drift | **Advisory** | Drift dokumentieren, Exit möglich wenn Owner akzeptiert |
| Library-Refresh < 56 | **Blocker** | Warten oder Ursache diagnostizieren |
| Deeper-Integration < 80% | **Blocker** | Failure-Typ prüfen (Infra vs. Test) |
| Measurement < 2 | **Blocker** | Benchmark manuell triggern |
| CI auf HEAD rot | **Blocker** | Fix, dann neu prüfen |
| Kritischer Bug offen | **Blocker** | Bug fixen oder als nicht-kritisch reklassifizieren |
| Branch Protection fehlt | **Advisory** | Admin-Schritt ausführen, Exit möglich |
| Owner sagt nein | **Blocker** | Verlängerung dokumentieren |

### Eskalationsregeln

- **1 Advisory rot:** Exit möglich mit dokumentierter Akzeptanz
- **1 Blocker rot:** Kein Exit. Minimal-Fix, dann erneut prüfen
- **2+ Blocker rot:** Kein Exit. Root-Cause-Analyse, Review nach Fix
- **Nur zeitbedingt blockiert:** Warten, nicht Schwellen senken

---

## Schnellstart (Copy-Paste)

```bash
# 1. Lokale Suite
python -m pytest --tb=short -q

# 2. Freeze-Exit-Check
python -m scripts.run_freeze_exit_check \
  --output-json artifacts/ci/freeze_exit_verdict.json \
  --output-md artifacts/ci/freeze_exit_verdict.md
cat artifacts/ci/freeze_exit_verdict.md

# 3. Publish-Drift
python -m scripts.detect_publish_drift --reconcile

# 4–8. Remote-Checks
gh run list --workflow smc-library-refresh --limit 80 --json conclusion | jq '[.[] | select(.conclusion=="success")] | length'
gh run list --workflow smc-deeper-integration-gates --limit 40 --json conclusion | jq '[.[] | select(.conclusion=="success")] | length'
gh run list --workflow smc-measurement-benchmark --json conclusion | jq 'length'
gh run list --workflow CI --limit 1 --json conclusion
gh issue list --label critical --state open
```

---

## Zeitliche Einordnung

| Meilenstein | Datum |
|-------------|-------|
| Freeze-Start | 2026-04-15 |
| Frühester 14-Tage-Punkt | 2026-04-29 |
| Freeze-Ende (geplant) | 2026-05-15 |
| Exit-Entscheidung | Am oder vor 2026-05-12 |

Dieser Operator Pack ersetzt keine bestehende Dokumentation, sondern
bündelt die vorhandenen Bausteine in eine ausführbare Reihenfolge.
