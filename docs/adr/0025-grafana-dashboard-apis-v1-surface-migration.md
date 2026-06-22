# ADR-0025: Publish the live-overlay dashboard via the Grafana App Platform `dashboard.grafana.app/v1` API surface (classic schema kept inside `spec`)

| Field   | Value |
|---------|-------|
| Status  | Accepted |
| Date    | 2026-06-22 |
| Refs    | `scripts/publish_overlay_dashboard.py`; `services/live_overlay_daemon/infra/grafana/dashboard.json`; `tests/test_publish_overlay_dashboard.py`; `tests/test_live_overlay_dashboard_contract.py`; ADR-0009 (pin-ledger consolidation); Grafana HTTP API — App Platform (`/apis`) |

---

## Context

The live-overlay Grafana dashboard for the `live_overlay` daemon is stored
in-repo at `services/live_overlay_daemon/infra/grafana/dashboard.json` and
published to Grafana Cloud by `scripts/publish_overlay_dashboard.py`.

The publish path had drifted into an unclear "v1 vs v2" state. The root cause
was that **"v2" conflates two independent axes**, which had not been separated
before this decision:

| Axis | "legacy / v1" | "new / v2" |
|------|---------------|------------|
| **API surface** | `POST /api/dashboards/db` | `POST/PUT /apis/dashboard.grafana.app/v1/namespaces/<ns>/dashboards[/<uid>]` |
| **Dashboard schema** | top-level `panels` + `schemaVersion` | `spec.elements` + layout kinds (`v2alpha1`) |

Verified facts (Grafana official docs, 2026-06-22):

- The new App Platform APIs are available in Grafana 12+; the legacy
  `/api/dashboards/*` endpoints are **deprecated in Grafana 13**, **not yet
  disabled**, with removal planned for a future major release.
- The documented `dashboard.grafana.app/v1` resource still carries the
  **classic dashboard model unchanged inside `spec`** (the example payload
  contains top-level `panels` and `schemaVersion`). The new element/layout
  model is a separate, still-alpha (`v2alpha1`) schema.

The prior code targeted `POST /api/v1/dashboards` for its "v2" path — an
endpoint that is **not** the documented App Platform surface — and its
docstrings claimed the repo dashboard was maintained in "v2 shape", which was
false (the repo file is, and remains, classic `panels`).

The original choice to keep emitting the legacy shape was a status-quo default,
not a researched decision. This ADR records the deliberate replacement.

---

## Problem

We want the GitOps / operational benefits of the App Platform API —
`resourceVersion`/`generation` change detection, optimistic-concurrency
`409 Conflict` instead of blind overwrite, folder/message annotations, and
alignment with the post-Grafana-13 deprecation path — **without** paying for a
risky rewrite of every panel into the alpha `v2alpha1` element model.

Options considered:

| Option | API surface | Schema | Verdict |
|--------|-------------|--------|---------|
| **A** Status quo | `/api/dashboards/db` | classic | Rejected: no GitOps benefit; rides the deprecated surface. |
| **B** (chosen) | `/apis/dashboard.grafana.app/v1` | **classic inside `spec`** | Low risk, full GitOps benefit, panel JSON reused verbatim. |
| **C** Full v2 | `/apis/...` | `v2alpha1` `elements` | Rejected for now: alpha API + full panel rewrite for an operational board; high churn, no runtime benefit. |

Note: the App Platform migration delivers **no** runtime/refresh-rate benefit
(`refresh=30s`, Prometheus query load, panel rendering are unaffected). Those
are tracked separately and are out of scope for this ADR.

---

## Decision

**Publish through the Grafana App Platform `dashboard.grafana.app/v1` API
surface, keeping the classic dashboard model unchanged inside `spec`.**

Concretely, `scripts/publish_overlay_dashboard.py`:

1. Reads the in-repo classic `dashboard.json` (top-level `uid` / `panels` /
   `schemaVersion`) — **the repo file format does not change**.
2. Wraps it into the App Platform resource envelope at publish time (a
   `Dashboard` resource whose `spec` is the unchanged classic dashboard):

   ```json
   {
     "apiVersion": "dashboard.grafana.app/v1",
     "kind": "Dashboard",
     "metadata": {
       "name": "<uid>",
       "annotations": {"grafana.app/folder": "<folderUid>", "grafana.app/message": "<msg>"}
     },
     "spec": "<classic dashboard JSON>"
   }
   ```
3. Performs an **upsert with optimistic concurrency**: `GET` the existing
   resource to read `metadata.resourceVersion`; `POST` to the collection when
   absent (create) or `PUT` to `.../dashboards/<uid>` echoing the
   `resourceVersion` when present (update). A concurrent UI edit therefore
   surfaces as **HTTP 409** instead of being silently overwritten.
4. Falls back to legacy `POST /api/dashboards/db` only when the App Platform
   API is unavailable on the stack (`/apis` returns 404), preserving
   compatibility with older stacks.
5. Targets namespace `default` by default (on-prem / org 1); Grafana Cloud
   uses `stacks-<stackId>`, overridable via `--namespace`. The namespace is
   **surfaced in `--dry-run`** rather than guessed silently.
6. Provides `--dry-run` (read-only summary: namespace, uid, create/update
   endpoints, method, panel count) and `--dry-run-full` (full payload) so a
   write is always previewable before egress.

---

## Consequences

**Positive**

- Full GitOps surface: change detection (`resourceVersion`/`generation`),
  optimistic-concurrency conflict protection, folder/message annotations,
  audit metadata (`createdBy`/`updatedBy`/`creationTimestamp`).
- Forward-compatible with the Grafana-13 legacy-API deprecation.
- **Zero panel churn** — the classic `dashboard.json` is reused verbatim as
  `spec`; no migration to the alpha element model.
- The publish is always previewable (`--dry-run` / `--dry-run-full`) and
  degrades gracefully to the legacy endpoint on older stacks.

**Negative / trade-offs**

- The single outbound `urllib.request.Request` in `_request_json` now carries
  a **dynamic** method (`GET`/`POST`/`PUT`), so it is no longer detectable by
  the literal-`method="POST"` shape of the HTTP-POST-egress ledger. Its egress
  edge is instead pinned by the single `urlopen` site in the urllib-urlopen
  ledger (`pin_registry.toml`) and `tests/test_http_client_discipline.py`
  (`scripts/publish_overlay_dashboard.py:287`). The POST-egress ledger entry
  for this file was removed with an inline justification rather than silently
  dropped.
- Pin ledgers for the keychain `subprocess.run` and the `urllib` call sites
  shifted line numbers and were re-pinned (ADR-0009 procedure; no
  `--no-verify`).
- The App Platform `namespace` must be known per stack; an incorrect namespace
  yields a 404 (and the legacy fallback). Mitigated by `--namespace` +
  dry-run surfacing.

**Not addressed here**

- Dashboard runtime performance (`refresh`, PromQL load, panel count) — a
  separate optimization track.
- Migration to the `v2alpha1` element schema (Option C) — deferred until the
  schema leaves alpha and a layout change is actually required.

---

## Related

- ADR-0009 — pin-ledger consolidation (`pin_registry.toml` + inline ledgers);
  the line/shape re-pinning in this change follows its procedure.
