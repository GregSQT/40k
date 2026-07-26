"""Règle 19.04 (Abilities in attached units) — les règles d'unité valent pour l'unité attachée.

PDF 19.04 : « abilities/rules that affect a unit (or models in it) apply to every model in an
attached unit, until the source of that ability/rule is destroyed ». Le tableau du PDF donne la
durée de vie de chaque source : règle du bodyguard → jusqu'à la mort de sa dernière figurine ;
règle du leader/support → jusqu'à la mort de la dernière figurine de CE leader/support (le PDF
précise même que le leader garde ses propres règles après la destruction de son bodyguard).

Vérifié BOUT-EN-BOUT via le vrai chemin de chargement (`load_units_from_scenario` →
`_fold_attached_characters` → `_build_enhanced_unit`) puis via le vrai consommateur
(`unit_can_reroll_charge`), jamais sur la fonction d'union isolée : le trou corrigé ici était
exactement un défaut de CÂBLAGE (la fonction d'union n'existait pas, les règles du character
restaient sur `models[i]` et aucun consommateur ne les lisait).

Fixtures choisies pour être discriminantes dans les deux sens : `AssaultIntercessor` porte
`targeted_intercession` et PAS `reroll_charge` ; `CaptainPowerWeaponBolter` porte
`reroll_charge` et PAS `targeted_intercession`.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest


def _scenario(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "board_ref": "25x21",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "units": units,
    }


def _load(scenario: Dict[str, Any]):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "attached.json"
        path.write_text(json.dumps(scenario))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        )
        eng.reset(seed=0)
        return eng


# Escouade de 3 figurines : l'unité attachée en comptera 4 (le Captain replié).
_BODYGUARD = {
    "id": 101, "unit_type": "AssaultIntercessor", "player": 2, "col": 12, "row": 10,
    "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}, {"col": 14, "row": 10}],
}
_LEADER = {
    "id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
    "attached_squad": 101, "col": 15, "row": 10,
}
_ENEMY = {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3}


def _rule_ids(engine, unit_id: str) -> set:
    unit = engine.game_state["unit_by_id"][unit_id]
    return {str(r["ruleId"]) for r in unit["UNIT_RULES"]}


def test_regle_du_leader_sapplique_a_lunite_attachee():
    """19.04 montant : `reroll_charge` du Captain vaut pour l'escouade entière.

    C'est le bug d'origine : attaché, le Captain n'est plus une unité, et sa règle n'était
    portée que par sa figurine — donc lue par personne.
    """
    from engine.phase_handlers.shared_utils import unit_can_reroll_charge

    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    assert "reroll_charge" in _rule_ids(eng, "101")
    # Le vrai consommateur, pas seulement le champ.
    assert unit_can_reroll_charge(eng.game_state, "101") is True


def test_regle_du_bodyguard_conservee():
    """L'union n'écrase rien : la règle propre de l'escouade reste en vigueur."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    assert "targeted_intercession" in _rule_ids(eng, "101")


def test_escouade_sans_character_inchangee():
    """Contre-épreuve : sans character attaché, l'unité garde exactement ses règles."""
    from engine.phase_handlers.shared_utils import unit_can_reroll_charge

    eng = _load(_scenario([_BODYGUARD, _ENEMY]))
    assert _rule_ids(eng, "101") == {"targeted_intercession"}
    assert unit_can_reroll_charge(eng.game_state, "101") is False


def test_les_roles_ne_remontent_jamais_a_lescouade():
    """Piège n°1 : `leader`/`support`/`sergeant` sont des marqueurs PAR FIGURINE.

    Les remonter à l'escouade ferait dériver `role='leader'` à TOUTES ses figurines de base
    (`_derive_model_role` lit `unit["UNIT_RULES"]` pour une figurine sans override), ce qui
    casserait l'ordre d'allocation 05.04 et la T bodyguard 19.02.
    """
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    assert "leader" not in _rule_ids(eng, "101")

    models_cache = eng.game_state["models_cache"]
    roles = [models_cache[mid]["role"] for mid in eng.game_state["squad_models"]["101"]]
    assert roles.count("leader") == 1, "seule la figurine du Captain est leader"
    assert roles.count(None) == 3, "les 3 Assault Intercessors restent des figurines de base"


def test_provenance_des_regles_separee_par_source():
    """Les deux sources 19.04 sont distinguées — prérequis de l'extinction (tranche -b).

    Sans cette séparation, impossible de savoir laquelle éteindre quand une figurine meurt.
    """
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    unit = eng.game_state["unit_by_id"]["101"]
    assert [r["ruleId"] for r in unit["_UNIT_RULES_OWN"]] == ["targeted_intercession"]
    assert {k: [r["ruleId"] for r in v] for k, v in unit["_ATTACHED_RULE_GROUPS"].items()} == {
        "102": ["reroll_charge"]
    }


def _kill(engine, model_id: str) -> None:
    from engine.phase_handlers.shared_utils import destroy_model

    destroy_model(engine.game_state, model_id, "combat")


def _models(engine) -> List[str]:
    return list(engine.game_state["squad_models"]["101"])


def test_mort_du_leader_eteint_sa_regle():
    """19.04 : « until the last model in that leader/support unit is destroyed ».

    Le Captain mort, l'escouade perd `reroll_charge` — et garde la sienne.
    """
    from engine.phase_handlers.shared_utils import unit_can_reroll_charge

    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = next(
        mid for mid in _models(eng)
        if "attached_from" in eng.game_state["models_cache"][mid]
    )
    assert unit_can_reroll_charge(eng.game_state, "101") is True

    _kill(eng, leader_mid)

    assert unit_can_reroll_charge(eng.game_state, "101") is False
    assert _rule_ids(eng, "101") == {"targeted_intercession"}


def test_mort_des_bodyguards_eteint_la_regle_du_datasheet_pas_celle_du_leader():
    """19.04 : « until the last model in that bodyguard unit is destroyed », plus la note du
    PDF « leader/support units continue to benefit from their own abilities even after their
    bodyguard unit is destroyed, provided they started the battle in an attached unit »."""
    from engine.phase_handlers.shared_utils import unit_can_reroll_charge

    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    models_cache = eng.game_state["models_cache"]
    natives = [mid for mid in _models(eng) if "attached_from" not in models_cache[mid]]
    assert len(natives) == 3

    for mid in natives[:-1]:
        _kill(eng, mid)
    assert _rule_ids(eng, "101") == {"targeted_intercession", "reroll_charge"}, (
        "tant qu'un bodyguard vit, les deux sources sont en vigueur"
    )

    _kill(eng, natives[-1])
    assert _rule_ids(eng, "101") == {"reroll_charge"}
    assert unit_can_reroll_charge(eng.game_state, "101") is True


def test_unite_entierement_detruite_na_plus_aucune_regle():
    """Aucune source vivante → aucune règle. Le PDF 25 « Destroyed » interdit à une unité
    détruite d'utiliser des capacités ; ici c'est vrai par construction, pas par un garde."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    for mid in _models(eng):
        _kill(eng, mid)
    assert _rule_ids(eng, "101") == set()


def test_escouade_sans_character_perd_ses_regles_a_la_derniere_figurine():
    """Le sens « descendant » vaut aussi sans character : une unité morte n'a plus de règle."""
    eng = _load(_scenario([_BODYGUARD, _ENEMY]))
    mids = _models(eng)
    for mid in mids[:-1]:
        _kill(eng, mid)
    assert _rule_ids(eng, "101") == {"targeted_intercession"}
    _kill(eng, mids[-1])
    assert _rule_ids(eng, "101") == set()


def test_marqueur_dattachement_sur_la_figurine():
    """La figurine repliée porte l'id de son unité d'origine jusque dans models_cache."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    models_cache = eng.game_state["models_cache"]
    attached = [
        mid for mid in eng.game_state["squad_models"]["101"]
        if "attached_from" in models_cache[mid]
    ]
    assert len(attached) == 1
    assert models_cache[attached[0]]["attached_from"] == "102"
    assert models_cache[attached[0]]["unitType"] == "CaptainPowerWeaponBolter"
