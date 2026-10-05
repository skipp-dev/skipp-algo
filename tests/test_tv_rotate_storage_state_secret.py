"""Guards for the validated TV_STORAGE_STATE rotation path (#3640).

`tradingview-storage-refresh.yml` validates a capture with the
`tv_storage_state_age` probe before it writes the secret. A hand-run
`gh secret set` skipped that gate, which is how a 2026-06-29 capture was pushed
over the fresh 07-13 session on 2026-07-14T12:33Z and stalled the publish chain.

These tests pin that `scripts/tv_rotate_storage_state_secret.sh` closes that gap
and — critically — that it is **fail-closed**: a stale capture must not reach
`gh` at all.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "tv_rotate_storage_state_secret.sh"
_RUNBOOK = _REPO_ROOT / "docs" / "tradingview-storage-state-capture-runbook.md"
_REFRESH_WORKFLOW = (
    _REPO_ROOT / ".github" / "workflows" / "tradingview-storage-refresh.yml"
)


def _write_state(path: Path, *, age_hours: float) -> None:
    validated_at = datetime.now(UTC) - timedelta(hours=age_hours)
    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "sessionid", "domain": ".tradingview.com"},
                    {"name": "sessionid_sign", "domain": ".tradingview.com"},
                ],
                "origins": [],
                "meta": {
                    "authValidatedAt": validated_at.isoformat(),
                    "validationMode": "standard_session",
                },
            }
        )
    )


def _stub_gh(bin_dir: Path, marker: Path) -> None:
    """A `gh` that records that it ran, so we can prove it did NOT."""
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s" "$*" > {marker}\n'
        "cat > /dev/null\n"  # drain stdin like the real `gh secret set`
        "exit 0\n"
    )
    gh.chmod(0o755)


def _run(state: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "gh-was-called"
    _stub_gh(bin_dir, marker)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PYTHON"] = sys.executable
    env["TV_SECRET_REPO"] = "skipp-dev/skipp-algo"
    proc = subprocess.run(
        ["bash", str(_SCRIPT), str(state)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return proc, marker


def test_script_exists_and_is_executable() -> None:
    assert _SCRIPT.is_file()
    assert os.access(_SCRIPT, os.X_OK), f"{_SCRIPT} must be executable"


def test_stale_capture_is_refused_and_never_reaches_gh(tmp_path: Path) -> None:
    """The #3640 scenario: a 15-day-old capture must not be rotatable."""
    state = tmp_path / "storage-state.json"
    _write_state(state, age_hours=382.5)  # the exact age observed in #3640

    proc, marker = _run(state, tmp_path)

    assert proc.returncode != 0, f"stale capture was accepted!\n{proc.stdout}\n{proc.stderr}"
    assert not marker.exists(), (
        "FAIL-CLOSED VIOLATION: gh ran despite a stale capture — the secret "
        "would have been overwritten, which is exactly bug #3640"
    )
    assert "REFUSING to rotate" in proc.stderr


def test_fresh_capture_is_written(tmp_path: Path) -> None:
    state = tmp_path / "storage-state.json"
    _write_state(state, age_hours=0.2)

    proc, marker = _run(state, tmp_path)

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert marker.exists(), "fresh capture should have been written"
    args = marker.read_text()
    assert "secret set TV_STORAGE_STATE" in args
    assert "--repo skipp-dev/skipp-algo" in args


def test_rotation_writes_a_pruned_copy_and_keeps_the_local_capture(tmp_path: Path) -> None:
    """A local capture carries the whole browser profile's cookies (2026-10-05:
    3 106 cookies, 903 KiB). Only TradingView's may reach the secret, and the
    local file must stay as it is."""
    state = tmp_path / "storage-state.json"
    _write_state(state, age_hours=0.2)
    data = json.loads(state.read_text())
    data["cookies"] += [{"name": f"ad{i}", "domain": f".ads{i % 30}.example"} for i in range(1500)]
    state.write_text(json.dumps(data))
    original = state.read_text()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stdin_copy = tmp_path / "secret-stdin.json"
    gh = bin_dir / "gh"
    gh.write_text(f'#!/usr/bin/env bash\ncat > {stdin_copy}\nexit 0\n')
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PYTHON"] = sys.executable
    env["TV_SECRET_REPO"] = "skipp-dev/skipp-algo"
    proc = subprocess.run(
        ["bash", str(_SCRIPT), str(state)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    written = json.loads(stdin_copy.read_text())
    assert sorted(c["name"] for c in written["cookies"]) == ["sessionid", "sessionid_sign"]
    assert written["meta"] == data["meta"]
    assert state.read_text() == original, "the local capture must not be rewritten"


def test_rotation_never_passes_the_capture_through_the_environment() -> None:
    script = _SCRIPT.read_text()
    code = "\n".join(line.split("#", 1)[0] for line in script.splitlines())
    assert '$(cat "${STATE_PATH}")' not in code
    assert "--tv-storage-state-file" in code


def test_capture_just_past_ttl_is_refused(tmp_path: Path) -> None:
    """Boundary: the gate is the 72 h refresh TTL, same as CI."""
    state = tmp_path / "storage-state.json"
    _write_state(state, age_hours=72.5)

    proc, marker = _run(state, tmp_path)

    assert proc.returncode != 0
    assert not marker.exists()


def test_missing_capture_is_refused(tmp_path: Path) -> None:
    proc, marker = _run(tmp_path / "does-not-exist.json", tmp_path)

    assert proc.returncode != 0
    assert not marker.exists()
    assert "no capture at" in proc.stderr


def test_rotation_gate_matches_the_ci_validate_step() -> None:
    """Parity: the hand path must not enforce a weaker TTL/probe than CI.

    If these drift, a capture CI would reject could still be hand-pushed — the
    gap #3640 came through.
    """
    script = _SCRIPT.read_text()
    workflow = _REFRESH_WORKFLOW.read_text()

    # Same probe, same severity gate.
    for token in ("credential_health_check.py", "tv_storage_state_age", '!= "ok"'):
        assert token in script, f"rotation script must reference {token!r}"
    assert "tv_storage_state_age" in workflow

    # Same TTL default.
    assert 'TV_STORAGE_STATE_MAX_AGE_HOURS:-72' in script
    assert "--tv-max-age-hours 72" in workflow


def test_npm_exposes_the_validated_rotation() -> None:
    scripts = json.loads((_REPO_ROOT / "package.json").read_text())["scripts"]
    assert scripts.get("tv:rotate-secret") == (
        "bash scripts/tv_rotate_storage_state_secret.sh"
    )


# ------------------------------------------------------------------ runbook


def test_runbook_rotates_through_the_validated_path() -> None:
    text = _RUNBOOK.read_text()
    assert "npm run tv:rotate-secret" in text, (
        "the runbook's rotation step must go through the validated wrapper"
    )
    bare = re.search(
        r"^gh secret set TV_STORAGE_STATE --repo \S+ *\\?$", text, re.MULTILINE
    )
    assert bare is None, (
        "the runbook still documents a bare `gh secret set`, which skips the "
        "tv_storage_state_age gate (#3640)"
    )


def test_runbook_inspection_step_does_not_print_unconditional_ok() -> None:
    """The precise #3640 mechanism.

    The inspection block computed `age` and printed a line starting with "OK — "
    regardless of it. For the 2026-06-29 capture it printed
    `OK — authValidatedAt=..., age=382.5h` and the operator proceeded to push.
    It may report the age; it must not bless it.
    """
    text = _RUNBOOK.read_text()
    assert 'print(f"OK — authValidatedAt' not in text, (
        "inspection step must not print a leading OK it never verified"
    )


def test_runbook_does_not_claim_the_probe_is_raw_json_only() -> None:
    """`_loads_tv_storage_state` falls back to gzip+base64 — the claim was false.

    It also mattered: the CI refresh writes gzip+base64, and the probe reads it
    (it reported the age in #3640), so the documented reason for preferring raw
    JSON never held.
    """
    text = _RUNBOOK.read_text()
    assert "raw JSON only" not in text
