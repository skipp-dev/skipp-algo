# ADR-0004: `@resilient` vs. `@circuit_breaker` — Failure-Recovery Pattern Boundary

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Status      | Proposed                                           |
| Date        | 2026-04-24                                         |
| Deciders    | skipp-dev                                          |
| Supersedes  | (none)                                             |
| Related     | [`smc_core/resilient.py`](../../smc_core/resilient.py), [`tests/test_smc_core_resilient.py`](../../tests/test_smc_core_resilient.py), [`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](../TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md) (E-3) |

## Context

The E-3 backlog item ("Strategischer Refactor `@resilient`-Decorator,
eigenes Quartal") landed the
[`smc_core.resilient`](../../smc_core/resilient.py) decorator (PR #106)
plus per-adapter migrations (`scripts/smc_fmp_client._get` in PR #108,
`terminal_fmp_insights._call_openai_chat` in PR #112).

Each subsequent migration attempt revealed adapters that **look like
retry loops but aren't**:

- [`terminal_finnhub.py`](../../terminal_finnhub.py#L43) carries a
  module-level `_social_sentiment_blocked` flag (permanent-disable on
  403) plus `_consecutive_429_count` driving an exponential
  `_rate_limit_backoff_until` skip-window across calls.
- [`terminal_technicals.py`](../../terminal_technicals.py#L186) maintains
  `_tv_cooldown_until`, `_tv_consecutive_429s`, and
  `_TV_POST_429_WINDOW` — a 2 min → 15 min escalating cooldown plus a
  5 min post-cooldown cautious-spacing window.
- [`databento_client.py`](../../databento_client.py)
  `_databento_get_range_with_retry` filters retryability by **error-
  message substrings** rather than exception classes.

Each of these was deferred from `@resilient` migration with an inline
`NOTE:` referencing a future `@circuit_breaker` companion. This ADR
draws the boundary explicitly so future contributors know which
pattern to reach for, and pre-commits to the contract the companion
will need.

## Decision drivers

1. **Caller-state vs. cross-call state.** Pure retry loops are
   stateless across calls; circuit-breakers carry shared state
   (consecutive-failure counter, deadline, half-open window).
2. **Blocking vs. non-blocking.** A retry sleeps the calling thread.
   A circuit-breaker raises *immediately* when the circuit is open —
   essential for UI threads (Streamlit) and shared event loops.
3. **Predicate shape.** `@resilient(exceptions=(...))` only accepts
   exception classes. Real-world adapters need predicates over status
   codes, error messages, or even URL paths (Finnhub permanent-disables
   the `/social-sentiment` endpoint specifically while keeping the
   rest of the API live).
4. **Recovery semantics.** Retry recovers a single call; circuit-
   breaker recovers an entire **endpoint or provider** for a window.

## Pattern boundary

| Concern                        | `@resilient` (Inner Failure Recovery) | `@circuit_breaker` (Outer Outage Protection) |
|--------------------------------|----------------------------------------|----------------------------------------------|
| Scope                          | Single call                            | Endpoint / provider                          |
| State                          | None across calls                      | Module-level (counter, deadline, flag)       |
| On classified failure          | Sleep + retry                          | Raise immediately or skip                    |
| Predicate                      | Exception class                        | Status code / message / path                 |
| Caller blocking                | Yes (`time.sleep`)                     | No (fail-fast)                               |
| Recovery                       | Per-call retry                         | Cooldown window + half-open probe            |
| UI-thread safe                 | No                                     | Yes                                          |
| Config knobs                   | `retries`, `base_delay`, `max_delay`   | `cooldown_base`, `cooldown_max`, `consecutive_failure_threshold`, `permanent_disable_predicate` |

## Decision

**Adopt the boundary above.** `@resilient` covers transient I/O errors
on a single call (timeouts, jitter-able 5xx). `@circuit_breaker`
covers cross-call provider state (rate-limit windows, premium-only
endpoints, sustained outages).

Migration triage rules:

1. If an adapter's failure handling reads or mutates **module-level
   state** between calls → it is a circuit-breaker. Do **not** force
   it into `@resilient`.
2. If retryability is decided by **anything other than the exception
   class** (HTTP status code, error-message substring, request path)
   → it is at least a partial circuit-breaker. Migrate the
   exception-class part to `@resilient` only if separable.
3. If the adapter runs on the Streamlit UI thread → blocking
   `time.sleep` is forbidden; use circuit-breaker fail-fast.

## Inventory

The following adapters fail rule 1 or 2 and **stay opted out** of
`@resilient` until a `@circuit_breaker` companion ships:

| Adapter | Pattern | Blocker |
|---|---|---|
| [`terminal_finnhub._get`](../../terminal_finnhub.py#L172) | 403 permanent-disable on `/social-sentiment` + 429 skip-window | path-aware predicate + module-state |
| [`terminal_technicals._tv_throttle`](../../terminal_technicals.py#L256) | 2→15 min escalating cooldown + post-cooldown cautious spacing | module-state, raises in throttle (not in adapter) |
| [`databento_client._databento_get_range_with_retry`](../../databento_client.py) | message-substring retryability filter | predicate shape mismatch (also: TLS-cert side-effect per attempt, duplicated function) |

These three are **the** circuit-breaker target list.

### Out-of-scope: not a recovery decorator at all

For completeness, [`scripts/execute_ibkr_watchlist._attempt_ibkr_reconnect`](../../scripts/execute_ibkr_watchlist.py#L207)
*looks* like a retry loop but is intentionally not a `@resilient`
candidate either:

- The loop produces a structured **audit log** (`attempts: list[dict]`)
  that the calling workflow surfaces in the run report. The retry is a
  **side product** of the audit, not the goal.
- Failure semantics are recorded — never raised — and the function
  always returns a result envelope (`status: "reconnected" | "failed" | "disabled"`).
- `time_module.sleep` is patched out by tests via the module-level
  rebinding (`time_module = time`).

Forcing this through `@resilient` would lose the audit trail, change
the no-raise contract, and break the test patch point. **No
migration intended for any decorator.** Documenting here so the next
audit doesn't re-discover the question.

## Consequences

### What this enables

- A future `smc_core.circuit_breaker` module can ship with a
  pre-validated adapter inventory and a known API contract:

  ```python
  # Sketch — not committed.
  @circuit_breaker(
      cooldown_base=120.0,
      cooldown_max=900.0,
      should_open=lambda exc: ...,
      permanent_disable=lambda exc, path: ...,
      key_fn=lambda *a, **kw: kw.get("path", "default"),
  )
  def _get(path: str, params: dict) -> dict: ...
  ```

- Each migration becomes a mechanical translation rather than a
  re-discovery of which state needs to move where.

- `tests/test_smc_core_resilient.py` already pins the contract for
  `@resilient`; the companion test suite mirrors it for the breaker.

### What stays out of scope

- This ADR does **not** ship the companion decorator.
- It does **not** require the three opted-out adapters to migrate
  on a fixed timeline; the breaker can ship and adapters can adopt
  it independently.
- It does **not** change the existing `@resilient` API contract.

### What must follow

- Inline `NOTE:` blocks in the three adapters get a back-pointer to
  this ADR (separate small PR or amended in the breaker-implementation
  PR).
- The next E-3 follow-up issue / backlog item is "Implement
  `smc_core.circuit_breaker`" with this ADR as the spec input.

## Verification on adoption

The implementation PR for `smc_core.circuit_breaker` must show:

- A contract test suite in the same shape as
  `tests/test_smc_core_resilient.py` (initial-state, transition to
  open, half-open probe, permanent-disable, key-isolation).
- One concrete adapter migration (Finnhub recommended, smallest
  state surface) with a regression test that exercises the
  permanent-disable path on a 403 to `/social-sentiment`.
- An updated **Inventory** table here marking the migrated adapter
  as ✅.
