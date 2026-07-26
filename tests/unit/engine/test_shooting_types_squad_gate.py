"""V11 T-B — les types de tir 10.04 / 10.05 / 10.06 existent enfin sur le chemin SQUAD/GYM.

Bug d'origine (trouvé le 2026-07-26, cf. `V11_entity_encoder_pointer.md` §1.2) : le gate de tir
du masque squad se résumait à
`can_shoot = not has_fled and not has_advanced and not has_shot and not in_er`, **sans aucune
exception d'arme**. Deux types de tir entiers étaient donc inaccessibles à l'agent :

- **10.05 ASSAULT SHOOTING** — « Unengaged **and made an advance move this turn** », avec ≥1 arme
  [ASSAULT] ; *while shooting*, seules les armes [ASSAULT] sont sélectionnables.
- **10.06 CLOSE-QUARTERS SHOOTING** — « **Engaged** and did not make an advance move this turn »,
  avec ≥1 arme [CLOSE-QUARTERS] **ou** une figurine MONSTER/VEHICLE ; *while shooting*, les
  cibles sont les unités engagées, et une figurine MONSTER/VEHICLE peut employer n'importe quelle
  arme mais subit **-1 au jet de touche** sauf [CLOSE-QUARTERS] sur une unité engagée, tandis
  qu'une arme [BLAST] ne peut toujours pas viser une unité engagée.

Le chemin PvP/mono connaissait les deux (`_can_shoot`) ; le chemin squad non — motif §9.1
« une règle vive sur un chemin, absente de l'autre ».

Les tests portent sur le **vrai masque** (`build_squad_action_mask`), pas sur le helper seul :
c'est le câblage appelant→fonction qui était cassé, pas la fonction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import (
    SHOOTING_TYPE_ASSAULT,
    SHOOTING_TYPE_CLOSE_QUARTERS,
    SHOOTING_TYPE_NORMAL,
    SQUAD_ACTION_SHOOT_SLOT_BASE,
    build_squad_action_mask,
    resolve_squad_shooting_type,
)
from engine.w40k_core import W40KEngine


def _weapon(name: str, rules: List[str], rng: int = 24, **over: Any) -> Dict[str, Any]:
    w = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
         "WEAPON_RULES": list(rules), "display_name": name}
    w.update(over)
    return w


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    rng_weapons: List[Dict[str, Any]] | None = None,
    keywords: List[str] | None = None,
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 2 * len(specs), "HP_MAX": 2, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons if rng_weapons is not None else [_weapon("Gun", [])],
        "CC_WEAPONS": [{"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
                        "WEAPON_RULES": [], "display_name": "Blade"}],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": k} for k in (keywords or ["INFANTRY"])],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET, "action_space_size": 1047,
    }
    return {
        "board": {"default": {"cols": 80, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False, "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


def _engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=_config(units))
    eng.reset()
    eng.game_state["phase"] = "shoot"
    return eng


def _can_shoot_any_slot(eng: W40KEngine) -> bool:
    mask = build_squad_action_mask(eng.game_state, "1")
    return any(mask[SQUAD_ACTION_SHOOT_SLOT_BASE + i] for i in range(5))


# --------------------------------------------------------------- 10.04 normal


def test_normal_shooting_is_the_default() -> None:
    eng = _engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(20, 10)])])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_NORMAL
    assert _can_shoot_any_slot(eng)


def test_a_unit_that_already_shot_cannot_shoot_again() -> None:
    eng = _engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(20, 10)])])
    eng.game_state["units_shot"] = {"1"}
    assert resolve_squad_shooting_type(eng.game_state, "1") is None
    assert not _can_shoot_any_slot(eng)


# --------------------------------------------------------------- 10.05 assault


def test_assault_shooting_is_open_after_an_advance() -> None:
    """ROUGE avant le fix : `has_advanced` fermait le tir sans regarder les armes."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Assault Gun", ["ASSAULT"])]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    eng.game_state["units_advanced"] = {"1"}
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_ASSAULT
    assert _can_shoot_any_slot(eng), "10.05 : une unite ayant advance avec une arme ASSAULT doit pouvoir tirer"


def test_no_assault_weapon_means_no_shooting_after_an_advance() -> None:
    """Discrimination : sans arme [ASSAULT], l'advance ferme bien le tir."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Plain Gun", [])]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    eng.game_state["units_advanced"] = {"1"}
    assert resolve_squad_shooting_type(eng.game_state, "1") is None
    assert not _can_shoot_any_slot(eng)


def test_an_engaged_unit_that_advanced_cannot_use_close_quarters() -> None:
    """10.06 exige « did not make an advance move this turn »."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("CQ", ["CLOSE_QUARTERS"], rng=12)]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    eng.game_state["units_advanced"] = {"1"}
    assert resolve_squad_shooting_type(eng.game_state, "1") is None


# -------------------------------------------------------- 10.06 close-quarters


def test_close_quarters_shooting_is_open_while_engaged() -> None:
    """ROUGE avant le fix : `in_er` fermait le tir sans regarder les armes."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("CQ Pistol", ["CLOSE_QUARTERS"], rng=12)]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_CLOSE_QUARTERS
    assert _can_shoot_any_slot(eng), "10.06 : une unite engagee avec une arme CLOSE_QUARTERS doit pouvoir tirer"


def test_engaged_without_close_quarters_weapon_cannot_shoot() -> None:
    """Discrimination : engagée sans arme [CLOSE-QUARTERS] et sans MONSTER/VEHICLE -> rien."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Plain Gun", [])]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") is None
    assert not _can_shoot_any_slot(eng)


def test_a_vehicle_is_eligible_to_close_quarters_without_any_such_weapon() -> None:
    """10.06 : « Has one or more [CLOSE-QUARTERS] weapons **or is a MONSTER/VEHICLE unit** »."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Cannon", [])], keywords=["VEHICLE"]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_CLOSE_QUARTERS
    assert _can_shoot_any_slot(eng)


def test_a_vehicle_blast_weapon_still_cannot_target_an_engaged_unit() -> None:
    """10.06 : « if that attack is made with a [BLAST] weapon, it still cannot target a unit
    your unit is engaged with »."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Big Blast", ["BLAST"])],
                  keywords=["VEHICLE"]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_CLOSE_QUARTERS
    assert not _can_shoot_any_slot(eng), "une arme BLAST ne peut pas viser l'unite engagee"


# --------------------------------------------- sélection d'armes « while shooting »


def test_weapon_selection_is_restricted_by_the_shooting_type() -> None:
    """Volet « WHILE SHOOTING » : le type de tir filtre les armes sélectionnables."""
    from engine.phase_handlers.shared_utils import squad_model_shootable_weapon_indices

    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("Plain", []),                          # index 0
            _weapon("Assault", ["ASSAULT"]),               # index 1
            _weapon("CQ", ["CLOSE_QUARTERS"], rng=12),     # index 2
        ]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    model = eng.game_state["models_cache"]["1#0"]
    gs = eng.game_state
    assert squad_model_shootable_weapon_indices(gs, "1", model, SHOOTING_TYPE_NORMAL) == [0, 1, 2]
    assert squad_model_shootable_weapon_indices(gs, "1", model, SHOOTING_TYPE_ASSAULT) == [1]
    assert squad_model_shootable_weapon_indices(gs, "1", model, SHOOTING_TYPE_CLOSE_QUARTERS) == [2]


def _bs_of_shot(eng: W40KEngine, weapon_index: int, monkeypatch: pytest.MonkeyPatch) -> int:
    """Seuil de touche effectif d'un tir de la figurine 1#0 sur l'escouade 2."""
    import random

    from engine.phase_handlers import shooting_handlers
    from tests.unit.engine._roll_helpers import roll_shoot_intent

    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    intent = {"model_id": "1#0", "target_unit_id": "2", "weapon_index": weapon_index,
              "n_attacks_resolved": 1}
    return int(roll_shoot_intent(eng.game_state, intent)["bs"])


def test_close_quarters_vehicle_takes_minus_one_to_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """10.06 : « unless that attack is made with a [CLOSE-QUARTERS] weapon AND targets a unit
    your unit is engaged with, subtract 1 from the hit roll » (figurines MONSTER/VEHICLE).

    -1 au jet = seuil dégradé de 1. Discrimination intégrée : l'arme [CLOSE-QUARTERS] sur la
    cible engagée garde son seuil.
    """
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], keywords=["VEHICLE"], rng_weapons=[
            _weapon("Cannon", [], rng=24, ATK=4),                       # index 0 : subit le -1
            _weapon("CQ Gun", ["CLOSE_QUARTERS"], rng=12, ATK=4),       # index 1 : exempte
        ]),
        _unit_cfg(2, 2, [(11, 10)]),
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_CLOSE_QUARTERS
    assert _bs_of_shot(eng, 1, monkeypatch) == 4, "arme CLOSE_QUARTERS sur cible engagee : pas de malus"
    assert _bs_of_shot(eng, 0, monkeypatch) == 5, "arme non-CLOSE_QUARTERS : -1 au jet de touche"


def test_no_close_quarters_malus_outside_close_quarters_shooting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contre-épreuve : hors 10.06, un véhicule tire sans malus."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], keywords=["VEHICLE"],
                  rng_weapons=[_weapon("Cannon", [], rng=40, ATK=4)]),
        _unit_cfg(2, 2, [(30, 10)]),   # loin : pas d'engagement
    ])
    assert resolve_squad_shooting_type(eng.game_state, "1") == SHOOTING_TYPE_NORMAL
    assert _bs_of_shot(eng, 0, monkeypatch) == 4


def test_the_mask_no_longer_depends_on_the_selected_weapon_index() -> None:
    """Le masque considère TOUTE arme éligible, plus seulement `selectedRngWeaponIndex`.

    En gym cet index vaut 0 pendant toute la partie : une figurine dont seule l'arme n°2 porte
    assez loin était invisible du masque.
    """
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("Short", [], rng=2),      # index 0, hors de portee de la cible
            _weapon("Long", [], rng=40),      # index 1, a portee
        ]),
        _unit_cfg(2, 2, [(30, 10)]),
    ])
    assert int(eng.game_state["models_cache"]["1#0"]["selectedRngWeaponIndex"]) == 0
    assert _can_shoot_any_slot(eng), "l'arme longue portee doit ouvrir le slot de tir"
