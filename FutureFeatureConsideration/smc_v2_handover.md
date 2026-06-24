# Handover: SMC v2 Feature Branch

**Status:** Gemerged in `origin/main` via PR #2936 (Commit `881e3957`). Folgearbeiten in PR #2940.  
**Basis:** `origin/main`  
**Python:** Projekt-Venv (`<repo-root>/.venv/bin/python`)  
**Stand:** Alle zugehörigen Tests grün, `ruff check --fix` sauber. Worktree und Branch wurden nach dem Merge aufgeräumt.

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
| D | Confluence-Score-Detektor (`smc_core/confluence_score.py`) + Cutover in `build_signal_quality_v2` |
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

Jedes v2-Feature wird unabhängig geprüft; es gibt keinen frühen Return mehr:

```python
result = build_signal_quality_v1(enrichment=enrichment, overrides=overrides)

if is_freshness_v2_enabled():
    result["SIGNAL_FRESHNESS"] = _freshness_label_v2(...)

if is_confluence_score_enabled():
    result.update(compute_confluence_score(enr))

if is_sweep_trap_enabled():
    result.update(detect_sweep_trap(enr))

if is_reaction_zone_enabled():
    result.update(detect_reaction_zone(enr))

if is_smt_divergence_enabled():
    result.update(detect_smt_divergence(enr))

if overrides:
    for key, value in overrides.items():
        if key in result:
            result[key] = value

return result
```

---

## 3. Dateien im aktuellen Stand

### Geänderte Dateien

- `open_prep/feature_flags.py` — neue Flags für v2-Features + `any_v2_feature_enabled()`
- `scripts/smc_signal_quality.py` — v1/v2-Router, `build_signal_quality_v2`, `_freshness_label_v2`, alle Detektoren integriert
- `tests/test_feature_flags.py` — Tests für neue Flags
- `.github/copilot-instructions.md` — Anti-Hang-Editor-Fallback-Regel

### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `smc_core/v2_features.py` | Isolierte v2-Feature-Flag-Wrapper |
| `smc_core/sweep_trap.py` | `detect_sweep_trap(enrichment)` |
| `smc_core/reaction_zone.py` | `detect_reaction_zone(enrichment)` |
| `smc_core/confluence_score.py` | `compute_confluence_score(enrichment)` |
| `smc_core/smt_divergence.py` | `detect_smt_divergence(enrichment)` |
| `tests/test_smc_core_v2_features.py` | 15 Tests für Flag-Wrapper |
| `tests/test_signal_quality_v2_freshness.py` | Freshness-v2- + Confluence-Cutover-Tests |
| `tests/test_signal_quality_v2_integration.py` | End-to-End-v2-Integrationstest |
| `tests/test_smc_core_sweep_trap.py` | 4 Tests |
| `tests/test_smc_core_reaction_zone.py` | 4 Tests |
| `tests/test_smc_core_confluence_score.py` | 5 Tests |
| `tests/test_smc_core_smt_divergence.py` | 4 Tests |
| `FutureFeatureConsideration/smc_v2_handover.md` | Dieses Dokument |
| `FutureFeatureConsideration/continue_fallback_rule.md` | Editor-Fallback-Regel |

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
python -m ruff check --fix .
python -m pytest \
  tests/test_feature_flags.py \
  tests/test_smc_core_v2_features.py \
  tests/test_signal_quality.py \
  tests/test_lean_value_domains.py \
  tests/test_signal_quality_v2_freshness.py \
  tests/test_signal_quality_v2_integration.py \
  tests/test_smc_core_sweep_trap.py \
  tests/test_smc_core_reaction_zone.py \
  tests/test_smc_core_confluence_score.py \
  tests/test_smc_core_smt_divergence.py \
  -q
```

Ergebnis: **alle zugehörigen Tests passed**.

---

## 6. Nächste Schritte

- [x] PR #2936 mergen, sobald CI grün ist.
- [x] Post-merge: Worktree entfernen, Branch löschen.
- [x] Detektoren gehärtet (Sweep Trap) und konfigurierbar gemacht.
- [x] Edge-Case-Tests ergänzt.
- [x] Freshness-Downgrade bei kontra-Signalen integriert.
- [x] Dokumentation in `docs/v5_5b_architecture.md` ergänzt.
- [ ] PR #2940 mergen.
- [ ] Weitere Iterationen: datengetriebene Kalibrierung der Confidence-Scores.

---

## 7. Schnell-Checkliste für Folgearbeiten an SMC v2

- [ ] Neuen Worktree von `origin/main` erstellen (der alte `smc-v2`-Worktree wurde entfernt)
- [ ] Branch bestätigen (`git branch --show-current`)
- [ ] Nicht im shared `<repo-root>/skipp-algo` schreiben
- [ ] Bei Änderungen an `scripts/smc_signal_quality.py` Patch-Skripte bevorzugen
- [ ] Nach jeder Änderung `ruff check --fix` und zugehörige `pytest`-Tests laufen lassen
- [ ] `FutureFeatureConsideration/smc_v2_handover.md` am Ende der Session aktualisiseren
