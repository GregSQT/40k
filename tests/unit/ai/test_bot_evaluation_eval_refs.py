"""T3 (V11_agent_rework.md) — 1ter : le chemin d'éval holdout ne doit plus émettre
`objectives_ref` (clé rejetée par le moteur, objectifs désormais portés par le terrain).
"""
import json
from pathlib import Path

import ai.bot_evaluation as bot_evaluation


def _make_scenario(tmp_path: Path) -> Path:
    scenario_dir = tmp_path / "agents" / "CoreAgent" / "scenarios" / "holdout_hard"
    scenario_dir.mkdir(parents=True)
    scenario_path = scenario_dir / "scenario_bot-01.json"
    scenario_path.write_text(
        json.dumps({
            "wall_ref": "random",
            "objectives_ref": "objectives-51.json",
            "objectives": [{"id": 1, "name": "A"}],
            "objective_hexes": [[1, 2]],
            "primary_objectives": [1],
        }),
        encoding="utf-8",
    )
    return scenario_path


def test_materialize_eval_scenario_refs_drops_objectives_ref(tmp_path):
    scenario_path = _make_scenario(tmp_path)
    out_path = bot_evaluation._materialize_eval_scenario_refs(
        scenario_path=str(scenario_path),
        wall_ref="walls-33.json",
    )
    with open(out_path, "r", encoding="utf-8") as f:
        materialized = json.load(f)

    assert materialized["wall_ref"] == "walls-33.json"
    # Les clés legacy objectifs ne sont plus émises (contrat terrain, rejetées par le moteur).
    assert "objectives_ref" not in materialized
    assert "objectives" not in materialized
    assert "objective_hexes" not in materialized


def test_materialize_eval_scenario_refs_bad_wall_ref_raises(tmp_path):
    scenario_path = _make_scenario(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="Invalid eval wall_ref"):
        bot_evaluation._materialize_eval_scenario_refs(
            scenario_path=str(scenario_path),
            wall_ref="   ",
        )
