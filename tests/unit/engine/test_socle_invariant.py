"""Invariant du socle : `BASE_SHAPE` DÉTERMINE le type de `BASE_SIZE`.

`round`/`square` portent un diamètre scalaire, `oval` une paire `[grand axe, petit axe]`.
Rien ne le vérifiait : neuf `cast` l'affirmaient au typage (hex_utils, terrain_utils,
movement_handlers) et deux gardes correctes existaient sans être branchées.

L'invariant est désormais validé UNE FOIS, à la frontière où la donnée entre dans le moteur
(`game_state._scale_socle`, chargement de datasheet, et `GameStateManager.create_unit` pour
les unités construites hors chargement), avec une erreur qui NOMME l'unité et les deux
valeurs incohérentes. Les accesseurs `Socle.scalar_size` / `Socle.oval_size` remplacent les
`cast` : ils lisent l'étiquette au lieu de l'affirmer.

Ces tests redeviennent ROUGES si la validation de frontière ou un accesseur est retiré.
Le dernier verrouille la donnée réelle : toutes les datasheets utilisées par les scénarios
respectent l'invariant (174 `round` scalaires + 5 `oval` paires sur l'ensemble du roster).
"""
import glob
import json
import re
from pathlib import Path

import pytest

from engine.game_state import GameStateManager, _scale_socle
from engine.hex_utils import Socle, require_base_size

_ROOT = Path(__file__).parents[3]


# --------------------------------------------------------------------------------------
# Frontière 1 : chargement de datasheet (_scale_socle)
# --------------------------------------------------------------------------------------

def test_oval_avec_taille_scalaire_leve_en_nommant_l_unite():
    """`oval` + diamètre scalaire : le cas que le docstring de `_scale_socle` décrivait
    comme un crash différé (`_socle_edge_primitives` indexe `size[0]` sur un int)."""
    with pytest.raises(TypeError) as exc:
        _scale_socle("oval", 13, 10, "datasheet Carnifex (unité 3)")

    msg = str(exc.value)
    assert "datasheet Carnifex (unité 3)" in msg   # l'unité est nommée
    assert "oval" in msg and "13" in msg           # les deux valeurs incoherentes aussi


def test_round_avec_paire_leve_en_nommant_l_unite():
    """Symétrique : `round` ne porte jamais de paire."""
    with pytest.raises(TypeError) as exc:
        _scale_socle("round", [13, 20], 10, "datasheet Intercessor (unité 1)")

    msg = str(exc.value)
    assert "datasheet Intercessor (unité 1)" in msg
    assert "round" in msg and "[13, 20]" in msg


def test_forme_de_socle_inconnue_leve():
    with pytest.raises(ValueError) as exc:
        _scale_socle("hexagone", 13, 10, "datasheet Zoanthrope")

    assert "hexagone" in str(exc.value) and "datasheet Zoanthrope" in str(exc.value)


def test_incoherence_detectee_meme_a_l_echelle_x1():
    """À `inches_to_subhex == 1` le socle est normalisé en `round`/1 : sans validation en
    amont, une datasheet incohérente passait ici SANS AUCUN signal."""
    with pytest.raises(TypeError):
        _scale_socle("oval", 13, 1, "datasheet Carnifex")


@pytest.mark.parametrize(
    "shape,size,attendu",
    [
        ("round", 13, ("round", 13)),
        ("oval", [13, 20], ("oval", [13, 20])),
        ("square", 8, ("square", 8)),
    ],
)
def test_conversion_inchangee_pour_un_socle_coherent(shape, size, attendu):
    """Contre-épreuve : la validation n'altère pas la conversion des socles valides."""
    assert _scale_socle(shape, size, 10, "datasheet X") == attendu


def test_normalisation_x1_toujours_appliquee():
    assert _scale_socle("oval", [13, 20], 1, "datasheet X") == ("round", 1)


# --------------------------------------------------------------------------------------
# Frontière 2 : unités construites hors chargement (create_unit)
# --------------------------------------------------------------------------------------

def _unit_config(shape, size):
    return {
        "id": "7", "player": 1, "unitType": "Carnifex", "DISPLAY_NAME": "Carnifex",
        "col": 3, "row": 4, "HP_CUR": 8, "HP_MAX": 8, "MOVE": 8, "T": 9,
        "ARMOR_SAVE": 2, "INVUL_SAVE": 7, "LD": 7, "OC": 3, "VALUE": 115,
        "ICON": "carnifex.png", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "MODEL_HEIGHT": 4.0, "BASE_SHAPE": shape, "BASE_SIZE": size,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_KEYWORDS": [],
    }


def test_create_unit_leve_sur_socle_incoherent():
    """Deuxième point d'entrée (API build army, fixtures) : même garde, même nommage."""
    manager = GameStateManager({"units": []})

    with pytest.raises(TypeError) as exc:
        manager.create_unit(_unit_config("oval", 13))

    assert "create_unit Carnifex (id 7)" in str(exc.value)


def test_create_unit_accepte_les_deux_formes_coherentes():
    manager = GameStateManager({"units": []})

    assert manager.create_unit(_unit_config("round", 13))["BASE_SIZE"] == 13
    assert manager.create_unit(_unit_config("oval", [13, 20]))["BASE_SIZE"] == [13, 20]


# --------------------------------------------------------------------------------------
# Accesseurs du Socle (ex-`cast`)
# --------------------------------------------------------------------------------------

def test_socle_scalar_size_refuse_une_paire():
    socle = Socle(shape="round", base_size=[13, 20], col=0, row=0)
    with pytest.raises(TypeError) as exc:
        socle.scalar_size()
    assert "[13, 20]" in str(exc.value)


def test_socle_oval_size_refuse_un_scalaire():
    socle = Socle(shape="oval", base_size=13, col=0, row=0)
    with pytest.raises(TypeError) as exc:
        socle.oval_size()
    assert "13" in str(exc.value)


def test_socle_accesseurs_rendent_la_valeur_attendue():
    assert Socle(shape="round", base_size=13, col=0, row=0).scalar_size() == 13
    assert Socle(shape="oval", base_size=[13, 20], col=0, row=0).oval_size() == [13, 20]


def test_distance_bord_a_bord_sur_socle_incoherent_leve():
    """Le cast rendait ce cas silencieux OU tardif ; il est maintenant explicite au premier
    calcul géométrique."""
    from engine.hex_utils import euclidean_edge_distance

    a = Socle(shape="round", base_size=13, col=0, row=0)
    b = Socle(shape="round", base_size=[13, 20], col=5, row=0)
    with pytest.raises(TypeError):
        euclidean_edge_distance(a, b)


# --------------------------------------------------------------------------------------
# Donnée réelle : les rosters respectent l'invariant
# --------------------------------------------------------------------------------------

def _scenario_unit_types():
    """Types d'unités référencés par les scénarios/rosters de config/."""
    used = set()
    for path in glob.glob(str(_ROOT / "config" / "**" / "*.json"), recursive=True):
        used.update(re.findall(r'"unit_type"\s*:\s*"(\w+)"', Path(path).read_text()))
    return used


def test_toutes_les_datasheets_chargees_respectent_l_invariant():
    """Preuve que la validation ne casse aucun chargement existant.

    Les unités `endlessDuty` sont exclues : leurs caractéristiques sont des RÉFÉRENCES
    statiques non résolues par le registre (`'Intercessor.BASE_SIZE'`), résolues par
    `services/endless_duty_runtime`, et elles ne passent donc jamais par `_scale_socle`
    (leur MOVE/HP_MAX seraient déjà des chaînes). L'assertion sur l'ensemble exclu
    verrouille cette frontière : aucune AUTRE unité n'a le droit d'être dans ce cas.
    """
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    references = {
        name for name, data in registry.units.items()
        if isinstance(data.get("BASE_SIZE"), str)
    }
    assert references and all(
        "endlessDuty" in str(registry.units[name]["file_path"]) for name in references
    )

    formes = {"round": 0, "oval": 0, "square": 0}
    for name, data in registry.units.items():
        if name in references:
            continue
        shape = data["BASE_SHAPE"]
        require_base_size(shape, data["BASE_SIZE"], f"datasheet {name}")
        formes[shape] += 1

    # Comptage constaté sur les datasheets découvertes par le registre : aucune ne viole
    # l'invariant (le roster déclare en tout 174 socles `round`, dont 18 dans des unités
    # `endlessDuty` à référence statique, exclues ci-dessus).
    assert formes == {"round": 156, "oval": 5, "square": 0}

    # Et toutes les unités que les scénarios chargent réellement en font partie.
    charges = _scenario_unit_types() & set(registry.units)
    assert charges and not (charges & references)


def test_registry_cache_json_coherent_si_present():
    """Le cache JSON du registre (s'il existe) porte la même donnée validée."""
    cache = _ROOT / "config" / "unit_registry_cache.json"
    if not cache.exists():
        pytest.skip("pas de cache de registre")
    units = json.loads(cache.read_text())["units"]
    for name, data in units.items():
        if isinstance(data.get("BASE_SIZE"), str):
            continue
        require_base_size(data["BASE_SHAPE"], data["BASE_SIZE"], f"cache {name}")
