"""Pin the Step 8 parallelism safety contract on the legacy producer workflow.

Recent producer schedule failures were concentrated in Step 8's parallel
10a-d layer while close-trade detail grew very large. This pin ensures:

1) The live producer workflow exports an explicit
   ``DATABENTO_STEP8_SUBSTEP_PARALLELISM`` env override.
2) The producer script still consumes that env switch.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
_SCRIPT = _REPO_ROOT / "scripts" / "databento_production_export.py"
_ENV_KEY = "DATABENTO_STEP8_SUBSTEP_PARALLELISM"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _producer_step_envs(workflow: dict) -> list[dict]:
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


def test_legacy_producer_cron_sets_step8_parallelism_env() -> None:
    envs = _producer_step_envs(_load(_WORKFLOW))
    assert envs, f"{_WORKFLOW.name} has no 'Run Databento production export' step"
    for env in envs:
        assert _ENV_KEY in env, (
            f"{_WORKFLOW.name} producer step is missing {_ENV_KEY}; "
            "Step 8 parallelism override must be explicitly pinned for "
            "the live producer workflow."
        )
        assert str(env[_ENV_KEY]) == "1", (
            f"{_WORKFLOW.name} producer step has {_ENV_KEY}={env[_ENV_KEY]!r}; "
            "expected '1' to keep Step 8 serialized on the legacy cron path."
        )


def test_producer_script_consumes_step8_parallelism_env() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert _ENV_KEY in text, (
        "Producer script must read DATABENTO_STEP8_SUBSTEP_PARALLELISM so "
        "workflow-level parallelism overrides take effect."
    )
    assert "max_workers=step8_parallelism" in text
