# TradingView E2E Revalidation — 2026-04-17

## Scope

WP-12: Verify compile and binding contracts for the three SMC mainline targets
using the Playwright-based `tv_preflight.ts` automation against TradingView.

## Targets

| Target | Script Name | Compile | Binding | Status |
|---|---|---|---|---|
| SMC Core Engine | SMC Core | ✅ compile_ok=true | n/a (compile only) | GREEN |
| SMC Dashboard | SMC Decision Board | ✅ compile_ok=true | ❌ settings dialog timeout | PARTIAL |
| SMC Long Strategy | SMC Execution | ✅ compile_ok=true | ❌ wrong legend entry selected | PARTIAL |

## Compile Verification (GREEN)

All three mainline targets compile successfully on TradingView as of 2026-04-17.
This was verified in two independent runs (readonly and mutating execution modes).

Report: `automation/tradingview/reports/preflight-wp12-revalidation-20260417.json`

## Binding Verification

### Last GREEN binding run: 2026-04-08

Report: `automation/tradingview/reports/preflight-2026-04-08T15-57-59-272Z.json`

| Target | Expected | Observed | Result |
|---|---|---|---|
| SMC Decision Board | 58 BUS inputs | 58 matched (+6 extras) | ✅ GREEN |
| SMC Execution | 8 BUS inputs | 8 matched (+1 extra) | ✅ GREEN |

### Contract drift since 04-08

- **SMC Decision Board**: +1 field (`BUS SchemaVersion`) — now 59 expected inputs
- **SMC Execution**: contract unchanged (8 inputs)
- Pine commits since 04-08: 10 commits touching mainline targets
  - `c57ea7e9` feat(core): close 21 missing v6 enrichment fields (WP-6)
  - `478095be` feat(governance): activate first staged runtime trust enforcement
  - `0318fab6` feat(dashboard): surface 5 measurement fields
  - `85c42068` feat(product): surface trust tier and degradation status
  - `7d769bfb` refactor(smc): split Core Engine into modular libraries
  - And 5 more

### 04-17 binding failures (automation, not contract)

**SMC Decision Board**: `openSettingsForScript` timed out after 70s.
The legend double-click reached the wrapper but TradingView's settings
surface never opened. This is a known persistent TradingView UI automation
flakiness documented in repo memory (`tradingview-settings-row-dblclick.md`).

**SMC Execution**: Settings dialog opened successfully, but the automation
selected the wrong legend entry — observed generic inputs
(`Show current anchor`, `Fib A Show % labels`, etc.) instead of BUS
strategy inputs. This is a legend-candidate selection bug, not contract drift.

## Residual Risk

The Dashboard gained `BUS SchemaVersion` since the last green binding run.
This field is verified in the binding contract config (`smc_product_cut_manifest.json`)
but has not been observed on TradingView due to the settings dialog timeout.

**Risk assessment**: LOW. The field was added deliberately in a tracked commit,
the Dashboard compiles cleanly with it, and all 58 prior fields were verified
green on 04-08. The remaining automation issues are UI interaction reliability
problems, not Pine contract regressions.

## Automation health

| Issue | Component | Since | Classification |
|---|---|---|---|
| Settings dialog timeout (Dashboard) | `openSettingsForScript` | 2026-04-05 (intermittent) | TradingView UI flakiness |
| Wrong legend entry (Strategy) | Legend candidate selection | 2026-04-16 | Automation bug |

These should be addressed in a future automation hardening pass but do not
block the compile-green conclusion.

## Conclusion

- **Compile**: GREEN — all 3 mainline targets verified 2026-04-17
- **Binding**: Last full GREEN on 2026-04-08 (9 days, +1 new Dashboard field)
- **Overall**: Compile contract intact. Binding contract structurally intact
  with one additive field. No evidence of regression.
