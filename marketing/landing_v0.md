# SMC — Landing Page v0 (Draft, not for launch)

> **Status:** Draft per Plan §1.2 (W0–W1, 21.04–03.05.2026).
> **Goal:** Wireframe + copy + 1 annotated screenshot. *Not* a public launch
> — Pricing must land in Q4 first.
> **Render target:** `marketing/landing_v0.html` (vanilla CSS, Inter font).

---

## Wireframe

```
┌──────────────────────────────────────────────────────────────┐
│ HEADER                                                       │
│   SMC — The SMC Indicator With Measured Trust.               │
│   Not claimed. Measured on 258+ events across 12 pairs.      │
│   [CTA: View Live Dashboard] [CTA: See the numbers]          │
├──────────────────────────────────────────────────────────────┤
│ LIVE SCREENSHOT — Audit View (rows 22–33)                    │
│   Annotation arrows on:                                      │
│     • Brier 0.168                                            │
│     • ECE 0.131 (smECE in Q3)                                │
│     • FVG Health row                                         │
│     • Trust-Tier badge                                       │
│     • Per-Family hit-rate rows (OB / FVG / BOS / SWEEP)      │
├──────────────────────────────────────────────────────────────┤
│ PILLAR 1            PILLAR 2            PILLAR 3             │
│ MEASURED            REGIME-AWARE        TRUST YOU CAN SEE    │
│   Brier 0.168         RTH vs ETH splits   19+ dashboard rows │
│   ECE   0.131         Vol regime in       Open code, public  │
│   5,608 tests          family weights     SHA anchors        │
│ (✅ in code,        (⚙️ operational)    (all hashes link    │
│  🧪 tested)                              to commit)          │
├──────────────────────────────────────────────────────────────┤
│ ACADEMIC BACKING                                             │
│   Friday 2026 · Parekh-Heller 2026 · Hammer-Patel 2025       │
│   (links → IEEE Access / JSE)                                │
├──────────────────────────────────────────────────────────────┤
│ PRICING                                                      │
│   Coming Q4. Transparent, monthly cancellable.               │
│   Opt-in renewal — no auto-charges without explicit confirm. │
└──────────────────────────────────────────────────────────────┘
```

---

## Copy blocks (final wording for v0)

### Hero

> **The SMC Indicator With Measured Trust.**
> Not claimed. Measured on 258+ events across 12 pairs.
> Brier 0.168 · ECE 0.131 · 5,608 tests passing.

### Pillar 1 — Measured

Every signal family is scored against a public calibration benchmark
(`zone_priority_calibration.json`). We report **Brier**, **ECE**, and
per-family **hit rate** — not aspirational percentages.

### Pillar 2 — Regime-aware

Family weights split by **session** (RTH / ETH) and **volatility regime**
(NORMAL / HIGH). The plan upgrades this to contextual calibration with
≥1,000 events in Q3 (Phase F).

### Pillar 3 — Trust You Can See

The Audit View exposes 19+ rows of evidence: trust tier, provider state,
per-family confidence, and FVG health. All numbers reference SHA-pinned
artefacts in the repo.

### Pricing footer (placeholder)

> **Coming Q4 2026.** Monthly cancellable in two clicks. Opt-in renewal
> — we email seven days before any charge and you confirm. No dark
> patterns; full refund if calibration grade drops below B for fourteen
> consecutive days.

---

## Proof types covered (per Folkard 2025)

| Type           | Source                                 | Status |
|----------------|----------------------------------------|--------|
| Stats / Figures | Brier, ECE, event count                | ✅ live |
| Accreditations  | Friday 2026, Parekh-Heller 2026, Hammer-Patel 2025 (full citations: [README → Academic Grounding](../README.md#academic-grounding)) | ✅ in README |
| Consistency     | All numbers cross-verifiable in Audit View          | ✅      |
| Social proof    | User quotes                            | ⏳ Q3 (W5+) |

---

## Assets to produce before merging v0 → v1

- [ ] Annotated PNG of Audit View (screenshot from TradingView, arrows in
      Figma / Keynote). Capture checklist:
      1. Load `SMC_Core_Engine.pine` + `SMC_Dashboard.pine` on AAPL 15m.
      2. Pick `Quickstart Preset = Mega-Cap US Tech` (loads RVOL floor 1.30).
      3. Wait until Hero one-liner row shows `Top FAM HR%` ≥ 70%.
      4. Capture full dashboard. Annotate (a) Hero one-liner, (b) Zone
         Priority row 5, (c) per-family rows 27–30, (d) Audit row 22
         (Zone Priority breakdown).
      5. Save as `marketing/assets/landing_v0_audit.png` (1600 × 1000).
- [ ] Final HTML render of `landing_v0.html` — once asset above is in,
      replace the placeholder `<div class="screenshot-placeholder">`
      block with `<img src="assets/landing_v0_audit.png" alt="…">`.
- [ ] Cross-link from README badge.
- [ ] Tracking-pixel decision (Q3 — Plausible or Umami, no GA).
- [ ] Quickstart-template gallery: link to
      [`tradingview_indicator_templates.md`](tradingview_indicator_templates.md)
      from the landing's *Three pillars* section once the three TV
      templates are saved.

---

## Out of scope (do *not* add to v0)

- Pricing logic / Stripe integration → Q4 (Plan §3.4).
- Community-Discord widget → Q4.
- Feature comparison table vs. LuxAlgo → never (favours incumbent;
  see Plan §0 guardrail).
- Auto-renewal claim copy not legally reviewed → Q4 W22.
