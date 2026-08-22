"""T-E — TOUTES les escouades ennemies ont un slot : observables ET tirables (§1.1).

Le défaut corrigé ici (V11_entity_encoder_pointer.md §1.1, mesuré le 2026-07-26 puis re-mesuré
avant T-E) : `init_enemy_slot_mapping` figeait **5** slots au début de partie et n'était jamais
recalculé. Sur les rosters d'entraînement réels, **9 resets sur 10** comptent au moins
6 escouades d'un côté — donc au moins une escouade ennemie était **absente de l'observation**
et **impossible à prendre pour cible** pendant toute la partie ; et le slot d'une escouade morte
restait vide DÉFINITIVEMENT au lieu d'être rendu à celle qui n'en avait pas. Plafond silencieux,
jamais logué.

Contre-épreuves intégrées :
- `test_six_enemy_squads_are_all_observable_and_shootable` : 6 escouades ennemies, toutes à
  portée — le 6ᵉ slot n'existait pas avant T-E ;
- `test_a_freed_slot_is_reassigned` : une escouade mappée meurt, une escouade sans slot prend sa
  place (avant T-E : jamais) ;
- `test_a_living_squad_never_changes_slot` : la réattribution ne casse PAS la stabilité des
  slots vivants — c'est l'invariant D1 (obs-slot-i ↔ action-slot-i) ;
- `test_overflow_is_logged_never_silent` : au-delà de K, le dépassement est TRACÉ.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.macro_intents import SHOOT_SLOT_BASE, SHOOT_SLOT_COUNT
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.phase_handlers.shared_utils import (
    SQUAD_ACTION_SHOOT_SLOT_COUNT,
    build_squad_action_mask,
    destroy_model,
    get_enemy_slot_mapping,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon() -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 60,
            "WEAPON_RULES": [], "display_name": "Test Rifle"}


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], *, oc: int = 2) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": oc, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
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
        eng = W40KEngine(config=build_engine_config(_config(units)))
    eng.reset()
    return eng


def _enemies(n: int, *, start_id: int = 10) -> List[Dict[str, Any]]:
    """`n` escouades ennemies alignées, toutes à portée de tir de l'escouade 1."""
    return [_unit_cfg(start_id + i, 2, [(40 + 2 * i, 20)], oc=1 + (i % 3)) for i in range(n)]


def test_slot_count_matches_the_action_space():
    """Un slot d'observation = une action de tir. Deux valeurs = desalignement D1."""
    assert ObservationBuilder.K_ENEMY_SLOTS == SQUAD_ACTION_SHOOT_SLOT_COUNT == SHOOT_SLOT_COUNT


def test_six_enemy_squads_are_all_observable_and_shootable():
    """6 escouades ennemies : les 6 sont dans l'observation ET dans le masque de tir.

    C'est le cas MESURÉ le plus fréquent des rosters réels. Avec 5 slots, la 6ᵉ n'existait ni
    dans l'observation ni dans l'espace d'action.
    """
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(6))
    gs = eng.game_state
    gs["phase"] = "shoot"

    mapping = get_enemy_slot_mapping(gs, 1)
    assert sum(1 for sid in mapping if sid is not None) == 6

    obs = eng.obs_builder.build_squad_observation(gs, "1")
    present = unit_bin_index("present")
    assert int(obs["enemies_bin"][:, present].sum()) == 6

    mask = build_squad_action_mask(gs, "1")
    shootable = [
        slot_i for slot_i in range(SHOOT_SLOT_COUNT)
        if int(mask[SHOOT_SLOT_BASE + slot_i]) == 1
    ]
    assert len(shootable) == 6, f"seuls {len(shootable)} slots tirables sur 6 ennemis"


def test_a_living_squad_never_changes_slot():
    """Stabilité (invariant D1) : un ennemi vivant garde son slot d'un appel à l'autre."""
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(4))
    gs = eng.game_state
    first = get_enemy_slot_mapping(gs, 1)
    # Un changement d'état qui rebat la menace (HP x OC) ne doit PAS permuter les slots.
    destroy_model(gs, "11#0", reason="combat")
    second = get_enemy_slot_mapping(gs, 1)
    for slot_i, sid in enumerate(first):
        if sid is not None and sid in gs["units_cache"]:
            assert second[slot_i] == sid, f"le slot {slot_i} a change d'escouade"


def test_a_freed_slot_is_reassigned():
    """Une escouade sans slot prend celui d'une escouade morte (avant T-E : jamais).

    K + 1 escouades ennemies : une n'a pas de slot. On tue une escouade mappée — son slot doit
    revenir à celle qui attendait, et non rester vide définitivement.
    """
    n = SQUAD_ACTION_SHOOT_SLOT_COUNT + 1
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(n))
    gs = eng.game_state
    mapping = get_enemy_slot_mapping(gs, 1)
    mapped = {sid for sid in mapping if sid is not None}
    assert len(mapped) == SQUAD_ACTION_SHOOT_SLOT_COUNT
    orphan = next(
        sid for sid, e in gs["units_cache"].items()
        if int(e["player"]) == 2 and sid not in mapped
    )

    victim = mapping[0]
    assert victim is not None
    for mid in list(gs["squad_models"][victim]):
        destroy_model(gs, mid, reason="combat")

    after = get_enemy_slot_mapping(gs, 1)
    assert orphan in after, "l'escouade sans slot n'a PAS ete promue apres une mort"
    assert victim not in after
    # … et sans deplacer les autres.
    for slot_i, sid in enumerate(mapping):
        if sid is not None and sid != victim:
            assert after[slot_i] == sid


def test_overflow_is_logged_never_silent():
    """Au-dela de K escouades ennemies, le depassement est TRACE (§11), jamais silencieux."""
    n = SQUAD_ACTION_SHOOT_SLOT_COUNT + 2
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(n))
    gs = eng.game_state
    gs.pop("enemy_slot_mapping_p1", None)
    captured: List[str] = []
    with patch("engine.game_utils.add_debug_file_log",
               side_effect=lambda state, msg: captured.append(msg)):
        get_enemy_slot_mapping(gs, 1)
    assert any("sans slot" in m for m in captured), "depassement de slots NON logue"


def test_no_overflow_log_when_everyone_fits():
    """Contre-epreuve : aucun log tant que toutes les escouades ont un slot."""
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(6))
    gs = eng.game_state
    gs.pop("enemy_slot_mapping_p1", None)
    captured: List[str] = []
    with patch("engine.game_utils.add_debug_file_log",
               side_effect=lambda state, msg: captured.append(msg)):
        get_enemy_slot_mapping(gs, 1)
    assert not [m for m in captured if "sans slot" in m]


def test_enemy_in_strategic_reserves_gets_no_slot():
    """Une escouade ennemie hors table (col=-1) ne reçoit pas de slot (§20 réserves stratégiques).

    Bug corrigé : la garde entry_is_on_battlefield manquait côté ennemi dans
    _refresh_enemy_slot_mapping, donc col=-1 était encodé comme feature spatiale.
    """
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(2))
    gs = eng.game_state
    # On force l'une des deux escouades ennemies en réserves stratégiques (sentinelle col=-1).
    gs.pop("enemy_slot_mapping_p1", None)
    enemy_sids = [str(sid) for sid, e in gs["units_cache"].items()
                  if int(e["player"]) == 2]
    reserve_sid = enemy_sids[0]
    gs["units_cache"][reserve_sid]["col"] = -1
    for mid in gs["squad_models"].get(reserve_sid, []):
        gs["models_cache"][mid]["col"] = -1

    mapping = get_enemy_slot_mapping(gs, 1)
    assert reserve_sid not in mapping, (
        f"Escouade {reserve_sid} (col=-1, réserves) obtient un slot : "
        "entry_is_on_battlefield absent côté ennemi"
    )
    on_table = [s for s in mapping if s is not None]
    assert len(on_table) == 1


def test_enemy_threat_order_oc_fallback_when_oc_total_is_zero():
    """La branche OC fallback de _enemy_threat_order lit les models quand OC_TOTAL == 0.

    Sans fallback, oc_total=0 → threat=0 → l'escouade serait reléguée en dernier slot.
    Avec fallback, l'OC est recalculé depuis models_cache.
    """
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(2))
    gs = eng.game_state
    gs.pop("enemy_slot_mapping_p1", None)
    enemy_sids = sorted(
        [str(sid) for sid, e in gs["units_cache"].items() if int(e["player"]) == 2],
        key=str,
    )
    # Escouade A : OC_TOTAL mis à zéro ; ses models ont OC individuel ≥ 1 (via _unit_cfg oc=).
    # Elle doit remonter en slot 0 si son fallback-OC × HP > escouade B.
    sid_a, sid_b = enemy_sids[0], enemy_sids[1]
    # Donner à A beaucoup plus de HP pour que le fallback lui donne une menace supérieure à B.
    gs["units_cache"][sid_a]["HP_CUR"] = 10
    gs["units_cache"][sid_a]["OC_TOTAL"] = 0
    # B : HP=1, OC_TOTAL=100 → threat=100. A devra avoir oc_fallback × 10 > 100 → oc_fallback>10.
    gs["units_cache"][sid_b]["HP_CUR"] = 1
    gs["units_cache"][sid_b]["OC_TOTAL"] = 100
    # On injecte OC=20 dans chaque model de A pour que le fallback donne oc=20, threat=200 > 100.
    for mid in gs["squad_models"].get(sid_a, []):
        gs["models_cache"][mid]["OC"] = 20

    mapping = get_enemy_slot_mapping(gs, 1)
    filled = [s for s in mapping if s is not None]
    assert filled[0] == sid_a, (
        f"Slot 0 attendu = {sid_a} (fallback OC×HP=200) mais obtenu {filled[0]}. "
        "La branche OC_TOTAL==0 ne bascule pas sur models_cache."
    )


def test_dead_squad_leaves_an_empty_slot_in_the_observation():
    """Un slot dont l'escouade est morte est vide dans l'obs (mask=0), pas rempli de zeros muets."""
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)])] + _enemies(2))
    gs = eng.game_state
    mapping = get_enemy_slot_mapping(gs, 1)
    victim = mapping[0]
    assert victim is not None
    for mid in list(gs["squad_models"][victim]):
        destroy_model(gs, mid, reason="combat")
    obs = eng.obs_builder.build_squad_observation(gs, "1")
    present = unit_bin_index("present")
    assert int(obs["enemies_bin"][:, present].sum()) == 1
    survivors = get_enemy_slot_mapping(gs, 1)
    assert victim not in survivors
