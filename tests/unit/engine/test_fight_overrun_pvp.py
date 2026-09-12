"""Overrun fight 12.06 en flux manuel PvP — pile-in ADDITIONNEL par-figurine.

PDF 12 (`12 Fights phase.pdf`) : « OVERRUN FIGHT 12.06 — ELIGIBLE IF: Your unit is unengaged, or
was unengaged at the start of the Fight step but became engaged during the Fight phase. EFFECT:
Your unit can make one additional pile-in move, then fights as described in Making Attacks (04). »
12.03 BEFORE MOVING : « If your unit is engaged, select every enemy unit it is engaged with.
Otherwise, select one or more enemy units within 5" of your unit. » AFTER : « Your unit must be
engaged. »

Avant ce lot, `_fight_v11_manual_step` n'exécutait le pile-in additionnel que si le clic-cible
portait `fight_type == "overrun"`, jamais émis par le front : une unité qui avait chargé et perdu
sa cible n'avait que « passer ». Désormais l'overrun est une action séparée (`overrun_pile_in`),
AVANT le choix de cible, qui ouvre le MÊME plan par-figurine que le pile-in groupé ; son commit
rend la main au combat de l'unité, dont le pool de cibles est recalculé.

Chemins verrouillés sur un MOTEUR RÉEL via `execute_semantic_action` (point d'entrée du front).
"""
from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.fight_handlers import (
    OVERRUN_PILE_IN_DONE_KEY,
    OVERRUN_PILE_IN_UNIT_KEY,
    fight_v11_enter_fight_step,
    fight_v11_start,
)
from engine.game_utils import require_unit_by_id
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)
from tests.unit.engine._state_builders import squad_model_cells


def _engine(units: List[Dict[str, Any]], charged: List[str]) -> W40KEngine:
    """Partie PvP hot-seat servie par l'API, entrée directement dans l'étape FIGHT (12.04) :
    le snapshot `engaged_at_fight_step_start` est pris ICI, sur les positions déclarées."""
    eng = _make_engine(_base_config(units))
    gs = eng.game_state
    gs["gym_training_mode"] = False
    gs["player_types"] = {"1": "human", "2": "human"}
    gs["current_mode_code"] = "pvp"
    eng.current_mode_code = "pvp"
    gs["current_player"] = 1
    gs["phase"] = "fight"
    gs["units_charged"] = set(charged)
    fight_v11_start(gs)
    fight_v11_enter_fight_step(gs)
    return eng


def _move_logs(gs: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [e for e in gs["action_logs"] if e.get("type") == kind]


# ---------------------------------------------------------------------------
# Unité qui a chargé, cible détruite : sans cible avant le pile-in, une cible après.
# ---------------------------------------------------------------------------

def test_overrun_pile_in_puis_combat_pour_une_unite_sans_cible():
    """ROUGE avant le lot : `overrun_pile_in` inconnu → « action ignorée », l'unité reste sans cible."""
    eng = _engine([
        _unit_cfg(1, 1, 20, 20),   # a chargé, sa cible est morte : non engagée
        _unit_cfg(2, 2, 23, 20),   # ennemi à 3" (≤ 5"), atteignable par un pile-in de 3"
    ], charged=["1"])
    gs = eng.game_state
    origin = squad_model_cells(gs, "1")

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["active_fight_unit"] == "1", out
    assert out["valid_targets"] == [], "sans pile-in additionnel, aucune cible (état d'avant le lot)"
    assert out["overrun_eligible"] is True, out

    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert ok is True, out
    assert out["pile_in_model_move"] is True and out["overrun_pile_in"] is True, out
    assert out["fight_subphase"] == "fight", "le plan s'ouvre DANS l'étape FIGHT, pas en 12.02"
    assert out["pile_in_targets"] == ["2"], "non engagée → cibles = ennemis ≤ 5\" (12.03 BEFORE)"
    assert out["eligible_models"] == ["1#0"]
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "1"

    plan = eng.execute_semantic_action(
        {"action": "pile_in_autoplace", "unitId": "1", "targetId": "2"}
    )[1]["plan"]
    ok, out = eng.execute_semantic_action(
        {"action": "commit_pile_in_plan", "unitId": "1", "plan": plan}
    )
    assert ok is True, out
    # Le commit rend la main au COMBAT de l'unité, toujours active, avec ses cibles recalculées.
    assert out["action"] == "wait" and out["fight_subphase"] == "fight", out
    assert out["active_fight_unit"] == "1" and out["valid_targets"] == ["2"], out
    assert out["overrun_eligible"] is False, "« one additional pile-in move » : un seul"
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs and gs[OVERRUN_PILE_IN_DONE_KEY] == {"1"}
    assert squad_model_cells(gs, "1") != origin, "les figurines ont bougé"
    assert "1" not in gs["units_selected_to_fight"], "pas encore combattu"
    logs = _move_logs(gs, "overrun_pile_in")
    assert len(logs) == 1 and logs[0]["unitId"] == "1", logs
    assert "OVERRUN PILED IN" in logs[0]["message"]
    assert _move_logs(gs, "pile_in") == [], "ce n'est pas le pile-in groupé 12.02"

    # Un second overrun est refusé : le pile-in additionnel est unique par sélection.
    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert ok is False and out["error"] == "overrun_not_eligible", out

    # Elle combat depuis sa nouvelle position (clic-cible → sélection 12.04 enregistrée).
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True, out
    assert "1" in gs["units_selected_to_fight"]


# ---------------------------------------------------------------------------
# Abandon du pile-in additionnel : l'unité reste active, rien ne bouge, pas « passée ».
# ---------------------------------------------------------------------------

def test_abandon_du_pile_in_additionnel_laisse_l_unite_active():
    eng = _engine([
        _unit_cfg(1, 1, 20, 20),
        _unit_cfg(2, 2, 23, 20),
    ], charged=["1"])
    gs = eng.game_state
    origin = squad_model_cells(gs, "1")
    eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "1"

    # Clic droit / Cancel pendant le plan = renoncer au move, PAS passer l'unité.
    ok, out = eng.execute_semantic_action({"action": "skip", "unitId": "1"})
    assert ok is True, out
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs
    assert out["active_fight_unit"] == "1" and out["valid_targets"] == [], out
    assert out["overrun_eligible"] is True, "renoncer n'épuise pas le droit au pile-in additionnel"
    assert squad_model_cells(gs, "1") == origin
    assert "1" not in gs["units_selected_to_fight"]

    # Hors plan, le même clic droit reprend son sens d'avant : passer une unité sans cible.
    ok, out = eng.execute_semantic_action({"action": "skip", "unitId": "1"})
    assert ok is True, out
    assert "1" in gs["units_selected_to_fight"] and gs["active_fight_unit"] is None


# ---------------------------------------------------------------------------
# Refus : unité engagée depuis le début de l'étape → normal fight seulement (12.05).
# ---------------------------------------------------------------------------

def test_overrun_refuse_pour_une_unite_engagee_au_debut_de_l_etape():
    eng = _engine([
        _unit_cfg(1, 1, 20, 20),
        _unit_cfg(2, 2, 21, 20),   # adjacent : engagée AVANT le snapshot
    ], charged=[])
    gs = eng.game_state
    assert gs["engaged_at_fight_step_start"]["1"] is True
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["overrun_eligible"] is False, out
    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert ok is False and out["error"] == "overrun_not_eligible", out
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs
    assert gs["active_fight_unit"] == "1", "le refus ne touche pas l'activation"


# ---------------------------------------------------------------------------
# Second cas 12.06 : devenue engagée pendant la phase → cibles = ENGAGÉES seulement (12.03).
# ---------------------------------------------------------------------------

def test_unite_devenue_engagee_cible_ses_engagees_pas_les_ennemis_a_5_pouces():
    eng = _engine([
        _unit_cfg(1, 1, 20, 20),
        _unit_cfg(2, 2, 21, 20),   # adjacent → engagée maintenant
        _unit_cfg(3, 2, 20, 23),   # à 3", non engagée
    ], charged=[])
    gs = eng.game_state
    # Devenue engagée PENDANT la phase : le snapshot la dit non engagée au début de l'étape.
    gs["engaged_at_fight_step_start"]["1"] = False

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["overrun_eligible"] is True, out
    assert set(out["valid_targets"]) == {"2"}
    # Une déclaration faite AVANT le move est caduque (les figurines bougent, 04.02 change).
    ok, out = eng.execute_semantic_action(
        {"action": "squad_fight_assign", "unitId": "1", "modelId": "1#0", "targetId": "2"}
    )
    assert ok is True and len(out["declarations"]) == 1, out
    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert ok is True, out
    assert out["pile_in_targets"] == ["2"], (
        "engagée → « select every enemy unit it is engaged with », l'ennemi à 5\" n'est pas cible"
    )
    assert "1" not in gs["pending_squad_fight_intents"], "déclarations d'avant le move purgées"



# ---------------------------------------------------------------------------
# New Foes to Face (12.08 AFTER) : un New Foe dont l'engageur est mort avant sa sélection est
# DÉSENGAGÉ → overrun 12.06 (« Your unit is unengaged »), comme le gym et l'auto lui font.
# Avant ce lot, la branche New Foes du flux manuel ne connaissait pas `overrun_pile_in` : le
# New Foe était « sélectionné sans attaque ».
# ---------------------------------------------------------------------------

def _engine_at_new_foes_engager_dead() -> W40KEngine:
    """U (P1, unité 1) a consolidé Engaging et finit engagée avec X, Y, W (P2, jamais
    sélectionnées : non engagées au début de l'étape, pas de charge) → New Foes = [X, Y, W],
    sélecteur P2. X (2) est sélectionnée en premier et détruit U. Reste Y (3) et W (5),
    désengagées ; Z (4, P1) est à 4" de Y (≤ 5", hors engagement) : cible d'overrun."""
    from engine.phase_handlers.fight_handlers import (
        _fight_v11_register_selection,
        fight_v11_consolidation_freeze_new_foes,
        fight_v11_enter_consolidate,
    )
    from engine.phase_handlers.shared_utils import destroy_model, place_model_at_effective_level

    eng = _engine([
        _unit_cfg(1, 1, 20, 20),   # U : a chargé, cible morte → sélectionnée sans attaque
        _unit_cfg(2, 2, 25, 20),   # X : à 5" de U au début de l'étape (non engagée)
        _unit_cfg(3, 2, 27, 20),   # Y : idem
        _unit_cfg(5, 2, 26, 21),   # W : idem
        _unit_cfg(4, 1, 31, 20),   # Z : à 4" de Y, hors engagement
    ], charged=["1"])
    gs = eng.game_state
    assert gs["engaged_at_fight_step_start"] == {"1": False, "2": False, "3": False, "5": False, "4": False}
    _fight_v11_register_selection(gs, "1")
    fight_v11_enter_consolidate(gs)
    # Consolidation Engaging de U (12.08) : U finit adjacente à X, Y et W.
    place_model_at_effective_level(gs, "1#0", 26, 20, int(gs["models_cache"]["1#0"]["level"]))
    gs["consolidation_done"].add("1")
    assert set(fight_v11_consolidation_freeze_new_foes(gs, require_unit_by_id(gs, "1"))) == {"2", "3", "5"}
    assert gs["consolidation_new_foes_selector"] == 2
    # X combat en premier et détruit U.
    _fight_v11_register_selection(gs, "2")
    destroy_model(gs, "1#0", "combat")
    gs["active_fight_unit"] = None
    return eng


def _new_foes_state(eng: W40KEngine) -> Dict[str, Any]:
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "3"})
    assert ok is True, out
    return out


def test_new_foe_desengage_overrun_puis_combat_et_verrou():
    """ROUGE avant le lot : `overrun_pile_in` inconnu de la branche New Foes → état inchangé,
    `overrun_eligible` absent du payload New Foes."""
    eng = _engine_at_new_foes_engager_dead()
    gs = eng.game_state
    origin = squad_model_cells(gs, "3")

    out = _new_foes_state(eng)
    assert out["fight_subphase"] == "consolidate" and set(out["consolidation_new_foes"]) == {"3", "5"}, out
    assert out["active_fight_unit"] == "3" and out["valid_targets"] == [], out
    assert out["overrun_eligible"] is True, "New Foe désengagé (engageur mort) → 12.06"

    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "3"})
    assert ok is True, out
    assert out["pile_in_model_move"] is True and out["overrun_pile_in"] is True, out
    assert out["fight_subphase"] == "consolidate", "le plan s'ouvre DANS l'attente New Foes"
    assert out["pile_in_targets"] == ["4"], "désengagée → cibles = ennemis ≤ 5\" (12.03 BEFORE)"
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "3"

    plan = eng.execute_semantic_action(
        {"action": "pile_in_autoplace", "unitId": "3", "targetId": "4"}
    )[1]["plan"]
    ok, out = eng.execute_semantic_action(
        {"action": "commit_pile_in_plan", "unitId": "3", "plan": plan}
    )
    assert ok is True, out
    # Le commit rend la main au combat du New Foe, toujours actif, cibles recalculées.
    assert out["fight_subphase"] == "consolidate" and set(out["consolidation_new_foes"]) == {"3", "5"}, out
    assert out["active_fight_unit"] == "3" and out["valid_targets"] == ["4"], out
    assert out["overrun_eligible"] is False, "« one additional pile-in move » : un seul"
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs and "3" in gs[OVERRUN_PILE_IN_DONE_KEY]
    assert squad_model_cells(gs, "3") != origin
    logs = _move_logs(gs, "overrun_pile_in")
    assert len(logs) == 1 and logs[0]["unitId"] == "3", logs

    # VERROU : le move fait partie de la sélection de Y — l'adversaire ne peut plus lui préférer W.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "5"})
    assert ok is True and out["active_fight_unit"] == "3", out
    assert "3" not in gs["units_selected_to_fight"]

    # Y combat Z depuis sa nouvelle position (clic-cible → sélection 12.04 enregistrée).
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "3", "targetId": "4"})
    assert ok is True, out
    assert "3" in gs["units_selected_to_fight"]


def test_new_foe_renonce_au_pile_in_additionnel_reste_actif():
    eng = _engine_at_new_foes_engager_dead()
    gs = eng.game_state
    origin = squad_model_cells(gs, "3")
    _new_foes_state(eng)
    eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "3"})
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "3"

    ok, out = eng.execute_semantic_action({"action": "skip", "unitId": "3"})
    assert ok is True, out
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs
    assert out["active_fight_unit"] == "3" and out["valid_targets"] == [], out
    assert out["overrun_eligible"] is True, "renoncer n'épuise pas le droit au pile-in additionnel"
    assert squad_model_cells(gs, "3") == origin
    assert "3" not in gs["units_selected_to_fight"]
    # Sans overrun, le New Foe sans cible reste « sélectionné sans attaque » (clic sur le plateau).
    ok, out = eng.execute_semantic_action({"action": "left_click", "unitId": "3"})
    assert ok is True, out
    assert "3" in gs["units_selected_to_fight"] and gs["active_fight_unit"] is None
    assert squad_model_cells(gs, "3") == origin


def test_new_foe_sans_ennemi_a_5_pouces_n_a_pas_d_overrun_utile():
    """Éligible 12.06 mais aucun ennemi ≤ 5" : le plan n'a pas de cible et ne peut pas être
    validé (AFTER « Your unit must be engaged ») — le renoncement est la seule issue."""
    from engine.phase_handlers.shared_utils import place_model_at_effective_level

    eng = _engine_at_new_foes_engager_dead()
    gs = eng.game_state
    place_model_at_effective_level(gs, "4#0", 34, 20, int(gs["models_cache"]["4#0"]["level"]))  # Z à 7" de Y
    out = _new_foes_state(eng)
    assert out["overrun_eligible"] is True and out["valid_targets"] == []
    ok, out = eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "3"})
    assert ok is True and out["pile_in_targets"] == [] and out["can_validate"] is False, out
    ok, out = eng.execute_semantic_action(
        {"action": "commit_pile_in_plan", "unitId": "3", "plan": []}
    )
    assert ok is True and out["pile_in_model_move"] is True, "plan refusé → aperçu renvoyé"
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "3" and "3" not in gs[OVERRUN_PILE_IN_DONE_KEY]


# ---------------------------------------------------------------------------
# VERROU (dispatch FIGHT) : après le commit du pile-in additionnel, le move fait partie de la
# sélection de l'unité (« one additional pile-in move, THEN fights ») — le joueur ne peut plus
# lui préférer une autre unité tant qu'elle n'a pas combattu (même verrou que l'Exhortation).
# ---------------------------------------------------------------------------

def test_apres_overrun_commite_le_joueur_ne_peut_pas_changer_d_unite():
    eng = _engine([
        _unit_cfg(1, 1, 20, 20),   # a chargé, cible morte
        _unit_cfg(3, 1, 20, 30),   # a chargé aussi, loin de tout
        _unit_cfg(2, 2, 23, 20),   # à 3" de l'unité 1
    ], charged=["1", "3"])
    gs = eng.game_state
    eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    plan = eng.execute_semantic_action(
        {"action": "pile_in_autoplace", "unitId": "1", "targetId": "2"}
    )[1]["plan"]
    ok, out = eng.execute_semantic_action({"action": "commit_pile_in_plan", "unitId": "1", "plan": plan})
    assert ok is True and out["active_fight_unit"] == "1" and out["valid_targets"] == ["2"], out

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "3"})
    assert ok is True and out["active_fight_unit"] == "1", out
    # Passer l'unité 1 est refusé aussi : elle a une cible (obligation de combattre, encart 12).
    ok, out = eng.execute_semantic_action({"action": "skip", "unitId": "1"})
    assert ok is True and out["active_fight_unit"] == "1", out
    assert "1" not in gs["units_selected_to_fight"]
    # Une fois qu'elle a combattu, l'autre unité redevient activable.
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True and "1" in gs["units_selected_to_fight"]
