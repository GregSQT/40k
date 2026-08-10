#!/usr/bin/env python3
"""Équivalence STRICTE entre `hex_utils.offset_slice_windows` et l'indexation naïve.

CE QUE CE FICHIER VERROUILLE (V11 §0.22, T1). Le motif « boucler sur les offsets d'une empreinte
et combiner deux tranches décalées » vivait en SIX copies, chacune recalculant ses quatre bornes
à la main, deux d'entre elles fenêtrées par des mécanismes différents (clamp de la destination
contre clamp de la source), et AUCUN test ne les reliait. Un bug de bornes corrigé dans l'une ne
l'était dans aucune autre — et un bug de bornes ne lève rien : il rend un masque faux, donc un
pool de déplacement ou de déploiement faux, silencieusement.

La référence est l'indexation naïve case par case : lente, évidemment juste, et indépendante de
toute astuce de slice. La comparaison est exhaustive sur de petites grilles (toutes les cases,
tous les décalages utiles, y compris ceux qui sortent entièrement du plateau) plutôt que
statistique — c'est un calcul de bornes, ses défauts vivent exactement aux bords.
"""

import numpy as np
import pytest

from engine.hex_utils import offset_slice_windows

#: Décalages couverts : au-delà de la taille de la grille dans les deux sens, donc les fenêtres
#: entièrement hors plateau (attendu : `None`) sont testées elles aussi.
_OFFSETS = [(dc, dr) for dc in range(-4, 5) for dr in range(-4, 5)]
_SHAPES = ((1, 1), (1, 3), (3, 1), (3, 3), (5, 4), (4, 7))


def _naive_dilate(src, dc, dr):
    """`out[c, r] = src[c+dc, r+dr]` si dans le plateau, sinon False. Référence du sens dilate."""
    cols, rows = src.shape
    out = np.zeros_like(src)
    for c in range(cols):
        for r in range(rows):
            sc, sr = c + dc, r + dr
            if 0 <= sc < cols and 0 <= sr < rows:
                out[c, r] = src[sc, sr]
    return out


def _naive_spread(src, dc, dr):
    """`out[c+dc, r+dr] |= src[c, r]`. Référence du sens propagation."""
    cols, rows = src.shape
    out = np.zeros_like(src)
    for c in range(cols):
        for r in range(rows):
            dcc, drr = c + dc, r + dr
            if 0 <= dcc < cols and 0 <= drr < rows and src[c, r]:
                out[dcc, drr] = True
    return out


def _by_windows(src, dc, dr, *, spread, bbox=None, clamp="dst"):
    """La même chose via le helper — exactement comme les sites de production l'appellent."""
    cols, rows = src.shape
    out = np.zeros_like(src)
    windows = offset_slice_windows(
        -dc if spread else dc, -dr if spread else dr, cols, rows, bbox=bbox, clamp=clamp
    )
    if windows is None:
        return out
    (sc0, sc1, sr0, sr1), (dc0, dc1, dr0, dr1) = windows
    out[dc0:dc1, dr0:dr1] |= src[sc0:sc1, sr0:sr1]
    return out


def _grid(shape, seed):
    """Grille aléatoire dont on GARANTIT qu'elle porte du vrai ET du faux.

    Une grille tirée au sort peut sortir toute fausse (constaté sur 1×3) : la comparaison serait
    alors verte en ne comparant que des zéros. Les deux coins sont donc posés, pas espérés — et le
    tirage reste sur un `default_rng(seed)` explicite, jamais sur `hash()`, dont la valeur change
    d'un processus à l'autre (`PYTHONHASHSEED`) et rendrait le test non reproductible.
    """
    grid = np.random.default_rng(seed).random(shape) < 0.5
    grid[0, 0] = True
    if grid.size > 1:
        # Sur une grille d'UNE case, `grid[-1, -1]` est `grid[0, 0]` : y écrire False effacerait
        # le vrai qu'on vient de poser et la grille repartirait vide.
        grid[-1, -1] = False
    return grid


@pytest.mark.parametrize("shape", _SHAPES)
def test_dilate_matches_naive_indexing_for_every_offset(shape):
    src = _grid(shape, seed=shape[0] * 100 + shape[1])
    assert src.any(), "grille vide : le test ne regarderait rien (vert vacant)"
    for dc, dr in _OFFSETS:
        attendu = _naive_dilate(src, dc, dr)
        obtenu = _by_windows(src, dc, dr, spread=False)
        assert np.array_equal(obtenu, attendu), (
            f"dilate {shape} offset ({dc},{dr}) : {int((obtenu != attendu).sum())} cases divergentes"
        )


@pytest.mark.parametrize("shape", _SHAPES)
def test_spread_matches_naive_indexing_for_every_offset(shape):
    src = _grid(shape, seed=shape[0] * 100 + shape[1] + 1)
    assert src.any(), "grille vide : le test ne regarderait rien (vert vacant)"
    for dc, dr in _OFFSETS:
        attendu = _naive_spread(src, dc, dr)
        obtenu = _by_windows(src, dc, dr, spread=True)
        assert np.array_equal(obtenu, attendu), (
            f"spread {shape} offset ({dc},{dr}) : {int((obtenu != attendu).sum())} cases divergentes"
        )


@pytest.mark.parametrize("shape", ((5, 4), (4, 7)))
def test_clamping_the_destination_writes_inside_the_window_and_nothing_else(shape):
    """`clamp="dst"` : la sortie est le plein-board MASQUÉ à la fenêtre, ni plus ni moins.

    C'est la propriété qui rend L_bbox exacte (pool identique au plein-board) : borner la sortie
    utile ne doit rien changer DANS la fenêtre, et ne rien écrire dehors.
    """
    cols, rows = shape
    src = _grid(shape, seed=7)
    bbox = (1, max(2, cols - 1), 1, max(2, rows - 1))
    fenetre = np.zeros(shape, dtype=bool)
    fenetre[bbox[0]:bbox[1], bbox[2]:bbox[3]] = True
    for dc, dr in _OFFSETS:
        plein = _naive_dilate(src, dc, dr)
        borne = _by_windows(src, dc, dr, spread=False, bbox=bbox, clamp="dst")
        assert np.array_equal(borne, plein & fenetre), (
            f"clamp dst {shape} offset ({dc},{dr}) : la sortie bornee n'est pas le plein-board "
            f"masque a la fenetre"
        )


@pytest.mark.parametrize("shape", ((5, 4), (4, 7)))
def test_clamping_the_source_reads_inside_the_window_and_nothing_else(shape):
    """`clamp="src"` : équivaut à effacer la source hors fenêtre, puis propager sans borne.

    C'est l'hypothèse sous laquelle l'union d'empreintes est fenêtrée en production (« toutes les
    sources non nulles sont dans la bbox ») : la formuler comme une égalité la rend vérifiable.
    """
    cols, rows = shape
    src = _grid(shape, seed=11)
    bbox = (1, max(2, cols - 1), 1, max(2, rows - 1))
    src_borne = np.zeros(shape, dtype=bool)
    src_borne[bbox[0]:bbox[1], bbox[2]:bbox[3]] = src[bbox[0]:bbox[1], bbox[2]:bbox[3]]
    for dc, dr in _OFFSETS:
        attendu = _naive_spread(src_borne, dc, dr)
        obtenu = _by_windows(src, dc, dr, spread=True, bbox=bbox, clamp="src")
        assert np.array_equal(obtenu, attendu), (
            f"clamp src {shape} offset ({dc},{dr}) : lire dans la fenetre ne revient pas a "
            f"propager une source effacee hors fenetre"
        )


def test_a_fully_out_of_board_offset_yields_no_window():
    """Le `continue` que les six copies écrivaient : aucune case commune → pas de fenêtre."""
    assert offset_slice_windows(9, 0, 5, 5) is None
    assert offset_slice_windows(0, -9, 5, 5) is None
    assert offset_slice_windows(0, 0, 5, 5) is not None


def test_an_empty_bbox_yields_no_window():
    """Fenêtre vide (bornes croisées) : rien à écrire, et surtout pas un slice négatif."""
    assert offset_slice_windows(0, 0, 5, 5, bbox=(3, 3, 0, 5)) is None
    assert offset_slice_windows(0, 0, 5, 5, bbox=(0, 5, 4, 2)) is None


def test_an_unknown_clamp_side_raises():
    """Un côté de clamp inconnu est une faute d'appel, pas une valeur à interpréter."""
    with pytest.raises(ValueError, match="clamp"):
        offset_slice_windows(0, 0, 5, 5, bbox=(0, 5, 0, 5), clamp="both")
