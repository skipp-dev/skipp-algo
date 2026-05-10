"""Pin: legacy Databento producer cron must export the Q3a env contract.

Audit follow-up to **F7 (2026-05-10)** — the legacy
``smc-databento-production-export.yml`` cron has been hitting the 240-min
GHA cap on every scheduled tick since 2026-05-06 because the
``DATABENTO_DAILY_MAX_WORKERS`` env switch (Q3a, PR #2098) was wired into
the *sharded* probe workflow but not into the legacy producer.

This pin enforces parity: both producer workflows must publish the same
Q3a env contract so the parallel-fetch cure is active wherever the
producer pipeline runs.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LEGACY = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
_SHARDED = (
    _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export-sharded.yml"
)

_Q3A_ENV_KEY = "DATABENTO_DAILY_MAX_WORKERS"
_Q3A_EXPECTED_VALUE = "4"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _producer_step_envs(workflow: dict) -> list[dict]:
    """Return env dicts of every step whose name starts with ``Run Databento production export``."""
    envs: list[dict] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            name = str(step.get("name") or "")
            if not name.startswith("Run Databento production export"):
                continue
            env = step.get("env") or {}
            if isinstance(env, dict):
                envs.append(env)
    return envs


def test_legacy_producer_cron_has_q3a_env() -> None:
    envs = _producer_step_envs(_load(_LEGACY))
    assert envs, f"{_LEGACY.name} has no 'Run Databento production export' step"
    for env in envs:
        assert _Q3A_ENV_KEY in env, (
            f"{_LEGACY.name} producer step is missing {_Q3A_ENV_KEY}; the "
            "Q3a parallel-fetch cure (PR #2098) must be active on the live "
            "production cron, not just the sharded probe (F7, 2026-05-10)."
        )
        assert str(env[_Q3A_ENV_KEY]) == _Q3A_EXPECTED_VALUE, (
            f"{_LEGACY.name} producer step has {_Q3A_ENV_KEY}="
            f"{env[_Q3A_ENV_KEY]!r}; expected {_Q3A_EXPECTED_VALUE!r} to "
            "match the sharded probe contract."
        )


def test_legacy_and_sharded_producer_share_q3a_contract() -> None:
    legacy_envs = _producer_step_envs(_load(_LEGACY))
    sharded_envs = _producer_step_envs(_load(_SHARDED))
    assert legacy_envs and sharded_envs
    legacy_values = {str(env.get(_Q3A_ENV_KEY)) for env in legacy_envs}
    sharded_values = {str(env.get(_Q3A_ENV_KEY)) for env in sharded_envs}
    assert legacy_values == sharded_values, (
        "Producer workflows disagree on the Q3a env contract: "
        f"legacy={sorted(legacy_values)} sharded={sorted(sharded_values)}."
    )
