#!/usr/bin/env python3
"""Conformité du mot-clé BEASTS (PDF `13 Terrain`, règles 13.06 / 13.08 / 13.09).

Texte de référence, où le mot-clé est écrit au PLURIEL aux trois endroits :

    13.06 SETTING UP OR ENDING A MOVE
        « That model has one or more of the following keywords:
          INFANTRY/BEASTS/SWARM/FLY/MONSTER. »

    13.08 BENEFIT OF COVER
        « That model has the INFANTRY/BEASTS/SWARM keyword and is within a terrain area. »

    13.09 HIDDEN
        « That model has the INFANTRY/BEASTS/SWARM keyword and is within a terrain area
          that contains one or more dense terrain features. »

Deux défauts sont verrouillés ici, et ils se COMPENSAIENT :

1. **Constante moteur au singulier** — `_HIDEABLE_KEYWORDS` portait `"beast"`, donc une unité
   déclarant le mot-clé officiel `BEASTS` n'était ni hideable (13.08/13.09) ni autorisée à finir
   un move en hauteur (13.06). `FenrisianWolf`, conforme au PDF, était la victime.
2. **Datasheet au singulier** — `Mucolid` déclarait `beast`, non conforme au PDF, et ne
   fonctionnait que parce que la constante portait la même faute. Corriger la constante seule
   l'aurait cassée : les deux moitiés doivent bouger ensemble.
"""

from __future__ import annotations

import pytest

from ai.unit_registry import UnitRegistry
from engine.game_state import (
    compute_hideable,
    unit_can_occupy_upper_floor,
)

#: Forme officielle du mot-clé (PDF 13.06/13.08/13.09), en minuscules — la convention de lecture
#: du moteur est `keywordId` strip/lower.
OFFICIAL_BEASTS = "beasts"


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


def test_registry_beasts_datasheets_use_official_plural(registry_units):
    """Contrat de données : toute datasheet de la famille BEASTS écrit la forme du PDF."""
    offenders = {
        name: keyword_id
        for name, unit in registry_units.items()
        for keyword_id in (
            str(entry["keywordId"]).strip().lower() for entry in unit["UNIT_KEYWORDS"]
        )
        if keyword_id.startswith("beast") and keyword_id != OFFICIAL_BEASTS
    }
    assert offenders == {}, (
        f"datasheets déclarant une forme non officielle du mot-clé BEASTS : {offenders} — "
        f"13.06/13.08/13.09 l'écrivent {OFFICIAL_BEASTS.upper()}"
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
