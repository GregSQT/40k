"""Résolution BFS charge — _has_valid_charge_target, charge_build_valid_destinations_pool."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.charge_handlers import (
    _charge_bfs_max_distance,
    _has_valid_charge_target,
    charge_build_valid_destinations_pool,
    charge_model_plan_state,
)
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants


def _unit(uid: str, player: int, col: int, row: int) -> Dict[str, Any]:
    return {**unit_invariants(),
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
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _make_game_state(
    units: List[Dict[str, Any]],
    wall_hexes=None,
    charge_max: int = 12,
    board_cols: int = 40,
    board_rows: int = 30,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
            },
            "charge": {
                "charge_max_distance": charge_max,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": board_cols,
        "board_rows": board_rows,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": wall_hexes if wall_hexes is not None else set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_advanced": set(),
        "console_logs": [],
        "_unit_move_version": 0,
    }
    build_units_cache(gs)
    return gs


class TestChargeResolution:
    def test_target_in_charge_range_eligible(self):
        """charge_in_range : ennemi à hex-dist=10, charge_max=12 → cible valide."""
        # Charger en (5,10), ennemi en (15,10) — dist BFS ≈ 10 ≤ 12 → reachable
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10)]
        gs = _make_game_state(units)
        assert _has_valid_charge_target(gs, units[0]) is True

    def test_target_out_of_charge_range_not_eligible(self):
        """charge_out_of_range : ennemi à hex-dist=15, charge_max=12 → non éligible."""
        # Charger en (5,10), ennemi en (20,10) — dist BFS ≈ 15 > 12 → not reachable
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 20, 10)]
        gs = _make_game_state(units)
        assert _has_valid_charge_target(gs, units[0]) is False

    def test_wall_column_blocks_charge_path(self):
        """charge_wall_block : colonne de murs entre chargeur (5,10) et cible (10,10).

        Étape 5.3 — l'éligibilité 12" (11.02.1) dépend de la métrique :
        - euclidien (PvP, défaut) : pré-gate **ligne droite** → le mur NE bloque PAS l'éligibilité
          (il bloque le charge move post-jet, 11.04, pas la déclaration) ;
        - gym/hex : éligibilité via **BFS pathfinding** → le mur bloque le chemin (contournement
          au-delà de la portée de charge) → non éligible.
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 10, 10)]
        wall_col = {(7, r) for r in range(0, 21)}

        # Euclidien (PvP, défaut) : ligne droite, mur non bloquant pour l'éligibilité.
        assert _has_valid_charge_target(_make_game_state(units), units[0]) is True
        assert _has_valid_charge_target(
            _make_game_state(units, wall_hexes=wall_col), units[0]
        ) is True, "euclidien : éligibilité ligne droite, mur non bloquant"

        # Gym/hex : BFS pathfinding, mur complet bloque le chemin dans la portée de charge.
        gs_nw = _make_game_state(units); gs_nw["gym_training_mode"] = True
        gs_w = _make_game_state(units, wall_hexes=wall_col); gs_w["gym_training_mode"] = True
        assert _has_valid_charge_target(gs_nw, units[0]) is True, "gym/hex sans mur : éligible"
        assert _has_valid_charge_target(gs_w, units[0]) is False, "gym/hex mur complet : bloque la charge"

    def test_two_enemies_only_one_in_range(self):
        """charge_two_enemies : deux ennemis, seul celui à portée génère une destination valide.

        enemy2 en (15,10) → BFS reach (True).
        enemy3 en (25,10) → hors portée (False).
        _has_valid_charge_target retourne True (au moins un ennemi atteignable).
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10), _unit("3", 2, 25, 10)]
        gs = _make_game_state(units)

        # Vérification globale : au moins un ennemi atteignable
        assert _has_valid_charge_target(gs, units[0]) is True

        # Vérification par cible individuelle
        dest_to_2 = charge_build_valid_destinations_pool(gs, "1", 12, target_id="2")
        dest_to_3 = charge_build_valid_destinations_pool(gs, "1", 12, target_id="3")

        assert len(dest_to_2) > 0, "enemy2 à (15,10) doit être une cible atteignable"
        assert len(dest_to_3) == 0, "enemy3 à (25,10) doit être hors de portée"


class TestChargeBfsMaxDistanceCacheMiss:
    """Un miss d'``units_cache`` dans ``_charge_bfs_max_distance`` doit LEVER, pas rendre le jet nu.

    Avant correction, l'absence de l'unité ou d'une cible déclarée retombait sur ``return rid`` :
    la borne du BFS de charge était alors calculée sans le décalage ancre→empreinte, donc le pool
    de destinations était tronqué SANS aucun signal. C'est ce silence qui absorbait les mutations
    de test sur ce chemin (cf. campagne 2026-07-29 §3.6).
    """

    def test_nominal_returns_the_roll_and_does_not_raise(self):
        """Contrôle positif : sur un état sain, la borne est rendue et rien ne lève.

        Bases 1 hex → l'empreinte se réduit à l'ancre, donc ``extra`` vaut 0 et la borne == jet.
        Ce test existe pour qu'un « lève toujours » ne puisse pas faire passer les deux suivants.
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10)]
        gs = _make_game_state(units)
        assert gs["units_cache"]["1"]["occupied_hexes"] == {(5, 10)}, "prémisse : empreinte = ancre"

        assert _charge_bfs_max_distance(gs, "1", 7, target_id="2") == 7
        assert len(charge_build_valid_destinations_pool(gs, "1", 12, target_id="2")) > 0

    def test_attacker_missing_from_units_cache_raises(self):
        """``units`` porte le chargeur mais ``units_cache`` ne l'a plus → désynchronisation, ça lève."""
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10)]
        gs = _make_game_state(units)
        assert "1" in gs["units_cache"], "prémisse : le chargeur EST dans le cache avant retrait"
        del gs["units_cache"]["1"]

        with pytest.raises(KeyError, match="_charge_bfs_max_distance: unit 1 missing"):
            _charge_bfs_max_distance(gs, "1", 7, target_id="2")

    def test_declared_target_missing_from_units_cache_raises(self):
        """L'appelant a déjà validé la cible par ``is_unit_alive`` : un miss ici est une erreur d'état."""
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10)]
        gs = _make_game_state(units)
        assert "2" in gs["units_cache"], "prémisse : la cible EST dans le cache avant retrait"
        del gs["units_cache"]["2"]

        with pytest.raises(KeyError, match="_charge_bfs_max_distance: unit 2 missing"):
            _charge_bfs_max_distance(gs, "1", 7, target_ids=["2"])


class TestChargeUnitsCacheDesyncIsLoud:
    """Aucun chemin de charge ne doit dégrader en silence sur un miss d'``units_cache``.

    ``units_cache`` est le miroir de ``units`` : toute unité vivante y est. Les entrées de la
    charge valident déjà l'unité et les cibles (``get_unit_by_id`` + ``is_unit_alive``), et rien
    ne meurt pendant la phase de charge — un miss est donc une désynchronisation d'état, pas un
    cas de jeu. Chacun de ces chemins retombait auparavant sur une valeur crédible (pool tronqué,
    ancre de départ, cible absente des voiles UI) sans jamais crasher.
    """

    def _gs_with_targets(self):
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 15, 10)]
        gs = _make_game_state(units)
        gs["charge_target_selections"] = {"1": ["2"]}
        gs["charge_roll_values"] = {"1": 12}
        gs["inches_to_subhex"] = 1  # plateau x1 : 1 sous-hex = 1"
        return gs

    def test_pool_is_loud_on_missing_charger_thanks_to_the_upstream_guard(self):
        """⚠️ Ce test NE verrouille PAS le ``require_key`` de ``charge_build_valid_destinations_pool``.

        Mesuré par mutation : remettre le repli ``{start_pos}`` laisse ce test VERT, parce que
        ``require_unit_position`` (``shared_utils``) lève avant et que son message contient déjà
        « units_cache ». Ce qui est vérifié ici est donc le contrat de bout en bout — le pool est
        bruyant, jamais tronqué — **porté par la garde amont**, pas par la ligne de ce module.
        Le ``require_key`` local reste pour supprimer la branche morte et le ``Optional``.
        Conservé quand même : si la garde amont disparaît un jour, ce test tombera.
        """
        gs = self._gs_with_targets()
        assert "1" in gs["units_cache"], "prémisse : le chargeur EST dans le cache avant retrait"
        assert len(charge_build_valid_destinations_pool(gs, "1", 12, full_occupied_positions=set())) > 0, \
            "prémisse : sur l'état sain, ce chemin rend un pool non vide"
        del gs["units_cache"]["1"]

        with pytest.raises((KeyError, ValueError), match="units_cache"):
            charge_build_valid_destinations_pool(gs, "1", 12, full_occupied_positions=set())

    def test_plan_state_raises_on_missing_declared_target(self):
        """Une cible déclarée absente du cache disparaissait des voiles UI (ni satisfaite, ni pas)."""
        gs = self._gs_with_targets()
        assert "2" in gs["units_cache"], "prémisse : la cible EST dans le cache avant retrait"
        # Prémisse : sur l'état sain, la cible déclarée est bien classée par le plan.
        healthy = charge_model_plan_state(gs, "1", {})
        assert set(healthy["satisfied_targets"]) | set(healthy["unsatisfied_targets"]) == {"2"}

        del gs["units_cache"]["2"]
        gs["_charge_plan_state_cache"] = None  # la mémoïsation servirait le ctx sain
        with pytest.raises(KeyError, match="_compute_plan_context: unit 2 missing"):
            charge_model_plan_state(gs, "1", {})

    def test_preview_plan_raises_instead_of_reporting_a_desync_as_missing_target(self):
        """``missing_targets`` ne doit porter QUE des refus métier, pas une désynchronisation.

        ``charge_commit_move_plan_handler`` renvoie ce champ tel quel dans ``invalid_charge_plan``
        (l.5504) : y ranger une cible absente d'``units_cache`` faisait lire « cible non engagée »
        au joueur sur un état corrompu — le silence même que ce lot supprime ailleurs.
        """
        from engine.phase_handlers.charge_handlers import charge_preview_move_plan

        gs = self._gs_with_targets()
        mid = next(iter(gs["units_cache"]["1"]["occupied_hexes_by_model"]))
        plan = [(str(mid), 14, 10, 0)]  # adjacent à la cible en (15,10) → engagement réel

        # Prémisse : sur l'état sain, le plan engage la cible et `missing_targets` est vide.
        healthy = charge_preview_move_plan(gs, "1", plan, ["2"])
        assert healthy["engaged_all"] is True, healthy
        assert healthy["missing_targets"] == [], healthy

        del gs["units_cache"]["2"]
        with pytest.raises(KeyError, match="charge_preview_move_plan: unit 2 missing"):
            charge_preview_move_plan(gs, "1", plan, ["2"])
