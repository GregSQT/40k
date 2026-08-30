"""Re-sélection de cible CC quand la cible désignée meurt PENDANT l'activation.

Chemin de production : l'agent joue `squad_fight` avec un `target_slot`, puis l'Exhortation de
Rage (06 Primitive D, `mortal_wounds_on_fight_activation`) tire son D6 et tue cette cible. Le
masque ne pouvait pas anticiper le D6 : `target_slot` désigne un mort. Si le pile-in overrun
12.06 rend d'autres ennemis frappables, la cible est REDEMANDÉE à l'agent (V11 §9 P3-1, « la
cible vient de l'ACTION ») au lieu d'être choisie par le moteur — sauf s'il n'en reste qu'une,
auquel cas il n'y a aucun choix à poser.

Règle : PDF `12 Fights pahse` 12.06 « ELIGIBLE IF: Your unit is unengaged […] EFFECT: Your unit
can make one additional pile-in move, then fights as described in Making Attacks (04) » —
l'escouade FRAPPE après le rapprochement, le combat à vide serait faux.

Verrou ROUGE/VERT : avant le fix, ce chemin levait
`ValueError: _continue_squad_fight: slot 5 -> None hors pool 12.05 ['4'] pour squad 101`.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import engine.phase_handlers.fight_handlers as fh
import engine.phase_handlers.shared_utils as su
import engine.w40k_core as wcore
from engine.action_decoder import PENDING_FIGHT_TARGET_KEY, PENDING_FIGHT_WEAPON_KEY
from engine.phase_handlers.shared_utils import SQUAD_ACTION_FIGHT_SLOT_BASE

from smoke_t5_bare import MELEE_SCENARIO


_SQUAD = "101"


# ---------------------------------------------------------------------------
# Harnais : moteur minimal portant les seules méthodes du chemin testé
# ---------------------------------------------------------------------------


class _FakeEngine:
    _continue_squad_fight_after_selection = (
        wcore.W40KEngine._continue_squad_fight_after_selection
    )
    _fight_target_after_designated_death = (
        wcore.W40KEngine._fight_target_after_designated_death
    )
    _fight_resolve_with_target = wcore.W40KEngine._fight_resolve_with_target
    _process_squad_action = wcore.W40KEngine._process_squad_action

    def __init__(self, gs: Dict[str, Any]) -> None:
        self.game_state = gs
        self.moves: List[Any] = []

    def _gym_commit_fight_move(self, gs, squad_id, plan, reason):  # noqa: ANN001
        self.moves.append((squad_id, reason))

    def _fight_v11_gym_settle(self) -> None:
        pass

    # --- stubs du préambule de `_process_squad_action` ---
    def _initialize_rule_choice_runtime_state(self) -> None:
        pass

    def _reject_action_while_faction_decision_pending(self, semantic):  # noqa: ANN001
        return None


def _gs() -> Dict[str, Any]:
    return {
        "phase": "fight",
        "game_over": False,
        "active_rule_choice_prompt": None,
        "units_cache": {_SQUAD: {"player": 1}},
        "models_cache": {"atk#0": {"squad_id": _SQUAD, "player": 1}},
        "squad_models": {_SQUAD: ["atk#0"]},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
    }


def _patch_overrun(
    monkeypatch: pytest.MonkeyPatch, slots: List[Optional[str]]
) -> None:
    """Escouade désengagée dont le pile-in overrun 12.06 réussit ; `slots` = mapping ennemi.

    Toutes les escouades encore présentes dans le mapping sont frappables après le
    rapprochement (`_model_can_fight_target` → True), ce qui reproduit la branche `_did_overrun`.
    """
    monkeypatch.setattr(fh, "_fight_v11_engaged_now", lambda gs, u: False)
    monkeypatch.setattr(su, "_fight_overrun_pile_in_plan", lambda gs, sid: [("atk#0", 0, 0, 0)])
    monkeypatch.setattr(su, "get_enemy_slot_mapping", lambda gs, player: list(slots))
    monkeypatch.setattr(fh, "_model_can_fight_target", lambda gs, m, uid, eid: True)
    monkeypatch.setattr(su, "squad_fight_restart_activation", lambda gs, sid: None)
    monkeypatch.setattr(wcore, "require_unit_by_id", lambda gs, uid: {"id": uid, "player": 1})
    monkeypatch.setattr(
        fh, "fight_weapon_eligible_slots", lambda gs, sid, tid: {0: "chainsword"}
    )


# ---------------------------------------------------------------------------
# 1. Cible désignée morte + PLUSIEURS cibles frappables → la cible est redemandée
# ---------------------------------------------------------------------------


def test_designated_target_dead_two_targets_arms_reselect(monkeypatch):
    """ROUGE avant le fix : ValueError « slot 0 -> None hors pool 12.05 ».

    Slot 0 = cible désignée, morte de l'Exhortation. Slots 1 et 2 sont devenus frappables par
    le pile-in overrun : deux choix réels, donc l'agent doit rejouer un FIGHT_SLOT.
    """
    _patch_overrun(monkeypatch, [None, "A", "B"])
    eng = _FakeEngine(_gs())

    ok, result = eng._continue_squad_fight_after_selection(_SQUAD, target_slot=0)

    assert ok is True
    assert result["waiting_for_target_select"] is True
    assert result["squad_id"] == _SQUAD
    pending = eng.game_state[PENDING_FIGHT_TARGET_KEY]
    assert pending["squad_id"] == _SQUAD
    assert pending["slot_to_target"] == {1: "A", 2: "B"}
    assert PENDING_FIGHT_WEAPON_KEY not in eng.game_state, (
        "l'arme ne se choisit qu'APRÈS la cible"
    )
    assert eng.moves == [(_SQUAD, "overrun_pile_in")], "le pile-in overrun 12.06 est commité"


# ---------------------------------------------------------------------------
# 2. Cible désignée morte + UNE seule cible → aucun choix posé
# ---------------------------------------------------------------------------


def test_designated_target_dead_single_target_resolves_directly(monkeypatch):
    """Une seule cible frappable : poser une décision à une option serait du bruit.

    Miroir exact de `_check_and_trigger_exhortation_de_rage`, qui applique directement quand
    `len(engaged) == 1`.
    """
    _patch_overrun(monkeypatch, [None, "A", None])
    eng = _FakeEngine(_gs())

    ok, result = eng._continue_squad_fight_after_selection(_SQUAD, target_slot=0)

    assert ok is True
    assert PENDING_FIGHT_TARGET_KEY not in eng.game_state
    assert result["waiting_for_weapon_select"] is True
    assert result["target_squad_id"] == "A"


# ---------------------------------------------------------------------------
# 3. Cibles légales mais aucun slot mappé → refus explicite
# ---------------------------------------------------------------------------


def test_targets_without_mapped_slot_raise(monkeypatch):
    """Des cibles INFRAPPABLES faute de slot ne doivent pas devenir un combat à vide silencieux.

    Même refus que le masque (`[SLOTS] … cible(s) infrappable(s)`), côté commit.
    """
    _patch_overrun(monkeypatch, [None, "A"])
    # Le pool contient une cible qui n'occupe aucun slot du mapping.
    monkeypatch.setattr(
        fh, "_model_can_fight_target", lambda gs, m, uid, eid: False
    )
    monkeypatch.setattr(
        su, "get_enemy_slot_mapping", lambda gs, player: [None, None]
    )
    eng = _FakeEngine(_gs())
    # `targets` non vide via la branche NON-overrun : l'escouade reste engagée.
    monkeypatch.setattr(fh, "_fight_v11_engaged_now", lambda gs, u: True)
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["Z"])

    with pytest.raises(RuntimeError, match="aucun slot ennemi mappé"):
        eng._continue_squad_fight_after_selection(_SQUAD, target_slot=0)


# ---------------------------------------------------------------------------
# 4. Non-régression : plus AUCUNE cible → combat à vide
# ---------------------------------------------------------------------------


def test_no_target_left_fights_empty(monkeypatch):
    """La cible désignée est morte et le pile-in overrun n'atteint personne : combat à vide."""
    monkeypatch.setattr(fh, "_fight_v11_engaged_now", lambda gs, u: True)
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: [])
    monkeypatch.setattr(su, "get_enemy_slot_mapping", lambda gs, player: [None])
    monkeypatch.setattr(su, "squad_fight_restart_activation", lambda gs, sid: None)
    monkeypatch.setattr(wcore, "require_unit_by_id", lambda gs, uid: {"id": uid, "player": 1})
    monkeypatch.setattr(
        fh, "build_manual_fight_allocation",
        lambda gs, sid: {"done": True, "waiting_for_player": False, "shoot_result": {}},
    )
    monkeypatch.setattr(
        wcore.generic_handlers if hasattr(wcore, "generic_handlers") else wcore,
        "end_activation", lambda gs, unit, *a, **kw: {"ok": True}, raising=False,
    )
    import engine.phase_handlers.generic_handlers as gh
    monkeypatch.setattr(gh, "end_activation", lambda gs, unit, *a, **kw: {"ok": True})

    eng = _FakeEngine(_gs())
    ok, result = eng._continue_squad_fight_after_selection(_SQUAD, target_slot=0)

    assert ok is True
    assert PENDING_FIGHT_TARGET_KEY not in eng.game_state
    assert result["target_squad_id"] is None


# ---------------------------------------------------------------------------
# 5-6. Reprise : `squad_fight_target_sel` consomme le pending
# ---------------------------------------------------------------------------


def test_target_sel_commit_resolves_chosen_slot(monkeypatch):
    """Le slot rejoué désigne la cible ; le pending est consommé et l'arme est demandée ensuite."""
    _patch_overrun(monkeypatch, [None, "A", "B"])
    eng = _FakeEngine(_gs())
    eng.game_state[PENDING_FIGHT_TARGET_KEY] = {
        "squad_id": _SQUAD,
        "slot_to_target": {1: "A", 2: "B"},
    }

    ok, result = eng._process_squad_action(
        {"action": "squad_fight_target_sel", "squad_id": _SQUAD, "target_slot": 2}
    )

    assert ok is True
    assert result["target_squad_id"] == "B", "la cible vient de l'ACTION, pas du moteur"
    assert PENDING_FIGHT_TARGET_KEY not in eng.game_state
    assert eng.moves == [], "la reprise ne refait PAS le pile-in overrun"


def test_target_sel_commit_rejects_slot_outside_pending(monkeypatch):
    """Un slot hors du pending est une rupture masque/commit, pas un cas à absorber."""
    _patch_overrun(monkeypatch, [None, "A", "B"])
    eng = _FakeEngine(_gs())
    eng.game_state[PENDING_FIGHT_TARGET_KEY] = {
        "squad_id": _SQUAD,
        "slot_to_target": {1: "A", 2: "B"},
    }

    with pytest.raises(ValueError, match="rupture masque/commit"):
        eng._process_squad_action(
            {"action": "squad_fight_target_sel", "squad_id": _SQUAD, "target_slot": 3}
        )


def test_target_sel_without_pending_raises():
    """Aucun pending : le masque n'aurait pas dû ouvrir de FIGHT_SLOT."""
    eng = _FakeEngine(_gs())
    with pytest.raises(RuntimeError, match="aucun état pending_fight_target_select"):
        eng._process_squad_action(
            {"action": "squad_fight_target_sel", "squad_id": _SQUAD, "target_slot": 1}
        )


# ---------------------------------------------------------------------------
# 7-8. Parité masque/décodeur sur le vrai ActionDecoder
# ---------------------------------------------------------------------------


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine_in_fight_phase(scenario_file: str, seed: int = 1):
    """Moteur gym amené en phase de combat par le vrai chemin d'entrée (jumeau du harnais V11)."""
    from ai.unit_registry import UnitRegistry
    from engine.game_utils import get_unit_by_id
    from shared.data_validation import require_present
    from engine.phase_handlers import fight_handlers
    from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=scenario_file,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    gs = eng.game_state
    gs["phase"] = "fight"
    engaged = [
        sid for sid in gs["units_cache"]
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert engaged, "le scénario mêlée doit être pré-engagé"
    gs["current_player"] = int(gs["units_cache"][str(engaged[0])]["player"])
    gs["units_fought"] = set()
    res = fight_handlers.fight_phase_start(gs)
    eng._fight_v11_gym_after_phase_start(res)
    return eng


def test_mask_opens_only_pending_fight_slots(melee_scenario_file):
    """Le pending est EXCLUSIF : seuls ses FIGHT_SLOT sont ouverts, le pool est vide."""
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    sid = next(iter(gs["units_cache"]))
    gs[PENDING_FIGHT_TARGET_KEY] = {"squad_id": str(sid), "slot_to_target": {1: "A", 3: "B"}}

    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)

    assert eligible == []
    opened = {i for i, v in enumerate(mask) if v}
    assert opened == {
        SQUAD_ACTION_FIGHT_SLOT_BASE + 1,
        SQUAD_ACTION_FIGHT_SLOT_BASE + 3,
    }, f"seuls les slots du pending doivent être ouverts, obtenu {sorted(opened)}"


def test_convert_fight_slot_with_pending_returns_target_sel(melee_scenario_file):
    """Le FIGHT_SLOT rejoué se décode en `squad_fight_target_sel`, pas en `squad_fight`."""
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    sid = str(next(iter(gs["units_cache"])))
    gs[PENDING_FIGHT_TARGET_KEY] = {"squad_id": sid, "slot_to_target": {1: "A", 3: "B"}}

    semantic = eng.action_decoder.convert_squad_action(
        SQUAD_ACTION_FIGHT_SLOT_BASE + 3, gs, eligible_units=[]
    )

    assert semantic == {
        "action": "squad_fight_target_sel",
        "squad_id": sid,
        "target_slot": 3,
    }


def test_convert_rejects_fight_slot_outside_pending(melee_scenario_file):
    """Un FIGHT_SLOT non ouvert par le pending est refusé au décodage."""
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    sid = str(next(iter(gs["units_cache"])))
    gs[PENDING_FIGHT_TARGET_KEY] = {"squad_id": sid, "slot_to_target": {1: "A"}}

    with pytest.raises(ValueError, match="rupture masque/commit"):
        eng.action_decoder.convert_squad_action(
            SQUAD_ACTION_FIGHT_SLOT_BASE + 2, gs, eligible_units=[]
        )


def test_pending_target_purged_at_fight_phase_end(melee_scenario_file):
    """Le pending ne doit pas survivre à la phase : il rouvrirait des FIGHT_SLOT au tour suivant."""
    from engine.phase_handlers.fight_handlers import _fight_phase_complete

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    gs[PENDING_FIGHT_TARGET_KEY] = {"squad_id": "X", "slot_to_target": {1: "A"}}

    _fight_phase_complete(gs)

    assert PENDING_FIGHT_TARGET_KEY not in gs
