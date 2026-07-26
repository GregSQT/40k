"""V11 §9.2.5 — l'observation squad expose les PROFILS D'ARMES et les BITS DE RÈGLES.

Trou fermé ici : depuis le 2026-07-26 toutes les règles d'armes du PDF 24 sont résolues dans le
chemin vif (tir ET mêlée), mais le vecteur squad (199-d) n'en contenait **aucune trace** — ni
NB/ATK/STR/AP/DMG/portée, ni un seul bit de règle. L'agent SUBISSAIT [MELTA], [DEVASTATING
WOUNDS], [RAPID FIRE]… sans les percevoir : impossible d'apprendre à s'en servir.

Ce que ces tests verrouillent :
- le regroupement par PROFIL avec le **nombre de porteurs vivants** (sans lui, 1 rokkit et
  9 shootas sont indiscernables) et sa décroissance quand une figurine meurt ;
- les caractéristiques brutes et les règles, à leur place documentée dans le layout ;
- les règles PARAMÉTRÉES exposées par leur valeur, et le **keyword ciblé** par [ANTI-X]
  (sans lui le seuil Y+ est du bruit — l'effet dépend des keywords de la cible, 24.03) ;
- la symétrie : les slots ENNEMIS portent les mêmes champs (choix de cible / menace) ;
- l'absence de troncature silencieuse (le dépassement de K est LOGUÉ) ;
- [INDIRECT FIRE] n'est PAS exposée : elle n'est pas implémentée, un bit serait du bruit pur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_weapon_profiles import (
    ANTI_KEYWORDS,
    PROFILE_BIN_SIZE,
    PROFILE_CONT_SIZE,
    PROFILE_STAT_CONT,
    WEAPON_RULE_BITS,
    WEAPON_RULE_PARAMS,
    collect_weapon_profiles,
    profile_identity,
)
from engine.w40k_core import W40KEngine

# Offsets DANS un profil (cf. observation_weapon_profiles, layout documenté).
P_NB, P_ATK, P_STR, P_AP, P_DMG, P_RNG, P_CARRIERS = range(PROFILE_STAT_CONT)
P_ANTI_Y = PROFILE_STAT_CONT + len(WEAPON_RULE_PARAMS)
B_ANTI_ONEHOT = len(WEAPON_RULE_BITS)
B_MASK = PROFILE_BIN_SIZE - 1


def _param_index(rule_id: str) -> int:
    names = [name for name, _ in WEAPON_RULE_PARAMS]
    return PROFILE_STAT_CONT + names.index(rule_id)


def _bit_index(rule_id: str) -> int:
    return WEAPON_RULE_BITS.index(rule_id)


def _weapon(**over: Any) -> Dict[str, Any]:
    base = {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }
    base.update(over)
    return base


def _melee(**over: Any) -> Dict[str, Any]:
    base = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2,
            "WEAPON_RULES": [], "display_name": "Test Blade"}
    base.update(over)
    return base


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    rng_weapons: List[Dict[str, Any]] | None = None,
    cc_weapons: List[Dict[str, Any]] | None = None,
    per_model_rng: Dict[int, List[Dict[str, Any]]] | None = None,
    keywords: List[str] | None = None,
) -> Dict[str, Any]:
    specs: List[Dict[str, Any]] = []
    for idx, (c, r) in enumerate(positions):
        spec: Dict[str, Any] = {"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10}
        if per_model_rng and idx in per_model_rng:
            spec["RNG_WEAPONS"] = per_model_rng[idx]
        specs.append(spec)
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons if rng_weapons is not None else [_weapon()],
        "CC_WEAPONS": cc_weapons if cc_weapons is not None else [_melee()],
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
        "board": {"default": {"cols": 200, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
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
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=_config(units))
    eng.reset()
    return eng


def _self_profile(engine: W40KEngine, slot: int) -> Tuple[Any, Any]:
    """(cont, bin) du slot de profil `slot` de MON escouade (0..K_ranged-1 = tir, puis mêlée)."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    c_base = ObservationBuilder.SQUAD_CONT_WEAPONS_BASE + slot * PROFILE_CONT_SIZE
    b_base = ObservationBuilder.SQUAD_BIN_WEAPONS_BASE + slot * PROFILE_BIN_SIZE
    return (obs["vec_cont"][c_base:c_base + PROFILE_CONT_SIZE],
            obs["vec_bin"][b_base:b_base + PROFILE_BIN_SIZE])


def _melee_slot_index(slot_in_melee: int = 0) -> int:
    return ObservationBuilder.SQUAD_SELF_K_RANGED + slot_in_melee


def _enemy_profile(engine: W40KEngine, enemy_slot: int, profile_slot: int) -> Tuple[Any, Any]:
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    c_base = (ObservationBuilder.squad_enemy_cont_base(enemy_slot)
              + ObservationBuilder.SQUAD_PER_ENEMY_SLOT_SUMMARY_CONT
              + profile_slot * PROFILE_CONT_SIZE)
    b_base = (ObservationBuilder.squad_enemy_bin_base(enemy_slot)
              + ObservationBuilder.SQUAD_PER_ENEMY_SLOT_SUMMARY_BIN
              + profile_slot * PROFILE_BIN_SIZE)
    return (obs["vec_cont"][c_base:c_base + PROFILE_CONT_SIZE],
            obs["vec_bin"][b_base:b_base + PROFILE_BIN_SIZE])


# ---------------------------------------------------------------- regroupement


def test_profiles_group_by_identity_and_count_carriers():
    """Deux profils distincts dans une escouade -> deux entrées, avec leurs porteurs."""
    bulk = _weapon(display_name="Shoota", NB=2, STR=4, RNG=18)
    rokkit = _weapon(display_name="Rokkit", NB=1, STR=8, AP=-2, DMG=3, RNG=24)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)],
                  rng_weapons=[bulk], per_model_rng={2: [rokkit]}),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    models = [eng.game_state["models_cache"][m] for m in eng.game_state["squad_models"]["1"]]
    profiles = collect_weapon_profiles(models, "RNG_WEAPONS")
    assert [(w["display_name"], n) for w, n in profiles] == [("Shoota", 2), ("Rokkit", 1)]


def test_carrier_count_is_exposed_and_drops_with_losses():
    """Le compteur de porteurs est la donnée qui distingue 1 rokkit de 9 shootas."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(3.0)
    destroy_model(eng.game_state, "1#2", reason="combat")
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(2.0)


def test_profile_order_is_deterministic_by_carriers():
    """L'ordre des slots ne permute pas d'un step à l'autre : porteurs décroissants."""
    a = _weapon(display_name="A", NB=1, STR=4)
    b = _weapon(display_name="B", NB=1, STR=9)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)],
                  rng_weapons=[a], per_model_rng={2: [b]}),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    first, second = _self_profile(eng, 0)[0], _self_profile(eng, 1)[0]
    assert first[P_CARRIERS] == pytest.approx(2.0) and first[P_STR] == pytest.approx(4.0)
    assert second[P_CARRIERS] == pytest.approx(1.0) and second[P_STR] == pytest.approx(9.0)
    # Stabilité : deux constructions successives donnent le même vecteur.
    assert list(_self_profile(eng, 0)[0]) == list(first)


def test_identical_stats_different_names_are_one_profile():
    """C'est le PROFIL qui décide de la résolution, pas le nom de l'arme."""
    w1 = _weapon(display_name="Bolter A")
    w2 = _weapon(display_name="Bolter B")
    assert profile_identity(w1) == profile_identity(w2)


# ---------------------------------------------------------------- contenu brut


def test_raw_characteristics_are_exposed():
    """NB / ATK / STR / AP / DMG / portée sortent en valeurs BRUTES, à leur offset documenté."""
    gun = _weapon(display_name="Melta", NB=2, ATK=3, STR=9, AP=-4, DMG="D6", RNG=12)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[gun]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    inches = int(eng.game_state["inches_to_subhex"])
    assert cont[P_NB] == pytest.approx(2.0)
    assert cont[P_ATK] == pytest.approx(3.0)
    assert cont[P_STR] == pytest.approx(9.0)
    assert cont[P_AP] == pytest.approx(-4.0)
    assert cont[P_DMG] == pytest.approx(3.5)          # D6 -> espérance moteur
    assert cont[P_RNG] == pytest.approx(12.0 * inches)


def test_melee_profiles_live_in_their_own_slots():
    """Les deux registres sont exposés EN PERMANENCE (l'agent anticipe tir ET mêlée en move)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], cc_weapons=[_melee(display_name="Axe", NB=4, STR=7, AP=-2)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, _melee_slot_index())
    assert cont[P_NB] == pytest.approx(4.0)
    assert cont[P_STR] == pytest.approx(7.0)
    assert cont[P_RNG] == pytest.approx(0.0)   # une arme de mêlée n'a pas de portée
    assert binv[B_MASK] == pytest.approx(1.0)


def test_empty_profile_slot_is_zero_padded_with_mask_off():
    """Un slot sans profil est identifiable par son mask, pas par des zéros ambigus."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, 1)   # une seule arme de tir -> slot 1 vide
    assert binv[B_MASK] == pytest.approx(0.0)
    assert not any(cont)


# ---------------------------------------------------------------- règles


def test_boolean_rule_bit_is_set():
    """Une règle booléenne résolue dans le vif allume son bit."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)],
                  rng_weapons=[_weapon(WEAPON_RULES=["DEVASTATING_WOUNDS"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    _, binv = _self_profile(eng, 0)
    assert binv[_bit_index("DEVASTATING_WOUNDS")] == pytest.approx(1.0)
    assert binv[_bit_index("TORRENT")] == pytest.approx(0.0)


@pytest.mark.parametrize("rule_id,declared,expected", [
    ("RAPID_FIRE", "RAPID_FIRE:2", 2.0),
    ("SUSTAINED_HITS", "SUSTAINED_HITS:1", 1.0),
    ("MELTA", "MELTA:4", 4.0),
    ("BLAST", "BLAST", 1.0),        # forme NUE légale : 1 dé par tranche de 5 (24.05)
    ("BLAST", "BLAST:2", 2.0),
])
def test_parameterised_rule_exposes_its_value(rule_id, declared, expected):
    """Une règle paramétrée sort en VALEUR, pas en bit : [RAPID FIRE 2] ≠ [RAPID FIRE 1]."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[_weapon(WEAPON_RULES=[declared])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    assert cont[_param_index(rule_id)] == pytest.approx(expected)


def test_anti_rule_exposes_threshold_and_target_keyword():
    """[ANTI-X Y+] 24.03 : le seuil SEUL est du bruit — le keyword ciblé est exposé aussi."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[_weapon(WEAPON_RULES=["ANTI_VEHICLE:2"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, 0)
    assert cont[P_ANTI_Y] == pytest.approx(2.0)
    onehot = list(binv[B_ANTI_ONEHOT:B_ANTI_ONEHOT + len(ANTI_KEYWORDS)])
    assert sum(onehot) == pytest.approx(1.0)
    assert onehot[ANTI_KEYWORDS.index("VEHICLE")] == pytest.approx(1.0)


def test_anti_rules_do_not_stack_best_threshold_wins():
    """24.02 : deux [ANTI] sur la même arme ne se cumulent pas — le MEILLEUR seuil est exposé."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)],
                  rng_weapons=[_weapon(WEAPON_RULES=["ANTI_INFANTRY:4", "ANTI_VEHICLE:2"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, 0)
    assert cont[P_ANTI_Y] == pytest.approx(2.0)
    onehot = list(binv[B_ANTI_ONEHOT:B_ANTI_ONEHOT + len(ANTI_KEYWORDS)])
    assert onehot[ANTI_KEYWORDS.index("VEHICLE")] == pytest.approx(1.0)
    assert onehot[ANTI_KEYWORDS.index("INFANTRY")] == pytest.approx(0.0)


def test_indirect_fire_is_deliberately_absent():
    """[INDIRECT FIRE] 24.19 n'est PAS résolue par le moteur : l'exposer serait du bruit."""
    assert "INDIRECT_FIRE" not in WEAPON_RULE_BITS
    assert "INDIRECT_FIRE" not in {name for name, _ in WEAPON_RULE_PARAMS}


# ---------------------------------------------------------------- ennemis


def test_enemy_slots_expose_the_same_profile_fields():
    """Symétrie : choisir une cible et jauger une menace exigent les mêmes données brutes."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20), (61, 20)],
                  rng_weapons=[_weapon(display_name="Big Shoota", NB=3, STR=6, AP=-1,
                                       WEAPON_RULES=["TWIN_LINKED"])]),
    ])
    cont, binv = _enemy_profile(eng, 0, 0)
    assert cont[P_NB] == pytest.approx(3.0)
    assert cont[P_STR] == pytest.approx(6.0)
    assert cont[P_CARRIERS] == pytest.approx(2.0)
    assert binv[_bit_index("TWIN_LINKED")] == pytest.approx(1.0)
    assert binv[B_MASK] == pytest.approx(1.0)


def test_empty_enemy_slot_carries_no_profile():
    """Slot ennemi vide -> profils à zéro, mask à 0 (padding identifiable)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _enemy_profile(eng, 4, 0)   # slot 4 : aucune escouade ennemie
    assert not any(cont)
    assert binv[B_MASK] == pytest.approx(0.0)


# ---------------------------------------------------------------- troncature


def test_profile_truncation_is_logged_never_silent():
    """Plus de profils que de slots -> le dépassement est TRACÉ (§11, pas de cap silencieux).

    Troncature RÉELLE : une escouade porteuse de K+2 profils de tir distincts, observée par le
    vrai chemin `build_squad_observation`. Contre-épreuve intégrée : la même escouade avec K
    profils exactement ne loggue RIEN.
    """
    k = ObservationBuilder.SQUAD_SELF_K_RANGED

    def _log_of(n_profiles: int) -> List[str]:
        # n_profiles armes de tir toutes différentes, une par figurine.
        per_model = {i: [_weapon(display_name=f"W{i}", STR=3 + i)] for i in range(n_profiles)}
        eng = _make_engine([
            _unit_cfg(1, 1, [(20 + i, 20) for i in range(n_profiles)],
                      rng_weapons=[_weapon(display_name="W0", STR=3)],
                      per_model_rng=per_model),
            _unit_cfg(2, 2, [(60, 20)]),
        ])
        captured: List[str] = []
        with patch("engine.game_utils.add_debug_file_log",
                   side_effect=lambda gs, msg: captured.append(msg)):
            eng.obs_builder.build_squad_observation(eng.game_state, "1")
        return [m for m in captured if "profils RNG_WEAPONS" in m]

    over = _log_of(k + 2)
    assert over, "troncature du bloc profils NON loguee"
    assert "ne sont pas observes" in over[0]
    assert not _log_of(k), "log de troncature emis alors qu'aucun profil n'est tronque"
