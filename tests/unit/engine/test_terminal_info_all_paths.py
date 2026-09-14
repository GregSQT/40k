"""Le bilan de fin d'episode est rendu par TOUTES les portes de terminaison, pas seulement une.

CE QUI A ETE MANQUE. `W40KEngine.step_with_mask` termine un episode par trois sorties :

  1. la garde « limite de tours atteinte », en tete de la fonction ;
  2. la sortie « pool vide -> advance_phase », quand le masque d'entree n'ouvre rien ;
  3. le retour normal, apres l'action.

Seule la troisieme batissait le bilan (`episode`, `tactical_data`, `deployment_mode`). Les deux
autres ecrivaient leur `info` a la main et n'y mettaient que `winner` / `win_method` — or
`ai/training_callbacks._handle_episode_end` EXIGE `tactical_data` (`require_key`) et
`ai/metrics_tracker.log_episode` exige `deployment_mode`. Un episode termine par l'une de ces
deux portes tuait donc le run d'entrainement, loin de sa cause.

POURQUOI AUCUN TEST NE L'A VU : les tests de terminaison existants n'exigeaient que `winner` et
`win_method` (`test_engine_full_loop`), et le seul qui verifie le bilan complet
(`test_forced_wait_not_penalised.test_episode_ending_inside_the_chain_still_reports_its_summary`)
passe par le retour normal — la seule porte qui n'etait pas cassee.

CE QUE CE FICHIER VERROUILLE : les trois portes rendent les MEMES cles de bilan. La liste est
recopiee ici plutot qu'importee de `TERMINAL_INFO_KEYS` : un test qui relit la constante qu'il
verrouille ne verrouille rien.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.macro_intents import ACTIVATE_SLOT_BASE
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    build_engine_config,
    build_game_rules,
    build_move_rules,
)

AGENT_KEY = "ArmageddonAgent_x1"

#: Le bilan que l'entrainement EXIGE : `ai/training_callbacks._handle_episode_end` pour les trois
#: premieres, `ai/metrics_tracker.log_episode` pour `deployment_mode`.
_EPISODE_SUMMARY_KEYS = ("episode", "tactical_data", "deployment_mode", "win_method", "winner")

#: Duree de bataille EFFECTIVE, lue sur l'etat du moteur : `get_effective_turn_limit` la tire de
#: `game_rules.max_turns` (source unique, cf. sa docstring), et non du training config. La coder
#: en dur ici ferait passer les tests a cote de la garde qu'ils visent le jour ou la regle change.

ALLY = (10, 10)
ALLY_2 = (10, 20)
ENEMY = (36, 10)


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter"}


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
    """Config de recompense MINIMALE mais COMPLETE pour un episode qui va jusqu'au bout.

    `objective_rewards` n'est pas decoratif : la recompense terminale le lit (`require_key`,
    `reward_calculator`), et ces tests sont les premiers de ce dossier a terminer reellement un
    episode. Les valeurs appartiennent au test — il verrouille la PRESENCE du bilan, pas un
    reglage d'agent.
    """
    return {
        AGENT_KEY: {
            "base_actions": {"wait": -0.1, "ranged_attack": 1.0},
            "objective_rewards": {
                "vp_margin_factor": 6.0,
                "on_objective_bonus": 5.0,
            },
            "situational_modifiers": {"win": 50.0, "lose": -50.0, "draw": 0.0},
        }
    }


def _make_engine() -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": build_game_rules(engagement_zone=1),
        "charge": {"charge_max_distance": 12},
        "move": build_move_rules(),
        "pve_mode": False,
        "controlled_agent": AGENT_KEY,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [_unit_cfg(10, 1, *ALLY), _unit_cfg(11, 1, *ALLY_2), _unit_cfg(2, 2, *ENEMY)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value=_rewards()):
        eng = W40KEngine(config=build_engine_config(config))
    eng.reset()
    eng.reward_calculator.rewards_config = _rewards()
    return eng


def _past_turn_limit(engine: W40KEngine) -> int:
    """Premier numero de tour AU-DELA de la duree de bataille (donc terminal)."""
    from engine.game_utils import get_effective_turn_limit

    limit = get_effective_turn_limit(engine.game_state)
    assert limit is not None, "bataille sans limite de tours : ces tests n'ont pas de porte a viser"
    return int(limit) + 1


def _legal_action(engine: W40KEngine) -> int:
    mask, _eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    legal = np.flatnonzero(np.asarray(mask, dtype=bool))
    assert legal.size > 0, "aucune action legale : le test ne pourrait rien jouer"
    return int(legal[0])


def _missing_summary_keys(info: Dict[str, Any]) -> List[str]:
    return [key for key in _EPISODE_SUMMARY_KEYS if key not in info]


# ─────────────────────────────────────────────────────────────────────────────
# Porte 1 — « limite de tours atteinte », la garde en tete de step_with_mask
#
# Le tour est pose AU-DELA de la duree de bataille, comme le fait la fin d'une vraie partie ; la
# garde le lit AVANT de traiter l'action et rend l'episode termine sans jamais atteindre le
# retour normal.
# ─────────────────────────────────────────────────────────────────────────────

def test_turn_limit_gate_reports_the_episode_summary():
    engine = _make_engine()
    engine.game_state["turn"] = _past_turn_limit(engine)

    _obs, _reward, terminated, truncated, info = engine.step(_legal_action(engine))

    # Premisse : c'est bien CETTE porte qui a repondu, pas le retour normal.
    assert info.get("turn_limit_exceeded") is True, (
        "la garde « limite de tours » n'a pas ete empruntee : le test verifierait une autre porte"
    )
    assert terminated and not truncated
    assert not _missing_summary_keys(info), (
        f"bilan d'episode perdu : {_missing_summary_keys(info)} absentes de l'`info` rendu. "
        "Cette porte construisait son `info` a la main, sans `_build_terminal_info`."
    )
    assert info["win_method"] is not None


def test_turn_limit_gate_tactical_data_is_the_episode_one():
    """VERT NON VACANT : le bilan porte les compteurs de L'EPISODE, pas un dict vide."""
    engine = _make_engine()
    engine.game_state["turn"] = _past_turn_limit(engine)

    _obs, _reward, _terminated, _truncated, info = engine.step(_legal_action(engine))

    tactical = info["tactical_data"]
    assert "victory_points_cumulative_episode" in tactical, (
        "tactical_data ne porte pas le bilan de victoire : `_build_terminal_info` n'a pas tourne"
    )
    assert tactical["total_ally_units"] == 2, tactical
    assert tactical["total_enemy_units"] == 1, tactical


# ─────────────────────────────────────────────────────────────────────────────
# Porte 2 — « pool vide -> advance_phase »
#
# Le masque d'ENTREE est vide (aucune escouade eligible, aucune action) : la fonction avance la
# phase et rend immediatement, sans jouer l'action. La partie se termine PENDANT cette
# transition — c'est le scenario decrit par la revue : la transition franchit la limite de tours.
# ─────────────────────────────────────────────────────────────────────────────

class _EmptyEntryMask:
    """Rend un masque d'entree VIDE une seule fois, puis laisse le vrai decodeur repondre.

    Le premier appel est celui de `step_with_mask` sur l'etat d'entree : c'est lui qui doit
    ouvrir la sortie anticipee. Les suivants (observation, masque de sortie) doivent decrire
    l'etat reel, sinon le test verrouillerait un moteur imaginaire.
    """

    def __init__(self, engine: W40KEngine) -> None:
        self._real = engine.action_decoder.get_squad_action_mask_and_eligible_units
        self.calls = 0

    def __call__(self, game_state):
        self.calls += 1
        if self.calls == 1:
            size = len(self._real(game_state)[0])
            return np.zeros(size, dtype=bool), []
        return self._real(game_state)


def _step_through_empty_entry_mask(engine: W40KEngine) -> Tuple[Dict[str, Any], bool, float]:
    """Joue UN step dont le masque d'entree est vide et dont la transition finit la partie.

    Rend aussi la recompense du step : cette porte doit VERSER ce que la transition change
    (ledger de marge, +-situational), cf. `test_pool_empty_gate_pays_the_ledger_and_the_outcome`.
    """
    empty_first = _EmptyEntryMask(engine)
    # La transition de phase franchit la limite de tours : `_check_game_over` la lit APRES
    # l'`advance_phase`, exactement comme en production quand le dernier tour se referme.
    real_advance = engine._advance_phase_and_drain

    def advance_then_end(action):
        out = real_advance(action)
        engine.game_state["turn"] = _past_turn_limit(engine)
        return out

    with patch.object(
        engine.action_decoder, "get_squad_action_mask_and_eligible_units", empty_first
    ), patch.object(engine, "_advance_phase_and_drain", advance_then_end):
        _obs, reward, terminated, _truncated, info = engine.step(ACTIVATE_SLOT_BASE)
    assert empty_first.calls >= 1, "le masque d'entree n'a pas ete demande"
    return info, terminated, float(reward)


def test_pool_empty_gate_reports_the_episode_summary():
    engine = _make_engine()

    info, terminated, _reward = _step_through_empty_entry_mask(engine)

    # Premisses : c'est bien cette porte, et l'episode s'est bien termine dedans.
    assert info.get("phase_auto_advanced") is True, (
        "la sortie « pool vide -> advance_phase » n'a pas ete empruntee"
    )
    assert terminated, "la transition n'a pas termine l'episode : le test ne verifie rien"
    assert not _missing_summary_keys(info), (
        f"bilan d'episode perdu : {_missing_summary_keys(info)} absentes de l'`info` rendu. "
        "Cette porte posait `winner` et `win_method` seuls."
    )


def test_pool_empty_gate_keeps_its_own_keys():
    """Le bilan s'AJOUTE aux cles de la porte, il ne les remplace pas."""
    engine = _make_engine()

    info, _terminated, _reward = _step_through_empty_entry_mask(engine)

    assert info["phase_auto_advanced"] is True
    assert "previous_phase" in info, "la porte a perdu la phase d'ou elle venait"


def test_pool_empty_gate_pays_the_ledger_and_the_outcome():
    """La porte verse le ledger de marge (B6) et le +-situational, et les COMPTE.

    Elle rendait 0.0 sans passer par `calculate_reward` : le dernier delta du ledger (les VP
    attribues par la transition qui termine la partie) n'etait jamais verse, `reset` remettait
    `vp_margin_paid` a 0, et la somme telescopique « facteur x marge finale » etait fausse sur
    cette porte — le +-situational y etait deja perdu. Rouge si la porte rend 0.0 a nouveau.
    """
    engine = _make_engine()
    controlled = int(engine.reward_calculator.config["controlled_player"])
    opponent = 2 if controlled == 1 else 1
    # Marge +15 non encore versee : le filigrane est a 0 (reset), comme si la transition qui
    # termine la partie venait d'attribuer ces VP.
    engine.game_state["victory_points"] = {controlled: 15, opponent: 0}
    assert engine.game_state["vp_margin_paid"] == 0

    info, terminated, reward = _step_through_empty_entry_mask(engine)

    assert terminated and info.get("phase_auto_advanced") is True
    assert info["winner"] == controlled, "premisse : marge +15 -> le joueur controle gagne"
    expected = 6.0 * 15 + 50.0  # ledger + situational `win`
    assert reward == pytest.approx(expected), (
        f"la porte a rendu {reward} au lieu de {expected} : ledger et/ou situational non verses"
    )
    assert engine.game_state["vp_margin_paid"] == 15, "filigrane non avance : le delta serait reverse"
    ventilation = info["tactical_data"]["reward_breakdown"]
    assert ventilation["vp_margin"] == pytest.approx(90.0), ventilation
    assert ventilation["situational"] == pytest.approx(50.0), ventilation
    assert info["episode"]["r"] == pytest.approx(expected), "accumulateur non alimente par la porte"


# ─────────────────────────────────────────────────────────────────────────────
# Les TROIS portes passent par la garde d'enumeration
#
# `_assert_terminal_keys_declared` vivait au seul retour normal : une cle terminale posee par une
# des deux sorties anticipees echappait au controle, et `_drain_forced_waits` ne l'aurait pas
# remontee quand l'episode se termine dans une chaine d'attentes forcees. Depuis la sortie unique
# de `step_with_mask`, la garde voit les trois. Le bilan est mocke ICI parce que
# `_build_terminal_info` appelle la garde lui-meme : sans mock, le test ne pourrait pas distinguer
# la garde de la sortie de celle de la construction.
# ─────────────────────────────────────────────────────────────────────────────

_UNDECLARED = "cle_terminale_non_declaree"


def _terminal_info_with_an_undeclared_key(engine: W40KEngine):
    real = engine._build_terminal_info

    def build():
        info = real()
        info[_UNDECLARED] = True
        return info

    return build


def test_turn_limit_gate_goes_through_the_enumeration_guard():
    engine = _make_engine()
    engine.game_state["turn"] = _past_turn_limit(engine)

    with patch.object(engine, "_build_terminal_info", _terminal_info_with_an_undeclared_key(engine)):
        with pytest.raises(RuntimeError, match=_UNDECLARED):
            engine.step(_legal_action(engine))


def test_pool_empty_gate_goes_through_the_enumeration_guard():
    engine = _make_engine()

    with patch.object(engine, "_build_terminal_info", _terminal_info_with_an_undeclared_key(engine)):
        with pytest.raises(RuntimeError, match=_UNDECLARED):
            _step_through_empty_entry_mask(engine)


# ─────────────────────────────────────────────────────────────────────────────
# Porte 3 — le retour normal, NON-REGRESSION
#
# C'est la seule porte qui batissait deja le bilan. Elle doit continuer, sinon l'extraction en
# methode aurait deplace le defaut au lieu de le corriger.
# ─────────────────────────────────────────────────────────────────────────────

def test_normal_return_still_reports_the_episode_summary():
    engine = _make_engine()
    terminated = False
    info: Dict[str, Any] = {}

    for step_index in range(200):
        if step_index == 3:
            # Fin par limite de tours DANS le flux normal : la transition de phase declenchee par
            # l'action lit `turn` et termine l'episode au retour normal.
            engine.game_state["turn"] = _past_turn_limit(engine) - 1
        _obs, _reward, terminated, _truncated, info = engine.step(_legal_action(engine))
        if terminated:
            break

    assert terminated, "l'episode ne s'est pas termine : le test ne verifie rien"
    assert info.get("turn_limit_exceeded") is None and info.get("phase_auto_advanced") is None, (
        "l'episode s'est termine par une sortie anticipee, pas par le retour normal"
    )
    assert not _missing_summary_keys(info), _missing_summary_keys(info)


# ─────────────────────────────────────────────────────────────────────────────
# La garde d'enumeration protege AUSSI les portes anticipees
# ─────────────────────────────────────────────────────────────────────────────

def test_terminal_info_keys_are_declared():
    """Une cle de bilan non declaree doit LEVER, sur n'importe quelle porte.

    C'est ce que la garde du point de sortie ne pouvait pas offrir : les sorties anticipees ne
    le traversent pas.
    """
    engine = _make_engine()
    engine.game_state["turn"] = _past_turn_limit(engine)

    with patch("engine.w40k_core.TERMINAL_INFO_KEYS", ("winner",)):
        with pytest.raises(RuntimeError, match="TERMINAL_INFO_KEYS"):
            engine.step(_legal_action(engine))
