"""§04.02 — cible engagée ne peut pas être ciblée par un tir normal (non CLOSE_QUARTERS).

Régression : le cache du pool utilisait enemy_pos_hash qui ne trackait que les ennemis.
Un allié qui pile-in adjacent à une cible après le premier build laissait le pool stale
→ la cible engagée restait dans le pool malgré §04.02.

Fix : remplacer enemy_pos_hash par _unit_move_version dans la clé de cache (incrémenté
sur TOUT mouvement, allié ou ennemi).
"""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.shooting_handlers import (
    shooting_build_valid_target_pool,
    _target_pool_cache,
)
from engine.phase_handlers.shared_utils import build_units_cache
import engine.spatial_relations as _sr
from tests._state_invariants import turn_state_invariants, unit_invariants


# EZ=1 hex + BASE_SIZE=1 + inches_to_subhex=1 (géométrie hex) :
# EZ compare min_distance_between_sets (hex steps, empreintes 1 hex) à engagement_zone=1.
# Unités adjacentes (distance 1) → IN EZ. Unités �� 2+ hexes → hors EZ.
_EZ = 1


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": _EZ,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            "detection_range": 18,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 2,
        "HP_MAX": 2,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "unitType": "infantry",
        "selectedRngWeaponIndex": 0,
        "selectedCcWeaponIndex": 0,
        "RNG_WEAPONS": [
            {
                "RNG": 24,
                "NB": 1,
                "ATK": 4,
                "STR": 4,
                "AP": 0,
                "DMG": 1,
                "WEAPON_RULES": [],
                "code": "shoota",
                "display_name": "Shoota",
                "shot": 0,
            }
        ],
        "CC_WEAPONS": [],
    }


def _make_game_state(units: List[Dict[str, Any]], current_player: int = 2) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": _board_config(),
        "board_cols": 30,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_fled": set(),
        "units_shot": set(),
        "shoot_activation_pool": [],
        "console_logs": [],
        "debug_logs": [],
        "hex_los_cache": {},
        "weapon_rule": {},
        "episode_number": 1,
        # Résolution hex (inches_to_subhex=1) : geometry_is_hex=True →
        # EZ et portée mesurées en hex steps. Déterministe, indépendant du config-loader global.
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


class TestEngagedTargetExcludedFromPool:
    """§04.02 : une cible engagée par un allié doit être exclue du pool de tir."""

    def test_engaged_target_excluded_after_friendly_moves_adjacent(self) -> None:
        """Cache stale par enemy_pos_hash : l'allié qui pile-in n'invalidait pas le pool.

        Scénario (géométrie hex, EZ=1 hex, socles 1 hex) :
        - Tireur 102 (p2) en (2, 5), arme RNG=24.
        - Cible 1 (p1) en (8, 5) — 6 hexes du tireur, hors EZ des deux alliés.
        - Allié 103 (p2) d'abord en (15, 5) — loin de la cible (hors EZ).
        Étape 1 : build pool → cible 1 doit être dans le pool (cache populé).
        Étape 2 : « mouvement » allié 103 → (9, 5) — adjacent à la cible (dans EZ=1).
                  bump _unit_move_version, purger _EZ_PAIR_CACHE.
                  NE PAS vider _target_pool_cache : c'est le cœur du test —
                  l'ancien code (enemy_pos_hash) génère la même clé → HIT stale,
                  le fix (_move_ver) génère une clé différente → MISS → rebuild frais.
        Étape 3 : rebuild pool → cible 1 DOIT être absente (§04.02 : cible engagée).
        """
        shooter_id = "102"
        target_id = "1"
        ally_id = "103"

        units = [
            _unit(102, 2, 2, 5),    # tireur p2 — loin du target (6 hexes), loin de l'allié
            _unit(1, 1, 8, 5),      # cible p1
            _unit(103, 2, 15, 5),   # allié p2, loin de la cible (7 hexes)
        ]
        gs = _make_game_state(units, current_player=2)

        # Vider les caches pour partir d'un état propre
        _target_pool_cache.clear()
        _sr._EZ_PAIR_CACHE.clear()

        # Étape 1 : build pool initial — allié loin, cible valide
        pool_before = shooting_build_valid_target_pool(gs, shooter_id)
        assert target_id in pool_before, (
            f"Cible {target_id} doit être dans le pool initial (allié loin) ; pool={pool_before}"
        )

        # Étape 2 : simuler le mouvement de l'allié adjacent à la cible
        uc = gs["units_cache"]
        uc[ally_id]["col"] = 9
        uc[ally_id]["row"] = 5
        uc[ally_id]["occupied_hexes"] = {(9, 5)}
        # occupied_hexes_by_model contient les positions par-figurine (chemin 3D EZ)
        _model_keys = list(uc[ally_id].get("occupied_hexes_by_model", {}).keys())
        if _model_keys:
            uc[ally_id]["occupied_hexes_by_model"] = {_model_keys[0]: (9, 5)}
        # Mettre à jour models_cache si présent
        _ally_models = gs.get("squad_models", {}).get(ally_id, [])
        for _mid in _ally_models:
            if _mid in gs.get("models_cache", {}):
                gs["models_cache"][_mid]["col"] = 9
                gs["models_cache"][_mid]["row"] = 5
        uc[ally_id].pop("_ez_fp", None)  # purge empreinte mémoïsée (cf. _engagement_entry_fingerprint)
        # Invalider le cache de versions (toute unité bougée)
        gs["_unit_move_version"] = gs["_unit_move_version"] + 1
        # NE PAS vider _target_pool_cache : c'est le cœur du test.
        # Ancien code (enemy_pos_hash) → même clé → cache HIT → pool stale ['1'] → ROUGE
        # Fix (_move_ver) → clé différente → cache MISS → rebuild frais → '1' absent → VERT
        _sr._EZ_PAIR_CACHE.clear()  # nécessaire pour que l'EZ recalculée soit fraîche

        # Étape 3 : rebuild pool — allié adjacent → cible engagée → §04.02
        pool_after = shooting_build_valid_target_pool(gs, shooter_id)
        assert target_id not in pool_after, (
            f"Cible {target_id} doit être ABSENTE du pool après que l'allié soit adjacent "
            f"(§04.02 : cible engagée) ; pool={pool_after}"
        )

    def test_unengaged_target_remains_in_pool(self) -> None:
        """Contrôle négatif : cible non engagée reste dans le pool après mouvement d'allié lointain."""
        shooter_id = "102"
        target_id = "1"
        ally_id = "103"

        units = [
            _unit(102, 2, 2, 5),
            _unit(1, 1, 8, 5),
            _unit(103, 2, 15, 5),
        ]
        gs = _make_game_state(units, current_player=2)

        _target_pool_cache.clear()
        _sr._EZ_PAIR_CACHE.clear()

        pool_before = shooting_build_valid_target_pool(gs, shooter_id)
        assert target_id in pool_before, (
            f"Pool initial vide, test vacant ; pool={pool_before}"
        )

        # Allié se déplace encore plus loin — toujours hors EZ de la cible
        uc = gs["units_cache"]
        uc[ally_id]["col"] = 25
        uc[ally_id]["row"] = 5
        uc[ally_id]["occupied_hexes"] = {(25, 5)}
        _model_keys2 = list(uc[ally_id].get("occupied_hexes_by_model", {}).keys())
        if _model_keys2:
            uc[ally_id]["occupied_hexes_by_model"] = {_model_keys2[0]: (25, 5)}
        uc[ally_id].pop("_ez_fp", None)
        gs["_unit_move_version"] = gs["_unit_move_version"] + 1
        _sr._EZ_PAIR_CACHE.clear()
        _target_pool_cache.clear()
        gs["unit_by_id"][shooter_id].pop("_precheck_cache", None)

        pool_after = shooting_build_valid_target_pool(gs, shooter_id)
        assert target_id in pool_after, (
            f"Cible {target_id} doit rester dans le pool (allié non adjacent) ; pool={pool_after}"
        )
