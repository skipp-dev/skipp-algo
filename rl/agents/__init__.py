"""RL agents (PPO slicer + SAC sizer).

Heavy backends gated via ``try``-import on ``stable_baselines3`` and
``gymnasium``. When absent, ``available`` is False and the trainer raises a
clear ``RuntimeError`` at instantiation time. Inference-time stubs
(``EpsilonGreedyTwapAgent``) are pure-numpy and serve as the always-on
fallback so a live consumer always has a callable agent.
"""
from rl.agents.epsilon_greedy_twap import EpsilonGreedyTwapAgent
from rl.agents.ppo_slicer import PPOSlicer
from rl.agents.sac_sizer import SACSizer

__all__ = ["EpsilonGreedyTwapAgent", "PPOSlicer", "SACSizer"]
