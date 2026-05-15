from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rl.agents import PPOSlicer, SACSizer
from rl.simulator import EnvConfig, ExecutionEnv
from rl.slippage import AlmgrenChrissCalibrator
from rl.types import TradeBlotter, TradeRecord
from scripts.ml_research_common import iso_now
from scripts.smc_atomic_write import atomic_write_text

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train synthetic PPO / SAC execution agents for offline GPU research.")
    parser.add_argument("--agent", choices=["ppo", "sac"], default="ppo")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default=os.getenv("SKIPP_RL_DEVICE", "auto"))
    parser.add_argument("--training-records", type=int, default=400)
    parser.add_argument("--total-timesteps", type=int, default=5000)
    parser.add_argument("--parent-qty", type=float, default=10_000.0)
    parser.add_argument("--horizon-steps", type=int, default=20)
    parser.add_argument("--order-type", choices=["limit_at_mid", "limit_aggressive", "market"], default="limit_at_mid")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output-path",
        default=str(REPO_ROOT / "artifacts" / "rl" / "research" / "latest.json"),
    )
    return parser


def _torch_cuda_available() -> bool:
    try:
        import torch  # type: ignore
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def _torch_runtime_details() -> dict[str, object]:
    try:
        import torch  # type: ignore
    except Exception:
        return {
            "installed": False,
            "version": None,
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_version": None,
        }
    return {
        "installed": True,
        "version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()),
        "cuda_version": str(torch.version.cuda) if torch.version.cuda is not None else None,
    }


def _resolve_training_device(requested: str) -> str:
    normalised = requested.strip().lower()
    if normalised not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"device must be one of auto/cpu/cuda, got {requested!r}")
    if normalised == "cpu":
        return "cpu"
    return "cuda" if _torch_cuda_available() else "cpu"


def _make_synthetic_blotter(n: int = 200, seed: int = 7) -> TradeBlotter:
    import numpy as np

    rng = np.random.default_rng(seed)
    blotter = TradeBlotter()
    for idx in range(n):
        side = 1 if rng.uniform() < 0.5 else -1
        qty = float(rng.uniform(100, 1_000))
        vol = float(rng.uniform(5_000, 50_000))
        dur = float(rng.uniform(5, 60))
        signed_pct = (side * qty) / vol
        slip_bps = 8.0 * abs(signed_pct) + 0.4 * dur ** 0.5 + float(rng.normal(0.0, 1.0))
        mid = 100.0
        fill = mid * (1.0 + side * slip_bps / 1e4)
        blotter.add(
            TradeRecord(
                order_id=f"o{idx}",
                family="BOS",
                side=side,
                quantity=qty,
                mid_at_signal=mid,
                fill_price=fill,
                volume_at_signal=vol,
                duration_s=dur,
            )
        )
    return blotter


def _build_agent(*, agent_name: str, device: str, seed: int, order_type: str):
    if agent_name == "ppo":
        return PPOSlicer(seed=seed, device=device, order_type=order_type)
    if agent_name == "sac":
        return SACSizer(seed=seed, device=device, order_type=order_type)
    raise ValueError(f"unsupported agent {agent_name!r}")


def run_training(
    *,
    agent_name: str,
    requested_device: str,
    training_records: int,
    total_timesteps: int,
    parent_qty: float,
    horizon_steps: int,
    order_type: str,
    seed: int,
) -> dict[str, object]:
    resolved_device = _resolve_training_device(requested_device)
    blotter = _make_synthetic_blotter(n=training_records, seed=seed)
    X, y = blotter.to_features_targets()
    calibrator = AlmgrenChrissCalibrator(prior_precision=0.01, noise_variance=4.0).fit(X, y)

    train_cfg = EnvConfig(
        parent_qty=parent_qty,
        horizon_steps=horizon_steps,
        default_order_type=order_type,
        seed=seed,
    )
    train_env = ExecutionEnv(cfg=train_cfg, slippage=calibrator)
    agent = _build_agent(agent_name=agent_name, device=resolved_device, seed=seed, order_type=order_type)
    agent.fit(train_env, total_timesteps=total_timesteps)

    eval_cfg = EnvConfig(
        parent_qty=parent_qty,
        horizon_steps=horizon_steps,
        default_order_type=order_type,
        seed=seed + 1,
    )
    eval_env = ExecutionEnv(cfg=eval_cfg, slippage=calibrator)
    obs, _info = eval_env.reset(seed=seed + 1)
    rewards: list[float] = []
    last_info: dict[str, object] | None = None
    for _ in range(horizon_steps):
        action = agent.predict(obs)
        obs, reward, terminated, truncated, info = eval_env.step(action)
        rewards.append(float(reward))
        last_info = info
        if terminated or truncated:
            break

    return {
        "generated_at": iso_now(),
        "agent": agent_name,
        "requested_device": requested_device,
        "resolved_device": str(getattr(agent, "resolved_device", resolved_device)),
        "torch": _torch_runtime_details(),
        "training_records": training_records,
        "total_timesteps": total_timesteps,
        "parent_qty": parent_qty,
        "horizon_steps": horizon_steps,
        "order_type": order_type,
        "seed": seed,
        "calibrator": {
            "mae": float(calibrator.mae(X, y)),
            "rmse": float(calibrator.rmse(X, y)),
        },
        "evaluation": {
            "steps": len(rewards),
            "total_reward": float(sum(rewards)),
            "implementation_shortfall_bps": float(eval_env.total_implementation_shortfall_bps),
            "realized_variance": float(eval_env.realized_variance),
            "remaining_qty": float((last_info or {}).get("remaining_qty", 0.0)),
        },
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = run_training(
        agent_name=str(args.agent),
        requested_device=str(args.device),
        training_records=int(args.training_records),
        total_timesteps=int(args.total_timesteps),
        parent_qty=float(args.parent_qty),
        horizon_steps=int(args.horizon_steps),
        order_type=str(args.order_type),
        seed=int(args.seed),
    )
    output_path = Path(args.output_path).expanduser()
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", output_path)

    print(f"agent={payload['agent']}")
    print(f"requested_device={payload['requested_device']}")
    print(f"resolved_device={payload['resolved_device']}")
    print(f"total_reward={payload['evaluation']['total_reward']:.6f}")
    print(f"implementation_shortfall_bps={payload['evaluation']['implementation_shortfall_bps']:.6f}")
    print(f"artifact={output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())