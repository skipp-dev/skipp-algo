# Agent Handover — 2026-06-04

Konsolidiertes Übergabedokument aus dem Copilot-Agent Repo-Memory.
Enthält den aktuellen Stand aller laufenden Workstreams, Lessons Learned,
Disziplin-Regeln und nächste Schritte.

---

## 1. Aktiver Workstream: ADR-0020 Options Flow (signed_uoa_notional)

### Was wurde gebaut
- **Extractor:** `governance/family_signed_uoa_notional_v2.py` — `signed_uoa_notional_at(bars, anchor_idx)` → SIGNED imbalance `sum(signed)/sum(abs)` in [-1,+1]. Gap-tolerant, honest-None, strictly PIT. `_Corrupt` Sentinel ist ein `enum.Enum` (nicht bare `object()`) für mypy-Narrowing.
- **Producer:** `scripts/pull_databento_edge_input.py` — `aggregate_signed_uoa_notional` + `_merge_signed_uoa_notional_into_bars`. OPRA-Convention: A=ask-lift=BULLISH(+), B=bid-hit=BEARISH(−), N=0. `notional = size * price * 100`.
- **OPRA Live Fetch:** `fetch_opra_trades_frame(symbol, start, end)` — Credential-bound. OPRA.PILLAR, PARENT-Symbology `{SYM}.OPT`.
- **Quote-Rule Aggressor:** `_quote_rule_opra_aggressor(price, bid, ask)` — Rekonstruiert den Aggressor aus NBBO: `price >= ask → A`, `price <= bid → B`, sonst N. Benötigt `tcbbo`-Schema (trade + consolidated BBO).
- **Adapter:** `governance/family_event_adapter.py` verdrahtet `signed_uoa_notional` an BEIDEN Event-Sites (zone+level), recorded-only.
- **EV-20 Workflow:** `.github/workflows/edge-pipeline-real-run.yml` hat Input `with_opra` (bool).

### Kritischer Schema-Fix
- `_OPRA_TRADES_SCHEMA = "tcbbo"` (NICHT `tbbo`, NICHT `trades`)
- OPRA.PILLAR verwendet CONSOLIDATED Schema-Namen. `tbbo` gibt 422 `dataset_schema_not_supported`.
- Erlaubte Schemas: `cmbp-1, cbbo-1s, cbbo-1m, tcbbo, trades, ohlcv-*, statistics, status, definition`.
- **PR #2569 MERGED** (squash `f2a2ea33`, 2026-06-04T15:33:18Z).

### A/B Ergebnis (pre-registered, DIRECTIONAL resolution label)

| Familie | n_OOS | Baseline AUC | Candidate AUC | Res. Δ | Verdict |
|---------|-------|-------------|---------------|--------|---------|
| BOS | 525 | 0.513 | 0.477 | +0.004 | **no_lift** |
| FVG | 425 | 0.549 | 0.538 | −0.001 | **no_lift** |
| OB | 435 | 0.501 | 0.494 | −0.001 | **no_lift** |
| SWEEP | 280 | 0.530 | 0.474 | +0.007 | **regresses_calibration** |

**Verdict: EXIT 2 = kein Lift.** Feature bleibt RECORDED-ONLY. Konsistent mit der Sättigungsdiagnose: Mikro-/Flow-Features predizieren nicht die 15m-SMC-Richtung.

### Probe-Daten (Varianz-Bestätigung)
- Run 26958674810 (AAPL/MSFT, tcbbo): signedNonZero=649/649, beide Vorzeichen (AAPL 365+/284−, MSFT 281+/368−). Degeneracy behoben.
- Run 26965270936 (5 Symbole, main): alle 5 Symbole 100% non-zero signed. 4639 Events, 2707 (58.4%) mit Feature recorded.

---

## 2. ADR-0019 Feature-Onramp: Sättigungsdiagnose (abgeschlossen)

### Kernbefund
1. **Label/Horizon Mismatch (Root Cause):** Alle getesteten Microstructure-Features (OFI, Kyle λ, avg_trade_size, relative_volume, WVF, VR, momentum_ribbon) predizieren MAGNITUDE/Volatilität, NICHT Swing-DIRECTION. Auf dem Richtungs-Label = coin flip; auf Magnitude-Label = AUC 0.60–0.64.
2. **Redundanz:** v1-Score absorbiert die Magnitude-Information bereits (AUC bis 0.67).
3. **Vol-Autokorrelation:** Bulk (BOS/FVG/OB) der Magnitude-Prädiktabilität = pure Volatilitätspersistenz. Triviale recent-vol EWMA matched/beats den Score.
4. **SWEEP-Ausnahme:** Einzige Zelle mit Score-vs-Vol-Edge (AUC 0.667 vs vol 0.453). ABER: 3rd-Window OOS (2025-04-01..10-01) → fair gap +0.029, CI crosses 0. NICHT repliziert.
5. **Compression:** Regime-relative vol-Percentile-Rank zeigt stabiles inverses Signal (low vol → big sweep), überlebt Pooling + OOS. Aber wirtschaftlich sub-marginal: net>0 nur bei vrp≤1.0 (zero premium), vrp=1.1 → CI crosses 0.

### Fazit
Queue FORMALLY CLOSED (2026-06-04). Directional-Achse SATURIERT. Nächste echte Gewinne brauchen einen ANDEREN Daten-Achse oder ein anderes Produkt.

---

## 3. Nächste Achsen (priorisiert)

| Rang | Achse | Status | Gate |
|------|-------|--------|------|
| 1 | **Options Flow** (signed_uoa_notional) | SHIPPED + A/B FAILED (directional). Mag/regime-Label untested. | Test auf MAGNITUDE-Label oder als Regime-Filter |
| 2 | **Cross-Asset Lead-Lag** | Design pass DONE. Leak-Risiko LOW bei 15m sync bars (nicht tick-level). ~1 Tag Impl. SPY auf XNAS.ITCH verfügbar. | [Design doc](governance/cross_asset_lead_lag_design.md). Pre-cond: PR #2573 merged, SPY-Daten verifiziert |
| 3 | **L2 Depth** (mbp-10 Order Book) | Trade-level VPIN A/B DONE → no_lift. L2 depth bleibt engineering-gated (1.7B rows PIT-Aggregation) | [VPIN findings](governance/adr0019_vpin_ab_findings.md). MBP-10 cost probe: 1.38M rec/sym-day, $0.19 |

### ADR-0020 Meta-Label (C-Slice)
- Draft vorhanden (`pending-adr-0020-meta-label.md`). NICHT committen bis ≥1 Feature `candidate_lifts_resolution` zeigt.
- Pre-Registration: MIN_META_RESOLUTION_LIFT > 0.005, BRIER_REGRESSION_TOLERANCE = 0.01, ABS_ECE_CEILING = 0.10.

### USI Delta / Momentum-Derivative
- Einziges genuinely neues Konzept aus Katalog-Analyse. Dockt auf `family_momentum_ribbon_v2.py`.
- GATE: nicht bauen bis current ribbon A/B Verdict auf realen Daten vorliegt.

---

## 4. CI/Governance Architektur

### Branch Protection
- `strict=true`, `required_status_checks=[fast-gates]`, keine required reviews.
- Auto-merge wartet auf ALLE Checks (inkl. non-required validate/CodeQL).
- Admin-merge (`gh api -X PUT .../merge`) = Fast Path für Low-Risk PRs.
- `gh pr update-branch` nötig wenn `mergeStateStatus=BEHIND`.

### Ledger/Pin/Budget-System (KRITISCH)
Vor jedem Push prüfen:

| Pattern | Ledger-Test |
|---------|-------------|
| `pytest.skip` / `@pytest.mark.skip` | `test_pytest_skip_budget.py` |
| `except:` / `except Exception:` | `test_broad_except_silent_budget.py` |
| `# type: ignore` | `test_type_ignore_budget.py` ← scannt den LITERAL string, auch in Kommentaren! |
| `hashlib.md5/sha1` | `test_hashlib_weak_hash_ledger.py` (LINE-EXACT) |
| `tempfile.mkstemp` | `test_random_tempfile_ledger_pin.py` (LINE-EXACT) |
| `nonlocal` | `test_nonlocal_budget.py` (LINE-EXACT) |
| `warnings.simplefilter` | `test_warnings_simplefilter_ledger.py` (LINE-EXACT) |
| bare `print()` in prod code | `test_prod_print_ledger.py` |

**One-shot local check vor Push:**
```powershell
& .venv\Scripts\python.exe -m pytest -q --no-header -n auto `
  tests/test_*ledger*.py tests/test_*pin*.py tests/test_*budget*.py `
  tests/test_*discipline*.py tests/test_*tripwires*.py `
  tests/test_silent_security_and_boundary_bundle.py 2>&1 | Select-Object -Last 3
```
Erwartet: ~630 Tests, ~60s, alle grün.

### PR-Titel-Linter (ADR-0013)
- Format: `concern(scope): subject`. scope PFLICHT.
- Erlaubte concerns: feat fix test docs refactor perf build ci chore revert style.
- `data(...)` ist NICHT erlaubt → Generatoren MÜSSEN `chore(<scope>)` nutzen.

### Upload-Artifact Pin
- `_FROZEN_MAJOR = "v7"` in `tests/test_workflow_upload_artifact_uniform_version.py`.
- Neue Workflows mit v4 → Test failt → auf v7 bumpen, nicht allowlisten.

### Coverage Omit Guard
- `pyproject.toml` `tool.coverage.run.omit` geschützt durch `tests/test_coverage_omit_audit.py`.
- Änderungen erfordern Update in `docs/coverage/coverage_omit_audit_2026-05-18.md`.

---

## 5. Arbeitsdisziplin (verbindlich)

### Vor JEDEM Commit — Pflicht-Checkliste
1. `pytest <betroffene_tests> -q` → grün?
2. `ruff check <geänderte_dateien>` → clean?
3. Selbst-Review: Diff konsistent? Alle verwandten Stellen aktualisiert?
4. Ledger-Scan (s.o.) auf geänderten .py-Files.
5. ERST DANN commit/push.

### SIM102 (collapsible-if) — NICHT fixen
Policy in `pyproject.toml:101` ignoriert SIM102. 7 Violations sind beabsichtigt (AST-Visitor Patterns).

### Edge-Pipeline Probes
- **Databento-Kosten:** tcbbo ist schwerer als trades. Probe-first Discipline.
- **Schema-Validierung:** VOR dem Dispatch prüfen, ob das Schema auf dem Dataset unterstützt ist (metadata.list_schemas).
- **PSR-Floor:** 30 triggered returns minimum; auf 15m braucht ein Fenster ≥8 Handelstage (~6 Events/Tag).
- **Secret-Rotation:** Wenn ein lokaler API-Key rotiert wird, AUCH jeden CI-Secret aktualisieren (`gh secret list` Timestamp vs. Rotation-Datum).

---

## 6. Produktstrategie (Director-Memo)

### North Star
SMC-Suite ist erst Produkt, wenn EINE SMC-Strategie reproduzierbaren, OOS positiven Edge auf Live-Databento nachweist — gemessen durchs Promotion-Gate.

### Strategische Schlüsse
- **STOP-Liste:** Keine neuen Governance-Tools bis echte Strategie ansteht.
- **EIN Wertstrom:** EV-20 Edge-Pipeline (real Databento → decision JSON → Promotion-Gate).
- **Drift an der Quelle:** Pre-Flight-Validator vor `gh pr create` in jedem Generator.

---

## 7. Offene technische Items

### TV Preflight (smc-library-refresh.yml)
- Failing seit 2026-05-29: v7 Dashboard stuck in historical-version view ("V2" read-only).
- Fix in `automation/tradingview/lib/tv_shared.ts` (uncommitted, branch docs/adr0019-variance-ratio-verdict).
- NICHT gepusht — braucht Live-TV-Verifikation.

### Databento Producer Perf (Phase 3)
- PRs #2287-#2292 offen (pip→uv, Sharded Producer, File-Cache).
- Zeit-Sharding (nicht Symbol-Sharding).
- Cache: `artifacts/databento_volatility_cache/` (gitignored).

### Stale Data-PRs
- Edge-Real-Run PRs tragen ~33 Dateien, oft 21-ahead/14-behind, CONFLICTING.
- Decision-JSONs sind echte Governance-Daten. NICHT einfach schließen ohne zu retten.

---

## 8. Worktree-Layout

| Worktree | Branch | Zweck |
|----------|--------|-------|
| `skipp-algo/` | `main` | Hauptarbeitskopie |
| `wt-ofi/` | `feat/adr0020-opra-tbbo-aggressor` (merged) | ADR-0020 Options Flow |
| `wt-kyle/` | — | Kyle Lambda A/B |
| `wt-vol/` | — | Relative Volume A/B |
| `wt-ab-onramp/` | — | Feature A/B Onramp |
| `wt-vr-cand/` | — | Variance Ratio Candidate |
| `wt-ats/` | — | Avg Trade Size |
| `wt-ribbon-retire/` | — | Momentum Ribbon |
| `wt-2355/`, `wt-2370/`, `wt-2371/` | — | Issue-Worktrees |

Python venv: `c:\Users\preus\skipp-algo\.venv\Scripts\python.exe` (immer absoluter Pfad aus Worktrees).
Env-Setup: `$env:PYTHONUTF8="1"; $env:PYTHONPATH=$PWD`.
Auth: `gh -R skippALGO/skipp-algo`, Auth-User: skipp-dev.

---

## 9. Key Lessons Learned

1. **OPRA.PILLAR nutzt CONSOLIDATED Schema-Namen** (tcbbo, cbbo), nicht venue-level (tbbo). Immer metadata.list_schemas prüfen.
2. **"type: ignore" Budget-Scanner** zählt den LITERAL String, auch in Kommentaren/Docstrings. Nie "type: ignore" als Prosa schreiben → "static-typing suppression".
3. **Line-exakte Ledger** (hashlib, tempfile, nonlocal, warnings): Jede Zeilenverschiebung (auch durch Kommentare) trippt den Drift-Guard.
4. **Feature-Varianz vor A/B prüfen:** OPRA `trades` side ist uniform N → signed=0 → zero variance → A/B nutzlos. Probe + Coverage-Check vor dem teuren A/B-Fenster.
5. **Branch Protection `BEHIND`:** `gh pr update-branch` triggert frische Checks → Auto-Merge greift erst danach.
6. **Secret-Rotation:** Lokale Key-Rotation invalidiert CI-Secrets. `gh secret list` Timestamp prüfen.
7. **ADR-Datei committen:** `git status ??` = untracked = shipped NICHT. Immer verifizieren.
8. **Microstructure-Features + Richtungs-Label = Null.** Diese Features predizieren Magnitude, nicht Direction. Label/Horizon-Match ist Voraussetzung.
9. **AUC < 0.5 bei einem Benchmark:** Nie den Gap raw quoten. Sign-Oracle (max(auc, 1-auc)) vor dem Edge-Claim.
10. **Stale Memory:** Memory-Files >7 Tage immer mit `Test-Path`/`grep_search` gegen main verifizieren.

---

*Generiert 2026-06-04 durch Copilot-Agent aus `/memories/repo/` (28 Files konsolidiert).*
