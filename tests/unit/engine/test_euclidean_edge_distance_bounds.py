"""``euclidean_edge_distance(max_distance=…)`` rend EXACTEMENT le même verdict que le calcul exact.

Pourquoi ce fichier existe. La distance bord-à-bord entre socles non ronds passe par le produit
arête × arête de deux contours ovals à 32 sommets : mesuré sur un drive de 200 pas du vrai moteur,
21 M d'appels à ``_point_segment_dist_sq`` pour 13,7 s sur 37 s de step. L'élagage par disques
inscrit/circonscrit tranche la même question en O(1) — mais un encadrement FAUX ne lève pas : il
rend un booléen d'engagement (règle 03.04) faux, silencieusement, sur une paire de socles précise.
C'est donc l'ÉQUIVALENCE qui est verrouillée ici, pas la performance.

Deux propriétés distinctes, et il faut les deux :
  1. sans ``max_distance``, la valeur reste la distance exacte — l'élagage « ce couple de figurines
     ne peut plus améliorer le minimum » ne doit rien changer (référence : force brute, aucun
     élagage) ;
  2. avec ``max_distance``, le VERDICT DE SEUIL est identique à celui du calcul exact — c'est tout
     ce que le contrat promet, et tout ce dont les appelants se servent.

L'échantillon est CONSTRUIT (formes × orientations × écarts), jamais tiré au hasard : les cas qui
comptent sont les socles tangents et ceux qui tombent dans la bande d'incertitude entre les deux
disques, là où l'encadrement ne conclut pas et où un décalage d'un epsilon ferait diverger les deux
chemins.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from engine.hex_utils import (
    Socle,
    _primitive_edge_dist,
    _socle_bounding_circles,
    _socle_edge_primitives,
    euclidean_edge_distance,
)

#: Socles de référence : les trois formes du dépôt, deux orientations non triviales pour celles qui
#: en portent une. ``base_size`` est en SUBHEX — l'unité que le moteur manipule, après la
#: conversion `datasheet ×10 → subhex` de ``normalize_socle_for_board`` : sur un plateau x5, un
#: socle d'infanterie de 32 mm vaut ~6 et un châssis de véhicule ~[20, 12].
SHAPES: List[Tuple[str, object, int]] = [
    ("round", 6, 0),
    ("round", 10, 0),
    ("square", 8, 0),
    ("square", 8, 2),
    ("oval", [20, 12], 0),
    ("oval", [20, 12], 3),
    ("oval", [12, 7], 5),
]

#: Écarts en colonnes entre les deux ancres. Un hex vaut 1,5 unité-norme et un socle de taille 20
#: porte un demi-grand axe de 15 : il faut donc aller jusqu'à ~30 colonnes pour sortir du contact,
#: et garder un pas fin dans la zone de tangence, seule à exercer les cas limites.
GAPS = [0, 2, 4, 6, 8, 10, 12, 14, 17, 21, 26, 32, 45]


def _make(shape, size, orientation, col, row, centers=None) -> Socle:
    return Socle(
        shape=shape, base_size=size, col=col, row=row,
        fp=None, model_centers=centers, orientation=orientation,
    )


def _brute_force_distance(a: Socle, b: Socle) -> float:
    """Distance bord-à-bord SANS le moindre élagage — la référence de la propriété 1.

    Reproduit le corps historique de ``euclidean_edge_distance`` pour le cas non rond : toutes les
    paires de primitives, ``_primitive_edge_dist`` sur chacune, minimum. Le cas rond↔rond n'a pas
    de référence séparée : il est déjà O(1) par paire et son early-out ne dépend pas des contours.
    """
    best = math.inf
    for pa in _socle_edge_primitives(a):
        for pb in _socle_edge_primitives(b):
            d = _primitive_edge_dist(pa, pb)
            if d < best:
                best = d
    return best if best > 0.0 else 0.0


def _pairs():
    """Toutes les paires (forme × forme × écart), ancres alignées puis décalées en ligne."""
    for shape_a, size_a, orient_a in SHAPES:
        for shape_b, size_b, orient_b in SHAPES:
            for gap in GAPS:
                yield (
                    _make(shape_a, size_a, orient_a, 10, 10),
                    _make(shape_b, size_b, orient_b, 10 + gap, 10),
                )
                yield (
                    _make(shape_a, size_a, orient_a, 10, 10),
                    _make(shape_b, size_b, orient_b, 10 + gap, 10 + gap),
                )


PAIRS = list(_pairs())


def test_l_echantillon_exerce_les_deux_regimes():
    """VERT VACANT : sans paires des DEUX côtés de l'élagage, tout le reste passerait sans voir.

    Deux régimes seulement : le minorant conclut « trop loin » sans toucher aux contours, ou il ne
    conclut pas et les arêtes sont réellement parcourues. C'est ce second cas qui vérifie
    l'équivalence là où elle peut casser.
    """
    seuil = 3.0
    regimes = {"ecarte_par_le_minorant": 0, "contours_parcourus": 0}
    for a, b in PAIRS:
        ax, ay, rca = _socle_bounding_circles(a)[0]
        bx, by, rcb = _socle_bounding_circles(b)[0]
        if math.hypot(bx - ax, by - ay) - rca - rcb > seuil:
            regimes["ecarte_par_le_minorant"] += 1
        else:
            regimes["contours_parcourus"] += 1
    assert all(count > 0 for count in regimes.values()), (
        f"l'échantillon n'exerce pas les deux régimes de l'élagage : {regimes}"
    )


def test_sans_seuil_la_distance_reste_exacte():
    """Propriété 1 : l'élagage par minorant ne déplace pas la valeur d'un iota.

    Une boucle et non un cas pytest par paire : le diagnostic est identique (la liste des
    divergences est dans le message), et 1 274 nœuds de collecte coûtaient plus cher à la suite
    que ce qu'ils apportaient. Même forme que les deux cas de seuil ci-dessous.
    """
    divergences = []
    exercees = 0
    for a, b in PAIRS:
        if a.shape == "round" and b.shape == "round":
            continue  # chemin analytique : aucun contour à élaguer
        exercees += 1
        exact = euclidean_edge_distance(a, b)
        reference = _brute_force_distance(a, b)
        if exact != pytest.approx(reference, abs=1e-12):
            divergences.append(
                (a.shape, b.shape, (a.col, a.row), (b.col, b.row), exact, reference)
            )
    assert exercees, "aucune paire non ronde dans l'échantillon : le cas ne mesure rien"
    assert not divergences, (
        f"{len(divergences)}/{exercees} paires s'écartent de la force brute. "
        f"3 premières : {divergences[:3]}"
    )


@pytest.mark.parametrize("threshold", [0.0, 0.5, 1.5, 3.0, 4.5, 7.5, 12.0, 30.0])
def test_avec_seuil_le_verdict_ne_change_jamais(threshold):
    """Propriété 2 : le booléen `<= seuil` est identique avec et sans ``max_distance``.

    C'est LE contrat exploité par `entries_in_engagement_zone`, son jumeau 3D et le calcul des
    cases interdites du mouvement — les trois seuls sites qui passent ``max_distance``.
    """
    divergences = []
    for a, b in PAIRS:
        exact = euclidean_edge_distance(a, b)
        borne = euclidean_edge_distance(a, b, max_distance=threshold)
        if (exact <= threshold) != (borne <= threshold):
            divergences.append(
                (a.shape, b.shape, (a.col, a.row), (b.col, b.row), exact, borne)
            )
    assert not divergences, (
        f"seuil {threshold} : {len(divergences)}/{len(PAIRS)} paires changent de verdict entre le "
        f"calcul exact et l'encadrement. 3 premières : {divergences[:3]}"
    )


@pytest.mark.parametrize("threshold", [1.5, 4.5, 12.0])
def test_sous_le_seuil_la_valeur_est_exacte(threshold):
    """Le contrat promet l'exactitude TANT QUE le résultat est ``<= max_distance``.

    C'est la promesse de ``min_distance_between_sets``, reprise mot pour mot ; la tenir interdit
    tout raccourci qui rendrait une valeur simplement « assez petite ». Au-dessus du seuil, seule
    la stricte supériorité est due, et c'est elle qui est contrôlée.
    """
    for a, b in PAIRS:
        exact = euclidean_edge_distance(a, b)
        borne = euclidean_edge_distance(a, b, max_distance=threshold)
        if borne <= threshold:
            assert borne == pytest.approx(exact, abs=1e-12), (
                f"{a.shape}/{b.shape} : sous le seuil {threshold}, la valeur bornée {borne} "
                f"n'est pas la distance exacte {exact}"
            )
        else:
            assert exact > threshold, (
                f"{a.shape}/{b.shape} : bornée {borne} > seuil {threshold} alors que l'exacte "
                f"vaut {exact} — l'élagage a écarté une paire réellement en portée"
            )


@pytest.mark.parametrize("orientation", range(6))
def test_le_disque_englobant_contient_vraiment_le_contour(orientation):
    """Le socle de l'optimisation : ``contour ⊆ disque(centre, bounding_radius)``.

    Un rayon trop PETIT rendrait le minorant faux : des socles réellement engagés seraient écartés
    en O(1), et la règle 03.04 rendrait « non engagé » sans que rien ne lève. Contrôlé sur toutes
    les orientations : le rayon vient de ``bounding_radius()``, qui est analytique et ignore
    l'angle, tandis que le contour, lui, est bel et bien tourné.

    Le cas du CARRÉ est celui qui compte : son point le plus éloigné est un COIN, à
    ``demi-côté × √2``. C'est exactement le défaut de broad-phase déjà documenté sur
    ``bounding_radius_norm`` — mesurer ce même rayon ici garde les deux usages solidaires.
    """
    for shape, size, _ in SHAPES:
        if shape == "round":
            continue
        socle = _make(shape, size, orientation, 10, 10)
        cx, cy, rad_circ = _socle_bounding_circles(socle)[0]
        for x, y in _socle_edge_primitives(socle)[0][1]:
            d = math.hypot(x - cx, y - cy)
            assert d <= rad_circ + 1e-9, (
                f"{shape}/{size} orientation {orientation} : sommet à {d} hors du disque "
                f"englobant {rad_circ}"
            )


#: Escouades ÉTALÉES dont une seule figurine s'approche de l'adversaire. C'est la configuration
#: qui exerce le minorant AGRÉGÉ : le disque d'escouade y est bien plus grand que chaque socle, et
#: un rayon sous-estimé écarterait toute la rencontre en O(1) — sans qu'aucun test portant sur une
#: paire isolée ne s'en aperçoive. Vérifié : un rayon d'escouade réduit de 10 % laisse tous les
#: autres cas du fichier au vert.
#: Calibrées : les deux escouades sont DISJOINTES et leur paire la plus proche est à ~1,5 unité,
#: sous les seuils testés, tandis que leurs disques d'escouade (rayon ~13) sont assez larges pour
#: qu'un rabotage de 10 % pousse le minorant agrégé au-dessus de ces mêmes seuils.
ETALEES = [
    ([(10, 10), (14, 10), (18, 10), (22, 10)], [(29, 10), (33, 10), (37, 10), (41, 10)]),
    ([(10, 10), (10, 16), (10, 22), (22, 10)], [(29, 10), (29, 16), (29, 22), (41, 22)]),
]


@pytest.mark.parametrize("centres_a,centres_b", ETALEES)
@pytest.mark.parametrize("threshold", [0.5, 3.0, 9.0, 25.0])
def test_le_minorant_agrege_ne_change_pas_le_verdict(centres_a, centres_b, threshold):
    """Deux escouades étalées : le raccourci d'escouade doit rendre le verdict du calcul complet.

    Le minorant agrégé court-circuite le produit figurine × figurine des DEUX branches, y compris
    la branche ronde qui n'a aucun autre élagage. S'il est trop serré, une escouade réellement en
    portée par une seule de ses figurines est déclarée hors portée.
    """
    for shape, size, orientation in (("round", 6, 0), ("oval", [20, 12], 3)):
        a = _make(shape, size, orientation, centres_a[0][0], centres_a[0][1], centers=centres_a)
        b = _make("round", 6, 0, centres_b[0][0], centres_b[0][1], centers=centres_b)
        exact = euclidean_edge_distance(a, b)
        borne = euclidean_edge_distance(a, b, max_distance=threshold)
        assert (exact <= threshold) == (borne <= threshold), (
            f"{shape} étalée vs escouade, seuil {threshold} : exact {exact}, borné {borne}"
        )
        if borne <= threshold:
            assert borne == pytest.approx(exact, abs=1e-12)


def test_le_disque_d_escouade_contient_toutes_les_figurines():
    """Le minorant AGRÉGÉ repose sur ce disque : trop petit, il écarte une escouade en portée.

    Il est délibérément plus large que le plus petit cercle englobant (barycentre, pas le cercle
    minimal) — donc ce qui est vérifié est l'INCLUSION, la seule propriété dont dépend le minorant.
    """
    from engine.hex_utils import _group_bounding_circle

    centres = [(20, 10), (24, 13), (21, 17), (26, 11)]
    circles = _socle_bounding_circles(_make("round", 6, 0, 20, 10, centers=centres))
    gx, gy, gr = _group_bounding_circle(circles)
    for cx, cy, r in circles:
        assert math.hypot(cx - gx, cy - gy) + r <= gr + 1e-9, (
            f"figurine ({cx:.2f},{cy:.2f}) r={r} hors du disque d'escouade "
            f"({gx:.2f},{gy:.2f}) r={gr}"
        )


#: Escouades dont les figurines sont ÉCHELONNÉES FINEMENT : leurs distances au socle adverse se
#: suivent de moins d'une unité-norme. C'est la seule configuration qui exerce vraiment l'élagage
#: « cette paire ne peut plus améliorer le minimum » — avec une figurine unique, `best` vaut encore
#: l'infini au premier passage et l'élagage ne s'exécute jamais. Vérifié : sans ces cas, un
#: élagage volontairement trop large (`lower >= best - 1.0`) laissait la suite entière au vert.
ECHELONNEES = [
    [(20, 10), (21, 10), (22, 10), (23, 10)],
    [(23, 10), (22, 10), (21, 10), (20, 10)],  # ordre inverse : le meilleur en dernier
    [(20, 10), (20, 11), (21, 10), (21, 11), (22, 12)],
    [(18, 9), (19, 10), (18, 11), (19, 12)],
]


@pytest.mark.parametrize("centres", ECHELONNEES)
@pytest.mark.parametrize("shape,size,orientation", SHAPES)
def test_l_elagage_entre_figurines_garde_la_distance_exacte(centres, shape, size, orientation):
    """L'élagage par minorant ne doit JAMAIS écarter la figurine qui portait le minimum.

    Comparaison à la force brute, sur des figurines dont les distances se tiennent en moins d'une
    unité : c'est là qu'un élagage d'un epsilon trop large change le résultat.
    """
    adverse = _make(shape, size, orientation, 10, 10)
    escouade = _make("round", 6, 0, centres[0][0], centres[0][1], centers=centres)
    assert euclidean_edge_distance(adverse, escouade) == pytest.approx(
        _brute_force_distance(adverse, escouade), abs=1e-12
    )
    assert euclidean_edge_distance(escouade, adverse) == pytest.approx(
        _brute_force_distance(escouade, adverse), abs=1e-12
    )


@pytest.mark.parametrize("threshold", [0.5, 2.0, 4.0, 9.0])
@pytest.mark.parametrize("centres", ECHELONNEES)
def test_l_elagage_entre_figurines_garde_le_verdict(threshold, centres):
    """Même configuration, vue par le chemin borné : le booléen de seuil ne bouge pas."""
    adverse = _make("oval", [20, 12], 3, 10, 10)
    escouade = _make("round", 6, 0, centres[0][0], centres[0][1], centers=centres)
    exact = euclidean_edge_distance(adverse, escouade)
    borne = euclidean_edge_distance(adverse, escouade, max_distance=threshold)
    assert (exact <= threshold) == (borne <= threshold), (
        f"seuil {threshold}, centres {centres} : exact {exact}, borné {borne}"
    )


@pytest.mark.parametrize("portee_subhex", [1, 3, 8, 20])
def test_le_jumeau_de_tir_rend_le_meme_verdict(portee_subhex):
    """JUMEAU tir : ``ranged_edge_distance`` transmettait ``max_distance`` au chemin hex et
    l'IGNORAIT en euclidien — le même défaut, de l'autre côté du miroir tir/mêlée.

    Le contrat vérifié est celui de ``ranged_in_range`` : le booléen « à portée » ne change pas,
    et sous le seuil la distance reste exacte. L'unité est le SUBHEX ici (la conversion ÷1,5 vit
    dans ``ranged_edge_distance``), d'où la portée exprimée telle qu'une arme la porte.
    """
    from engine.combat_utils import ranged_edge_distance, ranged_in_range

    for a, b in PAIRS:
        exact = ranged_edge_distance(a, b, "euclidean")
        borne = ranged_edge_distance(a, b, "euclidean", max_distance=portee_subhex)
        assert (exact <= portee_subhex) == (borne <= portee_subhex), (
            f"{a.shape}/{b.shape} portée {portee_subhex} : exact {exact}, borné {borne}"
        )
        assert ranged_in_range(a, b, portee_subhex, "euclidean") == (exact <= portee_subhex)
        if borne <= portee_subhex:
            assert borne == pytest.approx(exact, abs=1e-12)


def test_les_escouades_multi_figurines_gardent_le_minimum():
    """Une escouade compare CHAQUE figurine : le minimum ne doit pas être perdu par l'élagage.

    Le piège précis : l'élagage saute une paire dont le minorant dépasse le meilleur courant. Si le
    meilleur courant était mal initialisé, la figurine la plus proche — souvent la dernière de la
    liste — serait ignorée. On place donc la figurine proche en DERNIER.
    """
    loin = [(80, 80), (82, 80), (84, 80)]
    proche = loin + [(28, 10)]
    a = _make("oval", [20, 12], 2, 10, 10)
    b_loin = _make("round", 6, 0, 80, 80, centers=loin)
    b_proche = _make("round", 6, 0, 80, 80, centers=proche)
    d_loin = euclidean_edge_distance(a, b_loin)
    d_proche = euclidean_edge_distance(a, b_proche)
    assert d_proche < d_loin, (
        f"la figurine proche (11,10) n'a pas abaissé la distance : {d_proche} vs {d_loin}"
    )
    assert d_proche == pytest.approx(_brute_force_distance(a, b_proche), abs=1e-12)
    # Et le verdict de seuil reste le même par le chemin borné.
    seuil = d_proche + 0.5
    assert euclidean_edge_distance(a, b_proche, max_distance=seuil) <= seuil
