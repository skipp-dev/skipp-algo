# Post-Merge Validation — WP-15 bis WP-21

Stand: 2026-04-18 (WP-22)

## Zweck

Dieses Dokument verifiziert, dass die lokal abgeschlossenen Änderungen aus
WP-15 bis WP-21 nach Commit/Push auf dem echten Remote-Stand exakt das
Verhalten zeigen, das lokal behauptet wurde.

## Validierungsstatus

| WP | Änderung | Lokal behauptet | Im Repo vorhanden | In CI gelaufen | Operativ belegt |
|----|----------|-----------------|-------------------|----------------|-----------------|
| **WP-15** | Schema-Enum-Fix (`quality_recommendation`) | ✅ Full-Green (4834 pass) | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-16** | `run_freeze_exit_check.py` (10 Tests) | ✅ 10/10 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-17** | Publish Drift + Reconciliation (14 Tests) | ✅ 14/14 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-18** | Quality Floor Policy (6 Tests) | ✅ 6/6 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-19** | Generator Batch 2 — Sunset Watch (2 Tests) | ✅ 2/2 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-20** | Sentiment Impact Evaluation (5 Tests) | ✅ 5/5 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |
| **WP-21** | Product Identity Final Freeze (2 Tests) | ✅ 2/2 pass | ⏳ nach Commit | ⏳ nach Push | ⏳ nach CI-Lauf |

## Geänderte/neue Dateien (30 Dateien)

### Geänderte Dateien (Modified)

| Datei | WP | Typ |
|-------|----|----|
| `spec/smc_dashboard_payload.schema.json` | 15 | Schema |
| `spec/smc_pine_payload.schema.json` | 15 | Schema |
| `smc_integration/release_policy.py` | 9, 18 | Code |
| `smc_integration/trust_tier.py` | 9 | Code |
| `smc_integration/provider_health.py` | 13 | Code |
| `smc_core/layering.py` | 12, 20 | Code |
| `terminal_feed_lifecycle.py` | 13 | Code |
| `terminal_newsapi.py` | 12 | Code |
| `scripts/generate_smc_micro_profiles.py` | 11, 19 | Code |
| `docs/SMC_PRODUCT_IDENTITY.md` | 14, 21 | Doku |
| `docs/MEASUREMENT_CALIBRATION.md` | 9 | Doku |
| `docs/smc_field_consumer_governance.md` | 11, 19 | Doku |
| `docs/tradingview_operational_publish_runbook_2026-04-17.md` | 10 | Doku |
| `tests/test_generate_smc_micro_profiles.py` | 11, 19 | Test |
| `tests/test_release_policy.py` | 9, 18 | Test |
| `tests/test_smc_integration_trust_tier.py` | 13 | Test |
| `tests/test_smc_library_layering.py` | 12, 20 | Test |
| `tests/test_smc_product_cut_manifest.py` | 14, 21 | Test |

### Neue Dateien (Untracked)

| Datei | WP | Typ |
|-------|----|----|
| `scripts/detect_publish_drift.py` | 10, 17 | Code |
| `scripts/run_freeze_exit_check.py` | 16, 18 | Code |
| `artifacts/publish_manifest.json` | 10 | Artefakt |
| `docs/engineering-program/quality_floor_definition.md` | 9 | Doku |
| `docs/engineering-program/sentiment_role_definition.md` | 12, 20 | Doku |
| `tests/test_freeze_exit_check.py` | 16 | Test |
| `tests/test_publish_drift.py` | 10, 17 | Test |

## Lokale Testlauf-Evidenz

```
Full suite: 4834 passed, 43 skipped, 0 failures (489.85s)
```

## Post-Push Verifikationsschritte

Nach Commit und Push die folgenden Schritte ausführen:

1. **Commit verifizieren:** `git log --oneline -1` → alle 30 Dateien enthalten
2. **CI-Lauf prüfen:** `gh run list --workflow CI --limit 1` → conclusion: success
3. **Fast PR Gates:** `gh run list --workflow smc-fast-pr-gates --limit 1` → success
4. **Deeper Gates:** `gh run list --workflow smc-deeper-integration-gates --limit 1` → success
5. **Neue Tests laufen:** In CI-Log nach folgenden Test-Dateien suchen:
   - `test_freeze_exit_check.py`
   - `test_publish_drift.py`
   - `TestQualityFloorPolicy`
   - `TestSentimentImpact`
   - `test_product_identity_doc_exists_and_is_frozen`

## Diskrepanz-Handling

Falls Remote-Abweichungen auftreten:
- Keine neue WP-Lawine erzeugen
- Nur minimale, isolierte Nachbesserungen
- Jede Abweichung in diesem Dokument als Zeile dokumentieren

## Bekannte Erwartungen

- `.coverage` wird nicht committed (gitignored)
- `artifacts/ci/` Verzeichnis wird nicht committed (CI-Artefakte)
- `tests/fixtures/generated_seed/data/` — lokale Testfixtures
