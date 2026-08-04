"""Socle d'invariants d'état de tour pour les ``game_state`` littéraux des tests.

POURQUOI CE FICHIER
-------------------
Le moteur pose **toujours** les clés ci-dessous (dict de reset de ``W40KEngine.reset()`` dans
``engine/w40k_core.py``, plus ``units_fought`` et le CP de 08.02 posés par ``command_phase_start``,
que la cascade command du reset appelle aussitôt). Un ``game_state`` littéral qui les omet décrit un
état **impossible en production**, et la production le lit de deux façons :

- ``require_key(...)`` / ``gs["..."]`` → le test casse bruyamment (cas ``units_advanced`` / 10.05) ;
- ``.get("...", <défaut>)`` → le test observe un comportement faux et reste **vert**.

C'est le second cas qui rend l'omission dangereuse. La fixture s'aligne donc sur le moteur, et
**jamais l'inverse** : assouplir une lecture de production en ``.get`` pour faire passer un test
est interdit — c'est ce qui aurait désactivé 10.05 en silence.

⚠️ Le dict d'``__init__`` n'est PAS la référence : il omet ``units_advanced``, ``advance_rolls``,
``units_took_to_skies`` et ``units_took_to_skies_charge``. Seul le dict de ``reset()`` est complet,
et tout chemin de production passe par ``engine.reset()``. La conformité de ce socle avec ce dict
est verrouillée par ``tests/unit/engine/test_engine_reset.py`` (classe
``TestTurnStateInvariantsConformity``) : le dict ci-dessous est **répliqué** à la main (une fixture
unitaire ne peut pas construire un engine complet), et ces tests rougissent si le moteur ajoute,
retire ou renomme un invariant. Ce dict est la seule source : rien ne recopie sa liste de clés.

USAGE
-----
Fusionner en tête du littéral, pour que les clés propres à la fixture gagnent :

    game_state = {
        **turn_state_invariants(),
        "phase": "shoot",
        "units_advanced": {"3"},   # écrase le set() vide du socle
        ...
    }
"""

from __future__ import annotations

from typing import Any, Dict


def turn_state_invariants() -> Dict[str, Any]:
    """Retourne les invariants d'état de tour, aux valeurs exactes d'un ``game_state`` post-reset.

    ``units_fought`` n'est pas dans le dict de ``reset()`` : c'est ``command_phase_start`` qui le
    pose, à chaque tour. Il est néanmoins présent dans tout ``game_state`` de production (la
    cascade command suit immédiatement le reset) et lu en ``require_key`` par la phase fight —
    il appartient donc au socle.

    Un dict neuf à chaque appel : les valeurs sont mutables et ne doivent jamais être
    partagées entre deux fixtures.
    """
    return {
        # Compteur de tour : present dans TOUT game_state de production (`reset()` le pose a 1).
        # Les emetteurs d'action_log le lisent en `require_key` depuis la suppression du repli
        # silencieux `game_state["current_turn"] ... else 1` — une cle qui n'a jamais existe et
        # qui datait toutes les lignes pile-in/consolidation de step.log au tour 1.
        "turn": 1,
        # Stock de CP des deux joueurs (regle 08.02), lu en `require_key` par
        # `gain_command_points` (cascade command) et par l'observation. `reset()` le pose a
        # `initial_command_points(config)` = 0, puis la cascade command du tour 1 accorde le CP
        # de 08.02 aux deux joueurs : la valeur post-reset est 1, comme pour `units_fought`.
        "command_points": {1: 1, 2: 1},
        "units_moved": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_shot": set(),
        "units_shot_previous_turn": set(),
        "units_charged": set(),
        "units_attacked": set(),
        "units_fought": set(),
        "units_advanced": set(),
        "advance_rolls": {},
        "units_took_to_skies": set(),
        "units_took_to_skies_charge": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
    }
