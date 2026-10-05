"""Restore a sufficiently deep Databento production export for deep-history consumers.

Pulls one of today's ``smc-databento-production-export-<RUN_DATE>-*`` GitHub Actions
artifact from the ``main`` branch (or a recent same-prefix fallback), verifies
that its manifest covers enough trading days for long-horizon structure
families, and extracts it into ``artifacts/smc_microstructure_exports/``. Survives
transient zip corruption by retrying each candidate up to 3 times before
falling back to the next eligible artifact. Only artifacts produced by the
canonical sharded producer workflow are eligible; emergency/manual artifacts
from the deprecated monolith use the same legacy prefix but must not feed
deep-history consumers such as the rolling benchmark or library refresh.

Replaces the inline heredoc previously embedded in
``.github/workflows/smc-measurement-benchmark-rolling.yml`` (F-V8-D4,
2026-05-16). Behavior is bit-identical; only the location changed so the
logic can be linted / type-checked / unit-tested.

Required env vars:
  GITHUB_REPOSITORY   – e.g. ``skipp-dev/skipp-algo``
  GH_TOKEN            – token with ``actions:read`` on the repo
  RUN_DATE            – today's UTC date as ``YYYY-MM-DD``
  GITHUB_OUTPUT       – path to the step-outputs file (provided by Actions)

Step outputs written:
  found_artifact   = ``true`` | ``false``
  artifact_name    = name of the restored artifact (only when found)
  artifact_run_id  = producer run id (only when found)
  artifact_mode    = ``today`` | ``fallback`` (only when found)
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

_PREFIX = "smc-databento-production-export-"
_CANONICAL_WORKFLOW_FILE = "smc-databento-production-export-sharded.yml"
# The producer is addressed by this FILE (see _list_producer_run_ids), not by name.
_ROOT = Path("artifacts/smc_microstructure_exports")
_USER_AGENT = "smc-measurement-benchmark-rolling"
_API_VERSION = "2022-11-28"


def _emit(output_path: Path, key: str, value: str) -> None:
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def _api_get_json(token: str, path: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_zip(token: str, repo: str, artifact_id: int) -> bytes:
    """Download an artifact zip, stripping Authorization on cross-host redirect.

    GitHub's ``/artifacts/{id}/zip`` returns a 302 to Azure Blob Storage.
    ``urllib.request`` forwards all headers on redirect — the Azure endpoint
    rejects the GitHub Bearer token with 401.  We use a custom redirect
    handler that strips ``Authorization`` when the redirect targets a
    different host (the standard ``gh`` CLI does the same).
    """

    class _StripAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
        """Drop Authorization header when redirected to a different host."""

        def redirect_request(
            self,
            req: urllib.request.Request,
            fp,
            code: int,
            msg: str,
            headers,
            newurl: str,
        ) -> urllib.request.Request | None:
            new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new_req is None:
                return None
            # Strip auth when crossing to a different host (e.g. Azure Blob).
            orig_host = urlparse(req.full_url).hostname
            dest_host = urlparse(newurl).hostname
            if orig_host != dest_host:
                new_req.remove_header("Authorization")
            return new_req

    opener = urllib.request.build_opener(_StripAuthRedirectHandler)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    with opener.open(req, timeout=120) as resp:
        return resp.read()


# Candidate discovery (2026-10-01): ask the PRODUCER for its runs, then each run
# for its artifacts. The previous implementation paged the repo-wide artifact
# index (``/actions/artifacts?per_page=100&page=N``, up to 30 pages) and
# filtered by name prefix. Since 2026-09-25 ~16:00 UTC that index answers
# HTTP 500 for this repo (reproduced 2026-10-01: per_page=30/50/100 -> 500,
# per_page=1 -> 200, ``?name=<exact>`` -> 200). From then on the rolling
# benchmark (every evening run) and smc-library-refresh (every run) died in
# their restore step, before looking at a single bundle; the last good restore
# is run 36055941993 (2026-09-24). The run-scoped route does not touch that index, needs no
# depth heuristic ("hundreds of artifacts per day", see 2026-07-13), and makes
# the canonical-producer filter structural: only runs of
# ``_CANONICAL_WORKFLOW_FILE`` are ever listed, so a deprecated-monolith
# artifact with the same legacy prefix cannot become a candidate.
_MAX_RUN_PAGES = 5
_MAX_CANDIDATE_AGE_DAYS = 14
_MIN_TRADE_DAYS = 15


def _horizon_iso(run_date: str) -> str:
    """Oldest acceptable artifact ``created_at`` (ISO-Z) for the fallback."""
    day = date.fromisoformat(run_date) - timedelta(days=_MAX_CANDIDATE_AGE_DAYS)
    return f"{day.isoformat()}T00:00:00Z"


def _list_producer_run_ids(token: str, repo: str, horizon_iso: str) -> list[int]:
    """Ids of canonical producer runs on ``main`` created since the horizon.

    A failure here is NOT swallowed: without the run list there is nothing to
    restore from, and the honest outcome is the red step with the traceback.
    """
    since = horizon_iso[:10]
    run_ids: list[int] = []
    for page in range(1, _MAX_RUN_PAGES + 1):
        payload = _api_get_json(
            token,
            f"repos/{repo}/actions/workflows/{_CANONICAL_WORKFLOW_FILE}/runs"
            f"?branch=main&created=%3E%3D{since}&per_page=100&page={page}",
        )
        batch = payload.get("workflow_runs") or []
        run_ids.extend(int(run.get("id") or 0) for run in batch)
        if len(batch) < 100:
            break
    return [run_id for run_id in run_ids if run_id > 0]


def _list_candidates(token: str, repo: str, today_prefix: str, horizon_iso: str) -> list[dict]:
    artifacts: list[dict] = []
    for run_id in _list_producer_run_ids(token, repo, horizon_iso):
        try:
            payload = _api_get_json(token, f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # One unreadable run must not cost the whole restore: the other
            # producer runs of the horizon are independent fallbacks.
            print(f"::warning::Could not list artifacts of producer run {run_id}: {exc}")
            continue
        for item in payload.get("artifacts") or []:
            name = str(item.get("name") or "")
            if not name.startswith(_PREFIX):
                continue
            if bool(item.get("expired")):
                continue
            # ISO-Z strings compare lexicographically; empty/absent
            # created_at sorts as too old -> skipped (fail-closed).
            if str(item.get("created_at") or "") < horizon_iso:
                continue
            workflow_run = item.get("workflow_run") or {}
            if str(workflow_run.get("head_branch") or "") != "main":
                continue
            artifacts.append(item)

    artifacts.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    preferred = [item for item in artifacts if str(item.get("name") or "").startswith(today_prefix)]
    fallback = [item for item in artifacts if item not in preferred]
    # A full-window bundle is materially larger than a two-day delta. Sorting
    # each date bucket by size avoids downloading all eight known-small
    # incremental artifacts before inspecting the daily full-window candidate.
    # Only the largest artifact per UTC day can be the full seed; if it still
    # fails semantic coverage validation, move to the next-newest day. Size is
    # only an ordering hint; _trade_days_covered is the authority.
    def _daily_representatives(items: list[dict]) -> list[dict]:
        by_day: dict[str, dict] = {}
        for item in items:
            day = str(item.get("created_at") or "")[:10]
            incumbent = by_day.get(day)
            key = (int(item.get("size_in_bytes") or 0), str(item.get("created_at") or ""))
            incumbent_key = (
                int(incumbent.get("size_in_bytes") or 0),
                str(incumbent.get("created_at") or ""),
            ) if incumbent else (-1, "")
            if key > incumbent_key:
                by_day[day] = item
        return sorted(
            by_day.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

    return _daily_representatives(preferred) + _daily_representatives(fallback)


def _trade_days_covered(target_dir: Path) -> int:
    """Return unique manifest trade dates, or zero for an invalid bundle."""
    manifests = sorted(target_dir.rglob("databento_volatility_production_*_manifest.json"))
    if len(manifests) != 1:
        return 0
    try:
        payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    values = payload.get("trade_dates_covered")
    if not isinstance(values, list):
        return 0
    trade_days = len({value for value in values if isinstance(value, str) and value.strip()})
    declared_coverage = payload.get("coverage_trade_days")
    if declared_coverage is not None and declared_coverage != trade_days:
        return 0
    if payload.get("artifact_scope") == "delta":
        return 0
    return trade_days


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    run_date = os.environ["RUN_DATE"]
    output_path = Path(os.environ["GITHUB_OUTPUT"])
    min_trade_days = int(
        os.environ.get(
            "DATABENTO_MIN_TRADE_DAYS",
            os.environ.get("DATABENTO_BENCHMARK_MIN_TRADE_DAYS", _MIN_TRADE_DAYS),
        )
    )
    if min_trade_days < 1:
        raise ValueError("DATABENTO_MIN_TRADE_DAYS must be positive")

    today_prefix = f"{_PREFIX}{run_date}-"
    _ROOT.mkdir(parents=True, exist_ok=True)

    candidates = _list_candidates(token, repo, today_prefix, _horizon_iso(run_date))
    if not candidates:
        print(
            "::warning::No Databento producer artifact candidates found "
            f"(today or fallback within {_MAX_CANDIDATE_AGE_DAYS} days)."
        )
        _emit(output_path, "found_artifact", "false")
        return 0

    errors: list[str] = []
    for item in candidates[:20]:
        artifact_id = int(item["id"])
        artifact_name = str(item.get("name") or "")
        run_id = int((item.get("workflow_run") or {}).get("id") or 0)
        mode = "today" if artifact_name.startswith(today_prefix) else "fallback"
        for attempt in (1, 2, 3):
            target_dir = _ROOT / artifact_name
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            try:
                blob = _download_zip(token, repo, artifact_id)
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    bad_entry = zf.testzip()
                    if bad_entry:
                        raise zipfile.BadZipFile(f"corrupt entry {bad_entry!r}")
                    zf.extractall(target_dir)

                trade_days = _trade_days_covered(target_dir)
                if trade_days < min_trade_days:
                    errors.append(
                        f"{artifact_name}: insufficient history "
                        f"({trade_days} trading days < {min_trade_days})"
                    )
                    print(
                        f"::notice::Skipping Databento export artifact {artifact_name}: "
                        f"manifest covers {trade_days} trading days; benchmark requires "
                        f"at least {min_trade_days}."
                    )
                    shutil.rmtree(target_dir, ignore_errors=True)
                    break

                print(
                    f"::notice::Restored Databento export artifact {artifact_name} "
                    f"(run_id={run_id}, mode={mode}, attempt={attempt}, "
                    f"trade_days={trade_days}).",
                )
                _emit(output_path, "found_artifact", "true")
                _emit(output_path, "artifact_name", artifact_name)
                _emit(output_path, "artifact_run_id", str(run_id))
                _emit(output_path, "artifact_mode", mode)
                return 0
            except (zipfile.BadZipFile, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                errors.append(f"{artifact_name}#{attempt}: {exc}")
                if attempt < 3:
                    time.sleep(attempt * 2)

    print(
        "::warning::All Databento producer artifact download attempts failed; "
        "verify step will enforce manifest presence.",
    )
    for line in errors[:5]:
        print(f"::warning::{line}")
    _emit(output_path, "found_artifact", "false")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
