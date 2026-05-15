from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ml.training import LGBMFamilyTrainer, LogisticBaseline, XGBFamilyTrainer
from scripts.ml_research_common import (
    build_dataset_bundle,
    iso_now,
    parse_families,
    summarise_reports,
)
from scripts.smc_atomic_write import atomic_write_text

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train synthetic ml/ family models for offline GPU research.")
    parser.add_argument("--backend", choices=["logistic", "xgboost", "lightgbm"], default=os.getenv("SKIPP_ML_BACKEND", "xgboost"))
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default=os.getenv("SKIPP_ML_DEVICE", "auto"))
    parser.add_argument("--families", default="BOS,OB,FVG,SWEEP")
    parser.add_argument("--samples-per-family", type=int, default=900)
    parser.add_argument("--feature-count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output-path",
        default=str(REPO_ROOT / "artifacts" / "ml" / "research" / "training" / "latest.json"),
    )
    return parser


def _build_trainer(*, backend: str, device: str, seed: int):
    if backend == "logistic":
        return LogisticBaseline(seed=seed, max_iter=400)
    if backend == "xgboost":
        return XGBFamilyTrainer(seed=seed, device=device, n_estimators=160)
    if backend == "lightgbm":
        return LGBMFamilyTrainer(seed=seed, device=device, n_estimators=160)
    raise ValueError(f"unsupported backend {backend!r}")


def _device_metadata(*, backend: str, trainer, requested_device: str) -> tuple[str, str | None]:
    resolved = str(getattr(trainer, "resolved_device", "cpu"))
    fallback = getattr(trainer, "device_fallback_reason", None)
    if backend == "logistic" and requested_device != "cpu":
        fallback = "logistic_cpu_only"
    return resolved, fallback


def run_training(*, backend: str, device: str, families_raw: str, samples_per_family: int, feature_count: int, seed: int) -> dict[str, object]:
    families = parse_families(families_raw)
    datasets = build_dataset_bundle(
        families,
        n_samples=samples_per_family,
        n_features=feature_count,
        seed=seed,
    )
    per_family: list[dict[str, object]] = []
    reports = []
    for idx, family in enumerate(families):
        trainer = _build_trainer(backend=backend, device=device, seed=seed + idx)
        fitted, report = trainer.fit(datasets[family])
        resolved_device, fallback_reason = _device_metadata(
            backend=backend,
            trainer=trainer,
            requested_device=device,
        )
        reports.append(report)
        per_family.append(
            {
                "family": family,
                "model_version": report.model_version,
                "backend": report.backend,
                "resolved_device": resolved_device,
                "device_fallback_reason": fallback_reason,
                "brier": report.brier,
                "log_loss": report.log_loss,
                "auc": report.auc,
                "n_train": report.n_train,
                "n_val": report.n_val,
                "feature_count": len(fitted.feature_names),
                "fold_metrics": [dict(item) for item in report.fold_metrics],
            }
        )

    aggregate = summarise_reports(reports)
    return {
        "generated_at": iso_now(),
        "mode": "train",
        "backend": backend,
        "requested_device": device,
        "resolved_devices": sorted({str(item["resolved_device"]) for item in per_family}),
        "families": list(families),
        "samples_per_family": samples_per_family,
        "feature_count": feature_count,
        "seed": seed,
        "aggregate": aggregate,
        "family_reports": per_family,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = run_training(
        backend=str(args.backend),
        device=str(args.device),
        families_raw=str(args.families),
        samples_per_family=int(args.samples_per_family),
        feature_count=int(args.feature_count),
        seed=int(args.seed),
    )
    output_path = Path(args.output_path).expanduser()
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", output_path)

    print(f"mode={payload['mode']}")
    print(f"backend={payload['backend']}")
    print(f"requested_device={payload['requested_device']}")
    print(f"resolved_devices={','.join(payload['resolved_devices'])}")
    print(f"mean_brier={payload['aggregate']['mean_brier']:.6f}")
    print(f"mean_auc={payload['aggregate']['mean_auc']:.6f}")
    print(f"artifact={output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())