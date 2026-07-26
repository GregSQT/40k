"""`reroll_charge` (config/unit_rules.json) — « Unstoppable Valour », jamais implémentée jusqu'ici.

« When this unit makes a charge, it can reroll the charge roll. » Règle d'UNITÉ portée par 4
unités Orks des rosters (Bigboss, BannerNob, BoyzNobKustomShoota, Gretchin) et déclarée dans
`config/unit_rules.json` — mais absente du code (grep zéro avant cette tranche).

Décision du « can » (documentée) : on relance sur le SEUL critère exact et disponible — le jet
n'atteint aucune destination légale au contact de la cible. Un dé ne se relance qu'une fois
(PDF 01 Core, Re-rolls).

Lien 19.04 (Abilities in attached units) : la règle du leader vaut pour toute l'unité attachée.
Les tests ci-dessous fabriquent un `game_state` à la main et ne passent par AUCUNE unité attachée
réelle — c'est ce qui avait laissé passer le trou 19.04 (les règles du character restaient sur
`models[i]`, lues par personne). Le câblage attaché est verrouillé, lui, par
`test_attached_units_abilities_19_04.py` sur un vrai chargement de scénario.
"""
import pytest

from engine.phase_handlers.shared_utils import unit_can_reroll_charge


def _gs(unit_rules):
    return {"unit_by_id": {"1": {"id": "1", "UNIT_RULES": list(unit_rules)}}}


def test_regle_detectee_sur_l_unite():
    """L'unité qui déclare reroll_charge est reconnue."""
    assert unit_can_reroll_charge(_gs([{"ruleId": "reroll_charge"}]), "1") is True


def test_absence_de_regle():
    """Contre-épreuve : sans la règle, aucun reroll."""
    assert unit_can_reroll_charge(_gs([]), "1") is False


def test_autre_regle_ne_declenche_pas():
    """Discrimination : une autre règle d'unité ne donne pas le reroll de charge."""
    assert unit_can_reroll_charge(_gs([{"ruleId": "reroll_1_towound"}]), "1") is False


def test_unite_introuvable_leve():
    """Aucun repli masquant : une unité inconnue est un bug, pas un 'False' silencieux."""
    with pytest.raises(KeyError):
        unit_can_reroll_charge({"unit_by_id": {}}, "404")


def test_roster_ork_declare_bien_la_regle():
    """Ancrage données : les unités Orks des rosters de training portent bien la règle
    (sinon ce travail serait mort — c'est exactement le piège que §9.0 documente)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    porteurs = [
        p.name for p in (root / "frontend/src/roster/ork/units").glob("*.ts")
        if re.search(r'ruleId:\s*"reroll_charge"', p.read_text())
    ]
    assert porteurs, "aucune unité Ork ne déclare reroll_charge : fixture/donnée à revérifier"
