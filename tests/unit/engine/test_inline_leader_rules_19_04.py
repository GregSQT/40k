"""Règle 19.04 — leader/support déclaré inline dans models (sans attached_squad).

Bug : un Bigboss déclaré directement dans `models` du roster compact (format string dans
`composition.models`) n'avait pas `attached_from`. Dans la boucle de séparation de
`_build_enhanced_unit`, ses règles allaient donc dans `_UNIT_RULES_OWN` plutôt que dans
`_ATTACHED_RULE_GROUPS`. Résultat : `charge_roll_bonus` persistait après la mort du Bigboss,
tant que des Boyz natifs restaient vivants (`native_alive=True`).

Fix : `_build_enhanced_unit` détecte le rôle leader/support via `_derive_model_role` et
assigne une source fictive `_inline_<squad_id>_<idx>`. Les règles vont dans
`_ATTACHED_RULE_GROUPS[source_fictive]` et `recompute_unit_rules_in_effect` les exclut de
`alive_attached_sources` dès que la figurine sort de `squad_models`.

Figurines : Boyz (bodyguard, `secure_objective_on_control`) + Bigboss inline (`charge_roll_bonus`).
"""
from __future__ import annotations

from typing import TypedDict

from engine.phase_handlers.shared_utils import destroy_model, unit_has_rule_effect
from tests.unit.engine._config_helpers import load_engine_from_scenario

INLINE_LEADER_RULE = "charge_roll_bonus"
BODYGUARD_RULE = "secure_objective_on_control"


def _inline_scenario():
    return {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "army_faction": {"1": "TYRANIDS", "2": "ORKS"},
        "units": [
            {"id": 1, "unit_type": "Hormagaunt", "player": 1, "col": 3, "row": 3},
            {
                "id": 101,
                "unit_type": "Boyz",
                "player": 2,
                "col": 12,
                "row": 10,
                "models": [
                    {"col": 12, "row": 10},
                    {"col": 13, "row": 10},
                    {"unit_type": "Bigboss", "col": 14, "row": 10},
                ],
            },
        ],
    }


class _EngineOverrides(TypedDict):
    controlled_agent: str
    rewards_config: str


_ENGINE_OVERRIDES: _EngineOverrides = {
    "controlled_agent": "ArmageddonAgent_x1",
    "rewards_config": "ArmageddonAgent_x1",
}


def _rule_ids(engine, uid: str) -> set:
    return {str(r["ruleId"]) for r in engine.game_state["unit_by_id"][uid]["UNIT_RULES"]}


def _kill(engine, mid: str) -> None:
    destroy_model(engine.game_state, mid, "combat")


def _bigboss_mid(engine) -> str:
    mc = engine.game_state["models_cache"]
    try:
        return next(
            mid
            for mid in engine.game_state["squad_models"]["101"]
            if mc[mid].get("unitType") == "Bigboss"
        )
    except StopIteration:
        raise AssertionError(
            "_bigboss_mid: aucun modèle Bigboss dans squad_models[101]"
        ) from None


def test_inline_leader_rule_separee_en_attached_group():
    """La règle du Bigboss inline est dans _ATTACHED_RULE_GROUPS, pas _UNIT_RULES_OWN."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    unit = eng.game_state["unit_by_id"]["101"]
    own_ids = {r["ruleId"] for r in unit["_UNIT_RULES_OWN"]}
    assert INLINE_LEADER_RULE not in own_ids, (
        f"charge_roll_bonus ne doit pas être dans _UNIT_RULES_OWN, sinon il persiste"
        f" après la mort du Bigboss"
    )
    assert any(
        INLINE_LEADER_RULE in {r["ruleId"] for r in rules}
        for rules in unit["_ATTACHED_RULE_GROUPS"].values()
    ), "charge_roll_bonus doit être dans un _ATTACHED_RULE_GROUPS (source fictive du Bigboss)"


def test_inline_leader_rule_active_quand_vivant():
    """19.04 montant : la règle du Bigboss inline vaut pour l'escouade entière."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    assert INLINE_LEADER_RULE in _rule_ids(eng, "101")
    assert unit_has_rule_effect(eng.game_state["unit_by_id"]["101"], INLINE_LEADER_RULE) is True


def test_bodyguard_rule_conservee():
    """La règle native des Boyz reste en vigueur avec ou sans Bigboss."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    assert BODYGUARD_RULE in _rule_ids(eng, "101")


def test_inline_leader_rule_eteinte_a_la_mort():
    """19.04 descendant : la mort du Bigboss inline éteint charge_roll_bonus."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    assert unit_has_rule_effect(eng.game_state["unit_by_id"]["101"], INLINE_LEADER_RULE) is True

    _kill(eng, _bigboss_mid(eng))

    assert unit_has_rule_effect(eng.game_state["unit_by_id"]["101"], INLINE_LEADER_RULE) is False
    assert BODYGUARD_RULE in _rule_ids(eng, "101")


def test_inline_leader_role_non_remonte_a_lescouade():
    """Le marqueur 'leader' (rôle d'allocation) ne doit pas remonter dans UNIT_RULES."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    assert "leader" not in _rule_ids(eng, "101")


def test_inline_leader_modele_porte_attached_from():
    """Le Bigboss inline reçoit attached_from dans models_cache — prérequis de l'extinction."""
    eng = load_engine_from_scenario(_inline_scenario(), **_ENGINE_OVERRIDES)
    mc = eng.game_state["models_cache"]
    mid = _bigboss_mid(eng)
    assert "attached_from" in mc[mid], (
        f"Le Bigboss inline doit avoir attached_from dans models_cache pour que "
        f"recompute_unit_rules_in_effect puisse l'exclure de alive_attached_sources"
    )
