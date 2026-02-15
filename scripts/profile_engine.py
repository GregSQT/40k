#!/usr/bin/env python3
"""Profile W40KEngine.step() with cProfile. Run from project root."""
import cProfile
import pstats
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports, get_agent_scenario_file
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader


def main():
    W40KEngine, _ = setup_imports()
    cfg = get_config_loader()
    unit_registry = UnitRegistry()
    scenario_file = get_agent_scenario_file(
        cfg, "SpaceMarine_Infantry_Troop_RangedSwarm", "default", "bot"
    )

    env = W40KEngine(
        rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
        training_config_name="default",
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
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
