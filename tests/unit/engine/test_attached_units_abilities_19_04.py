"""Règle 19.04 (Abilities in attached units) — les règles d'unité valent pour l'unité attachée.

PDF 19.04 : « abilities/rules that affect a unit (or models in it) apply to every model in an
attached unit, until the source of that ability/rule is destroyed ». Le tableau du PDF donne la
durée de vie de chaque source : règle du bodyguard → jusqu'à la mort de sa dernière figurine ;
règle du leader/support → jusqu'à la mort de la dernière figurine de CE leader/support (le PDF
précise même que le leader garde ses propres règles après la destruction de son bodyguard).

Vérifié BOUT-EN-BOUT via le vrai chemin de chargement (`load_units_from_scenario` →
`_fold_attached_characters` → `_build_enhanced_unit`) puis via le vrai lecteur
(`unit_has_rule_effect`, celui qu'appellent tous les consommateurs de règles d'unité), jamais
sur la fonction d'union isolée : le trou corrigé ici était exactement un défaut de CÂBLAGE (la
fonction d'union n'existait pas, les règles du character restaient sur `models[i]` et aucun
consommateur ne les lisait).

Fixtures choisies pour être discriminantes dans les deux sens : `AssaultIntercessorJumpPack`
porte `charge_impact` et PAS `deep_strike` ; `ChaplainJumpPack` porte `deep_strike` et PAS
`charge_impact`, et 19.01 l'autorise à mener cette escouade (son `CAN_LEAD` couvre le keyword
« ASSAULT INTERCESSORS WITH JUMP PACKS »).

⚠️ Ces fixtures ont changé le 2026-08-10. Elles reposaient sur `CaptainPowerWeaponBolter` et
son `reroll_charge` — un placeholder INVENTÉ (« Unstoppable Valour »), absent de toute
datasheet, que le chantier 05 a purgé. Ce fichier était son dernier utilisateur, et c'est à ce
titre qu'il avait survécu à la purge quelques heures. Ne pas réintroduire une capacité fictive
pour la commodité d'un test : le couple ci-dessus vient de deux vraies datasheets.
"""
from __future__ import annotations

from typing import List

from tests.unit.engine._config_helpers import (
    ATTACHED_BODYGUARD as _BODYGUARD,
    ATTACHED_BODYGUARD_RULE as _REGLE_DU_BODYGUARD,
    ATTACHED_ENEMY as _ENEMY,
    ATTACHED_LEADER as _LEADER,
    ATTACHED_LEADER_RULE as _REGLE_DU_LEADER,
    attached_scenario as _scenario,
    load_engine_from_scenario as _load,
)


def _rule_ids(engine, unit_id: str) -> set:
    unit = engine.game_state["unit_by_id"][unit_id]
    return {str(r["ruleId"]) for r in unit["UNIT_RULES"]}


def _porte_la_regle_du_leader(engine) -> bool:
    """L'unité attachée bénéficie-t-elle de la règle conférée par le leader ?

    Passe par `unit_has_rule_effect` — le lecteur que TOUS les consommateurs de règles d'unité
    appellent (éligibilité de charge, de tir, seuils…). Interroger ce lecteur plutôt qu'un
    consommateur particulier vérifie le même câblage sans dépendre de la règle du jour : c'est
    ce qui avait rendu ce fichier otage d'une capacité inventée.
    """
    from engine.phase_handlers.shared_utils import unit_has_rule_effect

    return unit_has_rule_effect(engine.game_state["unit_by_id"]["101"], _REGLE_DU_LEADER)


def test_regle_du_leader_sapplique_a_lunite_attachee():
    """19.04 montant : Deep Strike du Chaplain vaut pour l'escouade entière.

    C'est le bug d'origine : attaché, le Chaplain n'est plus une unité, et sa règle n'était
    portée que par sa figurine — donc lue par personne.
    """
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    assert _REGLE_DU_LEADER in _rule_ids(eng, "101")
    # Le vrai consommateur, pas seulement le champ.
    assert _porte_la_regle_du_leader(eng) is True


def test_regle_du_bodyguard_conservee():
    """L'union n'écrase rien : la règle propre de l'escouade reste en vigueur."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    assert _REGLE_DU_BODYGUARD in _rule_ids(eng, "101")


def test_escouade_sans_character_inchangee():
    """Contre-épreuve : sans character attaché, l'unité garde exactement ses règles."""
    eng = _load(_scenario([_BODYGUARD, _ENEMY]))
    assert _rule_ids(eng, "101") == {_REGLE_DU_BODYGUARD}
    assert _porte_la_regle_du_leader(eng) is False


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
    assert roles.count("leader") == 1, "seule la figurine du Chaplain est leader"
    assert roles.count(None) == 3, "les 3 Assault Intercessors restent des figurines de base"


def test_provenance_des_regles_separee_par_source():
    """Les deux sources 19.04 sont distinguées — prérequis de l'extinction (tranche -b).

    Sans cette séparation, impossible de savoir laquelle éteindre quand une figurine meurt.
    """
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    unit = eng.game_state["unit_by_id"]["101"]
    assert [r["ruleId"] for r in unit["_UNIT_RULES_OWN"]] == [_REGLE_DU_BODYGUARD]
    assert {k: [r["ruleId"] for r in v] for k, v in unit["_ATTACHED_RULE_GROUPS"].items()} == {
        "102": [_REGLE_DU_LEADER]
    }


def _kill(engine, model_id: str) -> None:
    from engine.phase_handlers.shared_utils import destroy_model

    destroy_model(engine.game_state, model_id, "combat")


def _models(engine) -> List[str]:
    return list(engine.game_state["squad_models"]["101"])


def _leader_mid(engine) -> str:
    """Id de la figurine du CHARACTER replié dans l'escouade.

    `attached_from` est le marqueur de provenance posé par `_fold_attached_characters` : c'est
    lui, et non l'ordre des figurines, qui distingue le leader des bodyguards. Cinq tests
    avaient besoin de cette figurine — recopier la recherche à chaque fois laissait à chacun la
    possibilité de la retrouver autrement, donc de ne plus tester la même chose.
    """
    return next(
        mid for mid in _models(engine)
        if "attached_from" in engine.game_state["models_cache"][mid]
    )


def test_mort_du_leader_eteint_sa_regle():
    """19.04 : « until the last model in that leader/support unit is destroyed ».

    Le Chaplain mort, l'escouade perd son Deep Strike — et garde la sienne.
    """
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = _leader_mid(eng)
    assert _porte_la_regle_du_leader(eng) is True

    _kill(eng, leader_mid)

    assert _porte_la_regle_du_leader(eng) is False
    assert _rule_ids(eng, "101") == {_REGLE_DU_BODYGUARD}


def test_mort_des_bodyguards_eteint_la_regle_du_datasheet_pas_celle_du_leader():
    """19.04 : « until the last model in that bodyguard unit is destroyed », plus la note du
    PDF « leader/support units continue to benefit from their own abilities even after their
    bodyguard unit is destroyed, provided they started the battle in an attached unit »."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    models_cache = eng.game_state["models_cache"]
    natives = [mid for mid in _models(eng) if "attached_from" not in models_cache[mid]]
    assert len(natives) == 3

    for mid in natives[:-1]:
        _kill(eng, mid)
    assert _rule_ids(eng, "101") == {_REGLE_DU_BODYGUARD, _REGLE_DU_LEADER}, (
        "tant qu'un bodyguard vit, les deux sources sont en vigueur"
    )

    _kill(eng, natives[-1])
    assert _rule_ids(eng, "101") == {_REGLE_DU_LEADER}
    assert _porte_la_regle_du_leader(eng) is True


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
    assert _rule_ids(eng, "101") == {_REGLE_DU_BODYGUARD}
    _kill(eng, mids[-1])
    assert _rule_ids(eng, "101") == set()


def _open_shoot_allocation(engine, attacker_sid: str = "1", target_sid: str = "101") -> None:
    """Ouvre une activation de tir minimale — ce que lisent `destroy_model` et
    `_finalize_manual_allocation` (clé réelle `pending_shoot_allocation` de SHOOT_CTX)."""
    engine.game_state["pending_shoot_allocation"] = {
        "attacker_squad_id": attacker_sid,
        "summary": {"targets_meta": {target_sid: {}}},
        "weapon_groups": [],
    }


def test_source_tuee_par_une_attaque_confere_encore_sa_regle():
    """19.04, dernière clause : « if that last model was destroyed as the result of an attack,
    the ability it was conferring upon the attached unit applies until the attacking unit has
    resolved all of its attacks »."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = _leader_mid(eng)
    _open_shoot_allocation(eng)

    _kill(eng, leader_mid)

    assert leader_mid not in eng.game_state["models_cache"], "la figurine est bien morte"
    assert _porte_la_regle_du_leader(eng) is True, (
        "la règle survit jusqu'à la fin des attaques de l'attaquant"
    )


def test_la_fenetre_se_referme_a_la_fin_des_attaques():
    """Câblage : c'est `_finalize_manual_allocation` (« after that unit has resolved all of its
    attacks », même point que HAZARDOUS 24.15) qui éteint la règle en sursis."""
    from engine.phase_handlers.shared_utils import SHOOT_CTX, _finalize_manual_allocation

    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = _leader_mid(eng)
    _open_shoot_allocation(eng)
    _kill(eng, leader_mid)
    assert _porte_la_regle_du_leader(eng) is True

    _finalize_manual_allocation(eng.game_state, SHOOT_CTX)

    assert _porte_la_regle_du_leader(eng) is False
    assert _rule_ids(eng, "101") == {_REGLE_DU_BODYGUARD}


def test_pas_de_sursis_hors_attaque():
    """Discrimination : le sursis du PDF est conditionné à « destroyed as the result of an
    attack ». Un retrait de cohérence (03.03) éteint la règle immédiatement, même si une
    activation de tir est ouverte par ailleurs."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = _leader_mid(eng)
    _open_shoot_allocation(eng)

    destroy_model(eng.game_state, leader_mid, "coherency_removal")

    assert _porte_la_regle_du_leader(eng) is False


def test_pas_de_sursis_sans_activation_ouverte():
    """Hors activation, la mort éteint immédiatement : le sursis n'est pas un délai global."""
    eng = _load(_scenario([_BODYGUARD, _LEADER, _ENEMY]))
    leader_mid = _leader_mid(eng)
    assert "pending_shoot_allocation" not in eng.game_state

    _kill(eng, leader_mid)

    assert _porte_la_regle_du_leader(eng) is False


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
    assert models_cache[attached[0]]["unitType"] == _LEADER["unit_type"]
