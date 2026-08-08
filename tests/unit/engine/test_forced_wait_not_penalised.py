"""Une attente FORCEE n'est pas penalisee — le masque n'ouvrait que `wait`.

POURQUOI. `base_actions.wait` (-0.1) sanctionne la passivite CHOISIE : « tu pouvais tirer ou
avancer, tu n'as rien fait ». Or le moteur active des escouades a qui il ne laisse ensuite AUCUNE
autre action, et leur appliquait la meme penalite. Volume mesure et cause : cf. la docstring de
`RewardCalculator._wait_reward`.

CE QUE CE FICHIER VERROUILLE, et pourquoi chaque cas y est :
  1. la situation « seule `wait` est ouverte » est CONSTRUITE (ennemi hors de portee), jamais
     esperee d'une graine — et le test l'affirme avant d'en dependre ;
  2. le chemin de PRODUCTION (`step_with_mask`) pose bien le drapeau : un correctif teste mais
     jamais appele ne corrige rien ;
  3. une attente CHOISIE reste penalisee — c'est la non-regression qui donne son sens au reste ;
  4. le drapeau est consomme, donc il ne fuit pas sur le step suivant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.macro_intents import ACTIVATE_SLOT_BASE
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    build_engine_config,
    build_game_rules,
    build_move_rules,
)

# Cle d'agent REELLE : `config_loader._resolve_agent_config_key` exige un repertoire existant sous
# `config/agents/`. La VALEUR de la penalite, elle, reste injectee par `_rewards()` — le test
# verrouille un comportement du moteur, il ne doit pas rougir si tu retouches ton reglage.
AGENT_KEY = "ArmageddonAgent"
WAIT_PENALTY = -0.1

# Les trois positions sont sur la MEME ligne : seule la distance change entre les deux cas, donc
# rien d'autre (LoS, decor, orientation) ne peut expliquer la difference de masque.
#   26 > RNG 24            -> aucune cible tirable, le masque n'ouvre que `wait` ;
#    6 : dans les 24, et hors zone d'engagement -> le tir s'ouvre A COTE de `wait`.
# Pas 2 : a cette distance les socles sont ENGAGES, et une unite engagee sans arme
# [CLOSE-QUARTERS] (10.06) n'entre pas du tout dans le pool de tir — elle ne serait donc jamais
# interrogee, ce qui ne testerait rien ici.
ALLY = (10, 10)
# DEUXIEME escouade alliee, et elle n'est pas decorative : avec une seule, son attente VIDE le pool
# de tir, le payload porte alors `reason: "pool_empty"` et `calculate_reward` le classe en reponse
# systeme — il rend 0.0 avant d'atteindre la branche `squad_wait`. Le test aurait vu 0.0 des deux
# cotes et verrouille... le court-circuit, pas le correctif.
ALLY_2 = (10, 20)
ENEMY_FAR = (36, 10)
ENEMY_NEAR = (16, 10)


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _rewards() -> Dict[str, Any]:
    """`wait` est la seule cle qui compte ici ; les autres existent pour que la config soit valide."""
    return {AGENT_KEY: {"base_actions": {"wait": WAIT_PENALTY, "ranged_attack": 1.0}}}


def _make_engine(
    enemy_pos: Tuple[int, int], *, ally_positions: Tuple[Tuple[int, int], ...]
) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        # `build_game_rules` / `build_move_rules` plutot qu'une section litterale :
        # `build_engine_config` REMPLACE la section fournie, donc un litteral fige une copie des
        # regles reelles — et le garde anti-runaway lit `max_actions_per_model_per_turn` et
        # `step_limit_margin` a chaque `step()`. Une regle ajoutee au moteur ne doit pas casser ce
        # fichier une cle a la fois.
        "game_rules": build_game_rules(engagement_zone=1),
        "charge": {"charge_max_distance": 12},
        "move": build_move_rules(),
        "pve_mode": False,
        "controlled_agent": AGENT_KEY,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": ([_unit_cfg(10 + i, 1, *p) for i, p in enumerate(ally_positions)]
                  + [_unit_cfg(2, 2, *enemy_pos)]),
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value=_rewards()):
        eng = W40KEngine(config=build_engine_config(config))
    eng.reset()
    # Poser `phase` ne suffit pas : c'est `shooting_phase_start` qui MONTE le pool d'activation,
    # et sans pool le masque est vide (aucune escouade active, donc aucune action — pas meme
    # `wait`). C'est ce montage qui reproduit l'etat de production que ce fichier verrouille :
    # une unite ARMEE entre dans le pool sans qu'on exige qu'elle ait une cible.
    from engine.phase_handlers.shooting_handlers import shooting_phase_start

    # Config de recompense posee explicitement : la valeur de la penalite appartient au TEST, pas
    # au reglage de l'agent — sans quoi ce verrou rougirait a chaque retouche de
    # `ArmageddonAgent_rewards_config.json`, ce qu'il n'a aucune raison de surveiller.
    eng.reward_calculator.rewards_config = _rewards()

    eng.game_state["phase"] = "shoot"
    shooting_phase_start(eng.game_state)
    return eng


def _legal(engine: W40KEngine) -> List[int]:
    mask, _eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    return [int(i) for i in np.flatnonzero(np.asarray(mask, dtype=bool))]


# ─────────────────────────────────────────────────────────────────────────────
# 1. La situation est CONSTRUITE, pas esperee
#
# Avec UNE seule alliee, le moteur n'a personne d'autre a activer : le masque de tir est donc
# observable directement, sans jouer de choix d'activation. Ces deux cas ne franchissent aucun
# `step()` — ils decrivent le MASQUE, qui est la premisse de tout le reste.
# ─────────────────────────────────────────────────────────────────────────────

def test_enemy_out_of_range_leaves_only_wait_open():
    """Ennemi hors de portee -> le masque de tir n'ouvre QUE `wait`.

    Sans cette assertion, les tests suivants pourraient porter sur un masque a plusieurs actions
    et ne rien verrouiller du tout (« vert vacant »).
    """
    assert _legal(_make_engine(ENEMY_FAR, ally_positions=(ALLY,))) == [SQUAD_ACTION_WAIT]


def test_enemy_in_range_opens_more_than_wait():
    """Le temoin : a portee, l'agent a un VRAI choix — donc l'attente y est une decision."""
    legal = _legal(_make_engine(ENEMY_NEAR, ally_positions=(ALLY,)))
    assert SQUAD_ACTION_WAIT in legal
    assert len(legal) > 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Le moteur joue l'attente forcee lui-meme, et elle ne coute rien
#
# DEUX alliees ici : avec une seule, son attente vide le pool de tir et le payload
# `reason: "pool_empty"` fait classer le step en reponse systeme (`calculate_reward`), qui rend
# 0.0 avant d'atteindre la branche `squad_wait`. Le test aurait alors verrouille le
# court-circuit, pas le correctif.
# ─────────────────────────────────────────────────────────────────────────────

def test_engine_plays_forced_waits_itself():
    """L'agent choisit qui activer, et ne revoit la main qu'apres la phase de tir.

    Les deux alliees sont hors de portee : leurs deux activations de tir ne peuvent qu'attendre.
    Le moteur les joue donc sans rendre la main, et la phase de tir est drainee en UN step d'agent.
    """
    engine = _make_engine(ENEMY_FAR, ally_positions=(ALLY, ALLY_2))
    assert _legal(engine) == [ACTIVATE_SLOT_BASE, ACTIVATE_SLOT_BASE + 1]
    engine.step(ACTIVATE_SLOT_BASE)
    assert engine.game_state["phase"] != "shoot", (
        "la phase de tir n'a pas ete drainee : le moteur a rendu la main sur une attente forcee"
    )


def test_forced_waits_cost_nothing():
    engine = _make_engine(ENEMY_FAR, ally_positions=(ALLY, ALLY_2))
    _obs, reward, _term, _trunc, _info = engine.step(ACTIVATE_SLOT_BASE)
    assert reward == pytest.approx(0.0), (
        f"le step a coute {reward} : la penalite de passivite s'applique encore aux attentes que "
        "le moteur a imposees"
    )


def test_chosen_wait_is_still_penalised():
    """NON-REGRESSION : le correctif ne desarme pas la penalite en general.

    A portee, le masque ouvre le tir A COTE de `wait` : le moteur n'auto-joue rien, il rend la
    main, et l'attente que l'agent choisit alors reste payante.
    """
    engine = _make_engine(ENEMY_NEAR, ally_positions=(ALLY, ALLY_2))
    engine.step(ACTIVATE_SLOT_BASE)
    assert len(_legal(engine)) > 1  # precondition : l'agent a une alternative
    _obs, reward, _term, _trunc, _info = engine.step(SQUAD_ACTION_WAIT)
    assert reward == pytest.approx(WAIT_PENALTY), (
        f"une attente CHOISIE a rapporte {reward} au lieu de {WAIT_PENALTY}"
    )


def test_info_still_describes_the_agent_action():
    """`info` decrit l'action de l'AGENT, pas l'attente que le moteur s'est jouee.

    `ai/env_wrappers.AGENT_STEP_INFO_KEYS` (`action`, `success`, `phase`, `intent_value`,
    `zone_control`, `charge_succeeded`, `is_controlled_action`) est preleve APRES le retour du
    moteur : si l'auto-jeu ecrasait `info`, la DERNIERE action reelle de chaque phase deviendrait
    invisible aux metriques — dont le `zone_intent` qui, en mettant
    `zone_intent_free_steps_remaining` a 0, produit justement un masque de sortie reduit a `wait`.
    """
    engine = _make_engine(ENEMY_FAR, ally_positions=(ALLY, ALLY_2))
    _obs, _r, _term, _trunc, info = engine.step(ACTIVATE_SLOT_BASE)
    assert info["action"] != "squad_wait", (
        "l'auto-jeu a ecrase l'info du step de l'agent avec celle de son attente"
    )
    assert info["acting_player"] == 1


def test_autoplay_stops_at_the_turn_boundary():
    """L'auto-jeu ne joue jamais pour l'ADVERSAIRE.

    Sans cette borne, une chaine franchissant la frontiere de tour ferait jouer les attentes du
    joueur 2 dans le step du joueur 1, et `info` rendrait son `acting_player`.
    """
    engine = _make_engine(ENEMY_FAR, ally_positions=(ALLY, ALLY_2))
    player_before = engine.game_state["current_player"]
    _obs, _r, _term, _trunc, info = engine.step(ACTIVATE_SLOT_BASE)
    assert info["acting_player"] == player_before
    # Le moteur a pu changer de joueur en fin de chaine, mais aucun step n'a ete joue POUR lui :
    # c'est `acting_player` qui le prouve, pas l'etat courant.


def test_flag_does_not_leak_to_the_next_step():
    """La cle est consommee a chaque step : elle ne peut pas faire taire la penalite suivante."""
    engine = _make_engine(ENEMY_NEAR, ally_positions=(ALLY, ALLY_2))
    engine.step(ACTIVATE_SLOT_BASE)
    engine.step(SQUAD_ACTION_WAIT)
    assert "_wait_was_forced" not in engine.game_state
