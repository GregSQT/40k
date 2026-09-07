"""L'applicabilité des règles d'ARMES se dérive de l'armurerie, comme celle des capacités.

Une règle conditionnée à un token d'arme était déclarée `always` dans le corpus : le rapport la
rendait alors « Applicable et jamais exercée — la situation s'est presentee et aucun controle
n'a rien juge », alors que la situation ne s'était PAS présentée (aucune arme jouée ne porte le
token). C'est l'avertissement qui est la raison d'être du module ; le noyer sous des lignes
fausses le rend illisible.

LE PROFIL EST INDISPENSABLE. Mesuré sur l'armurerie du 2026-09-07 : HAZARDOUS est porté par 21
armes de TIR et par AUCUNE arme de mêlée, LETHAL_HITS par 3 de tir et 1 de mêlée. Un prédicat
« ce token est-il quelque part dans le roster ? » déclarerait donc `PROJ.1.4.hazardous` (mêlée)
applicable au motif qu'un pistolet plasma le porte — exactement le faux avertissement qu'on
retire. C'est pour ça que `weapon_rule_to_units` indexe par `(token, profil)`.
"""
from __future__ import annotations

import pytest

from ai.analyzer_rules import load_rules_corpus, rule_is_applicable


def _entree(rule_id: str) -> dict:
    return next(e for e in load_rules_corpus() if e["id"] == rule_id)


def _stats(carriers: dict, vus: set) -> dict:
    return {"weapon_rule_to_units": carriers, "unit_types_seen": vus}


def test_token_absent_de_larmurerie_rend_hors_roster() -> None:
    """Aucune arme jouée ne porte TORRENT → la règle ne pouvait pas servir."""
    stats = _stats({"TORRENT": {"ranged": {"Autre"}, "melee": set()}}, {"Intercessor"})
    assert rule_is_applicable(stats, _entree("PROJ.1.2.torrent")) is False


def test_token_porte_par_une_unite_jouee_rend_applicable() -> None:
    stats = _stats({"TORRENT": {"ranged": {"Intercessor"}, "melee": set()}}, {"Intercessor"})
    assert rule_is_applicable(stats, _entree("PROJ.1.2.torrent")) is True


def test_le_profil_separe_le_tir_de_la_melee() -> None:
    """LE cas mesuré : HAZARDOUS sur un pistolet plasma ne rend pas la règle de MÊLÉE applicable."""
    stats = _stats({"HAZARDOUS": {"ranged": {"VanguardVeteran"}, "melee": set()}}, {"VanguardVeteran"})
    assert rule_is_applicable(stats, _entree("PROJ.1.2.hazardous")) is True
    assert rule_is_applicable(stats, _entree("PROJ.1.4.hazardous")) is False, (
        "sans le grain tir/mêlée, la règle de mêlée hérite du token d'une arme de tir"
    )


def test_token_inconnu_du_registre_rend_hors_roster() -> None:
    """Un token qu'aucune arme de l'armurerie ne porte : `.get` de repli, pas de KeyError."""
    assert rule_is_applicable(_stats({}, {"Intercessor"}), _entree("PROJ.1.2.blast")) is False


def test_un_profil_inconnu_leve_au_lieu_de_se_replier() -> None:
    """T1 : un corpus qui écrit 'ranged '/'Melee'/'both' doit CASSER, pas rendre False en silence."""
    entree = dict(_entree("PROJ.1.2.torrent"))
    entree["applicability"] = {"kind": "weapon_rule_in_roster", "rule_id": "TORRENT", "profile": "both"}
    with pytest.raises(ValueError, match="profil d'arme"):
        rule_is_applicable(_stats({}, set()), entree)


def test_le_registre_reel_porte_le_grain_des_deux_cotes() -> None:
    """VERT VACANT : les tests ci-dessus valent ce que vaut le registre construit en vrai.

    Sans cette vérification, ils passeraient tous sur un `weapon_rule_to_units` qui n'aurait
    jamais été rempli — la donnée mesurée le 2026-09-07 est qu'HAZARDOUS existe côté tir et
    n'existe pas côté mêlée, et c'est CE fait qui rend la ligne du rapport honnête.
    """
    from ai.analyzer_config import load_analyzer_config, set_run_inches_to_subhex

    set_run_inches_to_subhex(1)
    cfg = load_analyzer_config()
    par_token = cfg.weapon_rule_to_units

    assert par_token["HAZARDOUS"]["ranged"], "aucune arme de tir HAZARDOUS dans l'armurerie ?"
    assert par_token["HAZARDOUS"]["melee"] == set(), "l'armurerie a changé : HAZARDOUS en mêlée"
    assert par_token["LETHAL_HITS"]["ranged"] and par_token["LETHAL_HITS"]["melee"], (
        "LETHAL_HITS doit exister des DEUX côtés — c'est le cas qui exige le grain"
    )
    # `COMBI` n'est pas un token d'armurerie : il est dérivé d'`unit_combi_by_weapon`, la table
    # que lit le contrôle `shoot_combi_profile_conflicts`.
    assert par_token["COMBI"]["ranged"] & set(cfg.unit_combi_by_weapon), (
        "la clé COMBI ne désigne pas les types porteurs d'une arme à profils multiples"
    )
