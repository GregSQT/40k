"""Lecture des sources TypeScript : une apostrophe dans un nom ne tronque plus la valeur.

DÉFAUT CORRIGÉ (2026-08-04, mesuré). `ai/unit_registry.py` lisait les chaînes TS avec
``["\\']([^"\\']+)["\\']`` : le motif ouvre sur `"` OU `'` et referme sur l'un ou l'autre, donc il
s'arrête à la PREMIÈRE apostrophe interne. `displayName: "Thievin' Scavengers"` (Gretchin, ajouté
par le chantier 02) rendait ``'Thievin'``. Silencieusement : aucune exception, une valeur
simplement fausse, qui part dans le payload de l'API et s'affiche telle quelle dans le badge de
règle du panneau PvP.

C'était un JUMEAU non traité : `engine/weapons/parser.py` avait exactement le même bug, corrigé
en V11 T6 pour les noms d'armes Orks (« Dok's Tools », « 'eadbanger »), et le parseur d'unités
avait gardé le motif naïf. Les deux lisent désormais le MÊME motif
(`shared/ts_parsing.TS_QUOTED_STRING`), et c'est ce partage que ce fichier verrouille — un test
qui n'aurait vérifié que Gretchin laisserait le motif se dupliquer et re-diverger.
"""
from __future__ import annotations

import re

import pytest

from shared.ts_parsing import TS_QUOTED_STRING


# ─────────────────────────────────────────────────────────────────────────────
# Le motif lui-même
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "source,expected",
    [
        ('displayName: "Thievin\' Scavengers"', "Thievin' Scavengers"),
        ('display_name: "Dok\'s Tools"', "Dok's Tools"),
        ('display_name: "\'eadbanger"', "'eadbanger"),
        ('display_name: "\'Waaagh! Staff"', "'Waaagh! Staff"),
        # Guillemets simples : comportement inchangé, la fermeture suit l'ouverture.
        ("displayName: 'Unstoppable Valour'", "Unstoppable Valour"),
        ('displayName: "Unstoppable Valour"', "Unstoppable Valour"),
    ],
)
def test_une_chaine_ts_se_ferme_sur_son_propre_guillemet(source: str, expected: str) -> None:
    match = re.search(r"\w+\s*:\s*" + TS_QUOTED_STRING, source)
    assert match is not None, f"aucun match sur {source!r}"
    assert match.group(2) == expected


def test_le_motif_naif_tronquait_bien(  ) -> None:
    """CONTRE-ÉPREUVE : sans la backreference, la même entrée est tronquée.

    Sans ce test, rien ne prouve que les cas ci-dessus discriminent quoi que ce soit — ils
    passeraient tous avec un motif qui se contenterait de « prendre tout jusqu'au bout ».
    """
    naive = r'["\']([^"\']+)["\']'
    match = re.search(r"\w+\s*:\s*" + naive, 'displayName: "Thievin\' Scavengers"')
    assert match is not None
    assert match.group(1) == "Thievin", (
        "le motif naïf ne tronque plus : ce test ne discrimine donc plus rien"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Le vrai chemin : la datasheet, lue par le vrai parseur
# ─────────────────────────────────────────────────────────────────────────────

def test_le_nom_affiche_de_thievin_scavengers_est_complet() -> None:
    """Bout en bout, par le VRAI chargement d'une datasheet — pas sur le motif isolé.

    Le défaut n'était pas dans la regex prise à part (elle « marchait » sur tous les noms
    existants), il était dans ce que le parseur en fait sur une datasheet réelle.
    """
    from ai.unit_registry import UnitRegistry

    rules = UnitRegistry().get_unit_data("Gretchin")["UNIT_RULES"]
    by_id = {str(rule["ruleId"]): str(rule["displayName"]) for rule in rules}
    assert by_id["cp_gain_on_objective"] == "Thievin' Scavengers"
    # Témoin SANS apostrophe : il prouve que le correctif n'a pas changé la lecture du cas
    # nominal. Il vient d'une autre datasheet depuis le chantier 05 — la seconde règle de
    # Gretchin était le placeholder « Unstoppable Valour », purgé parce qu'inventé.
    autre = UnitRegistry().get_unit_data("AggressorBoltStorm")["UNIT_RULES"]
    assert {str(r["ruleId"]): str(r["displayName"]) for r in autre}[
        "closest_target_penetration"
    ] == "Close-quarter firepower"


def test_aucun_nom_de_regle_de_roster_nest_tronque() -> None:
    """Balayage de TOUTES les datasheets : aucune valeur tronquée ne subsiste.

    ⚠️ La comparaison est une ÉGALITÉ à la valeur déclarée, pas une inclusion dans le texte
    source : `"Thievin"` EST une sous-chaîne de `"Thievin' Scavengers"`, donc un test par
    `in source` aurait été vert sur le défaut même qu'il prétend attraper. C'est le piège que
    la première version de ce test a effectivement posé.

    ⚠️ Le test échoue aussi si le balayage ne rend presque aucune règle (vert vacant).
    """
    from pathlib import Path

    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    roster_dir = Path(__file__).resolve().parents[3] / "frontend" / "src" / "roster"
    declared_pattern = re.compile(r"displayName\s*:\s*" + TS_QUOTED_STRING)
    checked = 0
    for unit_type in sorted(registry.units):
        sources = list(roster_dir.rglob(f"{unit_type}.ts"))
        if not sources:
            continue
        declared = {
            match.group(2)
            for path in sources
            for match in declared_pattern.finditer(path.read_text(encoding="utf-8"))
        }
        for rule in registry.get_unit_data(unit_type)["UNIT_RULES"]:
            display_name = str(rule["displayName"])
            assert display_name in declared, (
                f"{unit_type} : la règle lue porte displayName {display_name!r}, qui ne figure "
                f"pas parmi les noms DÉCLARÉS {sorted(declared)} — la lecture l'a tronqué"
            )
            checked += 1

    # Plancher MESURÉ, pas deviné : 80 règles d'unité sur 179 datasheets au 2026-08-04. Le seuil
    # est là pour attraper une énumération qui ne rend rien (vert vacant), pas pour figer un
    # décompte qui bouge à chaque datasheet ajoutée.
    assert checked >= 60, (
        f"seulement {checked} règles balayées : l'énumération ne regarde presque rien"
    )
