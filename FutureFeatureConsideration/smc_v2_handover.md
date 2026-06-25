# Handover: SMC v2 Feature Branch

**Status:** In Review — PR #2945 (`fix/smc-v2-confluence` → `main`).  
**Basis:** `origin/main` nach PR #2940.  
**PR URL:** https://github.com/skippALGO/skipp-algo/pull/2945

> Post-merge sollte dieser Abschnitt auf "Gemerged in `origin/main` via PR #2945" geändert werden.  
**Python:** Projekt-Venv (`<repo-root>/.venv/bin/python`)  
**Stand:** SMC-v2-Confluence-Migration (Phase D) abgeschlossen; Tests grün, `ruff check --fix` sauber.

---

## 1. Was bisher passiert ist

Die Session hat die SMC-v2-Roadmap vollständig umgesetzt. Continue-Editor-Tools hingen bei der großen Datei `scripts/smc_signal_quality.py` wiederholt oder meldeten fälschlich "file does not exist". Daher wurden temporäre Python-Patch-Skripte verwendet, die Zieldateien atomisch neu schreiben und anschließend gelöscht werden.

Implementiert wurden die Phasen:

| Phase | Inhalt |
|-------|--------|
| 0b | v2-Score-Router in `scripts/smc_signal_quality.py` |
| 0c | Zentrale Feature-Flag-Wrapper in `open_prep/feature_flags.py` und `smc_core/v2_features.py` |
| A | Freshness v2 mit erweiterten Labels (`very_fresh`/`fresh`/`aging`/`stale`/`expired`) |
| B | Sweep-Trap-Detektor (`smc_core/sweep_trap.py`) in `build_signal_quality_v2` integriert |
| C | Reaction-Zone-Detektor (`smc_core/reaction_zone.py`) in `build_signal_quality_v2` integriert |
| D | Confluence-Score-Detektor: Cutover von `smc_core/confluence_score.py` auf `smc_core/smc_confluence.compute_confluence`; orthogonale `OB_SUPPORT_SCORE`/`FVG_GAP_SCORE` in `measurement_evidence`; Sweep-Score-Skalierung auf 0-5 korrigiert; `CONFLUENCE_DIRECTION=NONE` bei Score 0; Budget-Refaktorierung in `build_signal_quality_v2` |
| E | SMT-Divergenz-Detektor (`smc_core/smt_divergence.py`) in `build_signal_quality_v2` integriert |
| F | Vollständige v2-Integration aller Detektoren |
| G | Integrationstest `tests/test_signal_quality_v2_integration.py` |

---

## 2. Wichtige technische Entscheidungen

### 2.1 Feature-Flag-Gating

Alle neuen v2-Features werden über `open_prep.feature_flags` geschaltet. `smc_core/v2_features.py` bietet zusätzliche, isolierte Wrapper, die direkt Env-Vars lesen, damit `smc_core` unabhängig von `open_prep` bleibt.

```python
# open_prep/feature_flags.py
def any_v2_feature_enabled() -> bool:
    return any([
        is_freshness_v2_enabled(),
        is_sweep_trap_enabled(),
        is_reaction_zone_enabled(),
        is_confluence_score_enabled(),
        is_smt_divergence_enabled(),
    ])
```

`smc_core/v2_features.py` bleibt ein isolierter Wrapper, der env vars direkt liest und **kein** `open_prep` importiert (Vorgabe: `tests/test_smc_fmp_client_isolation.py`).

### 2.2 Router in `scripts/smc_signal_quality.py`

Der Original-Code wurde als `build_signal_quality_v1` bewahrt. Der neue Router entscheidet wie folgt:

```python
def build_signal_quality(...):
    model = signal_quality_model()
    if model == "v1" and not any_v2_feature_enabled():
        return build_signal_quality_v1(...)
    return build_signal_quality_v2(...)
```

So kann `SIGNAL_QUALITY_MODEL=v1` bleiben und einzelne v2-Features trotzdem aktiviert werden.

### 2.3 Unabhängiges Gating in `build_signal_quality_v2`

`build_signal_quality_v2` ist kein Wrapper um `build_signal_quality_v1` mehr. Es besitzt ein eigenes Budget (Summe = 100):

| Slot | Budget |
|------|--------|
| Structure | 18 |
| Session | 18 |
| Liquidity | 12 |
| OB | 12 |
| FVG | 12 |
| Compression | 12 |
| Confluence | 12 |
| SMT | 4 |

Jedes v2-Feature wird unabhängig geprüft:

```python
if is_confluence_score_enabled():
    from smc_core.smc_confluence import compute_confluence
    confluence = compute_confluence(ob_light, fvg_light, sweeps)
    score += int(_MAX_CONFLUENCE_V2 * confluence.raw_confluence_score)
    result["CONFLUENCE_SCORE"] = confluence_contribution
    result["CONFLUENCE_DIRECTION"] = _derive_confluence_direction(enr)
    ...
```

`smc_core/confluence_score.py` wurde entfernt; der einzige Confluence-Algorithmus ist nun `smc_core/smc_confluence.py` (geometrischer Mittelwert über OB/FVG/Sweep mit Tiering).

---

## 3. Dateien im aktuellen Stand

### Geänderte Dateien

- `open_prep/feature_flags.py` — neue Flags für v2-Features + `any_v2_feature_enabled()`
- `scripts/smc_signal_quality.py` — v1/v2-Router, `build_signal_quality_v2`, `_freshness_label_v2`, alle Detektoren integriert
- `tests/test_feature_flags.py` — Tests für neue Flags
- `.github/copilot-instructions.md` — Anti-Hang-Editor-Fallback-Regel

### Geänderte Dateien in dieser Session

| Datei | Zweck |
|-------|-------|
| `smc_integration/measurement_evidence.py` | `_ob_support_score()`, `_fvg_gap_score()`; OB/FVG-Light-Dicts enthalten `OB_SUPPORT_SCORE`/`FVG_GAP_SCORE` |
| `scripts/smc_signal_quality.py` | Eigenes v2-Budget (18/18/12/12/12/12/12/4); Confluence-Cutover auf `smc_core.smc_confluence`; SMT-Slot |
| `tests/test_smc_core_confluence_score.py` | Migration auf `smc_core.smc_confluence.compute_confluence` und `build_signal_quality_v2` |
| `tests/test_signal_quality_v2_freshness.py` | Confluence-Test an neue API angepasst |
| `tests/test_signal_quality_v2_integration.py` | Orthogonale Scores + Budgettests angepasst |
| `tests/test_smc_v2_signal_quality.py` | Budget-Summe inkl. SMT; Confluence-Test an neue API |
| `tests/test_smc_integration_measurement_evidence.py` | OB/FVG-Price-Guard-Payloads um neue Score-Felder ergänzt |

### Entfernte Dateien

| Datei | Grund |
|-------|-------|
| `smc_core/confluence_score.py` | Funktionalität vollständig durch `smc_core/smc_confluence.py` ersetzt |

### Weiterhin vorhandene Begleitdateien

Diese Dateien existieren weiterhin im Branch und werden aktiv gepflegt:

| Datei | Zweck |
|-------|-------|
| `tests/test_smc_core_v2_features.py` | 15 Tests für Flag-Wrapper |
| `tests/test_signal_quality_v2_freshness.py` | Freshness-v2- + Confluence-Cutover-Tests |
| `tests/test_signal_quality_v2_integration.py` | End-to-End-v2-Integrationstest |
| `tests/test_smc_core_sweep_trap.py` | 4 Tests |
| `tests/test_smc_core_reaction_zone.py` | 4 Tests |
| `tests/test_smc_core_confluence_score.py` | 5 Tests |
| `tests/test_smc_core_smt_divergence.py` | 4 Tests |
| `FutureFeatureConsideration/continue_fallback_rule.md` | Editor-Fallback-Regel |

### Letzte Code-Änderungen (nach Copilot-Review)

| Änderung | Datei | Grund |
|----------|-------|-------|
| Event-Risk-Penalty in `_event_risk_penalty()` extrahiert | `scripts/smc_signal_quality.py` | Field-Preference-Chain-Drift beseitigen; Duplikation vermeiden |
| Sweep-Score-Skalierung von `/10` auf `/5` korrigiert | `scripts/smc_signal_quality.py` | `SWEEP_QUALITY_SCORE` hat Wertebereich 0–5, nicht 0–10 |
| Freshness-Decay ebenfalls `/5` skaliert | `scripts/smc_signal_quality.py` | Konsistenz mit Liquidity-Slot |
| `CONFLUENCE_DIRECTION=NONE` bei Score 0 | `scripts/smc_signal_quality.py` | Verhindert irreführende Richtung ohne Beitrag |
| `SWEEP_QUALITY_SCORE` auf 0.0–1.0 für `compute_confluence` normalisiert | `scripts/smc_signal_quality.py` | Verhindert Sweep-Sättigung im Confluence-Detektor |
| OB/FVG-Hilfsfunktions-Docstrings ins Englische übersetzt | `smc_integration/measurement_evidence.py` | Sprachkonsistenz |
| Doppelte `OB_FRESH`/`mitigation_state`-Berechnung entfernt | `smc_integration/measurement_evidence.py` | Vermeidet Drift |

---

## 4. Bekannte Probleme und Workarounds

### 4.1 Continue-Editor-Tools hängen bei großen Dateien

- **Betroffen:** `edit_existing_file` und `single_find_and_replace` auf `scripts/smc_signal_quality.py`.
- **Symptom:** Tool hängt oder meldet "file does not exist".
- **Workaround:** Temporäre Python-Patch-Skripte oder `cat > file << 'EOF'` verwenden, die die Zieldatei atomisch neu schreiben. Nach erfolgreichem `ruff`/`pytest` das Patch-Skript löschen.

### 4.2 Früherer Bug: Early-Return in `build_signal_quality_v2`

- **Status:** Behoben.
- **Details:** Siehe Abschnitt 2.3.

---

## 5. Validierung

Letzter erfolgreicher Testlauf (im Worktree-Root ausführen):

```bash
python -m ruff check --fix \
  smc_integration/measurement_evidence.py \
  scripts/smc_signal_quality.py \
  tests/test_smc_core_confluence_score.py \
  tests/test_signal_quality_v2_freshness.py \
  tests/test_signal_quality_v2_integration.py \
  tests/test_smc_v2_signal_quality.py \
  tests/test_smc_integration_measurement_evidence.py
python -m pytest \
  tests/test_smc_v2_confluence.py \
  tests/test_smc_core_confluence_score.py \
  tests/test_signal_quality_v2_freshness.py \
  tests/test_signal_quality_v2_integration.py \
  tests/test_smc_v2_signal_quality.py \
  tests/test_smc_integration_measurement_evidence.py \
  tests/test_smc_core_v2_features.py \
  tests/test_feature_flags.py \
  -q
```

Ergebnis: **alle zugehörigen Tests passed**.

---

## 6. Nächste Schritte

- [x] PR #2936 (Vorgänger-PR) wurde gemerged; Worktree entfernt, Branch gelöscht.
- [x] Detektoren gehärtet (Sweep Trap) und konfigurierbar gemacht.
- [x] Edge-Case-Tests ergänzt.
- [x] Freshness-Downgrade bei kontra-Signalen integriert.
- [x] Dokumentation in `docs/v5_5b_architecture.md` ergänzt.
- [x] PR aus `fix/smc-v2-confluence` erstellen: https://github.com/skippALGO/skipp-algo/pull/2945
- [ ] PR #2945 mergen, sobald CI grün und Review abgeschlossen.
- [ ] `docs/v5_5b_architecture.md` um Confluence-Cutover und OB/FVG-Scores ergänzen (Inhalt verifiziert und aktualisiert in diesem Commit).
- [ ] Weitere Iterationen: datengetriebene Kalibrierung der Confidence-Scores.

---

## 7. Schnell-Checkliste für Folgearbeiten an SMC v2

- [ ] Neuen Worktree von `origin/main` erstellen (der alte `smc-v2`-Worktree wurde entfernt)
- [ ] Branch bestätigen (`git branch --show-current`)
- [ ] Nicht im shared `<repo-root>/skipp-algo` schreiben
- [ ] Bei Änderungen an `scripts/smc_signal_quality.py` Patch-Skripte bevorzugen
- [ ] Nach jeder Änderung `ruff check --fix` und zugehörige `pytest`-Tests laufen lassen
- [ ] `FutureFeatureConsideration/smc_v2_handover.md` am Ende der Session aktualisieren
