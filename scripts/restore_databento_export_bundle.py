"""Restore the latest Databento production export artifact for the rolling benchmark.

Pulls today's ``smc-databento-production-export-<RUN_DATE>-*`` GitHub Actions
artifact from the ``main`` branch (or the most recent same-prefix fallback)
and extracts it into ``artifacts/smc_microstructure_exports/``. Survives
transient zip corruption by retrying each candidate up to 3 times before
falling back to the next-newer artifact. Only artifacts produced by the
canonical sharded producer workflow are eligible; emergency/manual artifacts
from the deprecated monolith use the same legacy prefix but must not feed the
rolling benchmark.

Replaces the inline heredoc previously embedded in
``.github/workflows/smc-measurement-benchmark-rolling.yml`` (F-V8-D4,
2026-05-16). Behavior is bit-identical; only the location changed so the
logic can be linted / type-checked / unit-tested.

Required env vars:
  GITHUB_REPOSITORY   – e.g. ``skippALGO/skipp-algo``
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
from pathlib import Path
from urllib.parse import urlparse

_PREFIX = "smc-databento-production-export-"
_CANONICAL_WORKFLOW_FILE = "smc-databento-production-export-sharded.yml"
_CANONICAL_WORKFLOW_NAME = "smc-databento-production-export-sharded"
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
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed api.github.com URL
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
            fp,  # noqa: ANN001
            code: int,
            msg: str,
            headers,  # noqa: ANN001
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
    with opener.open(req, timeout=120) as resp:  # noqa: S310 - fixed api.github.com URL
        return resp.read()


def _is_canonical_producer_run(token: str, repo: str, run_id: int, cache: dict[int, bool]) -> bool:
    """Return whether ``run_id`` belongs to the canonical sharded producer."""
    if run_id <= 0:
        return False
    if run_id in cache:
        return cache[run_id]
    payload = _api_get_json(token, f"repos/{repo}/actions/runs/{run_id}")
    workflow_path = str(payload.get("path") or "")
    workflow_name = str(payload.get("name") or "")
    ok = (
        workflow_path.endswith(f"/{_CANONICAL_WORKFLOW_FILE}")
        or workflow_path == _CANONICAL_WORKFLOW_FILE
        or workflow_name == _CANONICAL_WORKFLOW_NAME
    )
    cache[run_id] = ok
    return ok


def _list_candidates(token: str, repo: str, today_prefix: str) -> list[dict]:
    artifacts: list[dict] = []
    run_workflow_cache: dict[int, bool] = {}
    for page in range(1, 4):
        payload = _api_get_json(token, f"repos/{repo}/actions/artifacts?per_page=100&page={page}")
        batch = payload.get("artifacts") or []
        if not batch:
            break
        for item in batch:
            name = str(item.get("name") or "")
            if not name.startswith(_PREFIX):
                continue
            if bool(item.get("expired")):
                continue
            workflow_run = item.get("workflow_run") or {}
            if str(workflow_run.get("head_branch") or "") != "main":
                continue
            run_id = int(workflow_run.get("id") or 0)
            if not _is_canonical_producer_run(token, repo, run_id, run_workflow_cache):
                continue
            artifacts.append(item)
        if len(batch) < 100:
            break

    artifacts.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    preferred = [item for item in artifacts if str(item.get("name") or "").startswith(today_prefix)]
    fallback = [item for item in artifacts if item not in preferred]
    return preferred + fallback


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    run_date = os.environ["RUN_DATE"]
    output_path = Path(os.environ["GITHUB_OUTPUT"])

    today_prefix = f"{_PREFIX}{run_date}-"
    _ROOT.mkdir(parents=True, exist_ok=True)

    candidates = _list_candidates(token, repo, today_prefix)
    if not candidates:
        print("::warning::No Databento producer artifact candidates found (today or fallback).")
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

                print(
                    f"::notice::Restored Databento export artifact {artifact_name} "
                    f"(run_id={run_id}, mode={mode}, attempt={attempt}).",
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
