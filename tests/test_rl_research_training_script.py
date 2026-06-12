from __future__ import annotations

import pytest

import scripts.run_rl_research_training as rl_script
from rl.simulator import ExecutionEnv


def test_parser_defaults() -> None:
    args = rl_script.build_parser().parse_args([])
    assert args.agent == "ppo"
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/rl/research/latest.json")


def test_synthetic_blotter_produces_feature_matrix() -> None:
    blotter = rl_script._make_synthetic_blotter(n=25, seed=5)
    X, y = blotter.to_features_targets()
    assert X.shape == (25, 3)
    assert y.shape == (25,)


def test_resolve_training_device_uses_cpu_when_cuda_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rl_script, "_torch_cuda_available", lambda: False)
    assert rl_script._resolve_training_device("cuda") == "cpu"
    assert rl_script._resolve_training_device("auto") == "cpu"


def test_resolve_training_device_uses_cuda_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rl_script, "_torch_cuda_available", lambda: True)
    assert rl_script._resolve_training_device("cuda") == "cuda"
    assert rl_script._resolve_training_device("auto") == "cuda"


def test_run_training_wires_agent_to_execution_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        resolved_device = "cpu"

        def fit(self, env, total_timesteps: int) -> None:
            captured["fit_env"] = env
            captured["timesteps"] = total_timesteps

        def predict(self, obs):
            return 0.25

    monkeypatch.setattr(rl_script, "_resolve_training_device", lambda requested: "cpu")
    monkeypatch.setattr(rl_script, "_build_agent", lambda **kwargs: FakeAgent())

    payload = rl_script.run_training(
        agent_name="ppo",
        requested_device="auto",
        training_records=50,
        total_timesteps=64,
        parent_qty=1000.0,
        horizon_steps=4,
        order_type="market",
        seed=3,
    )

    fit_env = captured["fit_env"]
    assert isinstance(fit_env, ExecutionEnv)
    assert fit_env.cfg.default_order_type == "market"
    assert captured["timesteps"] == 64
    assert payload["evaluation"]["steps"] > 0


def test_run_training_preserves_requested_device_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAgent:
        resolved_device = "cpu"

        def fit(self, env, total_timesteps: int) -> None:
            return None

        def predict(self, obs):
            return 0.5

    monkeypatch.setattr(rl_script, "_resolve_training_device", lambda requested: "cpu")
    monkeypatch.setattr(rl_script, "_build_agent", lambda **kwargs: FakeAgent())

    payload = rl_script.run_training(
        agent_name="ppo",
        requested_device="cuda",
        training_records=40,
        total_timesteps=32,
        parent_qty=1000.0,
        horizon_steps=4,
        order_type="market",
        seed=13,
    )

    assert payload["requested_device"] == "cuda"
    assert payload["resolved_device"] == "cpu"
