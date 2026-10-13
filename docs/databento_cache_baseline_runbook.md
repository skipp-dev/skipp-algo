# Databento Sharded-Cache — Phase-B Baseline Runbook

**Action plan:** `Sharded Databento File-Cache (kalibriert)` — Phase B (Datenerhebung).
**Vorbedingung:** PR #2304 (Ledger-Fixes) und PR #2305 (`enable_cache_probe`-Toggle + atomarer Dump) sind auf `main` gemerged.
**Owner:** dev-on-call (Workflow-Dispatch + Analyse).
**Dauer:** ~5 min Operator-Zeit über 2 Tage. CI-Wallclock pro Run ≤ 120 min/Shard.

---

## Erinnerung (sonst vergessen wir es)

| Datum (UTC) | Aktion | Befehl / Link |
| --- | --- | --- |
| **2026-05-20** (Mi) ~09:00 | Run 1 dispatchen | `gh workflow run` (siehe §1) |
| **2026-05-21** (Do) ~09:00 | Run 2 dispatchen — **muss ≥ 1 Trading-Day nach Run 1 liegen**, sonst überschätzt der Hit-Rate-Schätzer | `gh workflow run` (siehe §1) |
| **2026-05-21** (Do) Abend | Artefakte runterladen + auswerten | §2 + §3 |
| **2026-05-22** (Fr) | Go/No-Go-Entscheidung Phase C dokumentieren | §4 |

> **Wenn dieser Termin gerissen wird:** Tracking-Issue im Repo bumpen (`area:cache-baseline` label). Kein Hard-Block — die Producer-Crons laufen weiter, nur Phase C wartet.

---

## §1 Run dispatchen (2× nötig)

```pwsh
$env:GH_PAGER='cat'
gh workflow run smc-databento-production-export-sharded.yml `
  -f lookback_days=30 `
  -f num_shards=6 `
  -f enable_cache_probe=true
```

`lookback_days` + `num_shards` müssen in beiden Runs **identisch** sein — sonst messen wir Apples vs. Oranges.

Run-IDs notieren:
```pwsh
gh run list --workflow=smc-databento-production-export-sharded.yml -L 5
```

---

## §2 Artefakte holen (nach Abschluss beider Runs)

```pwsh
mkdir baseline\run1, baseline\run2 -Force
gh run download <RUN1_ID> --dir baseline\run1 -p "cache-probe-shard-*"
gh run download <RUN2_ID> --dir baseline\run2 -p "cache-probe-shard-*"
```

Erwartet: 6 Ordner × 1 JSONL pro Run (= 12 Files insgesamt).

Plus Per-Shard-Wallclocks für die Phase-D-Baseline:
```pwsh
gh run view <RUN1_ID> --json jobs `
  --jq '.jobs[]|select(.name|startswith("producer"))|{name,startedAt,completedAt}'
```

---

## §3 Auswertung

```pwsh
python scripts/baseline_cache_probe.py `
  --expected-shards 6 --require-same-shards --min-lookups 1 `
  baseline/run1 baseline/run2
```

Coverage-Guards (failen statt still durchzurechnen):

- `--expected-shards 6` — jeder Run muss exakt 6 `cache_probe_shard_*.jsonl` haben (Matrix-Größe). Eine fehlende Shard bedeutet ein Producer-Matrix-Fail oder ein verlorener Probe-Upload → Re-Run.
- `--require-same-shards` — Run 1 und Run 2 müssen dieselben Shard-IDs abdecken (sonst Äpfel-vs-Birnen).
- `--min-lookups 1` — leere JSONLs (typisch wenn `enable_cache_probe=false` durchgerutscht ist) failen sofort.
- Strict-JSON ist Default; nur für legacy-pre-#2305-Artefakte `--no-strict-json` setzen.

Output (Beispiel):
```
Run 1 (baseline/run1):   12345 lookups    3456 unique paths   shards=[0, 1, 2, 3, 4, 5]
Run 2 (baseline/run2):   12567 lookups    3489 unique paths   shards=[0, 1, 2, 3, 4, 5]
Hit-rate (set-overlap, conservative):   67.42 %
Hit-rate (lookup-weighted, realistic):  71.18 %
Phase-C gate (>= 60 % lookup-weighted): PASS — proceed to Phase C.
```

Für maschinenlesbares JSON: `--json` Flag anhängen und die Datei unter `baseline/phase_b_result_YYYY-MM-DD.json` committen (siehe §4).

---

## §4 Decision-Doc (Phase-B Sign-off)

Folgende vier Zahlen + Entscheidung als kleinen Commit auf `main` ablegen
(z.B. unter `docs/databento_cache_baseline_phase_b_YYYY-MM-DD.md` —
analog zu `docs/c8_phase_a_signoff_2026-05-14.md`):

| Metrik | Wert | Quelle |
| --- | --- | --- |
| Projizierte Hit-Rate (lookup-weighted) | … % | `baseline_cache_probe.py` |
| Median Per-Shard-Wallclock (Run 1 + 2 gemittelt) | … min | `gh run view` |
| Max Per-Shard-Wallclock | … min | `gh run view` |
| Unique paths pro Run (Sanity) | …, … | `baseline_cache_probe.py` |

**Decision:**
- Hit-Rate ≥ 60 % → Phase C starten (ADR 0010 + `actions/cache@v4`-Wiring + `prune_stale_cache_files` + `scripts/cache_probe_analyze.py`).
- Hit-Rate < 60 % → Phase C **nicht** starten; stattdessen Plan-Postmortem (warum hat das Probe-Modell überschätzt?) und Cache-Idee deprecaten.

---

## Was nicht passieren darf

- **Kein `enable_cache_probe=true` auf der Cron-Schiene.** Der Toggle ist
  ausschliesslich dispatch-only; Phase B besteht aus **manuellen** Dispatches.
  Schedule-Runs würden den Hit-Rate-Schätzer mit Probe-IO belasten ohne
  Mehrwert.
- **Keine Code-Änderung am Producer in Phase B.** Wenn der Probe selbst
  Bugs hat → Hotfix-PR und Phase B von vorne.
- **Run 1 und Run 2 dürfen nicht am selben Trading-Day liegen** — sonst
  ist das 30-Tage-Lookback-Fenster identisch und der Hit-Rate-Schätzer
  liefert ~100 %, was nur Probe-Determinismus misst, nicht Cache-Reuse.
