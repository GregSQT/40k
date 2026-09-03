"""Le terrain SÉLECTIONNÉ est le terrain CHARGÉ — verrou sur la table de suffixes.

Le sélecteur de terrain ne nomme pas un fichier : il nomme un identifiant (`mc1`, `mc2`) que
`_terrain_scenario_suffix` traduit en SUFFIXE de scénario (`""` pour le terrain déclaré défaut du
mode, `"_<id>"` sinon). Rien ne garantissait que le fichier ainsi désigné contienne bien le terrain
demandé : `default_for` (dans `terrain_list.json`) et `terrain_ref` (dans chaque scénario) sont deux
données indépendantes, et elles ont divergé — choisir « Terrain 1 » en `pvp_test` chargeait
`scenario_pvp_test.json`, qui porte `terrain-mc2.json`.

Le symptôme est silencieux : le front dessine et le moteur joue le MÊME fichier, donc rien ne
plante ; seul le décor n'est pas celui qu'on a demandé. C'est ce test, et lui seul, qui relie les
deux données.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.api_server import (
    MODES_WITH_TERRAIN_SELECTOR,
    _TERRAIN_LIST_ENTRIES,
    _terrain_scenario_suffix,
)

_SCENARIO_DIR = Path("config/board/44x60x5/scenario")


def _selectable() -> list[tuple[str, str]]:
    """(mode, terrain_id) pour chaque combinaison réellement offerte par le sélecteur."""
    out: list[tuple[str, str]] = []
    for mode in sorted(MODES_WITH_TERRAIN_SELECTOR):
        for entry in _TERRAIN_LIST_ENTRIES:
            if mode in entry["modes"]:
                out.append((mode, entry["id"]))
    return out


def test_selectable_combinations_are_not_empty() -> None:
    """VERT VACANT : sans cette garde, une table vide ferait passer le test suivant."""
    combos = _selectable()
    assert len(combos) >= 4, f"table de terrains anormalement petite : {combos}"


@pytest.mark.parametrize(("mode", "terrain_id"), _selectable())
def test_selected_terrain_is_the_loaded_terrain(mode: str, terrain_id: str) -> None:
    scenario = _SCENARIO_DIR / f"scenario_{mode}{_terrain_scenario_suffix(mode, terrain_id)}.json"
    assert scenario.exists(), (
        f"mode {mode!r} + terrain {terrain_id!r} désigne {scenario}, qui n'existe pas"
    )
    with open(scenario, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    assert data["terrain_ref"] == f"terrain-{terrain_id}.json", (
        f"mode {mode!r} : choisir {terrain_id!r} charge {scenario.name}, "
        f"qui porte {data['terrain_ref']!r}"
    )
