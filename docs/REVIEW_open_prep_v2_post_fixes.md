# Open-Prep Suite — Senior Code Review (Post-Fix Cycle)

**Reviewer:** Automated Senior Review  
**Scope:** All 16 Python files in `open_prep/` (~8 200 LOC)  
**Date:** 2025-07-15  
**Framework:** Correctness · Data Contracts · Reliability · Performance · Security/Hygiene · Testability

---

## Executive Summary

All prior H1–H8 / M1–M5 / L1 fixes are confirmed merged. Six new findings surfaced — **3 HIGH**, **2 MEDIUM**, **1 LOW**.

| Severity | Count | Synopsis |
|----------|-------|----------|
| **HIGH** | 3 | diff sector-key mismatch, generic-alert stale field, relative output path |
| **MEDIUM** | 2 | non-atomic outcome writes, `_safe_float` vs `to_float` duplication |
| **LOW** | 1 | `__init__.__all__` incomplete |

---

## HIGH Severity

### H1 — `diff.py` sector-key mismatch breaks sector-rotation detection

**File:** `diff.py:130–145`  
**Dimension:** Correctness / Data Contracts

`save_result_snapshot()` (line 42) correctly normalises the sector key:

```python
"sector": c.get("symbol_sector") or c.get("sector"),
```

But `compute_diff()` reads the **current** candidates with:

```python
for c in current.get("candidates", []):
    s = str(c.get("sector") or "Unknown")
```

The current candidates are the raw `ranked_v2` list (passed at
`run_open_prep.py:3141`). Scorer v2 stores the sector as
`symbol_sector` (scorer.py:278). Therefore `c.get("sector")` returns
`None` for every current candidate → all fall into `"Unknown"` →
spurious rotation diffs every run.

**Fix:** Read `c.get("symbol_sector") or c.get("sector")` in
`compute_diff`, matching the normalisation in `save_result_snapshot`.

---

### H2 — `alerts.py` generic payload references deleted `gap_class` field

**File:** `alerts.py:148`  
**Dimension:** Data Contracts

```python
"gap_class": candidate.get("gap_class"),
```

`dispatch_alerts()` is called with `ranked_v2` candidates
(run_open_prep.py:3156). V2 candidates have `gap_bucket` (scorer.py:274),
not `gap_class`. Result: the generic webhook always sends
`"gap_class": null`. Downstream consumers that depend on this field
receive no useful data.

**Fix:** Replace `gap_class` with `gap_bucket` to serve the v2 field
that consumers can act on.

---

### H3 — `main()` writes to CWD-relative path

**File:** `run_open_prep.py:3337`  
**Dimension:** Reliability

```python
latest_path = Path("open_prep/latest_open_prep_run.json")
```

If `main()` is invoked from a different working directory (cron, CI,
systemd), the file is written to the wrong location — or silently
creates a stray directory tree. All other artifact paths (`OUTCOMES_DIR`,
`LAST_RESULT_PATH`, etc.) have the same pattern, but `main()` is the
public entry-point most likely to be called from elsewhere.

**Fix:** Anchor the path relative to `__file__` so it resolves
correctly regardless of CWD:

```python
_SELF_DIR = Path(__file__).resolve().parent
latest_path = _SELF_DIR / "latest_open_prep_run.json"
```

---

## MEDIUM Severity

### M1 — Non-atomic writes in `outcomes.py` and `diff.py`

**Files:** `outcomes.py:79`, `diff.py:36`  
**Dimension:** Reliability

Both files write JSON directly to the target path:

```python
with open(path, "w", encoding="utf-8") as fh:
    json.dump(...)
```

If the process crashes mid-write (kill, OOM, disk full), the file is
truncated and subsequent reads fail.  `watchlist.py` uses the same
pattern but is already batched (prior fix H3).

**Fix:** Use atomic write-then-rename (write to a `.tmp` sibling, then
`os.replace()` to the final path).

---

### M2 — `_safe_float` duplicated in `regime.py`; drift risk with `to_float` in `utils.py`

**Files:** `regime.py:16`, `utils.py:7`  
**Dimension:** Testability / Hygiene

`regime.py` defines its own `_safe_float(val, default=0.0)` which is
semantically identical to `utils.to_float`. Two independent
implementations risk diverging. `run_open_prep.py:200` also has a local
`_to_float` wrapper.

**Fix:** Replace `_safe_float` usages in `regime.py` with
`from open_prep.utils import to_float` and delete the private copy.

---

## LOW Severity

### L1 — `__init__.__all__` incomplete

**File:** `__init__.py`  
**Dimension:** Hygiene

`__all__` lists 13 modules but omits `streamlit_monitor` and `ai`.
While `streamlit_monitor` is a standalone app, `ai.py` is imported by
external callers as a backward-compat shim and should be discoverable.

**Fix:** Add `"ai"` to `__all__`.

---

## Evidence Pack (für Approval)

| ID | Before | After |
|----|--------|-------|
| H1 | `c.get("sector")` returns `None` for v2 candidates | Both save and diff use `c.get("symbol_sector") or c.get("sector")` |
| H2 | `gap_class: null` in every generic webhook | `gap_bucket` sent with actual v2 bucket label |
| H3 | Path breaks on non-repo CWD | Anchored to `__file__` |
| M1 | Direct-write path in outcomes/diff | Atomic tmp+rename |
| M2 | Two `_safe_float` clones | Single `to_float` import |
| L1 | `ai` missing from `__all__` | Added |

---

## Proposed Patch

See commit immediately following this review.
