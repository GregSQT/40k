"""D+ — toutes les figurines engagées frappent (04.01, 04.02, 24.11), chemin gym / bot PvE.

CE QUE CE FICHIER EMPÊCHE. Jusqu'au 2026-09-18, une activation `squad_fight` du gym ne
déclarait que les figurines porteuses du CODE D'ARME choisi par l'agent (une ligne
`squad_declare_fight_weapon_qty`), après lui avoir toujours posé la question d'arme — même sur
une escouade où aucune figurine n'a le choix. Mesuré bot contre bot sur 40 parties (moteur
5b2422dd5, `logs/melee_bench_avant_2026-09-18.json`) : 318 figurines frappent sur 598 engagées,
1 049 attaques sur 2 042 possibles ; la seringue [EXTRA ATTACKS] du PainBoy n'était jamais
complétée sur ce chemin.

Règles (PDF 04, 24) : 04.01 WHILE FIGHTING « You must select one melee weapon that model has » —
un choix seulement s'il y a ≥ 2 armes ordinaires ; 24.11 « you must select all of that model's
[EXTRA ATTACKS] weapons » ; 04.02 WHILE FIGHTING « Each target must be engaged with the model
that has that weapon » — une figurine engagée seulement avec un AUTRE ennemi frappe celui-là.

Scénario : trois Boyz (deux Boys + PainBoy `dok_tools` + `urty_syringe` [EXTRA ATTACKS]) entre
deux escouades d'Intercessors : `1#1`/`1#2` engagés avec l'escouade 2 seulement, `1#0` avec
l'escouade 3 seulement. Les positions sont en sous-hex x5 (plateau de la config par défaut).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from shared.data_validation import require_key


def _scenario(extra_units: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "primary_objectives": ["objectives_control"],
        "uses_codex_detachment": {"1": True, "2": True},
        "army_faction": {"1": "ORKS", "2": "ADEPTUS ASTARTES"},
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        "deployment_type": "fixed",
        "units": [
            {"id": "1", "player": 1, "unit_type": "Boyz", "col": 100, "row": 100,
             "models": [
                 {"col": 100, "row": 100},
                 {"col": 100, "row": 108},
                 {"col": 100, "row": 116, "unit_type": "PainBoy"},
             ]},
            # Cibles MONO-figurine : l'allocation des pertes n'a alors aucun choix à poser au
            # défenseur (05.04), le combat se résout dans le step.
            {"id": "2", "player": 2, "unit_type": "Intercessor", "col": 112, "row": 112,
             "models": [{"col": 112, "row": 112}]},
            {"id": "3", "player": 2, "unit_type": "Intercessor", "col": 88, "row": 96,
             "models": [{"col": 88, "row": 96}]},
            *(extra_units or []),
        ],
    }


@pytest.fixture()
def scenario_file(tmp_path: Path):
    def _write(extra_units: Optional[List[Dict[str, Any]]] = None) -> str:
        path = tmp_path / "mixed_melee.json"
        path.write_text(json.dumps(_scenario(extra_units)))
        return str(path)
    return _write


def _engine_in_fight_phase(scenario_path: str):
    """Moteur gym en phase de combat, machine V11 démarrée, sélecteur = joueur 1."""
    from ai.unit_registry import UnitRegistry
    from engine.agent_decision import PENDING_DECISION_KEY
    from engine.phase_handlers import fight_handlers
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1", scenario_file=scenario_path,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=1)
    gs = eng.game_state
    # Le reset s'arrête sur l'appel de Waaagh! (phase de commandement des Orks) : cette décision
    # n'a rien à voir avec le combat testé, elle est retirée pour que la phase de combat puisse
    # poser les siennes.
    gs.pop(PENDING_DECISION_KEY, None)
    gs["phase"] = "fight"
    gs["current_player"] = 1
    gs["units_fought"] = set()
    res = fight_handlers.fight_phase_start(gs)
    eng._fight_v11_gym_after_phase_start(res)
    return eng


def _slot_of(gs: Dict[str, Any], our_player: int, target_id: str) -> int:
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    mapping = get_enemy_slot_mapping(gs, our_player)
    for slot_i, esid in enumerate(mapping):
        if esid is not None and str(esid) == target_id:
            return slot_i
    raise AssertionError(f"cible {target_id} sans slot ennemi : {mapping}")


@pytest.fixture()
def declared_intents(monkeypatch):
    """Capture les intents au moment de l'allocation (ils sont consommés par la résolution)."""
    from engine.phase_handlers import fight_handlers

    captured: List[Dict[str, Any]] = []
    orig = fight_handlers.build_manual_fight_allocation

    def _spy(game_state: Dict[str, Any], squad_id: str) -> Dict[str, Any]:
        captured.extend(
            dict(i) for i in require_key(game_state, "pending_squad_fight_intents").get(str(squad_id), [])  # get allowed
        )
        return orig(game_state, squad_id)

    monkeypatch.setattr(fight_handlers, "build_manual_fight_allocation", _spy)
    return captured


def _weapon_code(gs: Dict[str, Any], intent: Dict[str, Any]) -> str:
    m = gs["models_cache"][str(intent["model_id"])]
    return str(require_key(m["CC_WEAPONS"][int(intent["weapon_index"])], "code"))


def test_every_engaged_model_strikes_extra_attacks_included_and_only_with_other_enemy(
    scenario_file, declared_intents
):
    """Une action `squad_fight` sur l'escouade 2 : les trois figurines engagées frappent.

    ROUGE avant D+ : seules les porteuses du code choisi frappaient après une question d'arme
    inutile ; la seringue n'était jamais déclarée ; `1#0` (engagé avec 3 seulement) ne frappait
    personne.
    """
    from engine.action_decoder import PENDING_FIGHT_TARGET_KEY, PENDING_FIGHT_WEAPON_KEY
    from engine.phase_handlers.shared_utils import get_fighting_models

    eng = _engine_in_fight_phase(scenario_file())
    gs = eng.game_state
    assert get_fighting_models(gs, "1", "2") == ["1#1", "1#2"], "précondition géométrique"
    assert get_fighting_models(gs, "1", "3") == ["1#0"], "précondition géométrique"

    ok, result = eng._process_squad_action(
        {"action": "squad_fight", "squad_id": "1", "target_slot": _slot_of(gs, 1, "2")}
    )

    assert ok is True
    assert "fight_result" in result, f"combat non résolu en un step : {result!r}"
    assert PENDING_FIGHT_WEAPON_KEY not in gs and PENDING_FIGHT_TARGET_KEY not in gs
    by_model = {}
    for intent in declared_intents:
        by_model.setdefault(str(intent["model_id"]), []).append(
            (_weapon_code(gs, intent), str(intent["target_unit_id"]))
        )
    assert by_model == {
        "1#0": [("choppa_a3", "3")],
        "1#1": [("choppa_a3", "2")],
        "1#2": [("urty_syringe", "2"), ("dok_tools", "2")],
    }, by_model
    assert result["target_squad_id"] == "2"


def test_weapon_question_only_for_models_with_two_ordinary_weapons(scenario_file, declared_intents):
    """`1#1` reçoit une seconde arme ordinaire : la question d'arme est posée POUR ELLE SEULE,
    les autres figurines sont déjà déclarées ; la réponse la déclare et le combat se résout.
    ROUGE avant D+ : la question était posée à toute l'escouade et la réponse ne déclarait que
    les porteuses du code."""
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
    from engine.macro_intents import FIGHT_WEAPON_SLOT_BASE

    eng = _engine_in_fight_phase(scenario_file())
    gs = eng.game_state
    base = gs["models_cache"]["1#1"]["CC_WEAPONS"][0]
    gs["models_cache"]["1#1"]["CC_WEAPONS"].append(
        {**base, "code": "choppa_alt", "display_name": "Choppa (alt)", "NB": 4}
    )

    ok, result = eng._process_squad_action(
        {"action": "squad_fight", "squad_id": "1", "target_slot": _slot_of(gs, 1, "2")}
    )
    assert ok is True and result.get("waiting_for_weapon_select") is True, result
    pending = gs[PENDING_FIGHT_WEAPON_KEY]
    assert pending["model_ids"] == ["1#1"]
    assert sorted(pending["slot_to_code"].values()) == ["choppa_a3", "choppa_alt"]
    # Masque exclusif sur ces deux slots.
    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert eligible == []
    assert {i for i, v in enumerate(mask) if v} == {
        FIGHT_WEAPON_SLOT_BASE + j for j in pending["slot_to_code"]
    }
    alt_slot = next(j for j, code in pending["slot_to_code"].items() if code == "choppa_alt")

    ok, result = eng._process_squad_action(
        {"action": "squad_fight_weapon", "squad_id": "1", "weapon_slot": alt_slot}
    )
    assert ok is True and "fight_result" in result, result
    assert PENDING_FIGHT_WEAPON_KEY not in gs
    codes = {(str(i["model_id"]), _weapon_code(gs, i)) for i in declared_intents}
    assert ("1#1", "choppa_alt") in codes
    assert ("1#1", "choppa_a3") not in codes, "04.01 : UNE arme ordinaire par figurine"
    assert {m for m, _ in codes} == {"1#0", "1#1", "1#2"}


def test_model_engaged_only_with_two_other_enemies_gets_a_restricted_target_question(
    scenario_file, declared_intents
):
    """`1#0` est engagé avec 3 ET 4 (ni l'une ni l'autre n'est la cible désignée 2) : une
    question de cible RESTREINTE à `1#0` est posée (slots de 3 et 4 seulement), la réponse la
    déclare sans repartir de zéro, puis le combat se résout avec les trois figurines."""
    from engine.action_decoder import PENDING_FIGHT_TARGET_KEY
    from engine.phase_handlers.shared_utils import (
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        get_fighting_models,
    )

    squad_4 = {"id": "4", "player": 2, "unit_type": "Intercessor", "col": 100, "row": 88,
               "models": [{"col": 100, "row": 88}]}
    eng = _engine_in_fight_phase(scenario_file([squad_4]))
    gs = eng.game_state
    assert get_fighting_models(gs, "1", "4") == ["1#0"], "précondition géométrique"
    assert get_fighting_models(gs, "1", "2") == ["1#1", "1#2"]

    ok, result = eng._process_squad_action(
        {"action": "squad_fight", "squad_id": "1", "target_slot": _slot_of(gs, 1, "2")}
    )
    assert ok is True and result.get("waiting_for_target_select") is True, result
    pending = gs[PENDING_FIGHT_TARGET_KEY]
    assert pending["model_ids"] == ["1#0"]
    assert sorted(pending["slot_to_target"].values()) == ["3", "4"]
    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert eligible == []
    assert {i for i, v in enumerate(mask) if v} == {
        SQUAD_ACTION_FIGHT_SLOT_BASE + s for s in pending["slot_to_target"]
    }
    slot_4 = next(s for s, t in pending["slot_to_target"].items() if t == "4")

    ok, result = eng._process_squad_action(
        {"action": "squad_fight_target_sel", "squad_id": "1", "target_slot": slot_4}
    )
    assert ok is True and "fight_result" in result, result
    assert PENDING_FIGHT_TARGET_KEY not in gs
    targets = {(str(i["model_id"]), str(i["target_unit_id"])) for i in declared_intents}
    assert targets == {("1#0", "4"), ("1#1", "2"), ("1#2", "2")}, targets


def test_primitive_auto_declares_single_ordinary_and_all_extra_attacks(scenario_file):
    """`squad_auto_declare_fight_weapons` seule : arme ordinaire unique d'office + [EXTRA
    ATTACKS] ; une figurine à deux armes ordinaires est rendue sans déclaration ordinaire ;
    idempotente."""
    from engine.phase_handlers.shared_utils import (
        squad_auto_declare_fight_weapons,
        squad_fight_restart_activation,
    )

    eng = _engine_in_fight_phase(scenario_file())
    gs = eng.game_state
    base = gs["models_cache"]["1#2"]["CC_WEAPONS"][0]
    gs["models_cache"]["1#2"]["CC_WEAPONS"].append({**base, "code": "dok_alt", "display_name": "Alt"})
    squad_fight_restart_activation(gs, "1")

    undecided = squad_auto_declare_fight_weapons(gs, "1", "2")
    assert undecided == {"1#2": ["dok_tools", "dok_alt"]}
    intents = gs["pending_squad_fight_intents"]["1"]
    assert {(str(i["model_id"]), _weapon_code(gs, i)) for i in intents} == {
        ("1#1", "choppa_a3"), ("1#2", "urty_syringe"),
    }
    # Idempotence : rien n'est dupliqué.
    assert squad_auto_declare_fight_weapons(gs, "1", "2") == undecided
    assert len(gs["pending_squad_fight_intents"]["1"]) == 2
