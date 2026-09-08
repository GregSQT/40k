#!/usr/bin/env python3
"""Conformité des mots-clés de terrain (PDF `13 Terrain`, règles 13.06 / 13.08 / 13.09).

Texte de référence, relevé dans le PDF :

    13.06 SETTING UP OR ENDING A MOVE
        « That model has one or more of the following keywords:
          INFANTRY/BEASTS/SWARM/FLY/MONSTER. »

    13.08 BENEFIT OF COVER
        « That model has the INFANTRY/BEASTS/SWARM keyword and is within a terrain area. »

    13.09 HIDDEN
        « That model has the INFANTRY/BEASTS/SWARM keyword and is within a terrain area
          that contains one or more dense terrain features. »

Le défaut d'origine portait sur BEASTS, et ses deux moitiés se COMPENSAIENT :

1. **Constante moteur au singulier** — `_HIDEABLE_KEYWORDS` portait `"beast"`, donc une unité
   déclarant le mot-clé officiel `BEASTS` n'était ni hideable (13.08/13.09) ni autorisée à finir
   un move en hauteur (13.06). `FenrisianWolf` était la victime : il porte `beasts`, `imperium`
   et `fenrisian wolves`, donc aucun mot-clé de secours.
2. **Datasheet au singulier** — `Mucolid` déclarait `beast`, non conforme au PDF. La
   compensation ne le sauvait que pour le hideable 13.08/13.09 : il porte aussi `fly`, donc il
   restait autorisé à finir en hauteur quelle que soit l'orthographe.

Le verrou porte désormais sur les CINQ mots-clés lus par le moteur, pas sur BEASTS seul, et le
PDF sert de référence aux DEUX côtés — moteur et donnée. C'est le point essentiel : dériver
l'attendu d'un côté à partir de l'autre laisse une faute partagée passer au vert, ce qui est
exactement ce qui s'était produit.
"""

from __future__ import annotations

import pytest

from ai.unit_registry import UnitRegistry
from engine.game_state import (
    _FLOOR_CAPABLE_KEYWORDS,
    _HIDEABLE_KEYWORDS,
    compute_hideable,
    unit_can_occupy_upper_floor,
)

#: Forme officielle du mot-clé (PDF 13.06/13.08/13.09), en minuscules — la convention de lecture
#: du moteur est `keywordId` strip/lower.
OFFICIAL_BEASTS = "beasts"

#: Formes officielles relevées dans le PDF, figées ICI et jamais dérivées du moteur ni des
#: datasheets : c'est la seule référence qu'une faute présente des deux côtés ne peut pas suivre.
OFFICIAL_HIDEABLE = frozenset({"infantry", OFFICIAL_BEASTS, "swarm"})
OFFICIAL_FLOOR_CAPABLE = OFFICIAL_HIDEABLE | {"fly", "monster"}


@pytest.fixture(scope="module")
def registry_units():
    """Datasheets réelles du dépôt — le contrat porte sur elles, pas sur des fixtures."""
    return UnitRegistry().units


@pytest.mark.parametrize("written", ["BEASTS", "Beasts", "beasts", " BEASTS "])
def test_beasts_keyword_grants_hideable(written):
    """13.08/13.09 : le mot-clé officiel BEASTS rend l'unité hideable, quelle que soit sa casse."""
    assert compute_hideable([{"keywordId": written}]) is True


@pytest.mark.parametrize("written", ["BEASTS", "Beasts", "beasts", " BEASTS "])
def test_beasts_keyword_grants_upper_floor(written):
    """13.06 : le mot-clé officiel BEASTS autorise à finir un move hors rez-de-chaussée."""
    assert unit_can_occupy_upper_floor([{"keywordId": written}]) is True


def test_engine_constants_match_pdf_spelling():
    """Côté moteur : les constantes lues écrivent EXACTEMENT les mots-clés du PDF.

    C'est le contrôle qui aurait vu le défaut d'origine. Le comparer à une référence figée sur
    le PDF est indispensable : un attendu dérivé des datasheets serait resté vert, puisque
    `Mucolid` portait alors la même faute que la constante.
    """
    assert set(_HIDEABLE_KEYWORDS) == OFFICIAL_HIDEABLE, (
        f"_HIDEABLE_KEYWORDS={_HIDEABLE_KEYWORDS} diverge du PDF 13.08/13.09, qui écrit "
        f"{sorted(OFFICIAL_HIDEABLE)}"
    )
    assert set(_FLOOR_CAPABLE_KEYWORDS) == OFFICIAL_FLOOR_CAPABLE, (
        f"_FLOOR_CAPABLE_KEYWORDS={_FLOOR_CAPABLE_KEYWORDS} diverge du PDF 13.06 « setting up "
        f"or ending a move », qui écrit {sorted(OFFICIAL_FLOOR_CAPABLE)}"
    )


def _edit_distance(left: str, right: str) -> int:
    """Distance de Levenshtein — sépare une faute de frappe d'un mot-clé réellement distinct."""
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, 1):
        current = [i]
        for j, char_right in enumerate(right, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_left != char_right),
                )
            )
        previous = current
    return previous[-1]


def test_registry_terrain_keywords_use_official_spelling(registry_units):
    """Côté donnée : aucune datasheet n'écrit une variante d'un mot-clé de terrain.

    Le prédicat est la distance d'édition 1, et non un préfixe. Mesuré sur le corpus réel, il
    attrape les quatre familles de fautes qui existent vraiment dans les rosters
    (`beast`/`beasts`, `grenade`/`grenades`, `harverster`/`harvester`, `jump pack`/`jump_pack`)
    là où un préfixe n'en voit que deux, et aucun des mots-clés distincts déclarés ne le
    déclenche à tort — les seuls qui approchent une forme officielle SONT ces formes.
    """
    offenders = {
        (name, keyword_id): official
        for name, unit in registry_units.items()
        for keyword_id in (
            str(entry["keywordId"]).strip().lower() for entry in unit["UNIT_KEYWORDS"]
        )
        for official in OFFICIAL_FLOOR_CAPABLE
        if keyword_id != official and _edit_distance(keyword_id, official) == 1
    }
    assert offenders == {}, (
        f"datasheets écrivant une variante d'un mot-clé de terrain : {offenders} — "
        f"13.06/13.08/13.09 écrivent {sorted(OFFICIAL_FLOOR_CAPABLE)}"
    )


def test_registry_beasts_units_are_hideable_and_floor_capable(registry_units):
    """Bout en bout : chaque unité BEASTS du registre obtient bien les deux droits de 13.x."""
    beasts_units = {
        name: unit["UNIT_KEYWORDS"]
        for name, unit in registry_units.items()
        if any(
            str(entry["keywordId"]).strip().lower() == OFFICIAL_BEASTS
            for entry in unit["UNIT_KEYWORDS"]
        )
    }
    # Énumération non vide : sans porteur, les deux assertions ci-dessous seraient vertes à vide.
    assert beasts_units, "aucune datasheet BEASTS dans le registre — le contrat ne teste rien"
    for name, keywords in beasts_units.items():
        assert compute_hideable(keywords) is True, f"{name} : BEASTS doit être hideable (13.08)"
        assert unit_can_occupy_upper_floor(keywords) is True, (
            f"{name} : BEASTS doit pouvoir finir en hauteur (13.06)"
        )
