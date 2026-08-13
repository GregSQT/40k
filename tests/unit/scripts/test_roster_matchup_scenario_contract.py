"""Verrouille le contrat V11 des scenarios ecrits par scripts/roster_matchup_stats.py.

Le script emettait `deployment_zone` / `wall_ref` / `objectives_ref` : `objectives_ref` est
rejetee par le moteur (`GameStateManager.load_units_from_scenario`) et les fichiers references
(walls-11.json, objectives-51.json) n'existent pas sous le board de la banque. Le contrat
vivant est celui de scripts/build_holdout_benchmark.py : `board_ref` + `terrain_ref`.
"""
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Cles refusees/mortes, telles que listees par LEGACY_KEYS dans
# scripts/migrate_scenario_bank_v11.py
LEGACY_KEYS = ("objectives", "objectives_ref", "objective_hexes", "deployment_zone", "wall_ref")


@pytest.fixture(scope="module")
def module():
    return charger_script("scripts/roster_matchup_stats.py")


def test_scenario_template_has_no_legacy_key(module):
    template = module._build_scenario_template("100pts", "44x60x5", "terrain-mc1.json")
    for key in LEGACY_KEYS:
        assert key not in template, f"cle legacy '{key}' encore emise par _build_scenario_template"


def test_scenario_template_declares_board_and_terrain(module):
    template = module._build_scenario_template("100pts", "44x60x5", "terrain-mc1.json")
    assert template["board_ref"] == "44x60x5"
    assert template["terrain_ref"] == "terrain-mc1.json"


def test_cli_defaults_point_to_existing_board_and_terrain(module):
    """Les defauts sont lus sur le PARSEUR construit, pas dans le texte du source."""
    parser = module._build_arg_parser()
    board_ref = parser.get_default("board_ref")
    terrain_ref = parser.get_default("terrain_ref")

    board_dir = PROJECT_ROOT / "config" / "board" / board_ref
    assert board_dir.is_dir(), f"board_ref par defaut inexistant: {board_dir}"
    terrain_path = board_dir / "terrain" / terrain_ref
    assert terrain_path.is_file(), f"terrain_ref par defaut inexistant: {terrain_path}"


def test_cli_defaults_survive_an_actual_parse(module):
    """Le parseur applique reellement ces defauts a des arguments parses."""
    args = module._build_arg_parser().parse_args(["--agent", "AnyAgent"])
    assert (PROJECT_ROOT / "config" / "board" / args.board_ref / "terrain" / args.terrain_ref).is_file()


def test_default_terrain_supplies_objectives_and_deployment_zones():
    """Sans deployment_zone ni objectives_ref, le terrain DOIT porter les deux."""
    import json

    terrain = json.loads(
        (PROJECT_ROOT / "config" / "board" / "44x60x5" / "terrain" / "terrain-mc1.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert any(area.get("objective") for area in terrain["terrain"]), "aucune aire objective:true"
    assert terrain["deployment_zones"], "aucune deployment_zones dans le terrain"


def test_cli_generation_defaults_match_the_shared_module(module):
    """Le script et `train.py --rule-checker` fabriquent le MEME artefact.

    Les defauts vivent en deux endroits — le parseur ici, les constantes du module partage la-bas.
    Deux valeurs differentes produiraient deux plateaux selon le point d'entree, sans que rien ne
    le signale : le scenario porte le board, pas le lanceur.
    """
    from shared import rule_checker_scenarios

    parser = module._build_arg_parser()
    assert parser.get_default("board_ref") == rule_checker_scenarios.DEFAULT_BOARD_REF
    assert parser.get_default("terrain_ref") == rule_checker_scenarios.DEFAULT_TERRAIN_REF
    assert parser.get_default("scale") == rule_checker_scenarios.DEFAULT_SCALE
