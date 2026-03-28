"""Publish-guard logic for the SMC micro-library TradingView publish flow.

Extracted from ``smc_microstructure_base_runtime`` to reduce scope creep.
All three functions are re-exported from the runtime module for backward
compatibility.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def publish_micro_library_to_tradingview(
    *,
    repo_root: Path,
    report_path: Path,
) -> dict[str, Any]:
    command = [
        "npm",
        "run",
        "--silent",
        "tv:publish-micro-library",
        "--",
        "--out",
        str(report_path),
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    payload: dict[str, Any] | None = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    if payload is None and report_path.exists():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    if payload is None:
        raise RuntimeError(stderr or stdout or "TradingView micro-library publish did not return a readable report.")
    payload["report_path"] = str(report_path)
    payload["stdout"] = stdout
    payload["stderr"] = stderr
    payload["returncode"] = completed.returncode
    if completed.returncode != 0:
        raise RuntimeError(str(payload.get("error") or stderr or stdout or "TradingView micro-library publish failed."))
    return payload


def inspect_generated_micro_library_contract(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / "pine" / "generated" / "smc_micro_profiles_generated.json"
    if not manifest_path.exists():
        return {
            "exists": False,
            "manifest_path": manifest_path,
            "owner": None,
            "version": None,
            "import_path": None,
            "reason": "Generate Pine Library first. No generated micro-library manifest exists yet.",
        }

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "exists": False,
            "manifest_path": manifest_path,
            "owner": None,
            "version": None,
            "import_path": None,
            "reason": f"Generated micro-library manifest could not be read: {exc}",
        }

    owner = str(payload.get("library_owner") or "").strip() or None
    raw_version = payload.get("library_version")
    try:
        version = int(raw_version) if raw_version is not None else None
    except (TypeError, ValueError):
        version = None

    return {
        "exists": True,
        "manifest_path": manifest_path,
        "owner": owner,
        "version": version,
        "import_path": str(payload.get("recommended_import_path") or "").strip() or None,
        "owner_version_ready": bool(owner and version is not None),
        "full_contract_ready": False,
        "reason": None,
    }


def evaluate_micro_library_publish_guard(
    *,
    repo_root: Path,
    library_owner: str,
    library_version: int,
) -> dict[str, Any]:
    contract = inspect_generated_micro_library_contract(repo_root)
    configured_owner = str(library_owner).strip()
    configured_version = int(library_version)

    if not contract["exists"]:
        return {
            "can_publish": False,
            "message": str(contract["reason"]),
            "severity": "warning",
            "contract": contract,
        }

    generated_owner = str(contract.get("owner") or "").strip()
    generated_version = contract.get("version")
    if generated_owner != configured_owner or generated_version != configured_version:
        contract["owner_version_ready"] = False
        return {
            "can_publish": False,
            "message": (
                "Publish blocked: the sidebar owner/version do not match the generated library artifacts. "
                f"Generated = {generated_owner or 'n/a'}/{generated_version if generated_version is not None else 'n/a'}, "
                f"Configured = {configured_owner or 'n/a'}/{configured_version}. Regenerate the Pine library first."
            ),
            "severity": "error",
            "contract": contract,
        }

    contract["owner_version_ready"] = True
    try:
        from scripts.smc_micro_validator import validate_publish_readiness

        validate_publish_readiness(
            manifest_path=Path(contract["manifest_path"]),
            core_path=repo_root / "SMC_Core_Engine.pine",
        )
    except Exception as exc:
        contract["full_contract_ready"] = False
        return {
            "can_publish": False,
            "message": (
                "Publish blocked: owner/version match, but the full manifest/snippet/core contract is not valid. "
                f"Details: {exc}"
            ),
            "severity": "error",
            "contract": contract,
        }

    contract["full_contract_ready"] = True

    return {
        "can_publish": True,
        "message": (
            "Publish ready: owner/version match and the full manifest/snippet/core contract validated successfully. "
            f"Import path: {contract.get('import_path') or 'n/a'}"
        ),
        "severity": "success",
        "contract": contract,
    }
