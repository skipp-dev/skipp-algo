"""F-002 / F-V8-perf-3.5: lifecycle contract for the cache-probe log.

These tests pin the public contract used by the sharded probe-cron
workflow (`smc-databento-production-export-sharded.yml`) and the
producer's atexit dump (`scripts/databento_production_export.py`):

- ``enable_cache_probe_log()`` is idempotent (does NOT clobber an
  already-active log on second call).
- ``reset_cache_probe_log()`` is the only way to clear state.
- ``dump_cache_probe_log()`` writes one JSON object per line and may be
  called multiple times safely.
- A simulated exception in the producer does not lose entries that were
  recorded before the exception, as long as the dump is registered via
  ``atexit`` (this is the contract F-001 hardens).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import databento_volatility_screener as dvs


@pytest.fixture(autouse=True)
def _reset_probe_log():
    dvs.reset_cache_probe_log()
    yield
    dvs.reset_cache_probe_log()


def test_enable_is_idempotent_and_does_not_clobber(tmp_path: Path) -> None:
    dvs.enable_cache_probe_log()
    dvs._record_cache_probe(tmp_path / "a.parquet", hit=True)
    dvs.enable_cache_probe_log()  # second call must NOT wipe the log
    assert dvs.cache_probe_log_size() == 1


def test_record_and_dump_jsonl_roundtrip(tmp_path: Path) -> None:
    dvs.enable_cache_probe_log()
    dvs._record_cache_probe(tmp_path / "a.parquet", hit=True)
    dvs._record_cache_probe(tmp_path / "b.parquet", hit=False)

    out = tmp_path / "out" / "probe.jsonl"
    n = dvs.dump_cache_probe_log(out)
    assert n == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0] == {"path": str(tmp_path / "a.parquet"), "hit": True}
    assert parsed[1]["hit"] is False


def test_record_no_op_when_disabled(tmp_path: Path) -> None:
    dvs._record_cache_probe(tmp_path / "a.parquet", hit=True)
    assert dvs.cache_probe_log_size() == 0
    assert dvs.dump_cache_probe_log(tmp_path / "empty.jsonl") == 0
    # disabled-mode dump MUST NOT create the file
    assert not (tmp_path / "empty.jsonl").exists()


def test_reset_clears_state(tmp_path: Path) -> None:
    dvs.enable_cache_probe_log()
    dvs._record_cache_probe(tmp_path / "a.parquet", hit=True)
    dvs.reset_cache_probe_log()
    assert dvs.cache_probe_log_size() == 0
    # re-enable starts from zero
    dvs.enable_cache_probe_log()
    assert dvs.cache_probe_log_size() == 0


def test_dump_is_idempotent_and_overwrites(tmp_path: Path) -> None:
    dvs.enable_cache_probe_log()
    dvs._record_cache_probe(tmp_path / "a.parquet", hit=True)
    out = tmp_path / "probe.jsonl"
    assert dvs.dump_cache_probe_log(out) == 1
    assert dvs.dump_cache_probe_log(out) == 1
    # still just one line (overwrite, not append)
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_atexit_flush_survives_unhandled_exception(tmp_path: Path) -> None:
    """F-001 contract: atexit-registered dump fires even when the script
    body raises an uncaught exception (SystemExit code != 0)."""
    repo_root = Path(__file__).resolve().parents[1]
    out = tmp_path / "probe.jsonl"
    script = textwrap.dedent(
        f"""
        import atexit, sys
        sys.path.insert(0, {str(repo_root)!r})
        import databento_volatility_screener as dvs
        from pathlib import Path
        dvs.enable_cache_probe_log()
        atexit.register(dvs.dump_cache_probe_log, {str(out)!r})
        dvs._record_cache_probe(Path("before-crash.parquet"), hit=True)
        raise RuntimeError("simulated producer crash")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stderr
    assert out.exists(), (
        f"atexit dump did not run; stderr={result.stderr!r}"
    )
    entries = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert entries == [{"path": "before-crash.parquet", "hit": True}]
