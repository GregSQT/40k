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
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)


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


def _positions(gs: Dict[str, Any], uid: str) -> Dict[str, tuple]:
    return {
        m: (int(gs["models_cache"][m]["col"]), int(gs["models_cache"][m]["row"]))
        for m in gs["squad_models"][uid]
    }


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
    origin = _positions(gs, "1")

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
    assert _positions(gs, "1") != origin, "les figurines ont bougé"
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
    origin = _positions(gs, "1")
    eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    eng.execute_semantic_action({"action": "overrun_pile_in", "unitId": "1"})
    assert gs[OVERRUN_PILE_IN_UNIT_KEY] == "1"

    # Clic droit / Cancel pendant le plan = renoncer au move, PAS passer l'unité.
    ok, out = eng.execute_semantic_action({"action": "skip", "unitId": "1"})
    assert ok is True, out
    assert OVERRUN_PILE_IN_UNIT_KEY not in gs
    assert out["active_fight_unit"] == "1" and out["valid_targets"] == [], out
    assert out["overrun_eligible"] is True, "renoncer n'épuise pas le droit au pile-in additionnel"
    assert _positions(gs, "1") == origin
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
