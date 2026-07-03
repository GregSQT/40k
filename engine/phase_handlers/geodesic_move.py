"""Primitives géodésiques euclidiennes partagées MOVE / CHARGE.

La charge est un move (règle 11.04) : elle réutilise exactement le champ géodésique
any-angle du move (Étape 4), seul le budget change (2D6 au lieu de M). Ces deux helpers
sont de la géométrie PURE (aucun état de phase) — ils vivent ici pour être consommés
par ``movement_handlers`` ET ``charge_handlers`` sans duplication ni couplage inter-phase.
"""

from typing import Any, Dict, Set, Tuple

from engine.hex_utils import geodesic_field, round_base_radius_norm


def _inflate_obstacles_by_footprint(
    obstacles: Set[Tuple[int, int]],
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
) -> Set[Tuple[int, int]]:
    """Minkowski discret : cellules-ancre dont l'empreinte toucherait un obstacle.

    Une ancre ``A`` est bloquée ssi ``A + off`` ∈ ``obstacles`` pour un ``off`` de son
    empreinte (``off_even`` si colonne paire, ``off_odd`` si impaire). Équivalent à la
    dilatation ``_placement_bad`` du chemin hex vectorisé, mais sous forme de set pour
    ``geodesic_field`` (clearance=0) : un socle non-rond est représenté par son empreinte
    discrète ORIENTÉE (garde l'orientation, contrairement à un disque circonscrit).
    """
    inflated: Set[Tuple[int, int]] = set()
    for _oc, _orr in obstacles:
        for _dc, _dr in off_even:
            _ac, _ar = _oc - _dc, _orr - _dr
            if (_ac & 1) == 0:
                inflated.add((_ac, _ar))
        for _dc, _dr in off_odd:
            _ac, _ar = _oc - _dc, _orr - _dr
            if (_ac & 1) == 1:
                inflated.add((_ac, _ar))
    return inflated


def _euclidean_move_field(
    start_pos: Tuple[int, int],
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    obstacles_traverse: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    budget_norm: float,
) -> Dict[Tuple[int, int], float]:
    """Champ géodésique euclidien du CENTRE de l'ancre (règle 03.01), budget en unités-norme.

    - Socle **rond** : clearance continue = rayon du socle (option A Minkowski), obstacles bruts.
    - Socle **non-rond** (oval/square) : clearance=0 + obstacles dilatés par l'empreinte discrète
      orientée (``_inflate_obstacles_by_footprint``) → garde l'orientation.
    Round et non-round partagent la MÊME primitive → pool d'ancre (preview) et model pool (commit)
    restent cohérents pour toutes les formes.
    """
    if base_shape == "round":
        return geodesic_field(
            start_pos, board_cols, board_rows, obstacles_traverse,
            budget_norm, round_base_radius_norm(base_size),
        )
    _inflated = _inflate_obstacles_by_footprint(obstacles_traverse, off_even, off_odd)
    _inflated.discard(start_pos)  # start jamais obstacle (geodesic_field lèverait sinon)
    return geodesic_field(start_pos, board_cols, board_rows, _inflated, budget_norm, 0.0)
