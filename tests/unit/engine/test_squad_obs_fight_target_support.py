"""Verrou : `n_models_engaging` — combien de MES figurines peuvent frapper CHAQUE cible (04.02).

Trou fermé ici. **V11 §9 P3-1** a fait de la cible de mêlée une décision de l'agent (une action
par slot ennemi, scorée par tête pointeur sur l'embedding de la cible). Restait un angle mort :
l'observation décrivait la cible (PV, T, save, armes, `edge_distance`) mais **pas la force avec
laquelle je la frapperais**. Or c'est le premier facteur du choix — engagée par 8 figurines ou
par 1, la même cible ne vaut pas la même chose.

Pourquoi les champs existants ne suffisaient PAS, et c'est tout l'objet de ce fichier :
- `n_fight_eligible` agrège sur TOUTES les cibles à la fois : à deux ennemis engagés, il rend le
  même nombre pour les deux (`test_field_discriminates_between_two_engaged_enemies`) ;
- `edge_distance` mesure l'escouade entière : deux cibles à la même distance d'ancre peuvent
  mobiliser un nombre très différent de figurines (04.02 s'évalue PAR FIGURINE, pas par ancre).

Décision d'implémentation verrouillée ici : l'oracle est `_model_can_fight_target`, la fonction
MOTEUR qu'emprunte la déclaration d'attaque (`FIGHT_DECLARE_CTX.can_target`) — jamais une
réimplémentation du test d'engagement, qui pourrait diverger sur la métrique et annoncer un
volume d'attaques que la résolution ne produit pas (`test_agrees_with_the_engine_declaration_oracle`).

Et c'est une grandeur de PAIRE (mon escouade → cette cible), comme `los_can_see` : elle n'a aucun
sens sur une entité alliée, où elle reste donc à 0 (`test_allies_never_carry_the_field`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index, unit_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

CONT_ENGAGING = unit_cont_index("n_models_engaging")
CONT_FIGHT_ELIGIBLE = unit_cont_index("n_fight_eligible")
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


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
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
        "units": units,
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    return eng


def _engaging_by_squad(engine: W40KEngine, observer: str) -> Dict[str, float]:
    """`n_models_engaging` par escouade ennemie, lu au SLOT que l'action de combat désigne."""
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
        out[str(sid)] = float(obs["enemies_cont"][slot_i][CONT_ENGAGING])
    return out


def test_counts_only_the_models_actually_engaged():
    """3 figurines à moi, 2 seulement au contact de l'ennemi -> 2, pas 3."""
    # (30,20) et (29,20) touchent (31,20)... non : seule (30,20) le touche. On colle donc deux
    # figurines de part et d'autre de l'ennemi, et on en laisse une au loin.
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20), (32, 20), (50, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    assert _engaging_by_squad(eng, "1")["2"] == 2.0


def test_field_discriminates_between_two_engaged_enemies():
    """LE cas qui justifie le champ : deux cibles engagées, des volumes d'attaque différents.

    `n_fight_eligible` rend la MÊME valeur pour les deux (il agrège) — c'est exactement l'angle
    mort que `n_models_engaging` comble.
    """
    # Ennemi "2" collé à deux de mes figurines, ennemi "3" à une seule.
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20), (32, 20), (30, 30)]),
        _unit_cfg(2, 2, [(31, 20)]),
        _unit_cfg(3, 2, [(30, 31)]),
    ]))
    engaging = _engaging_by_squad(eng, "1")
    assert engaging["2"] == 2.0
    assert engaging["3"] == 1.0

    # Contre-épreuve : le champ agrégé ne distingue PAS les deux cibles.
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    n_fight_eligible = float(obs["allies_cont"][0][CONT_FIGHT_ELIGIBLE])
    assert n_fight_eligible == 3.0, (
        "les 3 figurines sont éligibles au combat : la valeur agrégée est la même quelle que "
        "soit la cible visée — d'où l'ambiguïté que ce champ lève"
    )


def test_agrees_with_the_engine_declaration_oracle():
    """L'oracle est la fonction MOTEUR de déclaration d'attaque, pas une réimplémentation.

    Si l'observation comptait avec sa propre métrique d'engagement, elle annoncerait un volume
    d'attaques que la résolution ne produirait pas.
    """
    from engine.phase_handlers.fight_handlers import _model_can_fight_target

    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20), (32, 20), (50, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    gs = eng.game_state
    expected = sum(
        1
        for mid in gs["squad_models"]["1"]
        if mid in gs["models_cache"]
        and _model_can_fight_target(gs, gs["models_cache"][mid], "1", "2")
    )
    assert expected > 0, "fixture invalide : aucune figurine engagée"
    assert _engaging_by_squad(eng, "1")["2"] == float(expected)


def test_zero_when_out_of_engagement_range():
    """Hors zone d'engagement : 0. Le pool 12.05 sert de garde, aucune figurine n'est comptée."""
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ]))
    assert _engaging_by_squad(eng, "1")["2"] == 0.0


def test_matches_the_action_mask_target_pool():
    """Parité obs/masque : `n_models_engaging > 0` ⟺ le masque ouvre le slot de combat.

    C'est l'invariant qui rend le champ utile à la décision : l'agent ne doit pas voir « je peux
    frapper fort » sur une cible que le masque lui interdit, ni l'inverse.
    """
    from engine.macro_intents import FIGHT_SLOT_BASE
    from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
    from engine.game_utils import get_unit_by_id
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20), (32, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
        _unit_cfg(3, 2, [(60, 20)]),
    ]))
    gs = eng.game_state
    unit = get_unit_by_id(gs, "1")
    assert unit is not None
    pool = {str(t) for t in _fight_build_valid_target_pool(gs, unit)}
    engaging = _engaging_by_squad(eng, "1")

    our_player = int(gs["units_cache"]["1"]["player"])
    slot_map = get_enemy_slot_mapping(gs, our_player)
    for slot_i, sid in enumerate(slot_map):
        if sid is None:
            continue
        in_pool = str(sid) in pool
        assert (engaging[str(sid)] > 0.0) == in_pool, (
            f"slot {slot_i} ({sid}) : obs dit {engaging[str(sid)]} engagée(s), "
            f"pool 12.05 dit {'frappable' if in_pool else 'hors de portée'} — "
            f"l'action de combat {FIGHT_SLOT_BASE + slot_i} serait incohérente avec l'obs"
        )


def test_allies_never_carry_the_field():
    """Grandeur de PAIRE : sans sens sur une alliée (contre quel attaquant ?), donc 0."""
    eng = _make_engine(_config([
        _unit_cfg(1, 1, [(30, 20)]),
        _unit_cfg(4, 1, [(29, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
    ]))
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    for row in range(ObservationBuilder.K_ALLY_SLOTS):
        if obs["allies_bin"][row][BIN_PRESENT] != 1.0:
            continue
        assert float(obs["allies_cont"][row][CONT_ENGAGING]) == 0.0, (
            f"ligne alliée {row} porte n_models_engaging — ce champ n'a de sens que sur un ennemi"
        )
