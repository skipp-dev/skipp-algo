# SMC Long-Dip Suite — Getting Started

## What is this?

The SMC Suite is a long-dip trading system for US equities. It detects price zones where institutional money is likely buying (Order Blocks, Fair Value Gaps), enriches them with live market data (regime, news, earnings, VIX), and tells you:

> "Here is a setup. This is how strong it is. These are the risks."

It runs as 4 TradingView scripts that work together:

| Script | Role | Required? |
|---|---|---|
| **SMC Long-Dip Suite v7** | Main indicator — zones, hero card, alerts | Yes |
| **SMC Long-Dip Dashboard v7** | Dashboard — lifecycle status, market context | Recommended |
| **SMC Long-Dip Strategy v7** | Strategy — backtesting | Optional |
| **SMC Event Overlay** | Macro events, earnings markers | Optional |

## Step 1: Add the scripts (2 minutes)

1. Open TradingView and go to **Indicators & Strategies**
2. Search for "SMC Long-Dip Suite v7" in your **Invite-only** or **My scripts** tab
3. Add **SMC Long-Dip Suite v7** to your chart first
4. Then add **SMC Long-Dip Dashboard v7**
5. The Dashboard will ask you to connect "BUS" inputs — click each dropdown and select the matching output from SMC Long-Dip Suite v7 (they are labeled identically: BUS Armed → BUS Armed, etc.)

## Step 2: Read the Hero Card (1 minute)

The Hero Card appears in the top-right corner of your chart. It has 12 lines — here's what they mean:

| Line | What it tells you |
|---|---|
| **Action** | What to do: WAIT, PREPARE LONG, READY LONG, ENTER LONG, or BLOCKED |
| **Bias** | Direction of the current setup + regime override if active |
| **Confidence** | Signal strength: Strong, Usable, Thin |
| **Trust** | Data reliability: High, Guarded, Degraded, Insufficient |
| **VIX** | Market fear index (below 20 = calm, above 25 = nervous, above 35 = panic) |
| **Tone** | News + technical sentiment + how many stories mention this ticker |
| **Market** | Today's macro events (CPI, FOMC, GDP) with time |
| **Sector** | Which sectors are leading today |
| **Provider** | Data source status (3/3 ok = all good) |
| **Why now** | Why this setup is relevant right now |
| **Main blocker** | What could prevent a trade (earnings, regime, invalidation) |
| **Data** | When the library data was last refreshed |

**Key rule:** If "Action" says WAIT → do nothing. If it says BLOCKED → definitely do nothing.

## Step 3: Understand the colors (30 seconds)

- **Green zones** = Bullish Order Blocks (potential buy areas)
- **Blue zones** = Fair Value Gaps (price inefficiencies)
- **Dimmed zones** = Low confidence (regime, volume, or news issue)
- **Red/Orange labels** = Warnings (earnings day, RISK_OFF, stale data)

## Step 4: The 10 settings you might change

The suite has only 10 visible settings (experts can reveal 300+ via "All inputs"):

| Setting | Default | When to change |
|---|---|---|
| Signal Mode | Confirmed Only | Switch to "Aggressive Live" if you want faster but less reliable signals |
| Trading Style | Standard | "Easy" for beginners, "Pro" for experienced traders |
| Focus View | On | Turn off to see debug overlays |
| Target 1 (R) | 1.0 | Your first take-profit in risk multiples |
| Target 2 (R) | 2.0 | Your second take-profit |
| Trade Session Gate | On | Keeps you in active market hours only |
| Performance Mode | Balanced | "Light" if your chart is slow |

## Step 5: Setting up alerts (2 minutes)

Right-click the SMC Long-Dip Suite v7 indicator → "Add Alert". You'll see 10 alert options:

1. **Prepare Long** — Setup is forming
2. **Ready Long** — Confirmed, watching for trigger
3. **Enter Long** — Entry level hit (the main one!)
4. **Setup Blocked** — Invalidation or regime issue
5. **High Impact Macro Today** — CPI/FOMC/GDP day
6. **Earnings Today** — This ticker has earnings
7. **Earnings Tomorrow** — Heads-up for tomorrow
8. **Regime Blocked** — Market switched to RISK_OFF
9. **News Turned Bearish** — This ticker's sentiment flipped
10. **Library Stale** — Data older than 2 days

**Recommended minimum:** Enable "Enter Long" and "Setup Blocked".

## Step 6: Your first trade checklist

Before entering any trade, check:

- [ ] Action says READY LONG or ENTER LONG
- [ ] Trust is High or Guarded (not Degraded or Insufficient)
- [ ] No "earnings today" warning for this ticker
- [ ] VIX is below 25 (above = extra caution)
- [ ] Main blocker says "No active blocker"
- [ ] You know where your stop-loss is (the invalidation level)
- [ ] Your position size risks max 1% of your account

## FAQ

**"Why does it say WAIT even though the price is moving?"**
No SMC setup is active. The system only signals when a specific price structure (Order Block + Fair Value Gap + confirmation) aligns.

**"What does DISCOURAGED mean?"**
The market regime (RISK_OFF, high VIX, macro event) makes trading riskier. You CAN still trade, but reduce your size.

**"The data is X days old — is that bad?"**
If > 2 days: the enrichment data (news, regime, earnings) is stale. The price-based signals still work, but context signals are unreliable.

**"What is the difference between Easy, Standard, and Pro?"**
Easy = more setups, lower bar for entry. Pro = fewer setups, higher bar. Standard is the recommended starting point.
