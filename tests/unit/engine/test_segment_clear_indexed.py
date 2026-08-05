"""Verrou d'equivalence de `_segment_clear_indexed` — l'index spatial ne doit JAMAIS rendre un
verdict different du balayage de TOUS les obstacles.

Cette primitive n'avait aucun test. Elle porte pourtant la regle 03 : c'est elle qui decide si un
socle peut transiter d'un point a un autre, donc elle borne le move (09), la charge (11.04) et le
pile-in / la consolidation (12.03 / 12.08) via `geodesic_field`. Un faux « degage » ouvre un
trajet a travers un mur ; un faux « bloque » refuse une charge legale.

Le risque est structurel, pas theorique : la fonction combine trois accelerations qui peuvent
chacune sauter un obstacle — l'inscription de chaque obstacle dans ses 9 buckets
(`_build_obstacle_index`), le DDA qui ne visite que les buckets traverses, et le rejet rapide par
distance point-segment. Le test **ignore ces trois etages** et compare a la definition : « un
segment est degage ssi il ne touche AUCUN obstacle ».

Le test de bucket est par ailleurs ECRIT DEUX FOIS dans la fonction (bucket de depart, puis
boucle DDA) pour supprimer un appel de closure par bucket visite. Ces tests sont ce qui rattrape
une divergence entre les deux copies : plusieurs cas ci-dessous touchent un obstacle situe dans
le bucket de DEPART, d'autres un obstacle atteint seulement en cours de DDA.
"""

from __future__ import annotations

import math
from typing import List, Set, Tuple

import pytest

from engine.hex_utils import (
    _build_obstacle_index,
    _hex_center,
    _hex_corners_at,
    _obstacle_bucket_size,
    _segment_clear_indexed,
    _segment_hits_hex,
)

#: Clearances de PRODUCTION. `round_base_radius_norm` rend 0,75 a x1 (socle normalise) et 9 a
#: 22,5 a x5 pour les datasheets 25 a 60 mm. Le bucket de l'index vaut `max(2, 1 + clearance)`,
#: donc 2,0 a x1 mais 10 a 23,5 a x5 : le DDA n'y visite pas du tout le meme nombre de buckets.
#: Ne tester qu'a 0,0 laisserait tout le regime x5 non couvert.
CLEARANCES = [0.0, 0.75, 9.0, 12.0, 18.75]


def _brute_force_clear(
    ax: float, ay: float, bx: float, by: float,
    obstacles: Set[Tuple[int, int]], clearance: float,
) -> bool:
    """Definition de reference : aucun index, aucun DDA, aucun rejet rapide.

    Balaye TOUS les obstacles avec la meme primitive de contact que la version indexee
    (`_segment_hits_hex`) — c'est bien l'INDEXATION qu'on verrouille, pas la geometrie du contact.
    """
    for (wc, wr) in obstacles:
        ocx, ocy = _hex_center(wc, wr)
        if _segment_hits_hex(ax, ay, bx, by, _hex_corners_at(ocx, ocy), ocx, ocy, clearance):
            return False
    return True


def _indexed_clear(
    ax: float, ay: float, bx: float, by: float,
    obstacles: Set[Tuple[int, int]], clearance: float,
) -> bool:
    bs = _obstacle_bucket_size(clearance)
    return _segment_clear_indexed(ax, ay, bx, by, bs, _build_obstacle_index(obstacles, bs), clearance)


def _segments_across(obstacles: Set[Tuple[int, int]]) -> List[Tuple[float, float, float, float]]:
    """Segments couvrant les cas que le DDA distingue.

    Construits, pas tires au hasard : horizontaux, verticaux, diagonaux dans les quatre sens,
    degeneres (extremites confondues, donc bucket unique), et longs (des dizaines de buckets).
    Un segment purement aleatoire raterait justement les cas ou `dx == 0` / `dy == 0` mettent
    `t_delta` a l'infini.
    """
    segs: List[Tuple[float, float, float, float]] = []
    anchors = [(20, 20), (60, 45), (95, 70), (40, 90)]
    for (c0, r0) in anchors:
        x0, y0 = _hex_center(c0, r0)
        for (dc, dr) in ((30, 0), (0, 30), (25, 25), (-25, 25), (25, -25), (-30, -30),
                         (60, 5), (5, 60), (0, 0), (1, 0)):
            x1, y1 = _hex_center(c0 + dc, r0 + dr)
            segs.append((x0, y0, x1, y1))
    # Segments qui rasent un obstacle : c'est la ou le rejet rapide par distance point-segment
    # peut ecarter a tort. Vises sur les obstacles eux-memes, decales d'un demi-hex.
    for (wc, wr) in sorted(obstacles)[:12]:
        ox, oy = _hex_center(wc, wr)
        segs.append((ox - 12.0, oy - 0.4, ox + 12.0, oy + 0.4))
        segs.append((ox - 0.4, oy - 12.0, ox + 0.4, oy + 12.0))
    return segs


def _terrain() -> Set[Tuple[int, int]]:
    """Ligne de mur percee de deux ouvertures + ruines rectangulaires + obstacles isoles."""
    cells: Set[Tuple[int, int]] = set()
    for r in range(10, 100):
        if 30 <= r < 36 or 60 <= r < 66:
            continue
        cells.add((70, r))
    for rc in (25, 50, 100):
        for rr in (30, 65):
            for dc in range(4):
                for dr in range(4):
                    cells.add((rc + dc, rr + dr))
    cells |= {(15, 15), (45, 88), (110, 20), (88, 55)}
    return cells


TERRAIN = _terrain()


def test_the_fixture_produces_both_verdicts() -> None:
    """VERT VACANT : si tous les segments etaient degages (ou tous bloques), l'equivalence
    ci-dessous serait satisfaite par une fonction constante. On exige les deux verdicts."""
    verdicts = {
        _brute_force_clear(*seg, TERRAIN, 0.75) for seg in _segments_across(TERRAIN)
    }
    assert verdicts == {True, False}, f"la fixture ne produit que {verdicts}"


@pytest.mark.parametrize("clearance", CLEARANCES)
def test_indexed_matches_brute_force(clearance: float) -> None:
    """L'index + DDA + rejet rapide rendent EXACTEMENT le verdict du balayage complet."""
    for seg in _segments_across(TERRAIN):
        assert _indexed_clear(*seg, TERRAIN, clearance) == _brute_force_clear(
            *seg, TERRAIN, clearance
        ), f"desaccord sur {seg} a clearance {clearance}"


@pytest.mark.parametrize("clearance", CLEARANCES)
def test_obstacle_in_the_starting_bucket_blocks(clearance: float) -> None:
    """Copie n°1 du test de bucket : l'obstacle est SUR le depart du segment.

    Le segment ne quitte pas son bucket, donc seule la copie hors boucle peut le voir. Si elle
    diverge de celle du DDA, ce test tombe.
    """
    ox, oy = _hex_center(50, 50)
    obstacles = {(50, 50)}
    assert _indexed_clear(ox - 0.2, oy, ox + 0.2, oy, obstacles, clearance) is False


@pytest.mark.parametrize("clearance", CLEARANCES)
def test_obstacle_reached_only_by_the_dda_blocks(clearance: float) -> None:
    """Copie n°2 : l'obstacle est LOIN du depart, atteint seulement en avancant dans le DDA.

    Premisse verifiee dans le test : le depart est a plus d'un bucket de l'obstacle, donc la
    copie hors boucle ne peut pas le voir.
    """
    bs = _obstacle_bucket_size(clearance)
    sx, sy = _hex_center(20, 50)
    ox, oy = _hex_center(90, 50)
    assert abs(ox - sx) > 3.0 * bs, "premisse : l'obstacle doit etre hors du bucket de depart"
    assert _indexed_clear(sx, sy, ox, oy, {(90, 50)}, clearance) is False


@pytest.mark.parametrize("clearance", CLEARANCES)
def test_a_clear_corridor_stays_clear(clearance: float) -> None:
    """Contre-epreuve : sans obstacle sur le trajet, le verdict est « degage ».

    Sans elle, un `return False` inconditionnel passerait les trois tests precedents.
    """
    sx, sy = _hex_center(20, 50)
    ex, ey = _hex_center(60, 50)
    assert _indexed_clear(sx, sy, ex, ey, {(200, 200)}, clearance) is True


def test_an_empty_index_is_always_clear() -> None:
    """Aucun obstacle → sortie immediate, quel que soit le segment."""
    sx, sy = _hex_center(0, 0)
    ex, ey = _hex_center(120, 100)
    assert _indexed_clear(sx, sy, ex, ey, set(), 9.0) is True


@pytest.mark.parametrize("clearance", CLEARANCES)
def test_a_degenerate_segment_matches_brute_force(clearance: float) -> None:
    """Extremites confondues (dx == dy == 0) : `t_delta` vaut l'infini, le DDA ne doit pas
    boucler et le verdict doit rester celui du balayage complet."""
    for cell in ((50, 50), (70, 20), (200, 200)):
        px, py = _hex_center(*cell)
        assert _indexed_clear(px, py, px, py, TERRAIN, clearance) == _brute_force_clear(
            px, py, px, py, TERRAIN, clearance
        )


def test_the_opening_admits_the_socle_that_fits_and_refuses_the_one_that_does_not() -> None:
    """Geometrie CONSTRUITE : la colonne 70 est un mur perce sur les lignes 30-35.

    L'ouverture fait 6 lignes, soit 6 x sqrt(3) ~ 10,4 unites. Un socle de rayon 0,75 y passe ;
    un socle de rayon 9 (diametre 18) n'y entre pas. C'est la CLEARANCE qui tranche, et les deux
    verdicts sont exiges : un index qui bloquerait tout, ou qui laisserait tout passer, tombe.
    Chaque verdict est en plus recoupe avec le balayage complet — le test ne se contente pas de
    l'opinion de l'index sur lui-meme.
    """
    gap_rows = 6
    assert gap_rows * math.sqrt(3.0) < 2.0 * 9.0, "premisse : le gros socle ne doit PAS entrer"
    assert gap_rows * math.sqrt(3.0) > 2.0 * 0.75, "premisse : le petit socle doit entrer"

    through_gap = (*_hex_center(60, 33), *_hex_center(80, 33))
    through_wall = (*_hex_center(60, 13), *_hex_center(80, 13))

    for clearance, expected_gap in ((0.75, True), (9.0, False)):
        assert _indexed_clear(*through_gap, TERRAIN, clearance) is expected_gap
        assert _brute_force_clear(*through_gap, TERRAIN, clearance) is expected_gap
        assert _indexed_clear(*through_wall, TERRAIN, clearance) is False
        assert _brute_force_clear(*through_wall, TERRAIN, clearance) is False


def test_the_field_is_unchanged_by_the_inlining() -> None:
    """`geodesic_field` complet : le champ doit etre identique a celui de la version closure.

    La reference est recalculee ici par une copie LOCALE de la fonction telle qu'elle etait avant
    le depliage (closure `_hit`) : le verrou ne compare pas a une constante figee dans le test,
    qui deviendrait fausse au premier changement legitime de geometrie.
    """
    from engine import hex_utils as hu

    def _seg_with_closure(ax, ay, bx, by, bucket_size, idx, clearance):
        if not idx:
            return True
        gx, gy = int(ax // bucket_size), int(ay // bucket_size)
        gxe, gye = int(bx // bucket_size), int(by // bucket_size)
        _reach = hu._HEX_CIRCUMRADIUS + (clearance if clearance > 0.0 else 0.0) + hu._SEG_TOL
        _reach_sq = _reach * _reach

        def _hit(bgx, bgy):
            bucket = idx.get((bgx, bgy))
            if bucket:
                for (ocx, ocy) in bucket:
                    if hu._point_segment_dist_sq(ocx, ocy, ax, ay, bx, by) > _reach_sq:
                        continue
                    if hu._segment_hits_hex(
                        ax, ay, bx, by, hu._hex_corners_at(ocx, ocy), ocx, ocy, clearance
                    ):
                        return True
            return False

        if _hit(gx, gy):
            return False
        if gx == gxe and gy == gye:
            return True
        dx, dy = bx - ax, by - ay
        step_x = 1 if dx > 0 else -1
        step_y = 1 if dy > 0 else -1
        t_delta_x = bucket_size / abs(dx) if dx != 0 else math.inf
        t_delta_y = bucket_size / abs(dy) if dy != 0 else math.inf
        if dx > 0:
            t_max_x = ((gx + 1) * bucket_size - ax) / dx
        elif dx < 0:
            t_max_x = (gx * bucket_size - ax) / dx
        else:
            t_max_x = math.inf
        if dy > 0:
            t_max_y = ((gy + 1) * bucket_size - ay) / dy
        elif dy < 0:
            t_max_y = (gy * bucket_size - ay) / dy
        else:
            t_max_y = math.inf
        while True:
            if t_max_x < t_max_y:
                if t_max_x > 1.0:
                    break
                gx += step_x
                t_max_x += t_delta_x
            else:
                if t_max_y > 1.0:
                    break
                gy += step_y
                t_max_y += t_delta_y
            if _hit(gx, gy):
                return False
            if gx == gxe and gy == gye:
                break
        return True

    start = (30, 50)
    obstacles = TERRAIN - {start}
    for clearance, budget in ((0.75, 40.0), (9.0, 60.0)):
        inlined = hu.geodesic_field(start, 130, 110, obstacles, budget, clearance)
        _real = hu._segment_clear_indexed
        hu._segment_clear_indexed = _seg_with_closure
        try:
            reference = hu.geodesic_field(start, 130, 110, obstacles, budget, clearance)
        finally:
            hu._segment_clear_indexed = _real
        assert reference, "premisse : le champ de reference ne doit pas etre vide"
        assert inlined == reference, f"champ different a clearance {clearance}"
