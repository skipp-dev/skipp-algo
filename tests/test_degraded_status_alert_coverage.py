"""``degraded`` pages only because its component alerts do — pin that.

``compute_daemon_health_status`` returns ``"degraded"`` (health_status_code 4)
when, past a 900s warmup during an open US session, any of ``feed_healthy``,
``workers_healthy`` or ``overlay_fresh`` is false. **No alert rule references
health_status_code at all.** The state pages purely because each of those three
inputs has its own rule that fires earlier — lo-feed-down-market-open (5m),
lo-workers-degraded (3m), lo-no-symbols (5m, uptime>600s), lo-overlay-stale
(5m) — every one of them before the 900s gate even opens.

Adding a dedicated health_status_code==4 rule would be redundant noise: it can
never fire first. But the coverage is entirely *implicit*, so deleting or
weakening one component rule would silently open the gap with nothing red. This
test makes that edit fail CI instead.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_RULES = (
    Path(__file__).resolve().parents[1]
    / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
)

# Each input to the degraded predicate -> the metric that carries it, and the
# rule(s) that must keep watching it. Verified against the YAML 2026-07-23.
_DEGRADED_INPUTS = {
    "feed_healthy": ("live_overlay_feed_healthy", {"lo-feed-down-market-open"}),
    "workers_healthy": ("live_overlay_workers_healthy", {"lo-workers-degraded"}),
    "overlay_fresh/symbols": ("live_overlay_overlay_symbols", {"lo-no-symbols"}),
    "overlay_fresh/age": ("live_overlay_overlay_age_seconds", {"lo-overlay-stale"}),
}


def _rules() -> list[dict]:
    doc = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    return [rule for group in doc["groups"] for rule in group["rules"]]


def _exprs(rule: dict) -> str:
    return " ".join((q.get("model", {}) or {}).get("expr") or "" for q in rule["data"])


@pytest.mark.parametrize("label", sorted(_DEGRADED_INPUTS))
def test_every_degraded_input_keeps_an_alert(label: str) -> None:
    metric, required_uids = _DEGRADED_INPUTS[label]
    watching = {r["uid"] for r in _rules() if metric in _exprs(r)}

    assert watching, (
        f"{metric} feeds the degraded status but no alert rule references it. "
        "Nothing would page for a sustained outage on this input, because "
        "health_status_code itself has no rule."
    )
    assert required_uids <= watching, (
        f"{sorted(required_uids - watching)} no longer watches {metric}. "
        "If the rule was renamed, update _DEGRADED_INPUTS; if it was dropped, "
        "degraded lost its only alarm on this input."
    )


@pytest.mark.parametrize("label", sorted(_DEGRADED_INPUTS))
def test_the_covering_rules_page_before_the_900s_gate(label: str) -> None:
    """Coverage is only meaningful if it fires *earlier* than degraded engages.

    A component rule silently relaxed to `for: 30m` would leave a 15-minute
    window in which the daemon is degraded and nothing has paged yet.
    """
    _, required_uids = _DEGRADED_INPUTS[label]
    by_uid = {r["uid"]: r for r in _rules()}
    for uid in sorted(required_uids):
        pending = str(by_uid[uid].get("for", "0m"))
        assert pending.endswith("m"), f"{uid}: unexpected `for` unit {pending!r}"
        assert int(pending[:-1]) <= 15, (
            f"{uid} waits {pending} before firing — degraded engages at 900s "
            "(15 min), so this rule no longer pages first."
        )


def test_no_redundant_health_status_code_rule_was_added() -> None:
    """Documents the deliberate decision, and fails loudly if someone adds the
    redundant rule without removing this pin — so the reasoning gets revisited
    rather than quietly contradicted."""
    watching = [r["uid"] for r in _rules() if "live_overlay_health_status_code" in _exprs(r)]
    assert not watching, (
        f"{watching} alerts on health_status_code. That is covered by the "
        "component rules above and can never fire first — if it is wanted "
        "anyway, delete this test and say why in the rule comment."
    )
