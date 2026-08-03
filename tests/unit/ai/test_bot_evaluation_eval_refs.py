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


def test_le_scenario_materialise_reste_sous_la_racine_du_depot(tmp_path):
    """`W40KEngine.reset` journalise le chemin du scénario RELATIF à la racine du dépôt : c'est
    ce que le replay repasse à `/api/config/board` pour dessiner le décor de l'épisode. Un
    scénario matérialisé dans `/tmp` n'a pas de chemin relatif exprimable — le moteur refusait
    l'épisode et `--eval --step` sur le pool holdout mourait au premier reset.

    Le contrôle est fait ICI, à la source du chemin, plutôt que sur le message d'erreur du
    moteur : c'est l'emplacement du fichier qui est l'invariant, pas la formulation du refus.
    """
    import os

    scenario_path = _make_scenario(tmp_path)
    out_path = bot_evaluation._materialize_eval_scenario_refs(
        scenario_path=str(scenario_path),
        wall_ref="walls-33.json",
    )

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(bot_evaluation.__file__)))
    relative = os.path.relpath(os.path.abspath(out_path), repo_root).replace(os.sep, "/")

    try:
        assert not relative.startswith(".."), (
            f"scénario matérialisé hors du dépôt : {out_path} (racine {repo_root})"
        )
        # ET sous `config/` : `/api/config/board` refuse tout le reste (« scenario_file must be
        # under config/ »). Hors dépôt le moteur refusait l'épisode ; sous le dépôt mais hors
        # `config/`, l'épisode passait et c'est le replay qui repondait 500.
        assert relative.startswith("config/"), relative
        # Et le fichier survit au processus : le replay est ouvert APRES le run.
        assert os.path.isfile(out_path), out_path
    finally:
        bot_evaluation._cleanup_eval_ref_temp_dir()


def test_le_repertoire_de_travail_d_entrainement_reste_aussi_sous_la_racine():
    """JUMEAU : `ai/train.py` matérialise les mêmes scénarios (override `wall_ref`) pour
    l'entraînement, par un second répertoire. Il tombait dans `/tmp` pour la même raison, donc
    sous le même refus du moteur dès que le step logging est actif."""
    import os

    import ai.train as train

    path = train._get_wall_override_temp_dir()
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(train.__file__)))
        relative = os.path.relpath(path, repo_root).replace(os.sep, "/")
        assert relative.startswith("config/"), relative
    finally:
        train._cleanup_wall_override_temp_dir()
