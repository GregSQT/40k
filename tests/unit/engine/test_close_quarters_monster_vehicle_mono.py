"""§1.9 — le volet MONSTER/VEHICLE de 10.06 existe aussi sur le chemin PvP/mono.

Divergence corrigée ici (`V11_entity_encoder_pointer.md` §1.9, créée par T-B) : le volet
MONSTER/VEHICLE du tir à bout portant a été implémenté sur le chemin **squad/gym** le
2026-07-26, mais le chemin **PvP/mono** ne le connaissait pas — son gate filtrait toujours sur
les seules armes [CLOSE-QUARTERS], et son commentaire affirmait encore que ce volet « n'est pas
implémenté dans le moteur ». Un véhicule engagé pouvait donc tirer son arme principale (à -1)
en entraînement, mais pas en PvP. C'est le motif §9.1 (« une règle vive sur un chemin, absente
de l'autre »), inversé.

**PDF 10.06 — CLOSE-QUARTERS SHOOTING**, lu le 2026-07-26 :
> ELIGIBLE IF: Engaged and did not make an advance move this turn ; **has one or more
> [CLOSE-QUARTERS] weapons or is a MONSTER/VEHICLE unit**.
> WHILE SHOOTING: Models in your unit can target enemy units your unit is engaged with.
> - **MONSTER/VEHICLE Models** : « Unless that attack is made with a [CLOSE-QUARTERS] weapon and
>   targets a unit your unit is engaged with, subtract 1 from the hit roll » ; « If that attack
>   is made with a [BLAST] weapon, it **still cannot target a unit your unit is engaged with** ».
> - **Non-MONSTER/Non-VEHICLE Models** : « You can only select [CLOSE-QUARTERS] weapons […] and
>   you can only select enemy units that are engaged with your unit as targets. »

**PDF 24.07 [CLOSE-QUARTERS]** : la restriction de mélange d'armes vaut « for each model in that
unit (**excluding MONSTER/VEHICLE models**) » — sans cette exclusion, le volet ci-dessus serait
rendu inopérant dès la deuxième arme tirée.

Contre-épreuves intégrées : chaque test MONSTER/VEHICLE a son jumeau INFANTRY, qui doit rester
REFUSÉ. Le fix ne doit rien ouvrir à l'infanterie.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shooting_handlers import (
    _has_valid_shooting_targets,
    _is_valid_shooting_target,
    weapon_availability_check,
)
from engine.phase_handlers.shared_utils import (
    SHOOTING_TYPE_CLOSE_QUARTERS,
    resolve_squad_shooting_type,
)
from engine.w40k_core import W40KEngine


def _weapon(name: str, rules: List[str], rng: int = 24) -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
            "WEAPON_RULES": list(rules), "display_name": name, "shot": 0}


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    rng_weapons: List[Dict[str, Any]] | None = None,
    keywords: List[str] | None = None,
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 4, "HP_MAX": 4, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 4 * len(specs), "HP_MAX": 4, "MOVE": 6, "T": 6,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 0,
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
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
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


def _unit(eng: W40KEngine, uid: str) -> Dict[str, Any]:
    return next(u for u in eng.game_state["units"] if str(u["id"]) == uid)


def _engaged_setup(keywords: List[str], weapons: List[Dict[str, Any]]) -> W40KEngine:
    """Tireur au CONTACT d'un ennemi (11,10), plus un second ennemi non engagé à 20 hexes."""
    return _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=weapons, keywords=keywords),
        _unit_cfg(2, 2, [(11, 10)]),
        _unit_cfg(3, 2, [(30, 10)]),
    ])


# --------------------------------------------------------- éligibilité (cercle vert)


def test_engaged_vehicle_without_close_quarters_weapon_can_shoot():
    """ROUGE avant le fix : le gate mono ne connaissait que les armes [CLOSE-QUARTERS]."""
    eng = _engaged_setup(["VEHICLE"], [_weapon("Multi-Melta", [])])
    assert _has_valid_shooting_targets(eng.game_state, _unit(eng, "1"), 1) is True


def test_engaged_infantry_without_close_quarters_weapon_still_cannot_shoot():
    """Contre-épreuve : le volet non-MONSTER/VEHICLE de 10.06 est inchangé."""
    eng = _engaged_setup(["INFANTRY"], [_weapon("Bolt Rifle", [])])
    assert _has_valid_shooting_targets(eng.game_state, _unit(eng, "1"), 1) is False


def test_engaged_monster_that_advanced_still_cannot_shoot():
    """10.06 exige « did not make an advance move this turn » — le volet MV n'y déroge pas."""
    eng = _engaged_setup(["MONSTER"], [_weapon("Bio-Cannon", [])])
    eng.game_state["units_advanced"] = {"1"}
    assert _has_valid_shooting_targets(eng.game_state, _unit(eng, "1"), 1) is False


# --------------------------------------------------------- sélection d'armes


def test_weapon_menu_offers_a_non_close_quarters_weapon_to_an_engaged_vehicle():
    """« MONSTER/VEHICLE Models: you can select any of that model's ranged weapons. »"""
    eng = _engaged_setup(["VEHICLE"], [_weapon("Multi-Melta", [])])
    pool = weapon_availability_check(eng.game_state, _unit(eng, "1"), 1, 0, 1)
    assert [w["can_use"] for w in pool] == [True]


def test_weapon_menu_still_refuses_it_to_engaged_infantry():
    eng = _engaged_setup(["INFANTRY"], [_weapon("Bolt Rifle", [])])
    pool = weapon_availability_check(eng.game_state, _unit(eng, "1"), 1, 0, 1)
    assert [w["can_use"] for w in pool] == [False]
    assert "CLOSE_QUARTERS" in str(pool[0]["reason"])


def test_sidearms_mixing_restriction_excludes_monster_vehicle():
    """24.07 : « for each model in that unit (excluding MONSTER/VEHICLE models) ».

    Un véhicule ayant déjà tiré une arme [CLOSE-QUARTERS] peut enchaîner sur une autre arme —
    sans cette exclusion, le volet MONSTER/VEHICLE serait mort dès la 2ᵉ arme.
    """
    weapons = [_weapon("Storm Bolter", ["CLOSE_QUARTERS"]), _weapon("Multi-Melta", [])]
    eng = _engaged_setup(["VEHICLE"], weapons)
    unit = _unit(eng, "1")
    unit["_shooting_with_close_quarters"] = True   # a déjà tiré une arme [CLOSE-QUARTERS]
    pool = weapon_availability_check(eng.game_state, unit, 1, 0, 1)
    assert [w["can_use"] for w in pool] == [True, True]

    infantry = _engaged_setup(["INFANTRY"], [dict(w) for w in weapons])
    inf_unit = _unit(infantry, "1")
    inf_unit["_shooting_with_close_quarters"] = True
    inf_pool = weapon_availability_check(infantry.game_state, inf_unit, 1, 0, 1)
    assert [w["can_use"] for w in inf_pool] == [True, False], "l'infanterie garde 24.07"


# --------------------------------------------------------- choix de cible


def test_engaged_vehicle_may_target_a_unit_it_is_not_engaged_with():
    """Le volet « cibles limitées aux unités engagées » ne vise QUE les non-MONSTER/VEHICLE."""
    eng = _engaged_setup(["VEHICLE"], [_weapon("Multi-Melta", [], rng=48)])
    shooter = _unit(eng, "1")
    shooter["selectedRngWeaponIndex"] = 0
    assert _is_valid_shooting_target(eng.game_state, shooter, _unit(eng, "3")) is True


def test_engaged_infantry_may_not_target_a_unit_it_is_not_engaged_with():
    eng = _engaged_setup(["INFANTRY"], [_weapon("Bolt Pistol", ["CLOSE_QUARTERS"], rng=48)])
    shooter = _unit(eng, "1")
    shooter["selectedRngWeaponIndex"] = 0
    assert _is_valid_shooting_target(eng.game_state, shooter, _unit(eng, "3")) is False


def test_blast_weapon_still_cannot_target_the_engaged_unit():
    """« If that attack is made with a [BLAST] weapon, it still cannot target a unit your unit
    is engaged with » — la seule restriction de cible qui survit pour un MONSTER/VEHICLE."""
    eng = _engaged_setup(["VEHICLE"], [_weapon("Battle Cannon", ["BLAST"], rng=48)])
    shooter = _unit(eng, "1")
    shooter["selectedRngWeaponIndex"] = 0
    assert _is_valid_shooting_target(eng.game_state, shooter, _unit(eng, "2")) is False
    # … mais elle peut viser l'ennemi avec lequel elle n'est PAS engagée.
    assert _is_valid_shooting_target(eng.game_state, shooter, _unit(eng, "3")) is True


# --------------------------------------------------------- parité des deux chemins


def test_both_paths_agree_on_the_monster_vehicle_volet():
    """§9.1 : la règle doit être vive des DEUX côtés, plus jamais d'un seul.

    Le chemin squad résout un type de tir, le chemin mono ouvre son cercle vert : sur le même
    état, les deux doivent dire la même chose. C'est ce test qui empêche la divergence de
    revenir.
    """
    for keywords, expected in (("VEHICLE", True), ("MONSTER", True), ("INFANTRY", False)):
        eng = _engaged_setup([keywords], [_weapon("Big Gun", [])])
        squad_type = resolve_squad_shooting_type(eng.game_state, "1")
        mono_ok = _has_valid_shooting_targets(eng.game_state, _unit(eng, "1"), 1)
        assert (squad_type == SHOOTING_TYPE_CLOSE_QUARTERS) is expected, keywords
        assert mono_ok is expected, keywords
