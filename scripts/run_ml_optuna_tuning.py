from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.training import LGBMFamilyTrainer, LogisticBaseline, XGBFamilyTrainer  # noqa: E402
from scripts.ml_research_common import (  # noqa: E402
    build_dataset_bundle,
    iso_now,
    parse_families,
)
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tune synthetic ml/ family models with Optuna.")
    parser.add_argument("--backend", choices=["logistic", "xgboost", "lightgbm"], default=os.getenv("SKIPP_ML_BACKEND", "xgboost"))
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default=os.getenv("SKIPP_ML_DEVICE", "auto"))
    parser.add_argument("--families", default="BOS,OB,FVG,SWEEP")
    parser.add_argument("--samples-per-family", type=int, default=700)
    parser.add_argument("--feature-count", type=int, default=16)
    parser.add_argument("--trials", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output-path",
        default=str(REPO_ROOT / "artifacts" / "ml" / "research" / "optuna" / "latest.json"),
    )
    return parser


def _load_optuna() -> Any:
    try:
        import optuna  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "optuna is not installed. Install via 'pip install -r requirements-ml.txt' to run tuning jobs."
        ) from exc
    return optuna


def _build_trainer(*, backend: str, device: str, seed: int, params: dict[str, Any]):
    if backend == "logistic":
        return LogisticBaseline(seed=seed, **params)
    if backend == "xgboost":
        return XGBFamilyTrainer(seed=seed, device=device, **params)
    if backend == "lightgbm":
        return LGBMFamilyTrainer(seed=seed, device=device, **params)
    raise ValueError(f"unsupported backend {backend!r}")


def _device_metadata(*, backend: str, trainer, requested_device: str) -> tuple[str, str | None]:
    resolved = str(getattr(trainer, "resolved_device", "cpu"))
    fallback = getattr(trainer, "device_fallback_reason", None)
    if backend == "logistic" and requested_device != "cpu":
        fallback = "logistic_cpu_only"
    return resolved, fallback


def _suggest_params(trial, *, backend: str) -> dict[str, Any]:
    if backend == "logistic":
        return {
            "l2": trial.suggest_float("l2", 1e-4, 1e-1, log=True),
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.2, log=True),
            "max_iter": trial.suggest_int("max_iter", 200, 600, step=100),
        }
    if backend == "xgboost":
        return {
            "max_depth": trial.suggest_int("max_depth", 3, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 80, 220, step=20),
            "subsample": trial.suggest_float("subsample", 0.65, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.65, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 10.0, log=True),
        }
    return {
        "num_leaves": trial.suggest_int("num_leaves", 15, 63, step=4),
        "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 80, 220, step=20),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.65, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.65, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 10.0, log=True),
    }


def run_tuning(
    *,
    backend: str,
    device: str,
    families_raw: str,
    samples_per_family: int,
    feature_count: int,
    trials: int,
    timeout_seconds: int,
    seed: int,
) -> dict[str, object]:
    optuna = _load_optuna()
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    families = parse_families(families_raw)
    datasets = build_dataset_bundle(
        families,
        n_samples=samples_per_family,
        n_features=feature_count,
        seed=seed,
    )

    def objective(trial) -> float:
        params = _suggest_params(trial, backend=backend)
        family_metrics: dict[str, dict[str, float | str | None]] = {}
        briers: list[float] = []
        resolved_devices: set[str] = set()
        for idx, family in enumerate(families):
            trainer = _build_trainer(backend=backend, device=device, seed=seed + idx, params=params)
            _fitted, report = trainer.fit(datasets[family])
            resolved_device, fallback_reason = _device_metadata(
                backend=backend,
                trainer=trainer,
                requested_device=device,
            )
            resolved_devices.add(resolved_device)
            briers.append(report.brier)
            family_metrics[family] = {
                "brier": float(report.brier),
                "auc": float(report.auc),
                "resolved_device": resolved_device,
                "device_fallback_reason": fallback_reason,
            }
        trial.set_user_attr("family_metrics", family_metrics)
        trial.set_user_attr("resolved_devices", sorted(resolved_devices))
        return float(np.mean(briers))

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(
        objective,
        n_trials=max(1, trials),
        timeout=timeout_seconds if timeout_seconds > 0 else None,
    )

    trial_rows = []
    for trial in study.trials:
        trial_rows.append(
            {
                "number": trial.number,
                "state": trial.state.name,
                "value": float(trial.value) if trial.value is not None else None,
                "params": dict(trial.params),
                "resolved_devices": list(trial.user_attrs.get("resolved_devices", [])),
                "family_metrics": dict(trial.user_attrs.get("family_metrics", {})),
            }
        )

    observed_resolved_devices = sorted(
        {
            str(device_name)
            for row in trial_rows
            for device_name in row["resolved_devices"]
            if device_name is not None
        }
    )
    best_resolved_devices = [str(item) for item in study.best_trial.user_attrs.get("resolved_devices", [])]

    return {
        "generated_at": iso_now(),
        "mode": "tune",
        "backend": backend,
        "requested_device": device,
        "families": list(families),
        "samples_per_family": samples_per_family,
        "feature_count": feature_count,
        "trials_requested": trials,
        "trials_completed": len(study.trials),
        "best_trial_number": int(study.best_trial.number),
        "best_value": float(study.best_value),
        "best_params": dict(study.best_params),
        "best_resolved_devices": best_resolved_devices,
        "observed_resolved_devices": observed_resolved_devices,
        "trial_summaries": trial_rows,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = run_tuning(
        backend=str(args.backend),
        device=str(args.device),
        families_raw=str(args.families),
        samples_per_family=int(args.samples_per_family),
        feature_count=int(args.feature_count),
        trials=int(args.trials),
        timeout_seconds=int(args.timeout_seconds),
        seed=int(args.seed),
    )
    output_path = Path(args.output_path).expanduser()
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", output_path)

    best_devices = payload.get("best_resolved_devices", [])
    print(f"mode={payload['mode']}")
    print(f"backend={payload['backend']}")
    print(f"requested_device={payload['requested_device']}")
    print(f"trials_completed={payload['trials_completed']}")
    print(f"best_value={payload['best_value']:.6f}")
    print(f"best_resolved_devices={','.join(best_devices)}")
    print(f"artifact={output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())