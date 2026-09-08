"""Les zones d'engagement publiées sont IMMUABLES, et leur empreinte reste lue du CONTENU.

CE QUE CE FICHIER VERROUILLE. Le fingerprint de `_move_spatial_cache` est la garantie
anti-régression §0.18 des deux côtés de « masque ⊆ exécutable » : un compteur de version y avait
déjà servi un cache périmé, parce qu'un chemin d'écriture ne le bumpait pas. Il relit donc l'état.
Relire le CONTENU des deux ensembles `enemy_adjacent_hexes_player_*` coûtait 137 µs par appel
(7 942 hexes cumulés, 15,5 appels par step, mesuré le 2026-09-08 sur `scripts/bench_env_step.py`).

La correction ne remplace pas cette lecture par un jeton : elle PUBLIE ces ensembles en `frozenset`.
CPython calcule alors leur hash depuis leur contenu et le met en cache SUR L'OBJET, donc l'empreinte
reste dérivée du contenu tout en devenant gratuite à relire — et elle devient plus sûre que la
reconstruction, parce qu'un ensemble immuable ne peut pas changer de contenu sans devenir un autre
objet : aucun chemin d'écriture, présent ou futur, ne peut la rendre périmée.

Les quatre propriétés qui font que ce raisonnement tient, et qu'un test doit tenir à sa place :
  1. deux objets DIFFÉRENTS de même contenu donnent la même empreinte — sinon c'est un jeton
     d'identité déguisé, qui jetterait le cache à chaque republication à contenu constant ;
  2. un ensemble MUTABLE modifié en place jette quand même le cache — c'est la branche de repli,
     celle qui protège une save antérieure au gel et tout appelant qui poserait un `set` nu ;
  3. un contenu différent jette le cache — la propriété §0.18 elle-même ;
  4. TOUS les chemins de publication gèlent, y compris les deux chemins réactifs, que le bench
     n'exerce jamais (0 appel sur 80 steps) et que `test_reactive_move.py` ne couvre pas non plus
     puisqu'il pose lui-même ces clés en `set` nu.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shared_utils import (
    _move_spatial_cache,
    build_enemy_adjacent_hexes,
    build_units_cache,
    maybe_resolve_reactive_move,
    refresh_all_positional_caches_after_reactive_move,
    update_enemy_adjacent_caches_after_unit_move,
    update_enemy_adjacent_caches_after_unit_removed,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

EZ_KEYS = ("enemy_adjacent_hexes_player_1", "enemy_adjacent_hexes_player_2")


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": hp, "HP_MAX": hp, "VALUE": 100, "OC": 1,
        "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
        "MOVE": 6, "UNIT_RULES": [], "T": 4, "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
    }


def _unit_with_reactive(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    u = _unit(uid, player, col, row)
    u["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    return u


def _make_game_state(units: List[Dict[str, Any]], current_player: int = 1) -> Dict[str, Any]:
    """État minimal complet — le test construit son scénario, il ne dépend d'aucune graine."""
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "board_cols": 25, "board_rows": 21,
        "current_player": current_player, "phase": "move",
        "wall_hexes": set(), "terrain_areas": [],
        "units": units, "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [], "debug_logs": [], "action_logs": [], "action_log_seq": 0,
        "turn": 1, "_unit_move_version": 0,
        "reaction_window_active": False, "units_reacted_this_enemy_turn": set(),
        "last_move_event_id": 0, "reactive_mode": "micro", "reactive_decision_mode": "auto",
        "reactive_macro_order_current_window": [], "reactive_decision_payload": {},
        "last_move_cause": "normal",
        "move_activation_pool": [], "shoot_activation_pool": [], "charge_activation_pool": [],
        "units_moved": set(), "los_cache": {}, "hex_los_cache": {},
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


def _state_with_zones() -> Dict[str, Any]:
    """État dont les deux zones d'engagement sont publiées par le chemin de début de phase."""
    gs = _make_game_state([_unit(1, 1, 5, 10), _unit(2, 2, 12, 10)])
    for player in (1, 2):
        build_enemy_adjacent_hexes(gs, player)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# 1-3. L'empreinte est LUE DU CONTENU, jamais un jeton
# ─────────────────────────────────────────────────────────────────────────────

def test_two_distinct_objects_with_the_same_content_keep_the_cache():
    """Propriété 1 : l'empreinte suit le CONTENU, pas l'identité de l'objet.

    Si elle suivait l'identité — ou un compteur bumpé à chaque publication —, republier une zone
    inchangée (ce que fait `build_enemy_adjacent_hexes` à chaque début de phase) jetterait tout le
    cache spatial pour rien, et le poste que cette correction supprime reviendrait par la porte du
    recalcul. C'est aussi ce qui distingue cette solution du compteur de version interdit.
    """
    gs = _state_with_zones()
    holder_before = _move_spatial_cache(gs)

    for key in EZ_KEYS:
        assert isinstance(gs[key], frozenset), f"{key} doit être publiée immuable"
        # Objet DIFFÉRENT, contenu IDENTIQUE.
        rebuilt = frozenset(set(gs[key]))
        assert rebuilt is not gs[key]
        gs[key] = rebuilt

    assert _move_spatial_cache(gs) is holder_before, (
        "cache jeté alors que le contenu des zones est inchangé : l'empreinte suit l'objet, "
        "pas le contenu"
    )


def test_a_mutable_zone_mutated_in_place_still_throws_the_cache_away():
    """Propriété 2 : la branche de repli relit le contenu d'un ensemble MUTABLE.

    C'est elle qui rend la correction indépendante des chemins d'écriture : une save écrite avant
    le gel, ou un appelant qui poserait un `set` nu, garde le comportement d'avant — empreinte
    relue à chaque appel. Sans elle, la correction serait exactement le compteur de §0.18.
    """
    gs = _state_with_zones()
    gs["enemy_adjacent_hexes_player_1"] = set(gs["enemy_adjacent_hexes_player_1"])
    holder_before = _move_spatial_cache(gs)

    gs["enemy_adjacent_hexes_player_1"].add((0, 0))

    assert _move_spatial_cache(gs) is not holder_before, (
        "cache périmé servi après mutation en place d'une zone mutable — régression §0.18"
    )


def test_a_frozen_zone_replaced_by_a_different_content_throws_the_cache_away():
    """Propriété 3 : §0.18 elle-même — un contenu différent invalide le cache."""
    gs = _state_with_zones()
    holder_before = _move_spatial_cache(gs)

    gs["enemy_adjacent_hexes_player_1"] = frozenset(gs["enemy_adjacent_hexes_player_1"] | {(0, 0)})

    assert _move_spatial_cache(gs) is not holder_before, (
        "cache périmé servi après changement de contenu d'une zone — régression §0.18"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. TOUS les chemins de publication gèlent
# ─────────────────────────────────────────────────────────────────────────────

def test_phase_start_publishes_a_frozen_zone():
    gs = _make_game_state([_unit(1, 1, 5, 10), _unit(2, 2, 12, 10)])
    published = build_enemy_adjacent_hexes(gs, 1)

    assert published, "zone vide : le test ne regarderait rien"
    assert isinstance(published, frozenset)
    assert isinstance(gs["enemy_adjacent_hexes_player_1"], frozenset)


def test_unit_move_propagation_publishes_a_frozen_zone():
    gs = _state_with_zones()
    gs["units_cache"]["2"]["col"] = 11
    gs["units"][1]["col"] = 11

    update_enemy_adjacent_caches_after_unit_move(gs, 2, 12, 10, 11, 10)

    assert gs["enemy_adjacent_hexes_player_1"], "zone vide : le test ne regarderait rien"
    assert isinstance(gs["enemy_adjacent_hexes_player_1"], frozenset)


def test_unit_removal_propagation_publishes_a_frozen_zone():
    gs = _state_with_zones()
    gs["units_cache"].pop("2")

    update_enemy_adjacent_caches_after_unit_removed(gs, 2, 12, 10)

    assert isinstance(gs["enemy_adjacent_hexes_player_1"], frozenset)


def test_reactive_override_refresh_publishes_a_frozen_zone():
    """Chemin réactif 1/2 : republication depuis la structure de travail de la fenêtre.

    Cette structure, elle, RESTE mutable — `_apply_enemy_adjacent_delta_for_moved_unit` la modifie
    en place à chaque réaction appliquée. Seule la copie publiée est gelée.
    """
    gs = _state_with_zones()
    override_sets = {1: {(3, 3), (3, 4)}, 2: {(9, 9)}}
    override_counts = {1: {(3, 3): 1, (3, 4): 1}, 2: {(9, 9): 1}}

    refresh_all_positional_caches_after_reactive_move(
        gs,
        enemy_adjacent_sets_override=override_sets,
        enemy_adjacent_counts_override=override_counts,
    )

    for key, player in ((EZ_KEYS[0], 1), (EZ_KEYS[1], 2)):
        assert isinstance(gs[key], frozenset), f"{key} republiée mutable par le chemin réactif"
        assert set(gs[key]) == override_sets[player]
    assert override_sets[1] == {(3, 3), (3, 4)}, "la structure de travail ne doit pas être gelée"


def test_no_zone_is_ever_read_mutable_during_a_reaction_window(monkeypatch):
    """Chemin réactif 2/2 : l'instantané publié à L'OUVERTURE de la fenêtre est déjà gelé.

    Regarder l'état APRÈS la fenêtre ne verrouille pas ce site : la republication de sortie
    (`refresh_all_positional_caches_after_reactive_move`) écrase l'instantané d'ouverture, si bien
    qu'un instantané mutable laisse un état final gelé malgré tout — vérifié par mutation, le test
    d'état final restait VERT. On observe donc ce que le fingerprint LIT pendant la fenêtre.

    C'est aussi la formulation qui porte le gain : la propriété utile n'est pas « le type est bon
    à la fin », c'est « le fingerprint n'a jamais à reconstruire un frozenset ». Elle couvre du
    même coup tout futur site de publication.

    Ce chemin n'est exercé ni par `scripts/bench_env_step.py` (0 appel sur 80 steps) ni par
    `test_reactive_move.py`, qui pose lui-même ces clés en `set` nu.
    """
    import engine.phase_handlers.shared_utils as su

    seen: List[type] = []
    original = su._hex_set_content_hash

    def _recording(hexes):
        seen.append(type(hexes))
        return original(hexes)

    monkeypatch.setattr(su, "_hex_set_content_hash", _recording)

    gs = _make_game_state([_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)])
    monkeypatch.setattr("random.randint", lambda a, b: 3)

    result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")

    assert result["triggered"] is True, "fenêtre non déclenchée : le test ne regarderait rien"
    assert seen, "le fingerprint n'a lu aucune zone : le test ne regarderait rien"
    assert set(seen) == {frozenset}, (
        f"zone lue MUTABLE par le fingerprint pendant la fenêtre de réaction : {set(seen)}"
    )
    for key in EZ_KEYS:
        assert isinstance(gs[key], frozenset), f"{key} republiee mutable en sortie de fenetre"


def test_the_reactive_window_leaves_a_usable_move_cache():
    """Une zone gelée reste consommable par les lecteurs du cache spatial (pas de TypeError)."""
    gs = _state_with_zones()
    holder = _move_spatial_cache(gs)

    assert holder["fp"] is not None
    # Le contrat de lecture des zones : union, appartenance, différence — tous valides sur frozenset.
    zone = gs["enemy_adjacent_hexes_player_1"]
    assert (set() | zone) == set(zone)
    assert ((5, 10) in zone) in (True, False)
    assert not (zone - zone)
