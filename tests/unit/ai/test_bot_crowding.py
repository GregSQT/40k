"""Une zone déjà servie par les alliés repousse l'escouade suivante.

LE défaut que ce fichier verrouille, mesuré le 2026-08-12 sur 600 parties du panel refondu :
les bots empilent **2,6 à 3,0 escouades par zone** et n'en couvrent que 1,7 sur 5, quand l'agent
étale les siennes sur 2,9. Ils ne sont ni lents (92 % de l'armée est dans une zone dès le tour 3)
ni battus au décompte (ils contrôlent 1,66 des 1,92 zones où ils sont présents) : ils vont tous
au même endroit, parce que chaque escouade décide seule et calcule la même réponse.

C'est aussi ce qui rendait `w_contest` INERTE (aucun effet mesurable sur six win-rates) : rendre
une zone plus attirante quand personne ne se coordonne ne fait que déplacer le tas.

La pénalité porte sur le **surplus d'OC**, pas sur l'occupation : une zone disputée n'est pas
pénalisée — les renforts doivent y aller — mais une zone déjà gagnée large repousse la suivante.

⚠️ L'ÉTAT DE CE FICHIER EST UN ÉTAT MOTEUR, pas un dict de commodité : le surplus est dérivé de
`sum_objective_control_oc_multi`, donc il lit les EMPREINTES DE SOCLE et le drapeau
`battle_shocked`. Un état bricolé à côté (une position par escouade, aucun socle) rendrait
indétectables les deux écarts que ce fichier verrouille précisément.
"""
from __future__ import annotations

from typing import Any, Collection, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pytest

import ai.bot_doctrines as doc

Hexes = Set[Tuple[int, int]]

#: Les deux zones sont DISJOINTES même pour un gros socle : le test du socle pose une empreinte de
#: 7 cases autour de la zone A, qui ne doit pas mordre la zone B par accident.
ZONE_A: Hexes = {(1, 1)}
ZONE_B: Hexes = {(6, 6)}

#: Les deux zones sont à des distances DIFFÉRENTES, et c'est indispensable : `_objective_terms`
#: rend le MINIMUM des cartes. Avec deux cartes identiques, appliquer la pénalité à la mauvaise
#: zone rendrait exactement la même valeur et aucune assertion ne pourrait le voir.
DISTANCE_PROCHE = 5
DISTANCE_LOIN = 8

#: Les cartes uniformes portent la même valeur partout : cette case n'a rien de particulier.
SONDE = (0, 0)

GRILLE = 12


def _uniforme(distance: int) -> np.ndarray:
    """Carte de distance constante. `int16` est le dtype rendu par le moteur."""
    return np.full((GRILLE, GRILLE), distance, dtype=np.int16)


def _carte_vers(zone: Hexes, dedans: int, dehors: int) -> np.ndarray:
    """Carte à deux paliers : `dedans` sur la zone, `dehors` partout ailleurs."""
    grille = np.full((GRILLE, GRILLE), dehors, dtype=np.int16)
    for col, row in zone:
        grille[col, row] = dedans
    return grille


def _cartes(monkeypatch: pytest.MonkeyPatch, *cartes: np.ndarray) -> None:
    """Impose les cartes de distance, DANS L'ORDRE de `state["objectives"]`.

    SEULE la carte est patchée. Les zones, elles, sont dérivées de l'état par le parseur du moteur
    (`objective_hex_zones` lit `objectives[].hexes`) exactement comme en production : les patcher
    aussi obligeait chaque test à tenir à la main l'accord entre cartes, zones et `objectives`, et
    `_objective_terms` zippe ces listes — un désaccord de longueur se serait tronqué en silence.
    Une carte de distance, elle, exige la config de plateau : c'est une pure ENTRÉE, et c'est la
    seule chose que ce fichier a le droit d'inventer.
    """
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: list(cartes))


def _state(
    figurines: Sequence[Tuple[str, int, Tuple[int, int], int]],
    *,
    shocked: Collection[str] = (),
    socles: Optional[Dict[str, int]] = None,
    zones: Sequence[Hexes] = (ZONE_A, ZONE_B),
) -> Dict[str, Any]:
    """État moteur minimal mais RÉEL : `figurines` = [(id_escouade, joueur, position, OC), …].

    `socles` donne le diamètre de socle EN HEXES d'une escouade (1 par défaut) ; `shocked` liste
    les escouades battle-shockées (01.07). Les deux existent parce que le décompte de contrôle du
    moteur les lit — un état qui ne pourrait pas les exprimer ne verrouillerait rien.

    Les objectifs portent leurs `hexes`, donc le parseur du moteur en dérive les zones : `zones`
    est la SOURCE, et rien dans ce fichier ne redéclare une géométrie à côté.
    """
    socles = socles or {}
    units: List[Dict[str, Any]] = []
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, Any] = {}
    for squad_id, player, (col, row), oc in figurines:
        units.append({
            "id": squad_id,
            "player": player,
            "OC": oc,
            "battle_shocked": squad_id in shocked,
            "UNIT_RULES": [],
        })
        units_cache[squad_id] = {"player": player, "col": col, "row": row, "orientation": 0}
        model_id = f"{squad_id}#0"
        squad_models[squad_id] = [model_id]
        models_cache[model_id] = {
            "col": col, "row": row, "HP_CUR": 6,
            "BASE_SHAPE": "round", "BASE_SIZE": socles.get(squad_id, 1),
        }
    return {
        "objectives": [
            {"id": nom, "hexes": [[col, row] for col, row in sorted(zone)]}
            for nom, zone in zip("AB", zones)
        ],
        "units": units,
        "unit_by_id": {str(unit["id"]): unit for unit in units},
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "episode_number": 1,
        "turn": 1,
        "phase": "move",
    }


def _surplus(state: Dict[str, Any], me: int, sauf: str) -> List[float]:
    return doc._surplus_oc_by_zone(state, [ZONE_A, ZONE_B], me, sauf)


def _qui_decide(state: Dict[str, Any]) -> Dict[str, Any]:
    """L'escouade « 2 » : celle qui est activée et qui doit choisir sa destination."""
    return state["unit_by_id"]["2"]


def _distance_percue(state: Dict[str, Any], w_crowd: float) -> float:
    """La distance que l'escouade « 2 » LIT sur la carte combinée, pénalité comprise.

    Rend un FLOTTANT : tronquer ici serait précisément le défaut que ce fichier verrouille, et le
    helper le rejouerait en silence le jour où une assertion porterait sur une pénalité
    fractionnaire. `_objective_terms` garantit désormais ce type quel que soit l'état.
    """
    carte, _zones = doc._objective_terms(state, me=1, w_crowd=w_crowd, escouade="2")
    assert carte is not None, "aucune carte rendue : le test ne regarde rien"
    assert carte.dtype == np.float64, "la carte doit être flottante quel que soit l'état de partie"
    return float(carte[SONDE])


# ── Le surplus : la grandeur qui dit « cette zone est déjà servie » ─────────────────────────────


def test_an_uncontested_ally_creates_a_surplus() -> None:
    """Un allié seul sur la zone A : surplus de son OC, rien sur B."""
    state = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [4.0, 0.0]


def test_my_own_squad_never_counts_against_itself() -> None:
    """Verrou du piège inverse : sans l'exclusion, une escouade seule sur sa zone la fuirait.

    C'est le mode d'échec le plus coûteux de cette pénalité : le bot lâcherait les zones qu'il
    tient, ce qui est exactement ce qu'on cherche à empêcher.
    """
    state = _state([("1", 1, (1, 1), 4)])

    assert _surplus(state, me=1, sauf="1") == [0.0, 0.0]


def test_a_contested_zone_is_not_a_surplus() -> None:
    """OC allié 4 contre OC ennemi 4 : la zone n'est PAS servie, elle doit rester attirante."""
    state = _state([("1", 1, (1, 1), 4), ("101", 2, (1, 1), 4), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [0.0, 0.0]


def test_only_the_excess_over_the_enemy_counts() -> None:
    """OC allié 10 contre 4 : seuls les 6 de trop sont du gaspillage."""
    state = _state([("1", 1, (1, 1), 10), ("101", 2, (1, 1), 4), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [6.0, 0.0]


def test_the_surplus_is_counted_in_oc_not_in_squads() -> None:
    """DEUX escouades à 1 d'OC pèsent moins qu'UNE à 9.

    Compter les escouades serait le même proxy que le `max(NB × DMG)` que ce chantier a retiré :
    deux Gretchin et un Carnifex ne pèsent pas pareil sur une zone.
    """
    deux_faibles = _state([("1", 1, (1, 1), 1), ("2", 1, (1, 1), 1), ("3", 1, (9, 9), 1)])
    un_lourd = _state([("1", 1, (1, 1), 9), ("3", 1, (9, 9), 1)])

    assert _surplus(deux_faibles, me=1, sauf="3")[0] == 2.0
    assert _surplus(un_lourd, me=1, sauf="3")[0] == 9.0


def test_a_base_that_only_overlaps_the_zone_still_holds_it() -> None:
    """Le socle mord la zone, le CENTRE est dehors : le moteur donne le contrôle, le bot aussi.

    LE DÉFAUT CORRIGÉ. Le surplus tranchait la présence sur l'hexe-centre de chaque figurine,
    alors que `sum_objective_control_oc_multi` compte dès qu'une case de l'empreinte recouvre la
    zone. Une escouade à gros socle posée au bord tenait donc la zone pour le moteur et pas pour
    le bot, qui y renvoyait une escouade de plus : le motif ancre-contre-par-figurine.
    """
    state = _state([("1", 1, (2, 1), 4), ("2", 1, (9, 9), 1)], socles={"1": 3})

    figurine = state["models_cache"]["1#0"]
    centre = (int(figurine["col"]), int(figurine["row"]))

    assert centre not in ZONE_A, (
        "le centre du socle est DANS la zone : le test repasserait par l'hexe-centre et ne "
        "verrouillerait plus l'empreinte"
    )
    assert _surplus(state, me=1, sauf="2") == [4.0, 0.0]


def test_a_battle_shocked_squad_holds_nothing() -> None:
    """Règle 01.07 : l'OC d'une escouade battle-shockée vaut '-', elle ne tient donc rien (02.02).

    L'ANCIEN CALCUL LA COMPTAIT. Elle fabriquait un surplus FANTÔME : le bot refusait de renforcer
    une zone que son camp ne tenait pas — exactement le mode d'échec que
    `test_my_own_squad_never_counts_against_itself` prétend protéger, par l'autre bout.
    """
    state = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 1)], shocked={"1"})

    assert _surplus(state, me=1, sauf="2") == [0.0, 0.0]


# ── La carte de distance : ce que le surplus fait au choix de destination ───────────────────────


def test_a_served_zone_moves_away_by_the_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNE seule zone, déjà servie : sa distance perçue augmente de `w_crowd × surplus`.

    Une seule zone, exprès. Avec deux, la carte rendue est leur MINIMUM : la zone libre masquerait
    la pénalité de l'autre et le test passerait sans rien observer.
    """
    _cartes(monkeypatch, _uniforme(DISTANCE_PROCHE))
    state = _state([("1", 1, (1, 1), 6), ("2", 1, (9, 9), 1)], zones=[ZONE_A])

    assert _distance_percue(state, w_crowd=0.0) == DISTANCE_PROCHE, (
        "sans pénalité, la carte est la distance nue"
    )
    assert _distance_percue(state, w_crowd=2.0) == DISTANCE_PROCHE + 2 * 6, (
        "servie : elle doit s'éloigner de w_crowd × surplus"
    )


def test_the_next_squad_prefers_the_free_zone_even_when_it_is_farther(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La zone servie est la PLUS PROCHE, et la pénalité lui fait perdre le duel.

    C'est l'état d'avant qui est décrit par la première assertion : sans pénalité, l'escouade lit
    5 et part rejoindre le tas. Avec, elle lit 8 — la zone libre, pourtant plus loin.

    Les deux zones sont à des distances différentes EXPRÈS : la carte rendue étant leur minimum,
    deux distances égales rendraient `min(17, 5)` et `min(5, 17)` identiques, et le test resterait
    vert même si la pénalité était appliquée à la mauvaise zone.
    """
    _cartes(monkeypatch, _uniforme(DISTANCE_PROCHE), _uniforme(DISTANCE_LOIN))
    state = _state([("1", 1, (1, 1), 6), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [6.0, 0.0], "la zone A doit être la seule servie"
    assert _distance_percue(state, w_crowd=0.0) == DISTANCE_PROCHE, (
        "sans pénalité, la zone SERVIE gagne parce qu'elle est la plus proche"
    )
    assert _distance_percue(state, w_crowd=2.0) == DISTANCE_LOIN, (
        "pénalisée, la zone servie part à 17 : c'est la zone LIBRE qui sera choisie"
    )


# ── Le chemin RÉEL : ce qu'un bot du panel fait de tout ça ──────────────────────────────────────


class _BotSousTest(doc._DoctrineBot):
    """Doctrine réduite au terme d'objectif : les poids sont FIXÉS ici, pas lus en config.

    Aucun style du panel n'est instancié exprès. Ce test ne mesure pas une doctrine, il vérifie le
    CÂBLAGE que `select_movement_destination` fait entre l'unité activée et le calcul de la carte
    (ordre des six poids, joueur, identité de l'escouade) — trois décisions qu'aucun test
    n'atteignait, puisque tous s'arrêtaient aux fonctions privées d'un cran plus bas.
    """

    def __init__(self, w_crowd: float):
        super().__init__()
        #: `w_enn`, `w_fire` et `w_risk` sont nuls : la destination ne doit dépendre QUE des
        #: objectifs, et la seconde passe (coûteuse) est court-circuitée. Le tuple est posé ici
        #: dans SON ORDRE : c'est lui que `select_movement_destination` déballe.
        self._poids = (1.0, 0.0, 0.0, 0.0, 0.0, w_crowd)

    def movement_weights(self, unit, game_state):
        return self._poids


@pytest.mark.parametrize(
    ("w_crowd", "attendue", "pourquoi"),
    [
        (0.0, (1, 1), "sans pénalité, le bot rejoint le tas sur la zone la plus attirante"),
        (2.0, (6, 6), "pénalisée, la zone servie est abandonnée à la zone libre"),
    ],
)
def test_the_real_bot_walks_away_from_a_zone_its_allies_already_hold(
    monkeypatch: pytest.MonkeyPatch, w_crowd: float, attendue: Tuple[int, int], pourquoi: str
) -> None:
    """LE verrou d'ensemble, joué par l'ENTRÉE PUBLIQUE d'un bot de doctrine.

    Deux destinations, une par zone. La zone A est la plus attirante (distance 0 contre 3) et elle
    est déjà tenue large par un allié ; la zone B est libre. Le bot doit choisir A sans pénalité
    et B avec — c'est la décision réelle que prend une escouade en phase de mouvement.

    Ce que ce test attrape et qu'aucun autre n'attrapait : intervertir `w_contest` et `w_crowd` au
    déballage des six poids, ou cesser de transmettre l'identité de l'escouade activée.
    """
    _cartes(
        monkeypatch,
        _carte_vers(ZONE_A, dedans=0, dehors=10),
        _carte_vers(ZONE_B, dedans=3, dehors=10),
    )
    state = _state([
        ("1", 1, (1, 1), 6),    # l'allié qui tient déjà la zone A, large
        ("2", 1, (9, 9), 1),    # l'escouade qui décide, loin des deux zones
        ("101", 2, (11, 11), 1),  # un ennemi sur la table, hors de portée de tout
    ])

    choisie = _BotSousTest(w_crowd).select_movement_destination(
        _qui_decide(state), [(1, 1), (6, 6)], state
    )

    assert choisie == attendue, pourquoi


def test_a_fractional_weight_still_moves_the_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un poids INFÉRIEUR À 1 doit agir. Deux profils du panel sont réglés à `w_crowd: 0.5`.

    LE DÉFAUT CORRIGÉ. Le score tronquait la distance à l'entier avant d'appliquer les poids, donc
    toute pénalité fractionnaire disparaissait : 3 + 0,5 se relisait 3, et le poids ne servait à
    rien. C'est le même « poids inerte » que ce chantier reprochait à `w_contest`, et il rendait
    les paliers bas du panel indiscernables les uns des autres.

    Les deux zones sont à ÉGALITÉ STRICTE (3 et 3) : seule la demi-pénalité peut les départager,
    donc la tronquer ramène le choix à l'égalité et la zone servie l'emporte.
    """
    _cartes(
        monkeypatch,
        _carte_vers(ZONE_A, dedans=3, dehors=10),
        _carte_vers(ZONE_B, dedans=3, dehors=10),
    )
    state = _state([("1", 1, (1, 1), 1), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [1.0, 0.0], "surplus de 1 : la pénalité vaut 0,5"

    choisie = _BotSousTest(w_crowd=0.5).select_movement_destination(
        _qui_decide(state), [(1, 1), (6, 6)], state
    )

    assert choisie == (6, 6), "0,5 de pénalité suffit à départager deux zones à égalité"
