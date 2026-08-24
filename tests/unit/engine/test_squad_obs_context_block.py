"""T2 — Bloc A du vecteur squad : score de mission, force d'usure, objectifs stricts.

Refonte V11 (Documentation/Implémentation/Implémenté/V11_audit_observation.md §9.2, §9.8, §10 Bloc A) :
- score de mission (victory points) mien/ennemi : sans lui l'agent ignore qui gagne ;
- VALUE cumulee vivante / VALUE de depart, par camp (force d'usure) ;
- controle d'objectif = LECTURE de `objective_controllers`, l'etat persistant du moteur, au lieu
  d'un calcul local sur l'ANCRE de chaque unite. Regle 14.02 : le controle est determine a la FIN
  de chaque phase et de chaque tour, pas en continu — l'observation ne recalcule donc RIEN ;
- bit de PRESENCE par objectif (distingue « conteste/vide » de « absent du scenario ») ;
- suppression du `try/except: pass` qui rendait tout objectif malforme silencieusement nul.

Contre-epreuves integrees :
- `test_objective_control_counts_models_not_anchor` : l'escouade a son ANCRE HORS zone et ses
  figurines DEDANS -> l'ancien encodeur repondait 0 (conteste), le moteur repond +1 ;
- `test_control_is_frozen_during_a_phase` : deplacer une figurine hors zone EN COURS de phase ne
  change pas le controle observe (14.02) ; il ne bouge qu'au franchissement de frontiere ;
- `test_malformed_objective_raises` : un objectif sans `id` doit lever, jamais sortir un canal
  nul en silence (fin du `try/except: pass`) ;
- `test_value_ratio_drops_when_models_die` : la valeur brute vivante seule ne dirait pas l'usure.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index, global_cont_index
from engine.phase_handlers.shared_utils import destroy_model, update_model_position
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

# Contexte GLOBAL (tenseurs d'entites V11 §0.30 T-D) : lu par NOM de feature, jamais par un
# index recopie — c'est ce qui permet au schema d'evoluer sans reecrire les tests.
CONT_VP_MINE = global_cont_index("my_victory_points")
CONT_VP_ENEMY = global_cont_index("enemy_victory_points")
CONT_VALUE_MINE = global_cont_index("my_value_ratio")
CONT_VALUE_ENEMY = global_cont_index("enemy_value_ratio")
BIN_OBJ_CONTROL = global_bin_index("objective_control_0")
BIN_OBJ_PRESENCE = global_bin_index("objective_present_0")


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, models: List[Dict[str, int]], oc: int, value: int) -> Dict[str, Any]:
    specs = [{"col": m["col"], "row": m["row"], "HP_CUR": 1, "HP_MAX": 1, "VALUE": value} for m in models]
    return {
        "id": uid, "player": player, "col": specs[0]["col"], "row": specs[0]["row"],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": oc, "VALUE": value * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


# Objectif : zone de 3x1 hexes autour de (30,20). L'escouade active a son ANCRE en (28,20),
# HORS de la zone, et ses deux autres figurines DEDANS -> contre-epreuve ancre vs figurines.
_OBJECTIVE_HEXES = [[30, 20], [31, 20], [32, 20]]


# Checkpoint 14.02 : `objective_control_check` vient de `build_engine_config` (valeurs reelles de
# config/game_config.json). Sans lui, aucun controle n'est jamais etabli.
_PRIMARY_OBJECTIVE = {
    "id": "objectives_control",
    "scoring": {"start_turn": 2, "max_points_per_turn": 15, "rules": []},
    "timing": {"default_phase": "command", "round5_second_player_phase": "fight"},
    "control": {
        "method": "oc_sum_greater",
        "control_method": "default",
        "tie_behavior": "no_control",
    },
}


def _cross_phase_boundary(engine, new_phase: str = "shoot") -> None:
    """Franchit une frontiere de phase et laisse le moteur reevaluer le controle (14.02).

    Passe par `_build_observation`, le point ou le moteur declenche
    `refresh_objective_control_on_boundary` — donc on teste la chaine reelle, pas un appel direct.
    """
    engine.game_state["phase"] = new_phase
    engine._build_observation()


def _config(objectives: Any = None) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    objs = [{"id": "obj1", "hexes": _OBJECTIVE_HEXES}] if objectives is None else objectives
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
            "max_turns": 5,
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "primary_objective": _PRIMARY_OBJECTIVE,
        # Sans scenario, les objectifs viennent de config["scenario_objectives"] (w40k_core:385).
        "scenario_objectives": objs,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, [{"col": 28, "row": 20}, {"col": 30, "row": 20}, {"col": 31, "row": 20}],
                      oc=2, value=10),
            _unit_cfg(2, 2, [{"col": 60, "row": 20}, {"col": 62, "row": 20}], oc=1, value=20),
        ],
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    return eng


@pytest.fixture
def engine():
    return _make_engine(_config())


def test_victory_points_are_observed(engine):
    """Le score de mission des DEUX camps entre dans l'observation, du point de vue du joueur actif."""
    gs = engine.game_state
    gs["victory_points"][1] = 7
    gs["victory_points"][2] = 3

    cont = engine.obs_builder.build_squad_observation(gs, "1")["global_cont"]
    assert cont[CONT_VP_MINE] == pytest.approx(7.0)
    assert cont[CONT_VP_ENEMY] == pytest.approx(3.0)

    # Vu du joueur 2, les roles s'inversent (l'observation est egocentrique).
    cont_p2 = engine.obs_builder.build_squad_observation(gs, "2")["global_cont"]
    assert cont_p2[CONT_VP_MINE] == pytest.approx(3.0)
    assert cont_p2[CONT_VP_ENEMY] == pytest.approx(7.0)


def test_value_ratio_drops_when_models_die(engine):
    """VALUE cumulee vivante / VALUE de depart : 1.0 a l'intact, decroit avec les pertes."""
    gs = engine.game_state
    cont = engine.obs_builder.build_squad_observation(gs, "1")["global_cont"]
    assert cont[CONT_VALUE_MINE] == pytest.approx(1.0)
    assert cont[CONT_VALUE_ENEMY] == pytest.approx(1.0)

    destroy_model(gs, "1#2", reason="combat")  # 1 figurine a 10 pts sur 30
    cont = engine.obs_builder.build_squad_observation(gs, "1")["global_cont"]
    assert cont[CONT_VALUE_MINE] == pytest.approx(2.0 / 3.0)
    assert cont[CONT_VALUE_ENEMY] == pytest.approx(1.0)

    destroy_model(gs, "2#1", reason="combat")  # 1 figurine ennemie a 20 pts sur 40
    cont = engine.obs_builder.build_squad_observation(gs, "1")["global_cont"]
    assert cont[CONT_VALUE_ENEMY] == pytest.approx(0.5)


def test_no_control_before_any_phase_boundary(engine):
    """Debut de bataille : aucune frontiere franchie -> aucun controleur (14.02), pas un defaut."""
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["global_bin"]
    assert binv[BIN_OBJ_CONTROL] == pytest.approx(0.0)
    assert binv[BIN_OBJ_PRESENCE] == pytest.approx(1.0)


def test_objective_control_counts_models_not_anchor(engine):
    """Regle 14.02 : ce sont les FIGURINES dans la zone qui comptent, pas l'ancre de l'unite.

    Contre-epreuve : l'ancre de l'escouade 1 est en (28,20), HORS de la zone. L'ancien encodeur
    local (ancre dans hex_set) ne voyait AUCUN OC et renvoyait 0 ; le moteur voit 2 figurines
    x OC 2 = 4 et renvoie +1.
    """
    gs = engine.game_state
    _cross_phase_boundary(engine)
    binv = engine.obs_builder.build_squad_observation(gs, "1")["global_bin"]
    assert binv[BIN_OBJ_CONTROL] == pytest.approx(1.0)
    # Vu de l'ennemi, le meme objectif est controle par l'adversaire.
    binv_p2 = engine.obs_builder.build_squad_observation(gs, "2")["global_bin"]
    assert binv_p2[BIN_OBJ_CONTROL] == pytest.approx(-1.0)


def test_control_is_frozen_during_a_phase(engine):
    """14.02 : le controle ne bouge PAS en cours de phase, seulement au franchissement.

    Contre-epreuve du calcul continu : on evacue les figurines de la zone SANS changer de phase.
    Un encodeur qui recalculerait a chaque observation passerait immediatement a 0 ; la regle
    (et le scoring des VP, qui lit la meme source) dit que le controle tient jusqu'a la fin de
    la phase. Il ne tombe qu'apres la frontiere suivante.
    """
    gs = engine.game_state
    _cross_phase_boundary(engine, "shoot")
    assert engine.obs_builder.build_squad_observation(gs, "1")["global_bin"][BIN_OBJ_CONTROL] == 1.0

    for mid in gs["squad_models"]["1"]:
        update_model_position(gs, mid, 5 + int(mid.split("#")[1]) * 2, 60)
    binv = engine.obs_builder.build_squad_observation(gs, "1")["global_bin"]
    assert binv[BIN_OBJ_CONTROL] == pytest.approx(1.0), "le controle doit tenir jusqu'a la fin de phase"

    _cross_phase_boundary(engine, "charge")
    binv = engine.obs_builder.build_squad_observation(gs, "1")["global_bin"]
    assert binv[BIN_OBJ_CONTROL] == pytest.approx(0.0), "apres la frontiere, plus personne ne controle"


def test_objective_presence_bits(engine):
    """1 objectif au scenario -> presence [1,0,0,0,0] ; le controle 0 des slots absents est alors lisible."""
    _cross_phase_boundary(engine)
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["global_bin"]
    presence = [float(v) for v in binv[BIN_OBJ_PRESENCE:BIN_OBJ_PRESENCE + 5]]
    assert presence == [1.0, 0.0, 0.0, 0.0, 0.0]
    absent_control = [float(v) for v in binv[BIN_OBJ_CONTROL + 1:BIN_OBJ_CONTROL + 5]]
    assert absent_control == [0.0, 0.0, 0.0, 0.0]


def test_contested_objective_is_zero_but_present():
    """Egalite d'OC = conteste : controle 0 ET presence 1 (les deux bits sont necessaires)."""
    cfg = _config()
    # L'ennemi entre dans la zone avec assez d'OC pour egaliser (2 figs OC 2 = 4 des deux cotes).
    cfg["units"][1] = _unit_cfg(
        2, 2, [{"col": 31, "row": 20}, {"col": 32, "row": 20}], oc=2, value=20
    )
    eng = _make_engine(cfg)
    _cross_phase_boundary(eng)
    binv = eng.obs_builder.build_squad_observation(eng.game_state, "1")["global_bin"]
    assert binv[BIN_OBJ_CONTROL] == pytest.approx(0.0)
    assert binv[BIN_OBJ_PRESENCE] == pytest.approx(1.0)


def test_malformed_objective_raises(engine):
    """Un objectif sans `id` doit LEVER (fin du `try/except: pass` qui zerotait le canal)."""
    from shared.data_validation import ConfigurationError

    gs = engine.game_state
    gs["objectives"] = [{"hexes": _OBJECTIVE_HEXES}]  # pas d'`id`
    with pytest.raises((ConfigurationError, KeyError)):
        engine.obs_builder.build_squad_observation(gs, "1")


def test_malformed_objective_raises_at_checkpoint(engine):
    """Un objectif sans `hexes` fait lever le CHECKPOINT moteur, il n'est pas ignore."""
    from shared.data_validation import ConfigurationError

    gs = engine.game_state
    gs["objectives"] = [{"id": "broken"}]
    with pytest.raises((ConfigurationError, KeyError, TypeError)):
        _cross_phase_boundary(engine)
