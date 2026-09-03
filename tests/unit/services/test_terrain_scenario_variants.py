"""Chaque terrain proposé par le popup mène à un plateau RÉELLEMENT différent.

Le sélecteur de terrain se contentait d'exister : en mode PvP il ne servait à rien — le serveur
chargeait `scenario_pvp.json` quel que soit le terrain demandé, donc toujours `terrain-mc2`. Rien
ne rougissait, parce que le seul test qui touchait le sujet vérifiait que le scénario par défaut
se charge, pas que deux terrains différents donnent deux plateaux différents.

C'est ce maillon que ce fichier verrouille : pour chaque valeur acceptée de `terrain_ref`, le
scénario résolu existe, se charge, et déclare un fichier de terrain qui n'est celui d'aucun
autre. Un suffixe oublié ramène deux terrains sur le même fichier et rougit ici.
"""

import json
import os
import pathlib
from collections import Counter

import pytest

from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader
from engine.game_state import GameStateManager
from services.api_server import (
    MODES_WITH_TERRAIN_SELECTOR,
    TERRAIN_SCENARIO_SUFFIX_BY_MODE,
    TEST_SCENARIO_BOARD_MAP,
    VALID_TERRAIN_REFS,
    _default_board_scenario_path,
    _terrain_scenario_suffix,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
# Chaque mode qui expose le sélecteur, et le scénario que son suffixe complète.
_MODES = {
    "pvp": "scenario_pvp",
    "pve": "scenario_pve",
    "pvp_test": "scenario_pvp_test",
    "pve_test": "scenario_pve_test",
}
_MODES_A_BOARD_PATH = ("pvp_test", "pve_test")
_MODES_A_SELECTEUR = tuple(sorted(MODES_WITH_TERRAIN_SELECTOR))


def _terrains(mode: str) -> list[str]:
    return sorted(TERRAIN_SCENARIO_SUFFIX_BY_MODE[mode])


def _resolve(mode: str, terrain_ref: str) -> str:
    base = _MODES[mode]
    suffix = _terrain_scenario_suffix(mode, terrain_ref)
    if mode not in _MODES_A_BOARD_PATH:
        return _default_board_scenario_path(f"{base}{suffix}.json")
    board_dir = TEST_SCENARIO_BOARD_MAP["x5_44x60"]
    return os.path.join("config", board_dir, "scenario", f"{base}{suffix}.json")


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_un_terrain_non_supporte_par_le_mode_leve(mode: str):
    absents = VALID_TERRAIN_REFS - set(TERRAIN_SCENARIO_SUFFIX_BY_MODE[mode])
    for terrain_ref in sorted(absents):
        with pytest.raises(ValueError, match=terrain_ref):
            _terrain_scenario_suffix(mode, terrain_ref)
    # Un mode qui les supporte tous ne doit pas passer ce test par vacuité.
    for terrain_ref in _terrains(mode):
        _terrain_scenario_suffix(mode, terrain_ref)


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_sans_terrain_demande_le_mode_prend_son_scenario_de_base(mode: str):
    assert _terrain_scenario_suffix(mode, None) == "", (
        f"{mode} : le défaut doit être le terrain du scénario NON suffixé, sinon le plateau "
        "dessiné par le client et le plateau joué divergent"
    )


@pytest.mark.parametrize(
    ("mode", "terrain_ref"),
    [(m, t) for m in _MODES_A_SELECTEUR for t in _terrains(m)],
)
def test_le_scenario_du_terrain_se_charge(mode: str, terrain_ref: str):
    path = _resolve(mode, terrain_ref)
    assert os.path.exists(path), (
        f"terrain {terrain_ref!r} en {mode} : résolu en {path!r}, qui n'existe pas — le mode "
        "refuserait de démarrer"
    )

    unit_registry = UnitRegistry()
    manager = GameStateManager({"board": get_config_loader().get_board_config()}, unit_registry)
    result = manager.load_units_from_scenario(path, unit_registry)

    # VERT VACANT : un scénario vide passerait le simple « ça charge ».
    assert result["units"], f"{path} : scénario chargé mais sans aucune unité"
    assert result["objectives"], (
        f"{path} : aucun objectif — ils viennent des zones de terrain marquées "
        '"objective": true, leur absence signale un terrain non chargé'
    )


@pytest.mark.parametrize(
    ("mode", "terrain_ref"),
    [(m, t) for m in sorted(_MODES) for t in _terrains(m)],
)
def test_tout_terrain_accepte_resout_un_scenario_existant(mode: str, terrain_ref: str):
    """Tout `terrain_ref` que le serveur ACCEPTE doit mener à un fichier qui existe.

    Le test de chargement plus haut ne couvre que les modes à sélecteur, donc pas `pve_test`.
    Or le serveur y accepte quand même un `terrain_ref` — le client en envoie un dès que le
    terrain déclare le mode dans ses `modes` — et `pve_test` + `mc2` résolvait
    scenario_pve_test_mc2.json, fichier absent : le mode refusait de démarrer.
    """
    path = _resolve(mode, terrain_ref)
    assert os.path.exists(path), (
        f"{mode} + terrain {terrain_ref!r} : résolu en {path!r}, qui n'existe pas — "
        "le mode lèverait FileNotFoundError au démarrage"
    )


@pytest.mark.parametrize(
    ("mode", "terrain_ref"),
    [(m, t) for m in _MODES_A_SELECTEUR for t in _terrains(m)],
)
def test_le_scenario_resolu_declare_le_terrain_demande(mode: str, terrain_ref: str):
    """Le scénario résolu déclare LE terrain demandé, et pas un autre.

    Le contrôle d'unicité plus bas ne suffit pas : une INVERSION (mc1 → terrain-mc2 et
    mc2 → terrain-mc1) produit deux fichiers bien distincts, passait donc au vert, et
    laissait pourtant le joueur sur un plateau qui n'était pas celui qu'il avait choisi.
    Les murs sont vérifiés avec le décor parce qu'ils décrivent le même plateau : sinon le
    décor vient d'un plateau et les murs d'un autre.

    `deployment_zone` n'est volontairement PAS vérifié ici : c'est un nom de zone legacy,
    résolu depuis config/deployment/<board>/, où seul mc1 existe pour ce plateau. Les zones
    réelles viennent de la section `deployment_zones` du terrain_ref, donc rien n'établit
    que ce champ doive porter l'identifiant du terrain.
    """
    with open(_REPO_ROOT / _resolve(mode, terrain_ref), encoding="utf-8-sig") as f:
        scn = json.load(f)

    assert scn.get("terrain_ref") == f"terrain-{terrain_ref}.json", (
        f"{mode} + terrain {terrain_ref!r} : le scénario résolu déclare "
        f"{scn.get('terrain_ref')!r} — le plateau joué n'est pas celui sélectionné"
    )
    assert scn.get("wall_ref") == f"walls-{terrain_ref}.json", (
        f"{mode} + terrain {terrain_ref!r} : murs {scn.get('wall_ref')!r} — les murs "
        "doivent venir du même plateau que le décor"
    )


@pytest.mark.parametrize("mode", _MODES_A_SELECTEUR)
def test_deux_terrains_ne_partagent_jamais_le_meme_fichier_de_terrain(mode: str):
    par_terrain = {}
    for terrain_ref in _terrains(mode):
        with open(_REPO_ROOT / _resolve(mode, terrain_ref), encoding="utf-8-sig") as f:
            par_terrain[terrain_ref] = json.load(f)["terrain_ref"]

    counts = Counter(par_terrain.values())
    doublons = [t for t, ref in par_terrain.items() if counts[ref] > 1]
    assert not doublons, (
        f"{mode} : les terrains {sorted(doublons)} pointent le même fichier "
        f"({par_terrain}) — le sélecteur afficherait le même plateau pour des choix différents"
    )
