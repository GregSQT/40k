"""Contrat de `hex_line_iter` / `hex_line_iter_t` : la séquence rendue doit être STRICTEMENT
celle de l'implémentation d'origine.

Les deux générateurs ont été réécrits pour la performance (2026-09-08) : la déduplication par
``set`` — un hachage et une insertion par cellule — est devenue une comparaison à la cellule
PRÉCÉDENTE. Mesuré avant d'écrire : sur 60 916 lignes (balayage exhaustif 12x12, 40 000 lignes
longues en 220x300, horizontales), le cube-lerp ne produit AUCUNE répétition — le ``set`` ne
retirait jamais rien. La comparaison scalaire est donc conservée par prudence, comme équivalent
exact et non comme simple raccourci : si une répétition survenait, elle serait consécutive.
C'est ce que ce fichier verrouille, faute de quoi une optimisation aurait modifié les lignes de
vue — donc le couvert, donc les jets — sans qu'aucun test ne s'en aperçoive.

`_reference_hex_line_iter` est l'implémentation d'AVANT, recopiée verbatim (dédup par ``set``).
Ne pas l'« améliorer » : sa seule raison d'être est de rester l'ancienne.

La comparaison porte sur la LISTE, pas sur un ensemble : deux séquences de même contenu mais
d'ordre différent donneraient le même couvert par accident sur une ligne et pas sur la suivante,
et les consommateurs de LoS s'arrêtent au PREMIER hex bloquant — l'ordre est le contrat.

Trois angles, parce qu'aucun ne suffit seul :

  1. balayage EXHAUSTIF des lignes courtes (toutes les paires d'un carré 12x12) : c'est là que
     vivent les cas dégénérés — origine == destination, voisins immédiats, lignes d'une seule
     cellule ;
  2. lignes LONGUES tirées au hasard sur un plateau 220x300 (la taille réelle en x5) : c'est là
     que les répétitions apparaissent, et donc là que les deux dédups pourraient diverger ;
  3. les lignes HORIZONTALES et les diagonales de parité, que la docstring de `hex_line_iter`
     désigne comme le cas où le nudge de départage décide seul du résultat.
"""

from __future__ import annotations

import random
from typing import Iterator, List, Set, Tuple

from engine.hex_utils import hex_line_iter, hex_line_iter_t, offset_to_cube

BOARD_COLS, BOARD_ROWS = 220, 300


def _reference_hex_line_iter(
    col1: int, row1: int, col2: int, row2: int
) -> Iterator[Tuple[int, int]]:
    """Implémentation d'origine, RECOPIÉE VERBATIM (dédup par ``set``)."""
    if col1 == col2 and row1 == row2:
        yield (col1, row1)
        return

    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)

    n = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
    seen: Set[Tuple[int, int]] = set()

    ax = x1 + 1e-6
    ay = y1 + 1e-6
    az = z1 - 2e-6
    bx = (x2 + 1e-6) - ax
    by = (y2 + 1e-6) - ay
    bz = (z2 - 2e-6) - az

    for i in range(n + 1):
        t = i / n if n > 0 else 0.0
        fx = ax + bx * t
        fy = ay + by * t
        fz = az + bz * t

        rx = round(fx)
        ry = round(fy)
        rz = round(fz)

        dx = rx - fx
        if dx < 0.0:
            dx = -dx
        dy = ry - fy
        if dy < 0.0:
            dy = -dy
        dz = rz - fz
        if dz < 0.0:
            dz = -dz
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy > dz:
            ry = -rx - rz
        else:
            rz = -rx - ry

        cell = (rx, rz + ((rx - (rx & 1)) >> 1))
        if cell not in seen:
            seen.add(cell)
            yield cell


def _pairs_exhaustive(side: int = 12) -> List[Tuple[int, int, int, int]]:
    return [
        (c1, r1, c2, r2)
        for c1 in range(side)
        for r1 in range(side)
        for c2 in range(side)
        for r2 in range(side)
    ]


def test_short_lines_match_reference_exhaustively():
    """Balayage exhaustif 12x12 : même séquence, même ordre, cas dégénérés compris."""
    checked = 0
    for c1, r1, c2, r2 in _pairs_exhaustive():
        assert list(hex_line_iter(c1, r1, c2, r2)) == list(
            _reference_hex_line_iter(c1, r1, c2, r2)
        ), f"divergence sur ({c1},{r1})->({c2},{r2})"
        checked += 1
    assert checked == 12 ** 4, "le balayage doit être exhaustif, pas énumérer à vide"


def test_long_lines_match_reference():
    """Lignes longues sur un plateau réel : c'est là que les répétitions apparaissent."""
    rng = random.Random(7)
    repeats_seen = 0
    for _ in range(4000):
        c1 = rng.randrange(BOARD_COLS)
        r1 = rng.randrange(BOARD_ROWS)
        c2 = rng.randrange(BOARD_COLS)
        r2 = rng.randrange(BOARD_ROWS)
        got = list(hex_line_iter(c1, r1, c2, r2))
        assert got == list(
            _reference_hex_line_iter(c1, r1, c2, r2)
        ), f"divergence sur ({c1},{r1})->({c2},{r2})"
        # VERT VACANT : une comparaison de listes vides serait verte pour rien. On exige des
        # lignes réellement longues, et on vérifie au passage la propriété qui autorise la
        # dédup scalaire — la séquence ne repasse JAMAIS sur une cellule déjà rendue.
        assert len(got) == len(set(got)), (
            f"cellule répétée sur ({c1},{r1})->({c2},{r2}) : la dédup par cellule précédente "
            f"ne serait plus équivalente à la dédup par ensemble"
        )
        if len(got) > 2:
            repeats_seen += 1
    assert repeats_seen > 100, "échantillon dégénéré : presque aucune ligne longue tirée"


def test_horizontal_and_parity_lines_match_reference():
    """Lignes horizontales et diagonales de parité : le nudge y décide seul du résultat."""
    for row in range(0, 40):
        for c1, c2 in ((0, 39), (39, 0), (5, 6), (6, 5)):
            assert list(hex_line_iter(c1, row, c2, row)) == list(
                _reference_hex_line_iter(c1, row, c2, row)
            ), f"divergence horizontale ligne {row} : ({c1})->({c2})"
    for k in range(1, 40):
        assert list(hex_line_iter(0, 0, k, k)) == list(
            _reference_hex_line_iter(0, 0, k, k)
        ), f"divergence diagonale k={k}"


def test_iter_t_cells_match_iter_and_carry_position():
    """`hex_line_iter_t` rend LES MÊMES cellules que `hex_line_iter`, plus ``t`` croissant.

    Le jumeau porte la même déduplication ; sans ce contrôle, seule une moitié de la règle
    serait verrouillée.
    """
    rng = random.Random(11)
    for _ in range(1500):
        c1 = rng.randrange(BOARD_COLS)
        r1 = rng.randrange(BOARD_ROWS)
        c2 = rng.randrange(BOARD_COLS)
        r2 = rng.randrange(BOARD_ROWS)
        pairs = list(hex_line_iter_t(c1, r1, c2, r2))
        cells = [cell for cell, _t in pairs]
        assert cells == list(
            _reference_hex_line_iter(c1, r1, c2, r2)
        ), f"divergence iter_t sur ({c1},{r1})->({c2},{r2})"
        ts = [t for _cell, t in pairs]
        assert ts == sorted(ts), "t doit rester croissant le long de la ligne"
        assert 0.0 <= ts[0] and ts[-1] <= 1.0
