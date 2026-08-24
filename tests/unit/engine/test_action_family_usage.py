"""Tests — instrumentation de l'USAGE par famille d'action (`action_family_counts`).

POURQUOI CETTE MESURE EXISTE

Le tableau de bord publiait `valid_actions` / `invalid_actions` agreges : de quoi savoir si
l'agent joue des coups legaux, jamais de quoi savoir QUELLE DECISION il exerce. Une dimension
d'action jamais choisie (mal masquee, mal observee, jamais preferee) ou toujours choisie
(degeneree) est un defaut que le win-rate ne distingue pas d'un agent simplement faible. Sans
cette ventilation, un lot de tranches P3 livre d'un bloc n'est pas diagnosticable : une
regression du `combined` ne designe aucun coupable.

LE PIEGE QUE CES TESTS VERROUILLENT

`DEPLOY_SLOT_BASE = 4` et `MOVE_CELL_BASE = 0` : les ids 4-8 sont a la fois les cinq strategies
de deploiement et des cellules de move. La famille d'une action DEPEND donc de la phase ou elle
a ete jouee, et cette phase doit etre lue AVANT l'execution — l'action peut la faire avancer.
Classer apres coup rangerait un deploiement dans la phase suivante.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List
from unittest.mock import patch

import numpy as np
import pytest

from engine import macro_intents as mi
from engine.macro_intents import ACTION_FAMILIES, action_family
from engine.observation_builder import ObservationBuilder
from engine.reward_calculator import RewardCalculator
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


# ─────────────────────────────────────────────────────────────────────────────
# Le classifieur, sur le layout REEL (aucun litteral recopie)
# ─────────────────────────────────────────────────────────────────────────────

def test_chaque_famille_est_atteinte_par_au_moins_un_id():
    """Aucune famille declaree n'est inatteignable — une famille morte est un piege muet."""
    reached = {
        action_family(mi.MOVE_CELL_BASE, "move"),
        action_family(mi.ACTION_WAIT, "move"),
        action_family(mi.SHOOT_SLOT_BASE, "shoot"),
        action_family(mi.CHARGE_SLOT_BASE, "charge"),
        # L9 (2026-08-20) : paires de charge, DANS le bloc charge.
        action_family(mi.CHARGE_PAIR_SLOT_BASE, "charge"),
        action_family(mi.FIGHT_SLOT_BASE, "fight"),
        action_family(mi.ACTION_FIGHT_NO_TARGET, "fight"),
        action_family(mi.BASE_ZONE_INTENT, "move"),
        action_family(mi.CHOICE_BASE, "move"),
        action_family(mi.OATH_SLOT_BASE, "move"),
        # V11 §0.48 `L2` — comme les CHOICE et Oath, la phase ne desambigue rien : le masque est
        # EXCLUSIF quand le choix d'activation est pose, l'id se classe donc seul.
        action_family(mi.ACTIVATE_SLOT_BASE, "move"),
        action_family(mi.DEPLOY_SLOT_BASE, "deployment"),
        action_family(mi.SHOOT_INDIRECT_SLOT_BASE, "shoot"),
        action_family(mi.FIGHT_WEAPON_SLOT_BASE, "fight"),
    }
    assert reached == set(ACTION_FAMILIES)


@pytest.mark.parametrize("slot", list(mi.DEPLOY_SLOTS))
def test_les_ids_4_8_dependent_de_la_phase(slot: int):
    """Le recouvrement deploiement / cellules de move est la raison d'etre du parametre `phase`."""
    assert action_family(slot, "deployment") == "deploy_slot"
    assert action_family(slot, "move") == "move_cell"


def test_une_action_hors_slots_en_phase_deployment_leve():
    """Le masque de deploiement n'ouvre QUE 4-8 : autre chose est une incoherence, pas un cas."""
    with pytest.raises(ValueError, match="deployment"):
        action_family(mi.SHOOT_SLOT_BASE, "deployment")


@pytest.mark.parametrize("bad", [-1, mi.TOTAL_ACTION_SIZE, mi.TOTAL_ACTION_SIZE + 10])
def test_un_id_hors_espace_daction_leve(bad: int):
    with pytest.raises(ValueError, match="hors espace"):
        action_family(bad, "move")


def test_les_bornes_de_chaque_plage_sont_dans_la_bonne_famille():
    """Verrou d'ARITHMETIQUE : un decalage d'un cran aux bornes ne passe pas."""
    assert action_family(mi.MOVE_CELL_BASE + mi.MOVE_CELL_COUNT - 1, "move") == "move_cell"
    assert action_family(mi.SHOOT_SLOT_BASE + mi.SHOOT_SLOT_COUNT - 1, "shoot") == "shoot_slot"
    assert action_family(mi.CHARGE_SLOT_BASE + mi.CHARGE_SLOT_COUNT - 1, "charge") == "charge_slot"
    assert action_family(mi.CHARGE_PAIR_SLOT_BASE + mi.CHARGE_PAIR_SLOT_COUNT - 1, "charge") == "charge_pair_slot"
    assert action_family(mi.FIGHT_SLOT_BASE + mi.FIGHT_SLOT_COUNT - 1, "fight") == "fight_slot"
    assert action_family(mi.SHOOT_INDIRECT_SLOT_BASE + mi.SHOOT_INDIRECT_SLOT_COUNT - 1, "shoot") == "shoot_indirect_slot"
    assert action_family(mi.CHOICE_BASE + mi.CHOICE_COUNT - 1, "move") == "choice"


# ─────────────────────────────────────────────────────────────────────────────
# Le comptage moteur — le chemin de PRODUCTION, pas la fonction pure
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    weapon = {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": 24,
              "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test"}
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 6, "HP_MAX": 6, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [dict(weapon)], "CC_WEAPONS": [dict(weapon, RNG=1)],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "battle_shocked": False,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {
            "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0, "wall_hexes": [],
            "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[7, 6]]}],
            "inches_to_subhex": 1,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "max_turns": 5, "max_actions_per_model_per_turn": 7, "step_limit_margin": 1.5,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": units,
    }


@pytest.fixture(autouse=True)
def _stub_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les recompenses exigent une config d'agent ; elles ne pesent pas sur les compteurs."""
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self, *_a, **_k: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )


def _play(pick: Callable[[Any], int]) -> Dict[str, Any]:
    units = [_unit(1, 1, 3, 6), _unit(2, 1, 4, 6), _unit(3, 2, 11, 6), _unit(4, 2, 12, 6)]
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(_config(units)), gym_training_mode=True, quiet=True)
    engine.reset()
    info: Dict[str, Any] = {}
    for _ in range(4000):
        mask = engine.get_action_mask()
        legal = np.flatnonzero(mask)
        action = int(pick(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "l'episode ne s'est pas termine"
    return info["tactical_data"]


def test_le_moteur_ventile_les_actions_du_camp_controle():
    """VERT VACANT ecarte : on exige un total NON NUL, pas seulement une egalite."""
    tactical = _play(lambda legal: legal[0])
    counts = tactical["action_family_counts"]

    assert set(counts) == set(ACTION_FAMILIES), "familles declarees et comptees divergent"
    total = sum(counts.values())
    assert total > 0, "aucune action ventilee : le compteur ne regarde rien"
    assert total == tactical["total_actions"], (
        "la ventilation doit couvrir EXACTEMENT les actions du camp controle : "
        f"{total} ventilees pour {tactical['total_actions']} comptees"
    )


def test_sans_phase_de_deploiement_aucune_action_nest_classee_deploy():
    """Contre-epreuve du recouvrement 4-8, sur le chemin de PRODUCTION.

    Un moteur construit depuis une config (sans fichier de scenario) demarre en placement FIXE :
    aucune phase de deploiement n'est jouee. Les ids 4-8 y sont donc TOUS des cellules de move.
    Un classifieur qui les mapperait sur `deploy_slot` sans regarder la phase — le defaut que
    `pre_action_phase` evite — se trahit ici.
    """
    tactical = _play(lambda legal: legal[0])
    counts = tactical["action_family_counts"]
    assert counts["deploy_slot"] == 0, (
        "des actions classees `deploy_slot` alors qu'aucune phase de deploiement n'a ete jouee : "
        "la famille est deduite de l'id seul, pas de la phase"
    )
    assert counts["move_cell"] > 0, (
        "aucune cellule de move ventilee : l'episode n'a rien exerce, le test ne regarde rien"
    )
