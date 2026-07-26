"""T3 — suppression des features calculées + réorganisation des PV / stats brutes.

Refonte V11 (Documentation/Implementation/V11_audit_observation.md §9.1, §9.2, §10 B2/B3) :
- ❌ `obs[20]` firepower générique vs T4/Sv4 : résumé trompeur qui REMPLAÇAIT les données ;
- ❌ `value_over_ttk` (+7) et `threat_level` (+8) par ennemi : features calculées sur UNE arme
  échantillon et UNE figurine cible, aveugles aux règles et au couvert ;
- ❌ index d'arme CC par figurine (l'agent ne choisit pas son arme) et PV par figurine ;
- ✏️ PV réorganisés : effectif vivant (B2) + HP_MAX (B3) + PV de la figurine blessée (B2) ;
- ➕ profil d'escouade brut : MOVE, HP_MAX, T, save, invulnérable.

Contre-épreuves intégrées :
- `test_wounded_model_hp_is_observed` : une figurine entamée fait bouger la dimension B2 ;
  sous l'ancien code cette information n'existait qu'au niveau figurine (bloc C), supprimé ;
- `test_squad_profile_is_raw` : les stats sortent en valeurs brutes de datasheet (MOVE en
  subhex, save 3+ = 3.0), pas en fractions ;
- `test_enemy_block_has_no_computed_features` : le bloc ennemi ne doit plus dépendre de MON
  arme — toute réintroduction d'une rentabilité/menace le casse.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    MODEL_TYPE_BIN_FIELDS,
    SELF_MODEL_CONT_SIZE,
    UNIT_CONT_SIZE,
    unit_cont_index,
)
from engine.w40k_core import W40KEngine

CONT_HP_WOUNDED = unit_cont_index("wounded_hp_ratio")
CONT_MOVE = unit_cont_index("move")
CONT_HP_MAX = unit_cont_index("hp_max")
CONT_T = unit_cont_index("toughness")
CONT_SAVE = unit_cont_index("armor_save")
CONT_INVUL = unit_cont_index("invul_save")


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int, n_models: int) -> Dict[str, Any]:
    specs = [
        {"col": col + 2 * i, "row": row, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10}
        for i in range(n_models)
    ]
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 2 * n_models, "HP_MAX": 2, "MOVE": 6, "T": 5,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 4,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 2, "VALUE": 10 * n_models,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config() -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
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
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, 10, 20, n_models=3),
            _unit_cfg(2, 2, 60, 20, n_models=3),
        ],
    }


@pytest.fixture
def engine():
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=_config())
    eng.reset()
    return eng


def test_squad_profile_is_raw(engine):
    """MOVE / HP_MAX / T / save / invulnérable sortent en valeurs brutes de datasheet."""
    cont = engine.obs_builder.build_squad_observation(engine.game_state, "1")["allies_cont"][0]
    inches_to_subhex = int(engine.game_state["inches_to_subhex"])
    assert cont[CONT_MOVE] == pytest.approx(6.0 * inches_to_subhex)  # MOVE en subhex
    assert cont[CONT_HP_MAX] == pytest.approx(2.0)
    assert cont[CONT_T] == pytest.approx(5.0)
    assert cont[CONT_SAVE] == pytest.approx(3.0)
    assert cont[CONT_INVUL] == pytest.approx(4.0)


def test_wounded_model_hp_is_observed(engine):
    """PV de la figurine blessée : 1.0 tant qu'aucune n'est entamée, puis son ratio réel."""
    gs = engine.game_state
    cont = engine.obs_builder.build_squad_observation(gs, "1")["allies_cont"][0]
    assert cont[CONT_HP_WOUNDED] == pytest.approx(1.0)

    gs["models_cache"]["1#1"]["HP_CUR"] = 1  # figurine a 1 PV sur 2
    cont = engine.obs_builder.build_squad_observation(gs, "1")["allies_cont"][0]
    assert cont[CONT_HP_WOUNDED] == pytest.approx(0.5)


def test_block_sizes_after_removals(engine):
    """Bloc figurine : uniquement l'individuel (position), le profil étant au niveau TYPE."""
    assert SELF_MODEL_CONT_SIZE == 2  # col_rel, row_rel
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    assert obs["allies_cont"].shape == (ObservationBuilder.K_ALLY_SLOTS, UNIT_CONT_SIZE)


def test_model_block_holds_only_positions(engine):
    """Bloc figurines : seules les positions relatives restent (PV et index d'arme supprimés).

    Contre-épreuve : on blesse une figurine et on change son arme CC sélectionnée — le bloc
    figurines ne doit PAS bouger (sous l'ancien layout, deux de ses dimensions changeaient).
    """
    gs = engine.game_state
    before = engine.obs_builder.build_squad_observation(gs, "1")["self_models_cont"].tolist()

    gs["models_cache"]["1#0"]["HP_CUR"] = 1  # PV COURANTS : plus observés par figurine
    gs["models_cache"]["1#0"]["selectedCcWeaponIndex"] = 1
    after = engine.obs_builder.build_squad_observation(gs, "1")["self_models_cont"].tolist()
    assert before == after

    # ... alors qu'un DEPLACEMENT de la meme figurine, lui, doit bien bouger le bloc.
    gs["models_cache"]["1#0"]["col"] = int(gs["models_cache"]["1#0"]["col"]) + 3
    moved = engine.obs_builder.build_squad_observation(gs, "1")["self_models_cont"].tolist()
    assert moved != after


def test_enemy_block_has_no_computed_features(engine):
    """Bloc ennemi : aucune dimension ne dépend de MON arme (rentabilité/menace supprimées).

    Contre-épreuve : changer l'arme sélectionnée de mon escouade ne doit plus rien changer au
    bloc ennemi. Sous l'ancien code, `value_over_ttk` et `threat_level` en dépendaient.
    """
    gs = engine.game_state
    before = engine.obs_builder.build_squad_observation(gs, "1")["enemies_cont"].tolist()

    for mid in gs["squad_models"]["1"]:
        gs["models_cache"][mid]["RNG_WEAPONS"] = [
            {"ATK": 2, "STR": 12, "AP": 3, "DMG": 6, "NB": 5, "RNG": 48, "WEAPON_RULES": []}
        ]
        gs["models_cache"][mid]["selectedRngWeaponIndex"] = 0
    after = engine.obs_builder.build_squad_observation(gs, "1")["enemies_cont"].tolist()
    assert before == after


# ---------------------------------------------------------------------------
# Bloc C1 (V11 §9.4) — TYPES de figurines : profil + effectif, jamais répété
# ---------------------------------------------------------------------------
# Une escouade est homogène sauf exceptions (arme spéciale, sergent, personnage attaché —
# règle 19 : fusionné COMME figurine, avec ses propres PV/save). Décrire chaque figurine
# répéterait le même profil des dizaines de fois ET plafonnerait l'effectif observé à
# SQUAD_TOP_K ; décrire les TYPES avec leur effectif décrit l'escouade ENTIÈRE.

_ROLE_BITS = len(ObservationBuilder.SQUAD_MODEL_ROLES)
TYPE_HP_MAX = 0
TYPE_T = 1
TYPE_SAVE = 2
TYPE_INVUL = 3
TYPE_COUNT = 4


def _types(engine):
    """[(role|None, HP_MAX, T, save, invul, effectif), …] tels que lus DANS l'observation."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    # Sous-registre « types » de l'unite ACTIVE = ligne 0 des allies.
    cont, binv = obs["allies_types_cont"][0], obs["allies_types_bin"][0]
    present = MODEL_TYPE_BIN_FIELDS.index("present")
    out = []
    for t in range(ObservationBuilder.K_MODEL_TYPES):
        if float(binv[t][present]) != 1.0:  # slot de type occupé ?
            continue
        onehot = [float(binv[t][i]) for i in range(_ROLE_BITS)]
        role = ObservationBuilder.SQUAD_MODEL_ROLES[onehot.index(1.0)] if 1.0 in onehot else None
        out.append((
            role,
            float(cont[t][TYPE_HP_MAX]), float(cont[t][TYPE_T]),
            float(cont[t][TYPE_SAVE]), float(cont[t][TYPE_INVUL]),
            float(cont[t][TYPE_COUNT]),
        ))
    return out


def test_homogeneous_squad_is_one_type(engine):
    """3 figurines identiques -> UN type et un effectif de 3, pas trois descriptions répétées."""
    assert _types(engine) == [(None, 2.0, 5.0, 3.0, 4.0, 3.0)]


def test_attached_character_is_its_own_type(engine):
    """Le perso attaché forme son propre type ; les figurines de base gardent le leur."""
    gs = engine.game_state
    gs["models_cache"]["1#1"].update(
        {"HP_MAX": 6, "T": 8, "ARMOR_SAVE": 2, "INVUL_SAVE": 4, "role": "leader"}
    )
    types = _types(engine)
    assert ("leader", 6.0, 8.0, 2.0, 4.0, 1.0) in types
    assert (None, 2.0, 5.0, 3.0, 4.0, 2.0) in types, "les 2 Boyz restants forment un type d'effectif 2"
    assert len(types) == 2


def test_every_model_is_counted_beyond_the_model_block_cap():
    """Contre-épreuve du plafond : une escouade de 12 figurines est décrite ENTIÈREMENT.

    Le bloc figurines n'expose que SQUAD_TOP_K positions ; le bloc TYPES, lui, doit totaliser
    l'effectif complet. Sous l'ancien layout par figurine, la moitié de l'escouade — dont les
    personnages attachés, créés en dernier — n'apparaissait nulle part.
    """
    n_models = ObservationBuilder.SQUAD_TOP_K + 6
    cfg = _config()
    cfg["units"][0] = _unit_cfg(1, 1, 10, 20, n_models=n_models)
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    gs = eng.game_state
    last = f"1#{n_models - 1}"          # dernière figurine créée = le perso attaché
    gs["models_cache"][last].update({"HP_MAX": 6, "ARMOR_SAVE": 2, "role": "leader"})

    types = _types(eng)
    assert sum(t[5] for t in types) == float(n_models), "l'effectif total doit être décrit"
    assert any(t[0] == "leader" and t[5] == 1.0 for t in types), (
        "le perso attaché, créé en dernier, doit avoir son type"
    )


def test_type_order_is_stable_across_steps(engine):
    """L'ordre des types ne dépend pas de l'état mouvant : PPO a besoin de slots stables."""
    gs = engine.game_state
    gs["models_cache"]["1#1"].update({"HP_MAX": 6, "role": "leader"})
    before = _types(engine)

    gs["models_cache"]["1#0"]["col"] = int(gs["models_cache"]["1#0"]["col"]) + 5
    gs["models_cache"]["1#2"]["HP_CUR"] = 1
    assert _types(engine) == before


def test_role_bits_cover_every_engine_role():
    """Le one-hot couvre TOUS les rôles que le moteur peut produire (aucun rôle muet)."""
    from engine.phase_handlers.shared_utils import ROLE_TIER

    assert set(ObservationBuilder.SQUAD_MODEL_ROLES) == set(ROLE_TIER)


def test_engagement_counters_cover_the_whole_squad():
    """Les compteurs d'engagement portent l'escouade ENTIÈRE, pas seulement les slots exposés."""
    n_models = ObservationBuilder.SQUAD_TOP_K + 4
    cfg = _config()
    cfg["units"][0] = _unit_cfg(1, 1, 10, 20, n_models=n_models)
    cfg["units"][1] = _unit_cfg(2, 2, 11, 20, n_models=1)  # ennemi collé à la ligne alliée
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()

    cont = eng.obs_builder.build_squad_observation(eng.game_state, "1")["allies_cont"][0]
    n_fight = float(cont[unit_cont_index("n_fight_eligible")])
    n_ez = float(cont[unit_cont_index("n_in_enemy_ez")])
    n_buddy = float(cont[unit_cont_index("n_relayed_ez")])
    from engine.phase_handlers.shared_utils import get_fighting_models

    assert n_fight == float(len(set(get_fighting_models(eng.game_state, "1"))))
    assert n_ez >= 1.0
    assert n_buddy >= 0.0
