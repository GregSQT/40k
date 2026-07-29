"""T3 — phase move : escouades par figurine, advance (09.06), fall-back (09.07).

Règles assertées ici, lues dans ``Documentation/40k_rules/09 Movement phase.pdf`` :
  - 09.02 : chaque unité doit être sélectionnée pour bouger dans la phase, même pour
            rester stationnaire → en début de phase, le pool contient TOUTES les unités
            vivantes du joueur actif.
  - 09.05 : Normal move — distance maximale = caractéristique M de l'unité.
  - 09.06 : Advance move — distance maximale = M + jet d'advance (1D6) ; après le move,
            l'unité n'est plus éligible pour déclarer une charge.
  - 09.07 : Fall-back move — après le move, l'unité n'est plus éligible pour tirer ni
            pour déclarer une charge, et doit être désengagée.

Le PDF 09.06 ne dit RIEN d'une interdiction de tirer après un advance (cette restriction
relève des règles d'armes, PDF 10/24) : elle n'est donc pas assertée ici.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pytest

from engine.hex_utils import hex_distance

pytestmark = pytest.mark.integration


def _model_position(game, model_id: str) -> Tuple[int, int]:
    model = game.state["models_cache"][model_id]
    return int(model["col"]), int(model["row"])


def _model_destinations(game, model_id: str, provisional_plan: Dict[str, Tuple[int, int, int]]):
    """Pool BFS d'UNE figurine, les sœurs déjà posées bloquant le passage."""
    body = game.act(
        "move_model_destinations",
        model_id=model_id,
        provisional_plan={k: list(v) for k, v in provisional_plan.items()},
    )
    return body["result"]


def _plan_one_step(game, unit_id: str, farthest: bool = False) -> List[list]:
    """Construit un plan complet en déplaçant chaque figurine d'un pas.

    Reproduit le flux du front : figurine par figurine, chacune recalculée avec le plan
    provisoire des sœurs déjà posées. ``farthest`` vise la destination la plus éloignée
    (utile pour un fall-back qui doit sortir de l'engagement).
    """
    plan: Dict[str, Tuple[int, int, int]] = {}
    for model_id in game.models_of(unit_id):
        origin = _model_position(game, model_id)
        destinations = _model_destinations(game, model_id, plan)["destinations"]
        assert destinations, f"figurine {model_id} : aucune destination"
        key = (lambda d: -hex_distance(origin[0], origin[1], d[0], d[1])) if farthest else (
            lambda d: hex_distance(origin[0], origin[1], d[0], d[1]) or 99
        )
        chosen = min(destinations, key=key)
        plan[model_id] = (int(chosen[0]), int(chosen[1]), int(chosen[2]))
    return [[model_id, c, r, lv] for model_id, (c, r, lv) in plan.items()]


def _multi_model_unit(game) -> str:
    for unit_id in game.pool("move_activation_pool"):
        if len(game.models_of(unit_id)) > 1:
            return unit_id
    raise AssertionError("aucune escouade multi-figurines dans le pool de move")


def _would_flee(game, unit_id: str) -> bool:
    """Une unité engagée : son move serait un fall-back (09.07)."""
    plan = [[m, *_model_position(game, m)] for m in game.models_of(unit_id)]
    body = game.act("preview_move_plan", unitId=unit_id, plan=plan)
    return bool(body["result"]["would_flee"])


def _engaged_unit(game) -> str:
    for unit_id in game.pool("move_activation_pool"):
        game.act("activate_unit", unitId=unit_id)
        engaged = _would_flee(game, unit_id)
        game.act("right_click", unitId=unit_id)
        if engaged:
            return unit_id
    raise AssertionError("aucune unité engagée dans le pool de move")


class TestMovePoolComposition:
    def test_pool_contains_every_living_unit_of_the_active_player(self, game):
        """t3_pool_complet_09_02 : au début de la phase, toutes les unités y sont (09.02)."""
        expected = set(game.alive_ids(game.current_player))
        assert set(game.pool("move_activation_pool")) == expected


class TestSquadModelDestinations:
    def test_each_model_gets_its_own_destination_pool(self, game):
        """t3_pool_par_figurine : chaque figurine a son BFS, borné par M (09.05)."""
        unit_id = _multi_model_unit(game)
        move_budget = game.unit(unit_id)["MOVE"]
        cols, rows = game.state["board_cols"], game.state["board_rows"]
        game.act("activate_unit", unitId=unit_id)

        for model_id in game.models_of(unit_id):
            origin = _model_position(game, model_id)
            result = _model_destinations(game, model_id, {})
            destinations = result["destinations"]
            assert destinations, f"figurine {model_id} : pool vide"
            assert result["footprint_mask_loops"], f"figurine {model_id} : masque d'empreinte absent"
            for col, row, _level in destinations:
                assert 0 <= col < cols and 0 <= row < rows, f"destination hors board : {(col, row)}"
                # Chaque pas de BFS coûte au moins 1 subhex : la distance en hexes ne peut
                # donc jamais dépasser le budget de mouvement (09.05).
                distance = hex_distance(origin[0], origin[1], col, row)
                assert distance <= move_budget, (
                    f"figurine {model_id} : destination {(col, row)} à {distance} hexes "
                    f"pour un budget M={move_budget}"
                )

    def test_sisters_already_placed_block_the_pool(self, game):
        """t3_plan_provisoire : une sœur posée retire sa case du pool des suivantes."""
        unit_id = _multi_model_unit(game)
        game.act("activate_unit", unitId=unit_id)
        models = game.models_of(unit_id)
        first, second = models[0], models[1]

        free = _model_destinations(game, second, {})["destinations"]
        taken = min(
            (d for d in free if tuple(d[:2]) != _model_position(game, first)),
            key=lambda d: hex_distance(*_model_position(game, first), d[0], d[1]),
        )
        blocked = _model_destinations(game, second, {first: tuple(taken)})["destinations"]

        assert [taken[0], taken[1], taken[2]] in free
        assert [taken[0], taken[1], taken[2]] not in blocked, (
            f"la case {taken[:2]} occupée par la sœur {first} reste proposée à {second}"
        )


class TestCommitMovePlan:
    def test_incomplete_plan_is_rejected(self, game):
        """t3_plan_incomplet : un plan qui ne couvre pas toutes les figurines est refusé."""
        unit_id = _multi_model_unit(game)
        game.act("activate_unit", unitId=unit_id)
        plan = _plan_one_step(game, unit_id)

        accepted, body = game.try_act("commit_move_plan", unitId=unit_id, plan=plan[:-1])

        assert not accepted
        assert body["result"]["error"] == "plan_models_mismatch"
        assert unit_id in game.pool("move_activation_pool"), "l'unité a quitté le pool sur un refus"

    def test_valid_plan_previews_then_commits(self, game):
        """t3_commit_par_figurine : preview validant, puis commit → positions posées."""
        unit_id = _multi_model_unit(game)
        game.act("activate_unit", unitId=unit_id)
        plan = _plan_one_step(game, unit_id)

        preview = game.act(
            "preview_move_plan", unitId=unit_id, plan=[[m, c, r] for m, c, r, _ in plan]
        )["result"]
        assert preview["coherency_ok"] is True, "cohésion d'escouade (06.02) refusée sur un plan d'un pas"
        assert preview["can_validate"] is True
        assert all(preview["per_model"].values()), f"placements invalides : {preview['per_model']}"

        game.act("commit_move_plan", unitId=unit_id, plan=plan)

        for model_id, col, row, _level in plan:
            assert _model_position(game, model_id) == (col, row), (
                f"figurine {model_id} : posée en {_model_position(game, model_id)}, planifiée en {(col, row)}"
            )
        assert unit_id in [str(u) for u in game.state["units_moved"]]
        assert unit_id not in game.pool("move_activation_pool")

    def test_a_moved_unit_cannot_be_activated_again(self, game):
        """t3_reactivation_refusee : une unité déjà déplacée n'est plus activable (09.02)."""
        unit_id = _multi_model_unit(game)
        game.act("activate_unit", unitId=unit_id)
        game.act("commit_move_plan", unitId=unit_id, plan=_plan_one_step(game, unit_id))

        accepted, body = game.try_act("activate_unit", unitId=unit_id)

        assert not accepted
        assert body["result"]["error"] == "unit_not_eligible"


class TestAdvance:
    """09.06 — Advance move."""

    def test_advance_roll_extends_the_move_budget(self, game):
        """t3_advance_portee_09_06 : la portée passe à M + jet d'advance."""
        unit_id = next(u for u in game.pool("move_activation_pool") if not _is_engaged(game, u))
        move_budget = game.unit(unit_id)["MOVE"]
        subhex_per_inch = game.state["inches_to_subhex"]
        model_id = game.models_of(unit_id)[0]
        origin = _model_position(game, model_id)

        game.act("activate_unit", unitId=unit_id)
        before = max(
            hex_distance(*origin, d[0], d[1])
            for d in _model_destinations(game, model_id, {})["destinations"]
        )

        result = game.act("advance", unitId=unit_id)["result"]
        roll = result["advance_roll"]
        assert 1 <= roll <= 6, f"jet d'advance hors 1D6 : {roll}"

        after = max(
            hex_distance(*origin, d[0], d[1])
            for d in _model_destinations(game, model_id, {})["destinations"]
        )
        assert after > before, "l'advance n'a pas étendu la portée"
        assert after <= move_budget + roll * subhex_per_inch, (
            f"portée {after} hexes au-delà de M({move_budget}) + jet({roll})×{subhex_per_inch}"
        )
        assert unit_id in [str(u) for u in game.state["units_advanced"]]

    def test_advanced_unit_cannot_declare_a_charge(self, game):
        """t3_advance_pas_de_charge_09_06 : après un advance, plus de charge ce tour."""
        unit_id = next(u for u in game.pool("move_activation_pool") if not _is_engaged(game, u))
        game.act("activate_unit", unitId=unit_id)
        game.act("advance", unitId=unit_id)
        game.act("commit_move_plan", unitId=unit_id, plan=_plan_one_step(game, unit_id))
        assert unit_id in [str(u) for u in game.state["units_advanced"]]

        game.drain_to("charge")

        assert unit_id not in game.pool("charge_activation_pool"), (
            "une unité ayant fait un advance reste éligible à la charge (09.06)"
        )


class TestFallBack:
    """09.07 — Fall-back move."""

    def test_fall_back_marks_the_unit_and_disengages_it(self, game):
        """t3_fallback_desengage_09_07 : l'unité est tracée units_fled et n'est plus engagée."""
        unit_id = _engaged_unit(game)
        game.act("activate_unit", unitId=unit_id)
        game.act("commit_move_plan", unitId=unit_id, plan=_plan_one_step(game, unit_id, farthest=True))

        assert unit_id in [str(u) for u in game.state["units_fled"]]
        # 09.02 : un fall-back reste une sélection pour bouger — le moteur pose donc les
        # deux marques (``units_fled`` est un sous-ensemble de ``units_moved``,
        # movement_handlers.py:1292).
        assert unit_id in [str(u) for u in game.state["units_moved"]]

        game.drain_to("fight")
        assert unit_id not in [str(u) for u in game.state["fight_eligible_units"]], (
            "l'unité reste engagée après un fall-back (09.07 : must be unengaged)"
        )

    def test_fled_unit_cannot_shoot_nor_charge(self, game):
        """t3_fallback_ni_tir_ni_charge_09_07 : exclue du pool de tir ET de charge."""
        unit_id = _engaged_unit(game)
        game.act("activate_unit", unitId=unit_id)
        game.act("commit_move_plan", unitId=unit_id, plan=_plan_one_step(game, unit_id, farthest=True))
        assert unit_id in [str(u) for u in game.state["units_fled"]]

        game.drain_to("shoot")
        assert unit_id not in game.pool("shoot_activation_pool"), "une unité ayant fui peut tirer (09.07)"

        game.drain_to("charge")
        assert unit_id not in game.pool("charge_activation_pool"), "une unité ayant fui peut charger (09.07)"


def _is_engaged(game, unit_id: str) -> bool:
    """Engagement lu sans laisser de trace : activation, preview, annulation."""
    game.act("activate_unit", unitId=unit_id)
    engaged = _would_flee(game, unit_id)
    game.act("right_click", unitId=unit_id)
    return engaged
