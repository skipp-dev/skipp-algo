# Review v6.3.4 Release (14 Feb 2026)

**Release Focus**: Parity Hotfixes, Syntax Corrections, Scope Fixes.

## 1. Key Changes

### A. SkippALGO & Strategy (v6.3.4)

* **Parity Hardening**: Both Indicator and Strategy now share identical fix versions.
* **Scope Fix**: `plotchar()` calls moved to global scope (conditional execution) to satisfy Pine v6 strictness.
* **Syntax Fix**: `color.cyan` replaced with `color.aqua`.
* **Logic Fix**: Duplicate verify logic removed.

### B. QuickALGO (v6.3.4)

* Verified clean (Global `plotchar` scope confirmed).
* Confirmed no `color.cyan` usage.

## 2. Validation

### Automated Tests

* **Test Suite**: `tests/test_cooldown.py` + `tests/test_skippalgo_pine.py`.
* **Results**: 339 tests passed (`OK`).
* **Coverage**: Includes regression tests for Cooldown logic and guards against legacy code.

## 3. Deployment Status

* **Version**: `v6.3.4`
* **Tag**: `v6.3.4` (Signed/Annotated)
* **Recommendation**: Production Ready. Matches `v6.3.3` functional logic + Strategy fix.

---

## 4. Superseding Addendum (v6.3.13, 16 Feb 2026)

This document remains valid for the original `v6.3.4` scope. Current repository head is now at `v6.3.13` with additional parity hardening.

### Highlights since v6.3.4

* Restored strict Strategy entry-gate parity with Indicator:
  * reliability,
  * evidence,
  * evaluation,
  * abstain/decision checks.
* Added Strategy runtime dynamic risk parity:
  * Dynamic TP expansion,
  * Dynamic SL profile (widen/tighten),
  * preset-aware dynamic TP effective mapping.
* Wired previously dormant controls:
  * `chochReqVol` is now actively enforced for ChoCH entry paths,
  * BOS/ChoCH structure tags are rendered in Strategy,
  * BOS tags are rendered in Indicator.

### Current verification snapshot

* `pytest -q` → **386 passed**
