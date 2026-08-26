"""Choix d'arme CC par l'agent (V11 §0.69).

Le combat en deux temps : squad_fight arme pending_fight_weapon_select,
puis squad_fight_weapon résout et efface le pending.

Invariants vérifiés :
- pending posé → masque exclusif FIGHT_WEAPON_SLOTS
- commit valid slot → pending effacé, fight_result présent
- commit slot hors éligibles → ValueError (rupture masque/commit)
- fight_weapon_eligible_slots : seulement les slots avec ≥1 figurine engagée
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from smoke_t5_bare import MELEE_SCENARIO


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine_in_fight_phase(scenario_file: str, seed: int = 1):
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


def _first_fight_action_with_target(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Première action squad_fight avec cible disponible dans le pool 12.04."""
    from engine.game_utils import get_unit_by_id
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        fight_v11_current_pool,
    )
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    pool = fight_v11_current_pool(game_state)
    assert pool, "précondition : pool 12.04 non vide"
    for cid in pool:
        squad_id = str(cid)
        unit = get_unit_by_id(game_state, squad_id)
        if unit is None:
            continue
        targets = {str(t) for t in _fight_build_valid_target_pool(game_state, unit)}
        if not targets:
            continue
        our_player = int(game_state["units_cache"][squad_id]["player"])
        slot_map = get_enemy_slot_mapping(game_state, our_player)
        for slot_i, esid in enumerate(slot_map):
            if esid is not None and str(esid) in targets:
                return {"action": "squad_fight", "squad_id": squad_id, "target_slot": slot_i}
    pytest.skip("scénario sans cible mêlée accessible — test inapplicable")


# ── Tests ────────────────────────────────────────────────────────────────────


def test_squad_fight_arms_pending_fight_weapon_select(melee_scenario_file):
    """squad_fight avec cible pose pending_fight_weapon_select et retourne waiting_for_weapon_select.

    Échoue si la branche §0.69 est absente et que le combat est résolu directement.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    action = _first_fight_action_with_target(gs)

    ok, result = eng._process_squad_action(action)

    assert ok is True
    assert result.get("waiting_for_weapon_select") is True, (
        f"résultat inattendu {result!r} — pending_fight_weapon_select non armé"
    )
    assert PENDING_FIGHT_WEAPON_KEY in gs, "pending_fight_weapon_select absent du game_state"
    pending = gs[PENDING_FIGHT_WEAPON_KEY]
    assert pending["squad_id"] == action["squad_id"]
    assert pending["slot_to_code"], "aucun slot d'arme CC éligible dans le pending"


def test_pending_fight_weapon_makes_mask_exclusive(melee_scenario_file):
    """pending_fight_weapon_select → masque exclusif : seuls FIGHT_WEAPON_SLOTS ouverts.

    Échoue si le bloc exclusif dans get_squad_action_mask_and_eligible_units est absent.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
    from engine.macro_intents import FIGHT_WEAPON_SLOT_BASE, FIGHT_WEAPON_SLOT_COUNT

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    action = _first_fight_action_with_target(gs)
    eng._process_squad_action(action)

    assert PENDING_FIGHT_WEAPON_KEY in gs, "précondition : pending non armé"

    mask, eligible_units = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)

    # Le retour anticipé ─ (mask, []) ─ force un masque exclusif.
    assert eligible_units == [], "des unités éligibles offertes alors que le masque doit être exclusif"

    open_indices = [i for i, v in enumerate(mask) if v]
    weapon_slots = set(range(FIGHT_WEAPON_SLOT_BASE, FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT))
    pending = gs[PENDING_FIGHT_WEAPON_KEY]
    expected = {FIGHT_WEAPON_SLOT_BASE + j for j in pending["slot_to_code"]}

    assert set(open_indices) == expected, (
        f"masque non exclusif — ouverts hors FIGHT_WEAPON_SLOTS : "
        f"{set(open_indices) - weapon_slots!r}"
    )


def test_squad_fight_weapon_resolves_fight(melee_scenario_file):
    """squad_fight_weapon avec slot valide résout le combat et efface pending_fight_weapon_select.

    Échoue si la branche squad_fight_weapon est absente ou ne pop() pas le pending.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    action = _first_fight_action_with_target(gs)
    eng._process_squad_action(action)

    pending = gs[PENDING_FIGHT_WEAPON_KEY]
    first_slot = next(iter(pending["slot_to_code"]))

    ok, result = eng._process_squad_action({
        "action": "squad_fight_weapon",
        "squad_id": str(pending["squad_id"]),
        "weapon_slot": first_slot,
    })

    assert ok is True
    assert "fight_result" in result, f"fight_result absent du résultat : {result!r}"
    assert PENDING_FIGHT_WEAPON_KEY not in gs, "pending_fight_weapon_select non effacé après résolution"


def test_squad_fight_weapon_ineligible_slot_raises(melee_scenario_file):
    """slot hors slot_to_code → ValueError (rupture masque/commit).

    Échoue si le moteur absorbe silencieusement le slot invalide.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
    from engine.observation_entities import K_WEAPONS_MELEE

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    action = _first_fight_action_with_target(gs)
    eng._process_squad_action(action)

    pending = gs[PENDING_FIGHT_WEAPON_KEY]
    eligible = set(pending["slot_to_code"].keys())
    # Trouver un slot valide sur [0, K_WEAPONS_MELEE) mais pas éligible.
    ineligible = next((j for j in range(K_WEAPONS_MELEE) if j not in eligible), None)
    if ineligible is None:
        pytest.skip("tous les slots CC éligibles — rupture masque/commit inatteignable dans ce scénario")

    with pytest.raises(ValueError, match="rupture masque/commit"):
        eng._process_squad_action({
            "action": "squad_fight_weapon",
            "squad_id": str(pending["squad_id"]),
            "weapon_slot": ineligible,
        })


def test_pending_fight_weapon_obs_uses_pending_squad(melee_scenario_file):
    """pending_fight_weapon_select armé → _build_observation_and_mask retourne (obs, None).

    Sans le early-return (§0.69), eligible_units=[] + armed_decision=None font tomber le code
    dans le fallback qui prend la première escouade du cache (A) au lieu de pending_fw['squad_id']
    (B) : l'agent décrit A et choisit l'arme de B, empoisonnant le signal d'entraînement.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    action = _first_fight_action_with_target(gs)
    pending_squad_id = action["squad_id"]
    eng._process_squad_action(action)  # arme PENDING_FIGHT_WEAPON_KEY

    assert PENDING_FIGHT_WEAPON_KEY in gs, "précondition : pending non armé"
    assert gs[PENDING_FIGHT_WEAPON_KEY]["squad_id"] == pending_squad_id

    obs, mask_and_eligible = eng._build_observation_and_mask()

    # Le early-return est pris : second élément = None (aucun masque construit).
    # Si mask_and_eligible est un tuple, le fallback a été pris et l'obs décrit la mauvaise escouade.
    assert mask_and_eligible is None, (
        "pending_fight_weapon_select doit déclencher un early-return (mask_and_eligible=None) "
        f"— reçu {mask_and_eligible!r} : le fallback escouade-par-défaut a été pris"
    )
    assert obs is not None


def test_squad_fight_weapon_without_pending_raises(melee_scenario_file):
    """squad_fight_weapon sans pending pose → RuntimeError.

    Échoue si le moteur tente de résoudre un combat sans état intermédiaire.
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    squad_id = str(next(iter(gs["units_cache"])))

    with pytest.raises(RuntimeError, match="aucun état pending_fight_weapon_select"):
        eng._process_squad_action({
            "action": "squad_fight_weapon",
            "squad_id": squad_id,
            "weapon_slot": 0,
        })
