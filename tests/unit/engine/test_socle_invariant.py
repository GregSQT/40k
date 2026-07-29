"""Invariant du socle : `BASE_SHAPE` DÉTERMINE le type de `BASE_SIZE`.

`round`/`square` portent un diamètre scalaire, `oval` une paire `[grand axe, petit axe]`.
Rien ne le vérifiait : neuf `cast` l'affirmaient au typage (hex_utils, terrain_utils,
movement_handlers) et deux gardes correctes existaient sans être branchées.

L'invariant est validé à la frontière où la donnée entre dans le moteur
(`game_state._scale_socle`, chargement de datasheet, et `GameStateManager.create_unit` pour
les unités construites hors chargement), avec une erreur qui NOMME l'unité et les deux
valeurs incohérentes.

Le type du socle est ensuite SCINDÉ : `RoundSocle` / `SquareSocle` / `OvalSocle` portent
chacun le type exact de `base_size`, et `Socle(...)` est la fabrique qui choisit la classe
d'après l'étiquette. L'invariant n'est plus « vérifié à la lecture » (accesseurs
`scalar_size` / `oval_size`, supprimés) : un socle incohérent ne peut plus EXISTER.

Ces tests redeviennent ROUGES si la validation de frontière ou la fabrique est retirée.
Le dernier verrouille la donnée réelle : toutes les datasheets utilisées par les scénarios
respectent l'invariant (174 `round` scalaires + 5 `oval` paires sur l'ensemble du roster).
"""
import glob
import json
import re
from pathlib import Path

import pytest

from engine.game_state import GameStateManager, _scale_socle
from engine.hex_utils import (
    OvalSocle, RoundSocle, Socle, SquareSocle, require_base_size,
)

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
# Frontière 3 : la fabrique `Socle(...)` — l'invariant devient impossible à violer
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "shape,size,classe_attendue",
    [
        ("round", 13, RoundSocle),
        ("square", 8, SquareSocle),
        ("oval", [13, 20], OvalSocle),
    ],
)
def test_la_fabrique_choisit_la_classe_de_l_etiquette(shape, size, classe_attendue):
    """`BASE_SHAPE` ne décrit plus la forme « à côté » de la taille : elle CHOISIT le type."""
    socle = Socle(shape=shape, base_size=size, col=0, row=0)

    assert type(socle) is classe_attendue
    assert socle.shape == shape
    # `base_size` ne se lit QUE sur une classe concrète : le typage l'exige, ce test aussi.
    assert isinstance(socle, (RoundSocle, SquareSocle, OvalSocle))
    assert socle.base_size == size


@pytest.mark.parametrize(
    "shape,size,extrait",
    [
        ("round", [13, 20], "[13, 20]"),
        ("square", [13, 20], "[13, 20]"),
        ("oval", 13, "13"),
        ("oval", [13], "[13]"),            # paire incomplète
        ("oval", [13, 20, 4], "[13, 20"),  # triplet
        ("oval", (13, 20), "(13, 20)"),    # tuple : la donnée moteur est une liste
        ("round", True, "True"),           # `bool` est un `int` pour isinstance, jamais un diamètre
    ],
)
def test_la_fabrique_refuse_une_taille_qui_contredit_l_etiquette(shape, size, extrait):
    """Aucun socle incohérent ne peut EXISTER : le refus est à la construction, pas au calcul."""
    with pytest.raises(TypeError) as exc:
        Socle(shape=shape, base_size=size, col=0, row=0)

    assert shape in str(exc.value) and extrait in str(exc.value)


def test_la_fabrique_refuse_une_forme_inconnue():
    with pytest.raises(ValueError) as exc:
        Socle(shape="hexagone", base_size=13, col=0, row=0)

    assert "hexagone" in str(exc.value)


def test_with_model_centers_conserve_la_classe_concrete():
    """`_replace` du NamedTuple pouvait produire n'importe quoi ; ici on repasse par la
    fabrique, donc l'étiquette et la taille restent liées."""
    rond = Socle(shape="round", base_size=13, col=0, row=0, fp={(0, 0)})
    ovale = Socle(shape="oval", base_size=[13, 20], col=0, row=0, fp={(0, 0)})

    rond2 = rond.with_model_centers([(1, 1), (2, 2)])
    ovale2 = ovale.with_model_centers([(1, 1)])

    assert type(rond2) is RoundSocle and rond2.base_size == 13
    assert type(ovale2) is OvalSocle and ovale2.base_size == [13, 20]
    assert rond2.model_centers == [(1, 1), (2, 2)] and rond2.fp == {(0, 0)}
    assert rond.model_centers is None  # l'original n'est pas muté


def test_la_geometrie_ne_relit_plus_l_etiquette():
    """Contre-épreuve du gain : le chemin chaud rond↔rond est choisi par la CLASSE, et un
    socle ovale y échappe — sans qu'aucun accesseur ne relise `shape`."""
    from engine.hex_utils import euclidean_edge_distance, footprints_overlap

    a = Socle(shape="round", base_size=13, col=0, row=0)
    b = Socle(shape="round", base_size=13, col=40, row=4)
    ovale = Socle(shape="oval", base_size=[13, 20], col=1, row=0, fp={(1, 0)})

    assert not hasattr(a, "scalar_size") and not hasattr(ovale, "oval_size")
    assert euclidean_edge_distance(a, b) > 0.0
    assert footprints_overlap(a, a)
    # Paire mixte : méthode empreinte, `fp` requis des deux côtés.
    with pytest.raises(ValueError):
        footprints_overlap(a, ovale)


# --------------------------------------------------------------------------------------
# Consommateur du socle : le cache d'empreinte du combat
# --------------------------------------------------------------------------------------

def _fight_gs():
    """`engagement_zone > 1` : le préparateur d'offsets prend le chemin multi-hex."""
    return {
        "config": {
            "game_rules": {
                "engagement_zone": 5, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }


def test_cache_d_empreinte_fight_leve_au_lieu_de_memoriser_l_echec():
    """Le pire des replis : `except Exception: cache[key] = None` n'ignorait pas l'erreur,
    il la MÉMORISAIT — l'unité restait « sans empreinte rapide » pour toute la partie."""
    from engine.phase_handlers.fight_handlers import _fight_prepare_footprint_offsets

    gs = _fight_gs()
    unit = {"id": "7", "orientation": 0, "BASE_SHAPE": "oval", "BASE_SIZE": 13}

    with pytest.raises(TypeError) as exc:
        _fight_prepare_footprint_offsets(unit, gs)

    assert "fight footprint unit 7" in str(exc.value)   # l'unité est nommée
    assert "oval" in str(exc.value) and "13" in str(exc.value)
    # Et rien n'a été mémorisé : le prochain appel relèvera au lieu de servir un None.
    assert gs.get("_fight_fp_offset_pair_cache") == {}


def test_cache_d_empreinte_fight_none_reste_le_cas_metier_1_hex():
    """`None` garde son sens légitime : socle d'un hex -> pas de chemin rapide à préparer."""
    from engine.phase_handlers.fight_handlers import _fight_prepare_footprint_offsets

    gs = _fight_gs()
    unit = {"id": "7", "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1}

    assert _fight_prepare_footprint_offsets(unit, gs) is None


def test_cache_d_empreinte_fight_calcule_les_offsets_d_un_socle_valide():
    from engine.phase_handlers.fight_handlers import _fight_prepare_footprint_offsets

    gs = _fight_gs()
    unit = {"id": "7", "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": 3}

    pair = _fight_prepare_footprint_offsets(unit, gs)

    assert pair is not None and len(pair) == 2 and pair[0] and pair[1]


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
