#!/usr/bin/env python3
"""Profile W40KEngine.step() with cProfile. Run from project root."""
import cProfile
import pstats
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports, get_scenario_list_for_phase
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader


def main():
    agent_key = "Infantry_Swarm_MeleeSwarm"
    W40KEngine, _ = setup_imports()
    cfg = get_config_loader()
    unit_registry = UnitRegistry()
    scenario_list = get_scenario_list_for_phase(cfg, agent_key, "default", scenario_type="training")
    if not scenario_list:
        scenario_list = get_scenario_list_for_phase(cfg, agent_key, "default", scenario_type="bot")
    if not scenario_list:
        raise FileNotFoundError(f"No scenario found for agent {agent_key}")
    scenario_file = scenario_list[0]

    env = W40KEngine(
        rewards_config=agent_key,
        training_config_name="default",
        controlled_agent=agent_key,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
    )
    obs, _ = env.reset()

    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(500):  # 500 steps pour des stats plus stables
        action = env.action_space.sample()
        obs, reward, term, trunc, info = env.step(action)
        if term or trunc:
            obs, _ = env.reset()
    profiler.disable()

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats(pstats.SortKey.CUMULATIVE)
    ps.print_stats(40)
    print(s.getvalue())


if __name__ == "__main__":
    main()
