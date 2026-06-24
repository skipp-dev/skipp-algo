# Handover: SMC v2 Feature Branch

**Worktree:** `<repo-root>.worktrees/smc-v2`  
**Branch:** `feature/smc-v2`  
**Basis:** `origin/main`  
**Python:** Projekt-Venv (`<repo-root>/.venv/bin/python`)  
**Stand:** Alle zugehörigen Tests grün, `ruff check --fix` sauber.

---

## 1. Was bisher passiert ist

Die Session hat die SMC-v2-Roadmap Schritt für Schritt umgesetzt. Ursprünglich wollte der Nutzer einige Änderungen über Continue-Editor-Tools (`edit_existing_file`, `single_find_and_replace`) einspielen. Diese Tools hingen bei der großen Datei `scripts/smc_signal_quality.py` wiederholt oder meldeten fälschlich "file does not exist". Daraufhin wurde auf temporäre Python-Patch-Skripte umgestellt, die die Zieldateien atomisch neu schreiben, und anschließend wieder gelöscht.

Implementiert wurden die Phasen:

| Paket | Phase | Inhalt |
|-------|-------|--------|
| 2 | 0b | v2-Score-Router in `scripts/smc_signal_quality.py` |
| 3 | 0c | Zentrale Feature-Flag-Wrapper in `smc_core/v2_features.py` |
| 4 | A | Freshness v2 mit erweiterten Labels |
| 5 | B | Sweep-Trap-Stub (`smc_core/sweep_trap.py`) |
| 6 | C | Reaction-Zone-Stub (`smc_core/reaction_zone.py`) |
| 7 | D | Confluence-Score-Stub + Cutover in `build_signal_quality_v2` |
| 8 | E | SMT-Divergenz-Stub (`smc_core/smt_divergence.py`) |
| 9 | F | Sweep-Trap, Reaction-Zone und SMT-Divergenz in `build_signal_quality_v2` integriert |
| 10 | G | Vollständiger v2-Integrationstest (`tests/test_signal_quality_v2_integration.py`) |

---

## 2. Wichtige technische Entscheidungen

### 2.1 Feature-Flag-Gating

Alle neuen v2-Features werden über `open_prep.feature_flags` geschaltet. In `smc_core/v2_features.py` gibt es dafür einheitliche, safe-default-Wrapper. Beispiel:

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

`build_signal_quality` wurde in `build_signal_quality_v1` umbenannt. Ein neuer Router entscheidet, ob v1 oder v2 aufgerufen wird:

```python
# scripts/smc_signal_quality.py
def build_signal_quality(
    enrichment: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if signal_quality_model() == "v2" or any_v2_feature_enabled():
        return build_signal_quality_v2(enrichment=enrichment, overrides=overrides)
    return build_signal_quality_v1(enrichment=enrichment, overrides=overrides)
```

### 2.3 Unabhängiges Gating in `build_signal_quality_v2`

Ursprünglich gab es in `build_signal_quality_v2` einen frühen `return`, wenn Freshness v2 aus war:

```python
# BUG: verhinderte, dass Confluence etc. liefen, wenn Freshness v2 disabled
if not is_freshness_v2_enabled():
    return result
```

Dies wurde korrigiert. Jetzt ist jedes Feature unabhängig geschaltet:

```python
def build_signal_quality_v2(
    enrichment: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = build_signal_quality_v1(enrichment=enrichment, overrides=overrides)
    enr = enrichment or {}

    # Phase A: Freshness v2
    if is_freshness_v2_enabled():
        ...
        result["SIGNAL_FRESHNESS"] = _freshness_label_v2(...)

    # Phase F: Sweep Trap
    if is_sweep_trap_enabled():
        from smc_core.sweep_trap import detect_sweep_trap
        result.update(detect_sweep_trap(enr))

    # Phase F: Reaction Zone
    if is_reaction_zone_enabled():
        from smc_core.reaction_zone import detect_reaction_zone
        result.update(detect_reaction_zone(enr))

    # Phase D: Confluence Score
    if is_confluence_score_enabled():
        from smc_core.confluence_score import compute_confluence_score
        confluence = compute_confluence_score(enr)
        result.update(confluence)

    # Phase F: SMT Divergence
    if is_smt_divergence_enabled():
        from smc_core.smt_divergence import detect_smt_divergence
        result.update(detect_smt_divergence(enr))

    # Manuelle Overrides gewinnen immer
    if overrides:
        for key, value in overrides.items():
            if key in result:
                result[key] = value

    return result
```

---

## 3. Dateien im aktuellen Stand

### Geänderte Dateien (`git status` zeigt `M`)

- `open_prep/feature_flags.py` — neue Flags für v2-Features
- `scripts/smc_signal_quality.py` — v1/v2-Router, `build_signal_quality_v2`, `_freshness_label_v2`, eingebundene Detektoren
- `tests/test_feature_flags.py` — Tests für neue Flags

### Neue Dateien (`git status` zeigt `??`)

| Datei | Zweck |
|-------|-------|
| `smc_core/v2_features.py` | Zentrale v2-Feature-Flag-Wrapper |
| `smc_core/sweep_trap.py` | Stub: `detect_sweep_trap(enrichment)` |
| `smc_core/reaction_zone.py` | Stub: `detect_reaction_zone(enrichment)` |
| `smc_core/confluence_score.py` | Stub: `compute_confluence_score(enrichment)` |
| `smc_core/smt_divergence.py` | Stub: `detect_smt_divergence(enrichment)` |
| `tests/test_smc_core_v2_features.py` | 15 Tests für Flag-Wrapper |
| `tests/test_signal_quality_v2_freshness.py` | Freshness-v2- + Confluence-Cutover-Tests |
| `tests/test_signal_quality_v2_integration.py` | Integrationstest für alle v2-Features |
| `tests/test_smc_core_sweep_trap.py` | 4 Tests |
| `tests/test_smc_core_reaction_zone.py` | 4 Tests |
| `tests/test_smc_core_confluence_score.py` | 5 Tests |
| `tests/test_smc_core_smt_divergence.py` | 4 Tests |
| `FutureFeatureConsideration/smc_v2_handover.md` | Dieses Dokument |

---

## 4. Bekannte Probleme und Workarounds

### 4.1 Continue-Editor-Tools hängen bei großen Dateien

- **Betroffen:** `edit_existing_file` und `single_find_and_replace` auf `scripts/smc_signal_quality.py`.
- **Symptom:** Tool hängt oder meldet "file does not exist".
- **Workaround:** Temporäre Python-Patch-Skripte unter `scripts/patch_*.py` verwenden, die die Zieldatei neu schreiben. Nach erfolgreichem `ruff`/`pytest` das Patch-Skript löschen.
- **Empfehlung:** Für größere Änderungen an `scripts/smc_signal_quality.py` weiterhin Patch-Skripte oder `cat > file << 'EOF'` nutzen.

### 4.2 Früherer Bug: Early-Return in `build_signal_quality_v2`

- **Status:** Behoben.
- **Details:** Siehe Abschnitt 2.3.

---

## 5. Validierung

Letzter erfolgreicher Testlauf:

```bash
cd <repo-root>.worktrees/smc-v2
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

Ergebnis: **155 passed**.

---

## 6. Nächste Schritte

### Abgeschlossene nächste Schritte

- [x] Option A: Sweep-Trap, Reaction-Zone und SMT-Divergenz in `build_signal_quality_v2` eingebunden.
- [x] Option B: Integrationstest `tests/test_signal_quality_v2_integration.py` mit 3 Tests erstellt.
- [x] Option C: Vorbereitung für Pull Request abgeschlossen (`ruff` sauber, 155 Tests grün).

### Offen: PR auf GitHub öffnen

- Repo: `skippALGO/skipp-algo`
- Base: `main`
- Head: `feature/smc-v2`
- Branch ist sauber auf `origin/main` basiert, keine ungelösten Merge-Konflikte.
- Die Änderungen müssen noch gepusht und der PR erstellt werden.
