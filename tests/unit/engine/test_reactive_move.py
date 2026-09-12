"""Mouvement réactif — maybe_resolve_reactive_move déclenchement/non-déclenchement."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.agent_decision import consume_pending_agent_decision, read_pending_agent_decision
from engine.phase_handlers.shared_utils import (
    PENDING_REACTIVE_MOVE_KEY,
    _select_reactive_unit_order,
    build_units_cache,
    drive_reactive_move_window,
    maybe_resolve_reactive_move,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


def _pending_decision(gs: Dict[str, Any]) -> Dict[str, Any]:
    """La décision en attente, EXIGÉE : `read_pending_agent_decision` rend None sans décision."""
    decision = read_pending_agent_decision(gs)
    assert decision is not None, "aucune décision agent en attente"
    return decision


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": 100,
        "OC": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
    }


def _unit_with_reactive(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    u = _unit(uid, player, col, row)
    u["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    return u


def _make_game_state(units: List[Dict[str, Any]], current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
                           "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean",
                           "squad_min_neighbors": 1},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            # Requis par `validate_move_plan` : le pool réactif valide désormais le PLAN
            # RIGIDE de chaque destination, pas seulement la case d'ancre.
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        # Donnée de BOARD, au même titre que `wall_hexes` : le moteur la pose TOUJOURS
        # (`W40KEngine.reset`, `terrain_areas or []`), donc un `game_state` qui l'omet décrit un
        # état impossible en production. Vide = plateau sans terrain, ce que ces tests veulent.
        "terrain_areas": [],
        # Même statut que `terrain_areas` : le moteur pose TOUJOURS `objectives`, donc un
        # game_state qui l'omet décrit un état impossible en production. Vide = plateau sans
        # objectif, ce qui retire simplement l'intention « Objectif » des candidats réactifs.
        "objectives": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "_unit_move_version": 0,
        # Reactive move required fields
        "reaction_window_active": False,
        "units_reacted_this_enemy_turn": set(),
        "last_move_event_id": 0,
        "reactive_mode": "micro",
        "reactive_decision_mode": "auto",
        "reactive_macro_order_current_window": [],
        "reactive_decision_payload": {},
        "last_move_cause": "normal",
        # Phase pools
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "units_moved": set(),
        "los_cache": {},
        "hex_los_cache": {},
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Non-déclenchement
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveNoTrigger:

    def test_move_cause_reactive_returns_not_triggered(self):
        """reactive_cause : move_cause='reactive_move' → retour immédiat, triggered=False."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 6, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "reactive_move")
        assert result["triggered"] is False
        assert result["reactive_moves_applied"] == 0
        assert result["reactive_moves_declined"] == 0

    def test_no_reactive_rule_no_trigger(self):
        """reactive_norule : aucune unité avec la règle reactive_move → triggered=False."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]  # pas de règle reactive_move
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_unit_too_far_no_trigger(self):
        """reactive_toofar : unité éligible à plus de 9 hexes → triggered=False."""
        # unit 1 (player=1) moves to (5,10); unit 2 (player=2) is at (20,10) > 9 hexes away
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 20, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_same_player_no_trigger(self):
        """reactive_sameplayer : unité réactive du même joueur → non éligible → triggered=False."""
        # unit 1 (player=1) moves; unit 2 (player=1, same side) has reactive_move
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 1, 7, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_unit_within_engagement_range_no_trigger(self, monkeypatch):
        """reactive_engaged : porteur DÉJÀ au contact d'un ennemi → non éligible → triggered=False.

        Datasheet : « ... if this unit is not within Engagement Range of one or more enemy units,
        it can make a Normal move of up to D6" ». Le pool BFS n'écarte que les cases d'ARRIVÉE
        adjacentes à un ennemi : sans porte sur la position de DÉPART, le porteur quittait le
        corps à corps par un mouvement gratuit, sans les contraintes du Fall Back.
        """
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        # 3 (joueur 1) colle le porteur 2 (joueur 2) ; 1 (joueur 1) bouge à 2 hexes de lui.
        units = [_unit(1, 1, 4, 10), _unit_with_reactive(2, 2, 6, 10), _unit(3, 1, 7, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 3, 10, 4, 10, "move", "normal")
        assert result["triggered"] is False
        assert (units[1]["col"], units[1]["row"]) == (6, 10)

    def test_unit_out_of_engagement_range_still_triggers(self, monkeypatch):
        """Contrôle du test précédent : SEUL l'engagement change le verdict.

        Même scène, l'ennemi statique reculé hors zone d'engagement → le porteur redevient
        éligible. Sans ce contrôle, le `triggered=False` ci-dessus pourrait venir de la scène
        elle-même plutôt que de la porte, et resterait vert si la porte devenait inerte.
        """
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        units = [_unit(1, 1, 4, 10), _unit_with_reactive(2, 2, 6, 10), _unit(3, 1, 10, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 3, 10, 4, 10, "move", "normal")
        assert result["triggered"] is True
        assert result["reactive_moves_applied"] == 1

    def test_reentrance_raises_runtime_error(self):
        """reactive_reentrant : reaction_window_active=True → RuntimeError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["reaction_window_active"] = True
        with pytest.raises(RuntimeError, match="reentrance"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")


# ─────────────────────────────────────────────────────────────────────────────
# Déclenchement — unité éligible dans la zone
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveTriggered:

    def test_eligible_unit_moves_and_cache_updated(self, monkeypatch):
        """reactive_triggered : unité éligible dans la zone → triggered=True, cache mis à jour."""
        # unit 1 (player=1) moves from (4,10) to (5,10)
        # unit 2 (player=2, has reactive_move) is at (7,10) — 2 hexes from (5,10)
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)

        # D6 roll for reactive move range → 3 (resolve_dice_value uses random.randint)
        monkeypatch.setattr("random.randint", lambda a, b: 3)

        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is True
        assert result["reactive_moves_applied"] == 1
        assert result["reactive_moves_declined"] == 0

    def test_reactive_unit_position_updated_in_cache(self, monkeypatch):
        """reactive_cache : après déclenchement, units_cache reflète la nouvelle position."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        orig_pos = (gs["units_cache"]["2"]["col"], gs["units_cache"]["2"]["row"])

        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")

        new_pos = (gs["units_cache"]["2"]["col"], gs["units_cache"]["2"]["row"])
        # Unité a bougé — nouvelle position != ancienne
        assert new_pos != orig_pos

    def test_reaction_window_cleaned_up_after_trigger(self, monkeypatch):
        """reactive_cleanup : reaction_window_active remis à False après déclenchement."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert gs["reaction_window_active"] is False

    def test_reacted_unit_not_triggered_twice(self, monkeypatch):
        """reactive_onceperturn : unité déjà dans units_reacted_this_enemy_turn → non éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        gs["units_reacted_this_enemy_turn"] = {"2"}  # déjà réagi
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveEdgeCases:

    def test_move_cause_advance_triggers(self, monkeypatch):
        """reactive_advance : move_kind='advance' autorisé → triggered possible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "advance", "normal")
        assert result["triggered"] is True

    def test_move_cause_flee_triggers(self, monkeypatch):
        """reactive_flee : move_kind='flee' → triggered possible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "flee", "normal")
        assert result["triggered"] is True

    def test_invalid_move_kind_raises_value_error(self):
        """reactive_invalid_kind : move_kind invalide → ValueError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        with pytest.raises(ValueError, match="Unsupported move_kind"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "teleport", "normal")

    def test_invalid_move_cause_raises_value_error(self):
        """reactive_invalid_cause : move_cause invalide → ValueError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        with pytest.raises(ValueError, match="Unsupported move_cause"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "magic")

    def test_last_move_event_id_incremented(self, monkeypatch):
        """reactive_event_id : last_move_event_id incrémenté quand unité éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        gs["last_move_event_id"] = 5
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert gs["last_move_event_id"] == 6

    def test_action_log_entry_added_on_trigger(self, monkeypatch):
        """reactive_log_entry : déclenchement → entrée dans action_logs."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        initial_log_len = len(gs["action_logs"])
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert len(gs["action_logs"]) > initial_log_len

    def test_units_reacted_set_updated_on_trigger(self, monkeypatch):
        """reactive_reacted_set : unité réactive ajoutée à units_reacted_this_enemy_turn."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        assert "2" not in gs["units_reacted_this_enemy_turn"]
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert "2" in gs["units_reacted_this_enemy_turn"]

    def test_exactly_9_hexes_away_eligible(self, monkeypatch):
        """reactive_9hex_boundary : unité à exactement 9 hexes → éligible."""
        # Unité moved à (5,10), reactive unit à (14,10) = 9 hexes
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 14, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 5)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        # 9 hexes → eligible (distance <= 9)
        assert result["triggered"] is True

    def test_10_hexes_away_not_eligible(self, monkeypatch):
        """reactive_10hex_boundary : unité à 10 hexes → non éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 15, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 5)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_incoherent_formation_declined_with_log(self):
        """reactive_incoherent : escouade hors cohérence → declined + log reason=formation_incoherente.

        03.01 ENDING A MOVE : une unité qui ne peut pas finir en cohérence ne peut pas faire
        ce mouvement. L'escouade a 2 figurines séparées de 3 hexes (> cohesion_range=2) donc
        hors cohérence. Aucun D6 ne doit être lancé, aucun déplacement appliqué.
        """
        u_enemy = _unit(1, 1, 5, 10)
        u_reactive = _unit_with_reactive(2, 2, 7, 10)
        # 2 figurines : (7,10) et (10,10) → distance 3 hexes > cohesion_range 2 → incohérente.
        u_reactive["models"] = [
            {"col": 7, "row": 10, "HP_CUR": 1, "VALUE": 50},
            {"col": 10, "row": 10, "HP_CUR": 1, "VALUE": 50},
        ]
        gs = _make_game_state([u_enemy, u_reactive])

        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")

        assert result["reactive_moves_applied"] == 0
        assert result["reactive_moves_declined"] == 1
        assert result["triggered"] is True
        declined_logs = [
            e for e in gs["action_logs"]
            if e.get("type") == "reactive_move_declined" and e.get("reason") == "formation_incoherente"
        ]
        assert len(declined_logs) == 1
        assert declined_logs[0]["unitId"] == "2"


# ─────────────────────────────────────────────────────────────────────────────
# Ordre d'activation de la fenêtre de réaction — mode macro
# ─────────────────────────────────────────────────────────────────────────────

class TestSelectReactiveUnitOrder:
    """``reactive_mode="macro"`` : branche entière jamais exercée jusqu'ici.

    En micro l'ordre est le tri par id ; en macro il vient de
    ``reactive_macro_order_current_window``. Cette clé est absente des fixtures littérales et
    n'était peuplée nulle part : un ordre macro ignoré aurait activé les unités dans le mauvais
    ordre sans qu'aucun test ne bouge. Les tests ci-dessous distinguent les deux modes en
    choisissant un ordre macro **différent** du tri par id — sinon micro et macro seraient
    indiscernables.
    """

    def _eligible(self):
        return [_unit(1, 2, 5, 10), _unit(2, 2, 6, 10), _unit(3, 2, 7, 10)]

    def test_micro_orders_by_id(self):
        """reactive_order_micro : mode micro → tri par id, l'ordre macro est ignoré."""
        gs = _make_game_state(self._eligible())
        gs["reactive_macro_order_current_window"] = ["3", "1", "2"]

        ordered = _select_reactive_unit_order(gs, list(reversed(self._eligible())))

        assert [str(u["id"]) for u in ordered] == ["1", "2", "3"]

    def test_macro_follows_declared_order(self):
        """reactive_order_macro : mode macro → l'ordre déclaré prime sur le tri par id."""
        eligible = self._eligible()
        gs = _make_game_state(eligible)
        gs["reactive_mode"] = "macro"
        gs["reactive_macro_order_current_window"] = ["3", "1", "2"]

        ordered = _select_reactive_unit_order(gs, eligible)

        assert [str(u["id"]) for u in ordered] == ["3", "1", "2"]

    def test_macro_empty_order_raises(self):
        """reactive_order_macro_vide : en macro, un ordre vide est une erreur explicite.

        C'est la valeur du socle : elle ne doit surtout pas être prise pour « aucune contrainte ».
        """
        eligible = self._eligible()
        gs = _make_game_state(eligible)
        gs["reactive_mode"] = "macro"

        with pytest.raises(ValueError, match="macro order cannot be empty"):
            _select_reactive_unit_order(gs, eligible)

    def test_macro_order_unit_killed_mid_reaction_is_skipped(self):
        """reactive_order_macro_unite_morte : une unité tuée pendant la réaction est ignorée.

        Elle figure dans reactive_macro_order_current_window (fenêtre ouverte quand elle était
        vivante) mais plus dans eligible_units (recalculé après sa mort). La correction du
        CR-1 : silently skip au lieu de raise ValueError.
        """
        eligible = self._eligible()  # unités 1, 2, 3
        gs = _make_game_state(eligible)
        gs["reactive_mode"] = "macro"
        gs["reactive_macro_order_current_window"] = ["3", "2", "1"]

        # L'unité 2 vient de mourir : on la retire du pool eligible passé
        eligible_minus_2 = [u for u in eligible if u["id"] != 2]
        ordered = _select_reactive_unit_order(gs, eligible_minus_2)

        assert [str(u["id"]) for u in ordered] == ["3", "1"]

    def test_unknown_mode_raises(self):
        """reactive_order_mode_inconnu : un mode hors {micro, macro} est refusé."""
        eligible = self._eligible()
        gs = _make_game_state(eligible)
        gs["reactive_mode"] = "meso"

        with pytest.raises(ValueError, match="Unsupported reactive_mode"):
            _select_reactive_unit_order(gs, eligible)


class TestReactiveBudgetScale:
    """Le D6 de la capacité est en POUCES ; le BFS du pool compte des pas de GRILLE.

    Sans conversion, un « D6 pouces » plafonnait à 6 CASES — 1,2" à x5, 0,6" à x10 — alors que
    le budget de move, le jet d'advance et le jet de charge (`_charge_budget_subhex`) sont tous
    convertis. La capacité devenait quasi inopérante hors du board x1.
    """

    def _pool_radius(self, scale: int) -> int:
        from engine.phase_handlers.shared_utils import _build_reactive_move_destinations_pool
        from engine.hex_utils import hex_distance

        gs = _make_game_state([_unit_with_reactive(1, 1, 12, 10)])
        gs["inches_to_subhex"] = scale
        unit = gs["units"][0]
        col, row = unit["col"], unit["row"]
        # Le pool valide des PLANS : il lit les caches d'adjacence que la fenêtre de réaction
        # publie en production (`maybe_resolve_reactive_move`).
        for _p in (1, 2):
            gs[f"enemy_adjacent_hexes_player_{_p}"] = set()
            gs[f"enemy_adjacent_counts_player_{_p}"] = {}
        dests = _build_reactive_move_destinations_pool(
            gs, unit, 2, enemy_adjacent_hexes_override=set()
        )
        assert dests, "pool vide : le test ne regarderait rien"
        return max(hex_distance(col, row, c, r) for (c, r) in dests)

    def test_le_rayon_de_declenchement_suit_aussi_la_resolution(self):
        """JUMEAU du budget : les 9" de `reactive_move` (config/unit_rules.json) etaient
        compares a une distance de GRILLE. A x5 cela valait 1,8" — moins que la zone
        d'engagement : la capacite ne se declenchait quasiment plus hors du board x1."""
        from engine.phase_handlers.shared_utils import maybe_resolve_reactive_move

        def _triggers(scale: int, enemy_col: int) -> bool:
            gs = _make_game_state(
                [_unit_with_reactive(1, 1, 12, 10), _unit(2, 2, enemy_col, 10)]
            )
            gs["inches_to_subhex"] = scale
            res = maybe_resolve_reactive_move(
                gs, "2", enemy_col, 10, enemy_col, 10, "move", "normal"
            )
            return bool(res["triggered"])

        # Ennemi a 20 cases : hors des 9 CASES, mais dans les 9 POUCES des que x5 (45 cases).
        assert _triggers(1, 32) is False
        assert _triggers(5, 32) is True

    def test_le_budget_suit_la_resolution_du_board(self):
        r1 = self._pool_radius(1)
        r5 = self._pool_radius(5)

        assert r1 == 2, r1
        # 2" à x5 = 10 cases. Sans conversion, r5 vaudrait 2 comme à x1.
        assert r5 == 10, r5


class TestReactiveMoveDeplaceLesFigurines:
    """Un mouvement d'unité déplace TOUTES ses figurines (03.01).

    Le pool ne validait que la case d'ANCRE : translater le bloc y aurait écrit les figurines
    non-ancres sur des coordonnées jamais vérifiées (mur, empreinte d'une autre escouade, hors
    plateau), défaut amplifié ×5/×10 par la conversion du budget en subhex. Le pool retient
    désormais les seules destinations dont le PLAN RIGIDE est valide — c'est ce qui autorise la
    translation du bloc.
    """

    def test_le_pool_ne_retient_que_des_plans_valides(self):
        from engine.phase_handlers.shared_utils import (
            _build_reactive_move_destinations_pool,
            build_rigid_plan,
            validate_move_plan,
            DEFAULT_MOVE_CONSTRAINTS,
        )

        gs = _make_game_state([_unit_with_reactive(1, 1, 12, 10), _unit(2, 2, 20, 20)])
        for _p in (1, 2):
            gs[f"enemy_adjacent_hexes_player_{_p}"] = set()
            gs[f"enemy_adjacent_counts_player_{_p}"] = {}
        unit = gs["units"][0]

        dests = _build_reactive_move_destinations_pool(
            gs, unit, 2, enemy_adjacent_hexes_override=set()
        )

        assert dests, "pool vide : le test ne regarderait rien"
        constraints = {**DEFAULT_MOVE_CONSTRAINTS, "budget_per_model": 2}
        for dest in dests:
            plan = build_rigid_plan(int(dest[0]), int(dest[1]), "1", gs)
            assert plan is not None, dest
            assert validate_move_plan(plan, gs, constraints), dest

    def test_une_destination_dont_le_SECOND_socle_tombe_dans_un_mur_est_ecartee(self):
        """LE cas que la validation par plan attrape et que le BFS ne voit pas : la case
        d'ancre est libre, mais la figurine qui la suit atterrit dans un mur.

        Sans ce filtre, la translation rigide écrivait ce socle dans le mur.
        """
        from engine.phase_handlers.shared_utils import (
            _build_reactive_move_destinations_pool,
            build_rigid_plan,
        )

        def _gs(walls):
            gs = _make_game_state([_unit_with_reactive(1, 1, 12, 10)])
            gs["squad_models"]["1"] = ["1#0", "1#1"]
            # `orientation` : `build_models_cache` la pose sur TOUTE figurine, et le move la
            # lit en `require_key` (une absence = cache corrompu). Une fixture qui l'omet ne
            # decrit pas un etat que le moteur peut produire. MEME RAISON pour
            # `BASE_SHAPE`/`BASE_SIZE` (`_build_models_for_unit` les pose toujours) : depuis que
            # l'EZ du move se mesure sur le socle POSE, `explain_move_plan_rejection` les lit
            # pour chaque figurine du plan.
            gs["models_cache"] = {
                "1#0": {"id": "1#0", "squad_id": "1", "player": 1, "col": 12, "row": 10,
                        "level": 0, "HP_CUR": 1, "orientation": 0,
                        "BASE_SHAPE": "round", "BASE_SIZE": 1},
                "1#1": {"id": "1#1", "squad_id": "1", "player": 1, "col": 14, "row": 10,
                        "level": 0, "HP_CUR": 1, "orientation": 0,
                        "BASE_SHAPE": "round", "BASE_SIZE": 1},
            }
            gs["units_cache"]["1"]["occupied_hexes_by_model"] = {"1#0": (12, 10), "1#1": (14, 10)}
            gs["wall_hexes"] = set(walls)
            for _p in (1, 2):
                gs[f"enemy_adjacent_hexes_player_{_p}"] = set()
                gs[f"enemy_adjacent_counts_player_{_p}"] = {}
            return gs

        gs = _gs(set())
        sans_mur = _build_reactive_move_destinations_pool(
            gs, gs["units"][0], 2, enemy_adjacent_hexes_override=set()
        )
        assert sans_mur, "prémisse : il y avait bien des destinations"

        # On ne devine PAS la géométrie : la translation rigide s'applique en coordonnées cube
        # (un dx impair change la parité de colonne). On demande donc au moteur où atterrit le
        # SECOND socle, et c'est là qu'on pose le mur.
        cible = sans_mur[len(sans_mur) // 2]
        plan = build_rigid_plan(int(cible[0]), int(cible[1]), "1", gs)
        assert plan is not None, cible
        second = next(p for p in plan if p[0] == "1#1")
        case_du_second = (int(second[1]), int(second[2]))
        assert case_du_second != cible

        # État NEUF avec le mur : les ensembles spatiaux sont mémoïsés par état, muter
        # `wall_hexes` en place ne les invaliderait pas.
        gs_mur = _gs({case_du_second})
        avec_mur = _build_reactive_move_destinations_pool(
            gs_mur, gs_mur["units"][0], 2, enemy_adjacent_hexes_override=set()
        )

        # La case d'ancre reste libre : le BFS seul l'accepterait encore. Seule la validation
        # du plan la fait tomber.
        assert cible not in gs_mur["wall_hexes"]
        assert cible not in avec_mur, (
            "destination retenue alors que le second socle atterrit dans un mur"
        )


class TestReactivePoolCoherency:
    def test_une_escouade_hors_coherency_garde_ses_destinations(self):
        """Exiger la coherency dans le pool éteint la capacité en silence.

        La translation est RIGIDE : la formation, donc la coherency, est identique avant et
        après. La re-juger revient à exiger de la capacité qu'elle RÉPARE un état antérieur —
        une escouade sortie de coherency par une perte (résorbée seulement en fin de tour)
        verrait toutes ses destinations rejetées, pool vide, sans un log ni un `declined`.
        """
        from engine.phase_handlers.shared_utils import _build_reactive_move_destinations_pool

        gs = _make_game_state([_unit_with_reactive(1, 1, 12, 10)])
        gs["squad_models"]["1"] = ["1#0", "1#1"]
        # Deux socles très éloignés : hors coherency (`unit_model_cohesion_range` = 2).
        # `orientation` / `BASE_SHAPE` / `BASE_SIZE` : cf. le commentaire de la fixture jumelle
        # ci-dessus.
        gs["models_cache"] = {
            "1#0": {"id": "1#0", "squad_id": "1", "player": 1, "col": 12, "row": 10,
                    "level": 0, "HP_CUR": 1, "orientation": 0,
                    "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "1#1": {"id": "1#1", "squad_id": "1", "player": 1, "col": 20, "row": 10,
                    "level": 0, "HP_CUR": 1, "orientation": 0,
                    "BASE_SHAPE": "round", "BASE_SIZE": 1},
        }
        gs["units_cache"]["1"]["occupied_hexes_by_model"] = {"1#0": (12, 10), "1#1": (20, 10)}
        for _p in (1, 2):
            gs[f"enemy_adjacent_hexes_player_{_p}"] = set()
            gs[f"enemy_adjacent_counts_player_{_p}"] = {}

        dests = _build_reactive_move_destinations_pool(
            gs, gs["units"][0], 2, enemy_adjacent_hexes_override=set()
        )

        assert dests, "pool vide : la capacité est éteinte par un état antérieur au mouvement"


# ─────────────────────────────────────────────────────────────────────────────
# Mode `state` — le refus est rendu au joueur (datasheet : « it CAN make a Normal move »)
# ─────────────────────────────────────────────────────────────────────────────


def _suspended_window(monkeypatch, roll: int = 3):
    """Ouvre une fenêtre réactive en mode `state` et la laisse SUSPENDUE sur sa question.

    Rend `(gs, unite_reactive, resultat)`. L'unité 2 (joueur 2) porte la règle et réagit au
    mouvement de l'unité 1 (joueur 1), qui finit en (5,10) à 2 hexes d'elle.
    """
    monkeypatch.setattr("random.randint", lambda a, b: roll)
    units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
    gs = _make_game_state(units)
    gs["reactive_decision_mode"] = "state"
    result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
    return gs, units[1], result


class TestReactiveMoveStateDecision:

    def test_state_mode_poses_the_question_and_keeps_the_window_open(self, monkeypatch):
        """La capacité étant optionnelle, le moteur POSE la question au lieu de trancher."""
        gs, reactive, result = _suspended_window(monkeypatch)

        assert result["waiting_for_player"] is True
        assert result["reactive_moves_applied"] == 0
        # VERT VACANT : sans ces deux-là, un retour « en attente » pourrait accompagner une
        # fenêtre déjà refermée, et la reprise n'aurait plus rien à reprendre.
        assert gs["reaction_window_active"] is True
        assert gs[PENDING_REACTIVE_MOVE_KEY]["queue"] == ["2"]

        decision = read_pending_agent_decision(gs)
        assert decision is not None
        assert decision["type"] == "reactive_move"
        # La décision appartient au joueur qui RÉAGIT, pas à celui dont c'est le tour.
        assert int(decision["player"]) == 2
        assert int(decision["player"]) != int(gs["current_player"])
        assert str(decision["unit_id"]) == "2"
        # Tant que personne n'a répondu, l'unité n'a pas bougé.
        assert (reactive["col"], reactive["row"]) == (7, 10)

    def test_exactly_one_candidate_declines(self, monkeypatch):
        """`declines` est ce qui rend « ne pas réagir » discernable pour l'agent."""
        gs, _reactive, _result = _suspended_window(monkeypatch)
        options = _pending_decision(gs)["options"]

        declining = [option for option in options if option["declines"]]
        assert len(declining) == 1
        assert declining[0]["payload"]["action"] == "decline_reactive_move"
        # Un choix à candidat unique n'est pas un choix : les intentions doivent exister aussi.
        assert len(options) >= 2

    def test_le_premier_candidat_est_la_destination_de_pression(self, monkeypatch):
        """`CHOICE_0` DOIT rester la case la plus proche de l'ennemi déclencheur.

        Contrat dont dépend `ai/env_wrappers.bot_action_for_pending_choice` : le bot répond
        `CHOICE_0` pour retrouver EXACTEMENT l'ancienne heuristique déterministe
        (`_select_reactive_destination`). Si l'ordre des intentions changeait, l'adversaire de
        référence se mettrait à fuir ou à refuser, et deux runs ne mesureraient plus la même
        baseline — sans qu'aucun autre test ne le voie.
        """
        from engine.combat_utils import calculate_hex_distance

        gs, _reactive, _result = _suspended_window(monkeypatch)
        options = _pending_decision(gs)["options"]

        assert options[0]["label"].startswith("Pression")
        assert options[0]["declines"] is False
        first = options[0]["payload"]["destination"]
        # L'ennemi déclencheur a fini son mouvement en (5,10).
        best = min(
            (
                option["payload"]["destination"]
                for option in options
                if not option["declines"]
            ),
            key=lambda dest: calculate_hex_distance(dest["col"], dest["row"], 5, 10),
        )
        assert (first["col"], first["row"]) == (best["col"], best["row"])

    def test_declining_leaves_the_unit_in_place_and_closes_the_window(self, monkeypatch):
        """Refuser est un résultat de la règle, pas une erreur : l'unité reste, la fenêtre ferme."""
        gs, reactive, _result = _suspended_window(monkeypatch)
        gs["reactive_decision_payload"]["2"] = {"action": "decline_reactive_move"}

        result = drive_reactive_move_window(gs)

        assert result["waiting_for_player"] is False
        assert result["reactive_moves_declined"] == 1
        assert result["reactive_moves_applied"] == 0
        assert (reactive["col"], reactive["row"]) == (7, 10)
        assert gs["reaction_window_active"] is False
        assert PENDING_REACTIVE_MOVE_KEY not in gs

    def test_choosing_an_intention_moves_the_unit_to_that_cell(self, monkeypatch):
        """Le candidat choisi désigne une case, et c'est CELLE-LÀ que l'unité rejoint."""
        gs, reactive, _result = _suspended_window(monkeypatch)
        chosen = next(
            option
            for option in _pending_decision(gs)["options"]
            if not option["declines"]
        )
        destination = chosen["payload"]["destination"]
        gs["reactive_decision_payload"]["2"] = chosen["payload"]

        result = drive_reactive_move_window(gs)

        assert result["reactive_moves_applied"] == 1
        assert (reactive["col"], reactive["row"]) == (destination["col"], destination["row"])
        assert "2" in gs["units_reacted_this_enemy_turn"]
        assert PENDING_REACTIVE_MOVE_KEY not in gs

    def test_the_roll_survives_the_suspension(self, monkeypatch):
        """Le D6 montré au joueur est celui qui s'applique — il n'est pas re-tiré à la reprise.

        Sans persistance, la portée changerait entre la question et la réponse : le joueur
        choisirait une destination calculée sur un jet qui n'existe plus.
        """
        gs, _reactive, _result = _suspended_window(monkeypatch, roll=3)
        assert gs[PENDING_REACTIVE_MOVE_KEY]["roll"] == 3

        # Le dé change ENTRE la question et la réponse : seul un jet persisté résiste.
        monkeypatch.setattr("random.randint", lambda a, b: 6)
        chosen = next(
            option
            for option in _pending_decision(gs)["options"]
            if not option["declines"]
        )
        gs["reactive_decision_payload"]["2"] = chosen["payload"]
        drive_reactive_move_window(gs)

        applied = [entry for entry in gs["action_logs"] if entry.get("type") == "reactive_move"]
        assert len(applied) == 1
        assert applied[0]["range_roll"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# La phase n'avance pas sous une fenêtre réactive SUSPENDUE (moteur entier)
# ─────────────────────────────────────────────────────────────────────────────


def _engine_with_reactive_enemy(shoot_pool: List[str]) -> Any:
    """Moteur PvP : un tireur `move_after_shooting` (J1) et un réactif (J2) à 5 hexes de sa case.

    `shoot_pool` décide de la seule chose qui compte ici : le tireur est-il la DERNIÈRE
    activation de la phase (`["1"]`) ou non (`["1", "2"]`). C'est cette position, et elle seule,
    qui fait rendre `phase_complete` par la fin d'activation, donc qui expose la cascade.
    """
    from unittest.mock import patch

    from engine.w40k_core import W40KEngine
    from engine.phase_handlers.shooting_handlers import (
        ACTION,
        SHOOTING,
        _handle_shooting_end_activation,
    )
    from tests.unit.engine._config_helpers import (
        _fall_back_base_config,
        _fall_back_unit_cfg,
        build_engine_config,
    )

    shooter = _fall_back_unit_cfg(1, 1, 10, 20)
    shooter["UNIT_RULES"] = [
        {
            "ruleId": "move_after_shooting",
            "displayName": "Purgation Run (test)",
            # Distance FIXE plutôt que le D6 de la datasheet : le pool — donc les destinations
            # offertes — doit être le même à chaque exécution.
            "rule_args": {"distance": 3},
        }
    ]
    reactive = _fall_back_unit_cfg(3, 2, 10, 28)
    reactive["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    units = [shooter, _fall_back_unit_cfg(2, 1, 40, 40), reactive]

    config = build_engine_config(_fall_back_base_config(units))
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), patch.object(
        W40KEngine, "_build_reward_configs_for_current_units", return_value={}
    ):
        engine = W40KEngine(config=config, gym_training_mode=False)
    engine.reset()

    gs = engine.game_state
    gs["phase"] = "shoot"
    gs["current_player"] = 1
    gs["shoot_activation_pool"] = list(shoot_pool)
    # La phase de tir est déjà ouverte : sans ce drapeau `_process_shooting_phase` rejouerait
    # `shooting_phase_start` et reconstruirait le pool que le test vient de poser.
    engine._shooting_phase_initialized = True
    gs["_shooting_phase_initialized"] = True
    shooter_unit = gs["unit_by_id"]["1"]
    shooter_unit["SHOOT_LEFT"] = 0
    # Chemin de production : c'est la fin d'activation du tir qui pose le popup PvP
    # `move_after_shooting` et ses destinations.
    success, armed = _handle_shooting_end_activation(
        gs, shooter_unit, ACTION, 1, SHOOTING, SHOOTING, 1
    )
    assert success is True
    assert armed["action"] == "move_after_shooting_select_destination"
    return engine


class TestPhaseNAvancePasSousFenetreReactive:

    def test_derniere_activation_du_pool_la_phase_reste_ouverte(self):
        """Déclencheur en DERNIÈRE activation : la cascade ne doit pas traverser les phases.

        Sans la garde, cette seule action emmène la partie de `shoot` à `move` (shoot → charge →
        fight → tour suivant → command → move) : `command_phase_start` purge
        `units_reacted_this_enemy_turn`, `reactive_decision_payload` et `reaction_window_active`
        alors que la décision `reactive_move` est TOUJOURS posée.
        """
        engine = _engine_with_reactive_enemy(["1"])
        gs = engine.game_state

        success, result = engine.execute_semantic_action(
            {"action": "move_after_shooting", "unitId": "1", "destCol": 10, "destRow": 23}
        )

        assert success is True
        decision = read_pending_agent_decision(gs)
        assert decision is not None
        assert decision["type"] == "reactive_move"
        assert int(decision["player"]) == 2
        # VERT VACANT : sans ces trois-là, « la phase n'a pas bougé » pourrait décrire une
        # fenêtre qui ne s'est jamais ouverte.
        assert gs["phase"] == "shoot"
        assert gs["reaction_window_active"] is True
        assert PENDING_REACTIVE_MOVE_KEY in gs
        # Le client ne doit pas non plus se voir annoncer une transition qui n'a pas eu lieu.
        assert "next_phase" not in result

    def test_le_meme_declencheur_au_milieu_du_pool_ne_montre_rien(self):
        """Contrôle : au MILIEU du pool, le défaut est invisible — ce test resterait vert.

        La fin d'activation ne rend `phase_complete` que sur un pool vidé. Un test qui place le
        déclencheur ailleurs qu'en dernière activation n'atteint donc jamais la cascade et passe
        avec ou sans la garde : c'est la raison pour laquelle le test ci-dessus existe.
        """
        engine = _engine_with_reactive_enemy(["1", "2"])
        gs = engine.game_state

        success, result = engine.execute_semantic_action(
            {"action": "move_after_shooting", "unitId": "1", "destCol": 10, "destRow": 23}
        )

        assert success is True
        assert result.get("phase_complete") is None
        assert gs["shoot_activation_pool"] == ["2"]
        assert gs["phase"] == "shoot"
        assert _pending_decision(gs)["type"] == "reactive_move"

    def test_advance_phase_envoye_apres_l_armement_n_avance_pas_non_plus(self):
        """La reproduction du PvP humain : le mouvement déclencheur vide le pool de mouvement.

        En PvP, `_process_movement_phase` retire `next_phase` du résultat du dernier mouvement —
        la cascade ne part donc PAS de l'action elle-même : c'est le client qui envoie ensuite
        `advance_phase`, et c'est CE verbe qui traversait les phases sous la décision posée.
        Aucun champ du payload de `advance_phase` ne parle du mouvement réactif : seule la
        lecture de l'état l'arrête.
        """
        from unittest.mock import patch

        from engine.w40k_core import W40KEngine
        from tests.unit.engine._config_helpers import (
            _fall_back_base_config,
            _fall_back_unit_cfg,
            build_engine_config,
        )

        reactive = _fall_back_unit_cfg(3, 2, 10, 24)
        reactive["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
        units = [
            _fall_back_unit_cfg(1, 1, 10, 10),
            _fall_back_unit_cfg(2, 1, 10, 12),
            reactive,
        ]
        config = build_engine_config(_fall_back_base_config(units))
        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), patch.object(
            W40KEngine, "_build_reward_configs_for_current_units", return_value={}
        ):
            engine = W40KEngine(config=config, gym_training_mode=False)
        engine.reset()
        gs = engine.game_state

        # Premier mouvement : loin du réactif, aucune réaction — le pool n'est pas encore vide.
        engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 5, "destRow": 10}
        )
        assert read_pending_agent_decision(gs) is None
        # DERNIÈRE activation du pool, et elle déclenche la réaction.
        engine.execute_semantic_action(
            {"action": "move", "unitId": "2", "destCol": 10, "destRow": 16}
        )
        assert gs["move_activation_pool"] == []
        assert _pending_decision(gs)["type"] == "reactive_move"

        engine.execute_semantic_action({"action": "advance_phase", "from": "move"})

        assert gs["phase"] == "move"
        assert gs["reaction_window_active"] is True
        assert _pending_decision(gs)["type"] == "reactive_move"


# ─────────────────────────────────────────────────────────────────────────────
# Aucune autre action ne passe pendant qu'une décision réactive est armée
# ─────────────────────────────────────────────────────────────────────────────


def _pvp_engine_with_reactive_enemy() -> Any:
    """Moteur PvP humain/humain : deux unités J1 dans le pool de mouvement, un réactif J2.

    Bouger « 2 » vers (10,16) le place à 8 hexes du réactif : la fenêtre s'ouvre et suspend.
    « 1 » reste dans le pool, donc un second mouvement est possible — c'est le clic qu'on refuse.
    """
    from unittest.mock import patch

    from engine.w40k_core import W40KEngine
    from tests.unit.engine._config_helpers import (
        _fall_back_base_config,
        _fall_back_unit_cfg,
        build_engine_config,
    )

    reactive = _fall_back_unit_cfg(3, 2, 10, 24)
    reactive["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    units = [
        _fall_back_unit_cfg(1, 1, 10, 10),
        _fall_back_unit_cfg(2, 1, 10, 12),
        reactive,
    ]
    config = build_engine_config(_fall_back_base_config(units))
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), patch.object(
        W40KEngine, "_build_reward_configs_for_current_units", return_value={}
    ):
        engine = W40KEngine(config=config, gym_training_mode=False)
    engine.reset()
    return engine


class TestRefusPendantUneDecisionReactive:

    def test_un_second_mouvement_pendant_l_attente_est_refuse(self):
        """Le clic banal qui faisait lever le moteur : bouger une autre unité sans avoir répondu.

        Sans le refus, `maybe_resolve_reactive_move` retrouve `reaction_window_active` déjà vrai
        et lève `RuntimeError[reactive_move.reentrance]`.
        """
        engine = _pvp_engine_with_reactive_enemy()
        gs = engine.game_state

        engine.execute_semantic_action(
            {"action": "move", "unitId": "2", "destCol": 10, "destRow": 16}
        )
        assert _pending_decision(gs)["type"] == "reactive_move"
        assert gs["move_activation_pool"] == ["1"]

        success, result = engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 11, "destRow": 10}
        )

        assert success is True
        assert result["action"] == "waiting_for_reactive_move"
        assert result["waiting_for_player"] is True
        assert result["decision_type"] == "reactive_move"
        assert result["rejected_action"] == "move"
        assert str(result["unitId"]) == "3"
        assert int(result["player"]) == 2
        # Refus INERTE : ni l'unité refusée ni le pool n'ont bougé.
        mover = gs["unit_by_id"]["1"]
        assert (mover["col"], mover["row"]) == (10, 10)
        assert gs["move_activation_pool"] == ["1"]

    def test_la_reponse_passe_et_debloque_les_actions_suivantes(self):
        """Le refus vise TOUT sauf la réponse : `agent_decision` traverse, et rend la main.

        VERT VACANT évité : un refus qui barrerait aussi la réponse bloquerait la partie pour de
        bon, et le test précédent seul ne le verrait pas.
        """
        engine = _pvp_engine_with_reactive_enemy()
        gs = engine.game_state
        engine.execute_semantic_action(
            {"action": "move", "unitId": "2", "destCol": 10, "destRow": 16}
        )

        success, result = engine.execute_semantic_action(
            {"action": "agent_decision", "option_index": 0}
        )

        assert success is True
        assert result["decision_type"] == "reactive_move"
        assert result["reactive_moves_applied"] == 1
        assert read_pending_agent_decision(gs) is None
        assert gs["reaction_window_active"] is False

        success, result = engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 11, "destRow": 10}
        )
        assert success is True
        assert result["action"] == "move"
        assert (gs["unit_by_id"]["1"]["col"], gs["unit_by_id"]["1"]["row"]) == (11, 10)


# ─────────────────────────────────────────────────────────────────────────────
# PvE — le siège sans canal de réponse tranche immédiatement
# ─────────────────────────────────────────────────────────────────────────────


def _pve_engine(player_types: Dict[str, str]) -> Any:
    """Moteur en mode PvE, `player_types` DÉCLARÉ (jamais déduit).

    `execute_ai_turn` avale ses exceptions et les rend en `ai_decision_failed` : piloter par
    l'absence d'erreur laisserait un blocage PvE vert. Ces tests pilotent donc par les sièges.
    Le chargement du modèle est neutralisé — c'est la résolution de siège qui est mesurée, pas
    l'inférence.
    """
    from unittest.mock import patch

    from engine.pve_controller import PvEController
    from engine.w40k_core import W40KEngine
    from tests.unit.engine._config_helpers import (
        _fall_back_base_config,
        _fall_back_unit_cfg,
        build_engine_config,
    )

    reactive = _fall_back_unit_cfg(3, 2, 10, 24)
    reactive["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    units = [
        _fall_back_unit_cfg(1, 1, 10, 10),
        _fall_back_unit_cfg(2, 1, 10, 12),
        reactive,
    ]
    config = build_engine_config(_fall_back_base_config(units))
    config["pve_mode"] = True
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), patch.object(
        W40KEngine, "_build_reward_configs_for_current_units", return_value={}
    ), patch.object(PvEController, "load_ai_model_for_pve", lambda self, gs, engine: None):
        engine = W40KEngine(config=config, gym_training_mode=False)
        engine.reset()
    engine.game_state["player_types"] = dict(player_types)
    return engine


class TestReactiveMovePveSeats:

    def test_le_siege_ia_tranche_sans_bloquer_la_partie(self):
        """PvE : le bot réagit au mouvement du joueur, et personne n'a à répondre à sa place.

        `execute_ai_turn` refuse hors tour IA et 08.04 ne couvre que la phase de commandement :
        sans résolution ici, la décision restait posée pour toujours.
        """
        from engine.combat_utils import calculate_hex_distance

        engine = _pve_engine({"1": "human", "2": "ai"})
        gs = engine.game_state

        success, _result = engine.execute_semantic_action(
            {"action": "move", "unitId": "2", "destCol": 10, "destRow": 16}
        )

        assert success is True
        assert read_pending_agent_decision(gs) is None
        assert gs["reaction_window_active"] is False
        assert PENDING_REACTIVE_MOVE_KEY not in gs
        # VERT VACANT : « aucune décision en attente » décrirait aussi une fenêtre qui ne s'est
        # jamais ouverte. La réaction a bien EU LIEU, et vers l'ennemi déclencheur (`CHOICE_0`,
        # « Pression » — la destination que rendait l'ancienne heuristique déterministe).
        assert "3" in gs["units_reacted_this_enemy_turn"]
        reactive = gs["unit_by_id"]["3"]
        assert (reactive["col"], reactive["row"]) != (10, 24)
        assert calculate_hex_distance(
            int(reactive["col"]), int(reactive["row"]), 10, 16
        ) < calculate_hex_distance(10, 24, 10, 16)

    def test_le_siege_humain_garde_sa_question(self):
        """Contrôle : un siège humain, lui, conserve la décision — c'est l'UI qui y répond.

        Sans ce test, une résolution qui tomberait sur TOUS les sièges volerait la question au
        joueur sans qu'aucune assertion ne bouge.
        """
        engine = _pve_engine({"1": "human", "2": "human"})
        gs = engine.game_state

        engine.execute_semantic_action(
            {"action": "move", "unitId": "2", "destCol": 10, "destRow": 16}
        )

        decision = read_pending_agent_decision(gs)
        assert decision is not None
        assert decision["type"] == "reactive_move"
        assert int(decision["player"]) == 2
        assert (gs["unit_by_id"]["3"]["col"], gs["unit_by_id"]["3"]["row"]) == (10, 24)


class TestRefusEtCapaciteDuTour:
    """Le refus consomme-t-il le « Once per turn » de la datasheet ? NON — lecture assumée."""

    def test_le_refus_ne_consomme_pas_la_capacite_du_tour(self, monkeypatch):
        """Refuser n'est pas UTILISER : la question revient au déclencheur suivant du même tour.

        LECTURE RETENUE (décision utilisateur du 2026-09-10) du « Once per turn » de
        `config/unit_rules.json` : la limite porte sur le mouvement ACCOMPLI, pas sur la
        proposition. Une unité qui refuse n'a rien utilisé, donc elle reste éligible.

        ⚠️ Le corpus de règles ne tranche PAS cette lecture : recherche « once per » sur les
        27 PDF de `Documentation/40k_rules/` — deux occurrences, « once per battle »
        (15 Stratagems) et « USE LIMIT: Once per turn » (16 Actions, où la limite porte sur
        l'accomplissement de l'action), aucune définition générale. La lecture est donc PORTÉE
        PAR CE TEST et par le commentaire de `reacted_set.add` : sans lui, la seule trace du
        choix serait l'endroit où une ligne est appelée, et l'inverse passerait pour un fix.

        Conséquence de jeu verrouillée ici : tant que le joueur refuse, la question revient à
        chaque mouvement ennemi qui finit à portée dans le même tour.
        """
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        mover = _unit(1, 1, 5, 10)
        second_mover = _unit(3, 1, 3, 10)
        reactive = _unit_with_reactive(2, 2, 7, 10)
        gs = _make_game_state([mover, second_mover, reactive])
        gs["reactive_decision_mode"] = "state"

        first = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert first["waiting_for_player"] is True

        # ORDRE DE PRODUCTION, celui de `W40KEngine._handle_agent_decision_action` : consommer la
        # décision, écrire la réponse dans le canal que la fenêtre lit, reprendre la fenêtre.
        # Sauter le premier pas laisse la décision armée, et `set_pending_agent_decision` REFUSE
        # d'en empiler une seconde au déclencheur suivant — le test mesurerait ce refus au lieu
        # de la capacité du tour.
        consume_pending_agent_decision(
            gs, decision_type="reactive_move", player=2, unit_id="2"
        )
        gs["reactive_decision_payload"]["2"] = {"action": "decline_reactive_move"}
        declined = drive_reactive_move_window(gs)
        assert declined["reactive_moves_declined"] == 1
        # La réponse est CONSOMMÉE par la fenêtre. Sans cette vérification, le second
        # déclencheur pourrait rejouer le refus resté en place au lieu de reposer la question,
        # et l'assertion finale serait verte pour la mauvaise raison.
        assert "2" not in gs["reactive_decision_payload"]
        # Le refus n'inscrit rien au compteur du tour : c'est TOUTE la lecture retenue.
        assert "2" not in gs["units_reacted_this_enemy_turn"]

        # Second déclencheur, MÊME tour (`turn` inchangé) : une AUTRE unité ennemie finit son
        # mouvement à portée, hors zone d'engagement de l'unité réactive.
        again = maybe_resolve_reactive_move(gs, "3", 2, 10, 3, 10, "move", "normal")

        assert again["waiting_for_player"] is True, (
            "la question ne revient pas : le refus a consommé la capacité du tour"
        )
        decision = read_pending_agent_decision(gs)
        assert decision is not None
        assert str(decision["unit_id"]) == "2"
        assert int(decision["player"]) == 2
        # Elle n'a toujours pas bougé : deux questions, aucun mouvement.
        assert (reactive["col"], reactive["row"]) == (7, 10)
