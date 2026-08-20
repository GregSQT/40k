"""Tests — echantillonnage des objectifs tenus (01_VP/e_objectives_held, d_objectives_held_diff).

CE QUI A ETE MANQUE, ET POURQUOI AUCUN TEST NE L'A VU.

L'echantillonnage vivait dans ``RewardCalculator._calculate_objective_reward_per_turn`` : une
MESURE branchee sur un calcul de RECOMPENSE, donc soumise a ses gardes de sortie. La garde
d'entree (``phase_transition`` + ``next_phase == "move"``) n'est jamais vraie pour un resultat
d'ACTION, et une transition de phase pure repart en ``is_system_response`` bien avant d'y
arriver. Mesure sur 3 episodes complets : 215 appels, 0 echantillon. Les deux courbes n'ont
donc recu AUCUN point en 50 000 episodes — sans erreur, parce que leurs consommateurs etaient
gardes par ``if isinstance(samples, list) and samples``. Une liste vide ne se distingue pas
d'un agent qui ne tient aucun objectif : c'est le motif « vert vacant » exact.

CE QUE CES TESTS VERROUILLENT.

1. Les listes sont NON VIDES sur un episode joue jusqu'au bout (ce que l'ancien code ne
   produisait pas). Une assertion de longueur seule serait faible : elle passerait avec des
   echantillons pris n'importe ou.
2. Les echantillons REPRODUISENT EXACTEMENT les VP attribues, en rejouant les trois regles du
   primaire (>=1, >=2, plus que l'adversaire, plafond par tour). C'est la que le test cesse de
   se regarder lui-meme : il relie la mesure au score reellement inscrit dans game_state.
   Un echantillon pris au mauvais instant (avant scoring, apres deplacement, au passage de
   l'adversaire) casse cette egalite.
3. Le SIEGE : un echantillonnage code en dur sur le joueur 1 passerait tout le reste.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

#: Copie du primaire de production (config/primary_objective/*/Objectives_Control.json).
#: Inline et non chargee par le config_loader : le test doit dependre des REGLES qu'il rejoue
#: ci-dessous, pas du fichier de plateau courant.
PRIMARY_OBJECTIVE: Dict[str, Any] = {
    "id": "objectives_control",
    "scoring": {
        "start_turn": 2,
        "max_points_per_turn": 15,
        "rules": [
            {"id": "control_at_least_one", "points": 5, "condition": "control_at_least_one"},
            {"id": "control_at_least_two", "points": 5, "condition": "control_at_least_two"},
            {"id": "control_more_than_opponent", "points": 5, "condition": "control_more_than_opponent"},
        ],
    },
    "timing": {"default_phase": "command", "round5_second_player_phase": "fight"},
    "control": {"method": "oc_sum_greater", "control_method": "default", "tie_behavior": "no_control"},
}


def _weapon(rng: int) -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": rng,
            "WEAPON_RULES": [], "display_name": "Test Weapon"}


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 6, "HP_MAX": 6, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon(24)], "CC_WEAPONS": [_weapon(1)],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _config(controlled_player: int) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {
            "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0, "wall_hexes": [],
            # TROIS objectifs : avec un seul, la regle « >=2 » ne serait jamais evaluee et
            # l'egalite VP/echantillons tiendrait sans rien prouver de ce plafond.
            "objectives": [
                {"id": "obj1", "name": "Alpha", "hexes": [[4, 6]]},
                {"id": "obj2", "name": "Beta", "hexes": [[7, 6]]},
                {"id": "obj3", "name": "Gamma", "hexes": [[10, 6]]},
            ],
            "inches_to_subhex": 1,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "max_turns": 5, "max_actions_per_model_per_turn": 7, "step_limit_margin": 1.5,
            "pile_in_target_range": 5, "consolidation_trigger_range": 3,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 12},
        # Regle 14.02 : `objective_control_check` vient de `build_engine_config` (valeurs reelles
        # de `config/game_config.json`). Sans elle, `run_objective_control_checkpoint` levait —
        # avant, il SORTAIT en silence et ces deux fichiers, qui PRETENDENT mesurer l'axe de
        # controle, passaient pour la mauvaise raison.
        "pve_mode": False,
        "controlled_player": controlled_player,
        # `scenario_objectives` et non la cle `objectives` du board : sur la branche
        # `config=`, c'est CETTE cle que W40KEngine reporte dans game_state["objectives"]
        # (w40k_core.py:341). La renseigner cote board seulement laisse la liste vide, donc
        # zero objectif a controler et une mesure qui ne mesure rien.
        "scenario_objectives": [
            {"id": "obj1", "hexes": [[4, 6]]},
            {"id": "obj2", "hexes": [[7, 6]]},
            {"id": "obj3", "hexes": [[10, 6]]},
        ],
        "primary_objective": PRIMARY_OBJECTIVE,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        # Deux figurines par camp POSEES SUR des objectifs : le controle est acquis par
        # construction, pas espere d'un deplacement aleatoire.
        "units": [
            _unit(1, 1, 4, 6), _unit(2, 1, 7, 6),
            _unit(3, 2, 10, 6), _unit(4, 2, 10, 7),
        ],
    }


@pytest.fixture(autouse=True)
def _stub_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recompenses et observation neutralisees : elles ne pesent pas sur l'echantillonnage.

    C'est aussi le controle implicite le plus important de ce fichier : la mesure doit tenir
    alors que TOUT le calcul de recompense est court-circuite. C'est precisement ce que
    l'ancienne implementation ne pouvait pas faire.
    """
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    # settle_zone_intent_declaration est appele DIRECTEMENT par la phase command (hors
    # calculate_reward) et exige une config d'agent complete : encore de la recompense.
    monkeypatch.setattr(RewardCalculator, "settle_zone_intent_declaration", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self, *_a, **_k: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )


def _build(controlled_player: int) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(_config(controlled_player)), gym_training_mode=True, quiet=True)
    engine.reset()
    return engine


def _run_to_end(engine: W40KEngine, pick: Callable[[Any], int]) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    for _ in range(4000):
        mask = engine.get_action_mask()
        legal = np.flatnonzero(mask)
        action = int(pick(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "l'episode ne s'est pas termine : pas de tactical_data"
    return info["tactical_data"]


def _episode(controlled_player: int, seed: int) -> tuple[W40KEngine, Dict[str, Any]]:
    engine = _build(controlled_player)
    rng = np.random.default_rng(seed)
    return engine, _run_to_end(engine, lambda legal: rng.choice(legal))


def _hold_position_episode(controlled_player: int) -> tuple[W40KEngine, Dict[str, Any]]:
    """Episode ou personne ne bouge : le controle du deploiement est CONSERVE tour apres tour.

    Necessaire pour que la mesure porte : sur actions aleatoires, les figurines quittent les
    objectifs et tous les echantillons valent 0 — l'egalite VP/echantillons tiendrait alors a
    0 = 0 sans jamais exercer une seule des trois regles de score.
    """
    engine = _build(controlled_player)

    def stay(legal: Any) -> int:
        return SQUAD_ACTION_WAIT if SQUAD_ACTION_WAIT in legal else int(legal[0])

    return engine, _run_to_end(engine, stay)


def _points_from_samples(mine: List[float], theirs: List[float]) -> float:
    """Rejoue les trois regles du primaire sur les echantillons, plafond par tour inclus."""
    total = 0.0
    for my_count, their_count in zip(mine, theirs):
        turn_points = 0.0
        if my_count >= 1:
            turn_points += 5.0
        if my_count >= 2:
            turn_points += 5.0
        if my_count > their_count:
            turn_points += 5.0
        total += min(turn_points, 15.0)
    return total


_SEEDS = [3, 7, 11, 23, 41]


@pytest.mark.parametrize("seed", _SEEDS)
def test_samples_are_collected_on_every_scoring_turn(seed: int) -> None:
    """Un echantillon par tour marque, des deux cotes, et les listes ne sont PAS vides.

    max_turns=5 et start_turn=2 : le joueur controle marque aux tours 2, 3, 4 et 5, soit
    exactement 4 echantillons. L'ancienne implementation en produisait 0.
    """
    _engine, tactical = _episode(controlled_player=1, seed=seed)

    mine = tactical["controlled_objective_samples"]
    theirs = tactical["opponent_objective_samples"]

    assert len(mine) == 4, f"attendu un echantillon par tour marque (2..5), obtenu {mine}"
    assert len(theirs) == len(mine)
    assert all(count >= 0 for count in mine)


def test_samples_measure_the_objectives_actually_held() -> None:
    """MESURE NON VACANTE : sur position tenue, les echantillons valent le controle reel.

    Montage : le camp controle tient obj1 et obj2 (une figurine sur chacun), l'adversaire tient
    obj3. Personne ne bouge, donc a chacun des 4 tours marquants : 2 pour moi, 1 pour lui — et
    les trois regles de score sont exercees (>=1, >=2, plus que l'adversaire), soit le plafond
    de 15 par tour. Un controle qui vaudrait 0 partout, comme sur actions aleatoires, ferait
    passer l'egalite VP/echantillons sans rien mesurer.
    """
    engine, tactical = _hold_position_episode(controlled_player=1)

    assert tactical["controlled_objective_samples"] == [2.0, 2.0, 2.0, 2.0]
    assert tactical["opponent_objective_samples"] == [1.0, 1.0, 1.0, 1.0]
    assert float(engine.game_state["victory_points"][1]) == pytest.approx(60.0)


@pytest.mark.parametrize("seed", _SEEDS)
def test_samples_reproduce_the_victory_points_actually_awarded(seed: int) -> None:
    """Egalite exacte entre les echantillons et les VP inscrits dans game_state.

    Relie la mesure au score reel : un echantillon pris au mauvais instant, ou pris au passage
    de l'ADVERSAIRE, casse cette egalite. Vraie meme a zero VP.
    """
    engine, tactical = _episode(controlled_player=1, seed=seed)

    awarded = float(engine.game_state["victory_points"][1])
    assert _points_from_samples(
        tactical["controlled_objective_samples"],
        tactical["opponent_objective_samples"],
    ) == pytest.approx(awarded)


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_samples_follow_the_controlled_seat(controlled_player: int) -> None:
    """Le siege compte : les echantillons suivent l'agent controle, pas un camp fixe."""
    engine, tactical = _episode(controlled_player, seed=5)

    awarded = float(engine.game_state["victory_points"][controlled_player])
    assert _points_from_samples(
        tactical["controlled_objective_samples"],
        tactical["opponent_objective_samples"],
    ) == pytest.approx(awarded)
