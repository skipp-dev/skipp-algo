# Live News Local vs Remote Diff

This artifact compares the local balanced clean-state evaluation snapshot against the remote clean-state GitHub Actions snapshot from commit `9e0644f1`.

Compared snapshots:

- local: `artifacts/manual_newsapi_balanced_eval/snapshot.json` generated at `2026-04-09T02:58:45.270562Z`
- remote: `artifacts/smc_microstructure_exports/smc_live_news_snapshot.json` from `9e0644f1` generated at `2026-04-09T04:28:02.952868Z`

Summary:

- local stories: `74`
- remote stories: `73`
- only local headlines: `10`
- only remote headlines: `9`
- shared headlines with changed fields: `63`
- actionable regressions: `1`

## Only Local Headlines

- AI jobs: Meta cuts 200 in California amid AI push
- Meta Launches Muse Spark, First AI Model After Hiring Alexandr Wang
- Meta Stock Rises After Launch of New AI Model
- Meta Superintelligence launches Muse Spark AI model
- Meta Unveils Muse Spark AI Model To Compete In Generative AI Space
- Meta reenters the AI game with new 'Muse Spark' model
- Meta releases first new AI model since shaking up team
- Meta unveils first AI model from superintelligence team
- Palo Alto (PANW) Stock Is Trending Overnight: Here's What Is Happening - Apple (NASDAQ:AAPL), Amazon.com
- US FTC fights Meta's fresh attempt to stop reopening of $5bn privacy settlement | MLex | Specialist news and analysis on legal risk and regulation

## Only Remote Headlines

- Anthropic Curbs Rollout of AI Skeleton Key While Meta Regains Model Momentum
- Iowa attorney general sues Meta for breaking consumer protection laws
- Meta Infotech bags Rs 3-cr cloud security orders
- Meta Launches Muse Spark: MSL's First Model Delivers Efficiency Breakthrough
- Meta launches Muse Spark AI: What it is and what it can do
- Meta takes on Claude and ChatGPT with Muse Spark AI, says it understands the world around you
- Meta unveils first AI model from costly superintelligence team
- Muse Spark: Meta Unveils Its Most Advanced Multimodal AI Model Built by Superintelligence Labs; Rolling Out to WhatsApp, Instagram in Coming Weeks
- Russian Bots, Kremlin Agitprop, and Meta's Blind Eye: The Disinformation War Over Hungary's 2026 Election

## Actionable Regression

Only one shared story regressed from actionable to non-actionable, and it kept the same `story_key` on both sides.

| story_key | headline | local | remote |
| --- | --- | --- | --- |
| `dfda3de3b6e5dfd397dfae7315079a28fb62da07:5919003` | Exxon Mobil Stock: War Effect On Earnings (NYSE:XOM) | age `42.8m`, score `0.558`, materiality `MEDIUM`, recency `WARM`, actionable `true` | age `132.0m`, score `0.3836`, materiality `LOW`, recency `AGING`, actionable `false` |

Interpretation:

- the remaining mismatch was recency and score decay, not symbol matching or story deduplication
- the remote clean-state run already preserved the same story identity and source attribution
