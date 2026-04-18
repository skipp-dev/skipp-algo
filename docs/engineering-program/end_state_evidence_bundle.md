# End-State Evidence Bundle

Stand: 2026-04-18 (WP-25)

> Konsolidierter Abschlussnachweis des erreichten Systemzustands nach WP-9
> bis WP-21.  Für Owner-Entscheidung, spätere Reviews und
> Release-Kommunikation.

---

## 1. Test-Suite

| Metrik | Wert | Status |
|--------|------|--------|
| Tests gesamt | 4834 | ✅ |
| Bestanden | 4834 | ✅ |
| Fehlgeschlagen | 0 | ✅ |
| Übersprungen | 43 | ✅ (erwartete Skips) |
| Laufzeit | ~8 min | ✅ |
| Coverage | ≥ 65% | ✅ (pyproject.toml `fail_under=65`) |

**Evidenz:** Lokaler Lauf 2026-04-18, `pytest --tb=short -q`

---

## 2. Freeze-Exit-Check

| Criterion | Type | Status |
|-----------|------|--------|
| Benchmark Reports ≥ 2 | Blocking | ⏳ CI-abhängig |
| Benchmark Metrics (Brier/ECE) | Blocking | ⏳ CI-abhängig |
| Smoke Test ≥ 7/10 | Blocking | ⏳ CI-abhängig |
| Release Gates | Blocking | ⏳ CI-abhängig |
| Quality Floor | Advisory | ✅ Code present + tested |
| Publish Drift | Advisory | ✅ Code present + tested |

**Evidenz:** `scripts/run_freeze_exit_check.py` — 10 Tests grün

---

## 3. Publish Drift / Live-State

| Aspekt | Status |
|--------|--------|
| Manifest existiert | ✅ `artifacts/publish_manifest.json` |
| Drift-Detektor | ✅ `scripts/detect_publish_drift.py` |
| Reconciliation (4 Zustände) | ✅ consistent / drift / publish_outstanding / state_unknown |
| Tests | ✅ 14 Tests grün |

**Evidenz:** `tests/test_publish_drift.py`

---

## 4. Quality Floor

| Aspekt | Status |
|--------|--------|
| Tier-Definition | ✅ `docs/engineering-program/quality_floor_definition.md` |
| Tier-Klassifikation | ✅ `release_policy.py::classify_quality_tier()` |
| Communication Guard | ✅ `release_policy.py::QUALITY_COMMUNICATION_GUARD` |
| Release Advisory | ✅ `release_policy.py::quality_tier_release_advisory()` |
| Bootstrap-Konfidenz | ✅ `measurement_evidence.py` |
| Tests | ✅ 6 Tests grün (TestQualityFloorPolicy) |

---

## 5. CI / Refresh Status

| Workflow | Letzter bekannter Status | Quelle |
|----------|-------------------------|--------|
| `smc-library-refresh` | ✅ success | GitHub Actions |
| `smc-live-newsapi-refresh` | ✅ success | GitHub Actions |
| `smc-fast-pr-gates` | ✅ success | GitHub Actions |
| `smc-deeper-integration-gates` | ✅ success | GitHub Actions |

**Evidenz:** GitHub Actions Run History (Stand 2026-04-18)

---

## 6. Product Identity

| Aspekt | Status |
|--------|--------|
| Drei Produktsätze | ✅ `docs/SMC_PRODUCT_IDENTITY.md` |
| Hero Surface frozen | ✅ SMC Core Engine = Lite primary |
| Surface Classification | ✅ Hero / Companion / Research |
| Explicit Non-Goals | ✅ 9 ausgeschlossene Features |
| Identity Lock | ✅ WP-21 Freeze-Marker |
| Tests | ✅ 2 Tests grün |

---

## 7. Generator & Field Governance

| Aspekt | Status |
|--------|--------|
| Field Budget | ✅ 250 (FIELD_BUDGET) |
| Current Count | ~240 exports (headroom ≥ 2%) |
| Sunset Watch | ✅ 4 Batch-3 Kandidaten dokumentiert |
| Orphan Lifecycle | ✅ ORPHANED → DEPRECATED → sunset |
| Pipeline Phases | ✅ 5-Phasen-Modell (WP-11) |
| Tests | ✅ Budget + headroom + sunset watch Tests |

---

## 8. Sentiment / News

| Aspekt | Status |
|--------|--------|
| Rolle definiert | ✅ Additive context, not gating |
| Gewichte als Konstanten | ✅ TECH_WEIGHT=0.7, NEWS_WEIGHT=0.3 |
| Impact-Evaluator | ✅ `evaluate_sentiment_impact()` |
| NewsAPI dekommissioniert | ✅ Stubs only |
| Finnhub Social | ✅ Display-only (kein Gating) |
| Tests | ✅ 5 Tests grün (TestSentimentImpact) |

---

## 9. Staleness Model

| Aspekt | Status |
|--------|--------|
| Continuous staleness_score | ✅ `terminal_feed_lifecycle.py` |
| Domain-specific half-lives | ✅ News=120, Technical=480, Volume=720 min |
| Trust-Tier integration | ✅ `trust_tier.py::weighted_staleness()` |
| Legacy compatibility | ✅ Binäre Logik als Fallback erhalten |
| Tests | ✅ Decay + domain + trust-impact Tests |

---

## Evidenz-Klassifikation

| Kategorie | Dateien | Status |
|-----------|---------|--------|
| **Code present** | Alle WP-Änderungen im Working Tree | ✅ |
| **Test backed** | 39 neue Tests über WP-9 bis WP-21 | ✅ |
| **Operationally evidenced** | CI-Workflows laufen, Refreshes stabil | ✅ |
| **Still manual / owner dependent** | Branch Protection Ruleset, Publish-Vollzug auf TradingView | ⚠️ |

---

## Artefakt-Referenzen

| Artefakt | Pfad |
|----------|------|
| Freeze-Exit-Check | `scripts/run_freeze_exit_check.py` |
| Publish-Drift | `scripts/detect_publish_drift.py` |
| Publish-Manifest | `artifacts/publish_manifest.json` |
| Quality-Floor-Definition | `docs/engineering-program/quality_floor_definition.md` |
| Sentiment-Rolle | `docs/engineering-program/sentiment_role_definition.md` |
| Produktidentität | `docs/SMC_PRODUCT_IDENTITY.md` |
| Feld-Governance | `docs/smc_field_consumer_governance.md` |
| Branch-Protection | `docs/branch_protection_wp20.md` |
| Operator Pack | `docs/engineering-program/freeze_exit_operator_pack.md` |
| Post-Merge-Validation | `docs/engineering-program/post_merge_validation_wp22.md` |
