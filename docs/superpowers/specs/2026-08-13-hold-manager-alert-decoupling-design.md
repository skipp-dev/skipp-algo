# Hold Manager shadow — decoupling the alert payload from the source hash

**Date:** 2026-08-13
**Requirement:** R2-SHADOW-CUTOVER
**Status:** design approved by the operator on 2026-08-13; implementation follows.

## Problem

The six live TradingView alerts that feed the Hold Manager shadow receiver each
carry the attested source hash as a **hand-typed string** inside their webhook
message body. `hold_manager_shadow_receiver.py::_validate_contract` compares it:

```python
"sourceSha256": payload.source_sha256 == contract.source_sha256,
```

Any change to `SMC_Hold_Manager.pine` that moves the pin-frozen hash therefore
invalidates all six alert bodies at once. The receiver then reports
`sourceSha256: false` on every event, and the per-session requirement
`sourceHashMustMatch` blocks the observation window until a human retypes six
JSON blobs into the TradingView alert dialog.

This is not hypothetical. The pending BUS label rename (`feat/bus-label-rename`)
changes `input.source` titles and moves the hash, and on 2026-08-13 the operator
stopped mid-way through exactly that manual re-entry.

Measured on 2026-08-13, in this order:

- `pytest tests/test_evaluate_smc_hold_manager_shadow.py` → 15 passed. The
  contract's pin `1761e96aaf5e62412329bb7be10383c36fce4e471b98467f86e1ce63ba360813`
  still equals `sha256(freeze_library_pin(SMC_Hold_Manager.pine))`, so the 20+
  library-refresh commits since 2026-07-28 did **not** move it. `pin_frozen`
  does its job; only semantic edits move the hash.
- The alerts already exist and are already correct
  (`smc_hold_manager_shadow_alerts_2026-07-28.json`, `alertsCreated: true`).
  What is missing is not their creation.
- The R2.4 replay matrix does **not** depend on the alert mechanism. It counts
  Pine edges in a private fixture and records
  `serverAlertDelivery: {status: "pending"}` explicitly. Switching mechanisms
  does not invalidate it.
- Exactly two line-pinned guards name the Hold Manager's `alertcondition()`
  calls: `tests/test_pine_alertcondition_and_declaration_pin.py` (`6`) and
  `tests/test_smc_r1_rollout_contract.py`.

The defect class is a second copy of a fact the repository already computes —
the same class removed from `openExistingScript` earlier the same day, where a
saved-script name was doubling as a Pine declaration title.

## Non-goals

- **No automation that creates or edits TradingView alerts.** Live alerts fire
  into a production receiver; automating their mutation is more risk than the
  toil it removes. The single alert is created once by hand.
- **No change to the observation-window rules**, the evaluator's pass criteria,
  or the rollback drill requirements.
- **No publication.** The saved script stays private
  (`externalPublicationAllowed: false`).

## Design

### 1. Payload and source binding

A Pine script cannot state its own hash — the value is self-referential. The
identity in the payload therefore becomes a Pine-nameable stand-in:

- `SMC_Hold_Manager.pine` carries `HM_SHADOW_BUILD`, a plain integer constant.
- Pine builds the complete JSON at fire time inside `alert()`.
- The wire field `sourceSha256` is replaced by `sourceBuild` (integer).

**The hash does not leave the system; it is resolved server-side.** The receiver
validates `payload.source_build == contract.source_build` and then writes
`contract.source_sha256` into the ledger. Consequences:

- The `hold_manager_shadow_events` table is unchanged — no migration.
- `_event_id` keeps its exact composition, so duplicate detection is unchanged.
  Substituting `contract.source_sha256` for `payload.source_sha256` there is
  behaviour-preserving, because validation has already proven them equivalent.
- The persisted truth stays a hash, not a build number.

**Strictness is preserved.** A stale script deployed on TradingView emits the
old build number and is rejected — the same drift detection as today. The only
thing that changes is who writes the value: previously a human into six text
fields, now the source itself.

**Uniqueness needs history.** "Build N belongs to hash X" cannot be checked from
a single state: two different sources could carry the same number if someone
forgets to increment. The contract therefore gains

```json
"source": { "build": 1, "...": "..." },
"buildHistory": [
  { "build": 1, "sha256": "1761e96aaf5e62412329bb7be10383c36fce4e471b98467f86e1ce63ba360813" }
]
```

and a test holds three things together, all by computing rather than reading:

1. `contract.source.sha256 == sha256(freeze_library_pin(SMC_Hold_Manager.pine))`
   — already exists and is green.
2. `contract.source.build ==` the integer parsed out of the Pine constant.
3. No build appears in `buildHistory` with two different hashes, and the current
   `(build, sha256)` pair is present.

Check 3 is the load-bearing one: it turns "hash changed, build not incremented"
into a red test instead of a silent mis-binding. Because the payload comes from
the source, incrementing the build costs **zero** operator actions on
TradingView.

`buildHistory` starts at build 1 = the currently attested hash, which is the
source TradingView runs today. Adding the constant and the `alert()` calls is
itself a semantic edit, so the switched-over source is build 2. A later change
such as the BUS label rename becomes build 3 and costs no operator action.

### 2. Transport and receiver

**Route:** `POST /{token}/tradingview/hold-manager-shadow`, token first.

This ordering is load-bearing, not cosmetic. `main.py` runs uvicorn with
`access_log=False` and the comment *"/{token}/… routes: token must never reach
stdout/Railway logs (README §Security)"*. A route only inherits that protection
in the `/{token}/…` form. The daemon already authenticates
`GET /{token}/smc_live` this way, so the URL-borne token is the established
pattern in this service rather than a new exposure. There is no collision: the
existing route is a two-segment `GET`.

**Authentication moves ahead of parsing.** Today the body is parsed and then
authenticated. Reversing it means an unauthenticated caller no longer reaches
the pydantic parser — a small hardening that falls out of the change.

**`authToken` leaves the model.** Because `HoldManagerShadowAlert` sets
`extra="forbid"`, the receiver then rejects every old-shaped payload
automatically. The cutover is fail-closed without extra code.

**Six alerts become one.** The single alert uses the condition *"Any alert()
function call"*; the channel travels in the payload. `_load_contract` keeps its
`channels != _CHANNELS` check and the per-channel evaluation is untouched.

**The six `alertcondition()` calls stay in the Pine.** They only fire when an
alert is configured against them, and after the cutover none is — they lie
dormant. Keeping them buys three things:

- the line-pinned guard `"SMC_Hold_Manager.pine": 6` stays green, so no guard
  churn and no pin set to a vacuous zero;
- the file stays inside the population of `test_pine_alert_bar_close_gate.py`
  instead of silently dropping out of it;
- rollback is "recreate six alerts" rather than "revert the Pine".

A new test holds both mechanisms on the same six channels so they cannot drift
apart. A second new guard requires every `alert(` call in root-surface Pine to
be bar-close gated, and asserts its own population is non-empty so it cannot
pass by inspecting nothing.

### 3. Read-only alert readback

A Playwright probe opens the layout, reads the alert list, and asserts: exactly
one alert on `SMC Hold Manager R2.4 Validation`, enabled, condition *"Any
alert() function call"*, webhook configured.

**It must not record the webhook URL** — that URL contains the token. The
evidence records `webhookConfigured: true` and nothing more, and a test over the
artifact rejects any string that looks like a secret.

The evidence replaces the contract's current basis for alert existence, which is
the sentence *"Operator re-confirmed on 2026-07-29 that six correctly configured
alerts exist live"* — a verbal assurance standing in for a measurement.

Two honest caveats. First, the probe consumes the single `tradingview-session`
queue slot; against the measured 1.75× overload it is an on-demand probe and
must never become a cron. Second, whether the alert list is machine-readable at
all is unknown. The 2026-07-28 evidence asserts it is *"not machine-verifiable
from this repository"*, but no probe was ever run to establish that. The probe
answers the question; this design does not presume the answer.

The readback ships as its own pull request. It is independent of the decoupling
and must not hold it up.

### 4. Cutover, rollback, verification

**The switch is the deploy, not the merge**, and that fact decides the shape of
the rollout. Two measurements from 2026-08-13:

- `deploy-live-overlay-daemon.yml` fires on every push to `main` whose paths
  touch `services/live_overlay_daemon/**`. A receiver change therefore goes
  live the moment it merges.
- `config.hold_manager_shadow_contract_path()` resolves under `_REPO_ROOT`, so
  the contract is baked into the image. A contract-only or Pine-only change
  does **not** reach production until the daemon is redeployed.

Together these mean a receiver pull request must be safe to deploy unattended,
while Pine and contract changes can land early and stay dormant in production.
The work therefore splits into three deliberately safe steps.

**Step 1 — receiver and contract (landable immediately).** The new
`/{token}/…` route and the build-based model are added *alongside* the existing
route and model, which are left untouched. The contract gains `source.build: 1`
and a `buildHistory` whose single entry is the currently attested hash, so the
pinned hash does not move. The auto-deploy on merge is then a no-op for the six
live alerts: they keep hitting the legacy route with the legacy shape and the
unchanged hash. The new route is dormant because nothing sends to it yet.

**Step 2 — Pine and build advance (waits for the rollout to be possible).**
`HM_SHADOW_BUILD` and the six `alert()` calls move the source hash, so the
contract advances to build 2. This pull request touches no `services/` path and
therefore triggers no deploy: production keeps validating against the baked
build-1 contract, and the six live alerts keep working. The cutover is then a
deliberate sequence in one sitting — roll the new Pine out to TradingView,
create the one new alert, delete the six old ones, dispatch the daemon deploy so
production picks up the build-2 contract, run the readback.

**Step 3 — remove the legacy route** once the readback has proven the cutover.
A guard ties the removal to the contract state rather than to a date, so it
cannot be forgotten and cannot fire on a borrowed clock.

**Rollback.** Roll the receiver back, set `ACCEPTING=0`, recreate the six alerts
from `smc_hold_manager_shadow_alert_templates.json`. That template file is
therefore **not deleted** — it is marked superseded. Dated evidence artifacts are
never rewritten in this repository.

**The load-bearing test.** A Python test parses the six `alert()` calls out of
the Pine, renders the JSON template against a fixture, and validates the result
with the receiver's real `HoldManagerShadowAlert` model. The schema then exists
exactly once: if Pine and receiver drift apart, the test is red. A hand-written
copy of the expected shape would be the very defect this design removes.

Alongside it: the build-history guard from §1; receiver unit tests for unknown
build → 409, old-shaped payload → 400 via `extra="forbid"`, wrong path token →
404, valid request → 200 with the contract hash in the ledger; and a mutation
probe for every new guard, because a guard that has not been made to fail has
not been shown to check anything.

**What is not provable offline**, and is not claimed to be: that TradingView's
`alert()` really emits this JSON with the escaping and `str.format_time` output
the model expects. `scripts/sync_tradingview_libraries.py` validates Pine syntax
and imports locally, which shrinks the risk to TradingView-side semantics but
does not eliminate it. The single clean proof is the private fixture script
`SMC Hold Manager R2.4 Fixture TEST ONLY`, which already exists: it carries the
same `alert()` call and fires once into the receiver before the real script is
switched over.

## Known blocker

Rolling the new Pine out to TradingView requires the consumer rollout run, which
currently refuses with *"Library publish drift: the manifest says 230,
TradingView lists 231"*. `origin/main` pins 230 and no refresh PR for 231 is
open. Bumping the pin by hand would invent a value the refresh workflow must
produce.

Everything before that step — Pine, receiver, contract, and all guards — is
buildable immediately, without a browser and without the TradingView queue slot.
