"""Sélection du mode de fall-back (09.07) par le joueur actif, pour les DEUX sièges.

PDF 09, encart SELECTING MODES : « in the case of fall-back moves, ordered retreat is not
mandatory, so you could select desperate escape instead ». Et 09.07 AFTER MOVING — Desperate
Escape : « If your unit is not battle-shocked, you must make a battle-shock roll (01.07) ».

Le moteur dérivait le mode du seul drapeau `battle_shocked` : une escouade saine était en Ordered
Retreat quoi qu'il arrive, et une escouade saine ENCERCLÉE — aucune issue sans traverser les
ennemis — était close d'office (`no_valid_move_destinations`) sans qu'aucun geste ne lui permette
de choisir. `desperate_escape_post_move`, lui, n'avait aucun appelant de production.

Ce fichier verrouille les deux sièges sur un plateau x1 (hex) : une escouade d'une figurine en
(20,20), six ennemis sur ses six voisins. En Ordered Retreat, le pool est VIDE (les figurines
ennemies bloquent la traversée, 03.01) ; en Desperate Escape, les cases à distance 3 s'ouvrent
(la couronne 2 est dans l'EZ, donc interdite en destination : AFTER MOVING « unengaged »).

Cycles rouge→vert constatés :
  - `movement_unit_execution_loop` : retirer `and not desperate_escape_selectable` du skip →
    `test_pvp_encircled_sane_squad_is_offered_the_choice_not_skipped` rouge ;
  - `_handle_hazard_confirm` : rétablir la garde `battle_shocked` →
    `test_pvp_hazard_confirm_selects_desperate_escape_for_a_sane_squad` rouge ;
  - retirer l'appel `desperate_escape_post_move` d'un commit → le test de battle-shock de ce
    commit rouge ;
  - `action_decoder` : retirer la section 3ter → `test_gym_mask_arms_the_choice...` rouge.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.agent_decision import read_pending_agent_decision
from engine.combat_utils import calculate_hex_distance, get_hex_neighbors
from engine.macro_intents import CHOICE_BASE, MOVE_CELLS
from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    AGENT_DECISION_TYPE_SLOTS,
)
from engine.phase_handlers.movement_handlers import (
    apply_fall_back_mode_decision,
    arm_fall_back_mode_decision,
    fall_back_mode_decision_is_due,
    movement_unit_execution_loop,
)
from engine.phase_handlers.shared_utils import (
    FALL_BACK_MODES_KEY,
    _move_spatial_cache,
    build_enemy_adjacent_hexes,
    build_units_cache,
    desperate_escape_mode_selected,
    fall_back_mode_of,
    fall_back_mode_resolved,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)

_CENTER = (20, 20)
_HAZARD = "engine.phase_handlers.shared_utils.roll_hazard_for_unit"


def _no_wounds(squad_id: str, game_state: Dict[str, Any], auto_resolve: bool) -> int:
    """Hazard 06.03 sans blessure : le mode est retenu, les jets sont « faits », personne ne meurt."""
    game_state["_desperate_escape_rolls"] = [6]
    return 0


def _engine_encircled(*, gym: bool = True, centers=(_CENTER,)) -> W40KEngine:
    """Une escouade J1 saine par centre (ids 1, 2, …), six ennemis J2 sur ses six voisins (ids
    10+, 30+, …). Le pool d'activation contient les escouades J1 dans l'ordre des centres."""
    units: List[Dict[str, Any]] = []
    for k, center in enumerate(centers):
        units.append(_unit_cfg(1 + k, 1, *center))
        for i, (c, r) in enumerate(get_hex_neighbors(*center)):
            units.append(_unit_cfg(10 + 20 * k + i, 2, c, r))
    eng = _make_engine(_base_config(units))
    gs = eng.game_state
    gs["phase"] = "move"
    gs["current_player"] = 1
    gs["move_activation_pool"] = [str(1 + k) for k in range(len(centers))]
    gs["gym_training_mode"] = gym
    gs["pve_mode"] = False
    return eng


def _rebuild_caches(gs: Dict[str, Any]) -> None:
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)


def _disengage(gs: Dict[str, Any]) -> None:
    """Recule les six ennemis hors de l'ER de l'escouade 1 : elle n'est plus engagée."""
    for i in range(6):
        u = _unit(gs, str(10 + i))
        u["col"], u["row"] = 40 + i, 40
    _rebuild_caches(gs)


def _open_exit(gs: Dict[str, Any]) -> None:
    """Une issue : l'ennemi 10 recule, un couloir s'ouvre — un Ordered Retreat devient possible."""
    exit_enemy = _unit(gs, "10")
    exit_enemy["col"], exit_enemy["row"] = 30, 30
    _rebuild_caches(gs)


def _pvp_select_desperate_escape(eng: W40KEngine, sid: str = "1") -> Dict[str, Any]:
    """Active `sid` puis SÉLECTIONNE Desperate Escape par `hazard_confirm` (hazard sans blessure).
    Rend le payload de reprise (pool de Desperate Escape)."""
    gs = eng.game_state
    gs["active_movement_unit"] = sid
    movement_unit_execution_loop(gs, sid)
    with patch(_HAZARD, side_effect=_no_wounds):
        ok, payload = eng._process_semantic_action({"action": "hazard_confirm", "unitId": sid})
    assert ok, payload
    return payload


def _plan_to(sid: str, dest) -> List[List[Any]]:
    return [[f"{sid}#0", dest[0], dest[1], 0]]


def _gym_answer(eng: W40KEngine, desperate_escape: bool) -> None:
    """Fait poser la question par le masque, puis y répond pour l'escouade 1."""
    eng.action_decoder.get_squad_action_mask_and_eligible_units(eng.game_state)
    apply_fall_back_mode_decision(eng.game_state, "1", desperate_escape=desperate_escape)


def _unit(gs: Dict[str, Any], uid: str) -> Dict[str, Any]:
    return next(u for u in gs["units"] if str(u["id"]) == uid)


def _open_actions(mask) -> List[int]:
    return [i for i, opened in enumerate(mask) if bool(opened)]


def _logs_of_type(gs: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [e for e in gs.get("action_logs", []) if e.get("type") == kind]


# ─────────────────────────────────────────────────────────────────────────────
# 0. Contrat d'observation : un type de plus, aucune colonne de plus
# ─────────────────────────────────────────────────────────────────────────────


def test_the_type_consumes_a_reserved_slot_and_leaves_obs_size_untouched():
    # Ajouté en FIN, jamais inséré : son index est figé (les types suivants s'ajoutent après lui,
    # `consolidation_engaging` le 2026-09-18).
    assert AGENT_DECISION_TYPE_IDS.index("fall_back_mode") == 12, "ajouté en FIN, jamais inséré"
    assert len(AGENT_DECISION_TYPE_IDS) <= AGENT_DECISION_TYPE_SLOTS


# ─────────────────────────────────────────────────────────────────────────────
# 1. Siège humain (PvP) : activation, sélection par hazard_confirm, commit
# ─────────────────────────────────────────────────────────────────────────────


def test_pvp_encircled_sane_squad_is_offered_the_choice_not_skipped():
    """LE défaut : l'escouade saine encerclée était close d'office. Elle doit rester active, pool
    vide, mode `ordered_retreat` publié — c'est ce que le front lit pour offrir Desperate Escape."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    gs["active_movement_unit"] = "1"

    ok, payload = movement_unit_execution_loop(gs, "1")

    assert ok
    assert payload.get("action") != "skip", f"escouade close d'office : {payload}"
    assert payload["waiting_for_player"] is True
    assert payload["valid_destinations"] == [], "témoin : Ordered Retreat n'a aucune issue"
    assert payload["would_flee"] is True
    assert payload["fall_back_mode"] == "ordered_retreat"
    assert "1" in gs["move_activation_pool"], "l'activation ne doit pas être close"


def test_pvp_unengaged_squad_with_no_destination_is_still_skipped():
    """Témoin : le skip reste la règle hors fall-back (rien à sélectionner)."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    # Ennemis reculés hors ER : l'escouade n'est plus engagée, et les murs l'enferment.
    _disengage(gs)
    gs["wall_hexes"] = set(get_hex_neighbors(*_CENTER))
    gs["active_movement_unit"] = "1"

    ok, payload = movement_unit_execution_loop(gs, "1")

    assert ok
    assert payload.get("action") == "skip", f"attendu skip, obtenu {payload}"
    assert payload["skip_reason"] == "no_valid_move_destinations"


def test_pvp_shocked_squad_is_still_forced_into_desperate_escape():
    """Mode IMPOSÉ (« Otherwise, you must select this mode ») : popup à l'activation, aucun choix."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _unit(gs, "1")["battle_shocked"] = True
    gs["active_movement_unit"] = "1"

    ok, payload = movement_unit_execution_loop(gs, "1")

    assert ok
    assert payload["action"] == "requires_hazard"


def test_pvp_hazard_confirm_selects_desperate_escape_for_a_sane_squad():
    """`hazard_confirm` sur une escouade saine = SÉLECTION du mode : verrou posé, hazard roulé,
    pool rebâti À TRAVERS les ennemis, mode `desperate_escape` publié."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    gs["active_movement_unit"] = "1"
    movement_unit_execution_loop(gs, "1")
    assert gs["valid_move_destinations_pool"] == [], "témoin : pool Ordered Retreat vide"

    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, payload = eng._process_semantic_action({"action": "hazard_confirm", "unitId": "1"})

    assert ok, f"confirmation refusée : {payload}"
    assert hazard.call_count == 1, "le hazard 06.03 doit être roulé UNE fois"
    assert desperate_escape_mode_selected(gs, "1")
    assert payload["fall_back_mode"] == "desperate_escape"
    assert payload["fall_back_resume"] is True
    pool = payload["valid_destinations"]
    assert pool, "Desperate Escape doit ouvrir des destinations à travers l'encerclement"
    assert all(calculate_hex_distance(*_CENTER, c, r) >= 3 for c, r in pool), (
        "la couronne 2 est dans l'EZ ennemie : interdite en destination (AFTER MOVING unengaged)"
    )


def test_pvp_hazard_confirm_refuses_a_second_confirmation():
    """Les jets sont faits une fois : re-confirmer (double clic, report puis ré-activation) est
    refusé sans rejouer le hazard."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _pvp_select_desperate_escape(eng)
    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, payload = eng._process_semantic_action({"action": "hazard_confirm", "unitId": "1"})

    assert ok is False
    assert payload["error"] == "hazard_already_resolved"
    assert hazard.call_count == 0


def test_pvp_reactivation_after_hazard_does_not_repose_the_popup():
    """Escouade battle-shocked, hazard fait, activation reportée puis reprise : le verrou dit que
    les jets sont faits — reposer `requires_hazard` les ferait rejouer."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _unit(gs, "1")["battle_shocked"] = True
    gs["active_movement_unit"] = "1"
    assert movement_unit_execution_loop(gs, "1")[1]["action"] == "requires_hazard"
    _pvp_select_desperate_escape(eng)
    from engine.phase_handlers.movement_handlers import _handle_movement_postpone
    gs["active_movement_unit"] = "1"
    assert _handle_movement_postpone(gs, _unit(gs, "1"))[0]

    gs["active_movement_unit"] = "1"
    ok, payload = movement_unit_execution_loop(gs, "1")

    assert ok
    assert payload.get("action") != "requires_hazard", "popup reposé : hazard rejoué"
    assert payload["fall_back_mode"] == "desperate_escape"
    assert payload["valid_destinations"], "le pool de reprise doit être celui de Desperate Escape"


def test_pvp_lock_of_a_postponed_squad_survives_another_squad_selecting_desperate_escape():
    """Verrou par ESCOUADE, pas scalaire. A retient Desperate Escape (hazards roulés), reporte son
    activation ; B retient Desperate Escape à son tour et bouge. À la reprise d'A, son mode vaut
    encore : pas de second hazard, pas de retraite reclassée en move normal."""
    from engine.phase_handlers.movement_handlers import _handle_movement_postpone

    # A (1) encerclée en (20,20) et B (2) encerclée en (40,40), toutes deux J1 et saines.
    eng = _engine_encircled(gym=False, centers=(_CENTER, (40, 40)))
    gs = eng.game_state

    # A retient Desperate Escape, puis reporte.
    _pvp_select_desperate_escape(eng, "1")
    gs["active_movement_unit"] = "1"
    assert _handle_movement_postpone(gs, _unit(gs, "1"))[0]
    assert desperate_escape_mode_selected(gs, "1")

    # B retient Desperate Escape et bouge : son activation se clôt, la sienne seule.
    dest = _pvp_select_desperate_escape(eng, "2")["valid_destinations"][0]
    ok, result = eng._process_semantic_action({
        "action": "commit_move_plan", "unitId": "2", "plan": _plan_to("2", dest),
    })
    assert ok, result
    assert not desperate_escape_mode_selected(gs, "2"), "verrou de B non libéré"
    assert desperate_escape_mode_selected(gs, "1"), (
        "le verrou d'A a été écrasé par la sélection de B : A rejouerait ses hazards"
    )

    # Reprise d'A : mode encore retenu, aucun nouveau hazard possible.
    gs["active_movement_unit"] = "1"
    ok, payload = movement_unit_execution_loop(gs, "1")
    assert ok and payload["fall_back_mode"] == "desperate_escape"
    with patch(_HAZARD, side_effect=_no_wounds) as hazard_again:
        ok, refusal = eng._process_semantic_action({"action": "hazard_confirm", "unitId": "1"})
    assert ok is False and refusal["error"] == "hazard_already_resolved"
    assert hazard_again.call_count == 0


def test_pvp_hazard_confirm_refuses_an_unengaged_squad():
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _disengage(gs)

    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, payload = eng._process_semantic_action({"action": "hazard_confirm", "unitId": "1"})

    assert ok is False
    assert "not engaged" in payload["error"]
    assert hazard.call_count == 0
    assert not desperate_escape_mode_selected(gs, "1")


def _pvp_desperate_escape_then_commit(eng: W40KEngine) -> Dict[str, Any]:
    """Sélectionne Desperate Escape puis commet un fall-back par le plan par-figurine PvP."""
    dest = _pvp_select_desperate_escape(eng)["valid_destinations"][0]
    ok, result = eng._process_semantic_action({
        "action": "commit_move_plan", "unitId": "1", "plan": _plan_to("1", dest),
    })
    assert ok, f"commit refusé : {result}"
    return result


def test_pvp_plan_commit_after_desperate_escape_rolls_battle_shock_in_move_phase():
    """09.07 AFTER MOVING : l'escouade saine fait un jet de battle-shock APRÈS son mouvement. La
    ligne est journalisée en phase MOVE (pas `command` en dur), après la ligne de mouvement."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state

    result = _pvp_desperate_escape_then_commit(eng)

    assert result["action"] == "flee"
    shocks = _logs_of_type(gs, "battle_shock")
    assert len(shocks) == 1, f"un jet 01.07 attendu, obtenu {shocks}"
    assert shocks[0]["phase"] == "move"
    assert str(shocks[0]["unitId"]) == "1"
    logs = gs["action_logs"]
    assert logs.index(_logs_of_type(gs, "move")[-1]) < logs.index(shocks[0]), (
        "le jet doit SUIVRE la ligne de mouvement"
    )
    assert not desperate_escape_mode_selected(gs, "1"), "verrou non purgé par end_activation"


def test_pvp_ordered_retreat_commit_rolls_nothing():
    """Témoin : sans sélection, un fall-back reste un Ordered Retreat — ni hazard ni battle-shock."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _open_exit(gs)
    gs["active_movement_unit"] = "1"
    ok, payload = movement_unit_execution_loop(gs, "1")
    assert ok and payload["fall_back_mode"] == "ordered_retreat"
    assert payload["valid_destinations"], "témoin : un Ordered Retreat possible"
    dest = payload["valid_destinations"][0]

    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, result = eng._process_semantic_action({
            "action": "commit_move_plan", "unitId": "1", "plan": _plan_to("1", dest),
        })

    assert ok, result
    assert result["action"] == "flee"
    assert hazard.call_count == 0
    assert _logs_of_type(gs, "battle_shock") == []


def test_pvp_already_shocked_squad_does_not_retest_after_desperate_escape():
    """« If your unit is NOT battle-shocked » : une escouade déjà shockée ne rejoue pas le test."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    _unit(gs, "1")["battle_shocked"] = True

    _pvp_desperate_escape_then_commit(eng)

    assert _logs_of_type(gs, "battle_shock") == []


def test_pvp_quick_move_after_desperate_escape_rolls_battle_shock():
    """Jumeau du commit par-figurine : le commit rapide à l'ancre (action `move`)."""
    eng = _engine_encircled(gym=False)
    gs = eng.game_state
    dest = _pvp_select_desperate_escape(eng)["valid_destinations"][0]

    ok, result = eng._process_semantic_action({
        "action": "move", "unitId": "1", "destCol": dest[0], "destRow": dest[1],
    })

    assert ok, f"commit rapide refusé : {result}"
    assert result["action"] == "flee"
    shocks = _logs_of_type(gs, "battle_shock")
    assert len(shocks) == 1 and shocks[0]["phase"] == "move"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Siège piloté par le modèle : point de choix AVANT le pool
# ─────────────────────────────────────────────────────────────────────────────


def test_gym_mask_arms_the_choice_before_building_the_pool_and_opens_only_it():
    eng = _engine_encircled()
    gs = eng.game_state

    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)

    assert _open_actions(mask) == [CHOICE_BASE, CHOICE_BASE + 1]
    assert eligible == []
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "fall_back_mode"
    assert decision["unit_id"] == "1"
    assert [o["declines"] for o in decision["options"]] == [False, True]
    assert decision["options"][1]["label"] == "Ordered Retreat", "le refus EST Ordered Retreat"


def test_gym_rebuilding_the_mask_does_not_stack_a_second_decision():
    eng = _engine_encircled()
    gs = eng.game_state
    first, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    second, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert _open_actions(first) == _open_actions(second)


@pytest.mark.parametrize("shocked", [True, False])
def test_gym_no_question_when_the_mode_is_imposed_or_the_squad_is_unengaged(shocked):
    eng = _engine_encircled()
    gs = eng.game_state
    if shocked:
        _unit(gs, "1")["battle_shocked"] = True
    else:
        _disengage(gs)

    assert fall_back_mode_decision_is_due(gs, "1") is False
    assert arm_fall_back_mode_decision(gs, "1") is None


def test_gym_a_human_seat_is_never_asked_it_has_the_button():
    eng = _engine_encircled(gym=False)
    assert fall_back_mode_decision_is_due(eng.game_state, "1") is False


def test_gym_the_enemy_is_never_asked_during_your_turn():
    eng = _engine_encircled()
    gs = eng.game_state
    gs["current_player"] = 2
    assert fall_back_mode_decision_is_due(gs, "1") is False


def test_gym_desperate_escape_answer_opens_cells_through_the_encirclement():
    """Le choix RÉPONDU, le masque rouvre les cellules — celles de Desperate Escape, à travers
    l'anneau d'ennemis. Sans le verrou dans les caches (fingerprint spatial, clé de la carte de
    cellules), la carte d'Ordered Retreat (vide) était resservie."""
    eng = _engine_encircled()
    gs = eng.game_state
    eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    fp_before = _move_spatial_cache(gs)["fp"]

    apply_fall_back_mode_decision(gs, "1", desperate_escape=True)

    assert desperate_escape_mode_selected(gs, "1")
    assert fall_back_mode_resolved(gs, "1")
    assert read_pending_agent_decision(gs) is None
    assert _move_spatial_cache(gs)["fp"] != fp_before, "le verrou doit entrer dans le fingerprint"
    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert [str(u["id"]) for u in eligible] == ["1"]
    assert any(a in MOVE_CELLS for a in _open_actions(mask)), (
        "aucune cellule ouverte après Desperate Escape — l'encerclement n'a pas été traversé"
    )
    assert fall_back_mode_decision_is_due(gs, "1") is False, "la question se reposerait"


def test_gym_cell_map_cached_before_the_answer_is_not_reused_after_desperate_escape():
    """La carte de cellules est mémoïsée par fingerprint géométrique (`_squad_move_pool_cache`),
    et le choix d'activation en bâtit une TRANSITOIRE avant tout point de choix. Le verrou ne
    déplace aucune figurine : sans lui dans la clé, la carte d'Ordered Retreat (vide) était
    resservie après le choix Desperate Escape."""
    from engine.phase_handlers.shared_utils import build_squad_move_cell_map

    eng = _engine_encircled()
    gs = eng.game_state
    assert build_squad_move_cell_map(gs, "1", None) == {}, "témoin : Ordered Retreat vide"

    _gym_answer(eng, desperate_escape=True)

    assert build_squad_move_cell_map(gs, "1", None), (
        "carte d'Ordered Retreat resservie : le verrou de mode n'entre pas dans la clé du cache"
    )


def test_anchor_pool_lifts_the_engagement_band_in_desperate_escape_like_the_validation():
    """Jumeau du pool par-figurine et de `build_move_transit_blocked` : avec le toggle
    `can_move_through_enemy_engagement_zone` à False, la bande d'EZ bloque le transit en
    Ordered Retreat mais pas en Desperate Escape. Le pool d'ancre ne lisait que le toggle."""
    from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool

    eng = _engine_encircled()
    gs = eng.game_state
    gs["config"]["move"]["can_move_through_enemy_engagement_zone"] = False
    assert movement_build_valid_destinations_pool(gs, "1", read_only=True) == []

    _gym_answer(eng, desperate_escape=True)

    pool = movement_build_valid_destinations_pool(gs, "1", read_only=True)
    assert pool, "la bande d'EZ bloque encore le transit du pool d'ancre en Desperate Escape"
    assert all(calculate_hex_distance(*_CENTER, c, r) >= 3 for c, r in pool)


def test_gym_ordered_retreat_answer_leaves_a_trace_and_no_cell():
    """« Ordered Retreat » n'est pas un non-événement : la trace empêche de reposer la question,
    et le masque sert le pool d'Ordered Retreat — vide ici, donc WAIT seul."""
    eng = _engine_encircled()
    gs = eng.game_state

    _gym_answer(eng, desperate_escape=False)

    assert not desperate_escape_mode_selected(gs, "1")
    assert fall_back_mode_resolved(gs, "1")
    assert fall_back_mode_of(gs, "1") == "ordered_retreat"
    assert fall_back_mode_decision_is_due(gs, "1") is False
    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert [str(u["id"]) for u in eligible] == ["1"]
    assert not any(a in MOVE_CELLS for a in _open_actions(mask))
    assert read_pending_agent_decision(gs) is None


@pytest.mark.parametrize("option_index, expected", [(0, True), (1, False)])
def test_gym_the_engine_routes_the_choice_action(option_index, expected):
    """`CHOICE_i` doit ATTEINDRE l'application sur un vrai `W40KEngine` (décodage + dispatch)."""
    eng = _engine_encircled()
    gs = eng.game_state
    eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)

    semantic = eng.action_decoder.convert_squad_action(CHOICE_BASE + option_index, gs)
    assert semantic == {"action": "agent_decision", "option_index": option_index}
    ok, result = eng._process_squad_action(semantic)

    assert ok is True
    assert result["decision_type"] == "fall_back_mode"
    assert result["unitId"] == "1"
    assert result["desperateEscape"] is expected
    assert desperate_escape_mode_selected(gs, "1") is expected
    assert read_pending_agent_decision(gs) is None


def test_gym_commit_after_desperate_escape_rolls_hazard_then_battle_shock():
    """Chaîne complète du siège modèle : choix → hazard au commit → mouvement → battle-shock,
    la ligne 01.07 après la ligne de mouvement et en phase MOVE ; `fleeMode` = desperate_escape."""
    eng = _engine_encircled()
    gs = eng.game_state
    _gym_answer(eng, desperate_escape=True)
    mask, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    cell = next(a for a in _open_actions(mask) if a in MOVE_CELLS)
    semantic = eng.action_decoder.convert_squad_action(cell, gs)
    assert semantic["action"] == "squad_fall_back", semantic

    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, result = eng._process_squad_action(semantic)

    assert ok, result
    assert hazard.call_count == 1
    moves = _logs_of_type(gs, "move")
    assert len(moves) == 1 and moves[0]["fleeMode"] == "desperate_escape"
    shocks = _logs_of_type(gs, "battle_shock")
    assert len(shocks) == 1 and shocks[0]["phase"] == "move"
    logs = gs["action_logs"]
    assert logs.index(moves[0]) < logs.index(shocks[0])
    assert FALL_BACK_MODES_KEY not in gs, "mode non purgé par end_activation"


def test_gym_commit_without_selection_stays_ordered_retreat():
    """Témoin : `_process_squad_action` sans verrou (cf. test_gym_fall_back_not_battleshocked_
    keeps_ordered_retreat) — aucun hazard, aucun battle-shock."""
    eng = _engine_encircled()
    gs = eng.game_state
    _open_exit(gs)
    _gym_answer(eng, desperate_escape=False)
    mask, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    cell = next(a for a in _open_actions(mask) if a in MOVE_CELLS)

    with patch(_HAZARD, side_effect=_no_wounds) as hazard:
        ok, result = eng._process_squad_action(eng.action_decoder.convert_squad_action(cell, gs))

    assert ok, result
    assert hazard.call_count == 0
    assert _logs_of_type(gs, "move")[0]["fleeMode"] == "ordered_retreat"
    assert _logs_of_type(gs, "battle_shock") == []


def test_gym_bot_seat_always_keeps_ordered_retreat():
    """Baseline des bots : le moteur imposait Ordered Retreat ; le bot le garde (jamais un tirage)."""
    from ai.env_wrappers import bot_action_for_pending_choice

    eng = _engine_encircled()
    gs = eng.game_state
    mask, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)

    action = bot_action_for_pending_choice(gs, mask, "test")

    decision = read_pending_agent_decision(gs)
    assert decision is not None
    ordered_retreat = next(i for i, o in enumerate(decision["options"]) if o["declines"])
    assert action == CHOICE_BASE + ordered_retreat


def test_fall_back_mode_of_reads_the_lock_then_the_engagement():
    eng = _engine_encircled()
    gs = eng.game_state
    assert fall_back_mode_of(gs, "1") == "ordered_retreat"
    assert arm_fall_back_mode_decision(gs, "1") is not None
    apply_fall_back_mode_decision(gs, "1", desperate_escape=True)
    assert fall_back_mode_of(gs, "1") == "desperate_escape"
    # L'ennemi 10 est engagé avec l'escouade 1, sans mode retenu : Ordered Retreat par défaut.
    assert fall_back_mode_of(gs, "10") == "ordered_retreat"
    _disengage(gs)
    assert fall_back_mode_of(gs, "10") is None
