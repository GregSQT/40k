"""Bloc 1 — Cœur règles de l'étape FIGHT V11 (PDF 12.04→12.06).

Tests des fonctions ADDITIVES pures (non branchées sur le routage V10) :
- éligibilités fight 12.04 / overrun 12.06 / pile-in 12.03 / consolidation 12.08
- machine de sélection 12.04 (fight_v11_advance_selection) : FF d'abord, handoff,
  passage Remaining, fin d'étape.

Plateau single-hex (engagement_zone=1) : engagé = distance empreinte ≤ 1.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers.fight_handlers import (
    fight_v11_is_pile_in_eligible,
    fight_v11_is_eligible_to_fight,
    fight_v11_is_overrun_eligible,
    fight_v11_is_normal_fight_eligible,
    fight_v11_is_consolidation_eligible,
    fight_v11_eligible_unit_ids,
    fight_v11_advance_selection,
)


def _make_gs(
    units: List[Dict[str, Any]],
    *,
    current_player: int = 1,
    units_charged: Optional[List[str]] = None,
    units_selected_to_fight: Optional[List[str]] = None,
    engaged_snapshot: Optional[Dict[str, bool]] = None,
    fight_step: str = "fights_first",
    fight_selector: Optional[int] = None,
) -> Dict[str, Any]:
    units_cache: Dict[str, Any] = {}
    norm_units: List[Dict[str, Any]] = []
    for u in units:
        uid = str(u["id"])
        full = {
            "id": uid, "player": u["player"], "col": u["col"], "row": u["row"],
            "BASE_SIZE": 1, "BASE_SHAPE": "round", "orientation": 0,
            "HP_CUR": u.get("HP_CUR", 1), "HP_MAX": u.get("HP_MAX", 1),
        }
        norm_units.append(full)
        if u.get("alive", True):
            units_cache[uid] = {
                "col": u["col"], "row": u["row"], "player": u["player"],
                "BASE_SIZE": 1, "BASE_SHAPE": "round", "orientation": 0,
                "HP_CUR": u.get("HP_CUR", 1),
            }
    return {
        "inches_to_subhex": 1, "board_cols": 40, "board_rows": 40,
        "config": {"game_rules": {"engagement_zone": 1}},
        "units": norm_units, "units_cache": units_cache, "wall_hexes": set(),
        "current_player": current_player,
        "units_charged": set(units_charged or []),
        "units_selected_to_fight": set(units_selected_to_fight or []),
        "engaged_at_fight_step_start": dict(engaged_snapshot or {}),
        "fight_step": fight_step,
        "fight_selector": fight_selector if fight_selector is not None else current_player,
    }


def _u(gs, uid):
    for u in gs["units"]:
        if str(u["id"]) == uid:
            return u
    raise KeyError(uid)


# ----------------------------------------------------- éligibilités

class TestEligibilities:
    def test_pile_in_eligible_engaged_or_charged(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},   # engagé avec e
            {"id": "e", "player": 2, "col": 5, "row": 4},
            {"id": "c", "player": 1, "col": 20, "row": 20},  # a chargé, loin
            {"id": "x", "player": 1, "col": 30, "row": 30},  # ni engagé ni chargé
        ], units_charged=["c"])
        assert fight_v11_is_pile_in_eligible(gs, _u(gs, "a")) is True
        assert fight_v11_is_pile_in_eligible(gs, _u(gs, "c")) is True
        assert fight_v11_is_pile_in_eligible(gs, _u(gs, "x")) is False

    def test_fight_eligible_engaged_snapshot_charged(self):
        gs = _make_gs([
            {"id": "eng", "player": 1, "col": 5, "row": 5},
            {"id": "foe", "player": 2, "col": 5, "row": 4},
            {"id": "snap", "player": 1, "col": 20, "row": 20},   # engagé au début du step
            {"id": "chg", "player": 1, "col": 25, "row": 25},    # a chargé, cible morte
            {"id": "none", "player": 1, "col": 30, "row": 30},
            {"id": "sel", "player": 1, "col": 5, "row": 6},      # déjà sélectionné
        ], units_charged=["chg"], units_selected_to_fight=["sel"],
           engaged_snapshot={"snap": True})
        assert fight_v11_is_eligible_to_fight(gs, _u(gs, "eng")) is True
        assert fight_v11_is_eligible_to_fight(gs, _u(gs, "snap")) is True
        assert fight_v11_is_eligible_to_fight(gs, _u(gs, "chg")) is True
        assert fight_v11_is_eligible_to_fight(gs, _u(gs, "none")) is False
        assert fight_v11_is_eligible_to_fight(gs, _u(gs, "sel")) is False

    def test_overrun_eligible(self):
        gs = _make_gs([
            {"id": "free", "player": 1, "col": 20, "row": 20},  # unengaged maintenant
            {"id": "eng_was_free", "player": 1, "col": 5, "row": 5},  # engagé mais pas au start
            {"id": "foe", "player": 2, "col": 5, "row": 4},
            {"id": "eng_was_eng", "player": 1, "col": 10, "row": 10},  # engagé et l'était au start
            {"id": "foe2", "player": 2, "col": 10, "row": 9},
        ], engaged_snapshot={"eng_was_free": False, "eng_was_eng": True})
        assert fight_v11_is_overrun_eligible(gs, _u(gs, "free")) is True
        assert fight_v11_is_overrun_eligible(gs, _u(gs, "eng_was_free")) is True
        assert fight_v11_is_overrun_eligible(gs, _u(gs, "eng_was_eng")) is False

    def test_normal_fight_eligible_requires_engaged(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e", "player": 2, "col": 5, "row": 4},
            {"id": "far", "player": 1, "col": 20, "row": 20},
        ])
        assert fight_v11_is_normal_fight_eligible(gs, _u(gs, "a")) is True
        assert fight_v11_is_normal_fight_eligible(gs, _u(gs, "far")) is False

    def test_consolidation_eligible_selected_and_alive(self):
        gs = _make_gs([
            {"id": "s", "player": 1, "col": 5, "row": 5},
            {"id": "dead", "player": 1, "col": 6, "row": 6, "alive": False},
            {"id": "ns", "player": 1, "col": 7, "row": 7},
        ], units_selected_to_fight=["s", "dead"])
        assert fight_v11_is_consolidation_eligible(gs, _u(gs, "s")) is True
        assert fight_v11_is_consolidation_eligible(gs, _u(gs, "dead")) is False
        assert fight_v11_is_consolidation_eligible(gs, _u(gs, "ns")) is False


# ----------------------------------------------------- machine de sélection 12.04

class TestSelectionMachine:
    def test_fights_first_active_then_handoff_then_remaining(self):
        """P1 (actif) FF charge ; P2 a une unité engagée non-FF. Ordre attendu :
        FF P1 d'abord, puis Remaining (P1 a fait passer la séquence) puis P2."""
        gs = _make_gs([
            {"id": "p1ff", "player": 1, "col": 5, "row": 5},   # chargé → FF, engagé
            {"id": "p2", "player": 2, "col": 5, "row": 4},      # engagé, non-FF
        ], current_player=1, units_charged=["p1ff"],
           engaged_snapshot={"p1ff": True, "p2": True})

        # 1) FF : P1 sélectionne p1ff
        nxt = fight_v11_advance_selection(gs)
        assert nxt == "p1ff"
        assert gs["fight_step"] == "fights_first" and gs["fight_selector"] == 1
        gs["units_selected_to_fight"].add("p1ff")

        # 2) plus de FF → Remaining, P1 a fait passer la séquence mais n'a plus d'éligible
        #    → handoff à P2
        nxt = fight_v11_advance_selection(gs)
        assert nxt == "p2"
        assert gs["fight_step"] == "remaining" and gs["fight_selector"] == 2
        gs["units_selected_to_fight"].add("p2")

        # 3) plus personne → fin
        assert fight_v11_advance_selection(gs) is None

    def test_remaining_alternation_both_sides(self):
        """Aucune FF. Remaining démarre par l'actif (P1), alterne P1↔P2."""
        gs = _make_gs([
            {"id": "p1a", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},
            {"id": "p2a", "player": 2, "col": 10, "row": 10},
            {"id": "e2", "player": 1, "col": 10, "row": 9},
        ], current_player=1, fight_step="remaining", fight_selector=1)
        # tous engagés, aucun chargé → pas de FF
        order = []
        for _ in range(5):
            nxt = fight_v11_advance_selection(gs)
            if nxt is None:
                break
            order.append((gs["fight_selector"], nxt))
            gs["units_selected_to_fight"].add(nxt)
        # P1 sélectionne d'abord, puis l'autre joueur, etc. (alternance)
        selectors = [s for s, _ in order]
        assert selectors[0] == 1
        assert set(uid for _, uid in order) == {"p1a", "e1", "p2a", "e2"}

    def test_same_player_selects_consecutively_when_opponent_empty(self):
        """P1 a 2 unités éligibles, P2 aucune → P1 sélectionne 2 fois de suite, puis fin."""
        gs = _make_gs([
            {"id": "p1a", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},
            {"id": "p1b", "player": 1, "col": 10, "row": 10},
            {"id": "e2", "player": 2, "col": 10, "row": 9},
        ], current_player=1, fight_step="remaining", fight_selector=1)
        # P2 units e1/e2 : marquer comme déjà sélectionnées pour qu'il ne reste que P1
        gs["units_selected_to_fight"].update(["e1", "e2"])
        picked = []
        for _ in range(4):
            nxt = fight_v11_advance_selection(gs)
            if nxt is None:
                break
            assert gs["fight_selector"] == 1
            picked.append(nxt)
            gs["units_selected_to_fight"].add(nxt)
        assert set(picked) == {"p1a", "p1b"}

    def test_empty_returns_none(self):
        gs = _make_gs([
            {"id": "p1", "player": 1, "col": 20, "row": 20},  # ni engagé ni chargé
        ], current_player=1, fight_step="fights_first", fight_selector=1)
        assert fight_v11_advance_selection(gs) is None
