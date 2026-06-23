from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_DEFAULT_SELF_HOSTED_LABELS = ["self-hosted", "windows", "x64"]
_API_VERSION = "2022-11-28"
_USER_AGENT = "skipp-algo-runner-selector"


@dataclass(frozen=True)
class RunnerResolution:
    runs_on: str | list[str]
    runner_environment: str
    reason: str
    matched_runner_name: str | None = None


def build_required_labels(custom_label: str | None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for raw_label in [*_DEFAULT_SELF_HOSTED_LABELS, custom_label or ""]:
        label = raw_label.strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        labels.append(label)
        seen.add(key)
    return labels


def runner_matches_required_labels(runner: dict[str, Any], required_labels: list[str]) -> bool:
    runner_labels = {
        str(label.get("name", "")).strip().lower()
        for label in runner.get("labels") or []
        if str(label.get("name", "")).strip()
    }
    return all(label.lower() in runner_labels for label in required_labels)


def resolve_runs_on(
    runners: list[dict[str, Any]],
    custom_label: str | None,
    hosted_runner: str,
    no_idle_fallback: str = "hosted",
) -> RunnerResolution:
    required_labels = build_required_labels(custom_label)
    for runner in runners:
        if str(runner.get("status", "")).lower() != "online":
            continue
        if bool(runner.get("busy")):
            continue
        if not runner_matches_required_labels(runner, required_labels):
            continue
        return RunnerResolution(
            runs_on=required_labels,
            runner_environment="self-hosted",
            reason="matched_idle_self_hosted_runner",
            matched_runner_name=str(runner.get("name", "")).strip() or None,
        )
    if no_idle_fallback == "required-self-hosted":
        return RunnerResolution(
            runs_on=required_labels,
            runner_environment="self-hosted",
            reason="no_idle_matching_self_hosted_runner:forced_required_self_hosted",
        )
    return RunnerResolution(
        runs_on=hosted_runner,
        runner_environment="github-hosted",
        reason="no_idle_matching_self_hosted_runner",
    )


def _fetch_repository_runners(repository: str, token: str) -> list[dict[str, Any]]:
    request = Request(
        f"https://api.github.com/repos/{repository}/actions/runners?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": _API_VERSION,
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    runners = payload.get("runners")
    if not isinstance(runners, list):
        raise ValueError("GitHub runners payload missing runners list")
    return [runner for runner in runners if isinstance(runner, dict)]


def _append_github_output(
    github_output_path: str | None,
    resolution: RunnerResolution,
    required_labels: list[str],
) -> None:
    if not github_output_path:
        return
    with open(github_output_path, "a", encoding="utf-8") as handle:
        handle.write(f"runs_on_json={json.dumps(resolution.runs_on)}\n")
        handle.write(f"runner_environment={resolution.runner_environment}\n")
        handle.write(f"resolution_reason={resolution.reason}\n")
        handle.write(f"required_self_hosted_labels_json={json.dumps(required_labels)}\n")
        handle.write(f"matched_runner_name={resolution.matched_runner_name or ''}\n")


def _env_truthy(value: str | None) -> bool:
    """Return True for common truthy string encodings of a flag env var."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a GitHub Actions runner. Self-hosted-primary by default; "
            "github-hosted can be forced via --force-hosted / SMC_FORCE_GH_HOSTED."
        )
    )
    parser.add_argument("--repository", required=True, help="Repository in owner/name form.")
    parser.add_argument("--hosted-runner", default="ubuntu-latest", help="GitHub-hosted fallback runner label.")
    parser.add_argument("--custom-label", default="", help="Optional custom self-hosted runner label.")
    parser.add_argument(
        "--token-env",
        default="GH_TOKEN",
        help="Environment variable that stores the token used to query runner inventory.",
    )
    parser.add_argument(
        "--inventory-unavailable-fallback",
        choices=["hosted", "required-self-hosted"],
        default="hosted",
        help=(
            "Fallback mode when runner inventory cannot be queried. "
            "'hosted' preserves legacy behavior; 'required-self-hosted' routes directly "
            "to required self-hosted labels instead."
        ),
    )
    parser.add_argument(
        "--no-idle-fallback",
        choices=["hosted", "required-self-hosted"],
        default="hosted",
        help=(
            "Fallback mode when runner inventory was queried successfully but no "
            "runner matched online+idle+required-labels. 'hosted' preserves legacy "
            "behavior (route to github-hosted); 'required-self-hosted' routes to "
            "required self-hosted labels so the job queues until a runner is free."
        ),
    )
    parser.add_argument(
        "--force-hosted",
        action="store_true",
        default=_env_truthy(os.getenv("SMC_FORCE_GH_HOSTED")),
        help=(
            "Force github-hosted resolution unconditionally, bypassing runner "
            "inventory and every self-hosted fallback. Defaults to the truthiness "
            "of the SMC_FORCE_GH_HOSTED environment variable so a single repository "
            "variable can flip all workflows to github-hosted."
        ),
    )
    args = parser.parse_args()

    custom_label = args.custom_label.strip() or None
    required_labels = build_required_labels(custom_label)
    token = os.getenv(args.token_env, "").strip()
    force_required_self_hosted = args.inventory_unavailable_fallback == "required-self-hosted"

    if args.force_hosted:
        resolution = RunnerResolution(
            runs_on=args.hosted_runner,
            runner_environment="github-hosted",
            reason="forced_github_hosted",
        )
    elif not token:
        if force_required_self_hosted:
            resolution = RunnerResolution(
                runs_on=required_labels,
                runner_environment="self-hosted",
                reason=f"missing_token_env:{args.token_env}:forced_required_self_hosted",
            )
        else:
            resolution = RunnerResolution(
                runs_on=args.hosted_runner,
                runner_environment="github-hosted",
                reason=f"missing_token_env:{args.token_env}",
            )
    else:
        try:
            runners = _fetch_repository_runners(args.repository, token)
            resolution = resolve_runs_on(
                runners=runners,
                custom_label=custom_label,
                hosted_runner=args.hosted_runner,
                no_idle_fallback=args.no_idle_fallback,
            )
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            if force_required_self_hosted:
                resolution = RunnerResolution(
                    runs_on=required_labels,
                    runner_environment="self-hosted",
                    reason=f"runner_inventory_unavailable:{type(exc).__name__}:forced_required_self_hosted",
                )
            else:
                resolution = RunnerResolution(
                    runs_on=args.hosted_runner,
                    runner_environment="github-hosted",
                    reason=f"runner_inventory_unavailable:{type(exc).__name__}",
                )

    _append_github_output(os.getenv("GITHUB_OUTPUT"), resolution, required_labels)
    print(
        json.dumps(
            {
                "runs_on": resolution.runs_on,
                "runner_environment": resolution.runner_environment,
                "reason": resolution.reason,
                "matched_runner_name": resolution.matched_runner_name,
                "required_self_hosted_labels": required_labels,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
