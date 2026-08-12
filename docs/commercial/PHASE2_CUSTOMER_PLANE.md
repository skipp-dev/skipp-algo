# Phase 2 — customer plane and entitlement

Status: entered 2026-08-11. Exit gate **PASSED** 2026-08-12 — which closes the
four gate conditions, not the phase: P2-5's signed release and P2-6's
independent review are still open, and the latter cannot be closed from inside.

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

**Closed 2026-08-12.** The deploy happened the same day, in two steps: 09:48Z
(through tier entitlement) and 11:51Z (through the audit log). The paragraphs
above stand as written — they record what was true when measured, and the
measurement is the reason the deploy happened. Verified afterwards from inside
the running container rather than from deployment metadata: `licenses` carries
`tier` for all three records, and `license_events` answers queries. The
19-day gap is the reason "built" and "running" are separate columns here and
will stay separate.

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

The action plan's gate is four conditions. As of 2026-08-11 none of them was
proven as a gate, and two had no implementation to prove yet. As of
2026-08-12 the gate exists, runs in CI, and reports **PASSED**.

`skipp-live-lab/scripts/phase2_gate.py` emits
`skipp-phase2-customer-plane-gate/1`, the counterpart to `phase1_paper_gate`.
Its verdict is not prose: an evidence-backed condition that falls breaks the
run.

| Condition | State 2026-08-11 | State 2026-08-12 | Evidence in `skipp-live-lab` |
|---|---|---|---|
| two test customers cannot cross access boundaries | mechanism built, no end-to-end gate | **satisfied** | 9 tests, named individually in the gate's selection |
| revocation is demonstrably prompt | bound measured, not stated by any artifact | **satisfied** | 3 tests; the ≤ 15 s keepalive bound is recorded in the artifact's notes |
| secrets never reach the client | unproven | **satisfied** | 5 tests; both populations discovered, not maintained — secrets from source, routes from the running app |
| rollback is proven | unproven | **satisfied** | `artifacts/phase2_rollback_drill.json`, executed against production 2026-08-12T13:23Z |

Two design decisions are what make it a gate rather than a scoreboard. An
empty test selection counts as **false**: the dangerous failure of a gate is
not blocking too often, it is passing because it stopped measuring, and the
runner reports "no tests collected" with an exit code that is easy to read as
success. And the rollback record is **parsed**, not counted — `touch` at the
right path would otherwise be a valid proof of a rollback drill.

### The rollback drill, 2026-08-12

Performed on the live `lab-worker`: back to the pre-audit-log deployment, then
forward again. 16–17 s per direction from mutation to observed code change; the
customer refusal path answered in all 30 probe rounds; exactly one health
request per switch ran into the timeout, so the switch is not seamless and the
record says so.

Three findings that only a real drill produces:

- **The Railway CLI cannot roll back.** `railway redeploy` re-runs the *latest*
  deployment — during an incident, the broken one. The path back is the
  dashboard button or the `deploymentRollback` mutation behind it, now in the
  lab runbook.
- **A rollback takes back code, not data.** It was clean only because both
  migrations were additive. A dropping or renaming migration makes rollback
  unsafe; that is now a constraint on future migrations rather than luck.
- **The version marker nearly lied.** Read through
  `railway ssh -- sh -lc '<cmd>'`, every marker came back `0` because that form
  silently mangles its arguments — it would have shown an intact deployment as
  stale. The direct argv form is mandatory.

## Work packages

Ordered so that each one produces evidence rather than intent.

| ID | Work package | State |
|---|---|---|
| P2-1 | Tier entitlement: capability table, fail-closed enforcement at one chokepoint, ingest and open streams included, `set-tier` for the cancellation lifecycle | **done** — lab #95, merged and deployed 2026-08-12 09:48Z |
| P2-2 | Administrative audit log covering issue, revoke, rotate, unbind and tier change — all of them, so the record has no blind operation | **done** — lab #96, merged and deployed 2026-08-12 11:51Z |
| P2-3 | Executable exit-gate suite plus a machine-readable `phase2_customer_plane_gate` artifact, mirroring `phase1_paper_gate` | **done** — lab #97, runs in CI with `--fail-on-regression` |
| P2-4 | Proof that no customer-facing response carries a provider credential, swept over the whole response surface rather than sampled | **done** — lab #97; the sweep caught its own vacuity first (an injected leak did not fail it until the one route that touches a secret was forced down its error path) |
| P2-5 | Signed Sidecar release with a recorded rollback drill | **rollback drill done** — lab #97, executed against production. The *signed release* half is untouched and remains open |
| P2-6 | Customer-plane threat model and independent review | **half done** — the threat model is written (`docs/THREAT_MODEL_CUSTOMER_PLANE.md`); the independent review cannot be self-served and stays open |

### What P2-6's open half actually blocks

The threat model's useful section is what is *not* defended, and the entry at
the top of it is the reason the other half cannot be closed from inside: the
operator is unbounded and unwitnessed, the audit log's `actor` is unverified,
and at bus factor one the author of a control is also its only reviewer. The
document states this about itself rather than around it.

Its own follow-on work, ordered by consequence rather than effort: drill a
restore of the `/data` volume (the one remaining place where a mistake is
irreversible — code rollback is proven, data is not); make "migrations must be
additive" a repository rule, or the rollback proof lapses silently at the next
migration; notify a customer when a new installation binds, so TOFU becomes
"first wins, and she finds out"; mirror the audit log beyond the operator's
reach; and rotate one provider secret once, so the cost of doing it is known.

## Relationship to Phase 1

Phase 2 runs alongside Phase 1's calendar-bound evidence accumulation; the
indicative timeline places the customer plane in weeks 3–8 while paper
evidence accrues. Progress here does not advance `phase1_paper_gate`, and no
Phase-2 completion permits a performance claim: the claims registry and the
evidence classes in ADR-0033 §5 remain in force.
