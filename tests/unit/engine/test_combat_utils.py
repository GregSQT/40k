import pytest

from engine.combat_utils import get_unit_coordinates, hex_index_table


def test_get_unit_coordinates_normalizes_numeric_strings() -> None:
    unit = {"col": "4.0", "row": "2"}
    assert get_unit_coordinates(unit) == (4, 2)


def test_get_unit_coordinates_raises_key_error_when_missing_row() -> None:
    unit = {"col": 4}
    with pytest.raises(KeyError):
        get_unit_coordinates(unit)


# ─────────────────────────────────────────────────────────────────────────────
# HexIndexTable.bitmap_in_bounds — la conversion obstacles -> carte d'octets
#
# Mesuré le 2026-09-08 sur les 16 ensembles de transit distincts que produit réellement
# `scripts/bench_env_step.py` : 0 coordonnée fractionnaire, 0 coordonnée hors plateau, bornes
# (0,0)–(219,299). Les trois branches défensives de cette conversion ne sont donc JAMAIS
# exercées par la production — seuls ces tests les tiennent. Elles ne sont pas décoratives :
# l'index `col * board_rows + row` fait collisionner une coordonnée fractionnaire ou hors
# plateau avec une case parfaitement valide, à l'autre bout du terrain.
# ─────────────────────────────────────────────────────────────────────────────

BM_COLS, BM_ROWS = 220, 300


def _marked(cells) -> set:
    """Cases que la carte déclare bloquées, rendues en coordonnées."""
    blocked = hex_index_table(BM_COLS, BM_ROWS).bitmap_in_bounds(cells)
    return {blocked.table.cells[i] for i, v in enumerate(blocked.data) if v}


def test_bitmap_marks_exactly_the_integer_cells() -> None:
    """Cas nominal : une case entière du plateau est marquée, et elle seule."""
    assert _marked({(5, 3), (219, 299), (0, 0)}) == {(5, 3), (219, 299), (0, 0)}


def test_bitmap_marks_integer_valued_coordinates_whatever_their_type() -> None:
    """`(62.0, 80.0)` et son équivalent numpy bloquent, exactement comme `(62, 80)`.

    Le BFS d'origine testait `(62, 80) in obstacles` : une paire de VALEUR entière y était égale
    quel qu'en soit le type. Filtrer sur `type(...) is int` rendrait ces écritures inertes, donc
    rouvrirait un passage que l'appelant a fermé.
    """
    import numpy as np

    assert _marked({(62.0, 80.0)}) == {(62, 80)}
    assert _marked({(np.int64(62), np.int64(80))}) == {(62, 80)}


def test_bitmap_ignores_fractional_coordinates() -> None:
    """Un obstacle fractionnaire est inerte — surtout sur la case dont il porte l'INDEX.

    `62.7 * 300 + 80` vaut exactement `18890.0`, l'index de `(62, 290)`. Sans le contrôle de
    valeur entière, cet obstacle fermerait une case située 210 lignes plus bas.
    """
    assert _marked({(62.7, 80)}) == set()
    assert _marked({(62, 290)}) == {(62, 290)}  # contrôle de dents : la case EST marquable


def test_bitmap_ignores_cells_outside_the_board() -> None:
    """Un obstacle hors plateau est ignoré, jamais replié sur une case joignable.

    `(5, -1)` porte l'index de `(4, 299)` à 220x300 : sans filtre de bornes, il fermerait une
    case de l'autre bord du plateau.
    """
    assert _marked({(5, -1), (-1, 5), (BM_COLS, 5), (5, BM_ROWS)}) == set()
    assert _marked({(4, 299)}) == {(4, 299)}  # contrôle de dents


def test_bitmap_carries_its_own_table_and_is_immutable() -> None:
    """La carte porte la table qui lui donne son sens, et ne peut pas être marchée en place."""
    table = hex_index_table(44, 60)
    blocked = table.bitmap_in_bounds({(5, 3)})
    assert blocked.table is table
    assert len(blocked.data) == 44 * 60
    with pytest.raises(TypeError):
        blocked.data[0] = 1  # type: ignore[index]
