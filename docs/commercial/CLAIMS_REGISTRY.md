# Commercial claims registry

Status: internal Phase-0 policy, 2026-08-10.

This registry controls product, landing-page, onboarding and sales copy. It is
not legal advice. A technically true statement can still require separate
external review before publication.

## Status vocabulary

- **ALLOWED** — may be used when the cited current artefact still supports it.
- **CONDITIONAL** — may be used only with the required qualifier, date, sample
  and evidence class.
- **BLOCKED** — must not be used in customer-facing material.
- **EXTERNAL APPROVAL REQUIRED** — repository evidence cannot authorize use.

## Registry

| Claim | Status | Required wording or evidence |
|---|---|---|
| SMC Long-Dip Suite is a TradingView indicator for structured long-dip decisions in US equities | ALLOWED | Keep the long-only and decision-support scope visible |
| The product shows structure, context, invalidation and explicit uncertainty | ALLOWED | Each named capability must exist in the released customer surface |
| SMC Decision Board is an optional Pro companion | ALLOWED | Do not describe operator-only diagnostics as customer features |
| Skipp Live Decision Mesh is available to customers | BLOCKED | Private prototype; requires a separate release decision and evidence |
| TradingView supplies Skipp with proprietary/provider data | BLOCKED | TradingView is a chart/customer surface, not the Skipp upstream provider |
| Pine receives arbitrary live HTTP data from Skipp | BLOCKED | Pine has no supported arbitrary HTTP path; static library refresh is not live transport |
| The chart product is enriched by three live providers | BLOCKED | Conflates backend availability with actual Pine delivery |
| A named number of automated tests pass | CONDITIONAL | State exact commit, date, test scope and result; never use a historical count as a standing product claim |
| A calibration metric such as ECE, Brier or hit rate | CONDITIONAL | State date, population, sample size, horizon and evidence class; do not imply live P&L |
| The current 33 modeled OOS setups are a live track record | BLOCKED | They are modeled triggered-setup returns, not live execution or portfolio P&L |
| SMC is profitable, market-beating or has a proven edge | BLOCKED | Requires a separately approved live evidence and claims gate |
| Sharpe or drawdown as a headline marketing claim | BLOCKED | Current sample and confidence gates do not support it |
| Institutional-grade | BLOCKED | Undefined comparative superlative without an approved substantiation standard |
| Guaranteed accuracy, returns or risk reduction | BLOCKED | No guarantee is supported |
| Personalized recommendation or financial advice | BLOCKED | Product remains decision support |
| Automated live order placement, sizing or modification | BLOCKED | Outside the initial commercial product boundary |
| Provider-specific commercial copy | EXTERNAL APPROVAL REQUIRED | Approval is owner-controlled and handled outside the repository |
| Customer quote, user count or retention figure | CONDITIONAL | Requires consent, a reproducible measurement definition and observation date |
| Price, refund promise or renewal terms | EXTERNAL APPROVAL REQUIRED | Requires completed commercial policy and external approval before publication |

## Evidence-class labels

Every quantitative product statement must use exactly one of these classes:

- **MODELED OOS** — deterministic triggered-setup return model; not execution.
- **PAPER** — paper execution with recorded lifecycle and outcome.
- **LIVE** — real live execution evidence under the approved live protocol.
- **PRODUCT USAGE** — customer behavior or usability, never trading performance.

If the class cannot be determined, the claim is blocked.

## Publication checklist

Before customer-facing publication, the owner or delegated reviewer confirms:

1. the claim appears in this registry;
2. its status permits the intended use;
3. linked evidence is current and reproducible;
4. evidence class, date and sample are visible where required;
5. external approval has been obtained when required;
6. draft or historical copy cannot be mistaken for an approved current claim.
