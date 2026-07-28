"""Verrou : `charge_reachable_max_roll` — cette cible de charge est-elle ATTEIGNABLE (11.02/11.04) ?

Trou fermé ici. **V11 §9 P3-2** a fait de la cible de charge une décision de l'agent (une action
par slot ennemi, scorée par tête pointeur sur l'embedding de la cible). Restait un angle mort :
l'observation décrivait la cible (PV, T, save, armes, `edge_distance`) mais **pas si une charge
vers elle peut aboutir**. Or une charge ratée coûte l'ACTIVATION ENTIÈRE de l'unité (11.02
étape 3 : « Otherwise, your unit does not make a charge move »).

Pourquoi `edge_distance` ne suffit PAS, et c'est tout l'objet de ce fichier : elle mesure une
distance à vol d'oiseau. Une cible à 5" peut être structurellement inatteignable — aucune case
légale au contact (`test_zero_when_the_target_has_no_legal_landing_hex`, la contre-épreuve de
distance courte), ER d'une escouade non ciblée, ou pénalité de descente 13.06 retranchée du jet.

Décision d'implémentation verrouillée ici : l'oracle est `charge_build_valid_plan`, la fonction
MOTEUR qu'exécute le commit (`test_agrees_with_the_engine_plan_oracle`) — jamais une
réimplémentation, qui annoncerait une atteignabilité que la résolution ne produirait pas.

Et c'est une grandeur de PAIRE (mon escouade → cette cible), comme `los_can_see` : elle n'a aucun
sens sur une entité alliée ni hors de la phase de charge, où elle reste donc à 0.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.w40k_core import W40KEngine

BIN_CHARGE_REACHABLE = unit_bin_index("charge_reachable_max_roll")
BIN_PRESENT = unit_bin_index("present")


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    units: List[Dict[str, Any]], wall_hexes: List[List[int]] | None = None
) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": wall_hexes or [], "inches_to_subhex": 1,
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
        "units": units,
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    return eng


def _reachable_by_squad(engine: W40KEngine, observer: str) -> Dict[str, float]:
    """`charge_reachable_max_roll` par escouade ennemie, lu au SLOT que l'action désigne."""
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    gs = engine.game_state
    obs = engine.obs_builder.build_squad_observation(gs, observer)
    our_player = int(gs["units_cache"][observer]["player"])
    slot_map = get_enemy_slot_mapping(gs, our_player)
    out: Dict[str, float] = {}
    for slot_i, sid in enumerate(slot_map):
        if sid is None:
            continue
        assert obs["enemies_bin"][slot_i][BIN_PRESENT] == 1.0, f"slot {slot_i} mappé mais absent"
        out[str(sid)] = float(obs["enemies_bin"][slot_i][BIN_CHARGE_REACHABLE])
    return out


def _charge_phase(engine: W40KEngine) -> None:
    engine.game_state["phase"] = "charge"


def test_set_for_a_reachable_target_in_the_charge_phase():
    """Cible à 5", terrain dégagé : le bit est à 1 — une charge peut aboutir."""
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    _charge_phase(eng)
    assert _reachable_by_squad(eng, "1")["2"] == 1.0


def test_zero_outside_the_charge_phase():
    """Hors phase de charge, le bit vaut 0 : son masque est le one-hot `phase_charge`.

    C'est aussi la garde de COÛT — le plan de charge (l'appel le plus cher de l'observation) ne
    doit pas être construit aux 5 autres phases.
    """
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    eng.game_state["phase"] = "shoot"
    assert _reachable_by_squad(eng, "1")["2"] == 0.0


def test_zero_beyond_the_declaration_range():
    """Cible à plus de 12" : non déclarable (11.02), donc bit à 0 — et aucun plan construit."""
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ]))
    _charge_phase(eng)
    assert _reachable_by_squad(eng, "1")["2"] == 0.0


def test_zero_when_the_target_has_no_legal_landing_hex():
    """LE cas qui justifie le champ : cible PROCHE mais structurellement inatteignable.

    La cible est cernée de murs : aucune case au contact n'est légale (`_hex_legal_for_charge`),
    donc aucun plan n'existe, même au jet maximal. `edge_distance` est pourtant IDENTIQUE au cas
    atteignable ci-dessus — c'est exactement l'ambiguïté que ce bit lève, et sans lui l'agent
    déclarerait une charge perdue d'avance.
    """
    from engine.combat_utils import get_hex_neighbors
    from engine.observation_entities import unit_cont_index

    walls = [[int(c), int(r)] for c, r in get_hex_neighbors(31, 20)]
    units = [_unit_cfg(1, 1, [(26, 20)]), _unit_cfg(2, 2, [(31, 20)])]
    eng_blocked = _make_engine(_config(units, wall_hexes=walls))
    _charge_phase(eng_blocked)
    assert _reachable_by_squad(eng_blocked, "1")["2"] == 0.0

    # Contre-épreuve : à distance IDENTIQUE et sans les murs, le bit est à 1 — la seule variable
    # est l'atteignabilité, que `edge_distance` ne porte pas.
    eng_open = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    _charge_phase(eng_open)
    assert _reachable_by_squad(eng_open, "1")["2"] == 1.0

    cont_edge = unit_cont_index("edge_distance")
    obs_blocked = eng_blocked.obs_builder.build_squad_observation(eng_blocked.game_state, "1")
    obs_open = eng_open.obs_builder.build_squad_observation(eng_open.game_state, "1")
    assert (
        float(obs_blocked["enemies_cont"][0][cont_edge])
        == float(obs_open["enemies_cont"][0][cont_edge])
    ), "fixture invalide : les deux cas doivent avoir la MÊME edge_distance"


def test_agrees_with_the_engine_plan_oracle():
    """L'oracle est `charge_build_valid_plan`, la fonction qu'exécute le commit.

    Si l'observation décidait de l'atteignabilité avec sa propre logique, elle annoncerait des
    charges que la résolution refuserait — et l'agent apprendrait sur une carte fausse.
    """
    from engine.phase_handlers.shared_utils import CHARGE_MAX_ROLL, charge_build_valid_plan

    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
        _unit_cfg(3, 2, [(60, 20)]),
    ]))
    _charge_phase(eng)
    observed = _reachable_by_squad(eng, "1")
    for target_id in ("2", "3"):
        expected = charge_build_valid_plan(
            eng.game_state, "1", [target_id], CHARGE_MAX_ROLL
        ) is not None
        assert observed[target_id] == float(expected), f"desaccord avec l'oracle sur {target_id}"


def test_allies_never_carry_the_field():
    """Grandeur de PAIRE : 0 sur les entités alliées, y compris l'unité active."""
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(4, 1, [(27, 21)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    _charge_phase(eng)
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    for row in range(obs["allies_bin"].shape[0]):
        assert float(obs["allies_bin"][row][BIN_CHARGE_REACHABLE]) == 0.0


def test_matches_the_action_mask_charge_slots():
    """Parité obs/masque : un bit à 1 implique que le masque OUVRE le slot de charge.

    L'implication n'est pas une équivalence, et c'est voulu : le masque suit 11.02 (déclaration
    possible), le bit suit 11.04 (une charge peut aboutir). Une cible déclarable mais
    inatteignable garde donc son slot ouvert — l'agent a le droit de tenter, il sait juste que
    c'est perdu. L'inverse serait une rupture : voir « atteignable » ce que le masque interdit.
    """
    from engine.macro_intents import CHARGE_SLOT_BASE
    from engine.phase_handlers.shared_utils import (
        build_squad_action_mask,
        get_enemy_slot_mapping,
    )

    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(26, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
        _unit_cfg(3, 2, [(60, 20)]),
    ]))
    _charge_phase(eng)
    gs = eng.game_state
    slot_map = get_enemy_slot_mapping(gs, 1)
    mask = build_squad_action_mask(gs, "1", enemy_slot_ids=slot_map)
    obs = eng.obs_builder.build_squad_observation(gs, "1")
    opened_any = False
    for slot_i, sid in enumerate(slot_map):
        if sid is None:
            continue
        if float(obs["enemies_bin"][slot_i][BIN_CHARGE_REACHABLE]) == 1.0:
            assert mask[CHARGE_SLOT_BASE + slot_i] == 1, (
                f"slot {slot_i} annonce atteignable mais le masque le refuse"
            )
            opened_any = True
    assert opened_any, "fixture invalide : aucune cible atteignable"
