# C7/T8 — Track-Record Dashboard Deployment

**Status:** local + container only (auth out of scope for C7).

## Local

```bash
./scripts/run_dashboard.sh
# → http://localhost:8501
```

Honours `SKIPP_DASHBOARD_CACHE_DIR` (default: `./cache`) and
`SKIPP_DASHBOARD_PORT` (default: `8501`).

## Container

```bash
./scripts/run_dashboard.sh --container
```

Builds `skipp-dashboard:latest` from `Dockerfile.dashboard` and runs
it with `cache/` mounted read-only.  Image only contains the
dashboard surface (`terminal_tabs/`, `streamlit_terminal.py`,
`scripts/build_dashboard_payload.py`) — the trader-terminal stack
keeps using the root `Dockerfile`.

## Production deploy — explicitly out of scope for C7

Sprint plan §T8 defers AuthN/AuthZ to a follow-up.  Until then,
front the container with an SSO-aware reverse proxy
(Azure AD / Cloudflare Access / Google IAP).  Do **not** expose
port 8501 directly to the public internet because:

* Streamlit has no built-in auth.
* The dashboard reads from `cache/` which contains internal
  variant identifiers that should not leak.

## Healthcheck

The container exposes `/_stcore/health`.  The Dockerfile contains
a `HEALTHCHECK` clause; orchestrators (Docker Compose, Kubernetes,
Azure Container Apps) inherit it automatically.
