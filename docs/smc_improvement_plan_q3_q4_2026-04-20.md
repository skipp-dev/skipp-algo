# SMC Improvement Plan Q3/Q4 (2026-04-20) — Referenz-Stub

> **Dieses Dokument hat nie im Repo existiert.** (Stub angelegt 2026-07-27,
> Verdrahtungs-Sweep: `git log --all --diff-filter=A` über die gesamte
> History findet kein Add.) Es wird trotzdem von 14+ Stellen als normative
> Quelle zitiert — teils mit Zeilennummern (`§G2 line 414`, `§G3 line 415`,
> `line 397`), die damit **unverifizierbar** sind: u.a.
> `docs/f2_contextual_promotion_decision_2026-04-21.md`,
> `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md` (nennt es
> „Parent-Dokument"), `.github/workflows/g23-ab-watchdog.yml`,
> `.github/workflows/f2-promotion-gate-daily.yml`,
> `scripts/smc_zone_priority.py`, `scripts/smc_sprt_stop_rule.py`,
> `artifacts/experiments/f2_contextual_promotion.json`.
>
> Das ähnlich benannte `docs/smc_deep_review_2026-04-20_improvement_plan.md`
> ist ein ANDERES Dokument (keine §2.x-Struktur, kein G2/G3).

## Wo die zitierten Inhalte tatsächlich stehen

| Zitat | Reale Quelle |
|---|---|
| §2.4 G3 „30-Tage A/B (SPRT) vor Weight-Change" | `docs/STRATEGY_2026_Q3.md` §G3 + `scripts/smc_sprt_stop_rule.py` (SPRTConfig: p0/p1/α/β) |
| §G2 „line 414" Rollback-Regel (≥2 consecutive losses) | implementiert in `scripts/g23_ab_watchdog.py` (`DEFAULT_ROLLBACK_STREAK`), Status `docs/ab/g23_status.md` |
| §G3 „line 415" Promotion-Gate | `scripts/g23_ab_watchdog.py` + `docs/STRATEGY_2026_Q3.md` §G3 |
| §2.3 F2 Kontext-Kalibrierung | `docs/f2_contextual_promotion_decision_2026-04-21.md` (Gates 1–3) |
| „line 397" (zone-priority) | `scripts/smc_zone_priority.py` Modul-Docstring |

Die dortigen Implementierungen + gepinnten Tests sind die Wahrheit; die
Zeilenzitate auf dieses Dokument sind historisch und nicht auflösbar. Neue
Referenzen bitte direkt auf die realen Quellen.
