"""Cache d'activation de objective_control_contributions dans _DoctrineBot.

Deux invariants :
1. Même activation (épisode, tour, phase, unité) → objective_control_contributions appelé une
   seule fois ; le résultat mis en cache est identique au résultat recalculé directement.
2. Unité différente sur la même instance → cache invalidé, nouveau calcul.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pytest

import ai.bot_doctrines as doc
from engine.game_state import objective_control_contributions, objective_hex_sets
from shared.data_validation import ConfigurationError

ZONE_A: Set[Tuple[int, int]] = {(1, 1)}
ZONE_B: Set[Tuple[int, int]] = {(6, 6)}
GRILLE = 12


def _uniforme(distance: int = 5) -> np.ndarray:
    return np.full((GRILLE, GRILLE), distance, dtype=np.int16)


def _state(
    figurines: List[Tuple[str, int, Tuple[int, int], int]],
    *,
    episode_number: int = 1,
    turn: int = 1,
    phase: str = "move",
) -> Dict[str, Any]:
    """État moteur minimal : `figurines` = [(id, joueur, (col, row), OC), …]."""
    units: List[Dict[str, Any]] = []
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, Any] = {}
    for squad_id, player, (col, row), oc in figurines:
        units.append({"id": squad_id, "player": player, "OC": oc, "battle_shocked": False, "UNIT_RULES": []})
        units_cache[squad_id] = {"player": player, "col": col, "row": row, "orientation": 0}
        model_id = f"{squad_id}#0"
        squad_models[squad_id] = [model_id]
        models_cache[model_id] = {
            "col": col, "row": row, "HP_CUR": 6, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        }
    return {
        "objectives": [
            {"id": nom, "hexes": [[col, row] for col, row in sorted(zone)]}
            for nom, zone in zip("AB", (ZONE_A, ZONE_B))
        ],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "episode_number": episode_number,
        "turn": turn,
        "phase": phase,
    }


class _CacheTestBot(doc._DoctrineBot):
    """Doctrine réduite : w_crowd = 1.0 pour exercer le chemin du cache, w_fire/w_risk = 0."""
    PLACEMENT_WEIGHTS: Dict[int, float] = {}

    def __init__(self) -> None:
        super().__init__()
        # (w_obj, w_enn, w_fire, w_risk, w_contest, w_crowd)
        self._poids = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

    def movement_weights(self, unit, game_state):
        return self._poids


def _patch_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cartes de distance uniformes : évite le calcul de plateau, seule la géométrie des zones compte."""
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: [_uniforme(), _uniforme()])


# ── Invariant 1 : même activation → 1 seul calcul, résultat identique ───────────────────────────


def test_cache_avoids_recompute_within_same_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Appeler select_movement_destination deux fois pour la même unité/tour/phase
    n'appelle objective_control_contributions qu'une fois, et la valeur en cache est identique
    au résultat direct."""
    _patch_maps(monkeypatch)

    call_count = 0
    real_occ = doc.objective_control_contributions

    def spy(game_state, zones):
        nonlocal call_count
        call_count += 1
        return real_occ(game_state, zones)

    monkeypatch.setattr(doc, "objective_control_contributions", spy)

    state = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)])
    unit = state["unit_by_id"]["2"]
    bot = _CacheTestBot()

    bot.select_movement_destination(unit, [(1, 1), (6, 6)], state)
    assert call_count == 1, "première activation : 1 appel"

    bot.select_movement_destination(unit, [(1, 1), (6, 6)], state)
    assert call_count == 1, "même activation : le cache absorbe le deuxième appel"

    # La valeur mise en cache est identique au résultat recalculé directement.
    cached = bot._contributions_cache_val
    assert cached is not None, "le cache doit avoir été rempli"
    zones = objective_hex_sets(state)
    direct = real_occ(state, zones)
    assert cached == direct, "résultat en cache ≠ résultat direct"


# ── Invariant 2 : unité différente → cache invalidé, nouveau calcul ─────────────────────────────


def test_cache_invalidated_on_different_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une activation sur l'unité 3 après l'unité 2 invalide le cache : deux appels au total."""
    _patch_maps(monkeypatch)

    call_count = 0
    real_occ = doc.objective_control_contributions

    def spy(game_state, zones):
        nonlocal call_count
        call_count += 1
        return real_occ(game_state, zones)

    monkeypatch.setattr(doc, "objective_control_contributions", spy)

    state = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1), ("3", 1, (5, 5), 1)])
    unit2 = state["unit_by_id"]["2"]
    unit3 = state["unit_by_id"]["3"]
    bot = _CacheTestBot()

    bot.select_movement_destination(unit2, [(1, 1), (6, 6)], state)
    assert call_count == 1, "activation de l'unité 2 : 1 appel"

    bot.select_movement_destination(unit3, [(1, 1), (6, 6)], state)
    assert call_count == 2, "activation de l'unité 3 : cache invalidé, 2e appel"


# ── Invariant 3 : épisode différent → cache invalidé, nouveau calcul ─────────────────────────────


def test_cache_invalidated_on_new_episode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Même unité, épisode suivant → clé différente, cache invalidé : deux appels au total."""
    _patch_maps(monkeypatch)

    call_count = 0
    real_occ = doc.objective_control_contributions

    def spy(game_state, zones):
        nonlocal call_count
        call_count += 1
        return real_occ(game_state, zones)

    monkeypatch.setattr(doc, "objective_control_contributions", spy)

    state1 = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)], episode_number=1)
    state2 = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)], episode_number=2)
    unit1 = state1["unit_by_id"]["2"]
    unit2 = state2["unit_by_id"]["2"]
    bot = _CacheTestBot()

    bot.select_movement_destination(unit1, [(1, 1), (6, 6)], state1)
    assert call_count == 1, "épisode 1 : 1 appel"

    bot.select_movement_destination(unit2, [(1, 1), (6, 6)], state2)
    assert call_count == 2, "épisode 2 : cache invalidé, 2e appel"


# ── Invariant 4 : require_key sur les champs de clé — état partiel lève une erreur ───────────────


def _state_without(
    figurines: List[Tuple[str, int, Tuple[int, int], int]],
    omit: str,
    *,
    episode_number: int = 1,
    turn: int = 1,
    phase: str = "move",
) -> Dict[str, Any]:
    """État complet moins la clé `omit` — pour tester la garde require_key."""
    s = _state(figurines, episode_number=episode_number, turn=turn, phase=phase)
    del s[omit]
    return s


@pytest.mark.parametrize("omit_key", ["episode_number", "turn", "phase"])
def test_missing_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch, omit_key: str
) -> None:
    """Un état sans episode_number/turn/phase lève ConfigurationError (require_key, pas .get)."""
    _patch_maps(monkeypatch)
    figurines = [("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)]
    state = _state_without(figurines, omit_key)
    unit = state["unit_by_id"]["2"]
    bot = _CacheTestBot()

    with pytest.raises(ConfigurationError):
        bot.select_movement_destination(unit, [(1, 1), (6, 6)], state)
