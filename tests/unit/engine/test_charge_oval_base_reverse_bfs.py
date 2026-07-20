"""R6 / T1 — socle OVALE (`BASE_SIZE` liste) dans le BFS inverse d'éligibilité de charge.

Contexte (V11 §0.19.1). Le fix R6 normalise `_mover_bs` en miroir du traitement ennemi
(`max(...)` si liste) dans **deux** sites de `charge_handlers` :

- `charge_build_valid_destinations_pool` (~L3629) ;
- `_charge_reverse_goal_bfs_for_eligibility` (~L826).

**Ce fichier couvre les DEUX**, et de façon déterministe. Le site n°2 est situé *avant*
l'embranchement vers le BFS inverse (~L3698) : tout appel à
`charge_build_valid_destinations_pool` le traverse. Vérifié par mutation isolée du seul L3629,
ce fichier seul (sans `test_t5_bare_loop.py`) : **3 rouges**.

⚠️ Auparavant le site n°2 n'était verrouillé que par `test_t5_bare_loop.py`, qui déroule des
épisodes **au hasard** — il tenait par chance de trajectoire, pas par construction (motif §0.11).

Le second n'était couvert par RIEN : il est désactivé dès `inches_to_subhex > 1`
([charge_handlers.py:3698](../../engine/phase_handlers/charge_handlers.py#L3698)) et le training
tourne en x5, donc aucun test passant par le moteur ne l'atteint. L'audit §0.19.1 l'a démontré en
remplaçant `max(_mover_bs)` par `int(_mover_bs)` — un `TypeError` inconditionnel sur une liste —
sans que la suite ne rougisse.

Le chemin reste VIF au x1 : `services/api_server.py` et `frontend/src/hooks/useGameConfig.ts`
exposent le board `25x21` (`inches_to_subhex: 1`) au PvP, et la training config ArmageddonAgent
porte une phase de curriculum x1. D'où un test plutôt qu'une suppression.

⚠️ Ce fichier n'a de valeur que s'il ATTEINT réellement le BFS inverse — c'est le motif §0.11
(« un test vert ne couvre que les états qu'il atteint »). La garde est
`test_reverse_bfs_is_actually_reached`, plus la contre-épreuve par mutation consignée en
§0.19.1.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers import charge_handlers
from engine.phase_handlers.charge_handlers import charge_build_valid_destinations_pool
from engine.phase_handlers.shared_utils import build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "charge": {"charge_max_distance": 12},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(
    uid: int,
    player: int,
    col: int,
    row: int,
    base_size: Any = 1,
    base_shape: str = "round",
) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 4,
        "HP_MAX": 4,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": base_size,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": base_shape,
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _make_game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_advanced": set(),
        "console_logs": [],
        "_unit_move_version": 0,
        # Board x1 (25x21) : c'est CE réglage qui active le BFS inverse.
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ── La garde : le BFS inverse est-il vraiment exercé ? ──────────────────────────

def test_reverse_bfs_is_actually_reached(monkeypatch):
    """Sans cette garde, les tests ci-dessous pourraient passer sans jamais entrer dans le site.

    Motif §0.11 : un test qui n'atteint pas la configuration visée ne prouve rien, et sa
    docstring peut affirmer le contraire de bonne foi.
    """
    calls: List[str] = []
    original = charge_handlers._charge_reverse_goal_bfs_for_eligibility

    def _spy(*args, **kwargs):
        calls.append("hit")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        charge_handlers, "_charge_reverse_goal_bfs_for_eligibility", _spy
    )

    units = [
        _unit(1, 1, 5, 10, base_size=[5, 3], base_shape="oval"),
        _unit(2, 2, 8, 10),
    ]
    gs = _make_game_state(units)
    charge_build_valid_destinations_pool(gs, "1", 12, early_exit_if_valid=True)

    assert calls, (
        "le BFS inverse n'a PAS été appelé — le test ne couvre pas le site R6 n°1 "
        "(vérifier inches_to_subhex, early_exit_if_valid, target_id=None, unité non-FLY)"
    )


# ── Le comportement R6 lui-même ────────────────────────────────────────────────

def test_oval_base_list_does_not_crash_reverse_bfs():
    """`BASE_SIZE` liste (socle ovale) traverse le BFS inverse sans `TypeError` (fix R6).

    Avant le fix, `int(_mover_bs)` sur une liste levait
    `TypeError: int() argument must be ... not 'list'`.
    """
    units = [
        _unit(1, 1, 5, 10, base_size=[41, 27], base_shape="oval"),  # Carnifex
        _unit(2, 2, 8, 10),
    ]
    gs = _make_game_state(units)
    result = charge_build_valid_destinations_pool(gs, "1", 12, early_exit_if_valid=True)
    assert isinstance(result, list)


def test_psychophage_oval_base_list_does_not_crash():
    """Second socle ovale du parc (Psychophage `[47, 36]`), exigé par §8.3."""
    units = [
        _unit(1, 1, 5, 10, base_size=[47, 36], base_shape="oval"),
        _unit(2, 2, 8, 10),
    ]
    gs = _make_game_state(units)
    result = charge_build_valid_destinations_pool(gs, "1", 12, early_exit_if_valid=True)
    assert isinstance(result, list)


def test_round_base_int_still_works():
    """Non-régression : socle rond `int` — le fix ne doit pas casser le cas nominal."""
    units = [_unit(1, 1, 5, 10, base_size=3), _unit(2, 2, 8, 10)]
    gs = _make_game_state(units)
    result = charge_build_valid_destinations_pool(gs, "1", 12, early_exit_if_valid=True)
    assert isinstance(result, list)
