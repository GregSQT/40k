"""Root cause verrouillé pour les deux familles de conformité moteur §4 ROADMAP.

ROOT CAUSE (prouvée le 2026-08-17) : `update_units_cache_position` écrasait `occupied_hexes`
avec le seul footprint de la NOUVELLE ANCRE quand l'ancre d'une escouade multi-figurines était
détruite au combat. Cela laissait les figurines NON-ANCRES invisibles aux contrôles spatiaux.

Deux invariants cassés :

  - **03.01 Collision** : `build_occupied_positions_set` omet les hexes non-ancres → le pool de
    move d'une autre unité les autorise → deux unités finissent sur le même hex.

  - **09.05 Move PARTI d'un engagement** : `entry_footprint` (source de `_squad_is_in_enemy_er`
    et du chemin EZ 2D) ne voit que l'ancre → l'escouade paraît non-engagée → le masque offre
    `squad_normal_move` au lieu de `squad_fall_back`.

Fix appliqué le 2026-08-12 dans `update_units_cache_position` :
    pour les escouades multi-figurines, appel de `_recompute_squad_occupied_hexes` au lieu de
    recalculer le footprint de la seule ancre.
Mesuré avant fix : 7 collisions + 2 moves PARTI d'engagement sur le journal du 2026-08-11.
Mesuré après fix : 0 / 0.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.shared_utils import (
    _squad_is_in_enemy_er,
    build_occupied_positions_set,
    destroy_model,
)

# ---------------------------------------------------------------------------
# Scénario minimal
# ---------------------------------------------------------------------------
#
# Escouade "1" (P1) — 3 figurines :
#   1#0  à (3, 10) = ANCRE INITIALE  → sera détruite
#   1#1  à (4, 10) = nouvelle ancre après la mort de 1#0
#   1#2  à (8, 10) = figurine PROCHE de l'ennemi mais NON ANCRE
#
# Ennemi "2" (P2) à (9, 10) :
#   hex-distance à 1#1 = 5  > EZ 2  →  1#1 n'est PAS en zone d'engagement
#   hex-distance à 1#2 = 1 <= EZ 2  →  1#2 EST  en zone d'engagement
#
# Bug (ancienne version) : après `destroy_model("1#0")`, `update_units_cache_position`
# posait occupied_hexes = {(4,10)} (footprint de la nouvelle ancre seule) → 1#2 disparaissait
# des contrôles spatiaux.
# Fix : `_recompute_squad_occupied_hexes` reconstruit l'union {(4,10), (8,10)}.

SQUAD_ID = "1"
ENEMY_ID = "2"

ANCHOR_MID = "1#0"
ANCHOR_POS = (3, 10)
SURVIVOR_ANCHOR_MID = "1#1"
SURVIVOR_ANCHOR_POS = (4, 10)
REMOTE_MID = "1#2"
REMOTE_POS = (8, 10)  # adjacent à l'ennemi (dist 1 ≤ EZ 2) mais NON-ancre après la mort
ENEMY_POS = (9, 10)

EZ = 2  # engagement_zone DÉJÀ en sous-hexes (x1 : 2 subhex = 2")


def _gs() -> Dict[str, Any]:
    """Etat de jeu minimal : escouade P1 à 3 figurines + ennemi P2 mono-figurine."""
    return {
        "models_cache": {
            ANCHOR_MID: {
                "col": ANCHOR_POS[0], "row": ANCHOR_POS[1], "level": 0,
                "player": 1, "squad_id": SQUAD_ID, "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
            SURVIVOR_ANCHOR_MID: {
                "col": SURVIVOR_ANCHOR_POS[0], "row": SURVIVOR_ANCHOR_POS[1], "level": 0,
                "player": 1, "squad_id": SQUAD_ID, "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
            REMOTE_MID: {
                "col": REMOTE_POS[0], "row": REMOTE_POS[1], "level": 0,
                "player": 1, "squad_id": SQUAD_ID, "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
            "2#0": {
                "col": ENEMY_POS[0], "row": ENEMY_POS[1], "level": 0,
                "player": 2, "squad_id": ENEMY_ID, "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
        },
        "squad_models": {
            SQUAD_ID: [ANCHOR_MID, SURVIVOR_ANCHOR_MID, REMOTE_MID],
            ENEMY_ID: ["2#0"],
        },
        "units_cache": {
            SQUAD_ID: {
                "col": ANCHOR_POS[0], "row": ANCHOR_POS[1],
                "player": 1, "HP_CUR": 3,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                "occupied_hexes": {ANCHOR_POS, SURVIVOR_ANCHOR_POS, REMOTE_POS},
                # Pas de MODEL_HEIGHT → entry_has_vertical_data = False → chemin 2D hex
                # → occupied_hexes est la SEULE source de l'empreinte spatiale.
            },
            ENEMY_ID: {
                "col": ENEMY_POS[0], "row": ENEMY_POS[1],
                "player": 2, "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                "occupied_hexes": {ENEMY_POS},
            },
        },
        "config": {
            "game_rules": {
                "engagement_zone": EZ,
                "engagement_zone_vertical": 5.0,
                "max_base_size_hex": 6,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        # inches_to_subhex = 1  →  geometry_is_hex = True  →  métrique hex  →  1 fig = 1 case
        "inches_to_subhex": 1,
        "terrain_areas": [],
        "_unit_move_version": 0,
        # destroy_model émet un event "dead" via append_action_log → action_log_seq requis.
        "action_logs": [],
        "action_log_seq": 0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOccupiedHexesAfterAnchorDeath:
    """03.01 / 09.05 — invariant de base : occupied_hexes = union des survivants."""

    def test_occupied_hexes_is_union_after_anchor_death(self):
        """La correction preserve l'union ; l'ancienne version ne gardait que l'ancre."""
        gs = _gs()
        destroy_model(gs, ANCHOR_MID, "combat")

        entry = gs["units_cache"][SQUAD_ID]
        # Figurine non-ancre (8,10) doit rester dans l'union.
        assert REMOTE_POS in entry["occupied_hexes"], (
            f"Bug 03.01/09.05 actif : occupied_hexes = {entry['occupied_hexes']} "
            f"omet {REMOTE_POS} (1#2). Sans ce hex le pool move de l'ennemi et "
            f"_squad_is_in_enemy_er sont tous deux aveugles à cette figurine."
        )
        # Nouvelle ancre doit aussi être présente.
        assert SURVIVOR_ANCHOR_POS in entry["occupied_hexes"]
        # Ancre détruite ne doit plus être dans l'union.
        assert ANCHOR_POS not in entry["occupied_hexes"]

    def test_occupied_hexes_by_model_synchronized(self):
        """occupied_hexes_by_model est cohérent avec les survivants."""
        gs = _gs()
        destroy_model(gs, ANCHOR_MID, "combat")

        entry = gs["units_cache"][SQUAD_ID]
        by_model = entry.get("occupied_hexes_by_model", {})
        # Les deux survivants sont présents dans la carte par-figurine.
        assert SURVIVOR_ANCHOR_MID in by_model
        assert REMOTE_MID in by_model
        # La figurine détruite n'est plus dans la carte.
        assert ANCHOR_MID not in by_model
        # Chaque position par-figurine apparaît aussi dans occupied_hexes (cohérence croisée).
        occupied = entry["occupied_hexes"]
        for mid, pos in by_model.items():
            assert pos in occupied, (
                f"occupied_hexes_by_model[{mid!r}]={pos} absent de occupied_hexes={occupied}"
            )


class TestCollisionPrevention:
    """03.01 — build_occupied_positions_set doit inclure les hexes non-ancres."""

    def test_blocked_set_includes_nonanchor_positions(self):
        """Après la mort de l'ancre, les positions des non-ancres bloquent le pool ennemi."""
        gs = _gs()
        destroy_model(gs, ANCHOR_MID, "combat")

        blocked = build_occupied_positions_set(gs, exclude_unit_id=ENEMY_ID)

        assert REMOTE_POS in blocked, (
            f"Bug 03.01 : (8,10) absent de blocked={sorted(blocked)}. "
            f"L'ennemi pourrait y déplacer son unité → collision."
        )
        assert SURVIVOR_ANCHOR_POS in blocked

    def test_anchor_death_does_not_create_phantom_vacancy(self):
        """La mort de l'ancre ne libère pas son hex si d'autres figurines le couvrent."""
        gs = _gs()
        # Avant toute mort : tous les hexes initiaux sont bloqués.
        blocked_before = build_occupied_positions_set(gs, exclude_unit_id=ENEMY_ID)
        assert ANCHOR_POS in blocked_before

        destroy_model(gs, ANCHOR_MID, "combat")
        blocked_after = build_occupied_positions_set(gs, exclude_unit_id=ENEMY_ID)

        # L'ancre détruite quitte la map (plus de figurine là).
        assert ANCHOR_POS not in blocked_after
        # La figurine non-ancre reste bien présente.
        assert REMOTE_POS in blocked_after


class TestEngagementDetectionAfterAnchorDeath:
    """09.05 — _squad_is_in_enemy_er doit détecter l'engagement via les figurines non-ancres."""

    def test_squad_remains_engaged_after_anchor_death(self, monkeypatch):
        """Après mort de l'ancre, l'escouade est toujours engagée via 1#2 en (8,10)."""
        # Épingler la métrique hex : notre plateau x1 test utilise la métrique du
        # config global (euclidean à x5) ; on isole le test de cette dépendance.
        monkeypatch.setattr(
            "engine.spatial_relations.engagement_distance_metric",
            lambda *args, **kwargs: "hex",
        )
        gs = _gs()
        destroy_model(gs, ANCHOR_MID, "combat")

        # Avec le bug (occupied_hexes = {(4,10)}) :
        #   min_distance({(4,10)}, {(9,10)}) = 5 > 2 → NOT engaged → normal move autorisé (09.05)
        # Avec le fix (occupied_hexes = {(4,10),(8,10)}) :
        #   min_distance({(4,10),(8,10)}, {(9,10)}) = 1 ≤ 2 → engaged → fall back uniquement ✓
        assert _squad_is_in_enemy_er(gs, SQUAD_ID) is True, (
            "Bug 09.05 actif : l'escouade n'est pas détectée comme engagée alors que "
            f"1#2 en {REMOTE_POS} est à distance 1 de l'ennemi en {ENEMY_POS} (EZ={EZ})."
        )

    def test_squad_not_engaged_without_adjacent_models(self, monkeypatch):
        """Contre-épreuve : sans figurine à portée, l'escouade n'est PAS engagée."""
        monkeypatch.setattr(
            "engine.spatial_relations.engagement_distance_metric",
            lambda *args, **kwargs: "hex",
        )
        gs = _gs()
        # Détruire 1#0 ET 1#2 : seule 1#1 en (4,10) survit.
        # (4,10) est à dist 5 de (9,10) > EZ 2 → non engagée.
        destroy_model(gs, ANCHOR_MID, "combat")
        destroy_model(gs, REMOTE_MID, "combat")

        assert _squad_is_in_enemy_er(gs, SQUAD_ID) is False, (
            "Avec seulement 1#1 en (4,10), dist=5 > EZ=2 : l'escouade ne devrait PAS "
            "être détectée comme engagée."
        )
