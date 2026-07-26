"""T-D — ÉQUIVALENCE entité par entité : le format tenseurs ne perd aucune information.

`V11_entity_encoder_pointer.md` §4 T-D exige que l'observation reste « exactement équivalente en
information à l'actuelle sur un état donné (test d'équivalence entité par entité) ». Le passage
du vecteur PLAT aux tenseurs d'entités est un changement de FORME : chaque feature émise doit
donc pouvoir être recalculée depuis `game_state` par un chemin indépendant du builder.

Ce fichier fait exactement cela, pour les trois familles d'entités :
- l'unité ACTIVE (ligne 0 des alliés) ;
- une escouade ALLIÉE (bloc E, que le format plat interdisait — il aurait fallu inventer un
  ordre de slots qu'aucune action ne consomme, cf. V11_audit_observation.md §11) ;
- les slots ENNEMIS, dont l'ordre reste celui de l'action de tir (invariant D1).

Contre-épreuves intégrées :
- `test_ally_and_enemy_share_the_same_reading` : la MÊME escouade lue comme alliée (vue de son
  camp) et comme ennemie (vue d'en face) donne les mêmes valeurs de profil — c'est la définition
  du schéma unifié, et ce qui rend l'encodeur partagé légitime ;
- `test_enemy_weapon_profiles_are_no_longer_truncated` : l'ennemi expose désormais autant de
  profils que moi (§1.5 : 2+1 slots pour un maximum MESURÉ de 6 tir / 5 mêlée — l'arme
  d'exception d'un ennemi était tronquée à chaque épisode) ;
- `test_enemy_model_types_are_exposed` : les TYPES de figurines ennemies existent (§1.6 : jusqu'à
  5 profils défensifs distincts par escouade, dont l'agent ne voyait aucun).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    MODEL_TYPE_BIN_FIELDS,
    unit_bin_index,
    unit_cont_index,
)
from engine.w40k_core import W40KEngine


def _weapon(**over: Any) -> Dict[str, Any]:
    w = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
         "WEAPON_RULES": [], "display_name": "Test Bolter"}
    w.update(over)
    return w


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    value: int = 10, oc: int = 2, move: int = 6, t: int = 4,
    save: int = 4, invul: int = 0, hp_max: int = 2,
    rng_weapons: List[Dict[str, Any]] | None = None,
    per_model_over: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    specs: List[Dict[str, Any]] = []
    for i, (c, r) in enumerate(positions):
        spec: Dict[str, Any] = {"col": c, "row": r, "HP_CUR": hp_max, "HP_MAX": hp_max, "VALUE": value}
        if per_model_over and i in per_model_over:
            spec.update(per_model_over[i])
        specs.append(spec)
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": hp_max * len(specs), "HP_MAX": hp_max, "MOVE": move, "T": t,
        "ARMOR_SAVE": save, "INVUL_SAVE": invul,
        "RNG_WEAPONS": rng_weapons if rng_weapons is not None else [_weapon()],
        "CC_WEAPONS": [_weapon(display_name="Test Blade", RNG=0)],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": oc, "VALUE": value * len(specs),
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


@pytest.fixture
def engine() -> W40KEngine:
    """2 escouades par camp : les lignes « alliées » et « ennemies » sont toutes exercées."""
    return _make_engine([
        _unit_cfg(1, 1, [(20, 20), (22, 20), (24, 20)]),
        _unit_cfg(3, 1, [(30, 40), (32, 40)], value=15, oc=1, move=8),
        _unit_cfg(2, 2, [(60, 20), (62, 20)], value=13, oc=3, move=10, t=9,
                  save=2, invul=5, hp_max=4),
        _unit_cfg(4, 2, [(70, 50)], value=20, oc=1),
    ])


def _expected_unit_features(engine: W40KEngine, sid: str) -> Dict[str, float]:
    """Recalcule les features d'unité depuis `game_state`, SANS passer par le builder."""
    gs = engine.game_state
    entry = gs["units_cache"][sid]
    sq = gs["squad_cache"][sid]
    unit = next(u for u in gs["units"] if str(u["id"]) == sid)
    mids = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
    models = [gs["models_cache"][m] for m in mids]
    return {
        "alive_models": float(len(mids)),
        "hp_total": float(int(entry["HP_CUR"])),
        "value_alive": float(sum(float(m["VALUE"]) for m in models)),
        "oc_total": float(int(sq["oc_total"])),
        "model_count_ratio": len(mids) / float(int(sq["model_count_at_start"])),
        "wounded_hp_ratio": min(
            int(m["HP_CUR"]) / float(int(m["HP_MAX"])) for m in models
        ),
        "move": float(unit["MOVE"]),
        "hp_max": float(unit["HP_MAX"]),
        "toughness": float(unit["T"]),
        "armor_save": float(unit["ARMOR_SAVE"]),
        "invul_save": float(unit["INVUL_SAVE"]),
    }


def _row_of(obs, family: str, row: int) -> Dict[str, float]:
    cont = obs[f"{family}_cont"][row]
    return {name: float(cont[unit_cont_index(name)]) for name in (
        "alive_models", "hp_total", "value_alive", "oc_total", "model_count_ratio",
        "wounded_hp_ratio", "move", "hp_max", "toughness", "armor_save", "invul_save",
    )}


def test_active_unit_row_matches_the_game_state(engine):
    """Ligne 0 des alliés = l'unité observée, feature par feature."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    assert _row_of(obs, "allies", 0) == pytest.approx(_expected_unit_features(engine, "1"))
    assert float(obs["allies_bin"][0][unit_bin_index("is_active")]) == 1.0


def test_ally_row_matches_the_game_state(engine):
    """Bloc E : mes AUTRES escouades sont décrites (elles n'existaient pas au format plat)."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    present = unit_bin_index("present")
    rows = [r for r in range(1, obs["allies_bin"].shape[0])
            if float(obs["allies_bin"][r][present]) == 1.0]
    assert len(rows) == 1, "une seule autre escouade alliee dans le fixture"
    assert _row_of(obs, "allies", rows[0]) == pytest.approx(_expected_unit_features(engine, "3"))
    assert float(obs["allies_bin"][rows[0]][unit_bin_index("is_active")]) == 0.0
    assert float(obs["allies_bin"][rows[0]][unit_bin_index("is_ally")]) == 1.0


def test_enemy_rows_match_the_game_state_in_action_slot_order(engine):
    """Chaque slot ennemi décrit l'ennemi que désigne l'action de tir du MÊME slot (D1)."""
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    mapping = get_enemy_slot_mapping(engine.game_state, 1)
    present = unit_bin_index("present")
    for slot_i in range(ObservationBuilder.K_ENEMY_SLOTS):
        esid = mapping[slot_i] if slot_i < len(mapping) else None
        if esid is None:
            assert float(obs["enemies_bin"][slot_i][present]) == 0.0
            continue
        assert float(obs["enemies_bin"][slot_i][present]) == 1.0
        assert _row_of(obs, "enemies", slot_i) == pytest.approx(
            _expected_unit_features(engine, esid)
        )


def test_ally_and_enemy_share_the_same_reading(engine):
    """La même escouade, lue de son camp puis d'en face, donne les mêmes features d'unité.

    C'est la définition du schéma UNIFIÉ (§3.3 : « une unité est une unité ») : sans cette
    propriété, un encodeur partagé entre les deux camps n'aurait pas de sens.
    """
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    gs = engine.game_state
    obs_mine = engine.obs_builder.build_squad_observation(gs, "2")   # l'escouade 2 se voit
    obs_theirs = engine.obs_builder.build_squad_observation(gs, "1")  # et est vue d'en face
    slot = get_enemy_slot_mapping(gs, 1).index("2")
    seen_by_owner = _row_of(obs_mine, "allies", 0)
    seen_by_enemy = _row_of(obs_theirs, "enemies", slot)
    assert seen_by_owner == pytest.approx(seen_by_enemy)
    # … et les profils d'armes aussi, encodés par le MÊME encodeur avec le MÊME K.
    assert obs_mine["allies_wpn_cont"][0].tolist() == obs_theirs["enemies_wpn_cont"][slot].tolist()
    assert obs_mine["allies_wpn_bin"][0].tolist() == obs_theirs["enemies_wpn_bin"][slot].tolist()


def test_enemy_weapon_profiles_are_no_longer_truncated():
    """§1.5 : l'ennemi expose K profils par registre, comme moi (auparavant 2 tir + 1 mêlée).

    Contre-épreuve : l'escouade ennemie porte 4 profils de tir DISTINCTS. Sous l'ancien layout,
    les slots 2 et 3 étaient perdus — l'arme d'exception d'un ennemi (le fuseur du sergent)
    n'était jamais observée.
    """
    per_model = {i: {"RNG_WEAPONS": [_weapon(display_name=f"W{i}", STR=4 + i)]} for i in range(4)}
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60 + 2 * i, 20) for i in range(4)], per_model_over=per_model),
    ])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    occupied = [
        p for p in range(ObservationBuilder.K_WEAPONS_RANGED)
        if float(obs["enemies_wpn_bin"][0][p][-1]) == 1.0
    ]
    assert len(occupied) == 4
    strengths = sorted(float(obs["enemies_wpn_cont"][0][p][2]) for p in occupied)
    assert strengths == [4.0, 5.0, 6.0, 7.0]


def test_enemy_model_types_are_exposed():
    """§1.6 : les TYPES de figurines ennemies existent (profil défensif + effectif + rôle).

    Contre-épreuve : l'escouade ennemie contient un « Nob » (profil dérogatoire). Sous l'ancien
    layout, les slots ennemis n'avaient qu'un profil d'escouade issu de la datasheet : l'agent
    ne pouvait pas voir qu'une figurine y est plus dure que les autres.
    """
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20), (62, 20), (64, 20)]),
    ])
    gs = eng.game_state
    gs["models_cache"]["2#1"].update(
        {"HP_MAX": 6, "T": 8, "ARMOR_SAVE": 2, "INVUL_SAVE": 4, "role": "leader"}
    )
    obs = eng.obs_builder.build_squad_observation(gs, "1")
    present = MODEL_TYPE_BIN_FIELDS.index("present")
    types = [
        (
            tuple(float(v) for v in obs["enemies_types_cont"][0][t]),
            ObservationBuilder.SQUAD_MODEL_ROLES[
                [float(x) for x in obs["enemies_types_bin"][0][t][:4]].index(1.0)
            ] if 1.0 in [float(x) for x in obs["enemies_types_bin"][0][t][:4]] else None,
        )
        for t in range(ObservationBuilder.K_MODEL_TYPES)
        if float(obs["enemies_types_bin"][0][t][present]) == 1.0
    ]
    assert len(types) == 2, "le Nob forme son propre type"
    assert ((6.0, 8.0, 2.0, 4.0, 1.0), "leader") in types
    assert any(profile[4] == 2.0 and role is None for profile, role in types)


def test_ally_overflow_is_logged_never_silent():
    """Plus d'escouades alliées que de slots -> le dépassement est TRACÉ (§11)."""
    n = ObservationBuilder.K_ALLY_SLOTS + 1
    units = [_unit_cfg(i + 1, 1, [(10 + 3 * i, 20)]) for i in range(n)]
    units.append(_unit_cfg(100, 2, [(90, 20)]))
    eng = _make_engine(units)
    captured: List[str] = []
    with patch("engine.game_utils.add_debug_file_log",
               side_effect=lambda gs, msg: captured.append(msg)):
        eng.obs_builder.build_squad_observation(eng.game_state, "1")
    assert any("escouades alliees" in m for m in captured), "dépassement d'alliés NON logué"
