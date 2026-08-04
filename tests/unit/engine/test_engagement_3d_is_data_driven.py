"""Le gate vertical §03.04 est piloté par la DONNÉE, pas par l'opt-in de l'appelant.

Pourquoi ce fichier existe. L'engagement 3D (2" horizontal ET 5" vertical) a d'abord été câblé
en passant `vertical_zone_inches=` à la main sur ~49 call-sites. Il en restait **17 en 2D**, dont
deux jumeaux directs de sites traités :

  - `generic_handlers._is_adjacent_to_enemy_for_fight` vs `fight_handlers._is_adjacent_to_enemy_within_cc_range`
  - `shared_utils._squad_is_in_enemy_er` vs `fight_handlers._fight_v11_engaged_now`

et les tests d'engagement de 10.05/10.06 (`shooting_handlers._is_adjacent_to_enemy_within_cc_range`) — une
escouade pouvait donc être *engagée* pour l'interdiction de tir et *non engagée* pour le combat,
sur la même paire, au même instant.

Un opt-in oublié ne LÈVE pas : il rend un verdict faux, en silence. Ces tests verrouillent donc
la propriété qui rend l'oubli impossible : **aucun appelant ne passe de seuil, et le gate
s'applique quand même**, parce que la primitive le résout dès que les deux entrées portent leurs
cartes verticales.

Géométrie commune : deux escouades adjacentes à l'horizontale, l'une au sol, l'autre sur un
plancher à 10" — soit 7,5" de séparation verticale une fois retranchée la hauteur des figurines
(2,5"), donc au-delà des 5" de §03.04. Le verdict 2D dirait « engagées », le 3D dit « non ».
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest

from engine.phase_handlers.generic_handlers import _is_adjacent_to_enemy_for_fight
from engine.phase_handlers.shared_utils import _squad_is_in_enemy_er
from engine.phase_handlers.shooting_handlers import (
    _is_adjacent_to_enemy_within_cc_range as _shoot_is_adjacent,
)
from engine.phase_handlers.fight_handlers import (
    _is_adjacent_to_enemy_within_cc_range as _fight_is_adjacent,
)


ENGAGEMENT_ZONE = 2          # subhex, déjà scalé (contrat moteur)
MODEL_HEIGHT = 2.5           # pouces
FLOOR_HEIGHT = 10.0          # 10" ; 10 - 2,5 = 7,5" > 5" -> hors zone verticale
LOW_FLOOR = 3.0              # 3" ; 3 - 2,5 = 0,5" <= 5" -> dans la zone verticale
GROUND, NEXT_TO = (10, 10), (11, 10)


def _entry(mid: str, pos: Tuple[int, int], player: int, floor: float) -> Dict[str, Any]:
    return {
        "col": pos[0], "row": pos[1], "player": player, "level": 0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
        "occupied_hexes": {pos},
        # Les TROIS clés verticales, écrites ensemble comme le fait `build_units_cache` : c'est
        # leur présence qui déclenche le gate, aucun appelant ne le demande.
        "occupied_hexes_by_model": {mid: pos},
        "floor_height_by_model": {mid: floor},
        "MODEL_HEIGHT": MODEL_HEIGHT,
    }


def _gs(enemy_floor: float, *, vertical_data: bool = True) -> Dict[str, Any]:
    """Escouade « 1 » au sol en (10,10), ennemie « 2 » en (11,10) à `enemy_floor` pouces."""
    ally = _entry("1#0", GROUND, 1, 0.0)
    enemy = _entry("2#0", NEXT_TO, 2, enemy_floor)
    if not vertical_data:
        for e in (ally, enemy):
            for key in ("occupied_hexes_by_model", "floor_height_by_model", "MODEL_HEIGHT"):
                e.pop(key)
    return {
        "units_cache": {"1": ally, "2": enemy},
        "config": {"game_rules": {
            "engagement_zone": ENGAGEMENT_ZONE, "engagement_zone_vertical": 5,
        }},
        "inches_to_subhex": 1,
        "terrain_areas": [],
    }


UNIT_1 = {"id": "1", "player": 1}


#: Les quatre points d'entrée « cette unité est-elle engagée ? » du moteur. Les deux premiers
#: étaient restés en 2D ; les deux derniers étaient déjà 3D. Les tester ENSEMBLE est le sujet :
#: c'est leur DÉSACCORD qui était le défaut, pas la valeur d'un seul.
_ENGAGEMENT_ENTRY_POINTS = pytest.mark.parametrize("predicate", [
    pytest.param(lambda gs: _is_adjacent_to_enemy_for_fight(gs, UNIT_1), id="fight_eligibility"),
    pytest.param(lambda gs: _squad_is_in_enemy_er(gs, "1"), id="squad_in_enemy_er"),
    pytest.param(lambda gs: _shoot_is_adjacent(gs, UNIT_1), id="shooting_10.05"),
    pytest.param(lambda gs: _fight_is_adjacent(gs, UNIT_1), id="fight_cc_range"),
])


@_ENGAGEMENT_ENTRY_POINTS
def test_an_enemy_two_floors_up_is_not_engaged(predicate) -> None:
    """AUCUN de ces appelants ne passe de seuil vertical — et tous doivent quand même l'appliquer."""
    assert predicate(_gs(FLOOR_HEIGHT)) is False


@_ENGAGEMENT_ENTRY_POINTS
def test_an_enemy_on_the_ground_is_engaged(predicate) -> None:
    """Contre-épreuve : le gate ne refuse pas tout. Même géométrie horizontale, même hauteur."""
    assert predicate(_gs(0.0)) is True


@_ENGAGEMENT_ENTRY_POINTS
def test_a_low_floor_still_engages(predicate) -> None:
    """Le gate est un SEUIL (5"), pas un « même étage » : 3" de plancher reste au contact."""
    assert predicate(_gs(LOW_FLOOR)) is True


@_ENGAGEMENT_ENTRY_POINTS
def test_without_vertical_data_the_verdict_stays_horizontal(predicate) -> None:
    """Donnée absente → verdict 2D, pas une altitude supposée ni une exception.

    C'est le cas des entrées SYNTHÉTIQUES (candidats de pool construits sans niveau) : leur
    mesurer une altitude qu'elles n'ont pas serait pire que de les mesurer à plat.
    """
    assert predicate(_gs(FLOOR_HEIGHT, vertical_data=False)) is True


def test_the_four_entry_points_agree() -> None:
    """LE défaut d'origine : ils ne répondaient pas la même chose sur la MÊME paire.

    Une escouade *engagée* pour l'interdiction de tir (10.05) et *non engagée* pour l'éligibilité
    au combat, au même instant, sur les mêmes deux unités.
    """
    for floor in (0.0, LOW_FLOOR, FLOOR_HEIGHT):
        gs = _gs(floor)
        verdicts = {
            "fight_eligibility": _is_adjacent_to_enemy_for_fight(gs, UNIT_1),
            "squad_in_enemy_er": _squad_is_in_enemy_er(gs, "1"),
            "shooting_10.05": _shoot_is_adjacent(gs, UNIT_1),
            "fight_cc_range": _fight_is_adjacent(gs, UNIT_1),
        }
        assert len(set(verdicts.values())) == 1, (
            f"plancher {floor}\" : les points d'entrée divergent — {verdicts}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Une escouade morte ne se mesure pas
# ─────────────────────────────────────────────────────────────────────────────

def test_a_squad_with_no_models_left_in_the_cache_raises() -> None:
    """`units_cache` porte l'invariant « détruite = ABSENTE du cache ».

    `remove_from_units_cache` le dit : « Dead = absent from cache (single source of truth) ». Une
    entrée qui y reste avec une carte par-figurine VIDE viole donc cet invariant, et il n'existe
    aucune mesure juste à lui appliquer :
      - à plat, `_cache_entry_footprint` retombe sur l'ANCRE — une escouade détruite redeviendrait
        engageable, donc cible de mêlée ;
      - en 3D, aucune classe verticale n'est produite et le verdict est « non engagé » sans que
        rien n'ait été mesuré.

    Les deux sont des verdicts INVENTÉS. L'erreur explicite est le seul comportement correct.
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone

    vivante = _entry("2#0", NEXT_TO, 2, 0.0)
    morte = _entry("1#0", GROUND, 1, 0.0)
    morte["occupied_hexes_by_model"] = {}
    morte["floor_height_by_model"] = {}

    with pytest.raises(ValueError, match="escouade sans figurine"):
        unit_entries_within_engagement_zone(morte, vivante, ENGAGEMENT_ZONE)


def test_an_entry_without_the_per_model_layer_is_measured_flat() -> None:
    """Contre-épreuve : clé ABSENTE ≠ carte vide — l'une est légitime, l'autre est une corruption.

    Les entrées SYNTHÉTIQUES (candidats de pool construits sans niveau) n'ont pas de couche
    par-figurine du tout : `_synth_model_entry` et `_charge_synthetic_charger_cache_entry`
    laissent la clé de côté. Elles doivent rester mesurables à plat — sans quoi le garde-fou
    ci-dessus casserait tous les pools.
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone

    vivante = _entry("2#0", NEXT_TO, 2, 0.0)
    synthetique = _entry("1#0", GROUND, 1, 0.0)
    for key in ("occupied_hexes_by_model", "floor_height_by_model", "MODEL_HEIGHT"):
        synthetique.pop(key)

    assert unit_entries_within_engagement_zone(
        synthetique, vivante, ENGAGEMENT_ZONE
    ) is True, "une entrée sans couche par-figurine doit rester mesurable (verdict horizontal)"


# ─────────────────────────────────────────────────────────────────────────────
# Base-contact : le SEUIL dépend de la métrique
# ─────────────────────────────────────────────────────────────────────────────

def _contact_gs(ish: int, base: int, dcol: int) -> Dict[str, Any]:
    """Deux escouades mono-figurine, `dcol` cases d'écart, à l'échelle `ish`."""
    from engine.hex_utils import compute_occupied_hexes

    def _e(sid: str, col: int, player: int) -> Dict[str, Any]:
        return {
            "id": sid, "col": col, "row": 10, "player": player, "level": 0, "squad_id": sid,
            "BASE_SHAPE": "round", "BASE_SIZE": base, "orientation": 0,
            "occupied_hexes": set(compute_occupied_hexes(col, 10, "round", base, 0)),
            "occupied_hexes_by_model": {f"{sid}#0": (col, 10)},
            "floor_height_by_model": {f"{sid}#0": 0.0},
            "MODEL_HEIGHT": MODEL_HEIGHT,
        }
    return {
        "inches_to_subhex": ish, "terrain_areas": [],
        "config": {"game_rules": {
            "engagement_zone": 2 * ish, "engagement_zone_vertical": 5,
        }},
        "units_cache": {"1": _e("1", 10, 1), "2": _e("2", 10 + dcol, 2)},
        "models_cache": {"1#0": _e("1", 10, 1)},
    }


@pytest.mark.parametrize(
    "ish, base, dcol, attendu, pourquoi",
    [
        (1, 1, 1, True, "x1 : une figurine tient dans UNE case, deux cases adjacentes = socles collés"),
        (1, 1, 2, False, "x1 : une case d'écart, les socles ne se touchent pas"),
        (5, 6, 6, True, "x5 : écart bord-à-bord exactement 0 = tangence, donc contact"),
        (5, 6, 8, False, "x5 : socles séparés"),
    ],
)
def test_base_contact_threshold_follows_the_metric(ish, base, dcol, attendu, pourquoi) -> None:
    """12.03 : « Models in base-contact [...] cannot be moved » — le SEUIL n'est pas le même partout.

    Le contact est l'engagement à un seuil, mais ce seuil dépend de la géométrie :
      - `euclidean` (x5, x10) : socles multi-cases, « bord à bord » continu → zone **0** ;
      - `hex` (x1, `geometry_is_hex`) : `_scale_socle` normalise tout en `round`/1, une figurine
        tient dans UNE case → deux socles se touchent quand leurs cases sont ADJACENTES, donc
        zone **`BASE_TO_BASE_SUBHEX`**.

    Un seuil unique ne peut pas servir les deux, et s'en tenir à « zone 0 » a été une VRAIE
    régression : à x1 deux `round`/1 adjacents ont un écart euclidien de 0,2321 et une distance
    d'empreinte de 1 — donc « jamais au contact », donc 12.03 ne s'appliquait plus du tout sur le
    plateau d'ENTRAÎNEMENT. Ce paramétrage couvre les deux métriques et les deux verdicts, parce
    qu'un test qui n'en couvrirait qu'un laisserait l'autre repartir.
    """
    from engine.phase_handlers.shared_utils import model_in_base_contact

    gs = _contact_gs(ish, base, dcol)
    assert model_in_base_contact(gs, "1#0", gs["models_cache"]["1#0"]) is attendu, pourquoi
