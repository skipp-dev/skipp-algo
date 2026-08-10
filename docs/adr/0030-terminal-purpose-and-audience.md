# ADR-0030: The hosted Terminal is the operator's working surface — growth is expected, class change is gated

| Field | Value |
|---|---|
| Status | Accepted — ratified 2026-07-23 by the owner; scope definition written retroactively |
| Date | 2026-07-23 |
| Deciders | @preuss_steffen |
| Related | ADR-0033; `docs/BLOOMBERG_TERMINAL_PLAN.md`; `docs/CISCO_AI_DEFENSE_IMPLEMENTATION.md`; `README.md` §Product Positioning |

## Context

`streamlit_terminal.py` — the Real-Time News Intelligence Dashboard, README core
system #2 — has existed since the Bloomberg-terminal plan and gained its AI
Insights tab on 2026-03-01 (`a6525cbf9`), four and a half months before Cisco AI
Defense. On 2026-07-20 the Cisco rollout required a live runtime with real
provider egress to prove fail-closed enforcement, so the terminal was deployed to
the dedicated private Railway service `skipp-terminal-ai`
(`f454f2bdb`, `1eafb2d1a`, `f34b7b997`) and given an uptime monitor
(`cc9be4352`). It thereby acquired a public URL, a service name, and a monitor.

None of that was a product decision, and no purpose statement was ever written.
A repository-wide and machine-wide search on 2026-07-23 found implementation and
ops documentation only — no scope document, no audience definition, no recorded
discussion. The absence is the problem this ADR closes: a surface with a public
hostname, a monitor, and a steady feature cadence (#3906, #3914, #3916 in a
single week) invites the assumption that it is a product, and that assumption
silently changes what reviewers, agents, and future-you consider in scope.

On 2026-08-10 the owner accepted ADR-0033 and set a commercial-product goal for
the wider SMC system. That later decision does not supersede this Terminal
boundary: the hosted Terminal remains the internal operator plane, while the
commercial product receives a separate customer plane.

## Decision

**The hosted Terminal is the operator's own research and monitoring workbench.
It is single-operator infrastructure, not a product, and it is explicitly
allowed to grow without a new mandate.**

Three parts, in force together:

1. **Purpose.** `skipp-terminal-ai` exists so that the operator can do the work
   — news intelligence, alerting, market monitoring, and decision support —
   from any device, against live data, without a local Python environment. Its
   secondary, historical role is to be the live runtime where AI-egress
   enforcement is proven.

2. **Growth is the default, not the exception.** A working surface that cannot
   change is not a working surface. New tabs, new panels, new providers, new
   AI-assisted views, deeper density, better ergonomics — all of these are
   in-scope by default and need no separate authorization. Nobody has to ask
   whether a terminal improvement "fits the plan"; it does. This ADR must never
   be cited to reject a feature for being out of scope.

3. **What is gated is a change of *class*, not a change of size.** Growth stays
   free as long as the invariants below hold. Crossing one of them means the
   surface has become a different kind of system, and that is a new decision —
   a new ADR — not a pull request.

## The invariants (the only limits)

| # | Invariant | Why it is the boundary |
|---|---|---|
| 1 | **One operator.** Access stays a single shared token (`terminal_auth.py`, `STREAMLIT_AUTH_TOKEN`). No user accounts, roles, tenants, or per-user state. | The moment a second party's identity matters, it is a multi-user system with authn/authz, session isolation, and support obligations. |
| 2 | **No external users.** No signup, no onboarding, no invitations, no marketing entry point, no billing. | A third party relying on it makes availability and correctness a duty to someone else. |
| 3 | **Every first-party LLM exchange stays fail-closed** through the Cisco boundary per `docs/CISCO_AI_DEFENSE_IMPLEMENTATION.md`, including any new AI surface. | This is the property the deployment was built to prove; a new AI panel that bypasses it silently revokes it. |
| 4 | **No auto-execution.** The terminal informs and alerts; it does not place, size, or modify orders. | README §Product Positioning and the compliance posture depend on it. |
| 5 | **Decision support, never advice.** Output stays research and workflow support, not personalized recommendation. | Same posture; it is a regulatory line, not a stylistic one. |
| 6 | **Not a trading-model gate.** Nothing the terminal displays or its AI concludes promotes a PRE-A0/A0 model or substitutes for MLflow and the promotion gates. | Model governance is independent by design. |

Growth that keeps all six is ordinary work. Growth that breaks one is a class
change: write the next ADR, then build.

## Consequences

**Positive**

- The surface has a stated purpose, so scope questions have an answer instead of
  an assumption.
- Feature work on the terminal proceeds without per-change justification —
  the ADR authorizes the cadence rather than throttling it.
- The six invariants are reviewable. An agent or reviewer can check a terminal PR
  against a list instead of guessing at intent.
- The Cisco deployment's real status is recorded: proving ground first, hosted
  workbench second, product never.

**Negative / accepted costs**

- A future decision to serve real users means genuinely re-architecting auth,
  isolation, and support — this ADR does not pre-approve any of it, by design.
- The invariants are documentation, not tests. Invariants 1, 2, 4, and 5 have no
  automated guard; only invariant 3 is machine-enforced
  (`tests/test_ai_defense_egress_guard.py`). Drift on the unenforced ones is
  possible and will be caught by review or not at all.
- The public hostname keeps implying more than the system is. The access proxy
  and token are the only things making that implication harmless.

## Enforcement

- Invariant 3: `tests/test_ai_defense_egress_guard.py` fails when a new LLM
  generation endpoint or provider SDK import appears without a Cisco boundary.
- Invariants 1, 2, 4, 5, 6: review-time only. This ADR is the checklist.

## Evidence

- Terminal predates the Cisco rollout: `a6525cbf9` (2026-03-01, AI Insights tab),
  `3a74e5cfb` (2026-03-01, rebrand from Bloomberg framing).
- Deployment origin: `f454f2bdb` (#3803, fail-closed runtime), `1eafb2d1a`
  (protect Railway ingress), `f34b7b997` (#3812, protected producer),
  `cc9be4352` (#3826, uptime monitoring).
- Runtime posture: `docs/CISCO_AI_DEFENSE_IMPLEMENTATION.md` line 131 —
  one replica, `enforce`, public ingress only via the fail-closed access proxy.
- Single-token access model: `terminal_auth.py`.
- Compliance posture: `README.md` §Product Positioning & Compliance Notes.
