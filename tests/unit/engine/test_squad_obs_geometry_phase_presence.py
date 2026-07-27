"""V11 §0.32 T-H / T-I / T-J — masque de présence, géométrie unique, phase en one-hot.

Les trois constats de l'audit du 2026-07-28 portaient sur la FORME de l'observation, pas sur son
contenu. Ce fichier les verrouille :

- **T-H** : le bloc `self_models_*` n'avait AUCUN bit de présence — l'extracteur déduisait le
  masque de la ligne entière (`(|cont| + |bin|) > 0`). Une figurine posée sur le centroïde arrondi
  et sans aucun drapeau avait une ligne entièrement nulle : elle était comptée **absente**, exclue
  de l'agrégation et du dénominateur de `EntityRunningNorm`. `test_model_on_centroid_is_present`
  place exactement cette figurine (la fixture la garantit : `col_rel == row_rel == 0` et les trois
  drapeaux à zéro) — c'est le cas qui rougissait avant le bit `present`.
- **T-I** : `col_rel` / `row_rel` étaient des différences de coordonnées OFFSET, alors que la
  grille égocentrique et les directions d'objectif travaillent dans la projection `_hex_center`.
  En offset, deux VOISINS hexagonaux de parités de ligne différentes n'ont pas la même norme
  (1 contre √2) : l'anisotropie de parité, précisément ce que `spatial_grid` a choisi d'éviter.
  Les tests d'isotropie ci-dessous échouaient avec l'ancien encodage.
- **T-J** : `deployment` et `command` partageaient la valeur `phase = 0.0` — deux phases dont les
  ids d'action 4–8 ne signifient PAS la même chose (slot de déploiement contre cellule de move).
  Le one-hot les distingue, et une phase inconnue LÈVE au lieu de retomber sur 0.0.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.hex_utils import _hex_center
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    OBS_PHASE_IDS,
    global_bin_index,
    self_model_bin_index,
    self_model_cont_index,
    unit_cont_index,
)
from engine.w40k_core import W40KEngine

SM_COL = self_model_cont_index("col_rel")
SM_ROW = self_model_cont_index("row_rel")
SM_PRESENT = self_model_bin_index("present")
SM_FIGHT = self_model_bin_index("fight_eligible")
SM_IN_EZ = self_model_bin_index("in_enemy_ez")
SM_RELAYED = self_model_bin_index("ez_relayed_by_ally")
E_COL = unit_cont_index("col_rel")
E_ROW = unit_cont_index("row_rel")


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
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=_config(units))
    eng.reset()
    return eng


def _obs(engine):
    return engine.obs_builder.build_squad_observation(engine.game_state, "1")


#: Escouade de 4 figurines dont le centroïde tombe EXACTEMENT sur l'hex (30,20), avec :
#: - une figurine PILE sur ce centroïde -> ligne nulle hors bit de présence (cas T-H) ;
#: - trois figurines qui sont des VOISINS hexagonaux de (30,20), de parités de ligne et de
#:   colonne différentes -> normes offset différentes (1, 1, √2) mais MÊME distance hex (cas T-I).
_CENTROID_SQUAD = [(30, 20), (29, 19), (31, 20), (30, 21)]
_HEX_STEP = math.sqrt(3.0)  # distance centre-a-centre de deux hexes voisins (hex_radius = 1)


def test_fixture_is_the_pathological_case():
    """Garde-fou de la fixture : centroïde exact, une figurine dessus, trois voisins hex."""
    from engine.combat_utils import calculate_hex_distance

    cols = [c for c, _ in _CENTROID_SQUAD]
    rows = [r for _, r in _CENTROID_SQUAD]
    assert sum(cols) / 4.0 == 30.0 and sum(rows) / 4.0 == 20.0, "centroide non entier"
    for col, row in _CENTROID_SQUAD[1:]:
        assert calculate_hex_distance(30, 20, col, row) == 1, (
            f"({col},{row}) doit etre un VOISIN hexagonal de (30,20)"
        )
    offset_norms = {math.hypot(c - 30, r - 20) for c, r in _CENTROID_SQUAD[1:]}
    assert len(offset_norms) > 1, (
        "fixture inutile : en offset les trois voisins doivent avoir des normes DIFFERENTES"
    )


# ---------------------------------------------------------------------------
# T-H — bit de présence explicite
# ---------------------------------------------------------------------------


def test_model_on_centroid_is_present():
    """La figurine du centroïde, sans aucun drapeau, est marquée PRÉSENTE.

    Avant le bit `present`, sa ligne était entièrement nulle et l'extracteur la comptait absente.
    """
    eng = _make_engine([_unit_cfg(1, 1, _CENTROID_SQUAD), _unit_cfg(2, 2, [(90, 20)])])
    obs = _obs(eng)
    sm_cont, sm_bin = obs["self_models_cont"], obs["self_models_bin"]

    on_centroid = [
        k for k in range(len(sm_cont))
        if sm_cont[k][SM_COL] == 0.0 and sm_cont[k][SM_ROW] == 0.0
        and sm_bin[k][SM_PRESENT] == 1.0
    ]
    assert len(on_centroid) == 1, "la fixture doit poser UNE figurine sur le centroide"
    k = on_centroid[0]
    assert (
        sm_bin[k][SM_FIGHT] == 0.0
        and sm_bin[k][SM_IN_EZ] == 0.0
        and sm_bin[k][SM_RELAYED] == 0.0
    ), "fixture invalide : cette figurine doit n'avoir AUCUN drapeau (cas pathologique T-H)"
    assert float(sm_cont[k].sum()) == 0.0, "fixture invalide : ses continues doivent etre nulles"


def test_presence_bit_counts_exactly_the_alive_models():
    """La somme des bits `present` vaut l'effectif vivant observé, avant comme après une perte."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _make_engine([_unit_cfg(1, 1, _CENTROID_SQUAD), _unit_cfg(2, 2, [(90, 20)])])
    assert float(_obs(eng)["self_models_bin"][:, SM_PRESENT].sum()) == 4.0

    destroy_model(eng.game_state, "1#0", reason="combat")
    assert float(_obs(eng)["self_models_bin"][:, SM_PRESENT].sum()) == 3.0


def test_padding_rows_are_absent():
    """Les slots au-delà de l'effectif restent à zéro, bit `present` compris."""
    eng = _make_engine([_unit_cfg(1, 1, [(30, 20)]), _unit_cfg(2, 2, [(90, 20)])])
    sm_bin = _obs(eng)["self_models_bin"]
    assert float(sm_bin[0][SM_PRESENT]) == 1.0
    assert float(sm_bin[1:, SM_PRESENT].sum()) == 0.0


# ---------------------------------------------------------------------------
# T-I — une seule géométrie : la projection `_hex_center`
# ---------------------------------------------------------------------------


def test_self_model_positions_are_projected_isotropically():
    """Trois voisins hexagonaux du centroïde ont la MÊME norme, malgré des offsets différents."""
    eng = _make_engine([_unit_cfg(1, 1, _CENTROID_SQUAD), _unit_cfg(2, 2, [(90, 20)])])
    obs = _obs(eng)
    sm_cont, sm_bin = obs["self_models_cont"], obs["self_models_bin"]

    norms = sorted(
        math.hypot(float(sm_cont[k][SM_COL]), float(sm_cont[k][SM_ROW]))
        for k in range(len(sm_cont))
        if sm_bin[k][SM_PRESENT] == 1.0
    )
    assert norms[0] == pytest.approx(0.0), "la figurine du centroide doit etre a distance nulle"
    for norm in norms[1:]:
        assert norm == pytest.approx(_HEX_STEP, abs=1e-5), (
            f"norme {norm} : deux voisins hexagonaux doivent etre a la MEME distance "
            f"({_HEX_STEP}), sinon la geometrie est anisotrope (offset brut)"
        )


def test_self_model_positions_match_the_hex_center_oracle():
    """Oracle indépendant : chaque ligne vaut `_hex_center(fig) − _hex_center(centroïde arrondi)`."""
    eng = _make_engine([_unit_cfg(1, 1, _CENTROID_SQUAD), _unit_cfg(2, 2, [(90, 20)])])
    obs = _obs(eng)
    sm_cont, sm_bin = obs["self_models_cont"], obs["self_models_bin"]
    ax, ay = _hex_center(30, 20)
    expected = sorted(
        (round(_hex_center(c, r)[0] - ax, 5), round(_hex_center(c, r)[1] - ay, 5))
        for c, r in _CENTROID_SQUAD
    )
    got = sorted(
        (round(float(sm_cont[k][SM_COL]), 5), round(float(sm_cont[k][SM_ROW]), 5))
        for k in range(len(sm_cont))
        if sm_bin[k][SM_PRESENT] == 1.0
    )
    assert got == expected


def test_entity_positions_are_projected_isotropically():
    """Même exigence sur le bloc d'unités : deux ennemis voisins de moi, même norme."""
    norms = []
    for enemy_hex in ((30, 19), (29, 19)):
        eng = _make_engine([_unit_cfg(1, 1, [(30, 20)]), _unit_cfg(2, 2, [enemy_hex])])
        slot = _obs(eng)["enemies_cont"][0]
        norms.append(math.hypot(float(slot[E_COL]), float(slot[E_ROW])))
    assert norms[0] == pytest.approx(norms[1], abs=1e-5), (
        f"anisotropie de parite : {norms} — deux voisins hexagonaux doivent avoir la meme norme"
    )
    assert norms[0] == pytest.approx(_HEX_STEP, abs=1e-5)


def test_entity_position_matches_the_hex_center_oracle():
    """Oracle : la position d'entité est la projection de la figurine la plus proche."""
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)]), _unit_cfg(2, 2, [(100, 20), (26, 21)])])
    slot = _obs(eng)["enemies_cont"][0]
    ax, ay = _hex_center(20, 20)
    ex, ey = _hex_center(26, 21)
    assert float(slot[E_COL]) == pytest.approx(ex - ax, abs=1e-5)
    assert float(slot[E_ROW]) == pytest.approx(ey - ay, abs=1e-5)


# ---------------------------------------------------------------------------
# T-J — `phase` en one-hot, sans repli
# ---------------------------------------------------------------------------


def test_phase_is_a_one_hot_of_six_bits():
    """Chaque phase allume UN bit, le sien — et déploiement ≠ commande."""
    eng = _make_engine([_unit_cfg(1, 1, [(30, 20)]), _unit_cfg(2, 2, [(90, 20)])])
    vectors = {}
    for phase in OBS_PHASE_IDS:
        eng.game_state["phase"] = phase
        g_bin = _obs(eng)["global_bin"]
        bits = [float(g_bin[global_bin_index(f"phase_{p}")]) for p in OBS_PHASE_IDS]
        assert sum(bits) == 1.0, f"{phase} : {bits} n'est pas un one-hot"
        assert bits[OBS_PHASE_IDS.index(phase)] == 1.0, f"{phase} : mauvais bit allume"
        vectors[phase] = tuple(bits)

    assert vectors["deployment"] != vectors["command"], (
        "deploiement et commande DOIVENT etre distinguables (les ids d'action 4-8 n'y "
        "signifient pas la meme chose)"
    )
    assert len(set(vectors.values())) == len(OBS_PHASE_IDS), "deux phases partagent un encodage"


def test_unknown_phase_raises():
    """Aucun repli : une phase absente du schéma lève au lieu de sortir un vecteur nul."""
    eng = _make_engine([_unit_cfg(1, 1, [(30, 20)]), _unit_cfg(2, 2, [(90, 20)])])
    eng.game_state["phase"] = "shooting"  # nom du LOG, pas une phase du moteur
    with pytest.raises(ValueError, match="phase"):
        _obs(eng)


def test_missing_phase_raises():
    """La clé `phase` est requise (elle était lue avec un défaut « command »)."""
    from shared.data_validation import ConfigurationError

    eng = _make_engine([_unit_cfg(1, 1, [(30, 20)]), _unit_cfg(2, 2, [(90, 20)])])
    del eng.game_state["phase"]
    with pytest.raises((ConfigurationError, KeyError)):
        _obs(eng)


def test_phase_ids_match_the_engine_phase_order():
    """Contrat : l'ordre du one-hot est celui de `action_decoder.GAME_PHASES`."""
    from engine.action_decoder import GAME_PHASES

    assert list(OBS_PHASE_IDS) == list(GAME_PHASES)


def test_missing_model_count_at_start_raises():
    """Aucun repli sur l'effectif de depart (§0.32 T-J, residu ferme le 2026-07-28).

    `.get(..., len(alive_mids))` rendait un `model_count_ratio` de 1.0 — « escouade intacte » —
    sur une escouade decimee : une valeur FAUSSE servie au reseau, sans rien lever.
    """
    from shared.data_validation import ConfigurationError

    eng = _make_engine([_unit_cfg(1, 1, [(30, 20), (30, 21)]), _unit_cfg(2, 2, [(90, 20)])])
    del eng.game_state["squad_cache"]["1"]["model_count_at_start"]
    with pytest.raises(ConfigurationError, match="model_count_at_start"):
        _obs(eng)


def test_zero_model_count_at_start_raises():
    """`max(1, ...)` transformait un 0 de cache en `model_count_ratio` > 1."""
    eng = _make_engine([_unit_cfg(1, 1, [(30, 20), (30, 21)]), _unit_cfg(2, 2, [(90, 20)])])
    eng.game_state["squad_cache"]["1"]["model_count_at_start"] = 0
    with pytest.raises(ValueError, match="model_count_at_start"):
        _obs(eng)
