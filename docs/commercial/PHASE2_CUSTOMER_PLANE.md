# Phase 2 — customer plane and entitlement

Status: entered 2026-08-11. Verified baseline, not a completion claim.

Phase 2 of the [commercial action plan](COMMERCIAL_PRODUCT_BASELINE_AND_ACTION_PLAN.md)
builds the customer plane that [ADR-0033](../adr/0033-commercial-product-and-customer-plane.md)
requires: individual identity, entitlement, revocation, isolation and
customer-safe observability, separate from the internal operator Terminal.

## Where the customer plane actually lives

**Not in this repository.** The hosted read API, the license store, the seat
model and the Sidecar/extension client are in `skipp-dev/skipp-live-lab`
(`cloud_worker/`, `sidecar_server/`, `scripts/manage_licenses.py`). This
repository owns the programme, the gates and the claims registry.

Consequence for reviewers: a Phase-2 statement here is only as good as the
evidence in that repository, and every line below names it. Phase 2 therefore
cannot be closed from this repository alone.

## "Built" means merged, not running

Measured 2026-08-12: the hosted `lab-worker` serves a deployment created
**2026-07-24T17:16Z**. It has no GitHub auto-deploy — the record shows a CLI
redeploy with empty watch patterns — so merging does not ship. **38 pull
requests merged after that timestamp are not running**, including the entire
installation-seat model (lab #82–#88), the opaque support reference (#91), the
no-store fix on refusals (#92) and tier entitlement (#95).

This is proven behaviourally, not only from deployment metadata: a refusal from
the live service carries no `Cache-Control: no-store` header, which lab #92
added on 2026-08-07.

Every "built" below therefore means **merged into `skipp-live-lab` main and
covered by tests**, not observable in production. The gap is an operator
action — a deliberate deploy of 19 days of accumulated change — and it belongs
to whoever owns that decision, not to a merge.

Until that deploy happens, the exit gate cannot be evaluated against the
running system at all, which is a stronger statement than any single missing
item in the table below.

## Verified baseline, 2026-08-11

Measured against the seven Phase-2 bullets in the action plan.

| # | Bullet | State | Evidence |
|---|---|---|---|
| 1 | per-user identity | **built** | `cloud_worker/licensing.py`: per-license `sklb_`/`skin_` key pair, SHA-256 at rest, plaintext shown once, view and ingest roles strictly separated |
| 1 | tier entitlement | **in review** | lab PR #95: `pro`/`lite` tiers, one capability table, fail-closed on unknown tiers, mandatory `--tier` at issuance, `set-tier` for cancellation and resumption |
| 2 | session/device revocation | **built** | `revoke`/`rotate`; seat binding is TOFU and globally unique; an open SSE stream re-checks revocation (lab #67), seat ownership (lab #82/#83) and — with PR #95 — the tier, bounded by the 15 s keepalive |
| 2 | audit log | **missing** | no audit table and no administrative event log anywhere in the lab repository; `seat_denials` records customer-side refusals only, not operator actions |
| 3 | customer isolation | **built, not yet gate-proven** | global installation identity is the tenant boundary; capsule data follows the seat (lab #85); refusals are `Cache-Control: no-store` so an intermediary cannot serve one customer's rejection to the next (lab #92) |
| 3 | data minimization | **not assessed** | no inventory of what customer-attributable data the plane retains, and for how long |
| 4 | provider secrets separated from customer clients | **plausible, unproven** | the ingest/view split exists precisely so a TradingView webhook carries no read secret; there is no executable check that customer-facing responses never carry provider credentials |
| 5 | signed Sidecar releases | **partly built** | `scripts/create_sidecar_signing_key.py` (Ed25519), `scripts/build_macos_installer.py` (codesign + notarization); capsule signing is present but optional (`sidecar_server/app.py`: "optional until signature mode is enabled") |
| 5 | rollback proven | **missing** | `docs/CLOUD_WORKER_RUNBOOK.md` documents a worker-rollout rollback (Phase 2 → Phase 1, ≈2 minutes). That is a different object from a customer release rollback, and no rollback drill has been recorded |
| 6 | TTL, `asof`, provenance, freshness, fail-closed | **built** | `/v0/context` carries `asof` and a freshness state with reason codes; missing artifacts fail closed with 503; alerts carry a TTL |
| 7 | security threat model | **missing for this plane** | the only threat model in the lab repository is `phase1/sidecar-native-pairing-threat-model-2026-07-21.md`, scoped to native pairing |
| 7 | independent review | **missing** | bus factor remains one; this is recorded as a commercial gap in the action plan |

## Exit gate

The action plan's gate is four conditions. None of them is currently proven as
a gate, and two of them have no implementation to prove yet.

| Condition | State |
|---|---|
| two test customers cannot cross access boundaries | mechanism built and unit-tested per concern; no single end-to-end two-customer proof runs as a gate |
| revocation is demonstrably prompt | mechanism built; "prompt" now has a measured bound for open streams (≤ 15 s, lab PR #95) but no gate artifact states it |
| secrets never reach the client | unproven |
| rollback is proven | unproven |

Phase 1 exposes `phase1_paper_gate` as a machine-readable artifact. Phase 2
has no equivalent yet; until it does, its state is prose and cannot block a
release automatically.

## Work packages

Ordered so that each one produces evidence rather than intent.

| ID | Work package | State |
|---|---|---|
| P2-1 | Tier entitlement: capability table, fail-closed enforcement at one chokepoint, ingest and open streams included, `set-tier` for the cancellation lifecycle | lab PR #95, CI green, in review |
| P2-2 | Administrative audit log covering issue, revoke, rotate, unbind and tier change — all of them, so the record has no blind operation | open |
| P2-3 | Executable exit-gate suite plus a machine-readable `phase2_customer_plane_gate` artifact, mirroring `phase1_paper_gate` | open |
| P2-4 | Proof that no customer-facing response carries a provider credential, swept over the whole response surface rather than sampled | open |
| P2-5 | Signed Sidecar release with a recorded rollback drill | open |
| P2-6 | Customer-plane threat model and independent review | open, and P2-6 cannot be self-served — it needs a second person |

## Relationship to Phase 1

Phase 2 runs alongside Phase 1's calendar-bound evidence accumulation; the
indicative timeline places the customer plane in weeks 3–8 while paper
evidence accrues. Progress here does not advance `phase1_paper_gate`, and no
Phase-2 completion permits a performance claim: the claims registry and the
evidence classes in ADR-0033 §5 remain in force.
