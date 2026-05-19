# Quant Promotion-Gate Follow-up Findings — Closure 2026-05-18

**Status:** Closed / implemented
**Owner:** skipp-dev
**Primary code:** `governance/promotion_gate.py`
**Primary tests:** `tests/test_promotion_gate.py`, `tests/test_coverage_omit_audit.py`, `tests/test_tradingview_storage_state_security.py`

## Closure summary

The five non-blocking findings have been implemented as code, tests, or formal
audit documentation.

| ID | Finding | Implemented resolution | Evidence |
|---|---|---|---|
| QPG-01 | `live_vs_wf_ratio_max = 1.5` had no empirical calibration source | ADR-0008 now labels `1.5` as an explicit operator-prior baseline, links a calibration note, and defines the first empirical recalibration contract. | `docs/adr/0008-promotion-gate-thresholds.md`, `docs/research/promotion_gate/live_vs_wf_ratio_calibration_2026-05-18.md` |
| QPG-02 | `walkforward_brier <= 0` should be blocker instead of info/warning | PromotionGate now treats any non-positive `walkforward_brier` as `severity="blocker"` because the live/WF ratio denominator is invalid. | `governance/promotion_gate.py`, `tests/test_promotion_gate.py::test_live_vs_wf_ratio_both_zero_is_blocker` |
| QPG-03 | Sanity-floor ratio `< 0.05` should warn `suspicious_too_good` | The lower floor uses `DEFAULT_LIVE_VS_WF_RATIO_MIN = 0.05` and emits `check="suspicious_too_good"`, `severity="warning"`; warning alone does not block promotion. | `governance/promotion_gate.py`, `tests/test_promotion_gate.py::test_live_vs_wf_ratio_too_good_to_be_true_is_warning_and_does_not_block` |
| QPG-04 | Coverage-gate omit list needed audit | Added a complete audit of current `tool.coverage.run.omit` entries and a contract test requiring every omit to appear in the audit. | `docs/coverage/coverage_omit_audit_2026-05-18.md`, `tests/test_coverage_omit_audit.py` |
| QPG-05 | TradingView Playwright storage-state encryption/security check pending | Added a reproducible guard that fails on tracked plaintext TradingView/Playwright storage-state files; documented secure handling and exposed `npm run tv:auth-security`. | `scripts/check_tradingview_storage_state_security.py`, `tests/test_tradingview_storage_state_security.py`, `docs/tradingview-auth-modes.md`, `README.md`, `package.json` |

## Remaining non-code obligation

The only remaining obligation is scheduled recalibration, not an open finding:
once 100 promoted family windows with paired positive finite live/WF Brier values
exist, ADR-0008 requires recomputing the empirical ratio distribution.
